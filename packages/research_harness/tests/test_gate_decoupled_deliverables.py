"""Tests for gate-decoupled deliverable reporting (P-1, second half).

Motivating incident (topic 73 / run 32, 2026-08-08). The strict-coverage gate
was treated as the prerequisite for every user-visible result. The postmortem
is explicit that this was a sequencing error, not a gate error:

    "The strict gate is real and must pass before final external
    release. It is NOT a valid reason to withhold the already-feasible EAG
    skeleton, move maps, study contract, and figure/table contract."

Design choice: do NOT weaken the gate and do NOT move tools between stages.
Instead make the gate state which deliverables it does and does not block, so
an operator (or agent) reading `needs_coverage` can see immediately that useful
work remains available. A gate that only says "blocked" invites the reader to
stop everything.
"""

from __future__ import annotations

from research_harness.paper_pool_audit import (
    GATE_DECOUPLED_DELIVERABLES,
    decoupled_deliverable_status,
)


def test_catalog_names_the_postmortem_deliverables() -> None:
    names = {d["deliverable"] for d in GATE_DECOUPLED_DELIVERABLES}
    assert {
        "eag_exemplar_skeleton",
        "paragraph_move_map",
        "study_contract",
        "figure_table_contract",
    } <= names


def test_every_catalog_entry_declares_its_own_precondition() -> None:
    """A deliverable that claims to be gate-independent must still say what it
    genuinely needs — otherwise it is just a promise."""
    for entry in GATE_DECOUPLED_DELIVERABLES:
        assert entry["requires"], entry["deliverable"]
        assert entry["blocked_by_coverage"] is False


def test_deliverables_are_feasible_when_their_own_inputs_exist() -> None:
    status = decoupled_deliverable_status(
        available_artifacts={
            "topic_brief",
            "topic_venue_contract",
            "PAPER_PROFILE",
            "DOMAIN_WRITING_PROFILE",
        },
        exemplar_candidate_count=3,
    )
    feasible = {d["deliverable"] for d in status["feasible_now"]}
    assert "eag_exemplar_skeleton" in feasible
    assert "study_contract" in feasible
    assert status["blocked_by_coverage"] == []


def test_missing_own_input_blocks_only_that_deliverable() -> None:
    status = decoupled_deliverable_status(
        available_artifacts={"topic_brief"},
        exemplar_candidate_count=0,
    )
    blocked = {d["deliverable"]: d for d in status["not_yet_feasible"]}
    assert "eag_exemplar_skeleton" in blocked
    # And the reason must name the real missing input, not "coverage".
    assert "coverage" not in " ".join(blocked["eag_exemplar_skeleton"]["missing"])


def test_coverage_shortfall_never_appears_as_a_blocker() -> None:
    """The whole point: a coverage shortfall must not suppress these."""
    status = decoupled_deliverable_status(
        available_artifacts={
            "topic_brief",
            "topic_venue_contract",
            "PAPER_PROFILE",
            "DOMAIN_WRITING_PROFILE",
        },
        exemplar_candidate_count=3,
        coverage_eligible=11,
        min_coverage_eligible=50,
    )
    assert status["coverage_shortfall"] == 39
    assert status["blocked_by_coverage"] == []
    assert len(status["feasible_now"]) >= 3


def test_status_carries_an_explicit_operator_instruction() -> None:
    """Reading `needs_coverage` must not read as 'stop everything'."""
    status = decoupled_deliverable_status(
        available_artifacts={"topic_brief", "topic_venue_contract"},
        exemplar_candidate_count=3,
        coverage_eligible=11,
        min_coverage_eligible=50,
    )
    assert "coverage" in status["guidance"].lower()
    assert status["feasible_now"], "at least one deliverable should be available"


def test_empty_state_does_not_raise() -> None:
    status = decoupled_deliverable_status(
        available_artifacts=set(), exemplar_candidate_count=0
    )
    assert status["feasible_now"] == []
    assert len(status["not_yet_feasible"]) == len(GATE_DECOUPLED_DELIVERABLES)


# -- Yield trend must reach the gate report -----------------------------------


def test_gate_details_carry_the_acquisition_yield_trend(tmp_path, monkeypatch) -> None:
    """The gate is where an operator decides whether to keep acquiring, so the
    'is fetching still buying eligible papers?' answer belongs there."""
    from research_harness.acquisition import yield_monitor
    from research_harness.paper_pool_audit import build_coverage_gate_details

    ledger = tmp_path / "yield.jsonl"
    monkeypatch.setattr(yield_monitor, "DEFAULT_LEDGER", ledger)
    for eligible, linked in ((11, 137), (11, 170), (12, 205), (12, 240)):
        yield_monitor.record_coverage_snapshot(
            topic_id=73, eligible=eligible, linked=linked, ledger_path=ledger
        )

    details = build_coverage_gate_details(
        audit={
            "topic_id": 73,
            "counts": {"coverage_eligible": 12, "total_linked": 240},
        },
        min_coverage_eligible=50,
        min_year_span=5,
    )

    trend = details["acquisition_yield"]
    assert trend["snapshots"] == 4
    assert trend["should_stop"] is True
    assert trend["stop_reason"] == "low_eligible_yield"
    # And the recovery advice must reflect it rather than saying "acquire more".
    assert any(
        "yield" in a.lower() or "repair" in a.lower()
        for a in details["recovery_actions"]
    )


def test_gate_details_without_ledger_history_do_not_claim_a_trend(
    tmp_path, monkeypatch
) -> None:
    from research_harness.acquisition import yield_monitor
    from research_harness.paper_pool_audit import build_coverage_gate_details

    monkeypatch.setattr(yield_monitor, "DEFAULT_LEDGER", tmp_path / "absent.jsonl")
    details = build_coverage_gate_details(
        audit={"topic_id": 73, "counts": {"coverage_eligible": 11}},
        min_coverage_eligible=50,
        min_year_span=5,
    )
    assert details["acquisition_yield"]["snapshots"] == 0
    assert details["acquisition_yield"]["should_stop"] is False
