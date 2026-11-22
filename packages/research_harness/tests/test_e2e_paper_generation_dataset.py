from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_harness._selfdev.delivery_protocol import REQUIRED_ARTIFACTS


FIXTURE = (
    Path(__file__).parent / "fixtures" / "writing" / "e2e_paper_generation_dataset.json"
)

EXPECTED_STAGE_ORDER = (
    "PW01_TOPIC_AND_VENUE_CONTRACT",
    "PW02_EVIDENCE_ACQUISITION_AND_READING",
    "PW03_GAP_BASELINE_NOVELTY_VALIDATION",
    "PW04_EXPERIMENT_RESULT_INGESTION",
    "PW05_PAPER_PLAN_AND_STORYLINE",
    "PW06_SECTION_DRAFTING_AND_REVISION",
    "PW06B_SKELETON_SOURCE_AND_CITATION_INTEGRITY",
    "PW07_FIGURE_TABLE_AND_ASSET_QUALITY",
    "PW08_LATEX_CITATION_AND_FINAL_BUNDLE",
    "PW09_REVIEW_AUDIT_AND_PUBLICATION_PACK",
    "PW10_REBUTTAL_CAMERA_READY_AND_REPLAY",
)

EXPECTED_CONTROL_ARTIFACTS = {
    "PAPER_PROFILE",
    "DOMAIN_WRITING_PROFILE",
    "DOMAIN_METHOD_SEARCH_PROFILE",
    "EVALUATION_GATE_PROFILE",
    "PROBLEM_ANCHOR",
    "EXPERIMENT_GROUNDING_PROFILE",
    "RESULT_TO_CLAIM_ANALYSIS_PROFILE",
    "SKELETON_SOURCE_INTEGRITY_PROFILE",
    "PRESUBMISSION_SEVERITY_GATE_PROFILE",
    "REBUTTAL_READINESS_GATE_PROFILE",
    "VENUE_OVERLAY",
}


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_dataset_is_local_only_and_deterministic() -> None:
    dataset = _load_fixture()

    assert dataset["schema_version"] == "rh.e2e_paper_generation_dataset.v1"
    assert dataset["status"] == "local_fixture_only"
    assert dataset["stage_order"] == list(EXPECTED_STAGE_ORDER)
    assert set(dataset["required_artifacts"]) == set(REQUIRED_ARTIFACTS)
    assert set(dataset["required_control_artifacts"]) == EXPECTED_CONTROL_ARTIFACTS

    assert dataset["boundaries"] == {
        "uses_network": False,
        "uses_real_llm": False,
        "uses_real_zotero": False,
        "runs_external_provider": False,
        "writes_project_db": False,
        "adds_public_surface": False,
        "authorizes_submission": False,
    }

    assert dataset["graders"]
    assert all(grader["type"] == "code" for grader in dataset["graders"])


def test_positive_case_covers_full_pipeline_and_artifact_chain() -> None:
    dataset = _load_fixture()
    positive_cases = [
        case for case in dataset["cases"] if case["kind"] == "capability_positive"
    ]

    assert len(positive_cases) == 3
    for case in positive_cases:
        assert case["expected_decision"] == "reviewable_package_ready"
        assert case["expected_blockers"] == []
        assert case["external_actions"] == []
        assert set(case["artifact_states"]) == set(REQUIRED_ARTIFACTS)
        assert all(state == "current" for state in case["artifact_states"].values())
        assert set(case["control_artifact_states"]) == EXPECTED_CONTROL_ARTIFACTS
        assert all(
            state == "current" for state in case["control_artifact_states"].values()
        )
        assert [item["stage"] for item in case["stage_expectations"]] == list(
            EXPECTED_STAGE_ORDER
        )
        assert all(
            item["expected_status"] == "pass" for item in case["stage_expectations"]
        )


def test_blocker_cases_cover_evidence_result_and_package_boundaries() -> None:
    dataset = _load_fixture()
    blockers = {
        case["case_id"]: case
        for case in dataset["cases"]
        if case["kind"] == "capability_blocker"
    }

    assert {
        "social_science_missing_source_access",
        "stem_result_overclaim",
        "biomedical_package_integrity_block",
    } <= set(blockers)

    assert (
        blockers["social_science_missing_source_access"]["block_stage"]
        == "PW02_EVIDENCE_ACQUISITION_AND_READING"
    )
    assert (
        blockers["stem_result_overclaim"]["block_stage"]
        == "PW04_EXPERIMENT_RESULT_INGESTION"
    )
    assert (
        blockers["biomedical_package_integrity_block"]["block_stage"]
        == "PW09_REVIEW_AUDIT_AND_PUBLICATION_PACK"
    )

    for case in blockers.values():
        assert case["expected_decision"] == "blocked"
        assert case["expected_blockers"]
        assert case["external_actions"] == []


def test_non_stem_cases_prevent_silent_stem_defaults() -> None:
    dataset = _load_fixture()
    non_stem_cases = [case for case in dataset["cases"] if case["domain"] != "stem"]

    assert non_stem_cases
    for case in non_stem_cases:
        assert case["paper_profile"]["discipline"] not in {"ai", "ml", "stem"}
        assert case["domain_writing_profile"] != "domain-writing-stem"
        assert case["paper_profile"]["reporting_map"]
        assert case["paper_profile"]["evidence_rule"]


def test_every_case_has_evidence_inventory_and_no_external_actions() -> None:
    dataset = _load_fixture()

    for case in dataset["cases"]:
        inventory = case["evidence_inventory"]
        assert set(inventory) == {
            "paper_ids",
            "claim_ids",
            "result_artifacts",
            "source_artifacts",
            "weak_or_unsupported_markers",
        }
        assert case["external_actions"] == []
        if case["expected_decision"] == "reviewable_package_ready":
            assert inventory["paper_ids"]
            assert inventory["claim_ids"]
            assert inventory["source_artifacts"]
        else:
            assert case["expected_blockers"]
