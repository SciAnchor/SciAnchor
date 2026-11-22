"""RH-side Search Brief contract adapter.

This module preserves the paperfetch Search Brief shape as an RH
topic artifact without importing SPC or replacing RH's topic schema.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from ..storage.db import Database
from .._workflow.orchestrator.artifacts import ArtifactManager


RH_SEARCH_BRIEF_SCHEMA_VERSION = "rh.acquisition_search_brief.v1"
SPC_SEARCH_BRIEF_SCHEMA_VERSION = "seed-paper-curator.search-brief.v1"

PRESERVED_FIELDS = [
    "topic",
    "domain",
    "research_question",
    "scope.include",
    "scope.exclude",
    "scope.time_window",
    "scope.document_types",
    "concepts.target_system",
    "concepts.research_task",
    "concepts.method_families",
    "concepts.evidence_modalities",
    "concepts.synonyms",
    "concepts.abbreviations",
    "source_strategy.selected",
    "source_strategy.skipped",
    "query_families",
    "recall_plan",
    "quality_gate",
    "manual_seeds",
]

_REQUIRED_TOP_LEVEL = (
    "schema_version",
    "topic",
    "domain",
    "research_question",
    "scope",
    "concepts",
    "source_strategy",
    "query_families",
    "recall_plan",
    "quality_gate",
)


def normalize_search_brief(data: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in data]
    if missing:
        raise ValueError(f"search brief missing required fields: {', '.join(missing)}")
    source_schema = str(data.get("schema_version") or "")
    if source_schema != SPC_SEARCH_BRIEF_SCHEMA_VERSION:
        raise ValueError(
            f"search brief schema_version must be {SPC_SEARCH_BRIEF_SCHEMA_VERSION!r}"
        )

    brief = copy.deepcopy(dict(data))
    _ensure_scope(brief)
    _ensure_source_strategy(brief)
    return {
        "schema_version": RH_SEARCH_BRIEF_SCHEMA_VERSION,
        "source_schema": SPC_SEARCH_BRIEF_SCHEMA_VERSION,
        "brief": brief,
        "preserved_fields": list(PRESERVED_FIELDS),
    }


def record_topic_acquisition_brief(
    db: Database,
    topic_id: int,
    brief: Mapping[str, Any],
    *,
    title: str = "Acquisition Search Brief",
) -> int:
    normalized = normalize_search_brief(brief)
    artifact = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="acquisition",
        artifact_type="acquisition_search_brief",
        title=title,
        payload=normalized,
        metadata={
            "contract": SPC_SEARCH_BRIEF_SCHEMA_VERSION,
            "rh_schema_version": RH_SEARCH_BRIEF_SCHEMA_VERSION,
            "preserved_fields": list(PRESERVED_FIELDS),
        },
    )
    if artifact.id is None:
        raise RuntimeError("failed to record acquisition search brief artifact")
    return int(artifact.id)


def _ensure_scope(brief: dict[str, Any]) -> None:
    scope = brief.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("search brief scope must be an object")
    for key in ("include", "exclude"):
        value = scope.get(key)
        if not isinstance(value, list) or not value:
            raise ValueError(f"search brief scope.{key} must be a non-empty list")
    scope.setdefault("document_types", [])


def _ensure_source_strategy(brief: dict[str, Any]) -> None:
    strategy = brief.get("source_strategy")
    if not isinstance(strategy, dict):
        raise ValueError("search brief source_strategy must be an object")
    selected = strategy.get("selected")
    if not isinstance(selected, list) or len(selected) < 2:
        raise ValueError("search brief source_strategy.selected must list >=2 sources")
    strategy.setdefault("skipped", [])
