"""Guard for the delivery-protocol venue-overlay contract (LG77).

``build_delivery_venue_overlay`` is a deterministic, side-effect-free classifier
that resolves a target venue into a submission-constraint overlay (review model,
anonymization, format family, required declarations). These tests pin the family
classification, the no-silent-default behavior for unknown/empty venues, and the
serialized shape.
"""

from __future__ import annotations

from research_harness._selfdev.delivery_protocol import (
    DeliveryVenueOverlay,
    build_delivery_venue_overlay,
)


def test_ml_conference_overlay_requires_anonymization() -> None:
    overlay = build_delivery_venue_overlay(target_venue="NeurIPS 2026")

    assert overlay.status == "success"
    assert overlay.schema_version == "rh.delivery.venue_overlay.v1"
    assert overlay.venue_family == "ml_conference"
    assert overlay.review_model == "double_blind"
    assert overlay.anonymization_required is True
    assert overlay.format_family == "latex-two-column"
    assert "reproducibility_statement" in overlay.required_declarations
    assert overlay.blockers == ()
    assert overlay.public_surface == "none"
    assert overlay.runtime_dependency == "none"


def test_clinical_journal_overlay_is_single_blind_with_trial_registration() -> None:
    overlay = build_delivery_venue_overlay(target_venue="clinical-journal")

    assert overlay.status == "success"
    assert overlay.venue_family == "clinical_journal"
    assert overlay.review_model == "single_blind"
    assert overlay.anonymization_required is False
    assert overlay.format_family == "journal-single-column"
    assert "trial_registration" in overlay.required_declarations
    assert "ethics_approval" in overlay.required_declarations


def test_each_family_resolves_for_a_representative_venue() -> None:
    cases = {
        "ICML": "ml_conference",
        "EMNLP": "nlp_conference",
        "OSDI": "systems_conference",
        "Nature": "general_science_journal",
        "npj Digital Medicine": "nature_partner_journal",
        "The Lancet": "clinical_journal",
        "ICLR Workshop on Agents": "workshop",
        "Environmental Research Letters": "environmental_science_journal",
        "Journal of Hydrometeorology": "earth_science_journal",
        "Applied Energy": "energy_engineering_journal",
        "Energy and Buildings": "energy_engineering_journal",
        "Pattern Recognition": "engineering_journal",
        "Bioinformatics": "life_science_journal",
        "Nucleic Acids Research": "life_science_journal",
        "Global Change Biology": "life_science_journal",
        "Functional Ecology": "life_science_journal",
        "Network Neuroscience": "neuroscience_journal",
        "Humanities and Social Sciences Communications": "social_science_journal",
    }
    for venue, family in cases.items():
        overlay = build_delivery_venue_overlay(target_venue=venue)
        assert overlay.status == "success", venue
        assert overlay.venue_family == family, venue
        # Every resolved family must carry a non-empty constraint set.
        assert overlay.required_declarations, venue
        assert overlay.review_model in ("double_blind", "single_blind"), venue


def test_unknown_venue_blocks_without_silent_default() -> None:
    overlay = build_delivery_venue_overlay(target_venue="Some Niche Venue")

    assert overlay.status == "blocked"
    assert overlay.venue_family == "unknown"
    assert overlay.review_model == "unknown"
    assert overlay.anonymization_required is False
    assert overlay.required_declarations == ()
    assert overlay.blockers == ("unknown_venue",)


def test_empty_venue_blocks_on_missing_target() -> None:
    overlay = build_delivery_venue_overlay(target_venue="   ")

    assert overlay.status == "blocked"
    assert overlay.blockers == ("missing:target_venue",)
    assert overlay.target_venue == ""


def test_overlay_to_dict_serializes_sequences_as_lists() -> None:
    overlay = build_delivery_venue_overlay(target_venue="KDD")
    payload = overlay.to_dict()

    assert isinstance(overlay, DeliveryVenueOverlay)
    assert isinstance(payload["required_declarations"], list)
    assert isinstance(payload["blockers"], list)
    assert payload["venue_family"] == "ml_conference"
    assert payload["anonymization_required"] is True
