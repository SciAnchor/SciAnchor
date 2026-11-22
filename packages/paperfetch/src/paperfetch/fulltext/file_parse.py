"""无绑定身份的 PDF 物理解析；不写 papers.jsonl，也不冒充论文正文。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from paperfetch.core.context import CuratorContext
from paperfetch.core.contracts_v1 import ErrorInfo
from paperfetch.core.models import PaperRecord as LegacyPaperRecord
from paperfetch.fulltext.mineru import MinerUParseAction
from paperfetch.fulltext.parser import (
    _RETRYABLE_PARSE_ERRORS,
    _mineru_files,
    _write_parse_audit,
)
from paperfetch.observability.events import redact_sensitive


FILE_PARSE_MANIFEST = "spc.file-parse-manifest.v1"
MAX_PDF_BYTES = 200 * 1024 * 1024
MIN_PDF_BYTES = 100


@dataclass(frozen=True)
class FileParseOutcome:
    parse_id: str
    input_path: str
    input_sha256: str | None
    input_size_bytes: int | None
    markdown_path: str | None
    markdown_sha256: str | None
    markdown_size_bytes: int | None
    manifest_path: str | None
    error: ErrorInfo | None
    audit_ref: str | None

    @property
    def succeeded(self) -> bool:
        return self.markdown_path is not None and self.error is None


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _input_error(code: str, message: str, remediation: str) -> ErrorInfo:
    return ErrorInfo(
        code=code,
        error_class="precondition_failed",
        stage="parse_input",
        retryable=False,
        message=message,
        remediation=remediation,
    )


def _validate_pdf(path: Path) -> tuple[str, int] | ErrorInfo:
    if not path.is_file():
        return _input_error(
            "parse_input_missing",
            "指定的 PDF 不存在或不是文件",
            "传入本地可读的 PDF 路径",
        )
    size = path.stat().st_size
    if size < MIN_PDF_BYTES:
        return _input_error(
            "parse_input_too_small",
            "文件过小，不足以作为 PDF",
            "确认传入的是完整 PDF，而不是空文件或 HTML",
        )
    if size > MAX_PDF_BYTES:
        return _input_error(
            "parse_input_too_large",
            f"PDF 超过 {MAX_PDF_BYTES} 字节上限",
            "换更小的 PDF，或先在外部拆分后再解析",
        )
    try:
        with path.open("rb") as handle:
            magic = handle.read(5)
    except OSError:
        return _input_error(
            "parse_input_unreadable",
            "无法读取指定文件",
            "检查文件权限后重试",
        )
    if not magic.startswith(b"%PDF"):
        return _input_error(
            "parse_input_not_pdf",
            "文件缺少 %PDF 魔数，不能当作 PDF 解析",
            "只解析物理 PDF，不要传入 HTML、查看器页或任意本地文件",
        )
    return _sha256_file(path)


def _publish_parse_files(
    output_dir: Path,
    parse_id: str,
    *,
    input_path: Path,
    input_sha256: str,
    input_size_bytes: int,
    files: dict,
) -> tuple[Path, str, int]:
    target = output_dir / "parse" / parse_id
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    published: list[dict[str, str | int]] = []
    markdown_path: Path | None = None
    markdown_sha256 = ""
    markdown_size = 0
    for role, raw_spec in sorted(files.items()):
        raw_path, requested = (
            raw_spec if isinstance(raw_spec, tuple) else (raw_spec, "")
        )
        source = Path(raw_path)
        relative = requested or (
            f"{role}{''.join(source.suffixes)}" if source.suffixes else role
        )
        destination = target.joinpath(*Path(relative).as_posix().split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        digest, size = _sha256_file(destination)
        published.append(
            {"role": role, "path": relative, "sha256": digest, "size_bytes": size}
        )
        if role == "document_markdown":
            if size == 0:
                raise ValueError("MinerU Markdown 文件为空")
            markdown_path = destination
            markdown_sha256 = digest
            markdown_size = size
    if markdown_path is None:
        raise ValueError("MinerU 结果缺少 document.md")
    manifest = redact_sensitive(
        {
            "schema_version": FILE_PARSE_MANIFEST,
            "parse_id": parse_id,
            "identity_bound": False,
            "paper_record_written": False,
            "input": {
                "path": str(input_path),
                "sha256": input_sha256,
                "size_bytes": input_size_bytes,
            },
            "producer": {"name": "mineru", "version": "vlm"},
            "files": published,
        }
    )
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return markdown_path, markdown_sha256, markdown_size


class FileParseService:
    async def parse(
        self,
        *,
        pdf: Path,
        output_dir: Path,
        no_cache: bool = False,
    ) -> FileParseOutcome:
        started = time.perf_counter()
        pdf_path = pdf.expanduser().resolve()
        output = output_dir.expanduser().resolve()
        validated = _validate_pdf(pdf_path)
        if isinstance(validated, ErrorInfo):
            return FileParseOutcome(
                parse_id="",
                input_path=str(pdf_path),
                input_sha256=None,
                input_size_bytes=None,
                markdown_path=None,
                markdown_sha256=None,
                markdown_size_bytes=None,
                manifest_path=None,
                error=validated,
                audit_ref=None,
            )
        digest, size = validated
        parse_id = f"parse_{digest[:16]}"
        if not (os.getenv("MINERU_API_TOKEN") or "").strip():
            return FileParseOutcome(
                parse_id=parse_id,
                input_path=str(pdf_path),
                input_sha256=digest,
                input_size_bytes=size,
                markdown_path=None,
                markdown_sha256=None,
                markdown_size_bytes=None,
                manifest_path=None,
                error=ErrorInfo(
                    code="mineru_credentials_missing",
                    error_class="configuration_error",
                    stage="parse_preflight",
                    retryable=False,
                    message="未配置 MinerU API 凭证，无法解析 PDF",
                    remediation="在受控配置中设置 MINERU_API_TOKEN 后重试解析",
                ),
                audit_ref=None,
            )
        output.mkdir(parents=True, exist_ok=True)
        work_root = output / ".spc" / "staging" / f"{parse_id}-{uuid.uuid4().hex}"
        work_root.mkdir(parents=True, exist_ok=True)
        paper = LegacyPaperRecord(paper_id=f"spc_{digest[:32]}", title=pdf_path.name)
        paper.fulltext_status.download_status = "downloaded"
        paper.fulltext_status.download_attempted = True
        paper.fulltext_status.local_path = str(pdf_path)
        paper.fulltext_status.magic_pdf = True
        paper.fulltext_status.identity_verified = False
        paper.fulltext_status.identity_status = "not_checked"
        try:
            context = CuratorContext(run_id=f"file-parse-{parse_id}")
            context.output_dir = str(work_root)
            context.top_seeds = [paper]
            try:
                await MinerUParseAction(
                    enrich_top_k=1,
                    no_cache=no_cache,
                    run_code_audit=False,
                ).execute(context)
            except Exception as exc:
                return FileParseOutcome(
                    parse_id=parse_id,
                    input_path=str(pdf_path),
                    input_sha256=digest,
                    input_size_bytes=size,
                    markdown_path=None,
                    markdown_sha256=None,
                    markdown_size_bytes=None,
                    manifest_path=None,
                    error=ErrorInfo(
                        code="mineru_runtime_failed",
                        error_class="internal_error",
                        stage="parse",
                        retryable=True,
                        message=f"MinerU 解析流程异常终止：{type(exc).__name__}",
                        remediation="输入 PDF 未改写；稍后仅重试解析",
                    ),
                    audit_ref=None,
                )
            duration_ms = int((time.perf_counter() - started) * 1000)
            audit_ref = _write_parse_audit(
                output,
                parse_id,
                paper.fulltext_status,
                duration_ms=duration_ms,
                identity_bound=False,
            )
            if paper.fulltext_status.mineru_status != "parsed":
                failure_class = str(
                    paper.fulltext_status.mineru_failure_class or "mineru_parse_failed"
                )
                return FileParseOutcome(
                    parse_id=parse_id,
                    input_path=str(pdf_path),
                    input_sha256=digest,
                    input_size_bytes=size,
                    markdown_path=None,
                    markdown_sha256=None,
                    markdown_size_bytes=None,
                    manifest_path=None,
                    error=ErrorInfo(
                        code=failure_class,
                        error_class=failure_class,
                        stage=str(
                            paper.fulltext_status.mineru_failure_stage or "parse"
                        ),
                        retryable=failure_class in _RETRYABLE_PARSE_ERRORS,
                        message=f"MinerU 正文解析未完成：{failure_class}",
                        remediation="稍后仅重试解析；输入 PDF 未被改写",
                        audit_ref=audit_ref,
                    ),
                    audit_ref=audit_ref,
                )
            try:
                files = _mineru_files(
                    Path(paper.fulltext_status.mineru_markdown_path or ""),
                    Path(paper.fulltext_status.mineru_archive_path or ""),
                    Path(paper.fulltext_status.mineru_extracted_dir or ""),
                )
                markdown_path, markdown_sha256, markdown_size = _publish_parse_files(
                    output,
                    parse_id,
                    input_path=pdf_path,
                    input_sha256=digest,
                    input_size_bytes=size,
                    files=files,
                )
            except (OSError, ValueError) as exc:
                return FileParseOutcome(
                    parse_id=parse_id,
                    input_path=str(pdf_path),
                    input_sha256=digest,
                    input_size_bytes=size,
                    markdown_path=None,
                    markdown_sha256=None,
                    markdown_size_bytes=None,
                    manifest_path=None,
                    error=ErrorInfo(
                        code="mineru_output_invalid",
                        error_class="output_validation_failed",
                        stage="parse_output",
                        retryable=True,
                        message=f"MinerU 已返回结果，但正文文件不完整：{type(exc).__name__}",
                        remediation="仅重试解析，不要把结果写入 Seed Pack",
                        audit_ref=audit_ref,
                    ),
                    audit_ref=audit_ref,
                )
            manifest_path = (output / "parse" / parse_id / "manifest.json").as_posix()
            return FileParseOutcome(
                parse_id=parse_id,
                input_path=str(pdf_path),
                input_sha256=digest,
                input_size_bytes=size,
                markdown_path=str(markdown_path),
                markdown_sha256=markdown_sha256,
                markdown_size_bytes=markdown_size,
                manifest_path=manifest_path,
                error=None,
                audit_ref=audit_ref,
            )
        finally:
            shutil.rmtree(work_root, ignore_errors=True)
