"""Strict v0.1 data contracts for Workflow resource exchange.

The models intentionally describe resource facts only. Scientific execution,
quality gates, and RH authorization remain outside SPC.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
RAW_SHA256_PATTERN = r"^[0-9a-f]{64}$"
WORKFLOW_REF_PATTERN = r"^workflow:[a-z0-9][a-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9._-]*$"
ENVIRONMENT_REF_PATTERN = (
    r"^environment:[a-z0-9][a-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9._-]*$"
)
DATASET_REF_PATTERN = r"^dataset:[a-z0-9][a-z0-9._-]*:[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9._-]*$"
HOST_REF_PATTERN = r"^host:[a-z0-9][a-z0-9._-]*$"


class ContractError(ValueError):
    """Raised when a contract is malformed or has an invalid digest."""


class LifecycleStatus(str, Enum):
    PROVISIONAL = "provisional"
    FROZEN = "frozen"
    RETIRED = "retired"


class RuntimeKind(str, Enum):
    CONDA = "conda"
    EXTERNAL_MANAGED = "external_managed"


class ValidationLevel(str, Enum):
    IMPORT_PASS = "IMPORT_PASS"
    SMOKE_PASS = "SMOKE_PASS"
    REAL_PASS = "REAL_PASS"


VALIDATION_LEVEL_ORDER = {
    ValidationLevel.IMPORT_PASS: 1,
    ValidationLevel.SMOKE_PASS: 2,
    ValidationLevel.REAL_PASS: 3,
}


class ArtifactUse(str, Enum):
    EXECUTION_INPUT = "execution_input"
    AUDIT_EVIDENCE = "audit_evidence"
    OPTIONAL_METADATA = "optional_metadata"


class ReadinessEnforcement(str, Enum):
    RESOURCE_ONLY = "resource_only"
    OPERATION_ADVISORY = "operation_advisory"
    OPERATION_REQUIRED = "operation_required"


class ResourceStatus(str, Enum):
    READY = "ready"
    READY_WITH_OPTIONAL_MISSING = "ready_with_optional_missing"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"


class ItemStatus(str, Enum):
    READY = "ready"
    MISSING = "missing"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"
    OPTIONAL_MISSING = "optional_missing"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间戳必须包含 UTC 偏移")
    return value


def _aware_optional(value: datetime | None) -> datetime | None:
    return None if value is None else _aware(value)


class WorkflowSource(StrictModel):
    authority_type: Literal["static_manifest", "rh_workflow_graph", "other"]
    authority_id: str = Field(min_length=1, max_length=128)
    source_revision: str = Field(min_length=1, max_length=256)
    exported_at: datetime

    _validate_time = field_validator("exported_at")(_aware)


class EnvironmentRequirement(StrictModel):
    requirement_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    environment_ref: str = Field(pattern=ENVIRONMENT_REF_PATTERN)
    required: bool
    required_by_modules: list[str] = Field(min_length=1)
    minimum_validation_level: ValidationLevel


class ArtifactRequirement(StrictModel):
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    required: bool
    use: ArtifactUse


class DatasetRequirement(StrictModel):
    requirement_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    dataset_ref: str = Field(pattern=DATASET_REF_PATTERN)
    required: bool
    purpose_hint: str | None = Field(default=None, max_length=512)
    artifact_requirements: list[ArtifactRequirement]
    readiness_enforcement: ReadinessEnforcement


class WorkflowResourceManifest(StrictModel):
    schema_version: Literal["spc.workflow-resource-manifest.v1"]
    workflow_ref: str = Field(pattern=WORKFLOW_REF_PATTERN)
    workflow_source: WorkflowSource
    manifest_revision: int = Field(ge=1)
    lifecycle_status: LifecycleStatus
    platforms: list[str] = Field(min_length=1)
    selected_modules: list[str] = Field(min_length=1)
    environment_requirements: list[EnvironmentRequirement]
    dataset_requirements: list[DatasetRequirement]
    content_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def unique_requirement_ids(self) -> "WorkflowResourceManifest":
        for name, values in (
            ("environment", self.environment_requirements),
            ("dataset", self.dataset_requirements),
        ):
            identifiers = [item.requirement_id for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{name} requirement_id 存在重复值")
        return self


class ProbeDefinition(StrictModel):
    type: Literal[
        "executable_version",
        "python_import",
        "python_package_version",
        "r_package",
        "file_exists",
        "file_sha256",
        "conda_lock",
        "validation_ledger",
    ]
    level: ValidationLevel = ValidationLevel.IMPORT_PASS
    path: str | None = None
    executable: str | None = None
    name: str | None = None
    version_spec: str | None = None
    sha256: str | None = Field(default=None, pattern=RAW_SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("探针路径必须是相对路径，且不能包含 '..'")
        return value


class EnvironmentDefinition(StrictModel):
    schema_version: Literal["spc.environment-definition.v1"]
    environment_ref: str = Field(pattern=ENVIRONMENT_REF_PATTERN)
    lifecycle_status: LifecycleStatus
    runtime: RuntimeKind
    platforms: list[str] = Field(min_length=1)
    lock_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    external_identity: str | None = None
    probes: list[ProbeDefinition]
    content_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def external_identity_required(self) -> "EnvironmentDefinition":
        if self.runtime == RuntimeKind.EXTERNAL_MANAGED and not self.external_identity:
            raise ValueError("external_managed 环境必须提供 external_identity")
        if self.lifecycle_status == LifecycleStatus.FROZEN and not self.lock_digest:
            raise ValueError("frozen 环境必须提供 lock_digest")
        return self


class ValidationLedgerCheck(StrictModel):
    check_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    status: Literal["passed", "failed"]
    detail: str | None = Field(default=None, max_length=1024)


class ValidationLedgerEvidence(StrictModel):
    evidence_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    kind: Literal["report", "artifact", "log", "metrics", "other"]
    uri: str = Field(min_length=1, max_length=2048)
    sha256: str = Field(pattern=RAW_SHA256_PATTERN)


class EnvironmentValidationLedger(StrictModel):
    """Bound evidence that one environment passed a real Workflow run.

    A ledger is deliberately stricter than a marker file: it is bound to one
    environment lock, Workflow, execution host, covered module set, concrete
    datasets, validator revision, checks, and immutable evidence digests.
    """

    schema_version: Literal["spc.environment-validation-ledger.v1"]
    environment_ref: str = Field(pattern=ENVIRONMENT_REF_PATTERN)
    environment_lock_digest: str = Field(pattern=SHA256_PATTERN)
    workflow_ref: str = Field(pattern=WORKFLOW_REF_PATTERN)
    validation_level: ValidationLevel
    status: Literal["passed", "failed"]
    execution_host_id: str = Field(min_length=1, max_length=256)
    producer_actor: str = Field(min_length=1, max_length=128)
    validator_id: str = Field(min_length=1, max_length=256)
    validator_revision: str = Field(min_length=1, max_length=256)
    started_at: datetime
    completed_at: datetime
    covered_modules: list[str] = Field(min_length=1)
    dataset_refs: list[str]
    checks: list[ValidationLedgerCheck] = Field(min_length=1)
    evidence: list[ValidationLedgerEvidence] = Field(min_length=1)
    content_digest: str = Field(pattern=SHA256_PATTERN)

    _validate_started_at = field_validator("started_at")(_aware)
    _validate_completed_at = field_validator("completed_at")(_aware)

    @field_validator("dataset_refs")
    @classmethod
    def validate_dataset_refs(cls, value: list[str]) -> list[str]:
        for reference in value:
            if not re.fullmatch(DATASET_REF_PATTERN, reference):
                raise ValueError(f"dataset_ref 无效：{reference}")
        return value

    @model_validator(mode="after")
    def validate_evidence_semantics(self) -> "EnvironmentValidationLedger":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at 不能早于 started_at")
        if len(self.covered_modules) != len(set(self.covered_modules)):
            raise ValueError("covered_modules 存在重复值")
        if len(self.dataset_refs) != len(set(self.dataset_refs)):
            raise ValueError("dataset_refs 存在重复值")
        check_ids = [item.check_id for item in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("验证记录的 check_id 存在重复值")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("验证记录的 evidence_id 存在重复值")
        all_passed = all(item.status == "passed" for item in self.checks)
        if self.status == "passed" and not all_passed:
            raise ValueError("状态为 passed 的验证记录不能包含失败检查")
        if self.status == "failed" and all_passed:
            raise ValueError("状态为 failed 的验证记录必须至少包含一项失败检查")
        if self.validation_level == ValidationLevel.REAL_PASS and not self.dataset_refs:
            raise ValueError("REAL_PASS 验证记录必须提供具体 dataset_refs")
        return self


class DatasetSourceIdentity(StrictModel):
    namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    accession: str = Field(min_length=1, max_length=128)
    official_url: str | None = None


class DatasetSourceSnapshot(StrictModel):
    observed_at: datetime | None = None
    remote_snapshot_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)

    _validate_observed_at = field_validator("observed_at")(_aware_optional)


class DatasetArtifact(StrictModel):
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    filename: str = Field(min_length=1, max_length=255)
    kind: str = Field(min_length=1, max_length=64)
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=RAW_SHA256_PATTERN)
    source_url: str | None = None
    last_modified: datetime | None = None
    etag: str | None = None

    _validate_last_modified = field_validator("last_modified")(_aware_optional)

    @field_validator("filename")
    @classmethod
    def filename_only(cls, value: str) -> str:
        if Path(value).name != value or value in {".", ".."}:
            raise ValueError("制品 filename 不能包含路径")
        return value


class AcquisitionSource(StrictModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    mode: Literal[
        "automatic",
        "preinstalled",
        "manual_transfer",
        "controlled_access",
        "external_managed",
    ]
    priority: int = Field(ge=0)


class DatasetContentIdentity(StrictModel):
    identity_status: str = Field(min_length=1, max_length=128)
    raw_archive_member_count: int | None = Field(default=None, ge=0)
    raw_archive_member_manifest_sha256: str | None = Field(
        default=None,
        pattern=RAW_SHA256_PATTERN,
    )
    workflow_baseline_package_sha256: str | None = Field(
        default=None,
        pattern=RAW_SHA256_PATTERN,
    )
    server_wsl_package_sha256: str | None = Field(
        default=None,
        pattern=RAW_SHA256_PATTERN,
    )


class DatasetManifest(StrictModel):
    schema_version: Literal["spc.dataset-manifest.v1"]
    dataset_ref: str = Field(pattern=DATASET_REF_PATTERN)
    lifecycle_status: LifecycleStatus
    source_identity: DatasetSourceIdentity
    source_snapshot: DatasetSourceSnapshot
    artifacts: list[DatasetArtifact]
    acquisition_sources: list[AcquisitionSource] = Field(min_length=1)
    content_identity: DatasetContentIdentity
    content_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def unique_artifact_ids(self) -> "DatasetManifest":
        identifiers = [item.artifact_id for item in self.artifacts]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("artifact_id 存在重复值")
        if self.lifecycle_status == LifecycleStatus.FROZEN:
            if self.content_identity.identity_status != "verified":
                raise ValueError("frozen 数据集要求已验证的内容身份")
            if not self.source_snapshot.remote_snapshot_digest:
                raise ValueError("frozen 数据集必须提供 remote_snapshot_digest")
            incomplete = [
                item.artifact_id
                for item in self.artifacts
                if item.size_bytes is None or item.sha256 is None
            ]
            if incomplete:
                raise ValueError(
                    "frozen 数据集制品必须提供 size_bytes 和 sha256："
                    + ", ".join(incomplete)
                )
        return self


class HostProfile(StrictModel):
    schema_version: Literal["spc.host-profile.v1"]
    host_id: str = Field(pattern=HOST_REF_PATTERN)
    platform: str = Field(min_length=1, max_length=64)
    conda_executable: str | None = None
    allowed_environment_roots: list[str]
    allowed_data_roots: list[str] = Field(min_length=1)
    catalog_root: str
    environment_mappings: dict[str, str]
    dataset_mappings: dict[str, str] = Field(default_factory=dict)
    content_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("environment_mappings")
    @classmethod
    def validate_environment_mapping_keys(cls, value: dict[str, str]) -> dict[str, str]:
        for key in value:
            if not re.fullmatch(ENVIRONMENT_REF_PATTERN, key):
                raise ValueError(f"环境映射键无效：{key}")
        return value

    @field_validator("dataset_mappings")
    @classmethod
    def validate_dataset_mapping_keys(cls, value: dict[str, str]) -> dict[str, str]:
        for key in value:
            if not re.fullmatch(DATASET_REF_PATTERN, key):
                raise ValueError(f"数据集映射键无效：{key}")
        return value


class WorkflowRegistry(StrictModel):
    schema_version: Literal["spc.workflow-registry.v1"]
    workflows: dict[str, str]
    environments: dict[str, str]
    datasets: dict[str, str]
    content_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_reference_keys(self) -> "WorkflowRegistry":
        for name, mapping, pattern in (
            ("workflow", self.workflows, WORKFLOW_REF_PATTERN),
            ("environment", self.environments, ENVIRONMENT_REF_PATTERN),
            ("dataset", self.datasets, DATASET_REF_PATTERN),
        ):
            for reference in mapping:
                if not re.fullmatch(pattern, reference):
                    raise ValueError(f"{name} 注册表键无效：{reference}")
        return self


class ReportWorkflow(StrictModel):
    workflow_ref: str = Field(pattern=WORKFLOW_REF_PATTERN)
    manifest_revision: int = Field(ge=1)
    manifest_digest: str = Field(pattern=SHA256_PATTERN)


class ReportHost(StrictModel):
    host_id: str = Field(pattern=HOST_REF_PATTERN)
    platform: str
    profile_digest: str = Field(pattern=SHA256_PATTERN)


class ReportProducer(StrictModel):
    spc_version: str
    spc_git_sha: str | None = None
    producer_actor: str
    produced_at: datetime

    _validate_produced_at = field_validator("produced_at")(_aware)


class ProbeResult(StrictModel):
    type: str
    level: ValidationLevel
    status: ItemStatus
    detail: str | None = None


class Launcher(StrictModel):
    argv_prefix: list[str] = Field(min_length=1)


class EnvironmentResult(StrictModel):
    requirement_id: str
    environment_ref: str = Field(pattern=ENVIRONMENT_REF_PATTERN)
    required: bool
    status: ItemStatus
    prefix: str | None = None
    validation_level: ValidationLevel | None = None
    launcher: Launcher | None = None
    probe_results: list[ProbeResult]


class ArtifactResult(StrictModel):
    artifact_id: str
    required: bool
    status: ItemStatus
    path: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=RAW_SHA256_PATTERN)
    detail: str | None = None


class DatasetResult(StrictModel):
    requirement_id: str
    dataset_ref: str = Field(pattern=DATASET_REF_PATTERN)
    required: bool
    status: ItemStatus
    materialization_path: str | None = None
    dataset_manifest_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    artifact_results: list[ArtifactResult]


class Blocker(StrictModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    resource_ref: str
    message: str
    remediation: str | None = None


class WorkflowReady(StrictModel):
    schema_version: Literal["spc.workflow-ready.v1"]
    report_id: str
    workflow: ReportWorkflow
    contract_lifecycle: LifecycleStatus
    host: ReportHost
    producer: ReportProducer
    selected_modules: list[str]
    environments: list[EnvironmentResult]
    datasets: list[DatasetResult]
    resource_status: ResourceStatus
    blockers: list[Blocker]
    content_digest: str = Field(pattern=SHA256_PATTERN)


ContractModel = TypeVar("ContractModel", bound=BaseModel)


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        # Preserve the signed JSON surface: omitted optional fields must not be
        # inserted as nulls when a parsed contract is verified again.
        return value.model_dump(mode="json", exclude_unset=True)
    return value


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("规范 JSON 不允许 NaN 或无穷值")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_non_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_non_finite(item)


def canonical_json_bytes(value: Any, *, exclude_content_digest: bool = False) -> bytes:
    """Encode one contract using the cross-project canonical JSON rules."""

    payload = _json_value(value)
    if not isinstance(payload, Mapping):
        raise ContractError("规范契约值必须是 JSON 对象")
    normalized = dict(payload)
    if exclude_content_digest:
        normalized.pop("content_digest", None)
    _reject_non_finite(normalized)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_digest(value: Any) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(value, exclude_content_digest=True)
    ).hexdigest()
    return f"sha256:{digest}"


def attach_content_digest(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    payload.pop("content_digest", None)
    payload["content_digest"] = content_digest(payload)
    return payload


def verify_content_digest(value: Any) -> None:
    payload = _json_value(value)
    actual = str(payload.get("content_digest") or "")
    expected = content_digest(payload)
    if actual != expected:
        raise ContractError(
            f"content_digest 不一致：预期 {expected}，实际 {actual or '<缺失>'}"
        )


def load_contract(path: str | Path, model: type[ContractModel]) -> ContractModel:
    contract_path = Path(path)
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"无法读取契约 {contract_path}：{exc}") from exc
    try:
        verify_content_digest(payload)
        value = model.model_validate(payload)
    except ValueError as exc:
        raise ContractError(
            f"{contract_path} 中的 {model.__name__} 无效：{exc}"
        ) from exc
    return value


def binding_key(topic_id: Any, workflow_ref: str, host_id: str) -> str:
    """Return the v0.1 RH Artifact binding key using canonical JSON."""

    identity = {
        "topic_id": topic_id,
        "workflow_ref": workflow_ref,
        "host_id": host_id,
    }
    digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return f"sha256:{digest}"
