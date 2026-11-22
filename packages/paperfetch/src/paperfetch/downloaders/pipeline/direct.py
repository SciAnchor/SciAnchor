# -*- coding: utf-8 -*-
"""Phase 1 公开资源发现、规范化和传输编排。"""

from __future__ import annotations

import asyncio
import hashlib
from paperfetch.observability import get_event_logger
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

import httpx
from bs4 import BeautifulSoup

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.base import PDFRouteCandidate
from paperfetch.downloaders.pdf_common import redact_url
from paperfetch.downloaders.pipeline.scheduler import (
    DownloadScheduler,
    PDFRouteAttempt,
    _now_iso,
)
from paperfetch.utils.client import configured_proxy_url
from paperfetch.utils.normalizer import (
    extract_pmcid_from_url,
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
)

logger = get_event_logger("paperfetch.downloaders.pipeline.direct")


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "source",
    "campaign",
    "campaign_id",
}
TRACKING_QUERY_PREFIXES = ("utm_",)
MEDRXIV_DOI_PREFIXES = ("10.64898/",)
TRUSTED_OPENALEX_REPOSITORIES: Dict[str, set[str]] = {
    # University of Freiburg's institutional repository. Landing pages and
    # file assets are intentionally constrained to the same official host.
    "freidok.uni-freiburg.de": {"freidok.uni-freiburg.de"},
}
SUPPLEMENTARY_PDF_MARKERS = (
    "-mmc",
    "supplementary",
    "supplement",
    "_si_",
    "-si.",
)
TRUSTED_REPOSITORY_SOURCES = {
    "europe_pmc_doi",
    "europe_pmc",
    "pmc_canonical",
    "pmc_canonical_doi",
    "openalex_repository",
}
MDPI_JOURNAL_SLUG_MAP: Dict[str, str] = {
    "applied-sciences": "applsci",
    "applied sciences": "applsci",
    "applied sci": "applsci",
    "applsci": "applsci",
    "app": "applsci",
    "international journal of molecular sciences": "ijms",
    "int j mol sci": "ijms",
    "ijms": "ijms",
    "journal of marine science and engineering": "jmse",
    "j mar sci eng": "jmse",
    "jmse": "jmse",
    "materials": "materials",
    "sensors": "sensors",
    "molecules": "molecules",
    "nutrients": "nutrients",
    "pharmaceuticals": "pharmaceuticals",
    "cancers": "cancers",
    "sustainability": "sustainability",
    "energies": "energies",
    "water": "water",
    "diagnostics": "diagnostics",
}


def trusted_repository_proxy_mode() -> str:
    """Return the explicit proxy provenance for allowlisted repositories."""
    if configured_proxy_url("DOWNLOAD_PROXY") is not None:
        return "download-proxy"
    return "no-proxy"


def is_medrxiv_doi_capability(doi: str) -> bool:
    """Return whether the DOI namespace itself has a verified medRxiv route."""
    normalized = str(doi or "").strip().lower()
    return any(normalized.startswith(prefix) for prefix in MEDRXIV_DOI_PREFIXES)


@dataclass
class DiscoveredPDFResource:
    """发现器输出的原始公开 PDF 资源。"""

    source: str
    url: str
    referer: Optional[str] = None
    public_access: str = "unknown"
    confidence: str = "medium"
    diagnostics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PDFTransferCandidate:
    """规范化、去重后可交给传输执行器的资源。"""

    url: str
    canonical_url: str
    resource_fingerprint: str
    sources: List[str]
    referer: Optional[str] = None
    public_access: str = "unknown"
    confidence: str = "medium"
    priority: int = 100
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def audit_dict(self) -> Dict[str, Any]:
        return {
            "resource_fingerprint": self.resource_fingerprint,
            "url": redact_url(self.canonical_url),
            "sources": self.sources,
            "referer": self.referer,
            "public_access": self.public_access,
            "confidence": self.confidence,
            "priority": self.priority,
            "diagnostics": self.diagnostics,
        }


def normalize_resource_url(url: str) -> str:
    """生成稳定资源标识；鉴权和签名参数必须完整保留。"""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    default_port = (scheme == "https" and port == 443) or (
        scheme == "http" and port == 80
    )
    netloc = host if default_port or port is None else f"{host}:{port}"
    if parts.username or parts.password:
        credentials = parts.username or ""
        if parts.password:
            credentials += f":{parts.password}"
        netloc = f"{credentials}@{netloc}"
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
        and not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit(
        (scheme, netloc, parts.path or "/", urlencode(query, doseq=True), "")
    )


def resource_fingerprint(url: str) -> str:
    return hashlib.sha256(normalize_resource_url(url).encode("utf-8")).hexdigest()


def normalize_resources(
    resources: Iterable[DiscoveredPDFResource],
) -> tuple[List[PDFTransferCandidate], int]:
    """按完整规范化 URL 合并来源，返回候选和重复数量。"""
    merged: Dict[str, PDFTransferCandidate] = {}
    duplicates = 0
    source_priority = {
        "arxiv": 10,
        "medrxiv_rule": 11,
        "openalex_repository": 18,
        "europe_pmc_doi": 19,
        "metadata": 20,
        "crossref_mdpi_static": 21,
        "frontiers_rule": 22,
        "mdpi_rule": 22,
        "plos_rule": 22,
        "rsna_rule": 22,
        "europe_pmc": 23,
        "pmc_canonical": 24,
        "pmc_canonical_doi": 24,
        "asco_rule": 25,
        "semantic_scholar": 30,
        "unpaywall": 31,
        "crossref_tdm": 40,
        "doi_landing": 50,
    }
    for resource in resources:
        if not resource.url or urlsplit(resource.url).scheme not in {"http", "https"}:
            continue
        canonical = normalize_resource_url(resource.url)
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        priority = source_priority.get(resource.source, 60)
        existing = merged.get(fingerprint)
        if existing:
            duplicates += 1
            if resource.source not in existing.sources:
                existing.sources.append(resource.source)
            existing.priority = min(existing.priority, priority)
            existing.diagnostics.update(resource.diagnostics)
            continue
        merged[fingerprint] = PDFTransferCandidate(
            url=resource.url,
            canonical_url=canonical,
            resource_fingerprint=fingerprint,
            sources=[resource.source],
            referer=resource.referer,
            public_access=resource.public_access,
            confidence=resource.confidence,
            priority=priority,
            diagnostics=dict(resource.diagnostics),
        )
    return sorted(merged.values(), key=lambda item: item.priority), duplicates


class DirectResourceDiscovery:
    """并发执行本地和远程发现，不负责下载 PDF。"""

    def __init__(
        self,
        client: httpx.AsyncClient,
        repository_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.client = client
        self.repository_client = repository_client or client
        self.api_host_semaphores: Dict[str, asyncio.Semaphore] = {
            "api.semanticscholar.org": asyncio.Semaphore(2),
            "api.unpaywall.org": asyncio.Semaphore(2),
            "api.crossref.org": asyncio.Semaphore(2),
            "doi.org": asyncio.Semaphore(2),
            "www.medrxiv.org": asyncio.Semaphore(2),
            "www.ebi.ac.uk": asyncio.Semaphore(2),
            "api.openalex.org": asyncio.Semaphore(2),
            "freidok.uni-freiburg.de": asyncio.Semaphore(2),
        }

    async def discover(
        self, paper: PaperRecord, timeout: float = 10.0
    ) -> tuple[List[DiscoveredPDFResource], List[Dict[str, Any]]]:
        started = time.perf_counter()
        resources = self._local_resources(paper)
        events = [
            self._event(item.source, "found", url=redact_url(item.url), duration_ms=0)
            for item in resources
        ]
        if not paper.doi:
            return resources, events

        # Allowlisted repositories are an exact DOI two-hop (metadata then
        # landing page), so they receive a small independent budget before
        # broad metadata fan-out. This also avoids competing with Europe PMC
        # for the same connection window on constrained proxy links.
        try:
            repository_resources = await asyncio.wait_for(
                self._openalex_repository(paper),
                timeout=min(8.5, max(0.1, timeout)),
            )
            events.append(
                self._event(
                    "openalex_repository",
                    "found" if repository_resources else "no_result",
                    count=len(repository_resources),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            )
            if repository_resources:
                resources.extend(repository_resources)
                return resources, events
        except Exception as exc:
            events.append(
                self._event(
                    "openalex_repository",
                    "error",
                    error_class=type(exc).__name__,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            )

        remaining_strong_budget = timeout - (time.perf_counter() - started)
        if not normalize_pmcid(paper.pmc_id) and remaining_strong_budget > 0.1:
            try:
                epmc = await asyncio.wait_for(
                    self._europe_pmc_doi(paper),
                    timeout=min(5.5, remaining_strong_budget),
                )
                events.append(
                    self._event(
                        "europe_pmc_doi",
                        "found" if epmc else "no_result",
                        count=len(epmc),
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )
                )
                if epmc:
                    resources.extend(epmc)
                    return resources, events
            except Exception as exc:
                events.append(
                    self._event(
                        "europe_pmc_doi",
                        "error",
                        error_class=type(exc).__name__,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                    )
                )

        tasks = {
            asyncio.create_task(self._semantic_scholar(paper.doi)): "semantic_scholar",
            asyncio.create_task(self._unpaywall(paper.doi)): "unpaywall",
            asyncio.create_task(self._crossref(paper.doi)): "crossref_tdm",
            asyncio.create_task(self._doi_landing(paper.doi)): "doi_landing",
        }
        if is_medrxiv_doi_capability(paper.doi):
            tasks[asyncio.create_task(self._medrxiv_resource(paper.doi))] = (
                "medrxiv_rule"
            )
        cancelled_tasks: List[asyncio.Task] = []
        elapsed = time.perf_counter() - started
        deadline = time.monotonic() + max(0.0, timeout - elapsed)
        try:
            while tasks and time.monotonic() < deadline:
                done, _ = await asyncio.wait(
                    tasks,
                    timeout=max(0.0, deadline - time.monotonic()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    break
                for task in done:
                    source = tasks.pop(task, None)
                    if source is None:
                        # 同批完成的 OA 任务可能已被另一个成功结果回收。
                        continue
                    try:
                        found = task.result()
                        resources.extend(found)
                        events.append(
                            self._event(
                                source,
                                "found" if found else "no_result",
                                count=len(found),
                                duration_ms=int((time.perf_counter() - started) * 1000),
                            )
                        )
                        # 行内注释：如果已发现高置信度的官方静态资源或直接规则，提前短路返回，无需等待慢速第三方 API
                        if any(
                            r.confidence == "high"
                            and r.public_access == "open"
                            and r.source
                            in {
                                "crossref_mdpi_static",
                                "crossref_tdm",
                                "pmc_canonical",
                                "medrxiv_rule",
                            }
                            for r in resources
                        ):
                            break
                    except Exception as exc:
                        events.append(
                            self._event(
                                source,
                                "error",
                                error_class=type(exc).__name__,
                                duration_ms=int((time.perf_counter() - started) * 1000),
                            )
                        )
        finally:
            for task, source in tasks.items():
                task.cancel()
                events.append(
                    self._event(
                        source, "cancelled", reason="discovery_budget_exhausted"
                    )
                )
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if cancelled_tasks:
                await asyncio.gather(*cancelled_tasks, return_exceptions=True)
        return resources, events

    @staticmethod
    def _event(source: str, result: str, **diagnostics: Any) -> Dict[str, Any]:
        return {"source": source, "result": result, **diagnostics}

    def _local_resources(self, paper: PaperRecord) -> List[DiscoveredPDFResource]:
        found: List[DiscoveredPDFResource] = []
        status = paper.fulltext_status
        status.oa_declaration_status = (
            "declared_open"
            if str(status.oa_status or "").lower() in {"open", "oa", "gold", "green"}
            else "not_declared_open"
        )
        if paper.arxiv_id:
            found.append(
                DiscoveredPDFResource(
                    "arxiv",
                    f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf",
                    public_access="open",
                    confidence="high",
                )
            )
        for item in status.pdf_candidates:
            url = (
                (item.get("url") or item.get("pdf_url"))
                if isinstance(item, dict)
                else None
            )
            if url:
                found.append(
                    DiscoveredPDFResource(
                        str(item.get("source") or "metadata"),
                        str(url),
                        item.get("referer"),
                        "declared",
                        "high",
                    )
                )
        if status.pdf_url:
            found.append(
                DiscoveredPDFResource(
                    str(status.pdf_source or "metadata"),
                    status.pdf_url,
                    public_access="declared",
                    confidence="high",
                )
            )
        pmcid = normalize_pmcid(paper.pmc_id)
        if not pmcid:
            known_urls = [status.pdf_url]
            known_urls.extend(
                (item.get("url") or item.get("pdf_url"))
                for item in status.pdf_candidates
                if isinstance(item, dict)
            )
            pmcid = next(
                (
                    extracted
                    for candidate_url in known_urls
                    if (extracted := extract_pmcid_from_url(candidate_url))
                ),
                None,
            )
        if pmcid:
            paper.pmc_id = pmcid
            found.extend(
                [
                    DiscoveredPDFResource(
                        "pmc_canonical",
                        f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/",
                        f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
                        "declared",
                        "high",
                        diagnostics={"pmcid_source": "paper_or_normalized_resource"},
                    ),
                    DiscoveredPDFResource(
                        "europe_pmc",
                        f"https://europepmc.org/articles/{pmcid}?pdf=render",
                        f"https://europepmc.org/article/MED/{pmcid}",
                        "declared",
                        "medium",
                        diagnostics={"pmcid_source": "paper_or_normalized_resource"},
                    ),
                ]
            )
        doi = (paper.doi or "").strip()
        if doi.startswith("10.3389/"):
            found.append(
                DiscoveredPDFResource(
                    "frontiers_rule",
                    f"https://www.frontiersin.org/articles/{doi}/pdf",
                    public_access="open",
                    confidence="high",
                )
            )
        elif doi.startswith("10.3390/"):
            found.append(
                DiscoveredPDFResource(
                    "mdpi_rule",
                    f"https://www.mdpi.com/{doi}/pdf",
                    public_access="open",
                    confidence="high",
                )
            )
        elif doi.startswith("10.1371/"):
            found.append(
                DiscoveredPDFResource(
                    "plos_rule",
                    f"https://journals.plos.org/plosone/article/file?id={doi}&type=printable",
                    public_access="open",
                    confidence="high",
                )
            )
        elif doi.lower().startswith("10.1200/"):
            found.append(
                DiscoveredPDFResource(
                    "asco_rule",
                    f"https://ascopubs.org/doi/pdf/{doi}",
                    f"https://ascopubs.org/doi/{doi}",
                    "declared",
                    "medium",
                )
            )
        elif doi.lower().startswith("10.1148/"):
            found.append(
                DiscoveredPDFResource(
                    "rsna_rule",
                    f"https://pubs.rsna.org/doi/pdf/{doi}",
                    f"https://pubs.rsna.org/doi/{doi}",
                    "open",
                    "high",
                    diagnostics={"publisher_rule": "rsna_official_pdf"},
                )
            )
        return found

    async def _get(self, host: str, url: str, **kwargs: Any) -> httpx.Response:
        async with self.api_host_semaphores[host]:
            return await self.client.get(url, timeout=5.0, **kwargs)

    async def _head(self, host: str, url: str, **kwargs: Any) -> httpx.Response:
        async with self.api_host_semaphores[host]:
            return await self.client.head(url, timeout=5.0, **kwargs)

    async def _repository_get(
        self, host: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        async with self.api_host_semaphores[host]:
            return await self.repository_client.get(url, timeout=5.0, **kwargs)

    async def _semantic_scholar(self, doi: str) -> List[DiscoveredPDFResource]:
        keys = [
            item.strip()
            for item in os.getenv("SEMANTIC_SCHOLAR_API_KEYS", "").split(",")
            if item.strip()
        ]
        headers = {"x-api-key": keys[0]} if keys else {}
        response = await self._get(
            "api.semanticscholar.org",
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='')}?fields=openAccessPdf",
            headers=headers,
        )
        if response.status_code != 200:
            return []
        item = response.json().get("openAccessPdf") or {}
        return (
            [
                DiscoveredPDFResource(
                    "semantic_scholar",
                    item["url"],
                    public_access="open",
                    confidence="high",
                )
            ]
            if item.get("url")
            else []
        )

    async def _unpaywall(self, doi: str) -> List[DiscoveredPDFResource]:
        email = os.getenv("UNPAYWALL_EMAIL") or os.getenv("OPENALEX_MAILTO")
        if not email:
            return []
        response = await self._get(
            "api.unpaywall.org",
            f"https://api.unpaywall.org/v2/{quote(doi, safe='')}?email={quote(email)}",
        )
        if response.status_code != 200:
            return []
        payload = response.json()
        locations = [
            payload.get("best_oa_location") or {},
            *(payload.get("oa_locations") or []),
        ]
        resources: list[DiscoveredPDFResource] = []
        seen: set[str] = set()
        for location in locations:
            url = str(location.get("url_for_pdf") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            resources.append(
                DiscoveredPDFResource(
                    "unpaywall",
                    url,
                    location.get("url"),
                    "open",
                    "high" if location == locations[0] else "medium",
                    diagnostics={
                        "host_type": location.get("host_type"),
                        "version": location.get("version"),
                    },
                )
            )
        return resources

    async def _crossref(self, doi: str) -> List[DiscoveredPDFResource]:
        response = await self._get(
            "api.crossref.org", f"https://api.crossref.org/works/{quote(doi, safe='')}"
        )
        if response.status_code != 200:
            return []
        message = response.json().get("message") or {}
        links = message.get("link") or []
        resources = [
            DiscoveredPDFResource(
                "crossref_tdm",
                item["URL"],
                public_access="unknown",
                confidence="medium",
                diagnostics={"intended_application": item.get("intended-application")},
            )
            for item in links
            if item.get("URL")
            and str(item.get("content-type", "")).lower() == "application/pdf"
        ]
        institutions = message.get("institution") or []
        if isinstance(institutions, dict):
            institutions = [institutions]
        is_medrxiv = any(
            str(item.get("name") or "").strip().lower() == "medrxiv"
            for item in institutions
            if isinstance(item, dict)
        )
        # New medRxiv DOI namespaces are resolved independently in discover(),
        # so a Crossref timeout cannot suppress the official route. Crossref
        # institution metadata remains a fallback for legacy DOI namespaces.
        if is_medrxiv and not is_medrxiv_doi_capability(doi):
            resources = [*await self._medrxiv_resource(doi), *resources]
        if doi.lower().startswith("10.3390/"):
            journal_name = str(
                (
                    message.get("short-container-title")
                    or message.get("container-title")
                    or [""]
                )[0]
            )
            raw_slug = re.sub(r"[^a-z0-9]+", "-", journal_name.lower()).strip("-")
            volume = str(message.get("volume") or "").strip()
            article = str(
                message.get("article-number") or message.get("page") or ""
            ).strip()

            # 行内注释：解析 DOI 路径标识，如 10.3390/app11010312 -> app
            doi_match = re.match(r"^10\.3390/([a-zA-Z]+)", doi, re.IGNORECASE)
            doi_slug = doi_match.group(1).lower() if doi_match else ""

            resolved_slugs: list[str] = []
            for candidate_key in (raw_slug, journal_name.lower(), doi_slug):
                if candidate_key in MDPI_JOURNAL_SLUG_MAP:
                    mapped = MDPI_JOURNAL_SLUG_MAP[candidate_key]
                    if mapped not in resolved_slugs:
                        resolved_slugs.append(mapped)
            if raw_slug and raw_slug not in resolved_slugs:
                resolved_slugs.append(raw_slug)
            if doi_slug and doi_slug not in resolved_slugs:
                resolved_slugs.append(doi_slug)

            seen_slugs: set[str] = set()
            for slug in resolved_slugs:
                if (
                    slug
                    and slug not in seen_slugs
                    and volume.isdigit()
                    and article.isdigit()
                ):
                    seen_slugs.add(slug)
                    article_code = f"{slug}-{int(volume):02d}-{int(article):05d}"
                    resources.append(
                        DiscoveredPDFResource(
                            "crossref_mdpi_static",
                            f"https://mdpi-res.com/d_attachment/{slug}/{article_code}/article_deploy/{article_code}.pdf",
                            public_access="open",
                            confidence="high",
                            diagnostics={
                                "crossref_derived": True,
                                "journal_slug": slug,
                            },
                        )
                    )
        return resources

    async def _europe_pmc_doi(self, paper: PaperRecord) -> List[DiscoveredPDFResource]:
        """Recover strong PMC/PMID identifiers from an exact DOI match."""
        if normalize_pmcid(paper.pmc_id):
            return []
        expected_doi = normalize_doi(paper.doi)
        if not expected_doi:
            return []
        query = quote(f"DOI:{expected_doi}", safe="")
        response = await self._get(
            "www.ebi.ac.uk",
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query={query}&format=json&pageSize=5",
        )
        if response.status_code != 200:
            return []
        if (response.url.host or "").lower() not in {"www.ebi.ac.uk", "ebi.ac.uk"}:
            return []
        results = (response.json().get("resultList") or {}).get("result") or []
        exact = next(
            (
                item
                for item in results
                if isinstance(item, dict)
                and normalize_doi(item.get("doi")) == expected_doi
            ),
            None,
        )
        if not exact:
            return []
        if any(
            str(exact.get(flag) or "").strip().upper() != "Y"
            for flag in ("isOpenAccess", "inEPMC", "hasPDF")
        ):
            return []
        pmcid = normalize_pmcid(exact.get("pmcid"))
        pmid = normalize_pmid(exact.get("pmid"))
        if not pmcid:
            return []
        current_pmcid = normalize_pmcid(paper.pmc_id)
        current_pmid = normalize_pmid(paper.pubmed_id)
        if current_pmcid and current_pmcid != pmcid:
            return []
        if current_pmid and pmid and current_pmid != pmid:
            return []
        paper.pmc_id = pmcid
        if pmid:
            paper.pubmed_id = pmid
        diagnostics = {
            "identifier_source": "europe_pmc_exact_doi",
            "pmcid": pmcid,
            "pmid": pmid,
            "is_open_access": True,
            "in_epmc": True,
            "has_pdf": True,
        }
        return [
            DiscoveredPDFResource(
                "europe_pmc_doi",
                f"https://europepmc.org/articles/{pmcid}?pdf=render",
                f"https://europepmc.org/article/MED/{pmid or pmcid}",
                "open",
                "high",
                diagnostics=diagnostics,
            ),
            DiscoveredPDFResource(
                "pmc_canonical_doi",
                f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/",
                f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
                "open",
                "high",
                diagnostics=diagnostics,
            ),
        ]

    @staticmethod
    def _repository_pdf_urls(
        html_content: str,
        landing_url: str,
        allowed_pdf_hosts: set[str],
    ) -> List[str]:
        """Extract same-policy main-text PDFs from a trusted repository page."""
        soup = BeautifulSoup(html_content, "lxml")
        raw_urls: List[str] = []
        for meta in soup.find_all("meta"):
            name = str(meta.get("name") or meta.get("property") or "").strip().lower()
            content = str(meta.get("content") or "").strip()
            if name in {"citation_pdf_url", "dc.identifier", "og:pdf"} and content:
                raw_urls.append(content)
        raw_urls.extend(
            str(anchor.get("href") or "").strip()
            for anchor in soup.find_all("a", href=True)
        )

        results: List[str] = []
        seen: set[str] = set()
        for raw_url in raw_urls:
            if not raw_url:
                continue
            resolved = urljoin(landing_url, raw_url)
            parts = urlsplit(resolved)
            host = (parts.hostname or "").lower()
            decoded_path = unquote(parts.path).lower()
            if host not in allowed_pdf_hosts or not decoded_path.endswith(".pdf"):
                continue
            if any(marker in decoded_path for marker in SUPPLEMENTARY_PDF_MARKERS):
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            results.append(resolved)
        return results

    async def _openalex_repository(
        self, paper: PaperRecord
    ) -> List[DiscoveredPDFResource]:
        """Resolve allowlisted institutional-repository landings from exact OpenAlex DOI data."""
        expected_doi = normalize_doi(paper.doi)
        if not expected_doi:
            return []
        response = await self._repository_get(
            "api.openalex.org",
            f"https://api.openalex.org/works/https://doi.org/{expected_doi}",
        )
        if (
            response.status_code != 200
            or (response.url.host or "").lower() != "api.openalex.org"
        ):
            return []
        payload = response.json()
        if normalize_doi(payload.get("doi")) != expected_doi:
            return []

        ids = payload.get("ids") if isinstance(payload.get("ids"), dict) else {}
        recovered_pmid = normalize_pmid(ids.get("pmid"))
        current_pmid = normalize_pmid(paper.pubmed_id)
        if recovered_pmid and (not current_pmid or current_pmid == recovered_pmid):
            paper.pubmed_id = recovered_pmid

        resources: List[DiscoveredPDFResource] = []
        seen_landings: set[str] = set()
        for location in payload.get("locations") or []:
            if not isinstance(location, dict):
                continue
            landing_url = str(location.get("landing_page_url") or "").strip()
            landing_host = (urlsplit(landing_url).hostname or "").lower()
            allowed_pdf_hosts = TRUSTED_OPENALEX_REPOSITORIES.get(landing_host)
            if not landing_url or not allowed_pdf_hosts or landing_url in seen_landings:
                continue
            seen_landings.add(landing_url)
            landing_response = await self._repository_get(
                landing_host,
                landing_url,
                headers={"Accept": "text/html"},
                follow_redirects=True,
            )
            final_landing_url = str(landing_response.url)
            final_landing_host = (landing_response.url.host or "").lower()
            if (
                landing_response.status_code != 200
                or final_landing_host != landing_host
                or "html"
                not in str(landing_response.headers.get("content-type") or "").lower()
            ):
                continue
            for pdf_url in self._repository_pdf_urls(
                landing_response.text,
                final_landing_url,
                allowed_pdf_hosts,
            ):
                resources.append(
                    DiscoveredPDFResource(
                        "openalex_repository",
                        pdf_url,
                        final_landing_url,
                        "open",
                        "high",
                        diagnostics={
                            "identifier_source": "openalex_exact_doi",
                            "repository_host": landing_host,
                            "version": location.get("version"),
                            "pmid": recovered_pmid,
                        },
                    )
                )
        return resources

    async def _medrxiv_resource(self, doi: str) -> List[DiscoveredPDFResource]:
        resource = await self._medrxiv_canonical_pdf(doi)
        return [resource] if resource else []

    async def _medrxiv_canonical_pdf(self, doi: str) -> DiscoveredPDFResource | None:
        normalized_doi = doi.strip().lower()
        versionless_pdf = f"https://www.medrxiv.org/content/{normalized_doi}.full.pdf"
        try:
            response = await self._head(
                "www.medrxiv.org",
                versionless_pdf,
                headers={"Accept": "application/pdf"},
                follow_redirects=True,
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        content_type = str(response.headers.get("content-type") or "").lower()
        final_url = str(response.url)
        parts = urlsplit(final_url)
        host = (parts.hostname or "").lower()
        path = unquote(parts.path)
        match = re.fullmatch(
            rf"/content/{re.escape(normalized_doi)}v(\d+)\.full\.pdf",
            path,
            flags=re.IGNORECASE,
        )
        if (
            host not in {"medrxiv.org", "www.medrxiv.org"}
            or not match
            or "application/pdf" not in content_type
        ):
            return None
        canonical_version = f"v{match.group(1)}"
        article_url = final_url[: -len(".full.pdf")]
        return DiscoveredPDFResource(
            "medrxiv_rule",
            final_url,
            article_url,
            "open",
            "high",
            diagnostics={
                "publisher_rule": "medrxiv_official_pdf",
                "canonical_version": canonical_version,
                "version_resolution": "official_versionless_pdf_redirect",
            },
        )

    async def _doi_landing(self, doi: str) -> List[DiscoveredPDFResource]:
        url = f"https://doi.org/{quote(doi, safe='/')}"
        async with self.api_host_semaphores["doi.org"]:
            async with self.client.stream(
                "GET", url, headers={"Accept": "text/html,application/pdf"}, timeout=5.0
            ) as response:
                if response.status_code != 200:
                    return []
                content_type = response.headers.get("content-type", "").lower()
                final_url = str(response.url)
                if "application/pdf" in content_type:
                    return [
                        DiscoveredPDFResource(
                            "doi_landing", final_url, url, "unknown", "medium"
                        )
                    ]
                if "html" not in content_type:
                    return []
                body = await response.aread()
        from paperfetch.downloaders.pdf_common import find_pdf_link_from_html

        pdf_url = find_pdf_link_from_html(
            body[:2_000_000].decode("utf-8", errors="ignore"), final_url
        )
        return (
            [
                DiscoveredPDFResource(
                    "doi_landing", pdf_url, final_url, "unknown", "medium"
                )
            ]
            if pdf_url
            else []
        )


class DirectDownloadPipeline:
    """在单篇 45 秒截止时间内执行官方 API 和公开资源传输。"""

    TOTAL_BUDGET_SECONDS = 45.0
    DISCOVERY_BUDGET_SECONDS = 10.0
    # 验收默认要求 Phase 1 p95 <= 12.5 秒；官方 API 失败预算必须低于门禁，
    # 才能及时让出执行权给公开资源发现。
    API_BUDGET_SECONDS = 12.0
    RESOURCE_BUDGET_SECONDS = 20.0
    TRUSTED_REPOSITORY_RESOURCE_BUDGET_SECONDS = 120.0
    TRUSTED_REPOSITORY_TOTAL_BUDGET_SECONDS = 150.0
    MAX_PUBLIC_RESOURCES = 6

    def __init__(self, scheduler: DownloadScheduler) -> None:
        self.scheduler = scheduler
        repository_client = (
            scheduler.shared_client
            if trusted_repository_proxy_mode() != "no-proxy"
            and hasattr(scheduler, "shared_client")
            else scheduler.direct_client
        )
        self.discovery = DirectResourceDiscovery(
            scheduler.direct_client,
            repository_client=repository_client,
        )

    def _record_timeout(
        self,
        paper: PaperRecord,
        candidate: PDFRouteCandidate,
        duration_ms: int,
        reason: str,
    ) -> None:
        status = paper.fulltext_status
        last = status.download_attempts[-1] if status.download_attempts else {}
        if (
            last.get("route") == candidate.route
            and last.get("error_class") == "timeout"
        ):
            return
        now = _now_iso()
        proxy_mode = str(candidate.metadata.get("proxy_mode") or "no-proxy")
        attempt = PDFRouteAttempt(
            candidate.route,
            candidate.url,
            candidate.host,
            error_class="timeout",
            error=reason,
            proxy_policy=proxy_mode,
            proxy_mode=proxy_mode,
            client_kind=(
                "direct_client"
                if proxy_mode in {"none", "no_proxy", "no-proxy", "direct"}
                else "shared_client"
            ),
            started_at=now,
            ended_at=now,
            duration_ms=duration_ms,
            decision_reason=reason,
            diagnostics={
                "resource_fingerprint": candidate.metadata.get("resource_fingerprint"),
                "client_config": {"proxy_mode": "no-proxy", "trust_env": False},
            },
        )
        mark_route = getattr(self.scheduler, "_mark_route", None)
        record_attempt = getattr(self.scheduler, "_record_attempt", None)
        if mark_route and record_attempt:
            mark_route(status, candidate.route)
            record_attempt(status, attempt)
        else:
            if candidate.route not in status.attempted_routes:
                status.attempted_routes.append(candidate.route)
            status.download_attempts.append(attempt.audit_dict())
            status.failure_stage = candidate.route
            status.failure_taxonomy = "timeout"
        if not getattr(self.scheduler, "no_cache", True) and hasattr(
            self.scheduler, "cache"
        ):
            self.scheduler.cache.record_failure(paper, candidate, attempt)
        logger.info(
            "[PDF 传输] DEGRADED：当前路由超时，继续后续路由，DOI=%s，出版社=%s，transport=%s，route=%s，错误=timeout，耗时=%dms",
            paper.doi or paper.paper_id,
            paper.publisher or paper.journal or paper.venue or "未知",
            candidate.metadata.get("transport") or candidate.route,
            candidate.route,
            duration_ms,
        )

    async def run(
        self,
        paper: PaperRecord,
        target_file: str,
        api_candidates: List[PDFRouteCandidate],
        on_candidate_attempt: Any = None,
    ) -> None:
        started = time.monotonic()
        deadline = started + self.TOTAL_BUDGET_SECONDS
        status = paper.fulltext_status

        configured_api = [
            item
            for item in api_candidates
            if not item.metadata.get("missing_credentials")
        ]
        for skipped in [
            item for item in api_candidates if item.metadata.get("missing_credentials")
        ]:
            status.discovery_events.append(
                {
                    "source": skipped.route,
                    "result": "planned_skip",
                    "reason": "missing_credentials",
                }
            )
        if configured_api:
            try:
                await asyncio.wait_for(
                    self.scheduler.attempt_candidates(
                        paper,
                        configured_api,
                        target_file,
                        on_candidate_attempt=on_candidate_attempt,
                    ),
                    timeout=min(
                        self.API_BUDGET_SECONDS, max(0.001, deadline - time.monotonic())
                    ),
                )
            except asyncio.TimeoutError:
                status.discovery_events.append(
                    {
                        "source": "official_api",
                        "result": "timeout",
                        "duration_ms": int(self.API_BUDGET_SECONDS * 1000),
                    }
                )
                self._record_timeout(
                    paper,
                    configured_api[0],
                    int(self.API_BUDGET_SECONDS * 1000),
                    "official_api_budget_exhausted",
                )
        if status.download_status == "downloaded" or time.monotonic() >= deadline:
            return

        resources, events = await self.discovery.discover(
            paper,
            timeout=min(
                self.DISCOVERY_BUDGET_SECONDS, max(0.0, deadline - time.monotonic())
            ),
        )
        normalization_started = time.perf_counter()
        candidates, duplicate_count = normalize_resources(resources)
        if any(
            TRUSTED_REPOSITORY_SOURCES.intersection(item.sources) for item in candidates
        ):
            deadline = max(
                deadline,
                started + self.TRUSTED_REPOSITORY_TOTAL_BUDGET_SECONDS,
            )
        normalization_duration_ms = int(
            (time.perf_counter() - normalization_started) * 1000
        )
        status.discovery_events.extend(events)
        status.normalized_resources = [item.audit_dict() for item in candidates]
        status.discovery_events.append(
            {
                "source": "normalization",
                "result": "completed",
                "resource_count": len(candidates),
                "duplicate_count": duplicate_count,
                "duration_ms": normalization_duration_ms,
            }
        )
        logger.info(
            "[PDF 发现] 完成，DOI=%s，出版社=%s，来源=%s，资源数=%d，重复数=%d，耗时=%dms",
            paper.doi or paper.paper_id,
            paper.publisher or paper.journal or paper.venue or "未知",
            "+".join(sorted({source for item in candidates for source in item.sources}))
            or "无",
            len(candidates),
            duplicate_count,
            int((time.monotonic() - started) * 1000),
        )

        browser_used = False
        for item in candidates[: self.MAX_PUBLIC_RESOURCES]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status.discovery_events.append(
                    {
                        "source": "phase1_budget",
                        "result": "exhausted",
                        "duration_ms": int((time.monotonic() - started) * 1000),
                    }
                )
                break
            trusted_repository = bool(
                TRUSTED_REPOSITORY_SOURCES.intersection(item.sources)
            )
            resource_budget = (
                self.TRUSTED_REPOSITORY_RESOURCE_BUDGET_SECONDS
                if trusted_repository
                else self.RESOURCE_BUDGET_SECONDS
            )
            from paperfetch.core.settings import get_settings

            proxy_mode = (
                trusted_repository_proxy_mode()
                if TRUSTED_REPOSITORY_SOURCES.intersection(item.sources)
                else "download-proxy"
                if configured_proxy_url("DOWNLOAD_PROXY") is not None
                and (get_settings().text("DOWNLOAD_PROXY_MODE") or "").lower()
                not in {"direct", "none", "no_proxy"}
                else "no-proxy"
            )
            candidate = PDFRouteCandidate(
                "public_http",
                url=item.url,
                referer=item.referer,
                priority=item.priority,
                source="+".join(item.sources),
                metadata={
                    "resource_fingerprint": item.resource_fingerprint,
                    "canonical_url": item.canonical_url,
                    "discovery_sources": item.sources,
                    "transport": "http",
                    "anonymous_auth": True,
                    "proxy_mode": proxy_mode,
                    "attempt_timeout_seconds": max(
                        0.1, min(resource_budget, remaining) - 0.25
                    ),
                    "decision_reason": (
                        "trusted_repository_resource"
                        if trusted_repository
                        else "normalized_public_resource"
                    ),
                },
            )
            try:
                outer_timeout = min(resource_budget + 0.25, remaining)
                await asyncio.wait_for(
                    self.scheduler.attempt_candidates(
                        paper,
                        [candidate],
                        target_file,
                        on_candidate_attempt=on_candidate_attempt,
                    ),
                    timeout=outer_timeout,
                )
            except asyncio.TimeoutError:
                status.discovery_events.append(
                    {
                        "source": "+".join(item.sources),
                        "result": "timeout",
                        "resource_fingerprint": item.resource_fingerprint,
                    }
                )
                self._record_timeout(
                    paper,
                    candidate,
                    int(outer_timeout * 1000),
                    "phase1_resource_budget_exhausted",
                )
            if status.download_status == "downloaded":
                status.oa_transport_status = "retrievable"
                break
            last_attempt = (
                status.download_attempts[-1] if status.download_attempts else {}
            )
            known_public_browser_fallback = (
                "rsna_rule" in item.sources
                and last_attempt.get("error_class")
                in {"auth_required", "publisher_challenge"}
            )
            if (
                not browser_used
                and (
                    last_attempt.get("error_class") == "html_dynamic"
                    or known_public_browser_fallback
                )
                and deadline - time.monotonic() > 0
            ):
                browser_used = True
                browser_candidate = PDFRouteCandidate(
                    "public_browser",
                    url=item.url,
                    referer=item.referer,
                    priority=item.priority,
                    source="+".join(item.sources),
                    metadata={
                        "resource_fingerprint": item.resource_fingerprint,
                        "transport": "browser",
                        "anonymous_auth": True,
                        "proxy_mode": "no-proxy",
                        "ordinary_html_confirmed": not known_public_browser_fallback,
                        "known_public_pdf": known_public_browser_fallback,
                        "decision_reason": (
                            "allowlisted_known_public_publisher_pdf"
                            if known_public_browser_fallback
                            else "allowlisted_ordinary_dynamic_html"
                        ),
                    },
                )
                try:
                    await asyncio.wait_for(
                        self.scheduler.attempt_candidates(
                            paper,
                            [browser_candidate],
                            target_file,
                            on_candidate_attempt=on_candidate_attempt,
                        ),
                        timeout=min(
                            self.RESOURCE_BUDGET_SECONDS,
                            max(0.001, deadline - time.monotonic()),
                        ),
                    )
                except asyncio.TimeoutError:
                    status.discovery_events.append(
                        {
                            "source": "public_browser",
                            "result": "timeout",
                            "resource_fingerprint": item.resource_fingerprint,
                        }
                    )
                    self._record_timeout(
                        paper,
                        browser_candidate,
                        int(
                            min(
                                self.RESOURCE_BUDGET_SECONDS,
                                max(0.001, deadline - time.monotonic()),
                            )
                            * 1000
                        ),
                        "phase1_browser_budget_exhausted",
                    )
                if status.download_status == "downloaded":
                    status.oa_transport_status = "retrievable"
                    break
        if (
            status.download_status != "downloaded"
            and status.oa_declaration_status == "declared_open"
        ):
            status.oa_transport_status = "not_retrieved"
