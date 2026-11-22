"""Private trace-shape contract for RH end-to-end paper-generation evals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from research_harness._selfdev.e2e_paper_generation import (
    E2EPaperGenerationCase,
    E2EPaperGenerationDataset,
    load_default_e2e_paper_generation_dataset,
)


E2E_PAPER_GENERATION_TRACE_SCHEMA_VERSION = "rh.e2e_paper_generation_trace.v1"
E2E_PAPER_GENERATION_TRACE_CONTRACT_SCHEMA_VERSION = (
    "rh.e2e_paper_generation_trace_shape_contract.v1"
)
E2E_PAPER_GENERATION_TRACE_REPORT_SCHEMA_VERSION = (
    "rh.e2e_paper_generation_trace_shape_report.v1"
)

_REQUIRED_RECORD_FIELDS = (
    "run",
    "context_refs",
    "spans",
    "events",
    "artifacts",
    "control_artifacts",
    "evidence_inventory",
    "final_decision",
    "external_actions",
)
_REQUIRED_EVENT_TYPES = (
    "run_started",
    "stage_completed",
    "artifact_recorded",
    "control_artifact_recorded",
    "gate_decision",
    "durable_completion",
)
_REQUIRED_SPAN_TYPES = (
    "context_selection",
    "model_call",
    "tool_call",
    "gate_check",
    "artifact_write",
    "eval_scoring",
)


@dataclass(frozen=True)
class E2EPaperGenerationTraceShapeReport:
    dataset_schema_version: str
    trace_schema_version: str
    case_id: str
    status: str
    decision: str
    checked_record_fields: tuple[str, ...]
    checked_event_types: tuple[str, ...]
    checked_span_types: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    schema_version: str = E2E_PAPER_GENERATION_TRACE_REPORT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = {
            "ready_for_private_scoring": self.status == "pass",
            "blocker_count": len(self.blockers),
            "warning_count": len(self.warnings),
        }
        return payload


def build_default_e2e_paper_generation_trace_shape_contract() -> dict[str, Any]:
    return build_e2e_paper_generation_trace_shape_contract(
        load_default_e2e_paper_generation_dataset()
    )


def build_e2e_paper_generation_trace_shape_contract(
    dataset: E2EPaperGenerationDataset,
) -> dict[str, Any]:
    return {
        "schema_version": E2E_PAPER_GENERATION_TRACE_CONTRACT_SCHEMA_VERSION,
        "dataset_schema_version": dataset.schema_version,
        "trace_schema_version": E2E_PAPER_GENERATION_TRACE_SCHEMA_VERSION,
        "dataset_case_count": len(dataset.cases),
        "public_surface": "none",
        "external_actions_allowed": False,
        "required_record_fields": list(_REQUIRED_RECORD_FIELDS),
        "required_event_types": list(_REQUIRED_EVENT_TYPES),
        "required_span_types": list(_REQUIRED_SPAN_TYPES),
        "required_stage_order": list(dataset.stage_order),
        "required_artifacts": list(dataset.required_artifacts),
        "required_control_artifacts": list(dataset.required_control_artifacts),
        "completion_rule": "durable_completion_after_artifact_and_gate_events",
        "case_outcomes": {
            case.case_id: {
                "kind": case.kind,
                "expected_decision": case.expected_decision,
                "expected_blockers": list(case.expected_blockers),
                "block_stage": case.block_stage,
            }
            for case in dataset.cases
        },
    }


def evaluate_e2e_paper_generation_trace_shape(
    dataset: E2EPaperGenerationDataset, trace: Mapping[str, Any]
) -> E2EPaperGenerationTraceShapeReport:
    blockers: list[str] = []
    case_id = str(trace.get("case_id", ""))
    case = _case_or_none(dataset, case_id)

    _check_schema(trace, blockers)
    _check_required_records(trace, blockers)
    _check_external_actions(trace, blockers)
    _check_run_record(trace, blockers)
    _check_context_refs(trace, blockers)
    _check_spans(trace, blockers)
    _check_events(dataset, trace, case, blockers)
    _check_evidence_inventory(trace, blockers)
    _check_final_decision(trace, case, blockers)

    if case is None:
        blockers.append(f"unknown_case_id:{case_id}")

    status = "pass" if not blockers else "fail"
    return E2EPaperGenerationTraceShapeReport(
        dataset_schema_version=dataset.schema_version,
        trace_schema_version=str(trace.get("schema_version", "")),
        case_id=case_id,
        status=status,
        decision=(
            "trace_shape_accepted_for_private_scoring"
            if status == "pass"
            else "blocked_by_trace_shape"
        ),
        checked_record_fields=tuple(
            field for field in _REQUIRED_RECORD_FIELDS if field in trace
        ),
        checked_event_types=tuple(sorted(_event_types(trace))),
        checked_span_types=tuple(sorted(_span_types(trace))),
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=(),
    )


def _case_or_none(
    dataset: E2EPaperGenerationDataset, case_id: str
) -> E2EPaperGenerationCase | None:
    try:
        return dataset.case_by_id(case_id)
    except KeyError:
        return None


def _check_schema(trace: Mapping[str, Any], blockers: list[str]) -> None:
    if trace.get("schema_version") != E2E_PAPER_GENERATION_TRACE_SCHEMA_VERSION:
        blockers.append("unsupported_trace_schema")


def _check_required_records(trace: Mapping[str, Any], blockers: list[str]) -> None:
    for field in _REQUIRED_RECORD_FIELDS:
        if field not in trace:
            blockers.append(f"missing_record:{field}")


def _check_external_actions(trace: Mapping[str, Any], blockers: list[str]) -> None:
    external_actions = trace.get("external_actions")
    if external_actions:
        blockers.append("external_actions_present")


def _check_run_record(trace: Mapping[str, Any], blockers: list[str]) -> None:
    run = trace.get("run")
    if not isinstance(run, Mapping):
        blockers.append("run_record_not_object")
        return
    for field in ("run_id", "origin", "status"):
        if not run.get(field):
            blockers.append(f"run_missing:{field}")


def _check_context_refs(trace: Mapping[str, Any], blockers: list[str]) -> None:
    context_refs = trace.get("context_refs")
    if not isinstance(context_refs, list) or not context_refs:
        blockers.append("missing:context_refs")


def _check_spans(trace: Mapping[str, Any], blockers: list[str]) -> None:
    span_types = _span_types(trace)
    for span_type in _REQUIRED_SPAN_TYPES:
        if span_type not in span_types:
            blockers.append(f"missing_span:{span_type}")


def _check_events(
    dataset: E2EPaperGenerationDataset,
    trace: Mapping[str, Any],
    case: E2EPaperGenerationCase | None,
    blockers: list[str],
) -> None:
    event_types = _event_types(trace)
    for event_type in ("run_started", "gate_decision"):
        if event_type not in event_types:
            blockers.append(f"missing_event:{event_type}")
    if "durable_completion" not in event_types:
        blockers.append("missing:durable_completion_event")
    if case is not None:
        _check_stage_events(dataset, trace, case, blockers)
        _check_artifact_events(dataset, trace, case, blockers)
    _check_completion_order(trace, blockers)


def _check_stage_events(
    dataset: E2EPaperGenerationDataset,
    trace: Mapping[str, Any],
    case: E2EPaperGenerationCase,
    blockers: list[str],
) -> None:
    stages = tuple(
        str(event.get("stage", ""))
        for event in _events(trace)
        if event.get("event_type") in {"stage_completed", "stage_blocked"}
    )
    expected = dataset.stage_order
    if case.is_blocker and case.block_stage in dataset.stage_order:
        block_index = dataset.stage_order.index(case.block_stage)
        expected = dataset.stage_order[: block_index + 1]
    if stages != expected:
        blockers.append(f"{case.case_id}:stage_order_mismatch")


def _check_artifact_events(
    dataset: E2EPaperGenerationDataset,
    trace: Mapping[str, Any],
    case: E2EPaperGenerationCase,
    blockers: list[str],
) -> None:
    if not case.is_positive:
        return
    artifacts = _mapping_field(trace, "artifacts")
    controls = _mapping_field(trace, "control_artifacts")
    for artifact in dataset.required_artifacts:
        if _artifact_state(artifacts, artifact) != "current":
            blockers.append(f"{case.case_id}:missing_artifact:{artifact}")
    for artifact in dataset.required_control_artifacts:
        if _artifact_state(controls, artifact) != "current":
            blockers.append(f"{case.case_id}:missing_control_artifact:{artifact}")


def _check_completion_order(trace: Mapping[str, Any], blockers: list[str]) -> None:
    events = _events(trace)
    completion_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("event_type") == "durable_completion"
    ]
    if not completion_indexes:
        return
    completion_index = completion_indexes[-1]
    prerequisite_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("event_type")
        in {"artifact_recorded", "control_artifact_recorded", "gate_decision"}
    ]
    if prerequisite_indexes and completion_index <= max(prerequisite_indexes):
        blockers.append("durable_completion_before_artifacts_or_gates")


def _check_evidence_inventory(trace: Mapping[str, Any], blockers: list[str]) -> None:
    evidence_inventory = trace.get("evidence_inventory")
    if not isinstance(evidence_inventory, Mapping):
        blockers.append("evidence_inventory_not_object")
        return
    for field in ("paper_ids", "claim_ids", "source_artifacts"):
        if field not in evidence_inventory:
            blockers.append(f"evidence_inventory_missing:{field}")


def _check_final_decision(
    trace: Mapping[str, Any],
    case: E2EPaperGenerationCase | None,
    blockers: list[str],
) -> None:
    if case is None:
        return
    if trace.get("final_decision") != case.expected_decision:
        blockers.append(f"{case.case_id}:final_decision_mismatch")


def _events(trace: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    events = trace.get("events")
    if not isinstance(events, list):
        return ()
    return tuple(event for event in events if isinstance(event, Mapping))


def _event_types(trace: Mapping[str, Any]) -> set[str]:
    return {str(event.get("event_type", "")) for event in _events(trace)}


def _span_types(trace: Mapping[str, Any]) -> set[str]:
    spans = trace.get("spans")
    if not isinstance(spans, list):
        return set()
    return {
        str(span.get("span_type", "")) for span in spans if isinstance(span, Mapping)
    }


def _mapping_field(trace: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = trace.get(field)
    return value if isinstance(value, Mapping) else {}


def _artifact_state(artifacts: Mapping[str, Any], artifact: str) -> str:
    value = artifacts.get(artifact)
    if not isinstance(value, Mapping):
        return ""
    return str(value.get("state", ""))
