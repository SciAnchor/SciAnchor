"""MCP tool definitions and execution — wraps research_harness primitives."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from mcp.types import Tool

from research_harness.config import find_workspace_root
from research_harness.execution.factory import create_backend
from research_harness.path_jail import PathJailError, check_arguments
from research_harness.execution.tracked import TrackedBackend
from research_harness.primitives.registry import list_primitives
from research_harness.primitives.types import PrimitiveResult
from research_harness.provenance.recorder import ProvenanceRecorder
from research_harness.service import ResearchService
from research_harness.storage.db import Database

from . import tools_session as _tools_session
from .tool_surface import PUBLIC_MCP_TOOL_NAMES, public_tool_definitions
from .tools_convenience import (
    _CONVENIENCE_TOOLS,
    _execute_convenience as _execute_convenience_payload,
)
from .tools_acquisition import (
    _ACQUISITION_TOOLS,
    _execute_acquisition as _execute_acquisition_payload,
)
from .tools_orchestrator import (
    _ORCHESTRATOR_TOOLS,
    _execute_adversarial_review as _execute_adversarial_review_payload,
    _execute_orchestrator as _execute_orchestrator_payload,
)
from .tools_paperindex import _PAPERINDEX_TOOLS, _execute_paperindex
from .tools_productization import _PRODUCTIZATION_TOOLS, _execute_productization_tool
from .tools_primitives import (
    _execute_primitive as _execute_primitive_payload,
    _primitive_tool_definitions as _primitive_tool_definitions_payload,
    _record_iterative_retrieval_artifact as _record_iterative_retrieval_artifact_payload,
)
from .tools_workflow import (
    _candidate_evidence as _candidate_evidence_payload,
    _execute_experiment_handoff_prepare as _execute_experiment_handoff_prepare_payload,
    _execute_experiment_handoff_submit as _execute_experiment_handoff_submit_payload,
    _execute_workflow_entry as _execute_workflow_entry_payload,
    _load_candidate as _load_candidate_payload,
)
from .tools_zotero import (
    _execute_zotero_sync as _execute_zotero_sync_payload,
    _zotero_stable_dry_run_deferred_error as _zotero_stable_dry_run_deferred_error_payload,
)
from .tools_service_dispatch import (
    _SERVICE_BACKED_CONVENIENCE_TOOLS,
    _execute_service_backed_convenience as _execute_service_backed_convenience_payload,
    _execute_service_backed_primitive as _execute_service_backed_primitive_payload,
    _with_deprecation_notice as _with_deprecation_notice_payload,
)
from .tools_strategy import _inject_strategy_overlay as _inject_strategy_overlay_payload
from .tools_workflow_complete import (
    _WORKFLOW_COMPLETE_TOOLS,
    _execute_workflow_complete as _execute_workflow_complete_payload,
)
from .tools_decision import DECISION_TOOLS, _execute_decision
from .tool_wrappers import (
    _serialize_result,
    _wrap_convenience,
    _wrap_orchestrator as _wrap_orchestrator_payload,
)

logger = logging.getLogger(__name__)

_SESSION_ACTIVITY = _tools_session._SESSION_ACTIVITY
_SESSION_NUDGE_MGR = _tools_session._SESSION_NUDGE_MGR
_SESSION_TRIGGER_TOOLS = _tools_session._SESSION_TRIGGER_TOOLS
_try_get_orch_state = _tools_session._try_get_orch_state
_extract_topic_id = _tools_session._extract_topic_id
_maybe_session_advisory = _tools_session._maybe_session_advisory
_get_nudge_manager = _tools_session._get_nudge_manager
_check_nudge = _tools_session._check_nudge

# ---------------------------------------------------------------------------
# DB / backend helpers
# ---------------------------------------------------------------------------


def _resolve_db() -> Database:
    """Resolve database path from env or workspace default."""
    db_path = os.environ.get("RESEARCH_HARNESS_DB_PATH") or os.environ.get(
        "RESEARCH_HUB_DB_PATH"
    )
    if db_path:
        db = Database(Path(db_path))
    else:
        ws = find_workspace_root()
        if ws:
            db = Database(ws / ".research-harness" / "pool.db")
        else:
            db = Database(Path.home() / ".research-harness" / "pool.db")
    logger.info("Using DB: %s", db.db_path)
    db.migrate()
    return db


def _create_tracked_backend(db: Database) -> TrackedBackend:
    """Create a tracked research_harness backend."""
    backend_name = os.environ.get("RESEARCH_HARNESS_BACKEND") or os.environ.get(
        "RESEARCH_HUB_BACKEND", "research_harness"
    )
    inner = create_backend(backend_name, db=db)
    recorder = ProvenanceRecorder(db)
    return TrackedBackend(inner=inner, recorder=recorder)


# ---------------------------------------------------------------------------
# Primitive tools — auto-generated from PRIMITIVE_REGISTRY
# ---------------------------------------------------------------------------


def _primitive_tool_definitions() -> list[Tool]:
    """Compatibility shim preserving late-bound primitive listing."""
    return _primitive_tool_definitions_payload(primitive_lister=list_primitives)


def _inject_strategy_overlay(raw: dict[str, Any]) -> str:
    """Compatibility shim preserving late-bound DB resolution."""
    return _inject_strategy_overlay_payload(raw, db_resolver=_resolve_db)


def _record_iterative_retrieval_artifact(
    db: Database, arguments: dict[str, Any], result: PrimitiveResult
) -> None:
    """Compatibility shim preserving the tools module helper name."""
    _record_iterative_retrieval_artifact_payload(db, arguments, result)


def _execute_primitive(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Compatibility shim preserving late-bound tools module helpers."""
    return _execute_primitive_payload(
        name,
        arguments,
        db_resolver=_resolve_db,
        backend_factory=_create_tracked_backend,
        result_serializer=_serialize_result,
        orch_state_provider=_try_get_orch_state,
        session_advisory_provider=_maybe_session_advisory,
        nudge_provider=_check_nudge,
        iterative_artifact_recorder=_record_iterative_retrieval_artifact,
        logger_obj=logger,
    )


# ---------------------------------------------------------------------------
# Convenience tools — direct DB queries
# ---------------------------------------------------------------------------


def _execute_workflow_complete(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute complete workflow tools for pure CLI usage."""
    return _execute_workflow_complete_payload(name, arguments)


def _execute_convenience(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Compatibility shim preserving late-bound DB and Zotero helpers."""
    return _execute_convenience_payload(
        name,
        arguments,
        db_resolver=_resolve_db,
        zotero_sync_executor=_execute_zotero_sync,
    )


def _execute_zotero_sync(db: Database, arguments: dict[str, Any]) -> dict[str, Any]:
    """Compatibility shim preserving the tools module helper name."""
    return _execute_zotero_sync_payload(db, arguments)


def _zotero_stable_dry_run_deferred_error(
    *,
    direction: str,
    dry_run: bool,
) -> str:
    """Compatibility shim preserving the tools module helper name."""
    return _zotero_stable_dry_run_deferred_error_payload(
        direction=direction,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Orchestrator tools
# ---------------------------------------------------------------------------


def _execute_adversarial_review(
    svc: Any,
    db: Any,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Compatibility shim preserving the tools module helper name."""
    return _execute_adversarial_review_payload(svc, db, arguments)


def _execute_orchestrator(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Compatibility shim preserving late-bound tools module helpers."""
    return _execute_orchestrator_payload(
        name,
        arguments,
        db_resolver=_resolve_db,
        adversarial_review_executor=_execute_adversarial_review,
        experiment_handoff_prepare_executor=_execute_experiment_handoff_prepare,
        experiment_handoff_submit_executor=_execute_experiment_handoff_submit,
        workflow_entry_executor=_execute_workflow_entry,
        claim_verify_executor=_execute_claim_verify,
        adversarial_section_review_executor=_execute_adversarial_section_review,
    )


# ---------------------------------------------------------------------------
# v2 Step 5 handlers — bounded verification + adversarial section review
# ---------------------------------------------------------------------------


def _execute_claim_verify(db: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run bounded pair-wise claim verification for a topic."""
    from research_harness.execution.claim_verification import verify_claims

    pair_budget = int(arguments.get("pair_budget", 200))
    persist = bool(arguments.get("persist", True))
    result = verify_claims(
        db,
        arguments["topic_id"],
        pair_budget=pair_budget,
        persist=persist,
    )
    return {
        "success": True,
        "topic_id": arguments["topic_id"],
        "total_claims": result.total_claims,
        "pairs_considered": result.pairs_considered,
        "pairs_checked": result.pairs_checked,
        "contradictions_found": result.contradictions_found,
        "flagged_for_human_review": [
            {"claim_id": c.id, "modality": c.modality}
            for c in result.flagged_for_human_review
        ],
    }


def _execute_adversarial_section_review(
    svc: Any, db: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Run adversarial review on a section draft.

    Optionally opens review_issues for severity=critical weaknesses when
    auto_open_issues=True.
    """
    from research_harness.execution.llm_primitives import adversarial_section_review

    topic_id = int(arguments["topic_id"])
    section = arguments["section"]
    content = arguments["content"]
    target_words = int(arguments.get("target_words", 0))
    auto_open_issues = bool(arguments.get("auto_open_issues", True))

    result = adversarial_section_review(
        db=db,
        section=section,
        content=content,
        target_words=target_words,
    )

    opened_issues: list[int] = []
    if auto_open_issues:
        for w in result.get("weaknesses", []):
            if w.get("severity") == "critical":
                try:
                    issue = svc.add_review_issue(
                        topic_id=topic_id,
                        review_type="adversarial_section_review",
                        severity="critical",
                        category=w.get("category", "adversarial"),
                        summary=w.get("description", "")[:200],
                        details=f"Evidence: {w.get('evidence', '')}",
                        blocking=True,
                        recommended_action=(
                            "Address critical weakness and re-run adversarial_section_review"
                        ),
                    )
                    if isinstance(issue, dict) and "issue_id" in issue:
                        opened_issues.append(int(issue["issue_id"]))
                except Exception as exc:
                    logger.warning("Failed to auto-open review issue: %s", exc)
    result["auto_opened_issue_ids"] = opened_issues
    result["topic_id"] = topic_id
    result["success"] = True
    return result


# ---------------------------------------------------------------------------
# Phase 4 handlers — experiment handoff + workflow entry
# ---------------------------------------------------------------------------


def _load_candidate(db: Any, candidate_id: int) -> dict[str, Any] | None:
    """Compatibility shim preserving the tools module helper name."""
    return _load_candidate_payload(db, candidate_id)


def _candidate_evidence(db: Any, candidate: dict[str, Any]) -> dict[str, Any]:
    """Dereference evidence IDs stored on the candidate into full rows."""
    return _candidate_evidence_payload(db, candidate)


def _execute_experiment_handoff_prepare(
    svc: Any, db: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Compatibility shim preserving late-bound candidate helpers."""
    return _execute_experiment_handoff_prepare_payload(
        svc,
        db,
        arguments,
        candidate_loader=_load_candidate,
        evidence_loader=_candidate_evidence,
    )


def _execute_experiment_handoff_submit(
    svc: Any, db: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Compatibility shim preserving the tools module helper name."""
    return _execute_experiment_handoff_submit_payload(svc, db, arguments)


def _execute_workflow_entry(
    svc: Any, db: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Compatibility shim preserving the tools module helper name."""
    return _execute_workflow_entry_payload(svc, db, arguments)


# ---------------------------------------------------------------------------
# Acquisition tools
# ---------------------------------------------------------------------------


def _execute_acquisition(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Compatibility shim preserving late-bound DB resolution."""
    return _execute_acquisition_payload(
        name,
        arguments,
        db_resolver=_resolve_db,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_PRIMITIVE_NAMES: set[str] = set()
_PUBLIC_TOOL_NAMES = set(PUBLIC_MCP_TOOL_NAMES)


def _with_deprecation_notice(name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Compatibility shim preserving the public-tool set binding."""
    return _with_deprecation_notice_payload(
        name,
        result,
        public_tool_names=_PUBLIC_TOOL_NAMES,
    )


def _execute_service_backed_convenience(
    name: str, arguments: dict[str, Any], db: Database | None = None
) -> dict[str, Any]:
    """Compatibility shim preserving monkeypatchable ResearchService binding."""
    return _execute_service_backed_convenience_payload(
        name,
        arguments,
        db,
        service_factory=ResearchService,
    )


def _execute_service_backed_primitive(
    name: str,
    arguments: dict[str, Any],
    db: Database,
) -> dict[str, Any]:
    """Compatibility shim preserving service/session helper bindings."""
    return _execute_service_backed_primitive_payload(
        name,
        arguments,
        db,
        service_factory=ResearchService,
        orch_state_provider=_try_get_orch_state,
        topic_id_extractor=_extract_topic_id,
        session_advisory_provider=_maybe_session_advisory,
        nudge_provider=_check_nudge,
    )


def _all_tool_definitions() -> list[Tool]:
    """Return every executable tool definition, including internal helpers."""

    primitive_tools = _primitive_tool_definitions()
    from .tools_skill import SKILL_TOOLS

    return (
        primitive_tools
        + list(_CONVENIENCE_TOOLS.values())
        + list(_ORCHESTRATOR_TOOLS.values())
        + list(_PAPERINDEX_TOOLS.values())
        + list(_ACQUISITION_TOOLS.values())
        + list(SKILL_TOOLS.values())
        + list(_PRODUCTIZATION_TOOLS.values())
        + DECISION_TOOLS
        + list(_WORKFLOW_COMPLETE_TOOLS.values())
    )


def list_tool_definitions() -> list[Tool]:
    """Return contracted public MCP tool definitions.

    Internal primitives stay executable for backward compatibility through
    ``execute_tool`` but are intentionally not advertised to agents.
    """
    global _PRIMITIVE_NAMES
    _PRIMITIVE_NAMES = {spec.name for spec in list_primitives()}
    return public_tool_definitions(_all_tool_definitions())


def _path_jail_denied_response(name: str, exc: Exception) -> dict[str, Any]:
    return {
        "status": "error",
        "summary": str(exc),
        "output": {"tool": name},
        "next_actions": [],
        "artifacts": [],
        "recovery_hint": "Copy the file into your own working tree and pass that path.",
        "primitive": name,
        "backend": "local",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": "",
    }


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route and execute any tool by name.

    All results are wrapped in HarnessResponse envelope for uniform
    agent guidance (status, summary, next_actions, recovery_hint).
    """
    # Ensure names are populated
    if not _PRIMITIVE_NAMES:
        list_tool_definitions()

    # One chokepoint for every tool: on a shared host the caller may only name
    # paths inside their own tree (RH_PATH_JAIL). No-op where it is unset.
    try:
        check_arguments(arguments, tool=name)
    except PathJailError as exc:
        return _path_jail_denied_response(name, exc)

    from .tools_skill import SKILL_TOOLS, execute_skill_tool

    if name in _PRODUCTIZATION_TOOLS:
        if name in _SERVICE_BACKED_CONVENIENCE_TOOLS:
            raw = _execute_service_backed_convenience(name, arguments)
        else:
            raw = _execute_productization_tool(name, arguments)
        return _with_deprecation_notice(name, _wrap_convenience(name, raw))
    if name in _PRIMITIVE_NAMES:
        if name in _SERVICE_BACKED_CONVENIENCE_TOOLS:
            db = _resolve_db()
            return _with_deprecation_notice(
                name,
                _execute_service_backed_primitive(name, arguments, db),
            )
        return _with_deprecation_notice(name, _execute_primitive(name, arguments))
    elif name in _CONVENIENCE_TOOLS:
        db = _resolve_db()
        if name in _SERVICE_BACKED_CONVENIENCE_TOOLS:
            raw = _execute_service_backed_convenience(name, arguments, db)
        else:
            raw = _execute_convenience(name, arguments)
        orch_state = _try_get_orch_state(db, _extract_topic_id(arguments))
        session_advisory = _maybe_session_advisory(db, name, arguments, orch_state)
        return _with_deprecation_notice(
            name, _wrap_convenience(name, raw, session_advisory=session_advisory)
        )
    elif name in _ORCHESTRATOR_TOOLS:
        if name in _SERVICE_BACKED_CONVENIENCE_TOOLS:
            raw = _execute_service_backed_convenience(name, arguments, _resolve_db())
        else:
            raw = _execute_orchestrator(name, arguments)
        return _with_deprecation_notice(name, _wrap_orchestrator(name, raw))
    elif name in _PAPERINDEX_TOOLS:
        if name in _SERVICE_BACKED_CONVENIENCE_TOOLS:
            raw = _execute_service_backed_convenience(name, arguments)
        else:
            raw = _execute_paperindex(name, arguments)
        return _with_deprecation_notice(
            name, _wrap_convenience(name, raw)
        )  # reuse convenience wrapper
    elif name in _ACQUISITION_TOOLS:
        raw = _execute_acquisition(name, arguments)
        return _with_deprecation_notice(name, _wrap_convenience(name, raw))
    elif name in SKILL_TOOLS:
        if name in _SERVICE_BACKED_CONVENIENCE_TOOLS:
            raw = _execute_service_backed_convenience(name, arguments)
        else:
            raw = execute_skill_tool(name, arguments)
        return _with_deprecation_notice(name, raw)
    elif name in [t.name for t in DECISION_TOOLS]:
        if name in _SERVICE_BACKED_CONVENIENCE_TOOLS:
            raw = _execute_service_backed_convenience(name, arguments, _resolve_db())
        else:
            raw = _execute_decision(name, arguments)
        return _with_deprecation_notice(name, _wrap_convenience(name, raw))
    elif name in _WORKFLOW_COMPLETE_TOOLS:
        if name in _SERVICE_BACKED_CONVENIENCE_TOOLS:
            raw = _execute_service_backed_convenience(name, arguments, _resolve_db())
        else:
            raw = _execute_workflow_complete(name, arguments)
        return _with_deprecation_notice(name, _wrap_convenience(name, raw))
    else:
        return _wrap_convenience(name, {"error": f"Unknown tool: {name}"})


def _wrap_orchestrator(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Compatibility shim preserving late-bound strategy overlay injection."""
    return _wrap_orchestrator_payload(
        name,
        raw,
        strategy_overlay_provider=_inject_strategy_overlay,
    )
