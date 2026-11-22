"""Private public-shaped status payload for Topic Knowledge.

This module builds the versioned read-only payload that a later MCP/CLI/HTTP
surface may wrap. It intentionally does not register any transport or execute
research actions.
"""

from __future__ import annotations

from typing import Any

from .knowledge_consumption import (
    ADVISORY_KNOWLEDGE_ACTIONS,
    BLOCKED_KNOWLEDGE_ACTIONS,
    EXECUTABLE_KNOWLEDGE_ACTIONS,
)
from .research_wiki import ResearchWikiExport
from .research_wiki import build_research_wiki_export
from .research_wiki_insights import (
    ResearchWikiInsightReport,
    find_research_wiki_insights,
)
from .research_wiki_validation import (
    ResearchWikiValidationReport,
    validate_research_wiki_export,
)
from .topic_knowledge_readiness import TopicKnowledgeReadinessReport
from .topic_knowledge_readiness import build_topic_knowledge_readiness_report
from .topic_layer import TopicKnowledgeSnapshot
from .topic_layer import get_latest_topic_knowledge_snapshot
from research_harness.storage.db import Database


KNOWLEDGE_STATUS_SCHEMA_VERSION = "knowledge_status.v1"
_MAX_NEXT_ACTIONS = 5
_COVERAGE_KEYS = (
    "papers",
    "paper_count",
    "paper_artifacts",
    "compiled_summaries",
    "normalized_claims",
    "gaps",
    "contradictions",
    "semantic_atoms",
    "semantic_edges",
)


class KnowledgeStatusUnavailable(ValueError):
    """Public-safe error for a missing read-only knowledge status payload."""

    code = "knowledge_status_unavailable"

    def __init__(self, topic_id: int) -> None:
        self.topic_id = topic_id
        self.public_message = f"knowledge status is unavailable for topic {topic_id}"
        super().__init__(self.public_message)


def build_knowledge_status_payload_from_db(
    db: Database,
    *,
    topic_id: int,
    search_queries: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Build `knowledge_status.v1` from the latest private topic snapshot."""

    if topic_id <= 0:
        raise ValueError("topic_id must be positive")
    snapshot = get_latest_topic_knowledge_snapshot(
        db,
        topic_id,
        require_current=False,
    )
    if snapshot is None:
        raise KnowledgeStatusUnavailable(topic_id)

    wiki_export = build_research_wiki_export(
        db,
        topic_id,
        require_current=False,
    )
    validation = validate_research_wiki_export(wiki_export)
    insights = find_research_wiki_insights(wiki_export)
    readiness = build_topic_knowledge_readiness_report(
        snapshot,
        wiki_export,
        insight_report=insights,
        validation_report=validation,
        search_queries=tuple(search_queries),
    )
    return build_knowledge_status_payload(
        snapshot=snapshot,
        wiki_export=wiki_export,
        readiness_report=readiness,
        validation_report=validation,
        insight_report=insights,
    )


def build_knowledge_status_payload(
    *,
    snapshot: TopicKnowledgeSnapshot,
    wiki_export: ResearchWikiExport,
    readiness_report: TopicKnowledgeReadinessReport,
    validation_report: ResearchWikiValidationReport | None = None,
    insight_report: ResearchWikiInsightReport | None = None,
    include_warnings: bool = True,
    max_next_actions: int = _MAX_NEXT_ACTIONS,
) -> dict[str, Any]:
    """Return the private `knowledge_status.v1` payload for later public wrapping."""

    _validate_topic(snapshot, wiki_export, readiness_report)
    validation = validation_report or validate_research_wiki_export(wiki_export)
    insights = insight_report or find_research_wiki_insights(wiki_export)
    if validation.topic_id != snapshot.topic_id:
        raise ValueError("validation topic_id must match snapshot topic_id")
    if insights.topic_id != snapshot.topic_id:
        raise ValueError("insight topic_id must match snapshot topic_id")

    warnings = _warnings(snapshot, readiness_report, validation)
    status = _status(snapshot, readiness_report, validation)
    artifact_ref = f"artifact:topic_knowledge_snapshot:{snapshot.artifact_id}"
    return {
        "schema_version": KNOWLEDGE_STATUS_SCHEMA_VERSION,
        "topic_id": snapshot.topic_id,
        "status": status,
        "readiness_status": readiness_report.status,
        "snapshot": {
            "artifact_ref": artifact_ref,
            "source_hash": snapshot.source_hash,
            "is_current": snapshot.is_current,
        },
        "coverage": _coverage(readiness_report.coverage),
        "wiki": _wiki(readiness_report, validation, insights),
        "next_actions": _next_actions(
            readiness_report.next_actions,
            max_next_actions=max_next_actions,
        ),
        "warnings": warnings if include_warnings else [],
        "links": {
            "snapshot_artifact": artifact_ref,
        },
    }


def _validate_topic(
    snapshot: TopicKnowledgeSnapshot,
    wiki_export: ResearchWikiExport,
    readiness_report: TopicKnowledgeReadinessReport,
) -> None:
    if snapshot.topic_id <= 0:
        raise ValueError("topic_id must be positive")
    if wiki_export.topic_id != snapshot.topic_id:
        raise ValueError("wiki topic_id must match snapshot topic_id")
    if readiness_report.topic_id != snapshot.topic_id:
        raise ValueError("readiness topic_id must match snapshot topic_id")


def _status(
    snapshot: TopicKnowledgeSnapshot,
    readiness_report: TopicKnowledgeReadinessReport,
    validation: ResearchWikiValidationReport,
) -> str:
    if not snapshot.is_current:
        return "stale"
    if readiness_report.status != "ready" or not validation.valid:
        return "degraded"
    return "ready"


def _warnings(
    snapshot: TopicKnowledgeSnapshot,
    readiness_report: TopicKnowledgeReadinessReport,
    validation: ResearchWikiValidationReport,
) -> list[str]:
    warnings: list[str] = []
    if not snapshot.is_current:
        warnings.append("snapshot_stale")
    if readiness_report.status != "ready":
        warnings.append(f"readiness_{readiness_report.status}")
    warnings.extend(validation.counts_by_code)
    return list(dict.fromkeys(warnings))


def _coverage(raw_coverage: dict[str, Any]) -> dict[str, int]:
    coverage = dict(raw_coverage)
    if "papers" not in coverage and "paper_count" in coverage:
        coverage["papers"] = coverage["paper_count"]
    return {
        key: _int_count(coverage.get(key)) for key in _COVERAGE_KEYS if key in coverage
    }


def _wiki(
    readiness_report: TopicKnowledgeReadinessReport,
    validation: ResearchWikiValidationReport,
    insights: ResearchWikiInsightReport,
) -> dict[str, Any]:
    wiki = dict(readiness_report.wiki)
    return {
        "page_count": _int_count(wiki.get("page_count")),
        "searchable_page_count": _int_count(wiki.get("searchable_page_count")),
        "evidence_bound_page_count": _int_count(wiki.get("evidence_bound_page_count")),
        "validation_issue_count": validation.issue_count,
        "insight_count": len(insights.insights),
    }


def _next_actions(
    raw_actions: tuple[str, ...],
    *,
    max_next_actions: int,
) -> list[dict[str, str]]:
    limit = max(0, min(int(max_next_actions), _MAX_NEXT_ACTIONS))
    actions: list[dict[str, str]] = []
    for action_name in raw_actions:
        mode = _action_mode(str(action_name))
        if mode == "blocked":
            continue
        actions.append(
            {
                "action_name": str(action_name),
                "mode": mode,
                "reason": "existing RH action selected from readiness report",
            }
        )
        if len(actions) >= limit:
            break
    return actions


def _action_mode(action_name: str) -> str:
    if action_name in EXECUTABLE_KNOWLEDGE_ACTIONS:
        return "executable"
    if action_name in ADVISORY_KNOWLEDGE_ACTIONS:
        return "advisory"
    if action_name in BLOCKED_KNOWLEDGE_ACTIONS:
        return "blocked"
    return "blocked"


def _int_count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
