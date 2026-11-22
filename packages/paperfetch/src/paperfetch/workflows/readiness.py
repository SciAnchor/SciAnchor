"""Deterministic Workflow resource checks for the v0.1 file contract."""

from __future__ import annotations

import getpass
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from paperfetch.datasets.geo import sha256_file
from paperfetch.runtime_info import collect_runtime_info
from paperfetch.workflows.contracts import (
    VALIDATION_LEVEL_ORDER,
    ArtifactResult,
    Blocker,
    ContractError,
    DatasetManifest,
    DatasetResult,
    EnvironmentDefinition,
    EnvironmentResult,
    EnvironmentValidationLedger,
    HostProfile,
    ItemStatus,
    Launcher,
    LifecycleStatus,
    ProbeDefinition,
    ProbeResult,
    ReportHost,
    ReportProducer,
    ReportWorkflow,
    ResourceStatus,
    RuntimeKind,
    ValidationLevel,
    WorkflowReady,
    attach_content_digest,
    load_contract,
)
from paperfetch.workflows.environment_identity import inspect_conda_environment
from paperfetch.workflows.registry import WorkflowRegistryStore


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _inside(path: Path, roots: Iterable[str]) -> bool:
    for root_value in roots:
        root = Path(root_value).expanduser().resolve()
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _allowed_path(value: str, roots: Iterable[str], *, kind: str) -> Path:
    candidate = Path(value).expanduser().resolve()
    if not _inside(candidate, roots):
        raise ValueError(f"{kind} 路径超出允许的根目录：{candidate}")
    return candidate


def _probe_path(prefix: Path, probe: ProbeDefinition) -> Path:
    if not probe.path:
        raise ValueError(f"{probe.type} 探针必须提供 path")
    candidate = (prefix / probe.path).resolve()
    try:
        candidate.relative_to(prefix)
    except ValueError as exc:
        raise ValueError(f"探针路径超出环境目录：{probe.path}") from exc
    return candidate


def _executable_path(prefix: Path, executable: str) -> Path | None:
    if Path(executable).name != executable:
        return None
    candidates = [
        prefix / "bin" / executable,
        prefix / "Scripts" / executable,
        prefix / "Scripts" / f"{executable}.exe",
        prefix / executable,
        prefix / f"{executable}.exe",
    ]
    return next((item for item in candidates if item.is_file()), None)


def _run_probe(
    prefix: Path,
    probe: ProbeDefinition,
    *,
    definition: EnvironmentDefinition,
    workflow_ref: str,
    required_by_modules: list[str],
    workflow_dataset_refs: list[str],
    conda_executable: Path | None,
) -> ProbeResult:
    status = ItemStatus.READY
    detail: str | None = None
    try:
        if probe.type == "file_exists":
            path = _probe_path(prefix, probe)
            if not path.exists():
                status = ItemStatus.MISSING
                detail = f"缺少文件：{probe.path}"
        elif probe.type == "file_sha256":
            path = _probe_path(prefix, probe)
            if not path.is_file():
                status = ItemStatus.MISSING
                detail = f"缺少文件：{probe.path}"
            elif probe.sha256:
                actual = sha256_file(path)
                if actual != probe.sha256:
                    status = ItemStatus.INVALID
                    detail = f"文件 SHA-256 不一致：{probe.path}"
        elif probe.type == "validation_ledger":
            path = _probe_path(prefix, probe)
            if not path.is_file():
                status = ItemStatus.MISSING
                detail = f"缺少文件：{probe.path}"
            else:
                ledger = load_contract(path, EnvironmentValidationLedger)
                problems = []
                if ledger.environment_ref != definition.environment_ref:
                    problems.append("environment_ref 不一致")
                if not definition.lock_digest:
                    problems.append("环境定义缺少 lock_digest")
                elif ledger.environment_lock_digest != definition.lock_digest:
                    problems.append("environment_lock_digest 不一致")
                if ledger.workflow_ref != workflow_ref:
                    problems.append("workflow_ref 不一致")
                if ledger.status != "passed":
                    problems.append("验证记录状态不是 passed")
                if (
                    VALIDATION_LEVEL_ORDER[ledger.validation_level]
                    < VALIDATION_LEVEL_ORDER[probe.level]
                ):
                    problems.append(
                        "validation_level 过低："
                        f"{ledger.validation_level.value}/{probe.level.value}"
                    )
                missing_modules = sorted(
                    set(required_by_modules) - set(ledger.covered_modules)
                )
                if missing_modules:
                    problems.append("未覆盖必需模块：" + ", ".join(missing_modules))
                unknown_datasets = sorted(
                    set(ledger.dataset_refs) - set(workflow_dataset_refs)
                )
                if unknown_datasets:
                    problems.append(
                        "数据集未在 Workflow 中注册：" + ", ".join(unknown_datasets)
                    )
                if probe.sha256 and sha256_file(path) != probe.sha256:
                    problems.append(f"文件 SHA-256 不一致：{probe.path}")
                if problems:
                    status = ItemStatus.INVALID
                    detail = "; ".join(problems)
                else:
                    detail = (
                        f"已验证 {ledger.validation_level.value} 记录；"
                        f"检查={len(ledger.checks)}，证据={len(ledger.evidence)}"
                    )
        elif probe.type == "conda_lock":
            if definition.runtime != RuntimeKind.CONDA:
                raise ValueError("conda_lock 探针要求 conda 环境")
            if conda_executable is None:
                raise ValueError(
                    "conda_lock 探针要求 Host Profile 提供 conda_executable"
                )
            if not definition.lock_digest:
                raise ValueError(
                    "conda_lock 探针要求 EnvironmentDefinition 提供 lock_digest"
                )
            payload, actual = inspect_conda_environment(conda_executable, prefix)
            if actual != definition.lock_digest:
                status = ItemStatus.INVALID
                detail = (
                    "conda lock 不一致："
                    f"expected={definition.lock_digest}, actual={actual}"
                )
            else:
                detail = f"conda lock 验证通过；软件包={len(payload['packages'])}"
        elif probe.type == "executable_version":
            if not probe.executable:
                raise ValueError("executable_version 探针必须提供 executable")
            if _executable_path(prefix, probe.executable) is None:
                status = ItemStatus.MISSING
                detail = f"缺少可执行文件：{probe.executable}"
        else:
            status = ItemStatus.UNSUPPORTED
            detail = f"v0.1 尚未实现 {probe.type} 探针"
    except (ContractError, OSError, ValueError) as exc:
        status = ItemStatus.INVALID
        detail = str(exc)
    return ProbeResult(type=probe.type, level=probe.level, status=status, detail=detail)


def _highest_level(results: list[ProbeResult]) -> ValidationLevel:
    ready_levels = [
        result.level for result in results if result.status == ItemStatus.READY
    ]
    if not ready_levels:
        return ValidationLevel.IMPORT_PASS
    return max(ready_levels, key=lambda item: VALIDATION_LEVEL_ORDER[item])


def _environment_result(
    definition: EnvironmentDefinition,
    requirement_id: str,
    required: bool,
    minimum_level: ValidationLevel,
    required_by_modules: list[str],
    workflow_ref: str,
    workflow_dataset_refs: list[str],
    profile: HostProfile,
    blockers: list[Blocker],
    *,
    mode: str,
) -> EnvironmentResult:
    if profile.platform not in definition.platforms:
        status = ItemStatus.UNSUPPORTED if required else ItemStatus.OPTIONAL_MISSING
        if required:
            blockers.append(
                Blocker(
                    code="ENVIRONMENT_PLATFORM_UNSUPPORTED",
                    resource_ref=definition.environment_ref,
                    message=f"环境不支持 Host 平台：{profile.platform}",
                )
            )
        return EnvironmentResult(
            requirement_id=requirement_id,
            environment_ref=definition.environment_ref,
            required=required,
            status=status,
            probe_results=[],
        )

    mapped = profile.environment_mappings.get(definition.environment_ref)
    if not mapped:
        status = ItemStatus.BLOCKED if required else ItemStatus.OPTIONAL_MISSING
        if required:
            blockers.append(
                Blocker(
                    code="ENVIRONMENT_NOT_MAPPED",
                    resource_ref=definition.environment_ref,
                    message="Host Profile 未映射必需环境",
                )
            )
        return EnvironmentResult(
            requirement_id=requirement_id,
            environment_ref=definition.environment_ref,
            required=required,
            status=status,
            probe_results=[],
        )

    try:
        prefix = environment_materialization_path(definition, profile)
    except ValueError as exc:
        blockers.append(
            Blocker(
                code="ENVIRONMENT_PATH_OUTSIDE_ALLOWED_ROOT",
                resource_ref=definition.environment_ref,
                message=str(exc),
            )
        )
        return EnvironmentResult(
            requirement_id=requirement_id,
            environment_ref=definition.environment_ref,
            required=required,
            status=ItemStatus.INVALID,
            prefix=mapped,
            probe_results=[],
        )

    if not prefix.exists():
        status = ItemStatus.BLOCKED if required else ItemStatus.OPTIONAL_MISSING
        if required:
            blockers.append(
                Blocker(
                    code="ENVIRONMENT_NOT_INSTALLED",
                    resource_ref=definition.environment_ref,
                    message=f"环境路径不存在：{prefix}",
                )
            )
        return EnvironmentResult(
            requirement_id=requirement_id,
            environment_ref=definition.environment_ref,
            required=required,
            status=status,
            prefix=str(prefix),
            probe_results=[],
        )

    conda_executable = None
    if profile.conda_executable:
        conda_executable = Path(profile.conda_executable).expanduser().resolve()

    results = [
        _run_probe(
            prefix,
            probe,
            definition=definition,
            workflow_ref=workflow_ref,
            required_by_modules=required_by_modules,
            workflow_dataset_refs=workflow_dataset_refs,
            conda_executable=conda_executable,
        )
        for probe in definition.probes
    ]
    failed = [item for item in results if item.status != ItemStatus.READY]
    achieved = _highest_level(results)
    level_too_low = (
        VALIDATION_LEVEL_ORDER[achieved] < VALIDATION_LEVEL_ORDER[minimum_level]
    )
    status = ItemStatus.READY
    lifecycle_invalid = (
        mode == "production" and definition.lifecycle_status != LifecycleStatus.FROZEN
    )
    if lifecycle_invalid and required:
        blockers.append(
            Blocker(
                code="ENVIRONMENT_DEFINITION_PROVISIONAL",
                resource_ref=definition.environment_ref,
                message="生产检查要求 frozen EnvironmentDefinition",
            )
        )
    if failed or level_too_low or lifecycle_invalid:
        status = ItemStatus.BLOCKED if required else ItemStatus.OPTIONAL_MISSING
        if required:
            blockers.append(
                Blocker(
                    code="ENVIRONMENT_PROBE_FAILED",
                    resource_ref=definition.environment_ref,
                    message=(
                        f"环境验证不足：已达到={achieved.value}，要求={minimum_level.value}，"
                        f"失败探针={len(failed)}"
                    ),
                )
            )

    launcher = None
    if definition.runtime == RuntimeKind.CONDA and profile.conda_executable:
        assert conda_executable is not None
        if not conda_executable.is_file():
            status = ItemStatus.BLOCKED if required else ItemStatus.OPTIONAL_MISSING
            if required:
                blockers.append(
                    Blocker(
                        code="CONDA_EXECUTABLE_MISSING",
                        resource_ref=definition.environment_ref,
                        message=f"conda 可执行文件不存在：{conda_executable}",
                    )
                )
        else:
            launcher = Launcher(
                argv_prefix=[
                    str(conda_executable),
                    "run",
                    "--prefix",
                    str(prefix),
                ]
            )
    return EnvironmentResult(
        requirement_id=requirement_id,
        environment_ref=definition.environment_ref,
        required=required,
        status=status,
        prefix=str(prefix),
        validation_level=achieved,
        launcher=launcher,
        probe_results=results,
    )


def environment_materialization_path(
    definition: EnvironmentDefinition,
    profile: HostProfile,
) -> Path:
    """Resolve one mapped environment inside the Host Profile boundary."""

    mapped = profile.environment_mappings.get(definition.environment_ref)
    if not mapped:
        raise ValueError(f"环境未映射：{definition.environment_ref}")
    return _allowed_path(mapped, profile.allowed_environment_roots, kind="environment")


def _archive_entries(directory: Path) -> dict[str, dict[str, object]]:
    path = directory / "archive.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return {}
    return {
        str(item.get("filename")): item
        for item in files
        if isinstance(item, dict) and item.get("filename")
    }


def dataset_materialization_path(
    definition: DatasetManifest, profile: HostProfile
) -> Path:
    """Resolve one dataset path while enforcing the Host Profile data boundary."""

    mapped = profile.dataset_mappings.get(definition.dataset_ref)
    if mapped:
        return _allowed_path(mapped, profile.allowed_data_roots, kind="dataset")
    if definition.source_identity.namespace == "geo":
        root = Path(profile.allowed_data_roots[0]).expanduser().resolve()
        return _allowed_path(
            str(root / "geo" / definition.source_identity.accession),
            profile.allowed_data_roots,
            kind="dataset",
        )
    raise ValueError(f"数据集要求显式 Host Profile 映射：{definition.dataset_ref}")


def _dataset_result(
    definition: DatasetManifest,
    requirement_id: str,
    required: bool,
    artifact_requirements: list,
    profile: HostProfile,
    blockers: list[Blocker],
    *,
    verify_files: bool,
    mode: str,
) -> DatasetResult:
    try:
        directory = dataset_materialization_path(definition, profile)
    except ValueError as exc:
        if required:
            blockers.append(
                Blocker(
                    code="DATASET_PATH_NOT_MAPPED",
                    resource_ref=definition.dataset_ref,
                    message=str(exc),
                )
            )
        return DatasetResult(
            requirement_id=requirement_id,
            dataset_ref=definition.dataset_ref,
            required=required,
            status=ItemStatus.BLOCKED if required else ItemStatus.OPTIONAL_MISSING,
            artifact_results=[],
            dataset_manifest_digest=definition.content_digest,
        )

    if not directory.is_dir():
        if required:
            blockers.append(
                Blocker(
                    code="DATASET_NOT_MATERIALIZED",
                    resource_ref=definition.dataset_ref,
                    message=f"数据目录不存在: {directory}",
                )
            )
        return DatasetResult(
            requirement_id=requirement_id,
            dataset_ref=definition.dataset_ref,
            required=required,
            status=ItemStatus.BLOCKED if required else ItemStatus.OPTIONAL_MISSING,
            materialization_path=str(directory),
            dataset_manifest_digest=definition.content_digest,
            artifact_results=[],
        )

    definitions = {item.artifact_id: item for item in definition.artifacts}
    archive = _archive_entries(directory)
    artifact_results: list[ArtifactResult] = []
    required_failure = False
    optional_failure = False
    for requirement in artifact_requirements:
        artifact = definitions.get(requirement.artifact_id)
        if artifact is None:
            status = (
                ItemStatus.BLOCKED
                if requirement.required
                else ItemStatus.OPTIONAL_MISSING
            )
            required_failure = required_failure or requirement.required
            optional_failure = optional_failure or not requirement.required
            artifact_results.append(
                ArtifactResult(
                    artifact_id=requirement.artifact_id,
                    required=requirement.required,
                    status=status,
                    detail="DatasetManifest 未定义该制品",
                )
            )
            if required and requirement.required:
                blockers.append(
                    Blocker(
                        code="DATASET_DEFINITION_INCOMPLETE",
                        resource_ref=definition.dataset_ref,
                        message=f"DatasetManifest 未定义制品：{requirement.artifact_id}",
                    )
                )
            continue
        path = directory / artifact.filename
        if not path.is_file():
            status = (
                ItemStatus.MISSING
                if requirement.required
                else ItemStatus.OPTIONAL_MISSING
            )
            required_failure = required_failure or requirement.required
            optional_failure = optional_failure or not requirement.required
            artifact_results.append(
                ArtifactResult(
                    artifact_id=artifact.artifact_id,
                    required=requirement.required,
                    status=status,
                    path=str(path),
                    detail="文件不存在",
                )
            )
            if required and requirement.required:
                blockers.append(
                    Blocker(
                        code="ARTIFACT_MISSING",
                        resource_ref=definition.dataset_ref,
                        message=f"必需文件不存在: {artifact.filename}",
                    )
                )
            continue

        size = path.stat().st_size
        status = ItemStatus.READY
        detail = None
        actual_sha: str | None = None
        if artifact.size_bytes is not None and size != artifact.size_bytes:
            status = ItemStatus.INVALID
            detail = f"文件大小不一致：预期 {artifact.size_bytes}，实际 {size}"
        elif artifact.sha256:
            sidecar = archive.get(artifact.filename, {})
            recorded_sha = str(sidecar.get("sha256") or "")
            recorded_size = sidecar.get("size_bytes")
            if verify_files:
                actual_sha = sha256_file(path)
            elif recorded_sha == artifact.sha256 and recorded_size == size:
                actual_sha = recorded_sha
            else:
                status = ItemStatus.INVALID
                detail = "archive.json 未验证 SHA-256；请使用 --verify-files 重新检查"
            if actual_sha is not None and actual_sha != artifact.sha256:
                status = ItemStatus.INVALID
                detail = "SHA-256 不一致"

        if status != ItemStatus.READY:
            required_failure = required_failure or requirement.required
            optional_failure = optional_failure or not requirement.required
            if required and requirement.required:
                if detail and detail.startswith("文件大小不一致"):
                    code = "ARTIFACT_SIZE_MISMATCH"
                else:
                    code = "ARTIFACT_SHA256_MISMATCH"
                blockers.append(
                    Blocker(
                        code=code,
                        resource_ref=definition.dataset_ref,
                        message=f"{artifact.filename}：{detail or '制品验证失败'}",
                    )
                )
        artifact_results.append(
            ArtifactResult(
                artifact_id=artifact.artifact_id,
                required=requirement.required,
                status=status,
                path=str(path),
                size_bytes=size,
                sha256=actual_sha,
                detail=detail,
            )
        )

    identity_unresolved = definition.content_identity.identity_status != "verified"
    if required and identity_unresolved:
        blockers.append(
            Blocker(
                code="DATASET_IDENTITY_UNRESOLVED",
                resource_ref=definition.dataset_ref,
                message=f"Dataset 内容身份未冻结：{definition.content_identity.identity_status}",
            )
        )
        required_failure = True
    if (
        required
        and mode == "production"
        and definition.lifecycle_status != LifecycleStatus.FROZEN
    ):
        blockers.append(
            Blocker(
                code="DATASET_MANIFEST_PROVISIONAL",
                resource_ref=definition.dataset_ref,
                message="生产检查要求 frozen DatasetManifest",
            )
        )
        required_failure = True

    if required_failure:
        status = ItemStatus.BLOCKED if required else ItemStatus.OPTIONAL_MISSING
    elif optional_failure:
        status = ItemStatus.OPTIONAL_MISSING
    else:
        status = ItemStatus.READY
    return DatasetResult(
        requirement_id=requirement_id,
        dataset_ref=definition.dataset_ref,
        required=required,
        status=status,
        materialization_path=str(directory),
        dataset_manifest_digest=definition.content_digest,
        artifact_results=artifact_results,
    )


def check_workflow(
    workflow_ref: str,
    host_profile: HostProfile,
    *,
    registry: WorkflowRegistryStore | None = None,
    verify_files: bool = False,
    mode: str = "shadow",
) -> WorkflowReady:
    """Resolve one Workflow and return a signed resource-readiness report."""

    if mode not in {"shadow", "production"}:
        raise ValueError("mode 必须是 shadow 或 production")
    store = registry or WorkflowRegistryStore()
    manifest = store.workflow(workflow_ref)
    blockers: list[Blocker] = []

    if host_profile.platform not in manifest.platforms:
        blockers.append(
            Blocker(
                code="PLATFORM_UNSUPPORTED",
                resource_ref=host_profile.host_id,
                message=f"Workflow 不支持平台：{host_profile.platform}",
            )
        )
    if mode == "production" and manifest.lifecycle_status != LifecycleStatus.FROZEN:
        blockers.append(
            Blocker(
                code="MANIFEST_PROVISIONAL",
                resource_ref=manifest.workflow_ref,
                message="生产检查要求 frozen WorkflowResourceManifest",
            )
        )

    environments = []
    workflow_dataset_refs = [
        requirement.dataset_ref for requirement in manifest.dataset_requirements
    ]
    for requirement in manifest.environment_requirements:
        definition = store.environment(requirement.environment_ref)
        environments.append(
            _environment_result(
                definition,
                requirement.requirement_id,
                requirement.required,
                requirement.minimum_validation_level,
                requirement.required_by_modules,
                manifest.workflow_ref,
                workflow_dataset_refs,
                host_profile,
                blockers,
                mode=mode,
            )
        )

    datasets = []
    for requirement in manifest.dataset_requirements:
        definition = store.dataset(requirement.dataset_ref)
        datasets.append(
            _dataset_result(
                definition,
                requirement.requirement_id,
                requirement.required,
                requirement.artifact_requirements,
                host_profile,
                blockers,
                verify_files=verify_files,
                mode=mode,
            )
        )

    unsupported = any(item.code == "PLATFORM_UNSUPPORTED" for item in blockers)
    if unsupported:
        overall = ResourceStatus.UNSUPPORTED
    elif blockers or any(
        item.required
        and item.status not in {ItemStatus.READY, ItemStatus.OPTIONAL_MISSING}
        for item in [*environments, *datasets]
    ):
        overall = ResourceStatus.BLOCKED
    elif any(
        item.status == ItemStatus.OPTIONAL_MISSING
        for item in [*environments, *datasets]
    ):
        overall = ResourceStatus.READY_WITH_OPTIONAL_MISSING
    else:
        overall = ResourceStatus.READY

    runtime = collect_runtime_info()
    payload = {
        "schema_version": "spc.workflow-ready.v1",
        "report_id": f"urn:uuid:{uuid4()}",
        "workflow": ReportWorkflow(
            workflow_ref=manifest.workflow_ref,
            manifest_revision=manifest.manifest_revision,
            manifest_digest=manifest.content_digest,
        ).model_dump(mode="json"),
        "contract_lifecycle": manifest.lifecycle_status.value,
        "host": ReportHost(
            host_id=host_profile.host_id,
            platform=host_profile.platform,
            profile_digest=host_profile.content_digest,
        ).model_dump(mode="json"),
        "producer": ReportProducer(
            spc_version=str(runtime.get("version") or "unknown"),
            spc_git_sha=runtime.get("git_sha"),
            producer_actor=getpass.getuser() or "unknown",
            produced_at=utc_now(),
        ).model_dump(mode="json"),
        "selected_modules": manifest.selected_modules,
        "environments": [item.model_dump(mode="json") for item in environments],
        "datasets": [item.model_dump(mode="json") for item in datasets],
        "resource_status": overall.value,
        "blockers": [item.model_dump(mode="json") for item in blockers],
    }
    return WorkflowReady.model_validate(attach_content_digest(payload))


def default_platform_id() -> str:
    machine = platform.machine().lower() or "unknown"
    system = platform.system().lower()
    return f"{system}-{machine}"
