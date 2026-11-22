"""Focused tests for MCP tool HarnessResponse wrapper helpers."""

from __future__ import annotations


ENVELOPE_KEYS = {
    "status",
    "summary",
    "output",
    "next_actions",
    "artifacts",
    "recovery_hint",
    "primitive",
    "backend",
    "model_used",
    "cost_usd",
    "session_advisory",
}


def test_wrap_convenience_preserves_success_and_error_envelopes() -> None:
    from research_harness_mcp.tool_wrappers import _wrap_convenience

    success = _wrap_convenience("topic_list", {"topics": []})
    assert ENVELOPE_KEYS.issubset(success)
    assert success["status"] == "success"
    assert success["summary"] == "topic_list completed"
    assert success["output"] == {"topics": []}
    assert success["primitive"] == "topic_list"
    assert success["backend"] == "local"

    error = _wrap_convenience("topic_list", {"error": "database unavailable"})
    assert ENVELOPE_KEYS.issubset(error)
    assert error["status"] == "error"
    assert error["summary"] == "database unavailable"
    assert error["output"] == {"error": "database unavailable"}
    assert error["recovery_hint"]


def test_wrap_orchestrator_preserves_summary_next_actions_and_overlay() -> None:
    from research_harness_mcp.tool_wrappers import _wrap_orchestrator

    calls: list[dict] = []

    def overlay_provider(raw: dict) -> str:
        calls.append(raw)
        return "stage strategy overlay"

    raw = {
        "run": {"current_stage": "build"},
        "gate": {"decision": "pass", "can_advance": True},
        "stage": {"missing_artifacts": ["literature_map"]},
    }

    result = _wrap_orchestrator(
        "orchestrator_status",
        raw,
        strategy_overlay_provider=overlay_provider,
    )

    assert ENVELOPE_KEYS.issubset(result)
    assert result["status"] == "success"
    assert result["summary"] == "Stage: build, gate: pass"
    assert result["output"] == raw
    assert result["backend"] == "orchestrator"
    assert any("orchestrator_advance" in action for action in result["next_actions"])
    assert any(
        "Record missing artifacts" in action for action in result["next_actions"]
    )
    assert result["strategy_overlay"] == "stage strategy overlay"
    assert calls == [raw]


def test_wrap_orchestrator_error_keeps_recovery_hint_without_overlay() -> None:
    from research_harness_mcp.tool_wrappers import _wrap_orchestrator

    def fail_overlay_provider(raw: dict) -> str:
        del raw
        raise AssertionError("overlay provider should not run for errors")

    result = _wrap_orchestrator(
        "orchestrator_status",
        {"error": "missing topic"},
        strategy_overlay_provider=fail_overlay_provider,
    )

    assert ENVELOPE_KEYS.issubset(result)
    assert result["status"] == "error"
    assert result["summary"] == "missing topic"
    assert result["recovery_hint"]
    assert "strategy_overlay" not in result
