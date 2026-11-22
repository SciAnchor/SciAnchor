"""EAG must anchor the WRITING surfaces, not just figure planning.

Before 2026-08-17 the abstract had no exemplar hook at all and the write gate
only checked the figure suite, so a topic could reach a finished manuscript
with no venue anchor and nobody would know: the npj-family draft opened with
"We introduce ...", a conference move. These tests pin the three repairs.
"""

from research_harness._workflow.execution.llm_primitives import (
    _ARC_PLAN_FOR_SECTION,
)
from research_harness._workflow.execution.prompts import (
    abstract_draft_prompt,
    eag_fallback_notice,
)


def test_abstract_has_an_arc_plan_like_the_introduction():
    assert _ARC_PLAN_FOR_SECTION["abstract"] == "exemplar_plan_abstract_arc"


def test_abstract_prompt_uses_contract_when_present():
    prompt = abstract_draft_prompt(
        "outline",
        "evidence",
        section_guidance="## EXEMPLAR ABSTRACT CONTRACT\nopen on the problem",
    )
    assert "REQUIRED — exemplar contract" in prompt
    assert "EXEMPLAR ABSTRACT CONTRACT" in prompt


def test_abstract_fallback_bans_conference_openers():
    prompt = abstract_draft_prompt("outline", "evidence")
    assert "fallback — no exemplar contract" in prompt
    # the exact failure that shipped: a journal abstract opening on "We introduce"
    assert "Do NOT open with" in prompt and "We introduce" in prompt


def test_fallback_notice_fires_only_without_a_contract():
    assert eag_fallback_notice("abstract", "") is not None
    assert eag_fallback_notice("introduction", "") is not None
    assert eag_fallback_notice("abstract", "## EXEMPLAR ABSTRACT CONTRACT") is None
    assert (
        eag_fallback_notice("introduction", "## EXEMPLAR INTRODUCTION CONTRACT") is None
    )
    # sections without a contract concept do not emit noise
    assert eag_fallback_notice("method", "") is None


def test_fallback_notice_names_the_repair():
    notice = eag_fallback_notice("abstract", "")
    assert "rh exemplar import" in notice
    assert "eag_fallback" in notice


def test_write_gate_defaults_on():
    """The gate must be on by default: the user's standing requirement is that
    EAG participates in every draft and revision."""
    import inspect

    from research_harness._workflow.orchestrator import invariants

    src = inspect.getsource(invariants.InvariantChecker.check_exemplar_writing_gate)
    # default "1" -> enabled unless explicitly switched off
    assert 'RESEARCH_HARNESS_EAG_WRITE_GATE", "1"' in src
    assert "exemplar_plan_abstract_arc" in src
    dispatch = inspect.getsource(invariants.InvariantChecker)
    assert "self.check_exemplar_writing_gate(topic_id, stage)" in dispatch
