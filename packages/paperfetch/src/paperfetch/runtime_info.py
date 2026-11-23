"""运行版本与发布来源信息。"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, Optional

from paperfetch.runtime_mode import resolve_log_mode

try:
    from paperfetch._build_info import BUILD_GIT_SHA, BUILD_TIME
except ImportError:
    BUILD_GIT_SHA = None
    BUILD_TIME = None


PACKAGE_NAME = "paperfetch"
# The PyPI distribution name differs from the import package name.
DISTRIBUTION_NAME = "scianchor-paperfetch"


def _clean_build_value(name: str, *, maximum_length: int = 128) -> Optional[str]:
    value = str(os.getenv(name) or "").strip()
    if not value:
        return None
    return value[:maximum_length]


def _distribution_details() -> tuple[str, bool]:
    try:
        distribution = metadata.distribution(DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return "unknown", False

    direct_url = distribution.read_text("direct_url.json")
    editable = False
    if direct_url:
        try:
            editable = bool(json.loads(direct_url).get("dir_info", {}).get("editable"))
        except (TypeError, ValueError, json.JSONDecodeError):
            editable = False
    return distribution.version, editable


def _find_git_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _git_sha(start: Path) -> Optional[str]:
    root = _find_git_root(start)
    if root is None:
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value if value else None


def _source_version(root: Optional[Path]) -> Optional[str]:
    if root is None:
        return None
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return None
    value = str(payload.get("project", {}).get("version") or "").strip()
    return value or None


def collect_runtime_info() -> Dict[str, Any]:
    """返回不包含凭证的版本、源码来源和运行时信息。"""

    installed_version, editable = _distribution_details()
    package_path = Path(__file__).resolve().parent
    source_root = _find_git_root(package_path)
    source_version = _source_version(source_root)
    package_version = source_version or installed_version
    git_sha = (
        BUILD_GIT_SHA
        or _clean_build_value("SPC_BUILD_GIT_SHA")
        or _git_sha(package_path)
    )
    from paperfetch.core.environment import (
        current_environment,
        infer_environment,
    )

    environment = current_environment()
    return {
        "package": PACKAGE_NAME,
        "version": package_version,
        "installed_version": installed_version,
        "version_mismatch": package_version != installed_version,
        "git_sha": git_sha,
        "build_time": BUILD_TIME or _clean_build_value("SPC_BUILD_TIME"),
        "install_mode": "editable" if editable else "installed",
        "package_path": str(package_path),
        "source_root": str(source_root) if source_root else None,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.system().lower(),
        "environment": environment,
        "environment_inferred": infer_environment(),
        "log_mode": resolve_log_mode(),
    }
