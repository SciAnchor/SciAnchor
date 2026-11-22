"""UF08: caption realization and bidirectional QA."""

from __future__ import annotations

from research_harness.visualization.figure_caption_qa import (
    check_figure_caption_evidence,
    realize_caption,
)
from research_harness.visualization.figure_package_contracts import (
    SCHEMA_CAPTION,
    SCHEMA_FIGURE_DESIGN,
)


def _design(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_DESIGN,
        "figure_id": "fig:cmp",
        "role": "quantitative_comparison",
        "one_sentence_claim": "Named methods are compared on F1.",
        "evidence_boundary": "evidence_backed",
        "panel_map": [
            {"panel_id": "A", "purpose": "primary"},
            {"panel_id": "B", "purpose": "secondary"},
        ],
        "visual_encoding": [
            {
                "encoding": "color",
                "meaning": "method family",
                "values": ["blue"],
                "visual_mark": "blue",
            }
        ],
        "render_route": "deterministic",
        "target_venue": "Information Processing & Management",
    }
    payload.update(overrides)
    return payload


def _caption(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_CAPTION,
        "caption_id": "cap:fig:cmp",
        "figure_id": "fig:cmp",
        "one_sentence_claim": "Named methods are compared on F1.",
        "panel_descriptions": [
            {"panel_id": "A", "description": "Primary metric.", "required_terms": []},
            {"panel_id": "B", "description": "Secondary metric.", "required_terms": []},
        ],
        "visual_encoding": [
            {
                "visual_mark": "blue",
                "meaning": "method family",
                "source_binding": "design_contract",
            }
        ],
        "measurement_and_units": "metrics=F1; units=score",
        "caption_status": "draft",
        "abbreviations": [{"term": "AUC", "expansion": "area under the curve"}],
    }
    payload.update(overrides)
    return payload


def _records(*, n: int = 120, unit: str = "score") -> list[dict[str, object]]:
    return [
        {
            "method": "Ours",
            "metric": "F1",
            "value": 0.81,
            "unit": unit,
            "sample_size": n,
        }
    ]


def test_realize_caption_includes_panels_and_n() -> None:
    realized = realize_caption(
        caption_contract=_caption(),
        design_contract=_design(),
        records=_records(),
    )
    text = realized["caption_text"]
    assert "(A) Primary metric." in text
    assert "(B) Secondary metric." in text
    assert "n=120" in text
    assert realized["caption_contract"]["caption_status"] == "draft"


def test_missing_panel_description() -> None:
    result = check_figure_caption_evidence(
        caption_contract=_caption(
            panel_descriptions=[
                {
                    "panel_id": "A",
                    "description": "Primary metric.",
                    "required_terms": [],
                }
            ]
        ),
        caption_text="Figure. (A) Primary metric.",
        design_contract=_design(),
        records=_records(),
    )
    assert result["validation"]["status"] == "fail"
    assert "missing_panel_description:B" in str(result["validation"]["checks"])


def test_nonexistent_panel() -> None:
    result = check_figure_caption_evidence(
        caption_contract=_caption(
            panel_descriptions=[
                {
                    "panel_id": "A",
                    "description": "Primary metric.",
                    "required_terms": [],
                },
                {
                    "panel_id": "C",
                    "description": "Invented panel.",
                    "required_terms": [],
                },
            ]
        ),
        caption_text="Figure. (A) Primary. (C) Invented.",
        design_contract=_design(panel_map=[{"panel_id": "A", "purpose": "primary"}]),
        records=_records(),
    )
    assert "nonexistent_panel:C" in str(result["validation"]["checks"])
    assert result["caption_contract"]["caption_status"] == "rejected"


def test_undefined_color_marker() -> None:
    result = check_figure_caption_evidence(
        caption_contract=_caption(visual_encoding=[]),
        caption_text="Figure. (A) Primary. (B) Secondary.",
        design_contract=_design(),
        records=_records(),
        render={"encodings": [{"encoding": "color", "visual_mark": "blue"}]},
    )
    assert "undefined_encoding:blue" in str(result["validation"]["checks"])


def test_axis_unit_mismatch() -> None:
    result = check_figure_caption_evidence(
        caption_contract=_caption(measurement_and_units="metrics=F1; units=percent"),
        caption_text="Measurement: percent.",
        design_contract=_design(),
        records=_records(unit="score"),
    )
    assert "axis_unit_mismatch" in str(result["validation"]["checks"])


def test_nonexistent_significance_mark() -> None:
    result = check_figure_caption_evidence(
        caption_contract=_caption(),
        caption_text="Figure. (A) Primary. * p<0.05.",
        design_contract=_design(),
        records=_records(),
    )
    assert "nonexistent_significance_mark" in str(result["validation"]["checks"])


def test_wrong_sample_size() -> None:
    result = check_figure_caption_evidence(
        caption_contract=_caption(),
        caption_text="Figure. (A) Primary. n=12.",
        design_contract=_design(),
        records=_records(n=120),
    )
    assert "wrong_sample_size:12!=120" in str(result["validation"]["checks"])


def test_planned_observed_confusion() -> None:
    result = check_figure_caption_evidence(
        caption_contract=_caption(),
        caption_text="The protocol showed improved enrollment.",
        design_contract=_design(
            role="study_or_experiment_design",
            evidence_boundary="planned_protocol",
        ),
        records=[],
    )
    assert "planned_observed_confusion" in str(result["validation"]["checks"])


def test_external_validation_overclaim() -> None:
    result = check_figure_caption_evidence(
        caption_contract=_caption(),
        caption_text="External validation confirmed the ranking.",
        design_contract=_design(),
        records=_records(),
    )
    assert "external_validation_overclaim" in str(result["validation"]["checks"])


def test_abbreviation_mismatch() -> None:
    result = check_figure_caption_evidence(
        caption_contract=_caption(),
        caption_text="AUC (average user count) is reported.",
        design_contract=_design(),
        records=_records(),
    )
    assert "abbreviation_mismatch:AUC" in str(result["validation"]["checks"])


def test_valid_caption_passes() -> None:
    realized = realize_caption(
        caption_contract=_caption(),
        design_contract=_design(),
        records=_records(),
    )
    result = check_figure_caption_evidence(
        caption_contract=realized["caption_contract"],
        caption_text=realized["caption_text"],
        design_contract=_design(),
        records=_records(),
        render={
            "panels": [{"panel_id": "A"}, {"panel_id": "B"}],
            "encodings": [{"encoding": "color", "visual_mark": "blue"}],
        },
    )
    assert result["validation"]["status"] == "pass"
    assert result["caption_contract"]["caption_status"] == "validated"
    for check in result["validation"]["checks"]:
        assert check["execution_status"] == "completed"
        assert check["verdict"] == "pass"
