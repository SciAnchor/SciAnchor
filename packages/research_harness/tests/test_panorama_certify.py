"""Tests for the project-certification gate.

The gate produces two artifacts: a candidate-scoped novelty verdict and a
separate promotion decision. The legacy ``decision`` property is retained and
derived, so the historical scenarios below still assert on it.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from research_harness.cli import main
from research_harness.panorama.certify import (
    FieldLevelClaimError,
    NoveltyVerdict,
    ReviewerScore,
    assert_no_field_level_claim,
    evaluate_certification,
    find_field_level_claims,
    parse_panel,
)


def _full_panel(overall: float, verdict: str = "commit") -> list[ReviewerScore]:
    return [
        ReviewerScore(axis=a, overall=overall, verdict=verdict)
        for a in ("novelty", "methodology", "significance", "rigor")
    ]


def test_go_when_all_axes_clear():
    d = evaluate_certification(auto_verdict="open", reviewers=_full_panel(7))
    assert d.decision == "go"
    assert d.panel_mean == 7.0


def test_occupied_auto_verdict_alone_does_not_refute_a_candidate():
    """A retrieval verdict describes query-family coverage, not project value.

    Previously `occupied` alone produced a hard NO-GO documented as "stop and
    switch direction", which is how a gap-level retrieval miss became a
    direction-level conclusion. It now leaves the candidate unclear and
    incubating until a reviewer corroborates it.
    """
    d = evaluate_certification(auto_verdict="occupied", reviewers=_full_panel(8))
    assert d.novelty.verdict == "unclear"
    assert d.promotion.decision == "incubate"
    assert d.decision == "no-go"  # legacy view still says "not now"
    assert any("query-family coverage" in r for r in d.reasons)


def test_occupied_plus_blocking_novelty_review_does_refute():
    reviewers = _full_panel(8)
    reviewers[0] = ReviewerScore(axis="novelty", overall=3, verdict="no-commit")
    d = evaluate_certification(auto_verdict="occupied", reviewers=reviewers)
    assert d.novelty.verdict == "refuted"
    assert d.promotion.decision == "stop"


def test_no_go_on_low_reviewer():
    reviewers = _full_panel(7)
    reviewers[0] = ReviewerScore(axis="novelty", overall=4, verdict="no-commit")
    d = evaluate_certification(auto_verdict="partially_occupied", reviewers=reviewers)
    assert d.decision == "no-go"
    assert any("novelty" in r for r in d.reasons)


def test_no_go_on_panel_mean_below_iclr_bar():
    # All reviewers at 5: above per-reviewer floor but mean 5 < 6 main bar.
    d = evaluate_certification(auto_verdict="open", reviewers=_full_panel(5))
    assert d.decision == "no-go"
    assert any("panel mean" in r for r in d.reasons)


def test_no_go_on_preemptor_found():
    d = evaluate_certification(
        auto_verdict="partially_occupied",
        reviewers=_full_panel(7),
        preemptors=["When Stability Fails (ICLR-2026 workshop)"],
    )
    assert d.decision == "no-go"
    assert any("pre-emptor" in r for r in d.reasons)


def test_no_go_on_incomplete_panel():
    d = evaluate_certification(
        auto_verdict="open",
        reviewers=[ReviewerScore(axis="novelty", overall=8)],
    )
    assert d.decision == "no-go"
    assert any("incomplete" in r for r in d.reasons)


def test_c2_scenario_reproduces_no_go():
    """The real C2 panel (3-4/10, direct pre-emptors) must be NO-GO."""
    reviewers = [
        ReviewerScore("novelty", 4, "no-commit"),
        ReviewerScore("methodology", 4, "no-commit"),
        ReviewerScore("significance", 3, "no-commit"),
        ReviewerScore("rigor", 4, "no-commit"),
    ]
    d = evaluate_certification(
        auto_verdict="partially_occupied",
        reviewers=reviewers,
        preemptors=[
            "When Agents Disagree 2602.11619",
            "When Stability Fails 2603.15840",
        ],
    )
    assert d.decision == "no-go"


def test_parse_panel_roundtrip():
    payload = {
        "auto_verdict": "partially_occupied",
        "reviewers": [
            {"axis": "novelty", "overall": 4, "verdict": "no-commit"},
            {"axis": "bad", "overall": "not-a-number"},
        ],
        "preemptors": ["X", ""],
    }
    auto, reviewers, preemptors = parse_panel(payload)
    assert auto == "partially_occupied"
    assert len(reviewers) == 1  # the non-numeric one dropped
    assert preemptors == ["X"]


def test_non_novelty_failure_holds_without_touching_the_novelty_verdict():
    """The failure this whole split exists to prevent.

    A methodology problem must not be recorded as "not novel". It produces a
    promotion hold while the novelty verdict stays exactly what the evidence
    supports.
    """
    reviewers = _full_panel(7)
    reviewers[1] = ReviewerScore(axis="methodology", overall=3, verdict="no-commit")

    d = evaluate_certification(auto_verdict="open", reviewers=reviewers)

    assert d.novelty.verdict == "not_refuted_by_retrieved_evidence"
    assert d.promotion.decision == "hold"
    assert d.promotion.blocking_axes == ["methodology"]
    assert any("novelty verdict is unchanged" in r for r in d.promotion.reasons)


def test_uncorroborated_preemptor_leaves_the_candidate_unclear():
    d = evaluate_certification(
        auto_verdict="open",
        reviewers=_full_panel(7),
        preemptors=["Some Adjacent Paper 2601.00001"],
    )
    assert d.novelty.verdict == "unclear"
    assert d.promotion.decision == "incubate"
    assert "pre-emptor found without corroborating reviewer judgement" in (
        d.novelty.coverage_warnings
    )


def test_inconclusive_retrieval_yields_unclear_not_a_positive_finding():
    d = evaluate_certification(auto_verdict="inconclusive", reviewers=_full_panel(8))
    assert d.novelty.verdict == "unclear"
    assert d.novelty.coverage_sufficient is False


def test_unrecognised_auto_verdict_fails_closed():
    """Upstream contract drift must not read as adequate coverage."""
    d = evaluate_certification(auto_verdict="mostly_fine", reviewers=_full_panel(8))
    assert d.novelty.verdict == "unclear"
    assert d.novelty.coverage_sufficient is False
    assert any("unrecognised" in w for w in d.novelty.coverage_warnings)


def test_missing_novelty_axis_cannot_produce_a_novelty_finding():
    d = evaluate_certification(
        auto_verdict="open",
        reviewers=[ReviewerScore(axis=a, overall=8) for a in ("methodology", "rigor")],
    )
    assert d.novelty.verdict == "unclear"
    assert "no novelty-axis reviewer in the panel" in d.novelty.coverage_warnings


def test_positive_novelty_finding_requires_sufficient_coverage():
    with pytest.raises(ValueError, match="requires sufficient coverage"):
        NoveltyVerdict(
            verdict="not_refuted_by_retrieved_evidence", coverage_sufficient=False
        )


@pytest.mark.parametrize(
    "verdict", ["red_ocean", "ceiling", "exhausted_field", "saturated"]
)
def test_novelty_verdict_schema_has_no_field_level_state(verdict: str):
    with pytest.raises(ValueError, match="novelty verdict must be one of"):
        NoveltyVerdict(verdict=verdict, coverage_sufficient=True)


def test_novelty_verdict_scope_cannot_widen_beyond_a_candidate_version():
    with pytest.raises(ValueError, match="scope must be"):
        NoveltyVerdict(
            verdict="unclear", coverage_sufficient=False, scope_kind="domain"
        )


def test_target_is_actually_read_and_not_decorative():
    """`--target` used to be accepted, echoed, and never consulted."""
    reviewers = _full_panel(5)  # mean 5.0

    main_track = evaluate_certification(
        auto_verdict="open", reviewers=reviewers, target="iclr-main"
    )
    workshop = evaluate_certification(
        auto_verdict="open", reviewers=reviewers, target="workshop"
    )

    assert main_track.promotion.decision == "hold"
    assert workshop.promotion.decision == "advance"
    assert workshop.decision == "go"


def test_unknown_target_falls_back_to_the_strictest_bar_and_says_so():
    d = evaluate_certification(
        auto_verdict="open", reviewers=_full_panel(5), target="some-venue"
    )
    assert d.promotion.decision == "hold"
    assert any("unknown venue target" in r for r in d.promotion.reasons)


def test_natural_language_targets_resolve_to_the_right_bar():
    """Live defect (F1 v1 certification, 2026-08-10): --target 'ICLR main
    track' fell into the unknown-venue fallback. Harmless there (fallback
    == iclr-main bar) but 'ICLR workshop' would be graded at the strictest
    bar instead of the workshop bar — a natural phrasing must never make
    the gate STRICTER than the venue the user named."""
    reviewers = _full_panel(5)  # mean 5.0: passes workshop bar, fails main

    workshop = evaluate_certification(
        auto_verdict="open", reviewers=reviewers, target="ICLR workshop"
    )
    assert workshop.promotion.decision == "advance"
    assert not any("unknown venue target" in r for r in workshop.promotion.reasons)

    main = evaluate_certification(
        auto_verdict="open", reviewers=reviewers, target="ICLR main track"
    )
    assert main.promotion.decision == "hold"
    assert not any("unknown venue target" in r for r in main.promotion.reasons)

    neurips = evaluate_certification(
        auto_verdict="open", reviewers=reviewers, target="NeurIPS 2027"
    )
    assert neurips.promotion.decision == "hold"
    assert not any("unknown venue target" in r for r in neurips.promotion.reasons)


@pytest.mark.parametrize(
    "text",
    [
        "the panorama campaign already found automated-research saturated",
        "E1's ceiling is a genuine limit for this research area",
        "all directions occupied in this field",
        "该领域已经饱和",
        "这个方向空间没有创新空间",
    ],
)
def test_field_level_exhaustion_claims_are_detected(text: str):
    assert find_field_level_claims(text)
    with pytest.raises(FieldLevelClaimError):
        assert_no_field_level_claim(text)


@pytest.mark.parametrize(
    "text",
    [
        "candidate v3 is refuted by 2 direct pre-emptors as of 2026-08-04",
        "query family 'silent error detection' returned no new results; lane stopped",
        "competition density for this task cluster is 0.81 as of the 2026-07 snapshot",
        "panel mean 5.0 < iclr-main bar 6.0",
        "held for non-novelty reasons; the novelty verdict is unchanged",
        # An exhaustion term IS allowed when it carries an explicit scope.
        "query family 'silent error detection' is exhausted as of the 2026-08-04 snapshot",
        "this candidate cluster is red-ocean under the current retrieval budget",
    ],
)
def test_legitimate_scoped_negative_statements_are_not_rejected(text: str):
    """Rejecting every negative statement would fake safety."""
    assert find_field_level_claims(text) == []
    assert_no_field_level_claim(text)


def test_certification_reasons_can_never_carry_a_field_level_claim():
    d = evaluate_certification(
        auto_verdict="occupied",
        reviewers=_full_panel(3, verdict="no-commit"),
        preemptors=["A", "B", "C"],
    )
    assert d.promotion.decision == "stop"
    for reason in d.reasons:
        assert_no_field_level_claim(reason)


def test_cli_certify_records_verdict(tmp_path):
    runner = CliRunner()
    root = tmp_path / "panorama"
    runner.invoke(
        main, ["panorama", "init", "d", "--rh-domain-id", "1", "--root", str(root)]
    )
    panel = {
        "auto_verdict": "partially_occupied",
        "reviewers": [
            {"axis": "novelty", "overall": 4, "verdict": "no-commit"},
            {"axis": "methodology", "overall": 4},
            {"axis": "significance", "overall": 3},
            {"axis": "rigor", "overall": 4},
        ],
        "preemptors": ["When Stability Fails 2603.15840"],
    }
    result = runner.invoke(
        main,
        [
            "panorama",
            "certify",
            "d",
            "--claim",
            "C2 stability bench",
            "--panel-json",
            json.dumps(panel),
            "--root",
            str(root),
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"decision": "no-go"' in result.output


def _coverage(computable: bool, stop: bool, unseen: float = 0.4) -> dict:
    return {
        "computable": computable,
        "stop_reached": stop,
        "unseen_fraction": unseen,
        "marginal_rate": 0.10,
    }


def test_quantitative_coverage_below_stopping_bar_forces_unclear():
    """Chao2 says the neighbourhood is mostly unseen: one query family's
    'open' cannot establish coverage, whatever the panel thinks."""
    d = evaluate_certification(
        auto_verdict="open",
        reviewers=_full_panel(8),
        coverage=_coverage(computable=True, stop=False),
    )
    assert d.novelty.verdict == "unclear"
    assert d.novelty.coverage_sufficient is False
    assert any("below the stopping bar" in w for w in d.novelty.coverage_warnings)


def test_quantitative_stop_reached_backs_the_positive_finding():
    d = evaluate_certification(
        auto_verdict="open",
        reviewers=_full_panel(8),
        coverage=_coverage(computable=True, stop=True, unseen=0.05),
    )
    assert d.novelty.verdict == "not_refuted_by_retrieved_evidence"
    assert any("stopping bar reached" in b for b in d.novelty.basis)


def test_uncomputable_coverage_falls_back_to_categorical_check():
    with_cov = evaluate_certification(
        auto_verdict="open",
        reviewers=_full_panel(8),
        coverage=_coverage(computable=False, stop=False),
    )
    without_cov = evaluate_certification(auto_verdict="open", reviewers=_full_panel(8))
    assert with_cov.novelty.verdict == without_cov.novelty.verdict
    assert any("coverage unquantified" in w for w in with_cov.novelty.coverage_warnings)


def test_quantitative_gate_cannot_rescue_inconclusive_retrieval():
    """stop_reached with an inconclusive auto verdict must stay unclear:
    the quantitative signal bounds what retrieval missed, it does not
    substitute for retrieval having said something."""
    d = evaluate_certification(
        auto_verdict="inconclusive",
        reviewers=_full_panel(8),
        coverage=_coverage(computable=True, stop=True, unseen=0.02),
    )
    assert d.novelty.verdict == "unclear"


def test_source_failures_force_unclear_even_when_stop_reached():
    """E1: silent source failure must never look like adequate coverage."""
    cov = _coverage(computable=True, stop=True, unseen=0.02)
    cov["sources_failed"] = ["openalex", "s2"]
    d = evaluate_certification(
        auto_verdict="open",
        reviewers=_full_panel(8),
        coverage=cov,
    )
    assert d.novelty.verdict == "unclear"
    assert d.novelty.coverage_sufficient is False
    assert any("source-level harvest failure" in w for w in d.novelty.coverage_warnings)


def test_venue_bar_journal_tiers():
    """Journal targets resolve to selectivity-tier bars, not the strictest
    CS-conference bar (found live: SR/HSSC/npj all fell to 5/6.0)."""
    from research_harness.panorama.certify import VENUE_BARS, _venue_bar

    bar, warnings = _venue_bar("Scientific Reports")
    assert bar == VENUE_BARS["journal-sound-science"] and not warnings
    bar, warnings = _venue_bar("Humanities and Social Sciences Communications")
    assert bar == VENUE_BARS["journal-selective"] and not warnings
    bar, warnings = _venue_bar("npj Digital Medicine")
    assert bar == VENUE_BARS["journal-flagship"] and not warnings
    bar, warnings = _venue_bar("Nature Communications")
    assert bar == VENUE_BARS["journal-flagship"] and not warnings
    # Unknown targets still fail strict, loudly.
    bar, warnings = _venue_bar("Some Obscure Venue")
    assert bar == (5, 6.0) and warnings
