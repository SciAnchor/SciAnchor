"""Tests for the static writing-rigor rules and their prompt wiring."""

from __future__ import annotations

from research_harness.execution.prompts import (
    build_section_draft_prompt,
    section_revise_prompt,
)
from research_harness.execution.writing_rigor import (
    DOMAIN_OVERLAYS,
    PAPER_RIGOR_RULES,
    PER_SECTION_TIPS,
    build_rigor_block,
    normalize_section_key,
    resolve_domain_key,
)

RIGOR_SENTINEL = "SCIENTIFIC RIGOR RULES"


# -- Module composition -------------------------------------------------------


class TestBuildRigorBlock:
    def test_contains_base_rules(self):
        block = build_rigor_block("introduction")
        assert RIGOR_SENTINEL in block

    def test_contains_section_tip(self):
        block = build_rigor_block("introduction")
        assert "INTRODUCTION METHODOLOGY" in block

    def test_contains_domain_overlay(self):
        block = build_rigor_block("method", domain_key="biomedical")
        assert "DOMAIN OVERLAY: BIOMEDICAL" in block

    def test_unknown_section_still_gets_base_rules(self):
        block = build_rigor_block("appendix")
        assert RIGOR_SENTINEL in block
        assert "METHODOLOGY" not in block

    def test_unknown_domain_falls_back_to_no_overlay(self):
        block = build_rigor_block("method", domain_key="astrology")
        assert "DOMAIN OVERLAY" not in block

    def test_every_tip_key_composes(self):
        for section in PER_SECTION_TIPS:
            block = build_rigor_block(section)
            assert RIGOR_SENTINEL in block
            assert PER_SECTION_TIPS[section].strip()[:20] in block

    def test_every_domain_overlay_composes(self):
        for domain in DOMAIN_OVERLAYS:
            block = build_rigor_block("introduction", domain_key=domain)
            assert "DOMAIN OVERLAY" in block

    def test_prohibited_phrases_folded_from_style_block(self):
        # The old prompts._COMMON_STYLE_BLOCK banned list now lives here.
        assert '"delve into"' in PAPER_RIGOR_RULES
        assert '"a myriad of"' in PAPER_RIGOR_RULES


class TestNormalizeSectionKey:
    def test_aliases(self):
        assert normalize_section_key("intro") == "introduction"
        assert normalize_section_key("Related Work") == "related_work"
        assert normalize_section_key("Methods") == "method"
        assert normalize_section_key("methodology") == "method"
        assert normalize_section_key("results") == "experiments"
        assert normalize_section_key("Conclusions") == "conclusion"

    def test_identity(self):
        assert normalize_section_key("abstract") == "abstract"
        assert normalize_section_key("limitations") == "limitations"


class TestResolveDomainKey:
    def test_from_domain_writing_profile(self):
        plan = {"domain_writing_profile": {"domain_skill": "domain-writing-humanities"}}
        assert resolve_domain_key(plan) == "humanities"

    def test_from_domain_skill_without_prefix(self):
        plan = {"domain_writing_profile": {"domain_skill": "law-policy"}}
        assert resolve_domain_key(plan) == "law_policy"

    def test_from_paper_profile_discipline(self):
        plan = {"paper_profile": {"discipline": "psychology"}}
        assert resolve_domain_key(plan) == "social_science"

    def test_discipline_families(self):
        assert resolve_domain_key({"paper_profile": {"discipline": "ml"}}) == "stem"
        assert (
            resolve_domain_key({"paper_profile": {"discipline": "public_health"}})
            == "biomedical"
        )
        assert (
            resolve_domain_key({"paper_profile": {"discipline": "philosophy"}})
            == "humanities"
        )
        assert (
            resolve_domain_key({"paper_profile": {"discipline": "regulation"}})
            == "law_policy"
        )

    def test_profile_wins_over_discipline(self):
        plan = {
            "domain_writing_profile": {"domain_skill": "domain-writing-biomedical"},
            "paper_profile": {"discipline": "ml"},
        }
        assert resolve_domain_key(plan) == "biomedical"

    def test_defaults_to_stem(self):
        assert resolve_domain_key(None) == "stem"
        assert resolve_domain_key({}) == "stem"
        assert (
            resolve_domain_key({"paper_profile": {"discipline": "unknown"}}) == "stem"
        )


# -- Prompt dispatch wiring ----------------------------------------------------


class TestSectionDraftPromptDispatch:
    def _prompt(self, section: str, **kwargs) -> str:
        return build_section_draft_prompt(
            section=section,
            outline="Working title: Test Paper",
            evidence_text="[1] A. Author et al. (2026)",
            **kwargs,
        )

    def test_abstract_dispatches_to_dedicated_prompt(self):
        # Regression: the abstract previously fell through to the generic prompt.
        prompt = self._prompt("abstract")
        assert "ABSTRACT METHODOLOGY" in prompt
        assert "five-sentence formula" in prompt
        assert "five moves" in prompt

    def test_discussion_gets_methodology_via_generic_prompt(self):
        prompt = self._prompt("discussion")
        assert "DISCUSSION METHODOLOGY" in prompt

    def test_conclusion_gets_methodology_via_generic_prompt(self):
        prompt = self._prompt("conclusion")
        assert "CONCLUSION METHODOLOGY" in prompt

    def test_limitations_gets_methodology_via_generic_prompt(self):
        prompt = self._prompt("limitations")
        assert "LIMITATIONS METHODOLOGY" in prompt

    def test_intro_uses_six_move_structure(self):
        prompt = self._prompt("introduction")
        assert "six moves" in prompt
        assert "Move 1 — Stakes" in prompt
        assert "Move 6 — Results preview" in prompt
        assert "We transform" in prompt

    def test_related_work_has_gap_contribution_mapping(self):
        prompt = self._prompt("related_work")
        assert "GAP-TO-CONTRIBUTION MAPPING" in prompt
        assert "STRUCTURAL barrier" in prompt

    def test_all_sections_contain_rigor_rules(self):
        for section in (
            "abstract",
            "introduction",
            "related_work",
            "method",
            "experiments",
            "discussion",
            "conclusion",
            "limitations",
        ):
            assert RIGOR_SENTINEL in self._prompt(section), section

    def test_plural_methods_uses_dedicated_prompt_and_target(self):
        prompt = self._prompt("Methods", max_words=3250)
        assert "METHOD SECTION FORMAT REQUIREMENTS (STRICT)" in prompt
        assert "Target words: ~3250" in prompt
        assert "Do NOT include a top-level" in prompt

    def test_domain_overlay_reaches_prompt(self):
        prompt = self._prompt("method", domain_key="humanities")
        assert "DOMAIN OVERLAY: HUMANITIES" in prompt

    def test_paper_context_block_injected_when_present(self):
        context = "## PAPER CONTEXT (single source of truth)\nCore claim: X"
        prompt = self._prompt("introduction", paper_context=context)
        assert "PAPER CONTEXT" in prompt

    def test_paper_context_absent_by_default(self):
        assert "PAPER CONTEXT" not in self._prompt("introduction")

    def test_patterns_path_gets_rigor_rules(self):
        prompt = build_section_draft_prompt(
            section="broader_impact",
            outline="",
            evidence_text="[1] A. Author et al. (2026)",
            writing_patterns="Open with a concrete failure case.",
        )
        assert RIGOR_SENTINEL in prompt
        assert "Writing Patterns from Top Papers" in prompt


class TestSectionRevisePrompt:
    def test_contains_rigor_and_revision_rules(self):
        prompt = section_revise_prompt("introduction", "text", "fix the hook")
        assert RIGOR_SENTINEL in prompt
        assert "REVISION RULES" in prompt

    def test_evidence_block_only_when_supplied(self):
        without = section_revise_prompt("method", "text", "feedback")
        assert "you MAY add new [N]" not in without
        with_evidence = section_revise_prompt(
            "method", "text", "feedback", evidence_text="[1] Paper"
        )
        assert "you MAY add new [N]" in with_evidence

    def test_domain_overlay_reaches_revise_prompt(self):
        prompt = section_revise_prompt(
            "method", "text", "feedback", domain_key="law_policy"
        )
        assert "DOMAIN OVERLAY: LAW / POLICY" in prompt
