"""UF03 intake: three modes, sufficiency, inventory, top-one ranking."""

from __future__ import annotations

from research_harness.visualization.figure_intake import assess_intake
from research_harness.visualization.figure_package_contracts import (
    SCHEMA_FIGURE_TASK,
    validate_context_assessment,
    validate_figure_opportunity,
)


def _task(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_TASK,
        "task_id": "task-intake",
        "target_venue": "Information Processing & Management",
        "context_type": "full_paper",
        "requested_action": "create",
    }
    payload.update(overrides)
    return payload


def test_full_paper_without_figures_selects_top_opportunity() -> None:
    result = assess_intake(
        _task(
            paper_context={
                "claims": [{"text": "The ranker outperforms named baselines on nDCG."}],
                "method_elements": ["encoder", "ranker"],
                "records": [
                    {
                        "record_id": "r1",
                        "method": "Ours",
                        "metric": "nDCG",
                        "value": 0.42,
                    }
                ],
                "ablation_records": [
                    {
                        "record_id": "a1",
                        "setting": "no-encoder",
                        "metric": "nDCG",
                        "value": 0.31,
                    }
                ],
            }
        )
    )
    assert result["assessment"]["status"] == "sufficient"
    assert result["existing_figure_inventory"] == []
    assert result["selected_opportunity"] is not None
    assert result["selected_opportunity"]["role"] in {
        "quantitative_comparison",
        "ablation_or_sensitivity",
    }
    validate_context_assessment(result["assessment"])
    for item in result["opportunities"]:
        validate_figure_opportunity(item)
    reasons = result["selected_opportunity"]["priority_reasons"]
    assert any(r.startswith("total=") for r in reasons)
    assert any(r.startswith("venue_fit=") for r in reasons)


def test_acceptable_existing_figure_is_kept() -> None:
    result = assess_intake(
        _task(
            context_type="existing_figure",
            requested_action="diagnose",
            paper_context={"method_elements": ["encoder", "ranker"]},
            existing_assets=[
                {
                    "asset_id": "fig1",
                    "figure_id": "fig:1",
                    "role": "method_architecture",
                    "caption": "Overview of the ranking pipeline.",
                    "body_references": ["See Figure 1"],
                    "path": "fig1.png",
                    "sha256": "abc",
                    "scientific_fidelity": "pass",
                    "communicative_quality": "pass",
                }
            ],
        )
    )
    inventory = result["existing_figure_inventory"]
    assert inventory[0]["decision"] == "keep"
    assert result["assessment"]["status"] == "sufficient"
    assert result["assessment"]["allowed_scope"] == "existing_figure_keep"
    assert result["selected_opportunity"]["existing_decision"] == "keep"


def test_defective_existing_figure_is_redrawn() -> None:
    result = assess_intake(
        _task(
            context_type="existing_figure",
            requested_action="diagnose",
            paper_context={
                "records": [
                    {
                        "record_id": "r1",
                        "method": "Ours",
                        "metric": "nDCG",
                        "value": 0.42,
                    }
                ]
            },
            existing_assets=[
                {
                    "asset_id": "fig2",
                    "figure_id": "fig:2",
                    "role": "quantitative_comparison",
                    "caption": "Ours is clinically deployable and significant.",
                    "body_references": ["Figure 2"],
                    "path": "fig2.png",
                    "defects": ["claim_exceeds_evidence", "numeric_not_from_records"],
                    "scientific_fidelity": "fail",
                }
            ],
        )
    )
    assert result["existing_figure_inventory"][0]["decision"] == "redraw"
    assert result["selected_opportunity"]["existing_decision"] == "redraw"
    assert result["assessment"]["status"] in {"sufficient", "partially_sufficient"}


def test_partial_method_context_narrows_scope() -> None:
    result = assess_intake(
        _task(
            context_type="partial_context",
            target_venue="npj Digital Medicine",
            paper_context={
                "method_elements": ["intake", "encoder", "risk head"],
                "method_text": "A three-stage pipeline scores imaging studies.",
            },
        )
    )
    assert result["assessment"]["status"] == "partially_sufficient"
    assert result["assessment"]["allowed_scope"].startswith("partial:")
    assert result["selected_opportunity"]["role"] == "method_architecture"
    assert result["selected_opportunity"]["evidence_boundary"] == "conceptual"
    assert "observed_result" in result["selected_opportunity"]["must_not_imply"]
    assert "clinical_deployment" in result["selected_opportunity"]["must_not_imply"]


def test_partial_result_context_ranks_comparison() -> None:
    result = assess_intake(
        _task(
            context_type="partial_context",
            paper_context={
                "records": [
                    {"record_id": "r1", "method": "A", "metric": "F1", "value": 0.81},
                    {"record_id": "r2", "method": "B", "metric": "F1", "value": 0.77},
                ]
            },
        )
    )
    assert result["assessment"]["status"] == "partially_sufficient"
    assert result["selected_opportunity"]["role"] == "quantitative_comparison"
    assert result["selected_opportunity"]["evidence_boundary"] == "evidence_backed"
    assert "comparison_records" in result["selected_opportunity"]["available_evidence"]


def test_decisive_missing_information_asks_one_question() -> None:
    result = assess_intake(_task(paper_context={}))
    assert result["assessment"]["status"] == "insufficient"
    assert result["selected_opportunity"] is None
    assert result["assessment"]["question"]
    assert result["assessment"]["allowed_scope"] == "none"
    assert result["assessment"]["missing_decisive_information"]


def test_missing_asset_without_caption_requests_information() -> None:
    result = assess_intake(
        _task(
            context_type="existing_figure",
            requested_action="diagnose",
            existing_assets=[{"asset_id": "blank", "figure_id": "fig:x"}],
        )
    )
    assert result["existing_figure_inventory"][0]["decision"] == "request_information"
    assert result["assessment"]["status"] == "insufficient"
    assert result["selected_opportunity"] is None
