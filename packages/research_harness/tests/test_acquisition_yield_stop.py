"""Tests for the acquisition yield stop criterion (P-1).

Motivating incident (topic 73 / run 32, 2026-08-08). The run made a terminal
strict-coverage gate the prerequisite for every user-visible result, then
"optimized raw downloads and annotations instead of the actual eligibility
predicate, continued low-yield acquisition despite 429/500 responses ... and
had no time budget or stop criterion".

RH already has a wall-time budget, but it is evaluated BETWEEN stages and
defaults to 480 minutes, so a run can burn eight hours inside one acquisition
loop untouched. What is missing is a criterion expressed in the quantity that
actually matters: papers that become STRICT-COVERAGE ELIGIBLE, not papers
downloaded.

This monitor is advisory: it reports `should_stop` with a reason. Wiring it to
an actual abort is a separate, gated change.
"""

from __future__ import annotations

from research_harness.acquisition.yield_monitor import (
    ACQUISITION_YIELD_SCHEMA,
    AcquisitionYieldMonitor,
)


def _monitor(**kwargs) -> AcquisitionYieldMonitor:
    return AcquisitionYieldMonitor(**kwargs)


def test_schema_id_is_stable() -> None:
    assert ACQUISITION_YIELD_SCHEMA == "rh.schema.report.acquisition_yield.v1"


def test_productive_batches_do_not_stop() -> None:
    m = _monitor(min_eligible_gain=2, patience=2)
    for _ in range(5):
        decision = m.record_batch(fetched=10, eligible_gain=5)
        assert decision.should_stop is False
    assert m.snapshot()["batches"] == 5


def test_consecutive_low_yield_batches_trigger_stop() -> None:
    m = _monitor(min_eligible_gain=2, patience=2)
    assert m.record_batch(fetched=10, eligible_gain=0).should_stop is False
    decision = m.record_batch(fetched=10, eligible_gain=1)
    assert decision.should_stop is True
    assert decision.reason == "low_eligible_yield"
    assert "2 consecutive" in decision.detail


def test_a_productive_batch_resets_patience() -> None:
    """One good batch means the lane is not exhausted — keep going."""
    m = _monitor(min_eligible_gain=2, patience=2)
    m.record_batch(fetched=10, eligible_gain=0)
    m.record_batch(fetched=10, eligible_gain=9)  # resets
    assert m.record_batch(fetched=10, eligible_gain=0).should_stop is False


def test_downloads_without_eligible_gain_still_count_as_low_yield() -> None:
    """The exact 2026-08-08 failure: many papers fetched, almost none eligible.
    Optimizing `fetched` is what made the run look productive while it was not.
    """
    m = _monitor(min_eligible_gain=2, patience=2)
    m.record_batch(fetched=40, eligible_gain=1)
    decision = m.record_batch(fetched=55, eligible_gain=0)
    assert decision.should_stop is True
    snap = m.snapshot()
    assert snap["fetched_total"] == 95
    assert snap["eligible_gain_total"] == 1


def test_repeated_transport_errors_trigger_stop() -> None:
    """429/500 storms were ridden out for hours instead of stopping."""
    m = _monitor(min_eligible_gain=1, patience=99, max_consecutive_errors=3)
    for _ in range(2):
        assert m.record_batch(fetched=0, eligible_gain=0, errors=5).should_stop is False
    decision = m.record_batch(fetched=0, eligible_gain=0, errors=5)
    assert decision.should_stop is True
    assert decision.reason == "repeated_transport_errors"


def test_successful_batch_resets_error_streak() -> None:
    m = _monitor(min_eligible_gain=1, patience=99, max_consecutive_errors=2)
    m.record_batch(fetched=0, eligible_gain=0, errors=3)
    m.record_batch(fetched=5, eligible_gain=3, errors=0)
    assert m.record_batch(fetched=0, eligible_gain=0, errors=3).should_stop is False


def test_batch_cap_stops_the_lane() -> None:
    m = _monitor(min_eligible_gain=1, patience=99, max_batches=3)
    for _ in range(2):
        assert m.record_batch(fetched=5, eligible_gain=5).should_stop is False
    decision = m.record_batch(fetched=5, eligible_gain=5)
    assert decision.should_stop is True
    assert decision.reason == "batch_cap_reached"


def test_snapshot_reports_cost_per_eligible_paper() -> None:
    """The number the operator actually needs: how many fetches buy one
    eligible paper. 137 linked / 11 eligible was invisible during the run."""
    m = _monitor()
    m.record_batch(fetched=100, eligible_gain=10)
    snap = m.snapshot()
    assert snap["schema"] == ACQUISITION_YIELD_SCHEMA
    assert snap["fetched_per_eligible"] == 10.0


def test_snapshot_handles_zero_eligible_without_dividing_by_zero() -> None:
    m = _monitor()
    m.record_batch(fetched=50, eligible_gain=0)
    assert m.snapshot()["fetched_per_eligible"] is None


def test_monitor_never_stops_before_any_batch() -> None:
    assert _monitor().snapshot()["should_stop"] is False


# -- Persistent ledger: yield across runner iterations -------------------------


def test_ledger_records_and_computes_gain_between_snapshots(tmp_path) -> None:
    from research_harness.acquisition.yield_monitor import (
        record_coverage_snapshot,
        yield_trend,
    )

    ledger = tmp_path / "yield.jsonl"
    record_coverage_snapshot(topic_id=73, eligible=11, linked=137, ledger_path=ledger)
    record_coverage_snapshot(topic_id=73, eligible=12, linked=170, ledger_path=ledger)
    record_coverage_snapshot(topic_id=73, eligible=12, linked=205, ledger_path=ledger)

    trend = yield_trend(73, ledger_path=ledger, min_eligible_gain=2, patience=2)
    assert trend["snapshots"] == 3
    assert trend["eligible_latest"] == 12
    assert trend["linked_latest"] == 205
    # Two consecutive intervals gained 1 and 0 — both below the threshold.
    assert trend["should_stop"] is True
    assert trend["stop_reason"] == "low_eligible_yield"


def test_ledger_isolates_topics(tmp_path) -> None:
    from research_harness.acquisition.yield_monitor import (
        record_coverage_snapshot,
        yield_trend,
    )

    ledger = tmp_path / "yield.jsonl"
    record_coverage_snapshot(topic_id=73, eligible=11, linked=137, ledger_path=ledger)
    record_coverage_snapshot(topic_id=99, eligible=50, linked=60, ledger_path=ledger)
    assert yield_trend(73, ledger_path=ledger)["snapshots"] == 1
    assert yield_trend(99, ledger_path=ledger)["eligible_latest"] == 50


def test_single_snapshot_cannot_conclude_anything(tmp_path) -> None:
    """One data point is not a trend — it must not trigger a stop."""
    from research_harness.acquisition.yield_monitor import (
        record_coverage_snapshot,
        yield_trend,
    )

    ledger = tmp_path / "yield.jsonl"
    record_coverage_snapshot(topic_id=73, eligible=11, linked=137, ledger_path=ledger)
    trend = yield_trend(73, ledger_path=ledger, patience=1)
    assert trend["should_stop"] is False


def test_missing_ledger_is_not_an_error(tmp_path) -> None:
    from research_harness.acquisition.yield_monitor import yield_trend

    trend = yield_trend(73, ledger_path=tmp_path / "absent.jsonl")
    assert trend["snapshots"] == 0
    assert trend["should_stop"] is False


# -- Automatic recording: the ledger must fill itself --------------------------


def test_audit_records_a_coverage_snapshot(tmp_path, monkeypatch) -> None:
    """A ledger nobody writes to is a ledger with no trend. The audit is the
    natural write point: it already computes the eligible count, and it runs
    every time the build gate is checked."""
    from research_harness.acquisition import yield_monitor

    ledger = tmp_path / "yield.jsonl"
    monkeypatch.setattr(yield_monitor, "DEFAULT_LEDGER", ledger)

    from research_harness.paper_pool_audit import record_audit_coverage_snapshot

    record_audit_coverage_snapshot(
        topic_id=73, counts={"coverage_eligible": 11, "total_linked": 137}
    )
    record_audit_coverage_snapshot(
        topic_id=73, counts={"coverage_eligible": 12, "total_linked": 170}
    )

    trend = yield_monitor.yield_trend(73, ledger_path=ledger)
    assert trend["snapshots"] == 2
    assert trend["eligible_latest"] == 12
    assert trend["linked_latest"] == 170


def test_snapshot_recording_never_raises_on_bad_counts(tmp_path, monkeypatch) -> None:
    from research_harness.acquisition import yield_monitor
    from research_harness.paper_pool_audit import record_audit_coverage_snapshot

    monkeypatch.setattr(yield_monitor, "DEFAULT_LEDGER", tmp_path / "y.jsonl")
    record_audit_coverage_snapshot(topic_id=73, counts={})
    record_audit_coverage_snapshot(topic_id=73, counts={"coverage_eligible": None})
