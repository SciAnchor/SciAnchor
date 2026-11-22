"""MCP strategy-overlay helper."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _inject_strategy_overlay(
    raw: dict[str, Any],
    *,
    db_resolver: Callable[[], Any],
    injector_factory: Callable[[Any], Any] | None = None,
) -> str:
    """Build strategy overlay for the current orchestrator stage."""
    try:
        # Extract stage from response
        stage = raw.get("current_stage", "")
        if not stage:
            run = raw.get("run", {})
            stage = run.get("current_stage", "")
        if not stage:
            stage = raw.get("to_stage", "")
        if not stage:
            return ""

        # Extract topic_id
        topic_id = raw.get("topic_id")
        if not topic_id:
            run = raw.get("run", {})
            topic_id = run.get("topic_id")

        db = db_resolver()
        if injector_factory is None:
            from research_harness.evolution.topic.injector import StrategyInjector

            injector_factory = StrategyInjector

        injector = injector_factory(db)
        overlay = injector.build_strategy_overlay(
            stage,
            topic_id=topic_id,
            max_strategies=3,
        )

        # Record injection counts
        strategies = injector.get_active_strategies(
            stage, topic_id=topic_id, max_strategies=3
        )
        for s in strategies:
            injector.record_injection(s.id)

        return overlay
    except Exception:
        return ""
