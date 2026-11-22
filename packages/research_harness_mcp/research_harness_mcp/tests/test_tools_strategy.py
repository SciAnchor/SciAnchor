"""Focused tests for MCP strategy-overlay helper extraction."""

from __future__ import annotations

from typing import Any


def test_inject_strategy_overlay_extracts_stage_and_topic_from_run() -> None:
    from research_harness_mcp.tools_strategy import _inject_strategy_overlay

    calls: list[tuple[str, Any]] = []

    class Strategy:
        def __init__(self, strategy_id: int) -> None:
            self.id = strategy_id

    class FakeInjector:
        def __init__(self, db: object) -> None:
            calls.append(("init", db))

        def build_strategy_overlay(
            self, stage: str, *, topic_id: int, max_strategies: int
        ) -> str:
            calls.append(("build", (stage, topic_id, max_strategies)))
            return "overlay text"

        def get_active_strategies(
            self, stage: str, *, topic_id: int, max_strategies: int
        ) -> list[Strategy]:
            calls.append(("active", (stage, topic_id, max_strategies)))
            return [Strategy(3), Strategy(5)]

        def record_injection(self, strategy_id: int) -> None:
            calls.append(("record", strategy_id))

    db = object()
    result = _inject_strategy_overlay(
        {"run": {"current_stage": "build", "topic_id": 7}},
        db_resolver=lambda: db,
        injector_factory=FakeInjector,
    )

    assert result == "overlay text"
    assert calls == [
        ("init", db),
        ("build", ("build", 7, 3)),
        ("active", ("build", 7, 3)),
        ("record", 3),
        ("record", 5),
    ]


def test_inject_strategy_overlay_returns_empty_without_stage() -> None:
    from research_harness_mcp.tools_strategy import _inject_strategy_overlay

    def fail_db_resolver() -> object:
        raise AssertionError("db should not be resolved without a stage")

    assert _inject_strategy_overlay({}, db_resolver=fail_db_resolver) == ""
