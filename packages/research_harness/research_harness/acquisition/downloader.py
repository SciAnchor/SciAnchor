"""PDF downloader with multi-candidate fallback and paywall detection."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from .pdf_audit import audit_pdf_identity
from .pdf_cache import FailureTTLCache, VerifiedPDFCache, pdf_cache_key
from .url_validation import is_non_pdf_url
from .routes import (
    PDFRouteAttempt,
    PDFRouteAudit,
    sha256_file,
)
from ..pdf_download import (
    PaperDownloadCandidate,
    is_pdf_bytes,
    preferred_filename,
)

logger = logging.getLogger(__name__)


def is_safe_fetch_url(url: str) -> bool:
    """Reject non-http(s) and private/loopback/link-local/reserved targets.

    Guards against SSRF when the downloader follows URLs parsed out of fetched,
    untrusted content (``citation_pdf_url`` tags, PMC OA ``<link>`` hrefs).
    Public hosts pass; IP literals in private/loopback/
    link-local/reserved ranges and ``localhost`` are blocked, which covers cloud
    metadata endpoints such as ``169.254.169.254``. Hostname-based SSRF (a public
    name that resolves to an internal IP) is out of scope for this static guard.
    """
    try:
        parts = urlparse(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    host = parts.hostname
    if not host:
        return False
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # not an IP literal; treat as a public hostname
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


MAX_CONCURRENCY = 5
MIN_PDF_BYTES = 10_000


@dataclass(frozen=True)
class DownloadResult:
    paper_id: int
    status: Literal["success", "failed", "needs_manual"]
    path: Path | None = None
    provider: str | None = None
    failure_reason: str | None = None
    audit: PDFRouteAudit | None = None


async def download_single(
    candidate: PaperDownloadCandidate,
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> DownloadResult:
    """Use SPC on Mac and server; validate bytes and identity before publishing."""
    import tempfile
    import subprocess
    from .spc_bridge import spc_download

    urls = [url for url in (candidate.url, *candidate.extra_urls) if url]
    if (
        not any((candidate.doi, candidate.arxiv_id, candidate.pmid, candidate.pmcid))
        and urls
        and all(is_non_pdf_url(url) for url in urls)
    ):
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="failed",
            failure_reason="only non-PDF resource URLs supplied",
            audit=PDFRouteAudit(
                paper_id=candidate.paper_id,
                failure_taxonomy="not_pdf",
                attempts=[
                    PDFRouteAttempt(
                        route="spc",
                        skipped=True,
                        error_class="not_pdf",
                        decision_reason="non_pdf_url_pattern",
                    )
                ],
            ),
        )
    if not candidate.doi:
        from dataclasses import replace
        from urllib.parse import unquote

        for url in (candidate.url, *candidate.extra_urls):
            match = re.search(r"10\.\d{4,9}/[^\s?&#]+", unquote(url or ""))
            if match:
                candidate = replace(candidate, doi=match.group(0))
                break
    if not candidate.has_any_identifier():
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="failed",
            failure_reason="no candidate identifier; enrich metadata before acquisition",
            audit=PDFRouteAudit(
                paper_id=candidate.paper_id, failure_taxonomy="no_candidate_identifier"
            ),
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / preferred_filename(candidate)
    cache_key = pdf_cache_key(candidate.doi, candidate.arxiv_id, candidate.title)
    cached = VerifiedPDFCache.from_env(min_bytes=MIN_PDF_BYTES).find(cache_key)
    if cached is not None and not _pdf_identity_failure(candidate, cached):
        if cached.resolve() != output_path.resolve():
            shutil.copy2(cached, output_path)
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="success",
            path=output_path,
            provider="local_cache",
            audit=PDFRouteAudit(
                paper_id=candidate.paper_id,
                successful_route="local_cache",
                cache_hit=True,
                local_path=str(output_path),
                sha256=sha256_file(output_path),
            ),
        )
    failure_cache = FailureTTLCache.from_env()
    if failure_cache.get_fresh(cache_key, "spc", ""):
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="failed",
            failure_reason="SPC failure cache TTL",
            audit=PDFRouteAudit(
                paper_id=candidate.paper_id,
                failure_taxonomy="all_routes_failed",
                attempts=[
                    PDFRouteAttempt(
                        route="spc", skipped=True, decision_reason="failure_cache_ttl"
                    )
                ],
            ),
        )
    async with semaphore:
        try:
            with tempfile.TemporaryDirectory(
                prefix="spc-", dir=output_dir
            ) as temporary:
                source = await asyncio.to_thread(
                    spc_download, candidate, Path(temporary)
                )
                content = source.read_bytes()
                if len(content) < MIN_PDF_BYTES or not is_pdf_bytes(content):
                    raise ValueError("SPC artifact is not a valid PDF")
                failure = _pdf_identity_failure(candidate, source)
                if failure:
                    raise ValueError(f"SPC PDF identity mismatch: {failure}")
                shutil.copy2(source, output_path)
                VerifiedPDFCache.from_env(min_bytes=MIN_PDF_BYTES).store(
                    cache_key, output_path
                )
            audit = PDFRouteAudit(
                paper_id=candidate.paper_id,
                successful_route="spc",
                local_path=str(output_path),
                sha256=sha256_file(output_path),
            )
            return DownloadResult(
                paper_id=candidate.paper_id,
                status="success",
                path=output_path,
                provider="spc",
                audit=audit,
            )
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            from .spc_bridge import SPCAcquisitionError
            from .seed_pack_import import map_spc_failure_class

            code = (
                exc.code if isinstance(exc, SPCAcquisitionError) else type(exc).__name__
            )
            if isinstance(exc, SPCAcquisitionError):
                taxonomy = map_spc_failure_class(code) or "all_routes_failed"
            elif isinstance(exc, subprocess.TimeoutExpired):
                taxonomy = "network_timeout"
            elif "identity mismatch" in str(exc):
                taxonomy = "identity_mismatch"
            elif "not a valid PDF" in str(exc):
                taxonomy = "not_pdf"
            else:
                taxonomy = "all_routes_failed"
            failure_cache.record(cache_key, "spc", "", code)
            return DownloadResult(
                paper_id=candidate.paper_id,
                status="failed",
                failure_reason=str(exc),
                audit=PDFRouteAudit(
                    paper_id=candidate.paper_id,
                    failure_taxonomy=taxonomy,
                    attempts=[PDFRouteAttempt(route="spc", error_class=code)],
                ),
            )


def _pdf_identity_failure(
    candidate: PaperDownloadCandidate, pdf_path: Path
) -> str | None:
    result = audit_pdf_identity(
        paper_id=candidate.paper_id,
        title=candidate.title,
        doi=candidate.doi,
        pmid=candidate.pmid,
        arxiv_id=candidate.arxiv_id,
        pmcid=candidate.pmcid,
        pdf_path=str(pdf_path),
    )
    return None if result.status == "verified" else result.reason


async def download_batch(
    candidates: list[PaperDownloadCandidate],
    output_dir: Path,
    max_concurrency: int = MAX_CONCURRENCY,
) -> list[DownloadResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = [download_single(c, output_dir, semaphore) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    final: list[DownloadResult] = []
    for i, r in enumerate(results):
        if isinstance(r, BaseException):
            logger.warning("Download task %d failed: %s", i, r)
            final.append(
                DownloadResult(
                    paper_id=candidates[i].paper_id,
                    status="failed",
                    failure_reason=str(r),
                )
            )
        else:
            final.append(r)
    return final
