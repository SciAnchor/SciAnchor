from __future__ import annotations

import json
from typing import Any

from research_harness._selfdev.e2e_paper_generation import (
    E2EPaperGenerationDataset,
    load_default_e2e_paper_generation_dataset,
)
from research_harness._selfdev.e2e_paper_generation_trace import (
    E2E_PAPER_GENERATION_TRACE_CONTRACT_SCHEMA_VERSION,
    E2E_PAPER_GENERATION_TRACE_REPORT_SCHEMA_VERSION,
    E2E_PAPER_GENERATION_TRACE_SCHEMA_VERSION,
    build_default_e2e_paper_generation_trace_shape_contract,
    evaluate_e2e_paper_generation_trace_shape,
)


def test_trace_shape_contract_exposes_dataset_requirements() -> None:
    contract = build_default_e2e_paper_generation_trace_shape_contract()

    assert (
        contract["schema_version"] == E2E_PAPER_GENERATION_TRACE_CONTRACT_SCHEMA_VERSION
    )
    assert contract["trace_schema_version"] == E2E_PAPER_GENERATION_TRACE_SCHEMA_VERSION
    assert contract["dataset_case_count"] == 6
    assert contract["public_surface"] == "none"
    assert contract["required_stage_order"][0] == "PW01_TOPIC_AND_VENUE_CONTRACT"
    assert "durable_completion" in contract["required_event_types"]
    assert "artifact_write" in contract["required_span_types"]
    assert "context_refs" in contract["required_record_fields"]
    assert (
        contract["case_outcomes"]["biomedical_clinical_review_full_chain"][
            "expected_decision"
        ]
        == "reviewable_package_ready"
    )

    json.dumps(contract, sort_keys=True)


def test_trace_shape_report_passes_canonical_positive_trace() -> None:
    dataset = load_default_e2e_paper_generation_dataset()
    trace = _positive_trace(dataset, "social_science_education_intervention_full_chain")

    report = evaluate_e2e_paper_generation_trace_shape(dataset, trace)
    payload = report.to_dict()

    assert report.schema_version == E2E_PAPER_GENERATION_TRACE_REPORT_SCHEMA_VERSION
    assert report.status == "pass"
    assert report.decision == "trace_shape_accepted_for_private_scoring"
    assert report.blockers == ()
    assert payload["summary"]["ready_for_private_scoring"] is True
    assert "run" in payload["checked_record_fields"]
    assert "durable_completion" in payload["checked_event_types"]
    json.dumps(payload, sort_keys=True)


def test_trace_shape_report_blocks_missing_durable_completion() -> None:
    dataset = load_default_e2e_paper_generation_dataset()
    trace = _positive_trace(dataset, "stem_event_forecasting_full_chain")
    trace["events"] = [
        event
        for event in trace["events"]
        if event["event_type"] != "durable_completion"
    ]

    report = evaluate_e2e_paper_generation_trace_shape(dataset, trace)

    assert report.status == "fail"
    assert report.decision == "blocked_by_trace_shape"
    assert "missing:durable_completion_event" in report.blockers


def test_trace_shape_report_blocks_external_actions_and_stage_drift() -> None:
    dataset = load_default_e2e_paper_generation_dataset()
    trace = _positive_trace(dataset, "biomedical_clinical_review_full_chain")
    trace["external_actions"] = ["zotero_sync"]
    trace["events"] = [
        event
        for event in trace["events"]
        if event.get("stage") != "PW10_REBUTTAL_CAMERA_READY_AND_REPLAY"
    ]

    report = evaluate_e2e_paper_generation_trace_shape(dataset, trace)

    assert report.status == "fail"
    assert "external_actions_present" in report.blockers
    assert (
        "biomedical_clinical_review_full_chain:stage_order_mismatch" in report.blockers
    )


def _positive_trace(dataset: E2EPaperGenerationDataset, case_id: str) -> dict[str, Any]:
    case = dataset.case_by_id(case_id)
    events: list[dict[str, Any]] = [{"event_type": "run_started", "status": "running"}]
    events.extend(
        {"event_type": "stage_completed", "stage": stage, "status": "pass"}
        for stage in dataset.stage_order
    )
    events.extend(
        {
            "event_type": "artifact_recorded",
            "artifact": artifact,
            "state": "current",
        }
        for artifact in dataset.required_artifacts
    )
    events.extend(
        {
            "event_type": "control_artifact_recorded",
            "artifact": artifact,
            "state": "current",
        }
        for artifact in dataset.required_control_artifacts
    )
    events.append(
        {
            "event_type": "gate_decision",
            "stage": "PW09_REVIEW_AUDIT_AND_PUBLICATION_PACK",
            "decision": "allow",
        }
    )
    events.append(
        {
            "event_type": "durable_completion",
            "status": "completed",
            "decision": case.expected_decision,
        }
    )
    return {
        "schema_version": E2E_PAPER_GENERATION_TRACE_SCHEMA_VERSION,
        "case_id": case.case_id,
        "run": {
            "run_id": f"trace-{case.case_id}",
            "origin": "local_dry_run",
            "status": "completed",
        },
        "context_refs": [
            {
                "kind": "fixture",
                "ref_id": "e2e_paper_generation_dataset.json",
                "content_hash": "sha256:test-fixture",
            }
        ],
        "spans": [
            {"span_type": "context_selection", "status": "completed"},
            {"span_type": "model_call", "status": "completed"},
            {"span_type": "tool_call", "status": "completed"},
            {"span_type": "gate_check", "status": "completed"},
            {"span_type": "artifact_write", "status": "completed"},
            {"span_type": "eval_scoring", "status": "completed"},
        ],
        "events": events,
        "artifacts": {
            artifact: {
                "artifact_id": f"{case.case_id}:{artifact}",
                "state": "current",
                "content_hash": f"sha256:{artifact.lower()}",
            }
            for artifact in dataset.required_artifacts
        },
        "control_artifacts": {
            artifact: {
                "artifact_id": f"{case.case_id}:{artifact}",
                "state": "current",
                "content_hash": f"sha256:{artifact.lower()}",
            }
            for artifact in dataset.required_control_artifacts
        },
        "evidence_inventory": case.to_dict()["evidence_inventory"],
        "external_actions": [],
        "final_decision": case.expected_decision,
    }
