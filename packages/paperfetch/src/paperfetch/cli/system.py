"""SPC 2.0 轻量能力盘点与运行前门禁。"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from paperfetch.core.config_v1 import RuntimeProfile, load_config
from paperfetch.core.contracts_v1 import (
    BusinessStatus,
    CommandItem,
    CommandResult,
    CommandSummary,
    EntityRef,
    ErrorInfo,
)
from paperfetch.observability import write_output
from paperfetch.runtime_info import collect_runtime_info


@dataclass(frozen=True)
class CapabilityDefinition:
    name: str
    description: str
    modules: tuple[str, ...] = ()
    credentials: tuple[str, ...] = ()
    children: tuple[str, ...] = ()


CAPABILITIES: dict[str, CapabilityDefinition] = {
    "system.core": CapabilityDefinition(
        "system.core",
        "版本、配置、结果、事件与轻量 CLI",
        ("pydantic", "httpx", "rich"),
    ),
    "paper.metadata": CapabilityDefinition(
        "paper.metadata",
        "DOI、PMID、PMCID、arXiv 元数据与引用查询",
        ("httpx", "bs4", "lxml"),
    ),
    "paper.download.oa": CapabilityDefinition(
        "paper.download.oa",
        "公开全文发现、传输、PDF 与论文身份校验",
        ("httpx", "pypdf", "cryptography"),
    ),
    "paper.download": CapabilityDefinition(
        "paper.download",
        "公开全文下载",
        children=("paper.metadata", "paper.download.oa"),
    ),
    "paper.parse": CapabilityDefinition(
        "paper.parse",
        "MinerU 正文解析与本地文件保存",
        ("httpx",),
        ("MINERU_API_TOKEN",),
    ),
    "dataset.archive": CapabilityDefinition(
        "dataset.archive",
        "公开归档元数据、远程 inventory、断点续传与 checksum",
        ("httpx",),
    ),
}


def _module_ready(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _credential_ready(name: str) -> bool:
    from paperfetch.core.settings import SETTINGS_BY_NAME, get_settings

    if name in SETTINGS_BY_NAME:
        return bool(get_settings().text(name))
    return bool((os.getenv(name) or "").strip())


def _normalized_path(value: str | None) -> str:
    return (value or "").replace("\\", "/").rstrip("/") + "/"


def _resolve_capability(name: str, stack: tuple[str, ...] = ()) -> dict:
    if name not in CAPABILITIES:
        return {
            "name": name,
            "known": False,
            "ready": False,
            "missing_modules": [],
            "missing_credentials": [],
            "missing_children": [],
        }
    if name in stack:
        raise RuntimeError(f"capability cycle: {' -> '.join((*stack, name))}")
    definition = CAPABILITIES[name]
    missing_modules = [item for item in definition.modules if not _module_ready(item)]
    missing_credentials = [
        item for item in definition.credentials if not _credential_ready(item)
    ]
    children = [
        _resolve_capability(item, (*stack, name)) for item in definition.children
    ]
    missing_children = [item["name"] for item in children if not item["ready"]]
    return {
        "name": name,
        "description": definition.description,
        "known": True,
        "ready": not missing_modules
        and not missing_credentials
        and not missing_children,
        "missing_modules": missing_modules,
        "missing_credentials": missing_credentials,
        "missing_children": missing_children,
    }


def capability_status(names: Iterable[str] | None = None) -> list[dict]:
    selected = sorted(set(names or CAPABILITIES))
    return [_resolve_capability(name) for name in selected]


def _path_check(path: Path, *, require_writable: bool) -> tuple[bool, dict]:
    """检查指定路径是否存在及可写性，并在要求可写时探测真实文件创建与已有日志权限。"""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    exists_parent = probe.exists()
    writable = exists_parent and os.access(probe, os.W_OK)
    data: dict[str, Any] = {
        "path": str(path),
        "existing_parent": str(probe),
        "parent_exists": exists_parent,
        "writable": writable,
    }
    # 行内注释：若要求可写且父目录存在，进行真实写入探针，杜绝目录属组权限导致的假阳性
    if require_writable and exists_parent and writable:
        if path.is_dir():
            probe_file = path / f".spc_preflight_probe_{uuid.uuid4().hex[:8]}.tmp"
            try:
                probe_file.write_text("probe", encoding="utf-8")
                probe_file.unlink(missing_ok=True)
            except OSError as exc:
                writable = False
                data["writable"] = False
                data["probe_error"] = str(exc)

            # 行内注释：探测日志目录下已有常用日志文件的追加写权限
            for log_name in ("spc.log", "spc.events.jsonl"):
                existing_log = path / log_name
                if existing_log.is_file() and not os.access(existing_log, os.W_OK):
                    writable = False
                    data["writable"] = False
                    data["unwritable_file"] = str(existing_log)

            # 行内注释：探测 audit 子目录的写入与遍历权限
            audit_dir = path / "audit"
            if audit_dir.exists():
                if not os.access(audit_dir, os.W_OK):
                    writable = False
                    data["writable"] = False
                    data["unwritable_dir"] = str(audit_dir)
                else:
                    audit_probe = (
                        audit_dir / f".spc_preflight_probe_{uuid.uuid4().hex[:8]}.tmp"
                    )
                    try:
                        audit_probe.write_text("probe", encoding="utf-8")
                        audit_probe.unlink(missing_ok=True)
                    except OSError as exc:
                        writable = False
                        data["writable"] = False
                        data["probe_error"] = str(exc)

    return (exists_parent and (writable or not require_writable)), data


def _check_item(
    name: str, passed: bool, data: dict, *, error_code: str, message: str
) -> CommandItem:
    return CommandItem(
        entity=EntityRef(type="preflight_check", id=name),
        status=BusinessStatus.COMPLETED if passed else BusinessStatus.REJECTED,
        data=data,
        error=None
        if passed
        else ErrorInfo(
            code=error_code,
            error_class="environment_not_ready",
            stage="preflight",
            retryable=False,
            message=message,
        ),
    )


def build_preflight_result(
    *,
    profile_name: str,
    capabilities: Iterable[str],
    config_file: str | None = None,
    expected_git_sha: str | None = None,
    expected_source_root: str | None = None,
    require_writable_paths: bool = False,
) -> CommandResult:
    started = time.perf_counter()
    run_id = uuid.uuid4().hex
    try:
        config, config_source = load_config(config_file)
    except Exception as exc:
        error = ErrorInfo(
            code="config_invalid",
            error_class="configuration_error",
            stage="preflight",
            message=f"SPC 配置无效：{type(exc).__name__}",
        )
        return CommandResult(
            command="system.preflight",
            run_id=run_id,
            status=BusinessStatus.REJECTED,
            error=error,
            summary=CommandSummary(
                selected=1,
                failed=1,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
    profile: RuntimeProfile | None = config.profiles.get(profile_name)
    if profile is None:
        error = ErrorInfo(
            code="profile_not_found",
            error_class="configuration_error",
            stage="preflight",
            message=f"未定义运行 Profile：{profile_name}",
        )
        return CommandResult(
            command="system.preflight",
            run_id=run_id,
            status=BusinessStatus.REJECTED,
            error=error,
            summary=CommandSummary(
                selected=1,
                failed=1,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            ),
        )

    runtime = collect_runtime_info()
    items: list[CommandItem] = []
    from paperfetch.core.environment import current_environment, infer_environment

    environment = current_environment()
    inferred = infer_environment()
    items.append(
        _check_item(
            "runtime.environment",
            environment == profile_name and environment == inferred,
            {
                "declared": environment,
                "profile": profile_name,
                "inferred": inferred,
            },
            error_code="runtime_environment_mismatch",
            message="SPC_ENVIRONMENT 必须与 --profile 以及当前解释器位置一致",
        )
    )
    platform_ok = runtime["platform"] == profile.platform
    items.append(
        _check_item(
            "runtime.platform",
            platform_ok,
            {"actual": runtime["platform"], "expected": profile.platform},
            error_code="runtime_platform_mismatch",
            message="运行平台与 Profile 不一致",
        )
    )
    python_ok = platform.python_version().startswith(f"{profile.python_minor}.")
    items.append(
        _check_item(
            "runtime.python",
            python_ok,
            {
                "actual": platform.python_version(),
                "expected_minor": profile.python_minor,
            },
            error_code="runtime_python_mismatch",
            message="Python 版本与 Profile 不一致",
        )
    )
    install_ok = runtime["install_mode"] in profile.install_modes
    items.append(
        _check_item(
            "runtime.install_mode",
            install_ok,
            {"actual": runtime["install_mode"], "allowed": profile.install_modes},
            error_code="runtime_install_mode_mismatch",
            message="安装模式与 Profile 不一致",
        )
    )
    if profile.python_executable_prefix:
        actual_python = _normalized_path(runtime["python_executable"])
        expected_python = _normalized_path(profile.python_executable_prefix)
        python_path_ok = actual_python.startswith(expected_python)
        items.append(
            _check_item(
                "runtime.python_path",
                python_path_ok,
                {
                    "actual": runtime["python_executable"],
                    "expected_prefix": profile.python_executable_prefix,
                },
                error_code="runtime_python_path_mismatch",
                message="Python 解释器不属于 Profile 固定运行时",
            )
        )
    if profile.package_path_prefix:
        actual_package = _normalized_path(runtime["package_path"])
        expected_package = _normalized_path(profile.package_path_prefix)
        package_path_ok = actual_package.startswith(expected_package)
        items.append(
            _check_item(
                "runtime.package_path",
                package_path_ok,
                {
                    "actual": runtime["package_path"],
                    "expected_prefix": profile.package_path_prefix,
                },
                error_code="runtime_package_path_mismatch",
                message="SPC 包不属于 Profile 固定运行时",
            )
        )
    if expected_git_sha:
        sha_ok = runtime.get("git_sha") == expected_git_sha
        items.append(
            _check_item(
                "runtime.git_sha",
                sha_ok,
                {"actual": runtime.get("git_sha"), "expected": expected_git_sha},
                error_code="runtime_git_sha_mismatch",
                message="运行时 Git SHA 与预期不一致",
            )
        )
    if expected_source_root:
        actual = (
            str(Path(runtime.get("source_root") or "").resolve())
            if runtime.get("source_root")
            else None
        )
        expected = str(Path(expected_source_root).resolve())
        root_ok = actual == expected
        items.append(
            _check_item(
                "runtime.source_root",
                root_ok,
                {"actual": actual, "expected": expected},
                error_code="runtime_source_root_mismatch",
                message="运行时源码根目录与预期不一致",
            )
        )
    encoding_ok = (sys.stdout.encoding or "").lower().replace("-", "") == "utf8" and (
        sys.stderr.encoding or ""
    ).lower().replace("-", "") == "utf8"
    items.append(
        _check_item(
            "runtime.utf8",
            encoding_ok,
            {"stdout": sys.stdout.encoding, "stderr": sys.stderr.encoding},
            error_code="runtime_encoding_mismatch",
            message="stdout/stderr 未统一为 UTF-8",
        )
    )
    requested = sorted(set((*profile.required_capabilities, *capabilities)))
    for status in capability_status(requested):
        items.append(
            _check_item(
                f"capability.{status['name']}",
                status["ready"],
                status,
                error_code="capability_not_ready"
                if status["known"]
                else "capability_unsupported",
                message=f"能力未就绪：{status['name']}",
            )
        )
    for label, path in {
        "state": profile.state_root,
        "data": profile.data_root,
        "cache": profile.cache_root,
        "logs": profile.log_root,
    }.items():
        path_ok, data = _path_check(path, require_writable=require_writable_paths)
        items.append(
            _check_item(
                f"path.{label}",
                path_ok,
                data,
                error_code="runtime_path_not_ready",
                message=f"运行目录不可用：{label}",
            )
        )
    from paperfetch.core.settings import unknown_settings_env

    unknown = unknown_settings_env()
    items.append(
        _check_item(
            "settings.unknown",
            not unknown,
            {"unknown_env": unknown},
            error_code="unknown_settings_env",
            message=f"未注册配置：{', '.join(unknown)}"
            if unknown
            else "受管环境变量均已注册",
        )
    )

    failed = sum(item.status == BusinessStatus.REJECTED.value for item in items)
    status = BusinessStatus.COMPLETED if failed == 0 else BusinessStatus.REJECTED
    error = (
        None
        if failed == 0
        else ErrorInfo(
            code="preflight_failed",
            error_class="environment_not_ready",
            stage="preflight",
            message=f"运行前检查未通过，共 {failed} 项阻断",
            remediation="按 items 中的稳定错误修复后重新运行 preflight",
        )
    )
    return CommandResult(
        command="system.preflight",
        run_id=run_id,
        status=status,
        summary=CommandSummary(
            selected=len(items),
            succeeded=len(items) - failed,
            failed=failed,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        ),
        items=items,
        metrics={"config_profile_count": len(config.profiles)},
        error=error,
        audit_ref=None,
    )


def run_system(parsed_args) -> int:
    if parsed_args.system_action == "source-status":
        import asyncio

        async def check_sources() -> list[CommandItem]:
            from paperfetch.utils.client import create_async_client

            client = create_async_client()
            items: list[CommandItem] = []
            try:
                sources = [
                    ("openalex", "https://api.openalex.org/works?per_page=1"),
                    (
                        "semantic_scholar",
                        "https://api.semanticscholar.org/graph/v1/paper/search?query=test&limit=1",
                    ),
                    (
                        "pubmed",
                        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=test&retmax=1&retmode=json",
                    ),
                ]
                for name, url in sources:
                    try:
                        response = await client.get(url, timeout=5.0)
                        available = response.status_code < 500
                        error = (
                            None
                            if available
                            else ErrorInfo(
                                code="source_unavailable",
                                error_class="network_error",
                                stage="source_probe",
                                retryable=True,
                                message=f"{name} 返回 HTTP {response.status_code}",
                            )
                        )
                    except Exception:
                        available = False
                        error = ErrorInfo(
                            code="source_unavailable",
                            error_class="network_error",
                            stage="source_probe",
                            retryable=True,
                            message=f"{name} 当前不可达",
                        )
                    items.append(
                        CommandItem(
                            entity=EntityRef(type="source", id=name),
                            status=BusinessStatus.COMPLETED
                            if available
                            else BusinessStatus.FAILED,
                            data={"available": available},
                            error=error,
                        )
                    )
            finally:
                await client.aclose()
            return items

        items = asyncio.run(check_sources())
        failed = sum(item.status == BusinessStatus.FAILED.value for item in items)
        result = CommandResult(
            command="system.source-status",
            run_id=uuid.uuid4().hex,
            status=BusinessStatus.COMPLETED if failed == 0 else BusinessStatus.PARTIAL,
            summary=CommandSummary(
                selected=len(items), succeeded=len(items) - failed, failed=failed
            ),
            items=items,
            error=None
            if failed == 0
            else ErrorInfo(
                code="sources_partially_unavailable",
                error_class="network_error",
                stage="source_probe",
                retryable=True,
                message=f"{failed} 个数据源当前不可达",
            ),
        )
    elif parsed_args.system_action == "source-capabilities":
        domain = parsed_args.domain
        configured = {
            "computer_science": {
                "primary": ["openalex", "semantic_scholar"],
                "secondary": ["crossref", "dblp", "arxiv"],
            },
            "biomedical": {
                "primary": ["openalex", "pubmed"],
                "secondary": ["crossref", "semantic_scholar", "europe_pmc"],
            },
        }.get(domain)
        error = (
            None
            if configured
            else ErrorInfo(
                code="domain_unsupported",
                error_class="invalid_input",
                stage="source_capabilities",
                message=f"领域 {domain} 暂无数据源配置",
            )
        )
        result = CommandResult(
            command="system.source-capabilities",
            run_id=uuid.uuid4().hex,
            status=BusinessStatus.COMPLETED if configured else BusinessStatus.FAILED,
            summary=CommandSummary(
                selected=1,
                succeeded=1 if configured else 0,
                failed=0 if configured else 1,
            ),
            items=[
                CommandItem(
                    entity=EntityRef(type="domain", id=domain),
                    status=BusinessStatus.COMPLETED
                    if configured
                    else BusinessStatus.FAILED,
                    data=configured or {},
                    error=error,
                )
            ],
            error=error,
        )
    elif parsed_args.system_action == "capabilities":
        statuses = capability_status(parsed_args.capability or None)
        result = CommandResult(
            command="system.capabilities",
            run_id=uuid.uuid4().hex,
            status=BusinessStatus.COMPLETED,
            summary=CommandSummary(selected=len(statuses), succeeded=len(statuses)),
            items=[
                CommandItem(
                    entity=EntityRef(type="capability", id=status["name"]),
                    status=BusinessStatus.COMPLETED,
                    data=status,
                )
                for status in statuses
            ],
        )
    elif parsed_args.system_action == "preflight":
        result = build_preflight_result(
            profile_name=parsed_args.profile,
            capabilities=parsed_args.capability,
            config_file=parsed_args.config,
            expected_git_sha=parsed_args.expected_git_sha,
            expected_source_root=parsed_args.expected_source_root,
            require_writable_paths=parsed_args.require_writable_paths,
        )
    write_output(result.model_dump(mode="json"), pretty=True)
    return (
        0
        if result.status == BusinessStatus.COMPLETED.value
        else 2
        if result.status == BusinessStatus.PARTIAL.value
        else 1
    )


def register_system_commands(subparsers):
    """注册 system capabilities/preflight。"""
    system_parser = subparsers.add_parser("system", help="查看能力并执行轻量运行前门禁")
    system_subparsers = system_parser.add_subparsers(
        dest="system_action", required=True
    )
    system_capabilities_parser = system_subparsers.add_parser(
        "capabilities", help="查看当前运行时已安装和已配置能力"
    )
    system_capabilities_parser.add_argument("--capability", action="append", default=[])
    system_capabilities_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )
    system_preflight_parser = system_subparsers.add_parser(
        "preflight", help="按 Profile 和能力检查运行身份；不隐式访问网络"
    )
    system_preflight_parser.add_argument(
        "--profile",
        required=True,
        choices=["development", "production"],
        help="与 SPC_ENVIRONMENT 相同：development 本机开发树，production 服务器正式安装",
    )
    system_preflight_parser.add_argument("--capability", action="append", default=[])
    system_preflight_parser.add_argument(
        "--config", default=None, help="非敏感 spc.toml"
    )
    system_preflight_parser.add_argument("--expected-git-sha", default=None)
    system_preflight_parser.add_argument("--expected-source-root", default=None)
    system_preflight_parser.add_argument(
        "--require-writable-paths", action="store_true"
    )
    system_preflight_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )
    source_status_parser = system_subparsers.add_parser(
        "source-status", help="实时检查主要论文元数据源"
    )
    source_status_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )
    source_capabilities_parser = system_subparsers.add_parser(
        "source-capabilities", help="查看领域数据源能力"
    )
    source_capabilities_parser.add_argument(
        "--domain", required=True, choices=["computer_science", "biomedical"]
    )
    source_capabilities_parser.add_argument(
        "--output-format", choices=["json"], default="json"
    )
    return [
        system_capabilities_parser,
        system_preflight_parser,
        source_status_parser,
        source_capabilities_parser,
    ]
