"""Deterministic identities for installed Conda environments."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from paperfetch.workflows.contracts import ContractError, canonical_json_bytes

CONDA_PACKAGE_FIELDS = (
    "name",
    "version",
    "build_number",
    "build_string",
    "channel",
    "platform",
)


def normalize_conda_packages(value: Any) -> list[dict[str, object]]:
    """Reduce ``conda list --json`` to a mirror-independent stable surface."""

    if not isinstance(value, list):
        raise ContractError("conda list 返回值必须是数组")
    records: list[dict[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ContractError(f"conda 软件包记录 {index} 必须是对象")
        missing = [field for field in CONDA_PACKAGE_FIELDS if field not in item]
        if missing:
            raise ContractError(
                f"conda 软件包记录 {index} 缺少字段：{', '.join(missing)}"
            )
        record = {field: item[field] for field in CONDA_PACKAGE_FIELDS}
        string_fields = ("name", "version", "build_string", "channel", "platform")
        valid_strings = all(isinstance(record[field], str) for field in string_fields)
        build_number = record["build_number"]
        valid_build_number = isinstance(build_number, int) and not isinstance(
            build_number,
            bool,
        )
        if not valid_strings or not valid_build_number:
            raise ContractError(f"conda 软件包记录 {index} 包含无效字段类型")
        records.append(record)
    return sorted(
        records,
        key=lambda item: tuple(item[field] for field in CONDA_PACKAGE_FIELDS),
    )


def conda_lock_payload(packages: Any) -> dict[str, object]:
    return {
        "schema_version": "spc.conda-environment-lock.v1",
        "packages": normalize_conda_packages(packages),
    }


def conda_lock_digest(packages: Any) -> str:
    payload = conda_lock_payload(packages)
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def inspect_conda_environment(
    conda_executable: str | Path,
    prefix: str | Path,
    *,
    timeout_seconds: float = 60.0,
) -> tuple[dict[str, object], str]:
    """Read an installed environment through Conda without activating it."""

    conda_path = Path(conda_executable).expanduser().resolve()
    prefix_path = Path(prefix).expanduser().resolve()
    if not conda_path.is_file():
        raise ContractError(f"conda 可执行文件不存在：{conda_path}")
    if not prefix_path.is_dir():
        raise ContractError(f"conda 环境不存在：{prefix_path}")
    try:
        completed = subprocess.run(
            [
                str(conda_path),
                "list",
                "--json",
                "--prefix",
                str(prefix_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(f"无法检查 conda 环境：{exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "未知错误"
        raise ContractError(f"conda list 执行失败（{completed.returncode}）：{detail}")
    try:
        packages = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError(f"conda list 返回了无效 JSON：{exc}") from exc
    payload = conda_lock_payload(packages)
    return payload, conda_lock_digest(packages)
