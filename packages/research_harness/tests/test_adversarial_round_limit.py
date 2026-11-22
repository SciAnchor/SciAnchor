"""Regression: adversarial loop contract v2 must make every exit reachable.

Topic 78 (2026-08-08/09) ran 30 rounds against a 3-round budget with zero
proposer responses and a mean score pinned at 1.43-1.71. Four defects, four
tests: the max-rounds guard counted only `active` round artifacts (always 1);
no response channel meant every round was an independent sample; `critical>0`
unconditionally outranked the low-score exit; recurring objections could not
be recognized across rounds.
"""

from __future__ import annotations

import pytest

from research_harness._workflow.orchestrator.adversarial import (
    AdversarialLoop,
    Objection,
    compute_objection_id,
)
from research_harness.storage.db import Database


@pytest.fixture
def loop(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        conn.commit()
    return AdversarialLoop(db)


def _objection(n: int, category: str = "senior_reviewer:method_validity") -> Objection:
    return Objection(
        category=category,
        severity="critical",
        target=f"claim {n}",
        reasoning="unsupported",
    )


def _responses_for(objections: list[Objection]) -> list[dict]:
    return [
        {"objection_id": o.objection_id, "resolved": False, "note": "acknowledged"}
        for o in objections
    ]


def _run_and_resolve(
    loop: AdversarialLoop,
    n: int,
    objections: list[Objection],
    responses: list[dict] | None = None,
    scores: dict[str, float] | None = None,
) -> dict:
    round_result = loop.run_round(
        topic_id=1,
        target_artifact_id=1,
        target_stage="write",
        round_number=n,
        proposal_snapshot={},
        objections=objections,
        proposer_responses=responses,
    )
    return loop.resolve_round(
        topic_id=1,
        target_stage="write",
        round_number=n,
        round_artifact_id=round_result["artifact_id"],
        scores=scores or {"method_validity": 1.0},
    )


def test_max_rounds_guard_fires_after_superseded_rounds(loop):
    max_rounds = loop.get_max_rounds("standard")
    # A fresh objection each round and a mean above the stagnation threshold,
    # so max-rounds is the exit under test (not stagnation / key saturation).
    for n in range(1, max_rounds + 1):
        objs = [_objection(n)]
        _run_and_resolve(
            loop,
            n,
            objs,
            responses=_responses_for([_objection(n - 1)]) if n > 1 else None,
            scores={"method_validity": 3.5},
        )
        assert loop._count_rounds(1, "write") == n

    repeat, reason = loop.should_repeat(
        topic_id=1, target_stage="write", mode="standard"
    )
    assert repeat is False
    assert f"Max rounds ({max_rounds})" in reason


def test_round_without_responses_after_unresolved_objections_is_rejected(loop):
    objs = [_objection(1)]
    _run_and_resolve(loop, 1, objs)

    with pytest.raises(ValueError, match="proposer_responses"):
        loop.run_round(
            topic_id=1,
            target_artifact_id=1,
            target_stage="write",
            round_number=2,
            proposal_snapshot={},
            objections=objs,
        )

    # With responses the same round records fine.
    result = loop.run_round(
        topic_id=1,
        target_artifact_id=1,
        target_stage="write",
        round_number=2,
        proposal_snapshot={},
        objections=objs,
        proposer_responses=_responses_for(objs),
    )
    assert result["round"]["targets_addressed"] == [objs[0].objection_id]


def test_objection_id_is_content_stable_and_resolves_by_id(loop):
    a = _objection(1)
    b = _objection(1)  # same complaint, new round instance
    assert a.objection_id == b.objection_id
    assert a.objection_id == compute_objection_id(a.category, a.severity, a.target)

    unresolved = loop._compute_unresolved(
        [b], [{"objection_id": a.objection_id, "resolved": True}]
    )
    assert unresolved == []


def test_two_consecutive_sub3_means_reject_even_with_critical(loop):
    objs = [_objection(1)]
    r1 = _run_and_resolve(loop, 1, objs, scores={"method_validity": 1.5})
    assert r1["resolution"]["outcome"] == "revise_and_repeat"  # first low round revises

    r2 = _run_and_resolve(
        loop, 2, objs, responses=_responses_for(objs), scores={"method_validity": 1.5}
    )
    # critical unresolved > 0, but stagnation outranks it now
    assert r2["resolution"]["critical_unresolved"] > 0
    assert r2["resolution"]["outcome"] == "reject_and_return"

    repeat, _ = loop.should_repeat(topic_id=1, target_stage="write", mode="strict")
    assert repeat is False


def test_no_new_objection_keys_for_two_rounds_stops_repeat(loop):
    objs = [_objection(1), _objection(2)]
    # strict mode allows 5 rounds; identical objections every round
    for n in range(1, 4):
        _run_and_resolve(
            loop,
            n,
            objs,
            responses=_responses_for(objs) if n > 1 else None,
            scores={"method_validity": 3.5},  # above stagnation threshold
        )

    repeat, reason = loop.should_repeat(topic_id=1, target_stage="write", mode="strict")
    assert repeat is False
    assert "No new objection keys" in reason

    # A genuinely new objection in the latest round keeps the loop alive.
    fresh = objs + [_objection(99, category="red_team:falsifiability")]
    _run_and_resolve(loop, 4, fresh, responses=_responses_for(objs))
    repeat, _ = loop.should_repeat(topic_id=1, target_stage="write", mode="strict")
    assert repeat is True
