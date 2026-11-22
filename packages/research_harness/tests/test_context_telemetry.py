"""Tests for context-budget telemetry (P-6 / FIX02).

Purpose: RH currently truncates evidence with scattered hardcoded character
limits and keeps NO record of what was dropped. An evidence item can be absent
from the model input with no trace — a real provenance hole.

This module is instrumentation only. It must not change any assembly result.
"""

from __future__ import annotations

import json

from research_harness.runtime.context_telemetry import (
    CONTEXT_BUDGET_SCHEMA,
    context_budget_scope,
    record_source,
    summarize_events,
)


def test_schema_id_is_stable() -> None:
    assert CONTEXT_BUDGET_SCHEMA == "rh.schema.event.context_budget.v1"


def test_scope_emits_one_event_with_conservation(tmp_path) -> None:
    sink = tmp_path / "ctx.jsonl"
    with context_budget_scope(
        primitive="claim_extract", stage="analyze", topic_id=7, sink_path=sink
    ):
        record_source(
            kind="paper_text",
            source_id="p1",
            offered=1000,
            kept=500,
            reason="char_truncation",
        )
        record_source(kind="paper_text", source_id="p2", offered=200, kept=200)

    lines = sink.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])

    assert event["schema"] == CONTEXT_BUDGET_SCHEMA
    assert event["primitive"] == "claim_extract"
    assert event["stage"] == "analyze"
    assert event["topic_id"] == 7
    # Conservation: offered == kept + dropped, always.
    assert event["offered_chars"] == 1200
    assert event["kept_chars"] == 700
    assert event["dropped_chars"] == 500
    assert len(event["drops"]) == 1
    assert event["drops"][0]["source_id"] == "p1"
    assert event["drops"][0]["reason"] == "char_truncation"


def test_fully_kept_sources_are_not_listed_as_drops(tmp_path) -> None:
    sink = tmp_path / "ctx.jsonl"
    with context_budget_scope(primitive="paper_summarize", sink_path=sink):
        record_source(kind="abstract", source_id="a1", offered=300, kept=300)

    event = json.loads(sink.read_text(encoding="utf-8").strip())
    assert event["drops"] == []
    assert event["dropped_chars"] == 0
    assert event["sources_offered"] == 1
    assert event["sources_fully_dropped"] == 0


def test_fully_dropped_source_is_counted(tmp_path) -> None:
    """The dangerous case: evidence that never reached the model at all."""
    sink = tmp_path / "ctx.jsonl"
    with context_budget_scope(primitive="gap_detect", sink_path=sink):
        record_source(
            kind="claim", source_id="c9", offered=400, kept=0, reason="budget_exhausted"
        )

    event = json.loads(sink.read_text(encoding="utf-8").strip())
    assert event["sources_fully_dropped"] == 1
    assert event["drops"][0]["kept_chars"] == 0


def test_record_outside_scope_is_a_noop(tmp_path) -> None:
    """Instrumentation must never raise in production paths."""
    record_source(kind="paper_text", source_id="orphan", offered=10, kept=1)


def test_sink_is_append_only(tmp_path) -> None:
    sink = tmp_path / "ctx.jsonl"
    for i in range(3):
        with context_budget_scope(primitive=f"p{i}", sink_path=sink):
            record_source(kind="x", source_id=str(i), offered=10, kept=5)

    lines = sink.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert [json.loads(x)["primitive"] for x in lines] == ["p0", "p1", "p2"]


def test_scope_emits_even_when_body_raises(tmp_path) -> None:
    sink = tmp_path / "ctx.jsonl"
    try:
        with context_budget_scope(primitive="deep_read", sink_path=sink):
            record_source(kind="pdf", source_id="d1", offered=900, kept=100)
            raise ValueError("boom")
    except ValueError:
        pass

    event = json.loads(sink.read_text(encoding="utf-8").strip())
    assert event["dropped_chars"] == 800
    assert event["errored"] is True


def test_summarize_events_reports_per_primitive_truncation(tmp_path) -> None:
    sink = tmp_path / "ctx.jsonl"
    with context_budget_scope(primitive="claim_extract", sink_path=sink):
        record_source(kind="paper_text", source_id="p1", offered=1000, kept=200)
    with context_budget_scope(primitive="claim_extract", sink_path=sink):
        record_source(kind="paper_text", source_id="p2", offered=1000, kept=1000)
    with context_budget_scope(primitive="gap_detect", sink_path=sink):
        record_source(kind="claim", source_id="c1", offered=500, kept=0)

    report = summarize_events(sink)
    by_prim = {row["primitive"]: row for row in report["per_primitive"]}

    assert by_prim["claim_extract"]["calls"] == 2
    assert by_prim["claim_extract"]["offered_chars"] == 2000
    assert by_prim["claim_extract"]["dropped_chars"] == 800
    assert by_prim["gap_detect"]["sources_fully_dropped"] == 1
    assert report["totals"]["sources_fully_dropped"] == 1


# -- Instrumentation of real truncation sites must not change behaviour -------


def test_compact_context_value_output_is_unchanged_by_instrumentation() -> None:
    """_compact_context_value is a live truncation site. Instrumenting it must
    leave its return value byte-identical, inside and outside a scope."""
    from research_harness._workflow.execution.llm_primitives import (
        _compact_context_value,
    )

    long_text = "word " * 400  # comfortably over any max_chars used in RH
    cases = [
        (long_text, 700),
        (long_text, 240),
        ("short", 700),
        ({"a": 1, "b": [1, 2, 3]}, 700),
        ([1, 2, 3], 10),
    ]

    outside = [_compact_context_value(v, max_chars=m) for v, m in cases]
    with context_budget_scope(primitive="unit_check"):
        inside = [_compact_context_value(v, max_chars=m) for v, m in cases]

    assert inside == outside


def test_compact_context_value_records_its_truncation(tmp_path) -> None:
    from research_harness._workflow.execution.llm_primitives import (
        _compact_context_value,
    )

    sink = tmp_path / "ctx.jsonl"
    with context_budget_scope(primitive="unit_check", sink_path=sink):
        _compact_context_value("word " * 400, max_chars=700)

    event = json.loads(sink.read_text(encoding="utf-8").strip())
    assert event["dropped_chars"] > 0
    assert event["drops"][0]["reason"] == "compact_context_value"


# -- Doctor visibility: a disabled sink must be visible before a run ----------


def test_doctor_reports_telemetry_disabled_by_default(monkeypatch) -> None:
    """Telemetry that is off by default and invisible is telemetry that will be
    discovered to be off only after the run it was meant to instrument."""
    from research_harness.runtime.context_telemetry import telemetry_status

    monkeypatch.delenv("RESEARCH_HARNESS_CONTEXT_TELEMETRY", raising=False)
    status = telemetry_status()
    assert status["check"] == "context_telemetry"
    assert status["enabled"] is False
    assert status["ok"] is True  # optional, so not a failure
    assert "RESEARCH_HARNESS_CONTEXT_TELEMETRY" in status["remediation"][0]


def test_doctor_reports_telemetry_enabled_with_sink(monkeypatch, tmp_path) -> None:
    from research_harness.runtime.context_telemetry import telemetry_status

    sink = tmp_path / "ctx.jsonl"
    monkeypatch.setenv("RESEARCH_HARNESS_CONTEXT_TELEMETRY", str(sink))
    status = telemetry_status()
    assert status["enabled"] is True
    assert status["sink"] == str(sink)
    assert status["events_recorded"] == 0


def test_doctor_reports_recorded_event_count(monkeypatch, tmp_path) -> None:
    from research_harness.runtime.context_telemetry import (
        context_budget_scope,
        record_source,
        telemetry_status,
    )

    sink = tmp_path / "ctx.jsonl"
    monkeypatch.setenv("RESEARCH_HARNESS_CONTEXT_TELEMETRY", str(sink))
    with context_budget_scope(primitive="p"):
        record_source(kind="x", source_id="1", offered=10, kept=5)

    assert telemetry_status()["events_recorded"] == 1
