"""单篇已验证 PDF 与可选解析编排；不直接写 Seed Pack 论文记录。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from paperfetch.fulltext.parser import PaperParseService, ParseOutcome
from paperfetch.fulltext.service import (
    DownloadOutcome,
    DownloadRequest,
    PaperDownloadService,
)
from paperfetch.artifacts.models import ArtifactPointer
from paperfetch.core.contracts_v1 import ErrorInfo
from paperfetch.core.information import ensure_successful_attempt
from paperfetch.papers.models import IdentityVerification, PaperRecord


@dataclass(frozen=True)
class PaperFileOutcome:
    paper_id: str
    pdf: ArtifactPointer | None
    identity: IdentityVerification | None
    fulltext: ArtifactPointer | None
    successful_route: str | None
    attempted: tuple[dict, ...]
    pdf_error: ErrorInfo | None
    parse_error: ErrorInfo | None
    audit_refs: tuple[str, ...]
    hop_diagnostics: dict | None = None

    @property
    def error(self) -> ErrorInfo | None:
        return self.pdf_error or self.parse_error

    @property
    def completed(self) -> bool:
        return self.pdf is not None and self.fulltext is not None and self.error is None

    @property
    def partial(self) -> bool:
        return self.pdf is not None and self.parse_error is not None


class PaperFileWorkflow:
    def __init__(
        self,
        download_service: PaperDownloadService | None = None,
        parse_service: PaperParseService | None = None,
    ) -> None:
        self.download_service = download_service or PaperDownloadService()
        self.parse_service = parse_service or PaperParseService()

    def _attempted(
        self, download: DownloadOutcome | None, paper: PaperRecord
    ) -> tuple[dict, ...]:
        if download is not None:
            return tuple(
                ensure_successful_attempt(
                    list(download.attempted),
                    download.successful_route,
                )
            )
        route = paper.fulltext.pdf.route
        if route:
            return ({"route": route, "outcome": "succeeded", "error_class": None},)
        return ()

    async def run(
        self,
        *,
        paper: PaperRecord,
        seed_pack: Path,
        no_cache: bool = False,
        download_only: bool = False,
        parse_only: bool = False,
        route_mode: str = "auto",
    ) -> PaperFileOutcome:
        existing_pdf = paper.fulltext.pdf.artifact
        identity = paper.fulltext.pdf.identity
        download: DownloadOutcome | None = None
        if parse_only and existing_pdf is None:
            error = ErrorInfo(
                code="verified_pdf_required",
                error_class="precondition_failed",
                stage="parse_input",
                retryable=False,
                message="只解析模式要求论文记录已有经过身份验证的 PDF",
                remediation="先下载并校验 PDF，不要把任意本地 PDF 当作论文正文",
            )
            return PaperFileOutcome(
                paper_id=paper.paper_id,
                pdf=None,
                identity=None,
                fulltext=None,
                successful_route=None,
                attempted=(),
                pdf_error=error,
                parse_error=None,
                audit_refs=(),
            )
        if existing_pdf is None:
            download = await self.download_service.download(
                DownloadRequest(
                    paper=paper,
                    seed_pack=seed_pack,
                    no_cache=no_cache,
                    route_mode=route_mode,
                )
            )
            if not download.succeeded:
                return PaperFileOutcome(
                    paper_id=paper.paper_id,
                    pdf=None,
                    identity=None,
                    fulltext=None,
                    successful_route=None,
                    attempted=self._attempted(download, paper),
                    pdf_error=download.error,
                    parse_error=None,
                    audit_refs=tuple(value for value in (download.audit_ref,) if value),
                    hop_diagnostics=download.hop_diagnostics,
                )
            existing_pdf = download.pdf
            identity = download.identity
        refs = tuple(
            value for value in ((download.audit_ref if download else None),) if value
        )
        route = download.successful_route if download else paper.fulltext.pdf.route
        attempted = self._attempted(download, paper)
        hop_diagnostics = download.hop_diagnostics if download else None
        if download_only:
            return PaperFileOutcome(
                paper_id=paper.paper_id,
                pdf=existing_pdf,
                identity=identity,
                fulltext=paper.fulltext.parse.artifact,
                successful_route=route,
                attempted=attempted,
                pdf_error=None,
                parse_error=None,
                audit_refs=refs,
                hop_diagnostics=hop_diagnostics,
            )
        if paper.fulltext.parse.artifact is not None and not parse_only:
            return PaperFileOutcome(
                paper_id=paper.paper_id,
                pdf=existing_pdf,
                identity=identity,
                fulltext=paper.fulltext.parse.artifact,
                successful_route=route,
                attempted=attempted,
                pdf_error=None,
                parse_error=None,
                audit_refs=refs,
                hop_diagnostics=hop_diagnostics,
            )
        parsed: ParseOutcome = await self.parse_service.parse(
            paper=paper,
            seed_pack=seed_pack,
            pdf=existing_pdf,
            no_cache=no_cache,
        )
        refs = (*refs, *(value for value in (parsed.audit_ref,) if value))
        return PaperFileOutcome(
            paper_id=paper.paper_id,
            pdf=existing_pdf,
            identity=identity,
            fulltext=parsed.fulltext,
            successful_route=route,
            attempted=attempted,
            pdf_error=None,
            parse_error=parsed.error,
            audit_refs=refs,
            hop_diagnostics=hop_diagnostics,
        )
