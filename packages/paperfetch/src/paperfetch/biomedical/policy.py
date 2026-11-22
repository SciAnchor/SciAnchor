"""版本化外部 policy 的固定条件执行器与操作输入就绪度。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from paperfetch.biomedical.models import (
    BiomedicalDatasetRecord,
    LifecycleStatus,
    OperationInputReadiness,
    OperationSignal,
    ReadinessRequirement,
    RequirementStatus,
    attach_digest,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicyRule(_StrictModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    fact: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    operator: Literal["equals", "at_least"]
    expected: bool | int | str
    failure_signal: OperationSignal
    unknown_signal: OperationSignal = OperationSignal.NOT_ASSESSABLE
    message: str


class OperationPolicy(_StrictModel):
    operation_version: str
    rules: list[PolicyRule]


class BiomedicalPolicy(_StrictModel):
    schema_version: Literal["spc.biomedical-domain-policy.v0.1"]
    policy_id: str
    policy_version: str
    lifecycle_status: LifecycleStatus
    operations: dict[str, OperationPolicy]


def load_policy(
    value: str | Path | dict[str, Any] | BiomedicalPolicy,
) -> BiomedicalPolicy:
    if isinstance(value, BiomedicalPolicy):
        return value
    if isinstance(value, dict):
        return BiomedicalPolicy.model_validate(value)
    path = Path(value).expanduser().resolve()
    return BiomedicalPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def _fact_evidence(record: BiomedicalDatasetRecord) -> dict[str, tuple[Any, list[str]]]:
    processed = [
        item for item in record.artifacts if item.kind == "processed_expression_matrix"
    ]
    replication_locators = sorted(
        {
            locator
            for level in record.replication_profile.levels
            for locator in level.source_locators
        }
    )
    modality_locators = [
        item.source_locator
        for item in record.field_assertions
        if item.field_name in {"dataset.title", "dataset.summary"}
    ]
    artifact_locators = [item.source_locator for item in processed]
    mapping = record.replication_profile.subject_sample_mapping
    mapping_complete = (
        True if mapping == "complete" else False if mapping == "missing" else None
    )
    measurement_space_count = len(record.measurement_design.measurement_spaces)
    return {
        "single_cell_observation_available": (
            "single_cell_rna_seq" in record.measurement_design.modalities,
            modality_locators,
        ),
        "processed_expression_artifact_available": (bool(processed), artifact_locators),
        "processed_expression_artifact_local_verified": (
            bool(processed)
            and all(item.availability == "local_verified" for item in processed),
            artifact_locators,
        ),
        "pooling_before_library": (
            record.replication_profile.pooling_detected,
            replication_locators,
        ),
        "subject_sample_mapping_complete": (mapping_complete, replication_locators),
        "biological_group_units_recoverable": (
            record.replication_profile.biological_group_units_recoverable,
            replication_locators,
        ),
        "paired_longitudinal_design": (
            (
                None
                if record.measurement_design.time_design == "unknown"
                else record.measurement_design.time_design == "paired_longitudinal"
            ),
            modality_locators,
        ),
        "single_measurement_space": (
            measurement_space_count <= 1 if measurement_space_count else None,
            modality_locators,
        ),
        "independent_dataset_count": (1, [record.dataset_ref]),
    }


def _satisfied(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "equals":
        return actual == expected
    if operator == "at_least":
        return actual >= expected
    raise ValueError(f"不支持的 policy 条件算子：{operator}")


def _requirement_status(signal: OperationSignal) -> RequirementStatus:
    return {
        OperationSignal.ALLOWED: RequirementStatus.SATISFIED,
        OperationSignal.CONDITIONAL: RequirementStatus.CONDITIONAL,
        OperationSignal.BLOCKED: RequirementStatus.BLOCKED,
        OperationSignal.NOT_ASSESSABLE: RequirementStatus.UNKNOWN,
    }[signal]


def assess_operation_readiness(
    record: BiomedicalDatasetRecord,
    intended_operation: str,
    policy: str | Path | dict[str, Any] | BiomedicalPolicy,
    *,
    checked_at: datetime | None = None,
) -> OperationInputReadiness:
    """执行外部 policy；返回事实性输入信号，不推荐算法或论文角色。"""

    resolved_policy = load_policy(policy)
    operation = resolved_policy.operations.get(intended_operation)
    if operation is None:
        raise ValueError(f"policy 未定义 intended_operation：{intended_operation}")
    facts = _fact_evidence(record)
    requirements: list[ReadinessRequirement] = []
    triggered: list[OperationSignal] = []
    limitations: list[str] = []
    for rule in operation.rules:
        if rule.fact not in facts:
            raise ValueError(f"policy 引用了未知事实：{rule.fact}")
        actual, locators = facts[rule.fact]
        if actual is None:
            signal = rule.unknown_signal
        elif _satisfied(actual, rule.operator, rule.expected):
            signal = OperationSignal.ALLOWED
        else:
            signal = rule.failure_signal
        triggered.append(signal)
        status = _requirement_status(signal)
        message = (
            f"已满足：{rule.message}"
            if status == RequirementStatus.SATISFIED
            else rule.message
        )
        requirements.append(
            ReadinessRequirement(
                code=rule.code,
                fact=rule.fact,
                status=status,
                message=message,
                evidence_locators=locators,
            )
        )
        if status != RequirementStatus.SATISFIED:
            limitations.append(rule.message)
    severity = {
        OperationSignal.ALLOWED: 0,
        OperationSignal.CONDITIONAL: 1,
        OperationSignal.NOT_ASSESSABLE: 2,
        OperationSignal.BLOCKED: 3,
    }
    signal = max(triggered or [OperationSignal.ALLOWED], key=severity.__getitem__)
    checked = checked_at or datetime.now(timezone.utc)
    if checked.tzinfo is None or checked.utcoffset() is None:
        raise ValueError("checked_at 必须包含 UTC 偏移")
    payload = {
        "schema_version": "spc.operation-input-readiness.v0.1",
        "lifecycle_status": "provisional",
        "dataset_ref": record.dataset_ref,
        "record_digest": record.content_digest,
        "intended_operation": intended_operation,
        "operation_version": operation.operation_version,
        "policy_id": resolved_policy.policy_id,
        "policy_version": resolved_policy.policy_version,
        "policy_lifecycle": resolved_policy.lifecycle_status.value,
        "signal": signal.value,
        "requirements": [item.model_dump(mode="json") for item in requirements],
        "limitations": list(
            dict.fromkeys([*limitations, *record.unresolved_questions])
        ),
        "checked_at": checked.isoformat(),
    }
    return OperationInputReadiness.model_validate(
        attach_digest(
            payload,
            excluded_fields=frozenset({"content_digest", "checked_at"}),
        )
    )
