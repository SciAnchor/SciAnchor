"""Workflow 资源契约与就绪报告命令适配器。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paperfetch.datasets.geo import atomic_write_json
from paperfetch.observability import write_output
from paperfetch.workflows.contracts import (
    ContractError,
    HostProfile,
    ResourceStatus,
    RuntimeKind,
    WorkflowReady,
    load_contract,
)
from paperfetch.workflows.environment_identity import inspect_conda_environment
from paperfetch.workflows.preparation import prepare_workflow
from paperfetch.workflows.readiness import (
    check_workflow,
    environment_materialization_path,
)
from paperfetch.workflows.registry import WorkflowRegistryStore


def _command_error(exc: Exception) -> dict[str, str]:
    if isinstance(exc, ContractError):
        error_code = "workflow_contract_invalid"
        error_class = "invalid_contract"
        message = f"Workflow 资源契约无效：{exc}"
    elif isinstance(exc, OSError):
        error_code = "workflow_file_operation_failed"
        error_class = "io_error"
        message = f"Workflow 资源文件操作失败：{type(exc).__name__}"
    else:
        error_code = "invalid_workflow_argument"
        error_class = "invalid_configuration"
        message = str(exc).strip() or "Workflow 参数或配置无效"
    return {
        "schema_version": "spc.workflow-command-error.v1",
        "status": "failed",
        "error_code": error_code,
        "error_class": error_class,
        "message": message,
        "error": message,
    }


def _emit_report_text(report: WorkflowReady) -> None:
    write_output(
        f"{report.workflow.workflow_ref}：状态={report.resource_status.value}，"
        f"主机={report.host.host_id}，生命周期={report.contract_lifecycle.value}"
    )
    for environment in report.environments:
        write_output(
            f"- 环境 {environment.requirement_id}：{environment.status.value} "
            f"（{environment.environment_ref}）"
        )
    for dataset in report.datasets:
        write_output(
            f"- 数据 {dataset.requirement_id}：{dataset.status.value} "
            f"（{dataset.dataset_ref}）"
        )
    for blocker in report.blockers:
        write_output(f"  阻断[{blocker.code}]：{blocker.message}")


def run_workflow_check(parsed_args: Any) -> int:
    try:
        profile = load_contract(parsed_args.host_profile, HostProfile)
        registry = WorkflowRegistryStore(parsed_args.registry_root)
        report = check_workflow(
            parsed_args.workflow_ref,
            profile,
            registry=registry,
            verify_files=parsed_args.verify_files,
            mode=parsed_args.mode,
        )
    except (ContractError, OSError, ValueError) as exc:
        payload = _command_error(exc)
        if parsed_args.output_format == "json":
            write_output(payload, pretty=True)
        else:
            write_output(payload["error"])
        return 1

    if parsed_args.report_file:
        atomic_write_json(
            Path(parsed_args.report_file).expanduser().resolve(),
            report.model_dump(mode="json"),
        )
    if parsed_args.output_format == "json":
        write_output(report.model_dump(mode="json"), pretty=True)
    else:
        _emit_report_text(report)
    return (
        0
        if report.resource_status
        in {
            ResourceStatus.READY,
            ResourceStatus.READY_WITH_OPTIONAL_MISSING,
        }
        else 2
    )


def run_workflow_status(parsed_args: Any) -> int:
    try:
        report = load_contract(parsed_args.report_file, WorkflowReady)
    except (ContractError, OSError, ValueError) as exc:
        payload = _command_error(exc)
        if parsed_args.output_format == "json":
            write_output(payload, pretty=True)
        else:
            write_output(payload["error"])
        return 4

    produced_at = report.producer.produced_at.astimezone(timezone.utc)
    age_seconds = max(0.0, (datetime.now(timezone.utc) - produced_at).total_seconds())
    stale = (
        parsed_args.max_age_seconds is not None
        and age_seconds > parsed_args.max_age_seconds
    )
    payload = report.model_dump(mode="json")
    payload["status_observation"] = {
        "age_seconds": round(age_seconds, 3),
        "max_age_seconds": parsed_args.max_age_seconds,
        "stale": stale,
    }
    if parsed_args.output_format == "json":
        write_output(payload, pretty=True)
    else:
        _emit_report_text(report)
        write_output(f"  报告年龄秒数={age_seconds:.1f}，已过期={stale}")
    if stale:
        return 2
    return (
        0
        if report.resource_status
        in {
            ResourceStatus.READY,
            ResourceStatus.READY_WITH_OPTIONAL_MISSING,
        }
        else 2
    )


def run_workflow_prepare(parsed_args: Any) -> int:
    try:
        profile = load_contract(parsed_args.host_profile, HostProfile)
        registry = WorkflowRegistryStore(parsed_args.registry_root)
        outcome = prepare_workflow(
            parsed_args.workflow_ref,
            profile,
            registry=registry,
            verify_files=parsed_args.verify_files,
            mode=parsed_args.mode,
            allow_large=parsed_args.allow_large,
            max_download_gb=parsed_args.max_size_gb,
            dataset_concurrency=parsed_args.dataset_concurrency,
            lock_timeout_seconds=parsed_args.lock_timeout_seconds,
        )
    except (ContractError, OSError, ValueError) as exc:
        payload = _command_error(exc)
        if parsed_args.output_format == "json":
            write_output(payload, pretty=True)
        else:
            write_output(payload["error"])
        return 1

    if parsed_args.report_file:
        atomic_write_json(
            Path(parsed_args.report_file).expanduser().resolve(),
            outcome.report.model_dump(mode="json", exclude_unset=True),
        )
    if parsed_args.output_format == "json":
        write_output(
            outcome.report.model_dump(mode="json", exclude_unset=True),
            pretty=True,
        )
    else:
        for action in outcome.actions:
            detail = f"（{action.detail}）" if action.detail else ""
            write_output(f"准备[{action.action}] {action.dataset_ref}{detail}")
        _emit_report_text(outcome.report)
    return outcome.exit_code


def run_workflow_environment_lock(parsed_args: Any) -> int:
    try:
        profile = load_contract(parsed_args.host_profile, HostProfile)
        registry = WorkflowRegistryStore(parsed_args.registry_root)
        definition = registry.environment(parsed_args.environment_ref)
        if definition.runtime != RuntimeKind.CONDA:
            raise ValueError("environment-lock仅支持Conda环境")
        if not profile.conda_executable:
            raise ValueError("Host Profile未配置conda_executable")
        prefix = environment_materialization_path(definition, profile)
        payload, digest = inspect_conda_environment(profile.conda_executable, prefix)
    except (ContractError, OSError, ValueError) as exc:
        error = _command_error(exc)
        if parsed_args.output_format == "json":
            write_output(error, pretty=True)
        else:
            write_output(error["error"])
        return 1

    expected = definition.lock_digest
    matches = expected is None or expected == digest
    result = {
        "schema_version": "spc.conda-environment-lock-report.v1",
        "status": "completed" if matches else "failed",
        "environment_ref": definition.environment_ref,
        "prefix": str(prefix),
        "package_count": len(payload["packages"]),
        "lock_digest": digest,
        "expected_lock_digest": expected,
        "matches_definition": matches,
    }
    if not matches:
        result.update(
            {
                "error_code": "environment_lock_mismatch",
                "message": "已安装 Conda 环境与定义的锁摘要不一致",
            }
        )
    if parsed_args.lock_file:
        atomic_write_json(Path(parsed_args.lock_file).expanduser().resolve(), payload)
        result["lock_file"] = str(Path(parsed_args.lock_file).expanduser().resolve())
    if parsed_args.output_format == "json":
        write_output(result, pretty=True)
    else:
        write_output(
            f"{definition.environment_ref}：软件包数={result['package_count']}，"
            f"锁摘要={digest}，与定义一致={matches}"
        )
    return 0 if matches else 2


def run_workflow(parsed_args: Any) -> int:
    if parsed_args.workflow_action == "check":
        return run_workflow_check(parsed_args)
    if parsed_args.workflow_action == "prepare":
        return run_workflow_prepare(parsed_args)
    if parsed_args.workflow_action == "status":
        return run_workflow_status(parsed_args)
    if parsed_args.workflow_action == "environment-lock":
        return run_workflow_environment_lock(parsed_args)
    raise ValueError(f"不支持的 Workflow 操作：{parsed_args.workflow_action}")


def register_workflow_commands(subparsers):
    """注册 workflow check/prepare/status/environment-lock。"""
    from paperfetch.cli.common import env_float as _env_float, env_int as _env_int

    workflow_parser = subparsers.add_parser(
        "workflow",
        help="检查版本化 Workflow 环境与数据资源",
    )
    workflow_subparsers = workflow_parser.add_subparsers(
        dest="workflow_action",
        required=True,
        help="Workflow 资源操作",
    )
    workflow_check_parser = workflow_subparsers.add_parser(
        "check",
        help="只读检查环境、数据和资源契约",
    )
    workflow_check_parser.add_argument(
        "workflow_ref", help="已注册的 workflow:<id>@<version>"
    )
    workflow_check_parser.add_argument(
        "--host-profile", required=True, help="Host Profile JSON"
    )
    workflow_check_parser.add_argument(
        "--registry-root", default=None, help="覆盖内置注册表根目录"
    )
    workflow_check_parser.add_argument(
        "--mode", choices=["shadow", "production"], default="shadow"
    )
    workflow_check_parser.add_argument(
        "--verify-files", action="store_true", help="重新计算大文件 SHA-256"
    )
    workflow_check_parser.add_argument(
        "--report-file", default=None, help="原子写入 workflow_ready.json"
    )
    workflow_check_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    workflow_prepare_parser = workflow_subparsers.add_parser(
        "prepare",
        help="准备允许自动获取的必需数据并重新检查资源",
    )
    workflow_prepare_parser.add_argument(
        "workflow_ref", help="已注册的 workflow:<id>@<version>"
    )
    workflow_prepare_parser.add_argument(
        "--host-profile", required=True, help="Host Profile JSON"
    )
    workflow_prepare_parser.add_argument(
        "--registry-root", default=None, help="覆盖内置注册表根目录"
    )
    workflow_prepare_parser.add_argument(
        "--mode", choices=["shadow", "production"], default="shadow"
    )
    workflow_prepare_parser.add_argument(
        "--verify-files", action="store_true", help="最终检查重新计算大文件 SHA-256"
    )
    workflow_prepare_parser.add_argument(
        "--allow-large", action="store_true", help="显式授权超过大小门禁的数据下载"
    )
    workflow_prepare_parser.add_argument(
        "--max-size-gb",
        type=float,
        default=_env_float("SPC_GEO_MAX_DOWNLOAD_GB", 20.0),
        help="自动下载大小门禁，默认20 GiB",
    )
    workflow_prepare_parser.add_argument(
        "--dataset-concurrency",
        type=int,
        default=_env_int("SPC_DATASET_CONCURRENCY", 2),
        help="主机允许同时活动的数据集上限，1-4，默认2；单一来源仍保持单流",
    )
    workflow_prepare_parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=_env_float("SPC_DATASET_LOCK_TIMEOUT_SECONDS", 30.0),
        help="等待主机/数据集/来源锁的秒数，默认30",
    )
    workflow_prepare_parser.add_argument(
        "--report-file", default=None, help="原子写入 workflow_ready.json"
    )
    workflow_prepare_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    workflow_status_parser = workflow_subparsers.add_parser(
        "status",
        help="校验并查看已有 workflow_ready.json",
    )
    workflow_status_parser.add_argument(
        "--report-file", required=True, help="已有 workflow_ready.json"
    )
    workflow_status_parser.add_argument(
        "--max-age-seconds", type=float, default=None, help="报告最大允许年龄"
    )
    workflow_status_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    workflow_lock_parser = workflow_subparsers.add_parser(
        "environment-lock",
        help="计算已安装Conda环境的确定性锁摘要",
    )
    workflow_lock_parser.add_argument(
        "environment_ref",
        help="已注册的 environment:<id>@<version>",
    )
    workflow_lock_parser.add_argument(
        "--host-profile", required=True, help="Host Profile JSON"
    )
    workflow_lock_parser.add_argument(
        "--registry-root", default=None, help="覆盖内置注册表根目录"
    )
    workflow_lock_parser.add_argument(
        "--lock-file", default=None, help="原子写入完整Conda锁JSON"
    )
    workflow_lock_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )
    return [
        workflow_check_parser,
        workflow_prepare_parser,
        workflow_status_parser,
        workflow_lock_parser,
    ]
