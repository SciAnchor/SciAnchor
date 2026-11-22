"""Tests for the venue prescription resolver (EAG first-impression binding)."""

from __future__ import annotations

import json

from research_harness.primitives.venue_prescription import (
    resolve_venue_prescription,
)


def test_resolves_neurips() -> None:
    rx = resolve_venue_prescription(
        target_venue="NeurIPS", discipline="machine learning"
    )
    assert rx.venue_tier  # non-empty tier label
    assert rx.style_profile == "stem_conference"
    assert rx.official_page_limit == 9


def test_resolves_biomed_style_from_discipline() -> None:
    rx = resolve_venue_prescription(discipline="biomedical omics")
    assert rx.style_profile == "biomed_omics"


def test_unknown_venue_has_zero_page_limit() -> None:
    rx = resolve_venue_prescription(target_venue="Some Unknown Venue")
    assert rx.official_page_limit == 0


def test_explicit_page_limit_wins() -> None:
    rx = resolve_venue_prescription(target_venue="NeurIPS", page_limit=12)
    assert rx.official_page_limit == 12


def test_has_fourteen_quality_targets() -> None:
    rx = resolve_venue_prescription(target_venue="ICLR", discipline="machine learning")
    assert len(rx.quality_targets) == 14
    dims = {t.dimension for t in rx.quality_targets}
    assert {
        "title",
        "abstract",
        "logical_flow",
        "completeness",
        "figure_density",
        "aesthetics",
        "palette",
        "layout",
        "page_fill",
        "paragraph_length",
        "main_appendix",
    } <= dims


def test_to_dict_is_json_serializable() -> None:
    rx = resolve_venue_prescription(target_venue="NeurIPS")
    d = rx.to_dict()
    assert json.dumps(d)  # must not raise
    assert d["official_page_limit"] == 9
    assert isinstance(d["abstract_word_band"], list)
    assert len(d["quality_targets"]) == 14
    # every target carries the audit tool + remediation the discriminator needs
    for t in d["quality_targets"]:
        assert t["audit_tool"]
        assert t["remediation"]
        assert t["metric_type"] in {"deterministic", "llm_judge", "vlm_judge"}
