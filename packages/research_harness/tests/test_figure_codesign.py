"""UF05 co-design: five roles × two venues, no rendering."""

from __future__ import annotations

import pytest

from research_harness.visualization.figure_codesign import codesign_figure
from research_harness.visualization.figure_package_contracts import (
    FIGURE_ROLES,
    SCHEMA_FIGURE_OPPORTUNITY,
    TARGET_VENUES,
    validate_caption_contract,
    validate_figure_design_contract,
)

_BOUNDARY = {
    "method_architecture": "conceptual",
    "study_or_experiment_design": "planned_protocol",
    "quantitative_comparison": "evidence_backed",
    "ablation_or_sensitivity": "evidence_backed",
    "qualitative_cases": "mixed",
}

_FORBIDDEN = {
    "conceptual": ["observed_result", "statistical_significance"],
    "planned_protocol": ["observed_result", "statistical_significance"],
    "evidence_backed": [],
    "mixed": ["statistical_significance"],
}


def _opp(role: str, venue: str, **overrides: object) -> dict[str, object]:
    boundary = str(_BOUNDARY[role])
    forbidden = list(_FORBIDDEN[boundary])
    if venue == "npj Digital Medicine":
        forbidden = list(
            dict.fromkeys([*forbidden, "clinical_deployment", "clinical_utility"])
        )
    available = {
        "method_architecture": ["method_description"],
        "study_or_experiment_design": ["protocol"],
        "quantitative_comparison": ["comparison_records"],
        "ablation_or_sensitivity": ["ablation_records"],
        "qualitative_cases": ["cases"],
    }[role]
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_OPPORTUNITY,
        "opportunity_id": f"opp:{role}",
        "role": role,
        "reader_question": f"question for {role}",
        "claim": f"Claim for {role}.",
        "evidence_boundary": boundary,
        "priority": "high",
        "available_evidence": available,
        "must_not_imply": forbidden,
    }
    payload.update(overrides)
    return payload


def _records(role: str) -> list[dict[str, object]]:
    if role not in {"quantitative_comparison", "ablation_or_sensitivity"}:
        return []
    return [
        {
            "record_id": "r1",
            "method": "A",
            "metric": "F1",
            "value": 0.81,
            "unit": "score",
        },
        {
            "record_id": "r2",
            "method": "B",
            "metric": "F1",
            "value": 0.77,
            "unit": "score",
        },
    ]


@pytest.mark.parametrize("role", FIGURE_ROLES)
@pytest.mark.parametrize("venue", TARGET_VENUES)
def test_codesign_all_roles_both_venues(role: str, venue: str) -> None:
    result = codesign_figure(
        opportunity=_opp(role, venue),
        target_venue=venue,
        records=_records(role),
        references=[{"reference_id": "ref-1", "transferable": ["figure_role"]}],
    )
    design = validate_figure_design_contract(result["design_contract"])
    caption = validate_caption_contract(result["caption_contract"])
    panel_ids = [p["panel_id"] for p in design["panel_map"]]
    cap_ids = [p["panel_id"] for p in caption["panel_descriptions"]]
    assert panel_ids == cap_ids
    assert design["figure_id"] == caption["figure_id"]
    assert design["one_sentence_claim"] == caption["one_sentence_claim"]
    assert design["forbidden_inferences"] == caption["forbidden_claims"]
    for panel in design["panel_map"]:
        assert panel["source_bindings"]
    for panel in caption["panel_descriptions"]:
        assert panel["source_bindings"]
    assert result["render_route"] == design["render_route"]
    if design["evidence_boundary"] in {"conceptual", "planned_protocol"}:
        assert "measurement_and_units" not in caption
        assert "uncertainty_definition" not in caption
        assert "statistical_annotations" not in caption
        assert "Measurement:" not in result["caption_skeleton"]
        assert "Uncertainty/statistics:" not in result["caption_skeleton"]
    if design["evidence_boundary"] == "evidence_backed":
        assert caption.get("measurement_and_units")
        assert "Measurement:" in result["caption_skeleton"]
    if venue == "npj Digital Medicine":
        assert "clinical_deployment" in design["forbidden_inferences"]


def test_deterministic_route_for_backed_comparison() -> None:
    result = codesign_figure(
        opportunity=_opp(
            "quantitative_comparison", "Information Processing & Management"
        ),
        target_venue="Information Processing & Management",
        records=_records("quantitative_comparison"),
    )
    assert result["render_route"] == "deterministic"


def test_generative_route_for_method_architecture() -> None:
    result = codesign_figure(
        opportunity=_opp("method_architecture", "npj Digital Medicine"),
        target_venue="npj Digital Medicine",
    )
    assert result["render_route"] == "generative"


def test_keep_existing_asset_uses_external_route() -> None:
    opp = _opp("method_architecture", "npj Digital Medicine", existing_decision="keep")
    result = codesign_figure(
        opportunity=opp,
        target_venue="npj Digital Medicine",
        assets=[{"asset_id": "fig1", "path": "fig1.png"}],
    )
    assert result["render_route"] == "external_asset"
