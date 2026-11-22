"""HarnessResponse wrapper helpers for MCP tool execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from research_harness.execution.harness_actions import classify_error
from research_harness.primitives.types import PrimitiveResult


def _serialize_result(
    result: PrimitiveResult,
    orch_state: dict[str, Any] | None = None,
    session_advisory: str = "",
    nudge: str = "",
) -> dict[str, Any]:
    """Convert PrimitiveResult to a HarnessResponse-shaped dict."""
    from research_harness.execution.harness_actions import (
        classify_error,
        compute_next_actions,
        compute_summary,
        extract_artifacts,
    )

    output = result.output
    if output is not None and hasattr(output, "__dataclass_fields__"):
        output = asdict(output)
    resp: dict[str, Any] = {
        "status": "success" if result.success else "error",
        "summary": compute_summary(result.primitive, result),
        "output": output,
        "next_actions": compute_next_actions(result.primitive, result, orch_state),
        "artifacts": extract_artifacts(result),
        "recovery_hint": classify_error(result.error) if not result.success else "",
        "primitive": result.primitive,
        "backend": result.backend,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
        "session_advisory": session_advisory,
    }
    if nudge:
        resp["nudge"] = nudge
    return resp


def _wrap_convenience(
    name: str, raw: dict[str, Any], session_advisory: str = ""
) -> dict[str, Any]:
    """Wrap a convenience tool result in HarnessResponse envelope."""
    is_error = "error" in raw
    return {
        "status": "error" if is_error else "success",
        "summary": raw.get("error", f"{name} completed"),
        "output": raw,
        "next_actions": [],
        "artifacts": [],
        "recovery_hint": classify_error(raw["error"]) if is_error else "",
        "primitive": name,
        "backend": "local",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": session_advisory,
    }


def _wrap_orchestrator(
    name: str,
    raw: dict[str, Any],
    *,
    strategy_overlay_provider: Callable[[dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """Wrap an orchestrator tool result in HarnessResponse envelope."""
    is_error = "error" in raw
    summary = raw.get("error", "")
    next_actions: list[str] = []

    if not is_error:
        if name == "orchestrator_status":
            run = raw.get("run", {})
            gate = raw.get("gate", {})
            stage = run.get("current_stage", "?")
            summary = f"Stage: {stage}, gate: {gate.get('decision', '?')}"
            if gate.get("can_advance"):
                next_actions.append(
                    f"orchestrator_advance — gate passed, ready to move past {stage}"
                )
            missing = raw.get("stage", {}).get("missing_artifacts", [])
            if missing:
                next_actions.append(f"Record missing artifacts: {', '.join(missing)}")
        elif name == "orchestrator_resume":
            stage = raw.get("current_stage", "?")
            inferred = raw.get("inferred_stage", stage)
            summary = (
                f"Resumed run at stage: {stage} (inferred from artifacts: {inferred})"
            )
            next_actions.append(
                "orchestrator_status — check current stage requirements"
            )
        elif name == "orchestrator_advance":
            summary = "Advanced to next stage"
            next_actions.append("orchestrator_status — check new stage requirements")
        elif name == "orchestrator_record_artifact":
            summary = f"Recorded artifact: {raw.get('type', '?')} (id={raw.get('artifact_id', '?')})"
            next_actions.append("orchestrator_gate_check — check if gate now passes")
        elif name == "orchestrator_add_artifact_dependency":
            summary = (
                f"Linked artifact {raw.get('to_artifact_id', '?')} to upstream "
                f"{raw.get('from_artifact_id', '?')}"
            )
        elif name == "orchestrator_mark_artifact_stale":
            count = len(raw.get("stale_ids", []))
            summary = f"Marked {count} artifact(s) stale"
            next_actions.append(
                "orchestrator_list_stale_artifacts — inspect affected downstream artifacts"
            )
        elif name == "orchestrator_clear_artifact_stale":
            summary = f"Cleared stale flag for artifact {raw.get('artifact_id', '?')}"
        elif name == "orchestrator_list_stale_artifacts":
            count = raw.get("count", 0)
            summary = f"{count} stale artifact(s) currently active"
            if count:
                next_actions.append(
                    "Refresh or supersede stale artifacts, then clear flags if appropriate"
                )
        elif name == "orchestrator_gate_check":
            decision = raw.get("gate_decision", "?")
            summary = f"Gate decision: {decision}"
            if decision == "pass":
                next_actions.append("orchestrator_advance — gate passed")
            elif decision == "fail":
                next_actions.append("orchestrator_status — check what's missing")
        elif name == "adversarial_review":
            verdict = raw.get("verdict", "?")
            backend = raw.get("backend", "?")
            issues = raw.get("issues_count", 0)
            critical = raw.get("critical_count", 0)
            summary = (
                f"Independent review ({backend}): verdict={verdict}, "
                f"{issues} issues ({critical} critical)"
            )
            if verdict == "revise":
                next_actions.append(
                    "Address critical/major issues, then re-run adversarial_review"
                )
            else:
                next_actions.append(
                    "orchestrator_gate_check — check if ready to advance"
                )
        else:
            summary = f"{name} completed"

    resp: dict[str, Any] = {
        "status": "error" if is_error else "success",
        "summary": summary,
        "output": raw,
        "next_actions": next_actions,
        "artifacts": [],
        "recovery_hint": classify_error(raw["error"]) if is_error else "",
        "primitive": name,
        "backend": "orchestrator",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": "",
    }

    if (
        not is_error
        and strategy_overlay_provider is not None
        and name
        in (
            "orchestrator_status",
            "orchestrator_resume",
            "orchestrator_advance",
        )
    ):
        strategy_overlay = strategy_overlay_provider(raw)
        if strategy_overlay:
            resp["strategy_overlay"] = strategy_overlay

    return resp
