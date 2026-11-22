"""Private readiness reporting for Topic Knowledge and Research Wiki outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .research_wiki import ResearchWikiExport
from .research_wiki_insights import (
    ResearchWikiInsightReport,
    find_research_wiki_insights,
)
from .research_wiki_search import search_research_wiki_pages
from .research_wiki_validation import (
    ResearchWikiValidationReport,
    validate_research_wiki_export,
)
from .topic_layer import TopicKnowledgeSnapshot


EXISTING_RH_ACTION_NAMES = frozenset(
    {
        "paper_summarize",
        "claim_extract",
        "gap_detect",
        "baseline_identify",
        "evidence_matrix",
        "section_draft",
        "consistency_check",
    }
)


@dataclass(frozen=True)
class TopicKnowledgeReadinessReport:
    topic_id: int
    status: str
    coverage: dict[str, Any]
    wiki: dict[str, Any]
    validation: dict[str, Any]
    insights: dict[str, Any]
    search: dict[str, Any]
    next_actions: tuple[str, ...]


def build_topic_knowledge_readiness_report(
    snapshot: TopicKnowledgeSnapshot,
    wiki_export: ResearchWikiExport,
    *,
    insight_report: ResearchWikiInsightReport | None = None,
    validation_report: ResearchWikiValidationReport | None = None,
    search_queries: tuple[str, ...] | list[str] = (),
) -> TopicKnowledgeReadinessReport:
    """Build a private advisory readiness report for Topic Knowledge consumers."""

    if snapshot.topic_id != wiki_export.topic_id:
        raise ValueError("snapshot topic_id must match wiki export topic_id")
    insights = insight_report or find_research_wiki_insights(wiki_export)
    validation = validation_report or validate_research_wiki_export(wiki_export)
    if insights.topic_id != snapshot.topic_id:
        raise ValueError("insight report topic_id must match snapshot topic_id")
    if validation.topic_id != snapshot.topic_id:
        raise ValueError("validation report topic_id must match snapshot topic_id")

    coverage = _snapshot_coverage(snapshot)
    wiki = _wiki_summary(wiki_export)
    validation_summary = {
        "valid": validation.valid,
        "issue_count": validation.issue_count,
        "counts_by_code": validation.counts_by_code,
    }
    insight_summary = {
        "count": len(insights.insights),
        "types": sorted({insight.insight_type for insight in insights.insights}),
    }
    search_summary = _search_summary(wiki_export, tuple(search_queries))
    return TopicKnowledgeReadinessReport(
        topic_id=snapshot.topic_id,
        status=_readiness_status(
            snapshot=snapshot,
            coverage=coverage,
            wiki=wiki,
            validation=validation_summary,
        ),
        coverage=coverage,
        wiki=wiki,
        validation=validation_summary,
        insights=insight_summary,
        search=search_summary,
        next_actions=_filtered_next_actions(snapshot),
    )


def topic_knowledge_readiness_report_to_dict(
    report: TopicKnowledgeReadinessReport,
) -> dict[str, Any]:
    """Serialize a readiness report into deterministic plain data."""

    return {
        "topic_id": report.topic_id,
        "status": report.status,
        "coverage": report.coverage,
        "wiki": report.wiki,
        "validation": report.validation,
        "insights": report.insights,
        "search": report.search,
        "next_actions": list(report.next_actions),
    }


def _snapshot_coverage(snapshot: TopicKnowledgeSnapshot) -> dict[str, Any]:
    payload_coverage = snapshot.payload.get("coverage")
    coverage = (
        payload_coverage if isinstance(payload_coverage, dict) else snapshot.coverage
    )
    return dict(coverage)


def _wiki_summary(wiki_export: ResearchWikiExport) -> dict[str, Any]:
    page_types: dict[str, int] = {}
    searchable_page_count = 0
    evidence_bound_page_count = 0
    for page in wiki_export.pages:
        page_types[page.page_type] = page_types.get(page.page_type, 0) + 1
        if page.title.strip() or page.body.strip():
            searchable_page_count += 1
        sources = page.frontmatter.get("sources")
        if isinstance(sources, list) and sources:
            evidence_bound_page_count += 1
    return {
        "page_count": len(wiki_export.pages),
        "page_types": {key: page_types[key] for key in sorted(page_types)},
        "searchable_page_count": searchable_page_count,
        "evidence_bound_page_count": evidence_bound_page_count,
    }


def _search_summary(
    wiki_export: ResearchWikiExport,
    search_queries: tuple[str, ...],
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for query in search_queries:
        result = search_research_wiki_pages(wiki_export, query, max_results=5)
        samples.append(
            {
                "query": query,
                "term_count": result.term_count,
                "hit_count": len(result.hits),
                "top_page": result.hits[0].page_path if result.hits else "",
            }
        )
    return {
        "query_count": len(search_queries),
        "sample_queries": samples,
    }


def _readiness_status(
    *,
    snapshot: TopicKnowledgeSnapshot,
    coverage: dict[str, Any],
    wiki: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    if not snapshot.is_current:
        return "stale"
    if not validation["valid"]:
        return "needs_attention"
    if int(coverage.get("semantic_atoms") or 0) <= 0:
        return "needs_attention"
    if int(wiki.get("page_count") or 0) <= 0:
        return "needs_attention"
    return "ready"


def _filtered_next_actions(snapshot: TopicKnowledgeSnapshot) -> tuple[str, ...]:
    raw_actions = snapshot.payload.get("next_actions")
    if not isinstance(raw_actions, list):
        return ()
    actions = [
        str(action) for action in raw_actions if str(action) in EXISTING_RH_ACTION_NAMES
    ]
    return tuple(dict.fromkeys(actions))
