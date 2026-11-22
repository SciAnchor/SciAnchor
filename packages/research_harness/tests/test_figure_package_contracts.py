"""UF01 shape-lock tests for Figure Package contract fixtures."""

from __future__ import annotations

import copy
import json

import pytest

from research_harness.visualization.experiment_figures import canonical_chart_kind
from research_harness.visualization.figure_package_contracts import (
    SCHEMA_CAPTION,
    SCHEMA_FIGURE_DESIGN,
    SCHEMA_FIGURE_PACKAGE,
    SCHEMA_FIGURE_TASK,
    FigureContractError,
    contract_sha256,
    validate_caption_contract,
    validate_context_assessment,
    validate_figure_design_contract,
    validate_figure_opportunity,
    validate_figure_package,
    validate_figure_task,
    validate_reference_record,
    validate_validation_check,
)
from research_harness.visualization.figure_suite_planning import (
    synthesize_planned_inventory,
)


def _task(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_TASK,
        "task_id": "task-1",
        "target_venue": "npj Digital Medicine",
        "context_type": "partial_context",
        "requested_action": "create",
        "output_requirement": {
            "formats": ["pdf", "png"],
            "editable_source": False,
            "target_width": "single_column",
        },
    }
    payload.update(overrides)
    return payload


def _design(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_DESIGN,
        "figure_id": "fig:overview",
        "role": "method_architecture",
        "one_sentence_claim": "The pipeline maps inputs to a scored output.",
        "evidence_boundary": "conceptual",
        "panel_map": [{"panel_id": "A", "purpose": "overview"}],
        "render_route": "generative",
        "target_venue": "npj Digital Medicine",
    }
    payload.update(overrides)
    return payload


def _caption(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_CAPTION,
        "caption_id": "cap-1",
        "figure_id": "fig:overview",
        "one_sentence_claim": "The pipeline maps inputs to a scored output.",
        "panel_descriptions": [{"panel_id": "A", "description": "overview"}],
        "caption_status": "draft",
    }
    payload.update(overrides)
    return payload


def _package(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_PACKAGE,
        "package_id": "pkg-1",
        "task_id": "task-1",
        "figure_id": "fig:overview",
        "assets": [
            {
                "path": "figures/figure_1.pdf",
                "media_type": "application/pdf",
                "sha256": "abc",
            }
        ],
        "caption": {"text": "Overview of the method.", "contract_id": "cap-1"},
        "task": _task(),
        "design_contract": _design(),
        "caption_contract": _caption(),
        "context_assessment": {"status": "sufficient"},
        "opportunity": {
            "opportunity_id": "opp-1",
            "role": "method_architecture",
            "reader_question": "How does the method work?",
            "claim": "A named pipeline scores the input.",
            "evidence_boundary": "conceptual",
            "priority": "high",
        },
        "reference_records": [
            {"reference_id": "ref-1", "rights_status": "internal_retrieval"}
        ],
        "validation": {
            "status": "review_pending",
            "checks": [
                {
                    "check_id": "caption_panel_mapping",
                    "execution_status": "completed",
                    "verdict": "pass",
                    "severity": "minor",
                }
            ],
        },
    }
    payload.update(overrides)
    return payload


def test_json_round_trip_and_stable_hash() -> None:
    validated = validate_figure_package(_package())
    dumped = json.loads(json.dumps(validated))
    again = validate_figure_package(dumped)
    assert again["figure_id"] == "fig:overview"
    assert contract_sha256(validated) == contract_sha256(again)
    reversed_keys = {key: validated[key] for key in reversed(list(validated))}
    assert contract_sha256(reversed_keys) == contract_sha256(validated)
    stamped = dict(validated)
    stamped["package_sha256"] = contract_sha256(validated)
    assert contract_sha256(stamped) == contract_sha256(validated)


def test_missing_required_field_fails_closed() -> None:
    task = _task()
    del task["task_id"]
    with pytest.raises(FigureContractError, match="task_id"):
        validate_figure_task(task)


def test_invalid_enum_fails_closed() -> None:
    with pytest.raises(FigureContractError, match="role"):
        validate_figure_opportunity(
            {
                "opportunity_id": "opp-1",
                "role": "framing",
                "reader_question": "q",
                "claim": "c",
                "evidence_boundary": "conceptual",
                "priority": "high",
            }
        )


def test_venue_alias_normalizes_ipm() -> None:
    task = validate_figure_task(
        _task(target_venue="Information Processing and Management")
    )
    assert task["target_venue"] == "Information Processing & Management"


def test_venue_conflict_fails_closed() -> None:
    payload = _package(
        design_contract=_design(target_venue="Information Processing & Management")
    )
    with pytest.raises(FigureContractError, match="venues conflict"):
        validate_figure_package(payload)


def test_unsupported_venue_fails_closed() -> None:
    with pytest.raises(FigureContractError, match="target_venue"):
        validate_figure_task(_task(target_venue="Nature"))


def test_not_run_check_cannot_pass() -> None:
    with pytest.raises(FigureContractError, match="cannot verdict pass"):
        validate_validation_check(
            {
                "check_id": "caption_panel_mapping",
                "execution_status": "not_run",
                "verdict": "pass",
            }
        )


def test_package_pass_requires_completed_checks() -> None:
    payload = _package(
        validation={
            "status": "pass",
            "checks": [
                {
                    "check_id": "caption_panel_mapping",
                    "execution_status": "not_run",
                    "verdict": None,
                }
            ],
        }
    )
    with pytest.raises(FigureContractError, match="not completed"):
        validate_figure_package(payload)


def test_caption_figure_id_must_match_package() -> None:
    payload = _package(caption_contract=_caption(figure_id="fig:other"))
    with pytest.raises(FigureContractError, match="caption_contract.figure_id"):
        validate_figure_package(payload)


def test_nested_contract_validators() -> None:
    assert validate_context_assessment({"status": "insufficient"})["status"] == (
        "insufficient"
    )
    assert validate_figure_design_contract(_design())["render_route"] == "generative"
    assert validate_caption_contract(_caption())["caption_status"] == "draft"
    assert (
        validate_reference_record({"reference_id": "r1", "rights_status": "unknown"})[
            "rights_status"
        ]
        == "unknown"
    )


def test_existing_figure_plan_and_suite_fixtures_still_load() -> None:
    assert canonical_chart_kind("grouped_bar") == "grouped_bar"
    assert canonical_chart_kind("forest_plot") == "forest"
    spec = {
        "style_profile": "stem_conference",
        "figures": [
            {
                "figure_id": "fig:main_results",
                "title": "Main results",
                "composition": "1x2",
                "caption_skeleton": "(a) benchmark; (b) ablation.",
                "panels": [
                    {"panel_id": "a", "chart": "grouped_bar", "y_label": "F1"},
                    {"panel_id": "b", "chart": "heatmap"},
                ],
            }
        ],
    }
    assert spec["figures"][0]["figure_id"] == "fig:main_results"
    cloned = copy.deepcopy(spec)
    inventory = synthesize_planned_inventory(
        records=[
            {
                "figure_type": "benchmark",
                "dataset": "DS",
                "method": "Ours",
                "metric": "F1",
                "value": 0.8,
            }
        ]
    )
    assert inventory["source"] == "explicit_records"
    assert inventory["mode"] == "observed"
    assert cloned == spec
