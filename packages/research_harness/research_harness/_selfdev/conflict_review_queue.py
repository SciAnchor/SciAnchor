"""Private in-memory conflict/manual-review projection over A12 reports.

Noncanonical, no persistent queue, no identity assignment, no writes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from research_harness._selfdev.rh_spc_dry_run_reconciliation import (
    ReconciliationReport,
)

_REVIEW_RELATIONS = frozenset({"conflict", "manual_review"})
_KIND_ORDER = {"conflict": 0, "manual_review": 1}
_SOURCE_ORDER = {"rh": 0, "spc": 1}


@dataclass(frozen=True)
class ConflictReviewRow:
    source_key: str
    source: str
    review_kind: str
    paired_keys: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ConflictReviewQueue:
    rows: tuple[ConflictReviewRow, ...]
    counts: dict[str, int]
    stable_sha256: str
    persistent_write: bool = False

    def to_portable(self) -> dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "stable_sha256": self.stable_sha256,
            "persistent_write": False,
            "rows": [asdict(row) for row in self.rows],
        }


def project_conflict_review_queue(
    report: ReconciliationReport,
) -> ConflictReviewQueue:
    """Project conflict/manual_review outcomes to one row per source key."""

    buckets: dict[str, dict[str, Any]] = {}
    for outcome in report.outcomes:
        if outcome.relation not in _REVIEW_RELATIONS:
            continue
        participants: list[str] = []
        if outcome.left_key:
            participants.append(outcome.left_key)
        participants.extend(outcome.right_keys)
        participant_set = set(participants)
        for key in participant_set:
            bucket = buckets.setdefault(
                key,
                {
                    "source_key": key,
                    "source": _source_of(key),
                    "review_kind": "manual_review",
                    "paired": set(),
                    "reasons": set(),
                },
            )
            if outcome.relation == "conflict":
                bucket["review_kind"] = "conflict"
            bucket["paired"].update(participant_set - {key})
            bucket["reasons"].update(outcome.evidence)

    rows = tuple(
        sorted(
            (
                ConflictReviewRow(
                    source_key=bucket["source_key"],
                    source=bucket["source"],
                    review_kind=bucket["review_kind"],
                    paired_keys=tuple(sorted(bucket["paired"])),
                    reasons=tuple(sorted(bucket["reasons"])),
                )
                for bucket in buckets.values()
            ),
            key=_row_sort_key,
        )
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.review_kind] = counts.get(row.review_kind, 0) + 1
    counts = dict(sorted(counts.items()))
    digest = hashlib.sha256(
        json.dumps(
            [asdict(row) for row in rows], ensure_ascii=True, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    return ConflictReviewQueue(rows=rows, counts=counts, stable_sha256=digest)


def _source_of(source_key: str) -> str:
    if source_key.startswith("rh:"):
        return "rh"
    if source_key.startswith("spc:"):
        return "spc"
    return "unknown"


def _row_sort_key(row: ConflictReviewRow) -> tuple[int, int, str]:
    return (
        _KIND_ORDER.get(row.review_kind, 99),
        _SOURCE_ORDER.get(row.source, 99),
        row.source_key,
    )
