# -*- coding: utf-8 -*-
"""SPC PDF 下载全链路无人值守验收器。"""

from __future__ import annotations

import json
from paperfetch.observability import get_event_logger
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from paperfetch.core.models import FulltextStatus, PaperRecord
from paperfetch.downloaders.pipeline.manager import PDFDownloadManager
from paperfetch.downloaders.pipeline.report import build_download_run_report

logger = get_event_logger("paperfetch.downloaders.validation")

REPORT_VERSION = "paperfetch.download-validation.v1"
DEFAULT_SUITE_PATH = Path(__file__).with_name("download_validation_samples.json")


@dataclass(frozen=True)
class ValidationGate:
    """验收门禁配置。"""

    minimum_success_rate: float = 1.0
    maximum_phase1_p95_ms: int = 12_500
    maximum_phase1_paper_ms: int = 47_000
    require_identity_verification: bool = True
    require_zero_duplicate_transfers: bool = True


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1)))
    )
    return int(ordered[index])


def _load_suite(path: Optional[str]) -> dict[str, Any]:
    suite_path = Path(path) if path else DEFAULT_SUITE_PATH
    payload = json.loads(suite_path.read_text(encoding="utf-8"))
    if payload.get("suite_version") != "paperfetch.download-suite.v1":
        raise ValueError("下载验收样本必须使用 paperfetch.download-suite.v1")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("下载验收样本不能为空")
    return payload


def _select_samples(
    suite: dict[str, Any],
    *,
    profile: str,
    publishers: Optional[Iterable[str]],
    sample_ids: Optional[Iterable[str]],
) -> list[dict[str, Any]]:
    profiles = suite.get("profiles") or {}
    profile_ids = profiles.get(profile)
    if profile_ids is None:
        raise ValueError(f"下载验收 profile 不存在: {profile}")
    allowed_ids = {str(item) for item in profile_ids}
    publisher_filter = {
        item.strip().lower() for item in publishers or [] if item.strip()
    }
    sample_filter = {item.strip() for item in sample_ids or [] if item.strip()}
    selected = []
    for sample in suite["samples"]:
        sample_id = str(sample.get("id") or "")
        publisher = str(sample.get("publisher") or "unknown").lower()
        if sample_id not in allowed_ids:
            continue
        if publisher_filter and publisher not in publisher_filter:
            continue
        if sample_filter and sample_id not in sample_filter:
            continue
        if not sample.get("doi") and not sample.get("arxiv_id"):
            raise ValueError(f"验收样本缺少 DOI/arXiv ID: {sample_id}")
        selected.append(sample)
    if not selected:
        raise ValueError("筛选后没有可执行的下载验收样本")
    return selected


def _paper_from_sample(sample: dict[str, Any], round_index: int) -> PaperRecord:
    doi = sample.get("doi")
    arxiv_id = sample.get("arxiv_id")
    title = str(sample.get("title") or doi or arxiv_id)
    status = FulltextStatus(
        oa_status=str(sample.get("access") or "unknown"),
        pdf_url=sample.get("pdf_url"),
        pdf_source=sample.get("pdf_source"),
        pdf_candidates=list(sample.get("pdf_candidates") or []),
    )
    return PaperRecord(
        paper_id=f"validation:{round_index}:{sample['id']}",
        doi=doi,
        arxiv_id=arxiv_id,
        title=title,
        publisher=sample.get("publisher"),
        journal=sample.get("journal"),
        venue=sample.get("venue"),
        document_type=sample.get("document_type"),
        fulltext_status=status,
    )


def _expected_result(
    sample: dict[str, Any],
    paper: PaperRecord,
    *,
    require_identity_verification: bool,
) -> tuple[bool, str]:
    status = paper.fulltext_status
    expected_status = str(sample.get("expected_status") or "downloaded")
    if expected_status == "downloaded":
        if status.download_status != "downloaded":
            return False, status.failure_taxonomy or "download_failed"
        if require_identity_verification and not status.identity_verified:
            return False, status.identity_status or "identity_unverified"
        return True, "downloaded"
    expected_errors = {str(item) for item in sample.get("expected_errors") or []}
    actual = status.failure_taxonomy or "unknown"
    if status.download_status == "downloaded":
        return True, "downloaded_better_than_expected"
    return actual in expected_errors, actual


def _phase1_attempt_durations(papers: list[PaperRecord]) -> list[int]:
    routes = {"public_http", "public_browser", "elsevier_api", "publisher_api_springer"}
    return [
        int(attempt["duration_ms"])
        for paper in papers
        for attempt in paper.fulltext_status.download_attempts
        if attempt.get("route") in routes
        and isinstance(attempt.get("duration_ms"), (int, float))
    ]


async def run_download_validation(
    *,
    suite_path: Optional[str] = None,
    profile: str = "smoke",
    rounds: int = 3,
    output_dir: str = ".spc_cache/download_validation",
    publishers: Optional[Iterable[str]] = None,
    sample_ids: Optional[Iterable[str]] = None,
    gate: Optional[ValidationGate] = None,
) -> dict[str, Any]:
    """使用隔离缓存连续执行全链路下载并评估生产门禁。"""
    if rounds < 1:
        raise ValueError("验收轮数必须大于等于 1")
    suite = _load_suite(suite_path)
    samples = _select_samples(
        suite,
        profile=profile,
        publishers=publishers,
        sample_ids=sample_ids,
    )
    gate = gate or ValidationGate()
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    round_reports: list[dict[str, Any]] = []
    all_phase1_durations: list[int] = []
    publisher_results: dict[str, Counter[str]] = defaultdict(Counter)
    discovery_source_results: Counter[str] = Counter()
    sample_results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    gate_failures: list[dict[str, Any]] = []

    for round_index in range(1, rounds + 1):
        round_root = root / f"round_{round_index}"
        pdf_dir = round_root / "pdf"
        cache_dir = round_root / "cache"
        papers = [_paper_from_sample(sample, round_index) for sample in samples]
        logger.info(
            "[下载验收] 开始，轮次=%d/%d，样本数=%d，缓存=%s",
            round_index,
            rounds,
            len(papers),
            cache_dir,
        )
        started = time.perf_counter()
        manager = PDFDownloadManager(
            output_dir=str(pdf_dir),
            cache_root=cache_dir,
            retry_failed=True,
            no_cache=True,
        )
        try:
            await manager.download_many(papers)
        finally:
            await manager.close()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        run_report = build_download_run_report(papers, total_candidates=len(papers))
        run_report["validation_round"] = round_index
        run_report["elapsed_ms"] = elapsed_ms
        round_root.mkdir(parents=True, exist_ok=True)
        (round_root / "run_report.json").write_text(
            json.dumps(run_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (round_root / "seed_papers.jsonl").write_text(
            "".join(
                json.dumps(paper.model_dump(mode="json"), ensure_ascii=False) + "\n"
                for paper in papers
            ),
            encoding="utf-8",
        )

        round_phase1 = _phase1_attempt_durations(papers)
        all_phase1_durations.extend(round_phase1)
        duplicate_transfers = int(
            run_report["metrics"]["deduplication"]["duplicate_transfer_count"]
        )
        round_entries = []
        for sample, paper in zip(samples, papers):
            passed, actual = _expected_result(
                sample,
                paper,
                require_identity_verification=gate.require_identity_verification,
            )
            discovery_sources = sorted(
                {
                    str(source)
                    for resource in paper.fulltext_status.normalized_resources
                    for source in resource.get("sources") or []
                }
            )
            for source in discovery_sources:
                discovery_source_results[source] += 1
            required_sources = {
                str(item) for item in sample.get("required_discovery_sources") or []
            }
            missing_sources = sorted(required_sources - set(discovery_sources))
            if missing_sources:
                passed = False
                actual = "required_discovery_source_missing"
            publisher = str(sample.get("publisher") or "unknown").lower()
            publisher_results[publisher]["passed" if passed else "failed"] += 1
            entry = {
                "sample_id": sample["id"],
                "doi": paper.doi,
                "arxiv_id": paper.arxiv_id,
                "publisher": publisher,
                "expected_status": sample.get("expected_status") or "downloaded",
                "passed": passed,
                "actual": actual,
                "download_status": paper.fulltext_status.download_status,
                "successful_route": paper.fulltext_status.successful_route,
                "identity_verified": paper.fulltext_status.identity_verified,
                "identity_status": paper.fulltext_status.identity_status,
                "failure_taxonomy": paper.fulltext_status.failure_taxonomy,
                "pdf_path": paper.fulltext_status.local_path,
                "pdf_size_bytes": paper.fulltext_status.file_size_bytes,
                "pdf_sha256": paper.fulltext_status.sha256,
                "discovery_sources": discovery_sources,
                "missing_discovery_sources": missing_sources,
            }
            sample_results[str(sample["id"])].append(entry)
            round_entries.append(entry)
            if not passed:
                gate_failures.append(
                    {"gate": "sample_expectation", "round": round_index, **entry}
                )
        if gate.require_zero_duplicate_transfers and duplicate_transfers:
            gate_failures.append(
                {
                    "gate": "duplicate_transfer_count",
                    "round": round_index,
                    "actual": duplicate_transfers,
                    "expected": 0,
                }
            )
        if round_phase1 and max(round_phase1) > gate.maximum_phase1_paper_ms:
            gate_failures.append(
                {
                    "gate": "phase1_paper_budget",
                    "round": round_index,
                    "actual_ms": max(round_phase1),
                    "maximum_ms": gate.maximum_phase1_paper_ms,
                }
            )
        round_reports.append(
            {
                "round": round_index,
                "elapsed_ms": elapsed_ms,
                "passed": sum(1 for item in round_entries if item["passed"]),
                "failed": sum(1 for item in round_entries if not item["passed"]),
                "phase1_p50_ms": _percentile(round_phase1, 50),
                "phase1_p95_ms": _percentile(round_phase1, 95),
                "duplicate_transfer_count": duplicate_transfers,
                "entries": round_entries,
            }
        )

    total = len(samples) * rounds
    passed = sum(
        item["passed"] for report in round_reports for item in report["entries"]
    )
    success_rate = passed / total if total else 0.0
    phase1_p95 = _percentile(all_phase1_durations, 95)
    if success_rate < gate.minimum_success_rate:
        gate_failures.append(
            {
                "gate": "success_rate",
                "actual": round(success_rate, 4),
                "minimum": gate.minimum_success_rate,
            }
        )
    if phase1_p95 > gate.maximum_phase1_p95_ms:
        gate_failures.append(
            {
                "gate": "phase1_p95",
                "actual_ms": phase1_p95,
                "maximum_ms": gate.maximum_phase1_p95_ms,
            }
        )

    report = {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now().isoformat(),
        "suite_version": suite["suite_version"],
        "profile": profile,
        "unattended": True,
        "isolated_cache": True,
        "rounds": rounds,
        "sample_count": len(samples),
        "execution_count": total,
        "passed": passed,
        "failed": total - passed,
        "success_rate": round(success_rate, 4),
        "validation_ok": not gate_failures,
        "gates": {
            "minimum_success_rate": gate.minimum_success_rate,
            "maximum_phase1_p95_ms": gate.maximum_phase1_p95_ms,
            "maximum_phase1_paper_ms": gate.maximum_phase1_paper_ms,
            "require_identity_verification": gate.require_identity_verification,
            "require_zero_duplicate_transfers": gate.require_zero_duplicate_transfers,
        },
        "gate_failures": gate_failures,
        "performance": {
            "phase1_count": len(all_phase1_durations),
            "phase1_p50_ms": _percentile(all_phase1_durations, 50),
            "phase1_p95_ms": phase1_p95,
            "phase1_max_ms": max(all_phase1_durations) if all_phase1_durations else 0,
        },
        "publisher_results": {
            key: dict(value) for key, value in publisher_results.items()
        },
        "discovery_source_results": dict(discovery_source_results),
        "sample_results": dict(sample_results),
        "round_reports": round_reports,
    }
    (root / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report
