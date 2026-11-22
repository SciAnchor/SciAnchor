"""Tests for the top-institution gate (EAG goal 4, institution half)."""

from __future__ import annotations

from research_harness.primitives.top_institutions import (
    has_top_institution,
    normalize_affiliation,
    top_institution_matches,
)


def test_normalize_lowercases_and_strips_punctuation() -> None:
    assert normalize_affiliation("Google Research, Mountain View, CA") == (
        "google research mountain view ca"
    )
    assert normalize_affiliation("M.I.T.") == "m i t"


def test_matches_known_institutions() -> None:
    hits = top_institution_matches(
        ["Google Research, Mountain View", "Stanford University", "Acme Corp"]
    )
    assert hits == ["google", "stanford"]


def test_matches_alias_variants() -> None:
    assert top_institution_matches(["Massachusetts Institute of Technology"]) == ["mit"]
    assert top_institution_matches(["Facebook AI Research"]) == ["meta"]


def test_no_match_for_unknown() -> None:
    assert top_institution_matches(["Unknown University"]) == []
    assert top_institution_matches(["Acme Analytics Corp"]) == []


def test_empty_and_none() -> None:
    assert top_institution_matches([]) == []
    assert top_institution_matches(None) == []
    assert top_institution_matches("") == []
    assert not has_top_institution(None)


def test_accepts_single_string() -> None:
    assert top_institution_matches("DeepMind, London") == ["deepmind"]
    assert has_top_institution("OpenAI")


def test_deduplicates_canonical_names() -> None:
    hits = top_institution_matches(["Google", "Google Research", "google brain"])
    assert hits == ["google"]
