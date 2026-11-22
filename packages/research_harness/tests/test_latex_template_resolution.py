"""Tests for venue-string-to-template resolution in the LaTeX compiler."""

from __future__ import annotations

from research_harness.execution.latex_compiler import (
    assemble_latex,
    resolve_template_key,
    template_fingerprint,
)


def test_resolve_template_key_maps_venue_strings_to_families():
    assert resolve_template_key("aaai") == "aaai"
    assert resolve_template_key("AAAI") == "aaai"
    assert resolve_template_key("AAAI 2026") == "aaai"
    assert resolve_template_key("AAAI-26") == "aaai"
    assert resolve_template_key("NeurIPS'25") == "neurips"
    assert resolve_template_key("NIPS 2014") == "neurips"
    assert resolve_template_key("EMNLP 2026") == "acl"
    assert resolve_template_key("ICLR2026") == "iclr"
    assert resolve_template_key("Some Unknown Journal") == "generic"
    assert resolve_template_key("") == "generic"


def test_aaai_venue_string_assembles_letterpaper_two_column():
    """An AAAI venue string must never fall through to the a4paper generic
    template — that fallthrough is how an AAAI target shipped as an A4
    single-column article."""
    tex, _bib = assemble_latex(
        title="T",
        authors=["A"],
        abstract="Abstract.",
        sections={"introduction": "Body."},
        template="AAAI 2026",
    )

    assert "letterpaper" in tex
    assert "a4paper" not in tex
    assert "\\twocolumn" in tex


def test_template_fingerprint_normalizes_venue_strings():
    assert template_fingerprint("AAAI 2026") == template_fingerprint("aaai")
    assert template_fingerprint("unknown") == template_fingerprint("generic")
