"""将现有合法下载路由适配为 SPC 1.0 不可变阶段结果。

下载器仍负责资源发现、Elsevier API、Europe PMC、公开 HTTP 和身份校验；
本模块不复制路由逻辑，也不允许下载器直接修改 Seed Pack 事实文件。
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paperfetch.artifacts.models import ArtifactPointer, ArtifactProducer
from paperfetch.artifacts.store import ArtifactStoreError, materialize_artifact
from paperfetch.core.contracts_v1 import ErrorInfo
from paperfetch.core.information import (
    LAYER_AUDIT,
    compact_route_attempts,
    ensure_successful_attempt,
    normalize_audit_ref,
)
from paperfetch.core.models import AuthorRecord, PaperRecord as LegacyPaperRecord
from paperfetch.downloaders.pipeline.manager import PDFDownloadManager
from paperfetch.observability.events import redact_sensitive
from paperfetch.papers.models import IdentityVerification, PaperRecord


@dataclass(frozen=True)
class DownloadRequest:
    paper: PaperRecord
    seed_pack: Path
    no_cache: bool = False
    route_mode: str = "auto"


@dataclass(frozen=True)
class DownloadOutcome:
    paper_id: str
    pdf: ArtifactPointer | None
    identity: IdentityVerification | None
    successful_route: str | None
    attempted: tuple[dict, ...]
    elapsed_ms: int
    error: ErrorInfo | None
    audit_ref: str | None
    hop_diagnostics: dict[str, Any] | None = None

    @property
    def succeeded(self) -> bool:
        return self.pdf is not None and self.identity is not None and self.error is None


_RETRYABLE_DOWNLOAD_ERRORS = {
    "connect_error",
    "gateway_fault",
    "network_error",
    "publisher_challenge",
    "rate_limited",
    "timeout",
}


_DOWNLOAD_ERROR_MESSAGES = {
    "connect_error": "论文下载连接失败；请运行 doctor --probe-traffic-classes 检查实际代理通路",
    "network_error": "论文下载网络请求失败；请运行 doctor --probe-traffic-classes 区分代理端点与上游通路",
    "gateway_fault": "论文下载经过的网关返回故障；代理节点或上游服务可能不可用",
    "timeout": "论文下载超过当前路线的硬截止",
    "rate_limited": "出版社或数据源当前限流",
    "publisher_challenge": "出版社自动验证未在有限等待内放行",
    "unattended_auth_blocked": "出版社要求复选框、CAPTCHA、MFA 或其他人工确认，无法无人值守完成",
    "subscription_required": "出版社官方 API 未对当前凭证提供该资源的全文",
    "auth_failed": "出版社或 API 拒绝了当前凭证",
    "identity_mismatch": "下载到的 PDF 与目标论文身份不一致，已拒绝保存",
    "identity_unverified": "PDF 缺少足够的 DOI 或题名证据，无法绑定目标论文",
    "not_pdf": "下载响应不是有效 PDF",
    "pdf_link_not_found": "出版社页面没有提供可验证的 PDF 地址",
}


def _legacy_paper(record: PaperRecord) -> LegacyPaperRecord:
    bibliographic = record.bibliographic
    venue_name = bibliographic.venue.name if bibliographic.venue else None
    publication_year = None
    if bibliographic.publication_date:
        try:
            publication_year = int(bibliographic.publication_date[:4])
        except ValueError:
            pass
    return LegacyPaperRecord(
        paper_id=record.paper_id,
        doi=record.identifiers.doi,
        pubmed_id=record.identifiers.pubmed_id,
        pmc_id=record.identifiers.pmc_id,
        arxiv_id=record.identifiers.arxiv_id,
        title=bibliographic.title,
        year=publication_year,
        journal=venue_name,
        venue=venue_name,
        volume=bibliographic.volume,
        issue=bibliographic.issue,
        pages=bibliographic.pages,
        publisher=bibliographic.publisher,
        document_type=bibliographic.paper_type,
        abstract=bibliographic.abstract,
        authors=[
            AuthorRecord(
                name=author.display_name,
                orcid=author.orcid,
                affiliations=[],
                source="spc_v1_adapter",
            )
            for author in bibliographic.authors
        ],
    )


def _identity_from_legacy(status: Any, record: PaperRecord) -> IdentityVerification:
    method = str(status.identity_status or "").removeprefix("verified_")
    targets = {
        "doi": record.identifiers.doi,
        "arxiv_id": record.identifiers.arxiv_id,
        "pmc_id": record.identifiers.pmc_id,
        "pubmed_id": record.identifiers.pubmed_id,
        "title": record.bibliographic.title,
    }
    if method not in targets or not targets[method]:
        method = next(
            name
            for name in ("doi", "arxiv_id", "pmc_id", "pubmed_id", "title")
            if targets[name]
        )
    target = targets[method]
    evidence = (
        status.identity_evidence if isinstance(status.identity_evidence, dict) else {}
    )
    observed = {
        "doi": next(
            (
                value
                for value in [
                    *(evidence.get("primary_dois") or []),
                    *(evidence.get("discovered_dois") or []),
                ]
                if str(value).casefold() == str(target).casefold()
            ),
            target,
        ),
        "arxiv_id": evidence.get("expected_arxiv") or target,
        "pmc_id": target,
        "pubmed_id": target,
        "title": evidence.get("metadata_title") or record.bibliographic.title,
    }[method]
    return IdentityVerification(
        method=method, target=str(target), observed=str(observed)
    )


def _download_error(status: Any, *, audit_ref: str | None) -> ErrorInfo:
    error_class = str(
        status.last_failure_class
        or status.failure_taxonomy
        or status.primary_failure_class
        or (
            "pdf_resource_not_discovered"
            if status.resource_outcome == "resource_not_discovered"
            else "pdf_download_failed"
        )
    )
    return ErrorInfo(
        code=error_class,
        error_class=error_class,
        stage=str(status.failure_stage or "pdf_transfer"),
        retryable=error_class in _RETRYABLE_DOWNLOAD_ERRORS,
        message=_DOWNLOAD_ERROR_MESSAGES.get(
            error_class,
            "未发现可验证的论文 PDF"
            if error_class == "pdf_resource_not_discovered"
            else f"所有已配置的合法下载方式均未获得已验证 PDF：{error_class}",
        ),
        remediation=(
            "检查运行环境与网络代理后稍后重试"
            if error_class in _RETRYABLE_DOWNLOAD_ERRORS
            else "查看 audit_ref 中的脱敏下载诊断"
        ),
        audit_ref=audit_ref,
    )


def _attempted(status: Any | None) -> tuple[dict, ...]:
    if status is None:
        return ()
    return tuple(
        ensure_successful_attempt(
            compact_route_attempts(getattr(status, "download_attempts", None)),
            getattr(status, "successful_route", None),
        )
    )


def _write_audit(seed_pack: Path, record: PaperRecord, status: Any) -> str | None:
    audit_dir = seed_pack / ".spc" / "audit" / record.paper_id
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    audit_path = audit_dir / f"pdf-download-{uuid.uuid4().hex}.json"
    payload = redact_sensitive(
        {
            "schema_version": "spc.paper-download-audit.v1",
            "layer": LAYER_AUDIT,
            "paper_id": record.paper_id,
            "identifiers": record.identifiers.model_dump(
                mode="json", exclude_none=True
            ),
            "resource_outcome": status.resource_outcome,
            "route": status.successful_route,
            "successful_route": status.successful_route,
            "discovery_events": status.discovery_events,
            "normalized_resources": status.normalized_resources,
            "download_attempts": status.download_attempts,
            "identity_status": status.identity_status,
            "identity_confidence": status.identity_confidence,
            "identity_evidence": status.identity_evidence,
        }
    )
    try:
        audit_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return None
    return normalize_audit_ref(audit_path, seed_pack)


class PaperDownloadService:
    async def download(self, request: DownloadRequest) -> DownloadOutcome:
        started = time.perf_counter()
        paper = _legacy_paper(request.paper)
        work_root = (
            request.seed_pack
            / ".spc"
            / "staging"
            / f"download-{request.paper.paper_id}-{uuid.uuid4().hex}"
        )
        work_root.mkdir(parents=True, exist_ok=True)
        manager = None
        try:
            try:
                manager = PDFDownloadManager(
                    str(work_root),
                    cache_root=request.seed_pack / ".spc" / "cache" / "pdf",
                    retry_failed=True,
                    no_cache=request.no_cache,
                    route_mode=request.route_mode,
                )
                status = await manager.download_one(paper)
            except Exception as exc:
                from paperfetch.downloaders.pipeline.errors import DownloadError

                classified = DownloadError.from_exception(exc, route="download_runtime")
                error = ErrorInfo(
                    code=classified.error_class or "download_runtime_failed",
                    error_class=classified.error_class or "internal_error",
                    stage="pdf_transfer",
                    retryable=(classified.error_class or "")
                    in _RETRYABLE_DOWNLOAD_ERRORS,
                    message=f"论文 PDF 下载流程异常终止：{type(exc).__name__}",
                    remediation="查看运行环境和脱敏诊断记录后重试",
                )
                return DownloadOutcome(
                    paper_id=request.paper.paper_id,
                    pdf=None,
                    identity=None,
                    successful_route=None,
                    attempted=(),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    error=error,
                    audit_ref=None,
                )
            finally:
                if manager is not None:
                    try:
                        await manager.close()
                    except Exception:
                        pass
            audit_ref = _write_audit(request.seed_pack, request.paper, status)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if not (
                status.download_status == "downloaded"
                and status.identity_verified
                and status.magic_pdf
                and status.local_path
                and Path(status.local_path).is_file()
            ):
                return DownloadOutcome(
                    paper_id=request.paper.paper_id,
                    pdf=None,
                    identity=None,
                    successful_route=None,
                    attempted=_attempted(status),
                    elapsed_ms=elapsed_ms,
                    error=_download_error(status, audit_ref=audit_ref),
                    audit_ref=audit_ref,
                )
            identity = _identity_from_legacy(status, request.paper)
            try:
                pointer = materialize_artifact(
                    request.seed_pack,
                    paper_id=request.paper.paper_id,
                    kind="paper_pdf",
                    files={"article_pdf": status.local_path},
                    producer=ArtifactProducer(name="spc-paper-download"),
                )
            except (ArtifactStoreError, OSError, ValueError) as exc:
                local_io = isinstance(exc, OSError)
                error = ErrorInfo(
                    code="pdf_file_save_failed"
                    if local_io
                    else "pdf_file_validation_failed",
                    error_class="local_io_error"
                    if local_io
                    else "output_validation_failed",
                    stage="pdf_file_save",
                    retryable=local_io,
                    message=(
                        "PDF 已下载，但保存本地文件失败"
                        if local_io
                        else "PDF 已下载，但本地文件校验未通过"
                    ),
                    remediation="检查输出目录后重试；详细原因见脱敏诊断记录",
                    audit_ref=audit_ref,
                )
                return DownloadOutcome(
                    paper_id=request.paper.paper_id,
                    pdf=None,
                    identity=None,
                    successful_route=status.successful_route,
                    attempted=_attempted(status),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    error=error,
                    audit_ref=audit_ref,
                )
            return DownloadOutcome(
                paper_id=request.paper.paper_id,
                pdf=pointer,
                identity=identity,
                successful_route=status.successful_route,
                attempted=_attempted(status),
                elapsed_ms=elapsed_ms,
                error=None,
                audit_ref=audit_ref,
            )
        finally:
            shutil.rmtree(work_root, ignore_errors=True)
