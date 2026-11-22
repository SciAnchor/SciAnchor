"""Session advisory and nudge helpers for MCP tool execution."""

from __future__ import annotations

from typing import Any

from research_harness.primitives.types import PrimitiveResult
from research_harness.storage.db import Database

_SESSION_ACTIVITY: dict[str, Any] = {
    "last_topic_id": None,
    "streak": 0,
}
_SESSION_NUDGE_MGR: dict[str, Any] = {
    "instance": None,
    "cost_usd": 0.0,
    "experiment_count": 0,
}
_SESSION_TRIGGER_TOOLS = {
    "paper_search",
    "paper_ingest",
    "paper_acquire",
    "claim_extract",
    "gap_detect",
    "query_refine",
    "search_query_add",
}


def _try_get_orch_state(db: Database, topic_id: int | None) -> dict[str, Any] | None:
    """Try to fetch orchestrator state for context-aware next_actions."""
    if topic_id is None:
        return None
    try:
        from research_harness.orchestrator import OrchestratorService

        svc = OrchestratorService(db)
        status = svc.get_status(topic_id)
        # get_status returns {"error": ...} when no run exists
        if "error" in status:
            return None
        return status
    except Exception:
        return None


def _extract_topic_id(arguments: dict[str, Any]) -> int | None:
    topic_id = arguments.get("topic_id")
    if topic_id is None:
        return None
    try:
        return int(topic_id)
    except (TypeError, ValueError):
        return None


def _maybe_session_advisory(
    db: Database,
    name: str,
    arguments: dict[str, Any],
    orch_state: dict[str, Any] | None,
) -> str:
    if name not in _SESSION_TRIGGER_TOOLS:
        return ""

    topic_id = _extract_topic_id(arguments)
    if topic_id is None:
        return ""

    if _SESSION_ACTIVITY["last_topic_id"] == topic_id:
        _SESSION_ACTIVITY["streak"] += 1
    else:
        _SESSION_ACTIVITY["last_topic_id"] = topic_id
        _SESSION_ACTIVITY["streak"] = 1

    if orch_state is not None:
        return ""

    if _SESSION_ACTIVITY["streak"] < 3:
        return ""

    return (
        f"Detected {_SESSION_ACTIVITY['streak']} consecutive operations on topic {topic_id}. "
        "Consider starting or resuming the full orchestrated literature workflow "
        "with orchestrator_resume, then record artifacts as you progress."
    )


def _get_nudge_manager(db: Database) -> Any:
    """Get or create session-level NudgeManager."""
    if _SESSION_NUDGE_MGR["instance"] is None:
        try:
            from research_harness.evolution.topic.nudge import NudgeManager
            import uuid

            _SESSION_NUDGE_MGR["instance"] = NudgeManager(
                db, f"mcp-{uuid.uuid4().hex[:8]}"
            )
        except Exception:
            pass
    return _SESSION_NUDGE_MGR["instance"]


def _check_nudge(
    db: Database, name: str, arguments: dict[str, Any], result: PrimitiveResult
) -> str:
    """Check if a nudge should be emitted after this tool call."""
    mgr = _get_nudge_manager(db)
    if mgr is None:
        return ""
    try:
        mgr.tick()
        if result.cost_usd:
            _SESSION_NUDGE_MGR["cost_usd"] += result.cost_usd
        if name == "experiment_run":
            _SESSION_NUDGE_MGR["experiment_count"] += 1

        # Infer stage from orchestrator state or argument
        stage = arguments.get("stage", "")
        if not stage:
            orch = _try_get_orch_state(db, arguments.get("topic_id"))
            if orch and isinstance(orch, dict):
                stage = orch.get("current_stage", "")

        nudge = mgr.check_nudge(
            stage=stage,
            cost_usd=_SESSION_NUDGE_MGR["cost_usd"],
            experiment_count=_SESSION_NUDGE_MGR["experiment_count"],
        )
        if nudge:
            return mgr.format_nudge(nudge)
    except Exception:
        pass
    return ""
