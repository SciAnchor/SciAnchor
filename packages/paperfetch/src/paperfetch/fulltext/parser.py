"""将 MinerU 解析结果适配为 SPC 1.0 正文文件清单。"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from paperfetch.fulltext.service import _legacy_paper
from paperfetch.artifacts.models import ArtifactPointer, ArtifactProducer
from paperfetch.artifacts.store import ArtifactStoreError, materialize_artifact
from paperfetch.core.context import CuratorContext
from paperfetch.core.contracts_v1 import ErrorInfo
from paperfetch.papers.models import PaperRecord
from paperfetch.fulltext.mineru import MinerUParseAction
from paperfetch.observability.events import redact_sensitive


@dataclass(frozen=True)
class ParseOutcome:
    paper_id: str
    fulltext: ArtifactPointer | None
    error: ErrorInfo | None
    audit_ref: str | None

    @property
    def succeeded(self) -> bool:
        return self.fulltext is not None and self.error is None


_RETRYABLE_PARSE_ERRORS = {
    "artifact_tls_error",
    "artifact_timeout",
    "artifact_download_failed",
    "artifact_upload_failed",
    "service_connection_error",
    "service_rate_limited",
    "service_timeout",
    "service_tls_error",
}


def _find_required_file(directory: Path, pattern: str, label: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(
            f"MinerU 正文目录的 {label} 文件数量应为 1，实际为 {len(matches)}"
        )
    return matches[0]


def _mineru_files(markdown_path: Path, archive_path: Path, extracted_dir: Path) -> dict:
    layout = extracted_dir / "layout.json"
    if not layout.is_file():
        raise ValueError("MinerU 正文目录缺少 layout.json")
    content_list = _find_required_file(
        extracted_dir, "*_content_list.json", "content list"
    )
    model = _find_required_file(extracted_dir, "*_model.json", "model")
    files: dict[str, str | Path | tuple[str | Path, str]] = {
        "document_markdown": (markdown_path, "document.md"),
        "layout": (layout, "layout.json"),
        "content_list": (content_list, "content-list.json"),
        "model": (model, "model.json"),
        "raw_archive": (archive_path, "raw/mineru-result.zip"),
    }
    for image in (
        sorted((extracted_dir / "images").rglob("*"))
        if (extracted_dir / "images").is_dir()
        else []
    ):
        if not image.is_file():
            continue
        relative = image.relative_to(extracted_dir).as_posix()
        files[f"image:{relative}"] = (image, relative)
    return files


def _write_parse_audit(
    seed_pack: Path,
    paper_id: str,
    status,
    *,
    doi: str | None = None,
    duration_ms: int | None = None,
    endpoint: str | None = None,
    identity_bound: bool | None = None,
) -> str | None:
    audit_dir = seed_pack / ".spc" / "audit" / paper_id
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    path = audit_dir / f"mineru-parse-{uuid.uuid4().hex}.json"
    payload = redact_sensitive(
        {
            "schema_version": "spc.paper-parse-audit.v1",
            "paper_id": paper_id,
            "doi": doi,
            "endpoint": endpoint
            or os.getenv("MINERU_BASE_URL")
            or "https://mineru.net/api/v4",
            "duration_ms": duration_ms,
            "status": status.mineru_status,
            "failure_stage": status.mineru_failure_stage,
            "failure_class": status.mineru_failure_class,
            "attempts": status.mineru_attempts,
            "error_summary": status.mineru_error_summary,
            **(
                {"identity_bound": identity_bound} if identity_bound is not None else {}
            ),
        }
    )
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return None
    return path.relative_to(seed_pack).as_posix()


class PaperParseService:
    async def parse(
        self,
        *,
        paper: PaperRecord,
        seed_pack: Path,
        pdf: ArtifactPointer,
        no_cache: bool = False,
    ) -> ParseOutcome:
        started = time.perf_counter()
        if not (os.getenv("MINERU_API_TOKEN") or "").strip():
            error = ErrorInfo(
                code="mineru_credentials_missing",
                error_class="configuration_error",
                stage="parse_preflight",
                retryable=False,
                message="未配置 MinerU API 凭证，无法生成正文文件",
                remediation="在受控配置中设置 MINERU_API_TOKEN 后仅重试解析",
            )
            return ParseOutcome(
                paper_id=paper.paper_id, fulltext=None, error=error, audit_ref=None
            )
        pdf_path = seed_pack / Path(pdf.manifest_path).parent / "article.pdf"
        legacy = _legacy_paper(paper)
        legacy.fulltext_status.download_status = "downloaded"
        legacy.fulltext_status.download_attempted = True
        legacy.fulltext_status.local_path = str(pdf_path)
        legacy.fulltext_status.magic_pdf = True
        legacy.fulltext_status.identity_verified = True
        legacy.fulltext_status.identity_status = "verified"
        work_root = (
            seed_pack
            / ".spc"
            / "staging"
            / f"parse-{paper.paper_id}-{uuid.uuid4().hex}"
        )
        work_root.mkdir(parents=True, exist_ok=True)
        context = CuratorContext(run_id=f"parse-{paper.paper_id}")
        context.output_dir = str(work_root)
        context.top_seeds = [legacy]
        action = MinerUParseAction(
            enrich_top_k=1,
            no_cache=no_cache,
            run_code_audit=False,
        )
        try:
            try:
                await action.execute(context)
            except Exception as exc:
                error = ErrorInfo(
                    code="mineru_runtime_failed",
                    error_class="internal_error",
                    stage="parse",
                    retryable=True,
                    message=f"MinerU 解析流程异常终止：{type(exc).__name__}",
                    remediation="已验证 PDF 保持可用；稍后仅重试解析",
                )
                return ParseOutcome(
                    paper_id=paper.paper_id, fulltext=None, error=error, audit_ref=None
                )
            status = legacy.fulltext_status
            duration_ms = int((time.perf_counter() - started) * 1000)
            audit_ref = _write_parse_audit(
                seed_pack,
                paper.paper_id,
                status,
                doi=paper.identifiers.doi,
                duration_ms=duration_ms,
            )
            if status.mineru_status != "parsed":
                failure_class = str(
                    status.mineru_failure_class or "mineru_parse_failed"
                )
                return ParseOutcome(
                    paper_id=paper.paper_id,
                    fulltext=None,
                    error=ErrorInfo(
                        code=failure_class,
                        error_class=failure_class,
                        stage=str(status.mineru_failure_stage or "parse"),
                        retryable=failure_class in _RETRYABLE_PARSE_ERRORS,
                        message=f"MinerU 正文解析未完成：{failure_class}",
                        remediation="稍后仅重试解析；已验证 PDF 仍保持可用",
                        audit_ref=audit_ref,
                    ),
                    audit_ref=audit_ref,
                )
            markdown_path = Path(status.mineru_markdown_path or "")
            archive_path = Path(status.mineru_archive_path or "")
            extracted_dir = Path(status.mineru_extracted_dir or "")
            try:
                files = _mineru_files(markdown_path, archive_path, extracted_dir)
                pointer = materialize_artifact(
                    seed_pack,
                    paper_id=paper.paper_id,
                    kind="mineru_fulltext",
                    files=files,
                    producer=ArtifactProducer(name="mineru", version="vlm"),
                    source_artifact_id=pdf.artifact_id,
                )
            except (ArtifactStoreError, OSError, ValueError) as exc:
                error = ErrorInfo(
                    code="mineru_output_invalid",
                    error_class="output_validation_failed",
                    stage="parse_output",
                    retryable=True,
                    message=f"MinerU 已返回结果，但正文文件清单不完整：{type(exc).__name__}",
                    remediation="仅重试解析，不需要重复下载 PDF",
                    audit_ref=audit_ref,
                )
                return ParseOutcome(
                    paper_id=paper.paper_id,
                    fulltext=None,
                    error=error,
                    audit_ref=audit_ref,
                )
            return ParseOutcome(
                paper_id=paper.paper_id,
                fulltext=pointer,
                error=None,
                audit_ref=audit_ref,
            )
        finally:
            shutil.rmtree(work_root, ignore_errors=True)
