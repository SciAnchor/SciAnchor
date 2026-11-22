# -*- coding: utf-8 -*-
"""全链路 PDF 下载验收命令。"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from pathlib import Path
from typing import Any

from paperfetch.observability import write_output

from paperfetch.core.contracts_v1 import (
    ArtifactRef,
    BusinessStatus,
    CommandItem,
    CommandResult,
    CommandSummary,
    EntityRef,
    ErrorInfo,
)

from paperfetch.cli.projections import validation_download_fact
from paperfetch.downloaders.validation import ValidationGate, run_download_validation


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _validation_item(
    entry: dict[str, Any], round_index: int, report_path: Path
) -> CommandItem:
    passed = bool(entry.get("passed"))
    actual = str(entry.get("actual") or "download_validation_failed")
    artifacts: list[ArtifactRef] = []
    path = entry.get("pdf_path")
    if passed and entry.get("download_status") == "downloaded" and path:
        artifacts.append(
            ArtifactRef(
                kind="pdf",
                path=str(path),
                size_bytes=entry.get("pdf_size_bytes"),
                sha256=entry.get("pdf_sha256"),
            )
        )
    data = {
        key: entry.get(key)
        for key in (
            "sample_id",
            "doi",
            "arxiv_id",
            "publisher",
            "expected_status",
            "actual",
            "download_status",
            "successful_route",
            "identity_verified",
            "identity_status",
        )
        if entry.get(key) is not None
    }
    data["download"] = validation_download_fact(entry)
    error = (
        None
        if passed
        else ErrorInfo(
            code="download_validation_sample_failed",
            error_class=actual,
            stage="pdf_validation",
            retryable=actual
            in {"network_error", "timeout", "connect_error", "publisher_challenge"},
            message=f"下载验收样本未满足门禁：{actual}",
            remediation="读取 audit_ref 中的验证报告，修复对应下载方式后重试",
            audit_ref=str(report_path),
        )
    )
    return CommandItem(
        entity=EntityRef(
            type="download_validation_sample",
            id=f"round-{round_index}:{entry.get('sample_id') or 'unknown'}",
        ),
        status=BusinessStatus.COMPLETED if passed else BusinessStatus.FAILED,
        artifacts=artifacts,
        data=data,
        error=error,
        audit_ref=str(report_path),
    )


def project_download_validation_result(
    report: dict[str, Any], *, output_dir: str, elapsed_ms: int
) -> CommandResult:
    """把详细全路由验收报告投影为统一 Agent 业务结果。"""
    report_path = Path(output_dir).resolve() / "validation_report.json"
    items = [
        _validation_item(entry, int(round_report.get("round") or 0), report_path)
        for round_report in report.get("round_reports") or []
        for entry in round_report.get("entries") or []
    ]
    failed = sum(item.status == BusinessStatus.FAILED.value for item in items)
    validation_ok = bool(report.get("validation_ok"))
    error = (
        None
        if validation_ok
        else ErrorInfo(
            code="download_validation_gate_failed",
            error_class="quality_gate_failed",
            stage="download_validation",
            retryable=True,
            message=f"下载产品验收未通过，共 {len(report.get('gate_failures') or [])} 项门禁失败",
            remediation="读取 audit_ref 中的验证报告，修复失败样本或性能门禁后重试",
            audit_ref=str(report_path),
        )
    )
    payload = report_path.read_bytes() if report_path.is_file() else None
    performance = report.get("performance")
    if not isinstance(performance, dict):
        performance = {}
    return CommandResult(
        command="download.validate",
        run_id=uuid.uuid4().hex,
        status=BusinessStatus.COMPLETED if validation_ok else BusinessStatus.FAILED,
        summary=CommandSummary(
            selected=len(items),
            succeeded=len(items) - failed,
            failed=failed,
            elapsed_ms=elapsed_ms,
        ),
        items=items,
        artifacts=[
            ArtifactRef(
                kind="validation_report",
                path=str(report_path),
                size_bytes=len(payload) if payload is not None else None,
                sha256=hashlib.sha256(payload).hexdigest()
                if payload is not None
                else None,
            )
        ],
        metrics={
            "success_rate": float(report.get("success_rate") or 0.0),
            "phase1_p50_ms": int(performance.get("phase1_p50_ms") or 0),
            "phase1_p95_ms": int(performance.get("phase1_p95_ms") or 0),
            "phase1_max_ms": int(performance.get("phase1_max_ms") or 0),
        },
        error=error,
        audit_ref=str(report_path),
    )


def run_download_validation_command(parsed_args) -> int:
    """运行固定样本验收并按门禁返回退出码。"""
    started = time.perf_counter()
    report = asyncio.run(
        run_download_validation(
            suite_path=parsed_args.suite,
            profile=parsed_args.profile,
            rounds=parsed_args.rounds,
            output_dir=parsed_args.output_dir,
            publishers=_csv(parsed_args.publisher),
            sample_ids=_csv(parsed_args.sample),
            gate=ValidationGate(
                minimum_success_rate=parsed_args.minimum_success_rate,
                maximum_phase1_p95_ms=parsed_args.maximum_phase1_p95_ms,
                maximum_phase1_paper_ms=parsed_args.maximum_phase1_paper_ms,
            ),
        )
    )
    result = project_download_validation_result(
        report,
        output_dir=parsed_args.output_dir,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    if parsed_args.output_format == "json":
        write_output(result.model_dump(mode="json"), pretty=True)
    else:
        write_output(
            "下载验收："
            f"status={result.status}，通过={result.summary.succeeded}，"
            f"失败={result.summary.failed}，"
            f"成功率={result.metrics['success_rate']:.2%}，"
            f"Phase1 p95={result.metrics['phase1_p95_ms']}ms"
        )
        if result.error:
            write_output(f"- 门禁失败：{result.error.message}")
    return 0 if result.status == "completed" else 2
