from __future__ import annotations

from research_harness._selfdev.conflict_review_queue import (
    project_conflict_review_queue,
)
from research_harness._selfdev.rh_spc_dry_run_reconciliation import (
    ReconciliationObservation,
    reconcile_observations,
)


def _obs(key: str, **overrides: object) -> ReconciliationObservation:
    values = {
        "source": "rh",
        "source_key": key,
        "title": "A study of forecasting",
        "year": 2024,
        "doi": None,
        "arxiv_id": None,
        "content_hash": None,
    }
    values.update(overrides)
    return ReconciliationObservation(**values)


def test_empty_and_all_same_yield_empty_queue() -> None:
    empty = project_conflict_review_queue(reconcile_observations((), ()))
    assert empty.rows == ()
    assert empty.counts == {}
    assert empty.persistent_write is False
    digest_empty = empty.stable_sha256

    same = project_conflict_review_queue(
        reconcile_observations(
            (_obs("rh:1", doi="10.1000/abc"),),
            (_obs("spc:1", source="spc", doi="10.1000/abc"),),
        )
    )
    assert same.rows == ()
    assert same.stable_sha256 == digest_empty


def test_conflict_expands_one_row_per_side_with_reasons() -> None:
    report = reconcile_observations(
        (_obs("rh:1", doi="10.1000/abc"),),
        (
            _obs(
                "spc:1",
                source="spc",
                doi="10.1000/abc",
                title="A contradictory title",
            ),
        ),
    )
    queue = project_conflict_review_queue(report)
    assert [row.source_key for row in queue.rows] == ["rh:1", "spc:1"]
    assert all(row.review_kind == "conflict" for row in queue.rows)
    assert "title_conflict" in queue.rows[0].reasons
    assert "doi_exact" in queue.rows[0].reasons
    assert queue.rows[0].paired_keys == ("spc:1",)
    assert queue.rows[1].paired_keys == ("rh:1",)
    assert queue.counts == {"conflict": 2}


def test_manual_review_unmatched_sides_each_get_a_row() -> None:
    report = reconcile_observations(
        (_obs("rh:lone", title="only rh", year=2020),),
        (_obs("spc:lone", source="spc", title="only spc", year=2021),),
    )
    queue = project_conflict_review_queue(report)
    keys = {row.source_key for row in queue.rows}
    assert keys == {"rh:lone", "spc:lone"}
    assert all(row.review_kind == "manual_review" for row in queue.rows)
    reasons = {row.source_key: row.reasons for row in queue.rows}
    assert "unmatched" in reasons["rh:lone"]
    assert "unmatched_right" in reasons["spc:lone"]


def test_key_merge_prefers_conflict_over_manual_review() -> None:
    # spc:shared matches rh:1 by DOI with title conflict, and is also the only
    # title-year peer for a second RH row that would otherwise be related —
    # force a second manual_review path via ambiguous title-year on another pair
    # that still names spc:shared through a crafted multi-match.
    report = reconcile_observations(
        (
            _obs("rh:1", doi="10.1000/abc", title="Left title"),
            _obs("rh:2", doi="10.1000/abc", title="Other left"),
        ),
        (
            _obs(
                "spc:shared",
                source="spc",
                doi="10.1000/abc",
                title="Right title",
            ),
        ),
    )
    # Both lefts strong-match the same SPC → each outcome is conflict or
    # manual_review with ambiguous_strong; either way spc:shared participates.
    queue = project_conflict_review_queue(report)
    by_key = {row.source_key: row for row in queue.rows}
    assert set(by_key) == {"rh:1", "rh:2", "spc:shared"}
    assert by_key["spc:shared"].review_kind == "conflict"
    assert set(by_key["spc:shared"].paired_keys) == {"rh:1", "rh:2"}
    # Exactly one row per source key.
    assert len(queue.rows) == 3


def test_ordering_and_digest_are_deterministic() -> None:
    report = reconcile_observations(
        (
            _obs("rh:z", doi="10.1000/z", title="Z"),
            _obs("rh:a", title="orphan", year=2019),
        ),
        (
            _obs(
                "spc:z",
                source="spc",
                doi="10.1000/z",
                title="Not Z",
            ),
            _obs("spc:b", source="spc", title="spc only", year=2018),
        ),
    )
    q1 = project_conflict_review_queue(report)
    q2 = project_conflict_review_queue(report)
    assert [row.source_key for row in q1.rows] == [row.source_key for row in q2.rows]
    assert q1.stable_sha256 == q2.stable_sha256
    kinds = [row.review_kind for row in q1.rows]
    # all conflicts before any manual_review
    if "conflict" in kinds and "manual_review" in kinds:
        assert kinds.index("conflict") < kinds.index("manual_review")
    portable = q1.to_portable()
    assert portable["persistent_write"] is False
    assert "rows" in portable


def test_every_conflict_or_manual_participant_appears_once() -> None:
    report = reconcile_observations(
        (
            _obs("rh:1", doi="10.1000/abc"),
            _obs("rh:2", title="gone", year=2020),
        ),
        (
            _obs(
                "spc:1",
                source="spc",
                doi="10.1000/abc",
                title="Different",
            ),
            _obs("spc:2", source="spc", doi="10.1000/abc", title="Also different"),
            _obs("spc:3", source="spc", title="right only", year=2021),
        ),
    )
    participants: set[str] = set()
    for outcome in report.outcomes:
        if outcome.relation not in {"conflict", "manual_review"}:
            continue
        if outcome.left_key:
            participants.add(outcome.left_key)
        participants.update(outcome.right_keys)
    queue = project_conflict_review_queue(report)
    keys = [row.source_key for row in queue.rows]
    assert len(keys) == len(set(keys))
    assert set(keys) == participants
