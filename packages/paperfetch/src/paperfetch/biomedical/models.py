"""公共生物医学数据垂直切片的严格 provisional 数据契约。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间戳必须包含 UTC 偏移")
    return value


def _without_fields(value: Any, excluded_fields: frozenset[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_fields(item, excluded_fields)
            for key, item in value.items()
            if key not in excluded_fields
        }
    if isinstance(value, list):
        return [_without_fields(item, excluded_fields) for item in value]
    return value


def canonical_digest(
    value: dict[str, Any],
    *,
    excluded_fields: frozenset[str] = frozenset({"content_digest"}),
) -> str:
    payload = _without_fields(value, excluded_fields)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def attach_digest(
    value: dict[str, Any],
    *,
    excluded_fields: frozenset[str] = frozenset({"content_digest"}),
) -> dict[str, Any]:
    payload = dict(value)
    payload["content_digest"] = canonical_digest(
        payload,
        excluded_fields=excluded_fields,
    )
    return payload


class LifecycleStatus(str, Enum):
    PROVISIONAL = "provisional"
    FROZEN = "frozen"


class Availability(str, Enum):
    PRESENT = "present"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    NOT_APPLICABLE = "not_applicable"


class Derivation(str, Enum):
    SOURCE_OBSERVED = "source_observed"
    DETERMINISTIC_NORMALIZATION = "deterministic_normalization"
    CANDIDATE_MAPPING = "candidate_mapping"
    HUMAN_ASSERTED = "human_asserted"


class Verification(str, Enum):
    UNREVIEWED = "unreviewed"
    HUMAN_CONFIRMED = "human_confirmed"
    HUMAN_REJECTED = "human_rejected"


class ConflictStatus(str, Enum):
    NONE = "none"
    SOURCE_DISAGREEMENT = "source_disagreement"
    UNRESOLVED = "unresolved"


class EntityType(str, Enum):
    PROJECT = "project"
    COHORT = "cohort"
    SUBJECT_GROUP = "subject_group"
    PATIENT = "patient"
    ANIMAL = "animal"
    DONOR = "donor"
    BIOLOGICAL_SAMPLE = "biological_sample"
    CELL_SUSPENSION = "cell_suspension"
    CELL = "cell"
    NUCLEUS = "nucleus"
    LIBRARY = "library"
    SEQUENCING_RUN = "sequencing_run"
    DATA_FILE = "data_file"


class RelationType(str, Enum):
    DERIVED_FROM = "derived_from"
    SPLIT_FROM = "split_from"
    POOLED_FROM = "pooled_from"
    PAIRED_WITH = "paired_with"
    NESTED_WITHIN = "nested_within"
    TECHNICAL_REPLICATION_OF = "technical_replication_of"
    MEASURED_BY = "measured_by"


class IndependenceStatus(str, Enum):
    CONFIRMED = "confirmed"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    UNKNOWN = "unknown"
    NOT_INDEPENDENT = "not_independent"


class ArtifactAvailability(str, Enum):
    LOCAL_VERIFIED = "local_verified"
    LOCAL_UNVERIFIED = "local_unverified"
    REMOTE_AVAILABLE = "remote_available"
    MISSING = "missing"
    UNKNOWN = "unknown"


class OperationSignal(str, Enum):
    ALLOWED = "allowed"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"
    NOT_ASSESSABLE = "not_assessable"


class RequirementStatus(str, Enum):
    SATISFIED = "satisfied"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class FieldAssertion(StrictModel):
    field_name: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    raw_value: Any = None
    normalized_value: Any = None
    normalization_system: str | None = None
    source_type: Literal[
        "geo_soft", "geo_filelist", "dataset_manifest", "human_annotation"
    ]
    source_locator: str = Field(min_length=1)
    observed_at: datetime
    availability: Availability
    derivation: Derivation
    verification: Verification = Verification.UNREVIEWED
    conflict: ConflictStatus = ConflictStatus.NONE
    requires_review: bool = False
    parser_version: str = "spc.biomedical-geo-parser.v0.1"
    terminology_version: str | None = None

    _validate_time = field_validator("observed_at")(_aware)

    @model_validator(mode="after")
    def candidate_mapping_requires_review(self) -> "FieldAssertion":
        if self.derivation == Derivation.CANDIDATE_MAPPING and not self.requires_review:
            raise ValueError("candidate_mapping 必须设置 requires_review=true")
        return self


class ExperimentalEntity(StrictModel):
    entity_id: str = Field(min_length=1, max_length=256)
    entity_type: EntityType
    label: str
    group_id: str | None = None
    aggregate_count: int | None = Field(default=None, ge=0)
    count_scope: Literal["total", "per_group", "unknown_scope"] | None = None
    source_locators: list[str] = Field(default_factory=list)


class ExperimentalRelation(StrictModel):
    relation_id: str = Field(min_length=1, max_length=256)
    source_entity_id: str
    target_entity_id: str
    relation_type: RelationType
    source_locator: str
    derivation: Derivation = Derivation.SOURCE_OBSERVED
    verification: Verification = Verification.UNREVIEWED
    conflict: ConflictStatus = ConflictStatus.NONE
    requires_review: bool = False


class ReplicationLevel(StrictModel):
    entity_type: EntityType
    total: int | None = Field(default=None, ge=0)
    per_group: dict[str, int] = Field(default_factory=dict)
    independence: IndependenceStatus
    usable_for_group_inference: bool
    reason: str
    source_locators: list[str] = Field(default_factory=list)


class ReplicationProfile(StrictModel):
    pooling_detected: bool
    subject_sample_mapping: Literal["complete", "partial", "missing", "unknown"]
    biological_group_units_recoverable: bool | None
    levels: list[ReplicationLevel]


class MeasurementDesign(StrictModel):
    modalities: list[str]
    platforms: list[str]
    assay_technologies: list[str]
    measurement_spaces: list[str]
    library_strategies: list[str]
    reference_genomes: list[str]
    feature_spaces: list[str]
    time_design: Literal[
        "paired_longitudinal",
        "cross_sectional_stage",
        "independent_time_course",
        "single_timepoint_cross_sectional",
        "unknown",
    ]


class DataArtifact(StrictModel):
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    filename: str
    kind: str
    source_url: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    local_path: str | None = None
    availability: ArtifactAvailability
    source_locator: str


class SourceArtifactSnapshot(StrictModel):
    role: Literal["geo_soft", "geo_filelist", "dataset_manifest"]
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)


class BiomedicalDatasetRecord(StrictModel):
    schema_version: Literal["spc.biomedical-dataset-record.v0.1"]
    lifecycle_status: LifecycleStatus = LifecycleStatus.PROVISIONAL
    dataset_ref: str
    source: Literal["NCBI_GEO"]
    accession: str = Field(pattern=r"^GSE[1-9][0-9]*$")
    title: str
    summary: str | None = None
    organisms: list[str]
    disease_terms: list[str]
    tissue_terms: list[str]
    field_assertions: list[FieldAssertion]
    entities: list[ExperimentalEntity]
    relations: list[ExperimentalRelation]
    replication_profile: ReplicationProfile
    measurement_design: MeasurementDesign
    artifacts: list[DataArtifact]
    unresolved_questions: list[str] = Field(default_factory=list)
    source_snapshots: list[SourceArtifactSnapshot]
    parsed_at: datetime
    content_digest: str = Field(pattern=SHA256_PATTERN)

    _validate_time = field_validator("parsed_at")(_aware)

    @model_validator(mode="after")
    def unique_entities_and_valid_relations(self) -> "BiomedicalDatasetRecord":
        identifiers = [item.entity_id for item in self.entities]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("ExperimentalEntity.entity_id 必须唯一")
        known = set(identifiers)
        for relation in self.relations:
            if (
                relation.source_entity_id not in known
                or relation.target_entity_id not in known
            ):
                raise ValueError("ExperimentalRelation 引用了不存在的实体")
        expected = canonical_digest(
            self.model_dump(mode="json"),
            excluded_fields=frozenset(
                {"content_digest", "parsed_at", "observed_at", "local_path"}
            ),
        )
        if self.content_digest != expected:
            raise ValueError("BiomedicalDatasetRecord content_digest 不一致")
        return self


class ReadinessRequirement(StrictModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    fact: str
    status: RequirementStatus
    message: str
    evidence_locators: list[str] = Field(default_factory=list)


class OperationInputReadiness(StrictModel):
    schema_version: Literal["spc.operation-input-readiness.v0.1"]
    lifecycle_status: LifecycleStatus = LifecycleStatus.PROVISIONAL
    dataset_ref: str
    record_digest: str = Field(pattern=SHA256_PATTERN)
    intended_operation: str
    operation_version: str
    policy_id: str
    policy_version: str
    policy_lifecycle: LifecycleStatus
    signal: OperationSignal
    requirements: list[ReadinessRequirement]
    limitations: list[str]
    checked_at: datetime
    content_digest: str = Field(pattern=SHA256_PATTERN)

    _validate_time = field_validator("checked_at")(_aware)

    @model_validator(mode="after")
    def verify_digest(self) -> "OperationInputReadiness":
        if self.content_digest != canonical_digest(
            self.model_dump(mode="json"),
            excluded_fields=frozenset({"content_digest", "checked_at"}),
        ):
            raise ValueError("OperationInputReadiness content_digest 不一致")
        return self


class AnalysisHandoff(StrictModel):
    schema_version: Literal["spc.analysis-handoff.v0.1"]
    lifecycle_status: LifecycleStatus = LifecycleStatus.PROVISIONAL
    dataset_ref: str
    record_digest: str = Field(pattern=SHA256_PATTERN)
    readiness_digest: str = Field(pattern=SHA256_PATTERN)
    intended_operation: str
    signal: OperationSignal
    artifacts: list[DataArtifact]
    entities: list[ExperimentalEntity]
    relations: list[ExperimentalRelation]
    replication_profile: ReplicationProfile
    measurement_design: MeasurementDesign
    limitations: list[str]
    generated_at: datetime
    content_digest: str = Field(pattern=SHA256_PATTERN)

    _validate_time = field_validator("generated_at")(_aware)

    @model_validator(mode="after")
    def verify_digest(self) -> "AnalysisHandoff":
        if self.content_digest != canonical_digest(
            self.model_dump(mode="json"),
            excluded_fields=frozenset({"content_digest", "generated_at"}),
        ):
            raise ValueError("AnalysisHandoff content_digest 不一致")
        return self
