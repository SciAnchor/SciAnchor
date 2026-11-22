"""Service-backed MCP dispatch helpers."""

from __future__ import annotations

from typing import Any, Callable

from research_harness.execution.harness_actions import classify_error
from research_harness.primitives.types import PrimitiveResult
from research_harness.service import ResearchService
from research_harness.storage.db import Database

_SERVICE_BACKED_CONVENIENCE_TOOLS = {
    "paper_search",
    "paper_ingest",
    "paper_summarize",
    "claim_extract",
    "evidence_link",
    "gap_detect",
    "baseline_identify",
    "section_draft",
    "figure_generate",
    "consistency_check",
    "exemplar_curate",
    "exemplar_retrieve",
    "exemplar_plan",
    "exemplar_generate",
    "exemplar_critique",
    "figure_suite_plan",
    "figure_suite_render",
    "figure_package",
    "manuscript_review",
    "manuscript_polish",
    "topic_list",
    "topic_show",
    "paper_list",
    "provenance_summary",
    "provenance_export",
    "orchestrator_status",
    "orchestrator_gate_check",
    "orchestrator_resume",
    "orchestrator_advance",
    "orchestrator_record_artifact",
    "paper_commit_version",
    "paper_task_intake",
    "topic_init",
    "topic_state",
    "paper_production_start",
    "paper_production_pending_decisions",
    "paper_production_decide",
    "paper_production_status",
    "paper_production_resume",
    "paper_production_mode",
    "paper_production_set_mode",
    "paper_production_export",
    "adversarial_review",
    "advisory_check",
    "zotero_sync",
    "topic_knowledge_status",
    "topic_knowledge_refresh",
    "cross_topic_atlas",
    "paperindex_search",
    "skill_list",
    "skill_get",
    "productization_boundary",
    "resource_ready_get",
}


def _with_deprecation_notice(
    name: str,
    result: dict[str, Any],
    *,
    public_tool_names: set[str],
) -> dict[str, Any]:
    """Mark compatibility-only tool calls without changing their payload shape."""

    if name in public_tool_names or "_deprecated" in result:
        return result
    return {
        **result,
        "_deprecated": (
            f"{name} is still executable for compatibility, but it is not part "
            "of the public MCP contract. Prefer one of the Tier A workflow-level "
            "tools advertised by tools/list."
        ),
    }


def _execute_service_backed_convenience(
    name: str,
    arguments: dict[str, Any],
    db: Database | None = None,
    *,
    service_factory: Callable[..., Any] = ResearchService,
) -> dict[str, Any]:
    """Execute a migrated convenience tool through the service dispatcher."""

    result = service_factory(db=db).invoke(name, arguments)
    if result.status == "error":
        message = result.error["message"] if result.error else result.summary
        if isinstance(result.output, dict) and result.output.get("error"):
            return result.output
        return {"error": message}
    return result.output


def _execute_service_backed_primitive(
    name: str,
    arguments: dict[str, Any],
    db: Database,
    *,
    service_factory: Callable[..., Any] = ResearchService,
    orch_state_provider: Callable[[Database, int | None], dict[str, Any] | None],
    topic_id_extractor: Callable[[dict[str, Any]], int | None],
    session_advisory_provider: Callable[
        [Database, str, dict[str, Any], dict[str, Any] | None], str
    ],
    nudge_provider: Callable[[Database, str, dict[str, Any], PrimitiveResult], str],
) -> dict[str, Any]:
    """Execute a migrated primitive through service while preserving MCP shape."""

    result = service_factory(db=db).invoke(name, arguments)
    payload = result.to_dict()
    metadata = payload.get("metadata") or {}
    orch_state = orch_state_provider(db, topic_id_extractor(arguments))
    session_advisory = session_advisory_provider(db, name, arguments, orch_state)

    error_message = ""
    if payload.get("error"):
        error_message = str(payload["error"].get("message", ""))
    primitive_result = PrimitiveResult(
        primitive=str(metadata.get("primitive") or name),
        success=payload["status"] == "success",
        output=result.output,
        error=error_message,
        backend=str(metadata.get("backend") or "local"),
        model_used=str(metadata.get("model_used") or ""),
        cost_usd=float(metadata.get("cost_usd") or 0.0),
        prompt_tokens=int(metadata.get("prompt_tokens") or 0),
        completion_tokens=int(metadata.get("completion_tokens") or 0),
    )
    nudge_text = nudge_provider(db, name, arguments, primitive_result)

    response: dict[str, Any] = {
        "status": payload["status"],
        "summary": payload["summary"],
        "output": payload["output"],
        "next_actions": payload["next_actions"],
        "artifacts": payload["artifacts"],
        "recovery_hint": payload["recovery_hint"]
        or (classify_error(error_message) if error_message else ""),
        "primitive": primitive_result.primitive,
        "backend": primitive_result.backend,
        "model_used": primitive_result.model_used,
        "cost_usd": primitive_result.cost_usd,
        "session_advisory": session_advisory,
    }
    if nudge_text:
        response["nudge"] = nudge_text
    return response
