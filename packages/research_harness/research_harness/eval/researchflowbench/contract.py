"""ResearchFlowBench dataset contract v0.

The contract is intentionally declarative. Builders and adapters can reference
these constants without implying that the current Pilot-20 fixture is
release-grade or publication-ready.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DATASET_CONTRACT_SCHEMA_VERSION = "researchflowbench.dataset_contract.v0"

TASK_SCHEMA_VERSION = "researchflowbench.task.v0"
EXTERNAL_TASK_SCHEMA_VERSION = "researchflowbench.external_task.v0.1"
SCORE_REPORT_SCHEMA_VERSION = "researchflowbench_score_report.v0"

SPLIT_SOURCE = "source"
SPLIT_DRAFT_DEV = "draft_dev"
SPLIT_MUTATE_DEV = "mutate_dev"
SPLIT_PROMOTION_TEST = "promotion_test"
SPLIT_HELD_OUT = "held_out"

DATASET_SPLITS_V0 = (
    SPLIT_SOURCE,
    SPLIT_DRAFT_DEV,
    SPLIT_MUTATE_DEV,
    SPLIT_PROMOTION_TEST,
    SPLIT_HELD_OUT,
)

ARTIFACT_RESEARCHFLOWBENCH_TASK_PACK = "researchflowbench_task_pack"
ARTIFACT_RESEARCHFLOWBENCH_SCORE_REPORT = "researchflowbench_score_report"
ARTIFACT_CANDIDATE_ARCHIVE_PACK = "candidate_archive_pack"
ARTIFACT_CHAMPION_REGISTRY_PACK = "champion_registry_pack"

DATASET_ARTIFACT_TYPES_V0 = (
    ARTIFACT_RESEARCHFLOWBENCH_TASK_PACK,
    ARTIFACT_RESEARCHFLOWBENCH_SCORE_REPORT,
    ARTIFACT_CANDIDATE_ARCHIVE_PACK,
    ARTIFACT_CHAMPION_REGISTRY_PACK,
)

GOLD_STORAGE_PUBLIC_SAFE_SYNTHETIC = "public_safe_synthetic"
GOLD_STORAGE_REFERENCE_ONLY = "reference_only"
GOLD_STORAGE_LOCAL_ONLY = "local_only"
GOLD_STORAGE_JUDGE_ONLY = "judge_only"

GOLD_STORAGE_POLICIES_V0 = (
    GOLD_STORAGE_PUBLIC_SAFE_SYNTHETIC,
    GOLD_STORAGE_REFERENCE_ONLY,
    GOLD_STORAGE_LOCAL_ONLY,
    GOLD_STORAGE_JUDGE_ONLY,
)

LEAKAGE_POLICY_V0 = {
    "gold_blind_visible_inputs": True,
    "judge_only_hidden": ("gold_bundle.json", "judge_bundle.json"),
    "visible_manifest_required": True,
    "visible_hashes_required": True,
    "leakage_canaries_required": True,
    "external_search_default": "forbidden_in_v0",
    "hidden_gold_forbidden_in_prompts": True,
}

MINIMUM_TASK_FIELDS_V0 = (
    "schema_version",
    "benchmark_id",
    "task_id",
    "split",
    "input",
    "expected_rh_axes",
    "artifact_policy",
    "license",
    "leakage_policy",
    "archive_linkage",
)

MINIMUM_SCORE_REPORT_FIELDS_V0 = (
    "schema_version",
    "benchmark_id",
    "split",
    "scores",
    "metrics",
    "rh_axis_ids",
    "artifact_refs",
    "model_execution_performed",
)

MINIMUM_SCORE_FIELDS_V0 = (
    "task_id",
    "split",
    "metrics",
    "rh_axis_ids",
)

MINIMUM_LICENSE_FIELDS_V0 = (
    "dataset_license",
    "data_source_url",
    "redistribution_policy",
    "gold_storage_policy",
    "third_party_data_vendored",
)

MINIMUM_ARCHIVE_LINKAGE_FIELDS_V0 = (
    "benchmark_id",
    "task_id",
    "split",
    "rh_axis_ids",
    "artifact_refs",
)


@dataclass(frozen=True)
class ResearchFlowBenchLicenseContract:
    """License and redistribution metadata required for every task pack."""

    dataset_license: str
    data_source_url: str
    redistribution_policy: str
    gold_storage_policy: str
    third_party_data_vendored: bool = False
    license_review_required: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.dataset_license:
            raise ValueError("dataset_license is required")
        if not self.data_source_url:
            raise ValueError("data_source_url is required")
        if self.gold_storage_policy not in GOLD_STORAGE_POLICIES_V0:
            raise ValueError(
                f"unsupported gold_storage_policy: {self.gold_storage_policy}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchFlowBenchArchiveLinkage:
    """Minimum metadata needed to archive scores and select champions."""

    benchmark_id: str
    task_id: str
    split: str
    rh_axis_ids: tuple[str, ...]
    artifact_refs: tuple[str, ...] = ()
    candidate_id: str = ""
    champion_candidate_id: str = ""

    def __post_init__(self) -> None:
        if not self.benchmark_id:
            raise ValueError("benchmark_id is required")
        if not self.task_id:
            raise ValueError("task_id is required")
        if self.split not in DATASET_SPLITS_V0:
            raise ValueError(f"unsupported ResearchFlowBench split: {self.split}")
        if not self.rh_axis_ids:
            raise ValueError("rh_axis_ids is required")
        object.__setattr__(self, "rh_axis_ids", tuple(self.rh_axis_ids))
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "task_id": self.task_id,
            "split": self.split,
            "rh_axis_ids": list(self.rh_axis_ids),
            "artifact_refs": list(self.artifact_refs),
            "candidate_id": self.candidate_id,
            "champion_candidate_id": self.champion_candidate_id,
        }


@dataclass(frozen=True)
class ResearchFlowBenchTaskContract:
    """Canonical v0 task metadata envelope."""

    benchmark_id: str
    task_id: str
    split: str
    input: dict[str, Any]
    expected_rh_axes: tuple[str, ...]
    artifact_policy: dict[str, Any]
    license: ResearchFlowBenchLicenseContract
    leakage_policy: dict[str, Any] = field(
        default_factory=lambda: dict(LEAKAGE_POLICY_V0)
    )
    archive_linkage: ResearchFlowBenchArchiveLinkage | None = None
    schema_version: str = TASK_SCHEMA_VERSION
    task_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.split not in DATASET_SPLITS_V0:
            raise ValueError(f"unsupported ResearchFlowBench split: {self.split}")
        if not self.expected_rh_axes:
            raise ValueError("expected_rh_axes is required")
        linkage = self.archive_linkage or ResearchFlowBenchArchiveLinkage(
            benchmark_id=self.benchmark_id,
            task_id=self.task_id,
            split=self.split,
            rh_axis_ids=tuple(self.expected_rh_axes),
        )
        if linkage.benchmark_id != self.benchmark_id:
            raise ValueError("archive_linkage benchmark_id must match task")
        if linkage.task_id != self.task_id:
            raise ValueError("archive_linkage task_id must match task")
        if linkage.split != self.split:
            raise ValueError("archive_linkage split must match task")
        object.__setattr__(self, "expected_rh_axes", tuple(self.expected_rh_axes))
        object.__setattr__(self, "archive_linkage", linkage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark_id": self.benchmark_id,
            "task_id": self.task_id,
            "split": self.split,
            "task_type": self.task_type,
            "input": dict(self.input),
            "expected_rh_axes": list(self.expected_rh_axes),
            "artifact_policy": dict(self.artifact_policy),
            "license": self.license.to_dict(),
            "leakage_policy": dict(self.leakage_policy),
            "archive_linkage": self.archive_linkage.to_dict(),
            "metadata": dict(self.metadata),
        }


def dataset_contract_v0_payload() -> dict[str, Any]:
    """Return the machine-readable ResearchFlowBench dataset contract v0."""

    return {
        "schema_version": DATASET_CONTRACT_SCHEMA_VERSION,
        "task_schema": {
            "schema_version": TASK_SCHEMA_VERSION,
            "minimum_fields": MINIMUM_TASK_FIELDS_V0,
        },
        "score_schema": {
            "schema_version": SCORE_REPORT_SCHEMA_VERSION,
            "minimum_report_fields": MINIMUM_SCORE_REPORT_FIELDS_V0,
            "minimum_score_fields": MINIMUM_SCORE_FIELDS_V0,
        },
        "split_names": DATASET_SPLITS_V0,
        "artifact_types": DATASET_ARTIFACT_TYPES_V0,
        "license_fields": MINIMUM_LICENSE_FIELDS_V0,
        "gold_storage_policies": GOLD_STORAGE_POLICIES_V0,
        "leakage_policy": LEAKAGE_POLICY_V0,
        "archive_champion_linkage": {
            "minimum_fields": MINIMUM_ARCHIVE_LINKAGE_FIELDS_V0,
            "score_reports_feed": ARTIFACT_CANDIDATE_ARCHIVE_PACK,
            "promotion_outputs": ARTIFACT_CHAMPION_REGISTRY_PACK,
            "automatic_mutation_enabled": False,
        },
    }
