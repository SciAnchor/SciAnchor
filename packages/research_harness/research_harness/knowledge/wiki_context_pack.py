"""Private Research Wiki context-pack helpers.

This module prepares an evidence-preserving Research Wiki payload for higher
level discovery, experiment-design, method-improvement, and writing agents. It
does not write RH storage rows and does not expose a public transport surface.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from research_harness.storage.db import Database

from .research_wiki import ResearchWikiExport, ResearchWikiPage
from .research_wiki import build_research_wiki_export
from .research_wiki_insights import ResearchWikiEvidenceAnchor
from .research_wiki_search import search_research_wiki_pages
from .research_wiki_validation import (
    ResearchWikiValidationReport,
    validate_research_wiki_export,
)
from .topic_layer import get_latest_topic_knowledge_snapshot


WIKI_CONTEXT_PACK_SCHEMA_VERSION = "wiki_context_pack.v1"
_UNAVAILABLE_PREFLIGHT = {
    "priority_evidence_layer": "",
    "fallback_allowed": True,
    "fallback_must_be_declared": True,
}
_LOADED_PREFLIGHT = {
    "priority_evidence_layer": "research_wiki",
    "fallback_allowed": False,
    "fallback_must_be_declared": True,
}
_WORD_RE = re.compile(r"[a-z0-9]+")
_STALE_OR_DEGRADED_STATUSES = {"stale", "degraded", "needs_attention"}
_ACTION_PAGE_TYPES = {
    "paper_summarize": {"source", "source_section"},
    "claim_extract": {"finding", "methodology", "source_section"},
    "baseline_identify": {"finding", "methodology", "source_section"},
    "consistency_check": {"finding", "methodology", "source_section"},
    "science_discovery": {"finding", "methodology", "concept", "thesis"},
    "experiment_design": {"finding", "methodology", "source_section"},
    "method_improvement": {"finding", "methodology", "source_section"},
    "paper_writing": {"finding", "thesis", "source_section"},
}


@dataclass(frozen=True)
class WikiContextPackWarning:
    code: str
    severity: str
    page_path: str
    message: str
    target: str = ""


@dataclass(frozen=True)
class WikiContextPage:
    page_path: str
    title: str
    page_type: str
    status: str
    score: float
    matched_terms: tuple[str, ...]
    selection_reason: str
    excerpt: str
    source_hashes: tuple[str, ...]
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...]


@dataclass(frozen=True)
class WikiContextPack:
    schema_version: str
    topic_id: int
    query: str
    action_name: str
    anchor_paper_id: int | None
    pages: tuple[WikiContextPage, ...]
    warnings: tuple[WikiContextPackWarning, ...]
    degraded: bool
    source_diversity: dict[str, int]
    evidence_anchor_count: int
    truncated: bool
    truncation: dict[str, int]


@dataclass(frozen=True)
class _CandidatePage:
    page: ResearchWikiPage
    score: float
    matched_terms: tuple[str, ...]
    selection_reason: str
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...]


def build_wiki_context_pack(
    export: ResearchWikiExport,
    *,
    query: str = "",
    action_name: str = "",
    anchor_paper_id: int | None = None,
    max_pages: int = 8,
    max_anchors: int = 24,
    excerpt_chars: int = 480,
    stale_policy: str = "warn",
    include_validation: bool = False,
    validation_report: ResearchWikiValidationReport | None = None,
) -> WikiContextPack:
    """Build a private ``wiki_context_pack.v1`` from an in-memory wiki export."""

    normalized_query = " ".join(str(query or "").split())
    page_limit = max(0, int(max_pages))
    anchor_limit = max(0, int(max_anchors))
    if stale_policy not in {"warn", "allow", "exclude"}:
        raise ValueError("stale_policy must be one of: warn, allow, exclude")

    validation = None
    if include_validation:
        validation = validation_report or validate_research_wiki_export(export)

    candidates = _candidate_pages(
        export=export,
        query=normalized_query,
        action_name=action_name,
        anchor_paper_id=anchor_paper_id,
    )
    if stale_policy == "exclude":
        candidates = [
            candidate
            for candidate in candidates
            if _page_status(candidate.page) not in _STALE_OR_DEGRADED_STATUSES
        ]

    selected_candidates = candidates[:page_limit]
    remaining_anchor_budget = anchor_limit
    selected_pages: list[WikiContextPage] = []
    included_anchors: list[ResearchWikiEvidenceAnchor] = []

    for candidate in selected_candidates:
        page_anchors = candidate.evidence_anchors[:remaining_anchor_budget]
        remaining_anchor_budget = max(0, remaining_anchor_budget - len(page_anchors))
        included_anchors.extend(page_anchors)
        selected_pages.append(
            WikiContextPage(
                page_path=candidate.page.relative_path,
                title=candidate.page.title,
                page_type=candidate.page.page_type,
                status=_page_status(candidate.page),
                score=candidate.score,
                matched_terms=candidate.matched_terms,
                selection_reason=candidate.selection_reason,
                excerpt=_excerpt(candidate.page, excerpt_chars),
                source_hashes=_source_hashes(page_anchors),
                evidence_anchors=page_anchors,
            )
        )

    omitted_page_count = max(0, len(candidates) - len(selected_candidates))
    total_candidate_anchor_count = sum(
        len(candidate.evidence_anchors) for candidate in candidates
    )
    omitted_anchor_count = max(0, total_candidate_anchor_count - len(included_anchors))
    warnings = _warnings(
        selected_pages=tuple(selected_pages),
        validation_report=validation,
        stale_policy=stale_policy,
        broad_fallback=(
            bool(selected_pages)
            and not normalized_query
            and not action_name
            and anchor_paper_id is None
            and all(page.selection_reason == "fallback" for page in selected_pages)
        ),
    )
    degraded = bool(warnings) and any(
        warning.severity == "error" for warning in warnings
    )
    degraded = degraded or any(
        page.status in _STALE_OR_DEGRADED_STATUSES for page in selected_pages
    )

    truncation = {
        "omitted_anchor_count": omitted_anchor_count,
        "omitted_page_count": omitted_page_count,
    }
    return WikiContextPack(
        schema_version=WIKI_CONTEXT_PACK_SCHEMA_VERSION,
        topic_id=export.topic_id,
        query=normalized_query,
        action_name=str(action_name or ""),
        anchor_paper_id=anchor_paper_id,
        pages=tuple(selected_pages),
        warnings=warnings,
        degraded=degraded,
        source_diversity=_source_diversity(included_anchors),
        evidence_anchor_count=len(included_anchors),
        truncated=bool(omitted_page_count or omitted_anchor_count),
        truncation=truncation,
    )


def wiki_context_pack_to_dict(pack: WikiContextPack) -> dict[str, Any]:
    """Serialize a context pack into deterministic public-safe plain data."""

    return {
        "schema_version": pack.schema_version,
        "topic_id": pack.topic_id,
        "query": pack.query,
        "action_name": pack.action_name,
        "anchor_paper_id": pack.anchor_paper_id,
        "page_count": len(pack.pages),
        "evidence_anchor_count": pack.evidence_anchor_count,
        "source_diversity": dict(pack.source_diversity),
        "degraded": pack.degraded,
        "truncated": pack.truncated,
        "truncation": dict(pack.truncation),
        "warnings": [_warning_to_dict(warning) for warning in pack.warnings],
        "pages": [_page_to_dict(page) for page in pack.pages],
    }


def build_wiki_context_pack_payload_from_db(
    db: Database,
    *,
    topic_id: int,
    query: str = "",
    action_name: str = "",
    anchor_paper_id: int | None = None,
    max_pages: int = 8,
    max_anchors: int = 24,
    excerpt_chars: int = 480,
    stale_policy: str = "warn",
) -> dict[str, Any]:
    """Build a public-safe preflight payload from the topic's Research Wiki.

    This is the controlled read-only facade over the private helper. It reports
    whether the paper-card/Research-Wiki evidence layer was actually loaded and
    never promotes ordinary local markdown synthesis as a Research Wiki context
    pack.
    """

    if topic_id <= 0:
        raise ValueError("topic_id must be positive")
    snapshot = get_latest_topic_knowledge_snapshot(
        db,
        topic_id,
        require_current=False,
    )
    if snapshot is None:
        return _unavailable_payload(
            topic_id=topic_id,
            reason="no_research_wiki_export",
            unavailable_reasons=(
                "no current or stale Topic Knowledge snapshot; refresh Topic Knowledge from paper cards first",
            ),
        )

    try:
        export = build_research_wiki_export(
            db,
            topic_id,
            require_current=False,
        )
    except ValueError as exc:
        return _unavailable_payload(
            topic_id=topic_id,
            reason="no_research_wiki_export",
            unavailable_reasons=(str(exc),),
        )

    validation = validate_research_wiki_export(export)
    pack = build_wiki_context_pack(
        export,
        query=query,
        action_name=action_name,
        anchor_paper_id=anchor_paper_id,
        max_pages=max_pages,
        max_anchors=max_anchors,
        excerpt_chars=excerpt_chars,
        stale_policy=stale_policy,
        include_validation=True,
        validation_report=validation,
    )
    data = wiki_context_pack_to_dict(pack)
    warnings = list(data["warnings"])
    if not snapshot.is_current:
        warnings.insert(
            0,
            {
                "code": "snapshot_stale",
                "severity": "warning",
                "page_path": "",
                "message": (
                    "Topic Knowledge snapshot source hash differs from current topic inputs"
                ),
                "target": f"artifact:topic_knowledge_snapshot:{snapshot.artifact_id}",
            },
        )

    degraded = bool(data["degraded"] or not snapshot.is_current)
    return {
        **data,
        "paper_wiki_status": "loaded",
        "status_reason": "wiki_context_pack_loaded",
        "degraded": degraded,
        "warnings": warnings,
        "snapshot": {
            "artifact_ref": f"artifact:topic_knowledge_snapshot:{snapshot.artifact_id}",
            "source_hash": snapshot.source_hash,
            "is_current": snapshot.is_current,
        },
        "validation": {
            "valid": validation.valid,
            "issue_count": validation.issue_count,
            "counts_by_code": validation.counts_by_code,
        },
        "preflight": dict(_LOADED_PREFLIGHT),
    }


def _unavailable_payload(
    *,
    topic_id: int,
    reason: str,
    unavailable_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": WIKI_CONTEXT_PACK_SCHEMA_VERSION,
        "topic_id": topic_id,
        "paper_wiki_status": "unavailable",
        "status_reason": reason,
        "unavailable_reasons": list(unavailable_reasons),
        "warnings": [],
        "preflight": dict(_UNAVAILABLE_PREFLIGHT),
        "pages": [],
    }


def _candidate_pages(
    *,
    export: ResearchWikiExport,
    query: str,
    action_name: str,
    anchor_paper_id: int | None,
) -> list[_CandidatePage]:
    pages_by_path = {page.relative_path: page for page in export.pages}
    candidates: list[_CandidatePage] = []
    seen: set[str] = set()

    if query:
        search_result = search_research_wiki_pages(
            export,
            query,
            max_results=max(len(export.pages), 1),
        )
        for hit in search_result.hits:
            page = pages_by_path.get(hit.page_path)
            if page is None:
                continue
            candidates.append(
                _CandidatePage(
                    page=page,
                    score=hit.score,
                    matched_terms=hit.matched_terms,
                    selection_reason="query_match",
                    evidence_anchors=hit.evidence,
                )
            )
            seen.add(page.relative_path)

    action_page_types = _ACTION_PAGE_TYPES.get(str(action_name or ""), set())
    for page in _sorted_pages(export.pages):
        if page.relative_path in seen or page.page_type not in action_page_types:
            continue
        candidates.append(_manual_candidate(page, query, "action_page_type"))
        seen.add(page.relative_path)

    if anchor_paper_id is not None:
        for page in _sorted_pages(export.pages):
            if page.relative_path in seen:
                continue
            anchors = _page_evidence_anchors(page)
            if any(anchor.paper_id == anchor_paper_id for anchor in anchors):
                candidates.append(
                    _CandidatePage(
                        page=page,
                        score=0.0,
                        matched_terms=_matched_terms(page, query),
                        selection_reason="anchor_paper",
                        evidence_anchors=anchors,
                    )
                )
                seen.add(page.relative_path)

    if not candidates:
        for page in _sorted_pages(export.pages):
            candidates.append(_manual_candidate(page, query, "fallback"))
    return candidates


def _manual_candidate(
    page: ResearchWikiPage,
    query: str,
    selection_reason: str,
) -> _CandidatePage:
    return _CandidatePage(
        page=page,
        score=0.0,
        matched_terms=_matched_terms(page, query),
        selection_reason=selection_reason,
        evidence_anchors=_page_evidence_anchors(page),
    )


def _sorted_pages(pages: tuple[ResearchWikiPage, ...]) -> list[ResearchWikiPage]:
    return sorted(pages, key=lambda page: (page.relative_path, page.title))


def _page_evidence_anchors(
    page: ResearchWikiPage,
) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    anchors: list[ResearchWikiEvidenceAnchor] = []
    sources = page.frontmatter.get("sources")
    if not isinstance(sources, list):
        return ()
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_type = str(source.get("source_type") or "")
        source_id = str(source.get("source_id") or "")
        source_hash = str(source.get("source_hash") or "")
        evidence_snippet = str(source.get("evidence_snippet") or "")
        if not source_type or not source_id or not source_hash or not evidence_snippet:
            continue
        paper_id = source.get("paper_id")
        anchors.append(
            ResearchWikiEvidenceAnchor(
                page_path=page.relative_path,
                paper_id=paper_id if isinstance(paper_id, int) else None,
                source_type=source_type,
                source_id=source_id,
                source_hash=source_hash,
                section_anchor=str(source.get("section_anchor") or ""),
                evidence_snippet=evidence_snippet,
            )
        )
    return tuple(
        sorted(
            anchors,
            key=lambda anchor: (
                anchor.source_type,
                anchor.source_id,
                anchor.source_hash,
                anchor.section_anchor,
                anchor.evidence_snippet,
            ),
        )
    )


def _matched_terms(page: ResearchWikiPage, query: str) -> tuple[str, ...]:
    terms = tuple(dict.fromkeys(_WORD_RE.findall(query.lower())))
    if not terms:
        return ()
    text = " ".join(
        _WORD_RE.findall(f"{page.title} {page.relative_path} {page.body}".lower())
    )
    tokens = set(text.split())
    return tuple(term for term in terms if term in tokens)


def _page_status(page: ResearchWikiPage) -> str:
    metadata = page.frontmatter
    if bool(metadata.get("stale")):
        return "stale"
    if bool(metadata.get("degraded")):
        return "degraded"
    return str(metadata.get("status") or metadata.get("readiness_status") or "ready")


def _excerpt(page: ResearchWikiPage, max_chars: int) -> str:
    limit = max(0, int(max_chars))
    text = " ".join(page.body.split())
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _source_hashes(
    anchors: tuple[ResearchWikiEvidenceAnchor, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted({anchor.source_hash for anchor in anchors if anchor.source_hash})
    )


def _source_diversity(
    anchors: list[ResearchWikiEvidenceAnchor],
) -> dict[str, int]:
    return {
        "paper_count": len({anchor.paper_id for anchor in anchors if anchor.paper_id}),
        "source_hash_count": len(
            {anchor.source_hash for anchor in anchors if anchor.source_hash}
        ),
        "source_type_count": len(
            {anchor.source_type for anchor in anchors if anchor.source_type}
        ),
    }


def _warnings(
    *,
    selected_pages: tuple[WikiContextPage, ...],
    validation_report: ResearchWikiValidationReport | None,
    stale_policy: str,
    broad_fallback: bool,
) -> tuple[WikiContextPackWarning, ...]:
    warnings: list[WikiContextPackWarning] = []
    if broad_fallback:
        warnings.append(
            WikiContextPackWarning(
                code="broad_fallback_context",
                severity="warning",
                page_path="",
                message=(
                    "context pack selected pages without query, action, or anchor; "
                    "treat as broad advisory context"
                ),
            )
        )

    if stale_policy == "warn":
        for page in selected_pages:
            if page.status in _STALE_OR_DEGRADED_STATUSES:
                warnings.append(
                    WikiContextPackWarning(
                        code=f"page_{page.status}",
                        severity="error",
                        page_path=page.page_path,
                        message=f"selected page status is {page.status}",
                    )
                )

    if validation_report is not None:
        selected_paths = {page.page_path for page in selected_pages}
        for issue in validation_report.issues:
            if issue.page_path not in selected_paths:
                continue
            warnings.append(
                WikiContextPackWarning(
                    code=issue.code,
                    severity=issue.severity,
                    page_path=issue.page_path,
                    message=issue.message,
                    target=issue.target,
                )
            )

    return tuple(
        sorted(
            warnings,
            key=lambda warning: (
                warning.code,
                warning.page_path,
                warning.target,
                warning.message,
                warning.severity,
            ),
        )
    )


def _warning_to_dict(warning: WikiContextPackWarning) -> dict[str, str]:
    return {
        "code": warning.code,
        "severity": warning.severity,
        "page_path": warning.page_path,
        "message": warning.message,
        "target": warning.target,
    }


def _page_to_dict(page: WikiContextPage) -> dict[str, Any]:
    return {
        "page_path": page.page_path,
        "title": page.title,
        "page_type": page.page_type,
        "status": page.status,
        "score": page.score,
        "matched_terms": list(page.matched_terms),
        "selection_reason": page.selection_reason,
        "excerpt": page.excerpt,
        "source_hashes": list(page.source_hashes),
        "evidence_anchors": [
            _evidence_anchor_to_dict(anchor) for anchor in page.evidence_anchors
        ],
    }


def _evidence_anchor_to_dict(
    anchor: ResearchWikiEvidenceAnchor,
) -> dict[str, Any]:
    return {
        "page_path": anchor.page_path,
        "paper_id": anchor.paper_id,
        "source_type": anchor.source_type,
        "source_id": anchor.source_id,
        "source_hash": anchor.source_hash,
        "section_anchor": anchor.section_anchor,
        "evidence_snippet": anchor.evidence_snippet,
    }
