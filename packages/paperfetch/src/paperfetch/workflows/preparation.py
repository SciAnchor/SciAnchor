"""已注册 Workflow 资源的确定性准备流程。

准备流程只物化明确注册的公共数据集，最终就绪判定仍交给
:mod:`paperfetch.workflows.readiness`；它不执行科研 Workflow。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from paperfetch.datasets.acquisition import (
    AcquisitionBusy,
    AcquisitionConfigurationError,
    configured_dataset_concurrency,
    configured_lock_timeout,
    error_payload,
)
from paperfetch.datasets.geo import (
    GeoDataError,
    GeoDatasetStore,
    GeoLargeDownloadBlocked,
)
from paperfetch.workflows.contracts import (
    Blocker,
    HostProfile,
    ItemStatus,
    LifecycleStatus,
    ResourceStatus,
    WorkflowReady,
    attach_content_digest,
)
from paperfetch.workflows.readiness import (
    check_workflow,
    dataset_materialization_path,
)
from paperfetch.workflows.registry import WorkflowRegistryStore


@dataclass(frozen=True)
class PreparationAction:
    dataset_ref: str
    action: str
    detail: str | None = None


@dataclass(frozen=True)
class WorkflowPreparationOutcome:
    report: WorkflowReady
    actions: tuple[PreparationAction, ...]
    exit_code: int


GeoStoreFactory = Callable[..., GeoDatasetStore]


def _augment_report(report: WorkflowReady, blockers: list[Blocker]) -> WorkflowReady:
    if not blockers:
        return report
    payload = report.model_dump(mode="json", exclude_unset=True)
    existing = {
        (item["code"], item["resource_ref"], item["message"])
        for item in payload["blockers"]
    }
    for blocker in blockers:
        value = blocker.model_dump(mode="json", exclude_unset=True)
        key = (value["code"], value["resource_ref"], value["message"])
        if key not in existing:
            payload["blockers"].append(value)
            existing.add(key)
    payload["resource_status"] = ResourceStatus.BLOCKED.value
    return WorkflowReady.model_validate(attach_content_digest(payload))


def _required_artifacts_ready(requirement, result) -> bool:
    required_ids = {
        item.artifact_id for item in requirement.artifact_requirements if item.required
    }
    if not required_ids:
        return result.status == ItemStatus.READY
    by_id = {item.artifact_id: item for item in result.artifact_results}
    return all(
        artifact_id in by_id and by_id[artifact_id].status == ItemStatus.READY
        for artifact_id in required_ids
    )


def _failure_exit_code(error_class: str | None, error_code: str | None) -> int:
    if error_class in {"integrity_mismatch", "identity_mismatch"}:
        return 4
    if error_class in {"network_error", "timeout", "rate_limited", "resource_busy"}:
        return 3
    if error_code in {"stream_retries_exhausted", "download_incomplete"}:
        return 3
    return 2


def _report_exit_code(report: WorkflowReady, preparation_exit: int) -> int:
    integrity_codes = {
        "ARTIFACT_SIZE_MISMATCH",
        "ARTIFACT_SHA256_MISMATCH",
        "ENVIRONMENT_PATH_OUTSIDE_ALLOWED_ROOT",
    }
    if any(item.code in integrity_codes for item in report.blockers):
        return 4
    if preparation_exit in {3, 4}:
        return preparation_exit
    if report.resource_status in {
        ResourceStatus.READY,
        ResourceStatus.READY_WITH_OPTIONAL_MISSING,
    }:
        return 0
    return 2


def prepare_workflow(
    workflow_ref: str,
    host_profile: HostProfile,
    *,
    registry: WorkflowRegistryStore | None = None,
    verify_files: bool = False,
    mode: str = "shadow",
    allow_large: bool = False,
    max_download_gb: float = 20.0,
    dataset_concurrency: int | None = None,
    lock_timeout_seconds: float | None = None,
    geo_store_factory: GeoStoreFactory = GeoDatasetStore,
) -> WorkflowPreparationOutcome:
    """Prepare required automatic datasets and return the final readiness fact."""

    if max_download_gb <= 0:
        raise ValueError("max_download_gb 必须大于 0")
    resolved_concurrency = configured_dataset_concurrency(dataset_concurrency)
    resolved_lock_timeout = configured_lock_timeout(lock_timeout_seconds)
    store = registry or WorkflowRegistryStore()
    manifest = store.workflow(workflow_ref)
    before = check_workflow(
        workflow_ref,
        host_profile,
        registry=store,
        verify_files=False,
        mode=mode,
    )
    actions: list[PreparationAction] = []
    preparation_blockers: list[Blocker] = []
    preparation_exit = 2

    # Production preparation must never mutate resources for a provisional
    # contract. Shadow mode remains available for deterministic development.
    if mode == "production" and manifest.lifecycle_status != LifecycleStatus.FROZEN:
        return WorkflowPreparationOutcome(
            report=before,
            actions=tuple(actions),
            exit_code=_report_exit_code(before, preparation_exit),
        )

    before_datasets = {item.requirement_id: item for item in before.datasets}
    for requirement in manifest.dataset_requirements:
        definition = store.dataset(requirement.dataset_ref)
        current = before_datasets[requirement.requirement_id]

        if not requirement.required:
            actions.append(
                PreparationAction(definition.dataset_ref, "skipped_optional")
            )
            continue
        if _required_artifacts_ready(requirement, current):
            actions.append(PreparationAction(definition.dataset_ref, "reused"))
            continue

        required_artifacts = [
            item for item in requirement.artifact_requirements if item.required
        ]
        definitions = {item.artifact_id: item for item in definition.artifacts}
        missing_definitions = [
            item.artifact_id
            for item in required_artifacts
            if item.artifact_id not in definitions
        ]
        if not required_artifacts or missing_definitions:
            detail = (
                "DatasetManifest没有声明可准备的必需artifact"
                if not required_artifacts
                else "DatasetManifest缺少artifact定义: "
                + ", ".join(missing_definitions)
            )
            preparation_blockers.append(
                Blocker(
                    code="DATASET_DEFINITION_INCOMPLETE",
                    resource_ref=definition.dataset_ref,
                    message=detail,
                    remediation="先冻结必需文件名、来源、大小和SHA-256，再执行prepare",
                )
            )
            actions.append(
                PreparationAction(definition.dataset_ref, "blocked_definition", detail)
            )
            continue

        automatic = any(
            item.mode == "automatic" for item in definition.acquisition_sources
        )
        if not automatic:
            detail = "该数据集没有允许SPC自动获取的acquisition source"
            preparation_blockers.append(
                Blocker(
                    code="DATASET_MANUAL_PREPARATION_REQUIRED",
                    resource_ref=definition.dataset_ref,
                    message=detail,
                    remediation="按DatasetManifest执行人工交付，再重新运行prepare",
                )
            )
            actions.append(
                PreparationAction(definition.dataset_ref, "blocked_manual", detail)
            )
            continue
        if definition.source_identity.namespace != "geo":
            detail = (
                f"v0.1尚未实现namespace={definition.source_identity.namespace}自动准备"
            )
            preparation_blockers.append(
                Blocker(
                    code="DATASET_PREPARATION_BACKEND_UNSUPPORTED",
                    resource_ref=definition.dataset_ref,
                    message=detail,
                )
            )
            actions.append(
                PreparationAction(definition.dataset_ref, "blocked_backend", detail)
            )
            continue

        try:
            target = dataset_materialization_path(definition, host_profile)
        except ValueError as exc:
            detail = str(exc)
            preparation_blockers.append(
                Blocker(
                    code="DATASET_PATH_NOT_MAPPED",
                    resource_ref=definition.dataset_ref,
                    message=detail,
                )
            )
            actions.append(
                PreparationAction(definition.dataset_ref, "blocked_path", detail)
            )
            preparation_exit = max(preparation_exit, 4)
            continue

        accession = definition.source_identity.accession.upper()
        if target.name.upper() != accession:
            detail = (
                "GEO自动准备要求materialization目录名与accession一致: "
                f"target={target}, accession={accession}"
            )
            preparation_blockers.append(
                Blocker(
                    code="DATASET_MAPPING_INCOMPATIBLE",
                    resource_ref=definition.dataset_ref,
                    message=detail,
                )
            )
            actions.append(
                PreparationAction(definition.dataset_ref, "blocked_path", detail)
            )
            preparation_exit = max(preparation_exit, 4)
            continue

        filenames = [
            definitions[item.artifact_id].filename for item in required_artifacts
        ]
        try:
            with geo_store_factory(
                output_dir=target.parent,
                max_download_gb=max_download_gb,
                dataset_concurrency=resolved_concurrency,
                lock_timeout_seconds=resolved_lock_timeout,
            ) as geo_store:
                result = geo_store.download(
                    accession,
                    filenames=filenames,
                    allow_large=allow_large,
                )
        except GeoLargeDownloadBlocked as exc:
            detail = str(exc)
            preparation_blockers.append(
                Blocker(
                    code="DATASET_LARGE_DOWNLOAD_APPROVAL_REQUIRED",
                    resource_ref=definition.dataset_ref,
                    message=detail,
                    remediation="核对下载计划后使用--allow-large显式授权",
                )
            )
            actions.append(
                PreparationAction(definition.dataset_ref, "blocked_approval", detail)
            )
            continue
        except (
            AcquisitionBusy,
            AcquisitionConfigurationError,
            GeoDataError,
            OSError,
        ) as exc:
            failure = error_payload(exc)
            detail = failure["message"]
            failure_exit = _failure_exit_code(
                failure["error_class"],
                failure["error_code"],
            )
            preparation_exit = max(preparation_exit, failure_exit)
            preparation_blockers.append(
                Blocker(
                    code="DATASET_PREPARATION_FAILED",
                    resource_ref=definition.dataset_ref,
                    message=detail,
                    remediation="保留download_state.json和.part后重试prepare",
                )
            )
            actions.append(PreparationAction(definition.dataset_ref, "failed", detail))
            continue

        if result.get("status") != "complete":
            detail = str(result.get("last_error") or "GEO 下载未完成")
            failure_exit = _failure_exit_code(
                result.get("error_class"),
                result.get("error_code") or "download_incomplete",
            )
            preparation_exit = max(preparation_exit, failure_exit)
            preparation_blockers.append(
                Blocker(
                    code="DATASET_PREPARATION_INCOMPLETE",
                    resource_ref=definition.dataset_ref,
                    message=detail,
                    remediation="保留download_state.json和.part后重试prepare",
                )
            )
            actions.append(
                PreparationAction(definition.dataset_ref, "incomplete", detail)
            )
        else:
            actions.append(
                PreparationAction(
                    definition.dataset_ref,
                    "prepared",
                    str(Path(result.get("dataset_dir") or target)),
                )
            )

    final_report = check_workflow(
        workflow_ref,
        host_profile,
        registry=store,
        verify_files=verify_files or mode == "production",
        mode=mode,
    )
    final_report = _augment_report(final_report, preparation_blockers)
    return WorkflowPreparationOutcome(
        report=final_report,
        actions=tuple(actions),
        exit_code=_report_exit_code(final_report, preparation_exit),
    )
