"""Tests for governance_gate primitive (deterministic, no LLM).

The gate operationalizes the r(rho) decision rule: a self-graded positive
verdict is discounted by the generator<->judge contamination correlation and
external anchors are required at a rate that grows with contamination.
"""

from __future__ import annotations

import math

from research_harness.primitives.evolution_impls import governance_gate


def test_self_graded_positive_no_anchor_abstains():
    """Same model produced and judged, zero external anchors -> abstain."""
    out = governance_gate(
        verdict="open",
        judge_confidence=0.9,
        generator_model="gpt-5.5",
        judge_model="gpt-5.5",
        external_anchors=0,
        contamination_rho=0.7,
        alpha=0.1,
    )
    assert out.self_graded is True
    assert out.contamination_regime == "self_graded"
    assert out.action == "abstain_pending_external"
    assert out.meets_error_budget is False
    assert out.required_external_verifications >= 1
    # residual = rho^(0+1) = 0.7 > alpha=0.1
    assert math.isclose(out.residual_contamination_risk, 0.7, abs_tol=1e-6)
    # confidence is discounted, not taken at face value
    assert out.trust_adjusted_confidence < 0.9


def test_enough_external_anchors_accepts():
    """With k anchors s.t. rho^(k+1) <= alpha, the finding is accepted."""
    # rho=0.7, alpha=0.1: need k+1 >= log(0.1)/log(0.7) = 6.46 -> k=6
    out = governance_gate(
        verdict="open",
        judge_confidence=0.9,
        generator_model="gpt-5.5",
        judge_model="gpt-5.5",
        external_anchors=6,
        contamination_rho=0.7,
        alpha=0.1,
    )
    assert out.action == "accept"
    assert out.meets_error_budget is True
    assert out.required_external_verifications == 0
    assert out.residual_contamination_risk <= 0.1


def test_partial_anchors_requires_more():
    out = governance_gate(
        verdict="open",
        judge_confidence=0.8,
        generator_model="gpt-5.5",
        judge_model="gpt-5.5",
        external_anchors=2,
        contamination_rho=0.7,
        alpha=0.1,
    )
    assert out.action == "require_external"
    assert out.required_external_verifications == 4  # 6 total - 2 held
    assert out.meets_error_budget is False


def test_negative_verdict_is_safe_direction():
    """Contamination inflates self-favored ACCEPTs, not REJECTs."""
    out = governance_gate(
        verdict="occupied",
        judge_confidence=0.6,
        generator_model="gpt-5.5",
        judge_model="gpt-5.5",
        external_anchors=0,
        contamination_rho=0.7,
    )
    assert out.action == "accept_verdict"
    assert out.meets_error_budget is True
    assert out.required_external_verifications == 0


def test_cross_family_judge_partially_decorrelates():
    """A genuinely different judge model reduces but does NOT eliminate rho."""
    same = governance_gate(
        verdict="open",
        generator_model="gpt-5.5",
        judge_model="gpt-5.5",
        contamination_rho=0.7,
    )
    cross = governance_gate(
        verdict="open",
        generator_model="gpt-5.5",
        judge_model="claude-opus-4-8",
        contamination_rho=0.7,
    )
    assert cross.contamination_regime == "cross_model"
    assert cross.self_graded is False
    # decorrelated but residual correlation remains (shared familiarity bias)
    assert 0.0 < cross.effective_rho < same.effective_rho
    # cross-model alone with zero anchors still fails a tight budget
    assert cross.action in ("require_external", "abstain_pending_external")


def test_same_family_different_checkpoint_is_family_effect():
    out = governance_gate(
        verdict="open",
        generator_model="gpt-5.5",
        judge_model="gpt-4o",
        contamination_rho=0.7,
    )
    assert out.contamination_regime == "cross_model"
    # family effect: milder discount than true cross-family
    assert math.isclose(out.effective_rho, 0.7 * 0.7, abs_tol=1e-6)


def test_same_lineage_override():
    """Explicit same_lineage=True forces worst-case treatment."""
    out = governance_gate(
        verdict="open",
        generator_model="model-a",
        judge_model="model-b",
        same_lineage=True,
        contamination_rho=0.7,
    )
    assert out.self_graded is True
    assert math.isclose(out.effective_rho, 0.7, abs_tol=1e-6)


def test_unknown_models_assume_worst_case():
    out = governance_gate(verdict="open", contamination_rho=0.7)
    assert out.self_graded is True
    assert out.contamination_regime == "self_graded"


def test_zero_rho_trusts_self_grade():
    """If measured contamination is zero, self-governance is fine."""
    out = governance_gate(
        verdict="open",
        judge_confidence=0.9,
        generator_model="gpt-5.5",
        judge_model="gpt-5.5",
        contamination_rho=0.0,
    )
    assert out.action == "accept"
    assert out.residual_contamination_risk == 0.0
    assert out.required_external_verifications == 0


def test_higher_rho_demands_more_verification():
    """r(rho) is monotone: more contamination -> more required external checks."""
    lo = governance_gate(verdict="open", contamination_rho=0.3, alpha=0.1)
    hi = governance_gate(verdict="open", contamination_rho=0.9, alpha=0.1)
    assert hi.required_external_verifications > lo.required_external_verifications


def test_registry_exposes_spec():
    from research_harness.primitives.registry import get_primitive_spec

    spec = get_primitive_spec("governance_gate")
    assert spec is not None
    assert spec.requires_llm is False
    assert spec.category.value == "verification"
