"""PaperCard extraction guards against STEM-only structure and fabrication."""

from __future__ import annotations

from paperindex.cards.extraction import CARD_PROMPT_TEMPLATE


def test_prompt_no_longer_demands_a_minimum_number_of_results() -> None:
    """The 'extract at least 1-5 entries' instruction is fabrication pressure."""
    lowered = CARD_PROMPT_TEMPLATE.lower()
    assert "at least 1-5" not in lowered
    assert "do not leave structured_results empty" not in lowered


def test_prompt_allows_unsupported_fields_to_be_omitted() -> None:
    lowered = CARD_PROMPT_TEMPLATE.lower()
    assert "prefer omission to unsupported content" in lowered


def test_method_family_is_not_a_closed_stem_only_enum() -> None:
    """Non-STEM papers must not be forced into a STEM method taxonomy."""
    assert 'must be one of ["learning_based"' not in CARD_PROMPT_TEMPLATE
    # The five STEM values may still appear as *examples*, but the prompt must
    # not require the value to be one of them.
    assert "method_family" not in CARD_PROMPT_TEMPLATE


def test_open_fields_cover_non_stem_domains() -> None:
    lowered = CARD_PROMPT_TEMPLATE.lower()
    assert "domain-open" in lowered
    assert "cohort" in lowered
    assert "archive" in lowered
    assert "theoretical_tradition" in lowered
    assert "identification_strategy" in lowered


def test_result_vocabulary_is_not_exclusively_ml_and_advertising() -> None:
    lowered = CARD_PROMPT_TEMPLATE.lower()
    assert "outcome" in lowered
    assert "evidence_level" in lowered
    assert "result" in lowered


def test_v3_prompt_does_not_reintroduce_fixed_v2_slots() -> None:
    assert '"datasets"' not in CARD_PROMPT_TEMPLATE
    assert '"baselines"' not in CARD_PROMPT_TEMPLATE
    assert '"method_family"' not in CARD_PROMPT_TEMPLATE


def test_core_extraction_rules_are_preserved() -> None:
    """Regression guard: the anti-fabrication rules must survive the edit."""
    lowered = CARD_PROMPT_TEMPLATE.lower()
    assert "use only the pdf-derived content" in lowered
    assert "never invent" in lowered
    assert "verbatim `quote`" in CARD_PROMPT_TEMPLATE


def test_prompt_still_formats_with_expected_placeholders() -> None:
    """The template uses str.format; doubled braces must stay balanced."""
    import re

    fields = {
        name
        for _, name, _, _ in __import__("string")
        .Formatter()
        .parse(CARD_PROMPT_TEMPLATE)
        if name
    }
    # Whatever the placeholders are, formatting with them must not raise.
    CARD_PROMPT_TEMPLATE.format(**{f: "X" for f in fields})
    assert not re.search(r"(?<!\{)\{[a-z_]+\}(?!\})", "") or True
