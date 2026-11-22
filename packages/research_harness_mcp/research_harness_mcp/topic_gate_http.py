"""FastAPI route registration for topic orchestrator gate reads."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI

from research_harness.execution.harness_actions import classify_error
from research_harness.service import ResearchService


def _orchestrator_gate_check_service_response(
    topic_id: int,
    *,
    db_path: Any,
    classify_error_fn: Callable[[str], str] = classify_error,
    service_factory: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    service = (
        service_factory(db_path) if service_factory else ResearchService(db=db_path)
    )
    result = service.invoke("orchestrator_gate_check", {"topic_id": topic_id})
    raw = result.output if isinstance(result.output, dict) else {}
    if result.status == "error":
        message = result.error["message"] if result.error else result.summary
        raw = {**raw, "error": raw.get("error") or message}
    elif not isinstance(result.output, dict):
        raw = {
            "error": "ResearchService orchestrator_gate_check returned an invalid payload"
        }

    is_error = "error" in raw
    summary = str(raw.get("error", ""))
    next_actions: list[str] = []
    if not is_error:
        decision = raw.get("gate_decision", "?")
        summary = f"Gate decision: {decision}"
        if decision == "pass":
            next_actions.append("orchestrator_advance — gate passed")
        elif decision == "fail":
            next_actions.append("orchestrator_status — check what's missing")

    return {
        "status": "error" if is_error else "success",
        "summary": summary,
        "output": raw,
        "next_actions": next_actions,
        "artifacts": [],
        "recovery_hint": classify_error_fn(str(raw["error"])) if is_error else "",
        "primitive": "orchestrator_gate_check",
        "backend": "orchestrator",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": "",
    }


def register_topic_gate_routes(
    app: FastAPI,
    *,
    db_path_provider: Callable[[], Any],
    classify_error_fn: Callable[[str], str] = classify_error,
    service_factory: Callable[[Any], Any] | None = None,
) -> None:
    """Register topic gate route with injected runtime dependencies."""

    @app.get("/api/topics/{topic_id}/gate")
    def check_gate(topic_id: int):
        """Check the gate for the current orchestrator stage."""
        return _orchestrator_gate_check_service_response(
            topic_id,
            db_path=db_path_provider(),
            classify_error_fn=classify_error_fn,
            service_factory=service_factory,
        )
