"""Tests for finish_rulebook P0 form contract (appendix vocab + case-trace seat)."""

from __future__ import annotations

import pytest

from research_harness._workflow.execution.finish_form_contract import (
    ensure_case_trace_in_appendix_plan,
    finish_form_findings,
    looks_like_mechanism_paper,
    manuscript_has_case_trace_signal,
    normalize_appendix_plan,
    normalize_appendix_token,
)
from research_harness.primitives import exemplar_impls as EAG


def test_normalize_appendix_aliases_and_vocab():
    assert normalize_appendix_token("extended-tables") == "extended_tables"
    assert normalize_appendix_token("case study") == "case_study_trace"
    assert normalize_appendix_token("prompt_export") == "prompt_or_protocol_export"
    assert normalize_appendix_token("TRIPOD checklist") == "reporting_checklist"
    assert normalize_appendix_token("random blurb about cats") is None


def test_normalize_plan_dedupes_and_orders():
    got = normalize_appendix_plan(
        ["extended-tables", "case_study_trace", "extended_tables", "proofs"]
    )
    assert got == ["extended_tables", "case_study_trace", "proofs"]


def test_ensure_case_trace_for_mechanism_papers():
    plan = ["extended_methods", "hyperparams"]
    out = ensure_case_trace_in_appendix_plan(plan, mechanism_paper=True)
    assert "case_study_trace" in out
    # non-mechanism: do not force
    out2 = ensure_case_trace_in_appendix_plan(["hyperparams"], mechanism_paper=False)
    assert out2 == ["hyperparams"]


def test_exemplar_plan_normalizes_appendix_without_llm(monkeypatch):
    class _Fake:
        model = "fake"

        def chat(self, *a, **k):
            return (
                '{"plan":{"sections":[{"name":"Introduction","role":"intro",'
                '"approx_share":0.2,"key_moves":["x"]}],'
                '"appendix_plan":["extended-tables","hyperparams"]}}'
            )

    monkeypatch.setattr(EAG, "_llm", lambda *a, **k: _Fake())
    monkeypatch.setattr(
        EAG,
        "_chat",
        lambda client, prompt: client.chat(),
    )
    out = EAG.exemplar_plan(
        unit_type="skeleton",
        target_content=(
            "We propose a neural architecture and pipeline with modules for "
            "mechanism modeling, algorithm design, and ablation of network components."
        ),
        retrieved_units=[
            {
                "unit_type": "skeleton",
                "source_paper_id": 1,
                "venue": "NeurIPS",
                "form": {"sections": ["Introduction", "Method", "Experiments"]},
            }
        ],
    )
    plan = out.plan if isinstance(out.plan, dict) else {}
    assert "case_study_trace" in (plan.get("appendix_plan") or [])
    assert "extended_tables" in (plan.get("appendix_plan") or [])


def test_exemplar_plan_refuses_an_empty_skeleton_pool_before_any_call(monkeypatch):
    def no_call(*a, **k):
        raise AssertionError("an empty pool must stop before the model is called")

    monkeypatch.setattr(EAG, "_llm", no_call)
    with pytest.raises(ValueError) as refused:
        EAG.exemplar_plan(unit_type="skeleton", target_content="x", retrieved_units=[])
    assert getattr(refused.value, "code", "") == "E-WRITE-EAG-POOL-EMPTY"


def test_figure_suite_roles_include_case_exhibit_and_pipeline_complete():
    assert "case_exhibit" in EAG.FIGURE_SUITE_ROLES
    assert "failure_gallery" in EAG.FIGURE_SUITE_ROLES
    assert set(EAG.ROLE_PIPELINE) == set(EAG.FIGURE_SUITE_ROLES)
    assert EAG.ROLE_PIPELINE["case_exhibit"] == "generative"
    assert EAG.ROLE_PIPELINE["failure_gallery"] == "generative"


def test_finish_form_findings_flags_missing_case_on_mechanism_text():
    text = (
        "Abstract. We introduce a deep learning model and neural network architecture "
        "with a modular pipeline. Method. Our algorithm uses three modules. "
        "Results. Accuracy improves on the benchmark. "
        "Table 1 shows metrics. Figure 1 is an overview schematic."
    )
    assert looks_like_mechanism_paper(text)
    assert not manuscript_has_case_trace_signal(text)
    findings = finish_form_findings(text)
    assert any(f.get("severity") == "high" for f in findings)
    assert any("case-trace" in f.get("issue", "").lower() for f in findings)


def test_finish_form_findings_quiet_when_case_present():
    text = (
        "We propose a neural architecture and pipeline mechanism. "
        "Figure 4 is a case study walkthrough of one input through each module. "
        "Appendix B Case Study provides the full repair trace. "
        "Supplementary Information includes extended methods."
    )
    findings = finish_form_findings(text)
    assert not any(f.get("severity") == "high" for f in findings)


def test_empty_case_heading_without_anchor_still_flags():
    """Bare 'Case Study' title is not a case-trace module (rulebook M4)."""
    from research_harness._workflow.execution.finish_form_contract import (
        manuscript_has_case_trace_signal,
    )

    empty = (
        "We propose a neural architecture pipeline mechanism model algorithm system. "
        "### Case Study\n"
        "See the discussion for details.\n"
        "Table 1 shows metrics. Figure 1 is overview only far away.\n"
    )
    # Distant Fig.1 must not launder the empty heading — windowed match.
    assert not manuscript_has_case_trace_signal(empty)
    findings = finish_form_findings(empty)
    assert any(f.get("severity") == "high" for f in findings)

    anchored = (
        "We propose a neural architecture pipeline mechanism model algorithm. "
        "### Case Study\n"
        "Figure 4 (a) input (b) intermediate gate map (c) output for one sample.\n"
        "Appendix B walks the repair trace.\n"
    )
    assert manuscript_has_case_trace_signal(anchored)


def test_claim_payoff_flags_orphan_contribution_bullets():
    from research_harness._workflow.execution.finish_form_contract import (
        scan_claim_payoff,
    )

    text = """
## Contributions
- We propose a novel dual-gate module for robust fusion.
- We achieve state-of-the-art accuracy on three benchmarks (Fig. 3, Table 2).
- We release code and models for reproducibility.

## Method
...
"""
    report = scan_claim_payoff(text)
    assert len(report.contributions) >= 2
    assert any("dual-gate" in o.lower() for o in report.orphan_contributions)
    assert any("fig" in w.lower() for w in report.with_payoff)
    findings = finish_form_findings(
        text
        + "\n neural architecture pipeline mechanism model algorithm module ablation\n"
    )
    assert any("payoff" in f.get("issue", "").lower() for f in findings)


def test_exhibit_blueprint_domain_split():
    from research_harness._workflow.execution.finish_form_contract import (
        build_exhibit_blueprint,
        exhibit_blueprint_as_prompt_block,
    )

    med = build_exhibit_blueprint(domain_family="medicine")
    assert med.figure_role == "case_exhibit"
    assert "vignette" in med.genre or "patient" in med.genre
    assert "input" in med.figure_caption_skeleton.lower()
    hss = build_exhibit_blueprint(domain_family="hss")
    assert (
        "excerpt" in hss.figure_caption_skeleton.lower()
        or "theme" in " ".join(hss.outline_steps).lower()
    )
    cs = build_exhibit_blueprint(domain_family="cs")
    block = exhibit_blueprint_as_prompt_block(cs)
    assert "EXHIBIT CONTENT CONTRACT" in block
    assert "case_study_trace" in block


def test_ablation_isomorphism_scan():
    from research_harness._workflow.execution.finish_form_contract import (
        scan_ablation_isomorphism,
    )

    text = (
        "Our method uses module AlphaGate and component BetaHead. "
        "Ablation study: we remove BetaHead and the fusion block; AlphaGate is not tested."
    )
    rep = scan_ablation_isomorphism(text)
    assert rep.has_ablation_section
    assert any("alphagate" in c for c in rep.claimed_components)


def test_ablation_contract_findings_from_coverage_gate_payload():
    from research_harness._workflow.execution.finish_form_contract import (
        ablation_contract_findings,
    )

    bad = {
        "canonical_components": ["encoder", "fusion", "head"],
        "ablation_components": ["encoder", "head"],  # missing fusion
        "repeats": 3,
        "variance_estimates": [0.01, 0.02],
        "acceptance_criteria": ["delta>0"],
        "evidence_kind": "final",
    }
    findings = ablation_contract_findings(bad)
    assert findings, "mismatch should yield findings"
    assert any("ablation" in f.get("issue", "").lower() for f in findings)

    good = {
        "canonical_components": ["encoder", "fusion", "head"],
        "ablation_components": ["encoder", "fusion", "head"],
        "repeats": 3,
        "variance_estimates": [0.01, 0.02, 0.01],
        "acceptance_criteria": ["delta>0"],
        "evidence_kind": "final",
    }
    assert ablation_contract_findings(good) == []


def test_experiments_prompt_mentions_case_exhibit():
    from research_harness._workflow.execution.prompts import experiments_draft_prompt

    p = experiments_draft_prompt("outline", "evidence [1]", max_words=500)
    assert "case_exhibit" in p
    assert "EXHIBIT CONTENT CONTRACT" in p or "walkthrough" in p.lower()


def test_exhibit_block_injectable_for_section_guidance():
    """section_draft merges exhibit blueprint into section_guidance for results."""
    from research_harness._workflow.execution.finish_form_contract import (
        build_exhibit_blueprint,
        exhibit_blueprint_as_prompt_block,
    )
    from research_harness._workflow.execution.prompts import build_section_draft_prompt

    bp = build_exhibit_blueprint(domain_family="cs")
    block = exhibit_blueprint_as_prompt_block(bp)
    prompt = build_section_draft_prompt(
        section="experiments",
        outline="Main results and case study",
        evidence_text="[1] prior work",
        max_words=800,
        section_guidance=block,
        domain_key="stem",
    )
    assert "EXHIBIT CONTENT CONTRACT" in prompt
    assert bp.section_title.split()[0] in prompt or "case" in prompt.lower()


def demo() -> None:
    test_normalize_appendix_aliases_and_vocab()
    test_normalize_plan_dedupes_and_orders()
    test_ensure_case_trace_for_mechanism_papers()
    test_figure_suite_roles_include_case_exhibit_and_pipeline_complete()
    test_finish_form_findings_flags_missing_case_on_mechanism_text()
    test_finish_form_findings_quiet_when_case_present()
    test_claim_payoff_flags_orphan_contribution_bullets()
    test_exhibit_blueprint_domain_split()
    test_ablation_isomorphism_scan()
    test_ablation_contract_findings_from_coverage_gate_payload()
    test_experiments_prompt_mentions_case_exhibit()
    test_exhibit_block_injectable_for_section_guidance()
    print("finish_form_contract demo ok")


if __name__ == "__main__":
    demo()
