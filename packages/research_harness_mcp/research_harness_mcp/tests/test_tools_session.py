"""Focused tests for MCP session advisory and nudge helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_extract_topic_id_accepts_int_like_values() -> None:
    from research_harness_mcp.tools_session import _extract_topic_id

    assert _extract_topic_id({"topic_id": 7}) == 7
    assert _extract_topic_id({"topic_id": "8"}) == 8
    assert _extract_topic_id({"topic_id": "not-int"}) is None
    assert _extract_topic_id({}) is None


def test_maybe_session_advisory_preserves_trigger_streak_text() -> None:
    from research_harness_mcp.tools_session import (
        _SESSION_ACTIVITY,
        _maybe_session_advisory,
    )

    _SESSION_ACTIVITY["last_topic_id"] = None
    _SESSION_ACTIVITY["streak"] = 0

    assert (
        _maybe_session_advisory(object(), "paper_search", {"topic_id": "7"}, None) == ""
    )
    assert (
        _maybe_session_advisory(object(), "paper_ingest", {"topic_id": 7}, None) == ""
    )
    advisory = _maybe_session_advisory(object(), "gap_detect", {"topic_id": 7}, None)

    assert "Detected 3 consecutive operations on topic 7" in advisory
    assert "orchestrator_resume" in advisory


def test_maybe_session_advisory_ignores_non_triggers_and_existing_runs() -> None:
    from research_harness_mcp.tools_session import (
        _SESSION_ACTIVITY,
        _maybe_session_advisory,
    )

    _SESSION_ACTIVITY["last_topic_id"] = None
    _SESSION_ACTIVITY["streak"] = 0

    assert _maybe_session_advisory(object(), "topic_list", {"topic_id": 7}, None) == ""
    assert (
        _maybe_session_advisory(object(), "paper_search", {"topic_id": "bad"}, None)
        == ""
    )
    assert (
        _maybe_session_advisory(
            object(),
            "paper_search",
            {"topic_id": 7},
            {"run": {"current_stage": "build"}},
        )
        == ""
    )


def test_check_nudge_returns_empty_when_manager_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools_session as tools_session

    monkeypatch.setattr(tools_session, "_get_nudge_manager", lambda db: None)

    result = tools_session._check_nudge(
        object(),
        "paper_search",
        {"topic_id": 7},
        SimpleNamespace(cost_usd=0.5),
    )

    assert result == ""


def test_check_nudge_formats_manager_decision_and_tracks_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools_session as tools_session

    calls: list[tuple[str, object]] = []

    class FakeNudgeManager:
        def tick(self) -> None:
            calls.append(("tick", None))

        def check_nudge(
            self,
            *,
            stage: str,
            cost_usd: float,
            experiment_count: int,
        ) -> str:
            calls.append(("check", (stage, cost_usd, experiment_count)))
            return "decision"

        def format_nudge(self, nudge: str) -> str:
            calls.append(("format", nudge))
            return f"formatted:{nudge}"

    tools_session._SESSION_NUDGE_MGR["cost_usd"] = 0.0
    tools_session._SESSION_NUDGE_MGR["experiment_count"] = 0
    monkeypatch.setattr(
        tools_session,
        "_get_nudge_manager",
        lambda db: FakeNudgeManager(),
    )

    result = tools_session._check_nudge(
        object(),
        "experiment_run",
        {"stage": "build"},
        SimpleNamespace(cost_usd=0.25),
    )

    assert result == "formatted:decision"
    assert calls == [
        ("tick", None),
        ("check", ("build", 0.25, 1)),
        ("format", "decision"),
    ]
