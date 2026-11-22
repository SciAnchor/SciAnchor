from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_harness._selfdev.e2e_paper_generation import (
    E2E_PAPER_GENERATION_DATASET_SCHEMA_VERSION,
    E2EPaperGenerationDatasetError,
    load_default_e2e_paper_generation_dataset,
    load_e2e_paper_generation_dataset,
)


FIXTURE = (
    Path(__file__).parent / "fixtures" / "writing" / "e2e_paper_generation_dataset.json"
)


def test_loader_returns_typed_dataset_and_summary() -> None:
    dataset = load_e2e_paper_generation_dataset(FIXTURE)
    summary = dataset.readiness_summary()

    assert dataset.schema_version == E2E_PAPER_GENERATION_DATASET_SCHEMA_VERSION
    assert dataset.status == "local_fixture_only"
    assert dataset.case_ids == (
        "stem_event_forecasting_full_chain",
        "social_science_education_intervention_full_chain",
        "biomedical_clinical_review_full_chain",
        "social_science_missing_source_access",
        "stem_result_overclaim",
        "biomedical_package_integrity_block",
    )
    assert dataset.positive_case_ids == (
        "stem_event_forecasting_full_chain",
        "social_science_education_intervention_full_chain",
        "biomedical_clinical_review_full_chain",
    )
    assert dataset.blocker_case_ids == (
        "social_science_missing_source_access",
        "stem_result_overclaim",
        "biomedical_package_integrity_block",
    )

    assert summary.status == "ready_for_private_eval"
    assert summary.case_count == 6
    assert summary.positive_case_count == 3
    assert summary.blocker_case_count == 3
    assert summary.stage_count == 11
    assert summary.required_artifact_count == 13
    assert summary.required_control_artifact_count == 11
    assert summary.external_actions_present is False
    assert summary.missing == ()


def test_loader_default_path_matches_fixture() -> None:
    default_dataset = load_default_e2e_paper_generation_dataset()
    explicit_dataset = load_e2e_paper_generation_dataset(FIXTURE)

    assert default_dataset.readiness_summary().to_dict() == (
        explicit_dataset.readiness_summary().to_dict()
    )


def test_loader_case_lookup_and_serialization_are_stable() -> None:
    dataset = load_e2e_paper_generation_dataset(FIXTURE)
    case = dataset.case_by_id("stem_result_overclaim")

    assert case.case_id == "stem_result_overclaim"
    assert case.block_stage == "PW04_EXPERIMENT_RESULT_INGESTION"
    assert case.expected_decision == "blocked"
    assert case.expected_blockers == (
        "overclaim:result_strength",
        "missing:ablation",
        "missing:statistical_summary",
    )
    assert case.paper_profile["discipline"] == "ai"

    serialized = dataset.to_dict()
    assert serialized["schema_version"] == E2E_PAPER_GENERATION_DATASET_SCHEMA_VERSION
    serialized_cases = {item["case_id"]: item for item in serialized["cases"]}
    assert serialized_cases["stem_result_overclaim"]["block_stage"] == (
        "PW04_EXPERIMENT_RESULT_INGESTION"
    )


def test_loader_rejects_unsupported_schema(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = {**payload, "schema_version": "rh.e2e_paper_generation_dataset.v0"}
    path = tmp_path / "bad-schema.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(E2EPaperGenerationDatasetError, match="schema_version"):
        load_e2e_paper_generation_dataset(path)


def test_loader_rejects_external_action_boundary(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["boundaries"] = {**payload["boundaries"], "uses_network": True}
    path = tmp_path / "network-boundary.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(E2EPaperGenerationDatasetError, match="uses_network"):
        load_e2e_paper_generation_dataset(path)


def test_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    duplicate = {**payload["cases"][1], "case_id": payload["cases"][0]["case_id"]}
    payload["cases"] = [payload["cases"][0], duplicate]
    path = tmp_path / "duplicate-cases.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(E2EPaperGenerationDatasetError, match="duplicate case_id"):
        load_e2e_paper_generation_dataset(path)
