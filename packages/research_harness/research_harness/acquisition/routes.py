"""RH-native route audit primitives for PDF acquisition."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..pdf_download import PaperDownloadCandidate


FAILURE_TAXONOMY = frozenset(
    {
        "not_pdf",
        "too_small",
        "http_401",
        "http_403",
        "http_404",
        "rate_limited",
        "browser_challenge",
        "paywall",
        "identity_mismatch",
        "network_timeout",
        "disabled_by_config",
        "policy_gate_missing",
        "credentials_missing",
        "auth_failed",
        "optional_dependency_missing",
        "optional_route_unavailable",
        "optional_route_circuit_open",
        "no_candidate_identifier",
        "no_direct_pdf_metadata",
        "all_routes_failed",
        # External/imported acquisition classes. ``subscription_required``
        # means the reported source lacks entitlement for the item: auto-retry
        # is pointless and the paper belongs in the manual queue. This is
        # distinct from ``paywall`` (generic access wall) and
        # ``browser_challenge`` (technical, human-recoverable). ``external_*``
        # classes only appear on audits imported from external acquisition
        # tools.
        "subscription_required",
        "external_not_attempted",
        "external_unmapped",
    }
)

_SECRET_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "awsaccesskeyid",
        "code",
        "credential",
        "key",
        "password",
        "secret",
        "signature",
        "sig",
        "session",
        "sessionid",
        "token",
        "x-amz-credential",
        "x-amz-signature",
    }
)

_ROUTE_PRIORITY = {
    "metadata_open_access": 190,
    "arxiv": 185,
    "openreview": 180,
    "pmc": 175,
    "publisher_html": 130,
    # content.openalex.org needs credentials RH does not use; ranked below
    # public OA routes so its 401 never shadows a working link.
    "openalex_content": 100,
    "doi_landing": 80,
    "optional_plugin": 60,
}


def redact_url(url: str | None) -> str | None:
    if not url:
        return url
    parsed = urlparse(url)
    netloc = parsed.netloc
    pairs = []
    changed = False
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        netloc = f"REDACTED@{host}"
        changed = True
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _SECRET_QUERY_KEYS:
            pairs.append((key, "REDACTED"))
            changed = True
        else:
            pairs.append((key, value))
    if not changed:
        return url
    return urlunparse(
        parsed._replace(netloc=netloc, query=urlencode(pairs, doseq=True))
    )


def host_for_url(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower()


@dataclass(frozen=True)
class PDFRouteCandidate:
    route: str
    url: str | None = None
    source: str = "resolver"
    priority: int = 100
    requires_browser: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def host(self) -> str:
        return host_for_url(self.url) or self.route

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "url": redact_url(self.url),
            "host": self.host,
            "source": self.source,
            "priority": self.priority,
            "requires_browser": self.requires_browser,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PDFRouteAttempt:
    route: str
    url: str | None = None
    host: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    error_class: str | None = None
    error: str | None = None
    skipped: bool = False
    cache_hit: bool = False
    cache_miss: bool = False
    bytes_downloaded: int | None = None
    duration_ms: int | None = None
    decision_reason: str | None = None
    final_url_host: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "url": redact_url(self.url),
            "host": self.host or host_for_url(self.url) or self.route,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "error_class": self.error_class,
            "error": self.error,
            "skipped": self.skipped,
            "cache_hit": self.cache_hit,
            "cache_miss": self.cache_miss,
            "bytes_downloaded": self.bytes_downloaded,
            "duration_ms": self.duration_ms,
            "decision_reason": self.decision_reason,
            "final_url_host": self.final_url_host,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class PDFRouteAudit:
    paper_id: int
    candidates: list[PDFRouteCandidate] = field(default_factory=list)
    attempts: list[PDFRouteAttempt] = field(default_factory=list)
    successful_route: str | None = None
    resolved_pdf_url: str | None = None
    failure_taxonomy: str | None = None
    cache_hit: bool = False
    sha256: str | None = None
    local_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        attempted_routes = []
        for attempt in self.attempts:
            if attempt.route not in attempted_routes:
                attempted_routes.append(attempt.route)
        return {
            "schema_version": "rh.pdf_route_audit.v1",
            "paper_id": self.paper_id,
            "candidate_pdf_urls": [
                candidate.to_dict() for candidate in self.candidates
            ],
            "attempted_routes": attempted_routes,
            "successful_route": self.successful_route,
            "resolved_pdf_url": redact_url(self.resolved_pdf_url),
            "failure_taxonomy": self.failure_taxonomy,
            "cache_hit": self.cache_hit,
            "sha256": self.sha256,
            "local_path": self.local_path,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }


def build_route_candidates(
    candidate: PaperDownloadCandidate, urls: Iterable[str]
) -> list[PDFRouteCandidate]:
    indexed: list[tuple[int, PDFRouteCandidate]] = []
    seen: set[str] = set()
    for index, url in enumerate(urls):
        clean = (url or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        route = route_for_url(candidate, clean)
        indexed.append(
            (
                index,
                PDFRouteCandidate(
                    route=route,
                    url=clean,
                    source=source_for_route(route, clean),
                    priority=_ROUTE_PRIORITY.get(route, 0),
                    requires_browser=route == "optional_plugin",
                ),
            )
        )
    return [
        item
        for _, item in sorted(indexed, key=lambda pair: (-pair[1].priority, pair[0]))
    ]


def route_for_url(candidate: PaperDownloadCandidate, url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()
    if host == "content.openalex.org":
        return "openalex_content"
    if candidate.url and url == candidate.url:
        return "metadata_open_access"
    if host.endswith("arxiv.org") and path.startswith("/pdf/"):
        return "arxiv"
    if host.endswith("openreview.net") and path.startswith("/pdf"):
        return "openreview"
    if (
        "europepmc.org" in host
        or "ncbi.nlm.nih.gov" in host
        or "pmc.ncbi.nlm.nih.gov" in host
    ):
        return "pmc"
    if host == "doi.org" or host.endswith(".doi.org"):
        return "doi_landing"
    if path.endswith(".pdf") or "pdf" in path or "pdf=render" in query:
        return "metadata_open_access"
    return "publisher_html"


def source_for_route(route: str, url: str) -> str:
    if route == "arxiv":
        return "arxiv"
    if route == "openreview":
        return "openreview"
    if route == "pmc":
        return "pmc"
    if route == "openalex_content":
        return "openalex"
    if route == "doi_landing":
        return "doi"
    if route == "metadata_open_access":
        return host_for_url(url) or "metadata"
    return "publisher"


def audit_summary(audit: PDFRouteAudit) -> dict[str, Any]:
    payload = audit.to_dict()
    return {
        "schema_version": payload["schema_version"],
        "paper_id": payload["paper_id"],
        "attempted_routes": payload["attempted_routes"],
        "successful_route": payload["successful_route"],
        "failure_taxonomy": payload["failure_taxonomy"],
        "cache_hit": payload["cache_hit"],
        "attempt_count": len(payload["attempts"]),
    }


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
