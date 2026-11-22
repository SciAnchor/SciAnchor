"""Acquisition yield stop criterion (P-1).

Why this exists — from the topic 73 / run 32 postmortem (2026-08-08):

    "The primary failure was sequencing, not intrinsic paper complexity. The run
    made the terminal strict-coverage gate the prerequisite for every
    user-visible result. It then optimized raw downloads and annotations instead
    of the actual eligibility predicate, continued low-yield acquisition despite
    429/500 responses ... and had no time budget or stop criterion."

The pool at that checkpoint read: 137 linked, 110 screened in, 42 annotated —
but only **11** strict-coverage eligible. The run looked productive on every
number it could see, because the number that mattered was not exposed.

RH already has `auto_runner.budget.BudgetMonitor`, but it is evaluated BETWEEN
stages and defaults to `max_wall_time_min = 480`, so a run can spend eight hours
inside a single acquisition loop untouched. This monitor is the missing
criterion, expressed in the quantity that decides the gate: papers that become
STRICT-COVERAGE ELIGIBLE, not papers fetched.

Deliberately advisory. It reports `should_stop` with a reason and never aborts
anything itself; wiring a hard abort is a separate, gated change. An advisory
signal that is visible beats a hard stop that nobody trusts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from research_harness.config import state_path

ACQUISITION_YIELD_SCHEMA = "rh.schema.report.acquisition_yield.v1"
COVERAGE_SNAPSHOT_SCHEMA = "rh.schema.event.coverage_snapshot.v1"

#: Default ledger location. Append-only JSONL, same substrate as the context
#: telemetry sink and the replayable-events model the authority docs require.
DEFAULT_LEDGER = state_path("coverage_yield.jsonl")


@dataclass(frozen=True)
class YieldDecision:
    """Outcome of recording one acquisition batch."""

    should_stop: bool
    reason: str = ""
    detail: str = ""


@dataclass
class AcquisitionYieldMonitor:
    """Track eligible-paper yield across acquisition batches.

    Args:
        min_eligible_gain: a batch is "productive" when it adds at least this
            many strict-coverage-eligible papers. Fetch counts are ignored on
            purpose — fetching more was exactly the wrong optimisation target.
        patience: stop after this many consecutive unproductive batches.
        max_consecutive_errors: stop after this many consecutive batches that
            were dominated by transport errors (the 429/500 case).
        max_batches: hard cap on batches for one lane; 0 disables.
    """

    min_eligible_gain: int = 2
    patience: int = 3
    max_consecutive_errors: int = 3
    max_batches: int = 0

    batches: int = 0
    fetched_total: int = 0
    eligible_gain_total: int = 0
    error_total: int = 0
    _low_yield_streak: int = 0
    _error_streak: int = 0
    _stopped: YieldDecision | None = field(default=None, repr=False)

    def record_batch(
        self,
        *,
        fetched: int,
        eligible_gain: int,
        errors: int = 0,
    ) -> YieldDecision:
        """Record one acquisition batch and return the stop decision.

        `eligible_gain` is the increase in strict-coverage-eligible papers, not
        the number downloaded, linked, or annotated. That distinction is the
        whole point: on 2026-08-08, 137 linked papers yielded 11 eligible ones.
        """
        self.batches += 1
        self.fetched_total += max(0, int(fetched))
        self.eligible_gain_total += max(0, int(eligible_gain))
        self.error_total += max(0, int(errors))

        productive = int(eligible_gain) >= self.min_eligible_gain
        self._low_yield_streak = 0 if productive else self._low_yield_streak + 1

        error_dominated = int(errors) > 0 and int(fetched) <= 0
        self._error_streak = self._error_streak + 1 if error_dominated else 0

        decision = self._evaluate()
        if decision.should_stop and self._stopped is None:
            self._stopped = decision
        return decision

    def _evaluate(self) -> YieldDecision:
        if self._error_streak >= self.max_consecutive_errors:
            return YieldDecision(
                should_stop=True,
                reason="repeated_transport_errors",
                detail=(
                    f"{self._error_streak} consecutive batches returned only "
                    f"transport errors; the source is not answering"
                ),
            )
        if self._low_yield_streak >= self.patience:
            return YieldDecision(
                should_stop=True,
                reason="low_eligible_yield",
                detail=(
                    f"{self._low_yield_streak} consecutive batches added fewer "
                    f"than {self.min_eligible_gain} strict-coverage-eligible "
                    f"papers; fetching more is not closing the gate"
                ),
            )
        if self.max_batches and self.batches >= self.max_batches:
            return YieldDecision(
                should_stop=True,
                reason="batch_cap_reached",
                detail=f"reached the configured cap of {self.max_batches} batches",
            )
        return YieldDecision(should_stop=False)

    def snapshot(self) -> dict[str, Any]:
        """Report the state an operator needs to judge whether to continue."""
        decision = self._stopped or self._evaluate()
        return {
            "schema": ACQUISITION_YIELD_SCHEMA,
            "batches": self.batches,
            "fetched_total": self.fetched_total,
            "eligible_gain_total": self.eligible_gain_total,
            "error_total": self.error_total,
            # The headline diagnostic: how many fetches buy one eligible paper.
            "fetched_per_eligible": (
                round(self.fetched_total / self.eligible_gain_total, 2)
                if self.eligible_gain_total
                else None
            ),
            "low_yield_streak": self._low_yield_streak,
            "error_streak": self._error_streak,
            "should_stop": decision.should_stop,
            "stop_reason": decision.reason,
            "stop_detail": decision.detail,
            "limits": {
                "min_eligible_gain": self.min_eligible_gain,
                "patience": self.patience,
                "max_consecutive_errors": self.max_consecutive_errors,
                "max_batches": self.max_batches,
            },
        }


# -- Persistent ledger: yield across runner iterations -------------------------
#
# Acquisition is not a single loop in RH — batching emerges from an agent
# calling tools across runner iterations. So the criterion cannot live inside
# one loop; it has to read a series. This ledger records the eligible count each
# time the coverage audit runs, and the trend is computed from consecutive
# snapshots. Append-only, so history is never rewritten.


def record_coverage_snapshot(
    *,
    topic_id: int,
    eligible: int,
    linked: int,
    ledger_path: str | Path | None = None,
) -> None:
    """Append one coverage observation. Never raises into a caller."""
    try:
        path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER
        event = {
            "schema": COVERAGE_SNAPSHOT_SCHEMA,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "topic_id": int(topic_id),
            "eligible": int(eligible),
            "linked": int(linked),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - a ledger write must not break a run
        return


def _read_snapshots(topic_id: int, path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if int(event.get("topic_id") or -1) == int(topic_id):
            out.append(event)
    return out


def yield_trend(
    topic_id: int,
    *,
    ledger_path: str | Path | None = None,
    min_eligible_gain: int = 2,
    patience: int = 3,
) -> dict[str, Any]:
    """Assess acquisition yield for one topic from its recorded snapshots.

    A single snapshot is not a trend and can never trigger a stop — concluding
    from one observation is exactly the error that produces premature stops and
    destroys trust in the signal.
    """
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER
    snapshots = _read_snapshots(topic_id, path)

    monitor = AcquisitionYieldMonitor(
        min_eligible_gain=min_eligible_gain, patience=patience
    )
    for previous, current in zip(snapshots, snapshots[1:]):
        monitor.record_batch(
            fetched=max(
                0, int(current.get("linked") or 0) - int(previous.get("linked") or 0)
            ),
            eligible_gain=max(
                0,
                int(current.get("eligible") or 0) - int(previous.get("eligible") or 0),
            ),
        )

    snap = monitor.snapshot()
    return {
        "schema": ACQUISITION_YIELD_SCHEMA,
        "topic_id": int(topic_id),
        "snapshots": len(snapshots),
        "eligible_latest": int(snapshots[-1].get("eligible") or 0) if snapshots else 0,
        "linked_latest": int(snapshots[-1].get("linked") or 0) if snapshots else 0,
        "intervals_assessed": snap["batches"],
        "fetched_per_eligible": snap["fetched_per_eligible"],
        "should_stop": snap["should_stop"],
        "stop_reason": snap["stop_reason"],
        "stop_detail": snap["stop_detail"],
    }
