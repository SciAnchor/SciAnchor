"""Private local dataset helpers for RH end-to-end paper-generation evals."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, TextIO

from research_harness._selfdev.delivery_protocol import REQUIRED_ARTIFACTS


E2E_PAPER_GENERATION_DATASET_SCHEMA_VERSION = "rh.e2e_paper_generation_dataset.v1"
E2E_PAPER_GENERATION_READINESS_SUMMARY_SCHEMA_VERSION = (
    "rh.e2e_paper_generation_readiness_summary.v1"
)
E2E_PAPER_GENERATION_EVAL_REPORT_SCHEMA_VERSION = (
    "rh.e2e_paper_generation_eval_report.v1"
)
E2E_PAPER_GENERATION_REPLAY_REPORT_SCHEMA_VERSION = (
    "rh.e2e_paper_generation_replay_report.v1"
)

DEFAULT_E2E_PAPER_GENERATION_DATASET_PATH = (
    Path(__file__).resolve().parents[4]
    / "packages/research_harness/tests/fixtures/writing/"
    "e2e_paper_generation_dataset.json"
)

_EXPECTED_FALSE_BOUNDARIES = (
    "uses_network",
    "uses_real_llm",
    "uses_real_zotero",
    "runs_external_provider",
    "writes_project_db",
    "adds_public_surface",
    "authorizes_submission",
)
_POSITIVE_KIND = "capability_positive"
_BLOCKER_KIND = "capability_blocker"
_POSITIVE_DECISION = "reviewable_package_ready"
_BLOCKED_DECISION = "blocked"


class E2EPaperGenerationDatasetError(ValueError):
    """Raised when the local paper-generation dataset contract is invalid."""


@dataclass(frozen=True)
class E2EPaperGenerationCase:
    case_id: str
    kind: str
    domain: str
    paper_profile: Mapping[str, Any]
    domain_writing_profile: str
    expected_decision: str
    expected_blockers: tuple[str, ...]
    external_actions: tuple[str, ...]
    artifact_states: Mapping[str, str]
    control_artifact_states: Mapping[str, str]
    evidence_inventory: Mapping[str, tuple[str, ...]]
    block_stage: str
    stage_expectations: tuple[Mapping[str, str], ...]
    result_state: str
    requested_claim_strength: str
    allowed_claim_strength: str
    venue_overlay: Mapping[str, Any]

    @property
    def is_positive(self) -> bool:
        return self.kind == _POSITIVE_KIND

    @property
    def is_blocker(self) -> bool:
        return self.kind == _BLOCKER_KIND

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "case_id": self.case_id,
            "kind": self.kind,
            "domain": self.domain,
            "paper_profile": _thaw_json(self.paper_profile),
            "domain_writing_profile": self.domain_writing_profile,
            "artifact_states": dict(self.artifact_states),
            "evidence_inventory": _thaw_json(self.evidence_inventory),
            "expected_decision": self.expected_decision,
            "expected_blockers": list(self.expected_blockers),
            "external_actions": list(self.external_actions),
        }
        if self.control_artifact_states:
            payload["control_artifact_states"] = dict(self.control_artifact_states)
        if self.block_stage:
            payload["block_stage"] = self.block_stage
        if self.stage_expectations:
            payload["stage_expectations"] = _thaw_json(self.stage_expectations)
        if self.result_state:
            payload["result_state"] = self.result_state
        if self.requested_claim_strength:
            payload["requested_claim_strength"] = self.requested_claim_strength
        if self.allowed_claim_strength:
            payload["allowed_claim_strength"] = self.allowed_claim_strength
        if self.venue_overlay:
            payload["venue_overlay"] = _thaw_json(self.venue_overlay)
        return payload


@dataclass(frozen=True)
class E2EPaperGenerationReadinessSummary:
    dataset_schema_version: str
    status: str
    case_count: int
    positive_case_count: int
    blocker_case_count: int
    stage_count: int
    required_artifact_count: int
    required_control_artifact_count: int
    grader_names: tuple[str, ...]
    positive_case_ids: tuple[str, ...]
    blocker_case_ids: tuple[str, ...]
    external_actions_present: bool
    missing: tuple[str, ...]
    schema_version: str = E2E_PAPER_GENERATION_READINESS_SUMMARY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class E2EPaperGenerationGraderResult:
    name: str
    status: str
    checked_case_ids: tuple[str, ...]
    failures: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class E2EPaperGenerationEvalReport:
    dataset_schema_version: str
    status: str
    case_count: int
    grader_count: int
    passed_grader_count: int
    failed_grader_count: int
    grader_results: tuple[E2EPaperGenerationGraderResult, ...]
    schema_version: str = E2E_PAPER_GENERATION_EVAL_REPORT_SCHEMA_VERSION

    @property
    def failed_grader_names(self) -> tuple[str, ...]:
        return tuple(result.name for result in self.grader_results if not result.passed)

    def result_by_name(self, name: str) -> E2EPaperGenerationGraderResult:
        for result in self.grader_results:
            if result.name == name:
                return result
        raise KeyError(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_schema_version": self.dataset_schema_version,
            "status": self.status,
            "summary": {
                "ready_for_private_eval": self.status == "pass",
                "case_count": self.case_count,
                "grader_count": self.grader_count,
                "passed_grader_count": self.passed_grader_count,
                "failed_grader_count": self.failed_grader_count,
                "failed_grader_names": list(self.failed_grader_names),
            },
            "grader_results": [result.to_dict() for result in self.grader_results],
        }


@dataclass(frozen=True)
class E2EPaperGenerationReplayReport:
    dataset_schema_version: str
    status: str
    decision: str
    readiness_summary: E2EPaperGenerationReadinessSummary
    eval_report: E2EPaperGenerationEvalReport
    blockers: tuple[str, ...]
    next_actions: tuple[str, ...]
    schema_version: str = E2E_PAPER_GENERATION_REPLAY_REPORT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_schema_version": self.dataset_schema_version,
            "status": self.status,
            "decision": self.decision,
            "readiness_summary": self.readiness_summary.to_dict(),
            "eval_report": self.eval_report.to_dict(),
            "blockers": list(self.blockers),
            "next_actions": list(self.next_actions),
        }


@dataclass(frozen=True)
class E2EPaperGenerationDataset:
    schema_version: str
    status: str
    purpose: str
    boundaries: Mapping[str, bool]
    stage_order: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    required_control_artifacts: tuple[str, ...]
    graders: tuple[Mapping[str, str], ...]
    cases: tuple[E2EPaperGenerationCase, ...]
    source_path: str

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases)

    @property
    def positive_case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases if case.is_positive)

    @property
    def blocker_case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases if case.is_blocker)

    @property
    def grader_names(self) -> tuple[str, ...]:
        return tuple(str(grader["name"]) for grader in self.graders)

    def case_by_id(self, case_id: str) -> E2EPaperGenerationCase:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(case_id)

    def readiness_summary(self) -> E2EPaperGenerationReadinessSummary:
        missing = _dataset_missing_parts(self)
        external_actions_present = any(case.external_actions for case in self.cases)
        return E2EPaperGenerationReadinessSummary(
            dataset_schema_version=self.schema_version,
            status="ready_for_private_eval" if not missing else "needs_repair",
            case_count=len(self.cases),
            positive_case_count=len(self.positive_case_ids),
            blocker_case_count=len(self.blocker_case_ids),
            stage_count=len(self.stage_order),
            required_artifact_count=len(self.required_artifacts),
            required_control_artifact_count=len(self.required_control_artifacts),
            grader_names=self.grader_names,
            positive_case_ids=self.positive_case_ids,
            blocker_case_ids=self.blocker_case_ids,
            external_actions_present=external_actions_present,
            missing=missing,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "purpose": self.purpose,
            "boundaries": dict(self.boundaries),
            "stage_order": list(self.stage_order),
            "required_artifacts": list(self.required_artifacts),
            "required_control_artifacts": list(self.required_control_artifacts),
            "graders": _thaw_json(self.graders),
            "cases": [case.to_dict() for case in self.cases],
        }


def load_default_e2e_paper_generation_dataset() -> E2EPaperGenerationDataset:
    return load_e2e_paper_generation_dataset(DEFAULT_E2E_PAPER_GENERATION_DATASET_PATH)


def evaluate_default_e2e_paper_generation_dataset() -> E2EPaperGenerationEvalReport:
    return evaluate_e2e_paper_generation_dataset(
        load_default_e2e_paper_generation_dataset()
    )


def build_default_e2e_paper_generation_replay_report() -> (
    E2EPaperGenerationReplayReport
):
    return build_e2e_paper_generation_replay_report(
        load_default_e2e_paper_generation_dataset()
    )


def build_e2e_paper_generation_replay_report(
    dataset: E2EPaperGenerationDataset,
) -> E2EPaperGenerationReplayReport:
    readiness_summary = dataset.readiness_summary()
    eval_report = evaluate_e2e_paper_generation_dataset(dataset)
    blockers = tuple(f"missing:{item}" for item in readiness_summary.missing) + tuple(
        f"failed_grader:{name}" for name in eval_report.failed_grader_names
    )
    status = "pass" if not blockers else "fail"
    return E2EPaperGenerationReplayReport(
        dataset_schema_version=dataset.schema_version,
        status=status,
        decision=(
            "ready_for_private_replay"
            if status == "pass"
            else "blocked_by_private_eval"
        ),
        readiness_summary=readiness_summary,
        eval_report=eval_report,
        blockers=blockers,
        next_actions=(
            ("LG78E_PRIVATE_REPLAY_HARNESS",)
            if status == "pass"
            else ("repair_failing_fixture_or_grader",)
        ),
    )


def run_e2e_paper_generation_replay_harness(
    *, dataset_path: str | Path | None = None
) -> dict[str, Any]:
    dataset = (
        load_default_e2e_paper_generation_dataset()
        if dataset_path is None
        else load_e2e_paper_generation_dataset(dataset_path)
    )
    return build_e2e_paper_generation_replay_report(dataset).to_dict()


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Private RH self-development replay harness for the local "
            "end-to-end paper-generation fixture."
        )
    )
    parser.add_argument(
        "--dataset",
        help="Optional path to an rh.e2e_paper_generation_dataset.v1 JSON fixture.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON instead of indented JSON.",
    )
    args = parser.parse_args(argv)

    payload = run_e2e_paper_generation_replay_harness(dataset_path=args.dataset)
    output = stdout if stdout is not None else sys.stdout
    json.dump(
        payload,
        output,
        indent=None if args.compact else 2,
        sort_keys=True,
    )
    output.write("\n")
    return 0 if payload["status"] == "pass" else 1


def evaluate_e2e_paper_generation_dataset(
    dataset: E2EPaperGenerationDataset,
) -> E2EPaperGenerationEvalReport:
    results = tuple(_evaluate_grader(dataset, name) for name in dataset.grader_names)
    passed_count = sum(1 for result in results if result.passed)
    failed_count = len(results) - passed_count
    return E2EPaperGenerationEvalReport(
        dataset_schema_version=dataset.schema_version,
        status="pass" if failed_count == 0 else "fail",
        case_count=len(dataset.cases),
        grader_count=len(results),
        passed_grader_count=passed_count,
        failed_grader_count=failed_count,
        grader_results=results,
    )


def load_e2e_paper_generation_dataset(
    path: str | Path,
) -> E2EPaperGenerationDataset:
    dataset_path = Path(path)
    payload = _load_json_mapping(dataset_path)
    return _parse_dataset(payload, source_path=str(dataset_path))


def _evaluate_grader(
    dataset: E2EPaperGenerationDataset, name: str
) -> E2EPaperGenerationGraderResult:
    evaluators = {
        "artifact_chain_complete": _grade_artifact_chain_complete,
        "stage_coverage_complete": _grade_stage_coverage_complete,
        "evidence_bound_claims": _grade_evidence_bound_claims,
        "domain_route_not_silent_stem": _grade_domain_route_not_silent_stem,
        "result_claim_boundary": _grade_result_claim_boundary,
        "package_readiness_boundary": _grade_package_readiness_boundary,
        "external_action_boundary": _grade_external_action_boundary,
    }
    evaluator = evaluators.get(name)
    if evaluator is None:
        return _grader_result(
            name=name,
            checked_case_ids=dataset.case_ids,
            failures=(f"unknown_grader:{name}",),
        )
    return evaluator(dataset)


def _grade_artifact_chain_complete(
    dataset: E2EPaperGenerationDataset,
) -> E2EPaperGenerationGraderResult:
    failures: list[str] = []
    for case in dataset.cases:
        if case.is_positive:
            if tuple(case.artifact_states) != dataset.required_artifacts:
                failures.append(f"{case.case_id}:artifact_chain_mismatch")
            for artifact in dataset.required_artifacts:
                if case.artifact_states.get(artifact) != "current":
                    failures.append(f"{case.case_id}:artifact_not_current:{artifact}")
        if case.is_blocker and not case.expected_blockers:
            failures.append(f"{case.case_id}:missing_blocker")
    return _grader_result(
        name="artifact_chain_complete",
        checked_case_ids=dataset.case_ids,
        failures=tuple(failures),
    )


def _grade_stage_coverage_complete(
    dataset: E2EPaperGenerationDataset,
) -> E2EPaperGenerationGraderResult:
    failures: list[str] = []
    for case in dataset.cases:
        if not case.is_positive:
            continue
        stages = tuple(str(item.get("stage", "")) for item in case.stage_expectations)
        if stages != dataset.stage_order:
            failures.append(f"{case.case_id}:stage_order_mismatch")
        for item in case.stage_expectations:
            if item.get("expected_status") != "pass":
                failures.append(f"{case.case_id}:nonpassing_stage:{item.get('stage')}")
    return _grader_result(
        name="stage_coverage_complete",
        checked_case_ids=dataset.positive_case_ids,
        failures=tuple(failures),
    )


def _grade_evidence_bound_claims(
    dataset: E2EPaperGenerationDataset,
) -> E2EPaperGenerationGraderResult:
    failures: list[str] = []
    for case in dataset.cases:
        inventory = case.evidence_inventory
        if case.is_positive:
            for key, label in (
                ("paper_ids", "paper_ids"),
                ("claim_ids", "claim_ids"),
                ("source_artifacts", "source_artifacts"),
            ):
                if not inventory.get(key):
                    failures.append(f"{case.case_id}:missing_positive_{label}")
            if inventory.get("weak_or_unsupported_markers"):
                failures.append(f"{case.case_id}:unexpected_weak_marker")
        if case.is_blocker and not (
            inventory.get("weak_or_unsupported_markers") or case.expected_blockers
        ):
            failures.append(f"{case.case_id}:missing_weak_or_blocker_marker")
    return _grader_result(
        name="evidence_bound_claims",
        checked_case_ids=dataset.case_ids,
        failures=tuple(failures),
    )


def _grade_domain_route_not_silent_stem(
    dataset: E2EPaperGenerationDataset,
) -> E2EPaperGenerationGraderResult:
    failures: list[str] = []
    for case in dataset.cases:
        discipline = str(case.paper_profile.get("discipline", ""))
        if case.domain == "stem":
            continue
        if discipline in {"ai", "ml", "stem"}:
            failures.append(f"{case.case_id}:silent_stem_discipline")
        if case.domain_writing_profile == "domain-writing-stem":
            failures.append(f"{case.case_id}:silent_stem_writing_profile")
    return _grader_result(
        name="domain_route_not_silent_stem",
        checked_case_ids=dataset.case_ids,
        failures=tuple(failures),
    )


def _grade_result_claim_boundary(
    dataset: E2EPaperGenerationDataset,
) -> E2EPaperGenerationGraderResult:
    failures: list[str] = []
    for case in dataset.cases:
        if not case.requested_claim_strength or not case.allowed_claim_strength:
            continue
        if case.requested_claim_strength == case.allowed_claim_strength:
            continue
        if case.expected_decision != _BLOCKED_DECISION:
            failures.append(f"{case.case_id}:overclaim_not_blocked")
        if not any(
            blocker.startswith("overclaim:") for blocker in case.expected_blockers
        ):
            failures.append(f"{case.case_id}:missing_overclaim_blocker")
    return _grader_result(
        name="result_claim_boundary",
        checked_case_ids=dataset.case_ids,
        failures=tuple(failures),
    )


def _grade_package_readiness_boundary(
    dataset: E2EPaperGenerationDataset,
) -> E2EPaperGenerationGraderResult:
    failures: list[str] = []
    required_controls = (
        "SKELETON_SOURCE_INTEGRITY_PROFILE",
        "PRESUBMISSION_SEVERITY_GATE_PROFILE",
        "VENUE_OVERLAY",
    )
    for case in dataset.cases:
        if case.is_positive:
            for control in required_controls:
                if case.control_artifact_states.get(control) != "current":
                    failures.append(f"{case.case_id}:package_control_missing:{control}")
        if case.block_stage == "PW09_REVIEW_AUDIT_AND_PUBLICATION_PACK":
            blockers = set(case.expected_blockers)
            if not any(blocker.startswith("critical:") for blocker in blockers):
                failures.append(f"{case.case_id}:missing_critical_package_blocker")
            if "missing:bib_doi_verification" not in blockers:
                failures.append(f"{case.case_id}:missing_bib_doi_blocker")
    return _grader_result(
        name="package_readiness_boundary",
        checked_case_ids=dataset.case_ids,
        failures=tuple(failures),
    )


def _grade_external_action_boundary(
    dataset: E2EPaperGenerationDataset,
) -> E2EPaperGenerationGraderResult:
    failures: list[str] = []
    for boundary, value in dataset.boundaries.items():
        if value:
            failures.append(f"boundary_enabled:{boundary}")
    for case in dataset.cases:
        if case.external_actions:
            failures.append(f"{case.case_id}:external_actions_present")
    return _grader_result(
        name="external_action_boundary",
        checked_case_ids=dataset.case_ids,
        failures=tuple(failures),
    )


def _grader_result(
    *, name: str, checked_case_ids: tuple[str, ...], failures: tuple[str, ...]
) -> E2EPaperGenerationGraderResult:
    return E2EPaperGenerationGraderResult(
        name=name,
        status="pass" if not failures else "fail",
        checked_case_ids=checked_case_ids,
        failures=failures,
        warnings=(),
    )


def _load_json_mapping(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise E2EPaperGenerationDatasetError(f"cannot read dataset: {path}") from exc
    except json.JSONDecodeError as exc:
        raise E2EPaperGenerationDatasetError(f"invalid dataset JSON: {path}") from exc
    return _require_mapping(payload, "dataset")


def _parse_dataset(
    payload: Mapping[str, Any], *, source_path: str
) -> E2EPaperGenerationDataset:
    schema_version = _string_field(payload, "schema_version", "dataset")
    if schema_version != E2E_PAPER_GENERATION_DATASET_SCHEMA_VERSION:
        raise E2EPaperGenerationDatasetError(
            f"unsupported schema_version: {schema_version}"
        )

    boundaries = _bool_mapping(payload.get("boundaries"), "boundaries")
    for key in _EXPECTED_FALSE_BOUNDARIES:
        if boundaries.get(key) is not False:
            raise E2EPaperGenerationDatasetError(f"boundary must be false: {key}")

    cases = tuple(_parse_case(raw, index) for index, raw in enumerate(_cases(payload)))
    _validate_case_ids(cases)

    dataset = E2EPaperGenerationDataset(
        schema_version=schema_version,
        status=_string_field(payload, "status", "dataset"),
        purpose=_string_field(payload, "purpose", "dataset"),
        boundaries=MappingProxyType(dict(boundaries)),
        stage_order=_string_tuple(payload.get("stage_order"), "stage_order"),
        required_artifacts=_string_tuple(
            payload.get("required_artifacts"), "required_artifacts"
        ),
        required_control_artifacts=_string_tuple(
            payload.get("required_control_artifacts"),
            "required_control_artifacts",
        ),
        graders=tuple(
            _freeze_json(_require_mapping(grader, f"graders[{index}]"))
            for index, grader in enumerate(_list_field(payload, "graders"))
        ),
        cases=cases,
        source_path=source_path,
    )
    _validate_dataset(dataset)
    return dataset


def _parse_case(raw_case: Any, index: int) -> E2EPaperGenerationCase:
    context = f"cases[{index}]"
    case = _require_mapping(raw_case, context)
    external_actions = _string_tuple(
        case.get("external_actions"), f"{context}.external_actions"
    )
    if external_actions:
        raise E2EPaperGenerationDatasetError(
            f"{context}.external_actions must be empty"
        )

    parsed = E2EPaperGenerationCase(
        case_id=_string_field(case, "case_id", context),
        kind=_string_field(case, "kind", context),
        domain=_string_field(case, "domain", context),
        paper_profile=_freeze_json(
            _require_mapping(case.get("paper_profile"), f"{context}.paper_profile")
        ),
        domain_writing_profile=_string_field(case, "domain_writing_profile", context),
        expected_decision=_string_field(case, "expected_decision", context),
        expected_blockers=_string_tuple(
            case.get("expected_blockers"), f"{context}.expected_blockers"
        ),
        external_actions=external_actions,
        artifact_states=_string_mapping(
            case.get("artifact_states"), f"{context}.artifact_states"
        ),
        control_artifact_states=_string_mapping(
            case.get("control_artifact_states", {}),
            f"{context}.control_artifact_states",
        ),
        evidence_inventory=_string_tuple_mapping(
            case.get("evidence_inventory"), f"{context}.evidence_inventory"
        ),
        block_stage=str(case.get("block_stage", "")),
        stage_expectations=tuple(
            _freeze_json(
                _require_mapping(stage, f"{context}.stage_expectations[{stage_index}]")
            )
            for stage_index, stage in enumerate(case.get("stage_expectations", ()))
        ),
        result_state=str(case.get("result_state", "")),
        requested_claim_strength=str(case.get("requested_claim_strength", "")),
        allowed_claim_strength=str(case.get("allowed_claim_strength", "")),
        venue_overlay=_freeze_json(
            _require_mapping(case.get("venue_overlay", {}), f"{context}.venue_overlay")
        ),
    )
    _validate_case(parsed, context)
    return parsed


def _validate_dataset(dataset: E2EPaperGenerationDataset) -> None:
    if dataset.status != "local_fixture_only":
        raise E2EPaperGenerationDatasetError(
            f"dataset.status must be local_fixture_only: {dataset.status}"
        )
    if tuple(REQUIRED_ARTIFACTS) != dataset.required_artifacts:
        raise E2EPaperGenerationDatasetError("required_artifacts drifted")
    if not dataset.graders:
        raise E2EPaperGenerationDatasetError("graders must not be empty")
    missing = _dataset_missing_parts(dataset)
    if missing:
        raise E2EPaperGenerationDatasetError(
            "dataset missing required parts: " + ", ".join(missing)
        )


def _validate_case(case: E2EPaperGenerationCase, context: str) -> None:
    if case.kind not in {_POSITIVE_KIND, _BLOCKER_KIND}:
        raise E2EPaperGenerationDatasetError(f"{context}.kind is unsupported")
    if case.is_positive:
        _validate_positive_case(case, context)
    if case.is_blocker:
        _validate_blocker_case(case, context)


def _validate_positive_case(case: E2EPaperGenerationCase, context: str) -> None:
    if case.expected_decision != _POSITIVE_DECISION:
        raise E2EPaperGenerationDatasetError(
            f"{context}.expected_decision must be {_POSITIVE_DECISION}"
        )
    if case.expected_blockers:
        raise E2EPaperGenerationDatasetError(
            f"{context}.expected_blockers must be empty"
        )
    if tuple(case.artifact_states) != tuple(REQUIRED_ARTIFACTS):
        raise E2EPaperGenerationDatasetError(
            f"{context}.artifact_states must cover required_artifacts"
        )
    if any(state != "current" for state in case.artifact_states.values()):
        raise E2EPaperGenerationDatasetError(
            f"{context}.artifact_states must all be current"
        )
    if not case.control_artifact_states:
        raise E2EPaperGenerationDatasetError(
            f"{context}.control_artifact_states must be present"
        )
    if not case.stage_expectations:
        raise E2EPaperGenerationDatasetError(
            f"{context}.stage_expectations must be present"
        )


def _validate_blocker_case(case: E2EPaperGenerationCase, context: str) -> None:
    if case.expected_decision != _BLOCKED_DECISION:
        raise E2EPaperGenerationDatasetError(
            f"{context}.expected_decision must be {_BLOCKED_DECISION}"
        )
    if not case.expected_blockers:
        raise E2EPaperGenerationDatasetError(
            f"{context}.expected_blockers must be present"
        )
    if not case.block_stage:
        raise E2EPaperGenerationDatasetError(f"{context}.block_stage must be present")


def _validate_case_ids(cases: tuple[E2EPaperGenerationCase, ...]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise E2EPaperGenerationDatasetError(f"duplicate case_id: {case.case_id}")
        seen.add(case.case_id)


def _dataset_missing_parts(
    dataset: E2EPaperGenerationDataset,
) -> tuple[str, ...]:
    missing: list[str] = []
    if not dataset.stage_order:
        missing.append("stage_order")
    if not dataset.required_artifacts:
        missing.append("required_artifacts")
    if not dataset.required_control_artifacts:
        missing.append("required_control_artifacts")
    if not dataset.graders:
        missing.append("graders")
    if not dataset.positive_case_ids:
        missing.append("positive_case")
    if not dataset.blocker_case_ids:
        missing.append("blocker_case")
    if any(case.external_actions for case in dataset.cases):
        missing.append("external_actions")
    return tuple(missing)


def _cases(payload: Mapping[str, Any]) -> list[Any]:
    cases = _list_field(payload, "cases")
    if not cases:
        raise E2EPaperGenerationDatasetError("cases must not be empty")
    return cases


def _list_field(payload: Mapping[str, Any], field: str) -> list[Any]:
    value = payload.get(field)
    if not isinstance(value, list):
        raise E2EPaperGenerationDatasetError(f"{field} must be a list")
    return value


def _string_field(payload: Mapping[str, Any], field: str, context: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise E2EPaperGenerationDatasetError(f"{context}.{field} must be a string")
    return value


def _require_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise E2EPaperGenerationDatasetError(f"{context} must be an object")
    return value


def _bool_mapping(value: Any, context: str) -> dict[str, bool]:
    mapping = _require_mapping(value, context)
    result: dict[str, bool] = {}
    for key, item in mapping.items():
        if not isinstance(item, bool):
            raise E2EPaperGenerationDatasetError(f"{context}.{key} must be a bool")
        result[str(key)] = item
    return result


def _string_mapping(value: Any, context: str) -> Mapping[str, str]:
    mapping = _require_mapping(value, context)
    result: dict[str, str] = {}
    for key, item in mapping.items():
        if not isinstance(item, str):
            raise E2EPaperGenerationDatasetError(f"{context}.{key} must be a string")
        result[str(key)] = item
    return MappingProxyType(result)


def _string_tuple_mapping(value: Any, context: str) -> Mapping[str, tuple[str, ...]]:
    mapping = _require_mapping(value, context)
    result: dict[str, tuple[str, ...]] = {}
    for key, item in mapping.items():
        result[str(key)] = _string_tuple(item, f"{context}.{key}")
    return MappingProxyType(result)


def _string_tuple(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise E2EPaperGenerationDatasetError(f"{context} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise E2EPaperGenerationDatasetError(f"{context}[{index}] must be a string")
        result.append(item)
    return tuple(result)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
