"""Research Wiki workflow preflight contracts.

This module is the runtime contract between RH workflow execution and the
paper-card-derived Research Wiki context pack. It keeps the public-safe summary
small enough for checkpoints while preserving explicit fallback semantics.
"""

from __future__ import annotations

from typing import Any

from research_harness.storage.db import Database

from .wiki_context_pack import build_wiki_context_pack_payload_from_db


RESEARCH_WIKI_PREFLIGHT_SCHEMA_VERSION = "research_wiki_preflight.v1"
_STAGE_ACTION_NAMES = {
    "analyze": "science_discovery",
    "propose": "experiment_design",
    "experiment": "method_improvement",
    "write": "paper_writing",
}


def requires_research_wiki_preflight(stage: str) -> bool:
    """Return whether a workflow stage must try Research Wiki preflight."""

    return stage in _STAGE_ACTION_NAMES


def action_name_for_workflow_stage(stage: str) -> str:
    """Map an RH workflow stage to the relevant context-pack action name."""

    return _STAGE_ACTION_NAMES.get(stage, "")


def run_research_wiki_preflight(
    *,
    db: Database,
    topic_id: int,
    stage: str,
    query: str = "",
) -> dict[str, Any] | None:
    """Build a compact, checkpoint-safe Research Wiki preflight summary.

    Returns ``None`` for stages that do not require Research Wiki preflight.
    """

    action_name = action_name_for_workflow_stage(stage)
    if not action_name:
        return None

    payload = build_wiki_context_pack_payload_from_db(
        db,
        topic_id=topic_id,
        query=query,
        action_name=action_name,
    )
    return summarize_research_wiki_preflight(payload, stage=stage)


def summarize_research_wiki_preflight(
    payload: dict[str, Any],
    *,
    stage: str,
) -> dict[str, Any]:
    """Summarize a context-pack payload for workflow checkpoints."""

    preflight = payload.get("preflight")
    if not isinstance(preflight, dict):
        preflight = {}
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    unavailable_reasons = payload.get("unavailable_reasons")
    if not isinstance(unavailable_reasons, list):
        unavailable_reasons = []

    return {
        "schema_version": RESEARCH_WIKI_PREFLIGHT_SCHEMA_VERSION,
        "topic_id": payload.get("topic_id"),
        "stage": stage,
        "action_name": str(
            payload.get("action_name") or action_name_for_workflow_stage(stage)
        ),
        "paper_wiki_status": str(payload.get("paper_wiki_status") or "not_triggered"),
        "status_reason": str(payload.get("status_reason") or ""),
        "priority_evidence_layer": str(preflight.get("priority_evidence_layer") or ""),
        "fallback_allowed": bool(preflight.get("fallback_allowed")),
        "fallback_must_be_declared": bool(
            preflight.get("fallback_must_be_declared", True)
        ),
        "must_not_silent_markdown_fallback": True,
        "degraded": bool(payload.get("degraded")),
        "warning_codes": [
            str(warning.get("code"))
            for warning in warnings
            if isinstance(warning, dict) and warning.get("code")
        ],
        "page_count": int(payload.get("page_count") or 0),
        "evidence_anchor_count": int(payload.get("evidence_anchor_count") or 0),
        "unavailable_reasons": [str(item) for item in unavailable_reasons],
    }
