from __future__ import annotations

import json
from pathlib import Path

from research_harness._selfdev.e2e_paper_generation import (
    E2E_PAPER_GENERATION_EVAL_REPORT_SCHEMA_VERSION,
    evaluate_default_e2e_paper_generation_dataset,
    evaluate_e2e_paper_generation_dataset,
    load_e2e_paper_generation_dataset,
)


FIXTURE = (
    Path(__file__).parent / "fixtures" / "writing" / "e2e_paper_generation_dataset.json"
)


def test_evaluator_passes_canonical_dataset() -> None:
    report = evaluate_default_e2e_paper_generation_dataset()

    assert report.schema_version == E2E_PAPER_GENERATION_EVAL_REPORT_SCHEMA_VERSION
    assert report.status == "pass"
    assert report.case_count == 6
    assert report.grader_count == 7
    assert report.passed_grader_count == 7
    assert report.failed_grader_count == 0
    assert report.failed_grader_names == ()
    assert all(result.status == "pass" for result in report.grader_results)

    serialized = report.to_dict()
    assert serialized["status"] == "pass"
    assert serialized["summary"]["ready_for_private_eval"] is True
    assert serialized["grader_results"][0]["name"] == "artifact_chain_complete"


def test_evaluator_detects_positive_case_evidence_drift(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["evidence_inventory"] = {
        **payload["cases"][0]["evidence_inventory"],
        "paper_ids": [],
    }
    path = tmp_path / "missing-positive-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_e2e_paper_generation_dataset(
        load_e2e_paper_generation_dataset(path)
    )

    assert report.status == "fail"
    assert "evidence_bound_claims" in report.failed_grader_names
    failed = report.result_by_name("evidence_bound_claims")
    assert failed.status == "fail"
    assert "stem_event_forecasting_full_chain:missing_positive_paper_ids" in (
        failed.failures
    )


def test_evaluator_detects_stage_coverage_drift(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["stage_expectations"] = payload["cases"][0][
        "stage_expectations"
    ][:-1]
    path = tmp_path / "stage-drift.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_e2e_paper_generation_dataset(
        load_e2e_paper_generation_dataset(path)
    )

    assert report.status == "fail"
    assert "stage_coverage_complete" in report.failed_grader_names
    failed = report.result_by_name("stage_coverage_complete")
    assert "stem_event_forecasting_full_chain:stage_order_mismatch" in (failed.failures)


def test_evaluator_detects_result_overclaim_boundary_drift(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    target_index = next(
        index
        for index, case in enumerate(payload["cases"])
        if case["case_id"] == "stem_result_overclaim"
    )
    payload["cases"][target_index] = {
        **payload["cases"][target_index],
        "expected_blockers": ["missing:ablation", "missing:statistical_summary"],
    }
    path = tmp_path / "overclaim-drift.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_e2e_paper_generation_dataset(
        load_e2e_paper_generation_dataset(path)
    )

    assert report.status == "fail"
    assert "result_claim_boundary" in report.failed_grader_names
    failed = report.result_by_name("result_claim_boundary")
    assert "stem_result_overclaim:missing_overclaim_blocker" in failed.failures
