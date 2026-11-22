from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_harness._selfdev.e2e_paper_generation import (
    E2E_PAPER_GENERATION_DATASET_SCHEMA_VERSION,
    load_default_e2e_paper_generation_dataset,
)
from research_harness._selfdev.e2e_paper_generation_trace import (
    E2E_PAPER_GENERATION_TRACE_SCHEMA_VERSION,
    evaluate_e2e_paper_generation_trace_shape,
)


TRACE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "writing"
    / "e2e_paper_generation_trace_cases.json"
)
TRACE_CASES_SCHEMA_VERSION = "rh.e2e_paper_generation_trace_cases.v1"


def _load_trace_fixture() -> dict[str, Any]:
    return json.loads(TRACE_FIXTURE.read_text(encoding="utf-8"))


def test_trace_fixture_is_local_only_and_references_dataset_schema() -> None:
    payload = _load_trace_fixture()

    assert payload["schema_version"] == TRACE_CASES_SCHEMA_VERSION
    assert payload["status"] == "local_fixture_only"
    assert (
        payload["dataset_schema_version"] == E2E_PAPER_GENERATION_DATASET_SCHEMA_VERSION
    )
    assert payload["boundaries"] == {
        "uses_network": False,
        "uses_real_llm": False,
        "uses_real_zotero": False,
        "runs_external_provider": False,
        "writes_project_db": False,
        "adds_public_surface": False,
        "authorizes_submission": False,
    }
    assert [trace["case_id"] for trace in payload["traces"]] == [
        "social_science_education_intervention_full_chain",
        "stem_result_overclaim",
    ]
    assert all(
        trace["schema_version"] == E2E_PAPER_GENERATION_TRACE_SCHEMA_VERSION
        for trace in payload["traces"]
    )
    assert all(trace["external_actions"] == [] for trace in payload["traces"])


def test_trace_fixture_cases_pass_private_trace_shape_validator() -> None:
    dataset = load_default_e2e_paper_generation_dataset()
    payload = _load_trace_fixture()

    reports = [
        evaluate_e2e_paper_generation_trace_shape(dataset, trace)
        for trace in payload["traces"]
    ]

    assert [report.status for report in reports] == ["pass", "pass"]
    assert all(
        report.decision == "trace_shape_accepted_for_private_scoring"
        for report in reports
    )


def test_blocked_trace_fixture_stops_at_expected_stage_with_blockers() -> None:
    payload = _load_trace_fixture()
    blocked_trace = next(
        trace
        for trace in payload["traces"]
        if trace["case_id"] == "stem_result_overclaim"
    )
    stage_events = [
        event["stage"]
        for event in blocked_trace["events"]
        if event["event_type"] in {"stage_completed", "stage_blocked"}
    ]

    assert stage_events[-1] == "PW04_EXPERIMENT_RESULT_INGESTION"
    assert blocked_trace["final_decision"] == "blocked"
    assert blocked_trace["expected_blockers"] == [
        "overclaim:result_strength",
        "missing:ablation",
        "missing:statistical_summary",
    ]
