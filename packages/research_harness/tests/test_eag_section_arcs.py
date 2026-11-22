"""EAG-Ladder batch 1: L1 section arcs + style card auto-plan (opt-in).

Producers (tool_dispatch) and the consumer (section_draft outline
auto-consume) are both gated by env switches that default OFF until the E1
A/B evidence flips them. All LLM surfaces are faked; tests are deterministic.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import research_harness._workflow.execution.llm_primitives as LP
from research_harness.auto_runner.tool_dispatch import (
    _SECTION_ARC_UNITS,
    _maybe_auto_exemplar_section_arc_plans,
    _maybe_auto_exemplar_style_plan,
)
from research_harness.orchestrator.service import OrchestratorService
from research_harness.primitives import exemplar_impls as EAG

from .test_paper_production_defaults import _create_topic

ARC_UNITS = ("related_work_arc", "method_arc", "experiment_arc", "discussion_arc")


# ---------------------------------------------------------------------------
# Unit registration
# ---------------------------------------------------------------------------


def test_arc_units_have_curate_and_plan_prompts_and_section_mapping():
    for unit in ARC_UNITS:
        assert unit in EAG._CURATE_PROMPTS, unit
        assert unit in EAG._PLAN_PROMPTS, unit
        assert "FORM" in EAG._CURATE_PROMPTS[unit]
        assert unit in EAG._SECTION_FOR_UNIT, unit
    assert _SECTION_ARC_UNITS == ARC_UNITS
    # Consumer map covers every prose section that has an arc contract.
    assert LP._ARC_PLAN_FOR_SECTION["related_work"] == "exemplar_plan_related_work_arc"
    assert LP._ARC_PLAN_FOR_SECTION["results"] == "exemplar_plan_experiment_arc"
    assert LP._ARC_PLAN_FOR_SECTION["limitations"] == "exemplar_plan_discussion_arc"


# ---------------------------------------------------------------------------
# Producers (tool_dispatch auto-plans)
# ---------------------------------------------------------------------------


def _fake_stack(
    monkeypatch,
    *,
    units_by_type: dict[str, list[Any]] | None = None,
    fail_units: set[str] | None = None,
):
    """Fake curate/retrieve/plan keeping per-unit-type call counts."""
    calls: dict[str, list[str]] = {"curate": [], "retrieve": [], "plan": []}
    units_by_type = units_by_type if units_by_type is not None else {}
    fail_units = fail_units or set()

    def fake_curate(*, unit_type: str, **kwargs):
        calls["curate"].append(unit_type)
        if unit_type in fail_units:
            raise RuntimeError(f"curate exploded for {unit_type}")
        units = units_by_type.get(unit_type, [SimpleNamespace(source_paper_id=1)])
        return SimpleNamespace(unit_type=unit_type, units=units)

    def fake_retrieve(*, unit_type: str, units=None, **kwargs):
        calls["retrieve"].append(unit_type)
        return SimpleNamespace(unit_type=unit_type, ranked=list(units or []))

    def fake_plan(*, unit_type: str, **kwargs):
        calls["plan"].append(unit_type)
        return SimpleNamespace(
            unit_type=unit_type,
            plan={"moves": [{"move": "m1", "instruction": f"do {unit_type}"}]},
            exemplar_ids=[1],
            form_only=True,
        )

    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_curate", fake_curate
    )
    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_retrieve", fake_retrieve
    )
    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_plan", fake_plan
    )
    return calls


def test_style_autoplan_on_by_default_and_disable_switch(db, monkeypatch):
    # Default ON since the venue-family/prose-screen overhaul; =0 disables.
    monkeypatch.delenv("RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN", raising=False)
    calls = _fake_stack(monkeypatch)
    topic_id = _create_topic(db, "style-default-topic")
    svc = OrchestratorService(db)

    _maybe_auto_exemplar_style_plan(
        db=db, svc=svc, topic_id=topic_id, context={}, results=[]
    )
    assert calls["curate"] == ["style"]
    assert svc.get_latest_artifact(topic_id, "write", "exemplar_plan_style") is not None

    monkeypatch.setenv("RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN", "0")
    calls2 = _fake_stack(monkeypatch)
    topic_id2 = _create_topic(db, "style-disabled-topic")
    _maybe_auto_exemplar_style_plan(
        db=db, svc=svc, topic_id=topic_id2, context={}, results=[]
    )
    assert calls2["curate"] == []
    assert svc.get_latest_artifact(topic_id2, "write", "exemplar_plan_style") is None


def test_style_autoplan_records_style_card_when_enabled(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN", "1")
    _fake_stack(monkeypatch)
    topic_id = _create_topic(db, "style-on-topic")
    svc = OrchestratorService(db)
    results: list[Any] = []

    _maybe_auto_exemplar_style_plan(
        db=db, svc=svc, topic_id=topic_id, context={"title": "T"}, results=results
    )

    card = svc.get_latest_artifact(topic_id, "write", "exemplar_plan_style")
    assert card is not None
    assert card.payload["unit_type"] == "style"
    assert card.payload["origin"] == "eag_auto_plan"
    assert [r.tool for r in results] == ["exemplar_auto_plan"]


def test_section_arc_autoplans_gated_and_record_all_four(db, monkeypatch):
    # Disabled with =0 (default is ON since the whole-paper imitation mandate).
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_SECTION_ARCS", "0")
    calls = _fake_stack(monkeypatch)
    topic_id = _create_topic(db, "arcs-topic")
    svc = OrchestratorService(db)
    results: list[Any] = []

    _maybe_auto_exemplar_section_arc_plans(
        db=db, svc=svc, topic_id=topic_id, context={}, results=results
    )
    assert calls["curate"] == []

    # Default ON: all four contracts recorded.
    monkeypatch.delenv("RESEARCH_HARNESS_EAG_SECTION_ARCS", raising=False)
    _maybe_auto_exemplar_section_arc_plans(
        db=db, svc=svc, topic_id=topic_id, context={"title": "T"}, results=results
    )
    for unit in ARC_UNITS:
        artifact = svc.get_latest_artifact(topic_id, "write", f"exemplar_plan_{unit}")
        assert artifact is not None, unit
        assert artifact.payload["unit_type"] == unit
    assert calls["curate"] == list(ARC_UNITS)

    # Idempotent: second run short-circuits before any primitive call.
    _maybe_auto_exemplar_section_arc_plans(
        db=db, svc=svc, topic_id=topic_id, context={}, results=results
    )
    assert calls["curate"] == list(ARC_UNITS)


def test_section_arc_autoplans_isolate_per_unit_failures(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_SECTION_ARCS", "1")
    _fake_stack(monkeypatch, fail_units={"method_arc"})
    topic_id = _create_topic(db, "arcs-isolation-topic")
    svc = OrchestratorService(db)

    _maybe_auto_exemplar_section_arc_plans(
        db=db, svc=svc, topic_id=topic_id, context={}, results=[]
    )

    assert (
        svc.get_latest_artifact(topic_id, "write", "exemplar_plan_method_arc") is None
    )
    for unit in ("related_work_arc", "experiment_arc", "discussion_arc"):
        assert (
            svc.get_latest_artifact(topic_id, "write", f"exemplar_plan_{unit}")
            is not None
        ), unit


# ---------------------------------------------------------------------------
# Consumer (section_draft outline auto-consume)
# ---------------------------------------------------------------------------


# Minimal plan that passes the manuscript logic gate so section_draft runs.
_PASSING_PLAN = {
    "manuscript_logic_gate_report": {
        "schema_version": "rh.manuscript.logic_gate_report.v1",
        "status": "pass",
        "blockers": [],
    },
    "fine_logic_audit_report": {
        "schema_version": "rh.manuscript.fine_logic_audit_report.v1",
        "status": "pass",
        "blockers": [],
    },
}


def _record_arc_plan(db, topic_id: int, unit: str, instruction: str) -> None:
    OrchestratorService(db).record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type=f"exemplar_plan_{unit}",
        title=f"exemplar plan: {unit}",
        payload={
            "unit_type": unit,
            "plan": {"moves": [{"move": "m1", "instruction": instruction}]},
            "form_only": True,
        },
    )


def _capture_draft_prompts(monkeypatch) -> list[str]:
    captured: list[str] = []

    class _FC:
        model = "mock-llm"

    def responder(client, prompt, **kwargs):
        captured.append(str(prompt))
        return "A drafted section with a citation [1]."

    monkeypatch.setattr(LP, "_get_client", lambda *a, **k: _FC())
    monkeypatch.setattr(LP, "_client_chat", responder)
    return captured


def test_section_draft_ignores_arc_plan_when_gate_off(db, monkeypatch):
    # Explicitly disabled (default is ON since the whole-paper mandate).
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_SECTION_ARCS", "0")
    topic_id = _create_topic(db, "consume-off-topic")
    marker = "ARC-MARKER survey the two strands then position"
    _record_arc_plan(db, topic_id, "related_work_arc", marker)
    captured = _capture_draft_prompts(monkeypatch)

    LP.section_draft(
        db=db, section="related_work", topic_id=topic_id, paper_plan=_PASSING_PLAN
    )

    assert captured, "section_draft did not reach the LLM"
    assert all(marker not in p for p in captured)


def test_section_draft_consumes_arc_plan_when_enabled(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_SECTION_ARCS", "1")
    topic_id = _create_topic(db, "consume-on-topic")
    marker = "ARC-MARKER survey the two strands then position"
    _record_arc_plan(db, topic_id, "related_work_arc", marker)
    captured = _capture_draft_prompts(monkeypatch)

    LP.section_draft(
        db=db, section="related_work", topic_id=topic_id, paper_plan=_PASSING_PLAN
    )

    assert captured, "section_draft did not reach the LLM"
    assert any(marker in p for p in captured)


def test_section_draft_intro_arc_consumption_stays_default_on(db, monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_EAG_SECTION_ARCS", raising=False)
    topic_id = _create_topic(db, "consume-intro-topic")
    marker = "ARC-MARKER open with the concrete domain problem"
    _record_arc_plan(db, topic_id, "intro_arc", marker)
    captured = _capture_draft_prompts(monkeypatch)

    LP.section_draft(
        db=db, section="introduction", topic_id=topic_id, paper_plan=_PASSING_PLAN
    )

    assert captured, "section_draft did not reach the LLM"
    assert any(marker in p for p in captured)


def test_plural_methods_consumes_method_arc_and_prompt(db, monkeypatch):
    topic_id = _create_topic(db, "consume-methods-topic")
    marker = "ARC-MARKER develop the method in five linked moves"
    _record_arc_plan(db, topic_id, "method_arc", marker)
    captured = _capture_draft_prompts(monkeypatch)

    output = LP.section_draft(
        db=db,
        section="Methods",
        topic_id=topic_id,
        max_words=3250,
        paper_plan=_PASSING_PLAN,
    )

    assert output.draft.section == "Methods"
    assert marker in captured[0]
    assert "METHOD SECTION FORMAT REQUIREMENTS (STRICT)" in captured[0]
    assert "Target words: ~3250" in captured[0]
    assert LP.eag_revision_guidance(db, topic_id, "Methods").find(marker) >= 0


def test_section_draft_injects_venue_polish_when_topic_has_target_venue(
    db, monkeypatch
):
    topic_id = _create_topic(db, "polish-on-topic", venue="NeurIPS")
    captured = _capture_draft_prompts(monkeypatch)

    LP.section_draft(
        db=db, section="introduction", topic_id=topic_id, paper_plan=_PASSING_PLAN
    )

    joined = "\n".join(captured)
    assert "VENUE POLISH CONTRACT" in joined
    assert "paragraph_length" in joined or "abstract" in joined


def test_section_draft_skips_venue_polish_without_target_venue(db, monkeypatch):
    topic_id = _create_topic(db, "polish-off-topic", venue="")
    captured = _capture_draft_prompts(monkeypatch)

    LP.section_draft(
        db=db, section="introduction", topic_id=topic_id, paper_plan=_PASSING_PLAN
    )

    assert all("VENUE POLISH CONTRACT" not in p for p in captured)


def test_section_review_folds_venue_polish_failures(db, monkeypatch):
    topic_id = _create_topic(db, "polish-review-topic", venue="NeurIPS")

    class _FC:
        model = "mock-llm"

    monkeypatch.setattr(LP, "_get_client", lambda *a, **k: _FC())
    monkeypatch.setattr(
        LP,
        "_client_chat",
        lambda *a, **k: json.dumps(
            {
                "overall_score": 0.9,
                "dimensions": [],
                "suggestions": [],
            }
        ),
    )
    # Thin one-sentence body paragraph (>15 words) fails paragraph_length.
    thin = (
        "This single sentence paragraph has more than fifteen words so the "
        "venue polish contract must flag it as underdeveloped."
    )
    out = LP.section_review(
        db=db,
        section="introduction",
        content=thin,
        target_words=200,
        topic_id=topic_id,
    )
    names = [c.check_name for c in out.deterministic_checks]
    assert any(n.startswith("venue_polish_") for n in names)
    assert out.needs_revision is True


def test_curate_quality_scale_guard(db, monkeypatch):
    # Models often return quality normalized to 0-1 despite the 0-10
    # instruction; (0,1] must be rescaled or every exemplar is rejected.

    responses = iter(
        [
            '{"form":{"tone":"measured"},"quality":0.92,"prose_quality":0.9,"summary":"s"}'
        ]
    )
    monkeypatch.setattr(EAG, "_chat", lambda c, p: next(responses))
    monkeypatch.setattr(
        EAG,
        "_fetch_sources",
        lambda *a, **k: [
            {"id": 1, "title": "T", "venue": "V", "abstract": "x" * 200, "note": ""}
        ],
    )

    out = EAG.exemplar_curate(db=db, topic_id=1, unit_type="style", min_quality=7.0)
    assert out.kept == 1, (out.kept, out.rejected)
    assert abs(out.units[0].quality - 9.2) < 1e-9


def test_section_review_arc_conformance_paragraph_count(db):
    """eag_arc_conformance: draft paragraph count must track the contract."""
    topic_id = _create_topic(db, "arc-conformance-topic")
    svc = OrchestratorService(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="exemplar_plan_intro_arc",
        title="exemplar plan: intro_arc (test)",
        payload={
            "plan": {
                "paragraphs": [
                    {"role": "establish-importance", "sentences": []},
                    {"role": "gap", "sentences": []},
                    {"role": "this-work", "sentences": []},
                ]
            }
        },
    )
    ok = LP._arc_conformance_check(
        db, topic_id, "introduction", "para one\n\npara two\n\npara three"
    )
    assert ok is not None and ok[0] is True
    bad = LP._arc_conformance_check(
        db,
        topic_id,
        "introduction",
        "\n\n".join(f"para {i}" for i in range(6)),
    )
    assert bad is not None and bad[0] is False and "plans 3" in bad[1]
    # No contract for method (opt-in arcs off) -> no check emitted.
    assert LP._arc_conformance_check(db, topic_id, "method", "x\n\ny") is None


def test_section_revise_restates_eag_contract(db, monkeypatch):
    """Revision surfaces must not lose the EAG target (user mandate)."""
    topic_id = _create_topic(db, "revise-contract-topic")
    marker = "ARC-MARKER open with the concrete domain problem"
    _record_arc_plan(db, topic_id, "intro_arc", marker)
    captured = _capture_draft_prompts(monkeypatch)

    LP.section_revise(
        db=db,
        section="introduction",
        content="Some drafted introduction text.",
        review_feedback="Tighten the gap statement.",
        topic_id=topic_id,
    )

    assert captured, "section_revise did not reach the LLM"
    assert any("EXEMPLAR INTRODUCTION CONTRACT" in p for p in captured)
    assert any(marker in p for p in captured)
