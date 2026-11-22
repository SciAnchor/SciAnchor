"""SPC 产品环境和本机/服务器 production 运行面。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

EnvironmentName = Literal["development", "production"]
ENVIRONMENTS = ("development", "production")
# A shared server install; override with PAPERFETCH_PRODUCTION_ROOT.
SERVER_PRODUCTION_ROOT = Path(
    os.environ.get("PAPERFETCH_PRODUCTION_ROOT", "/opt/paperfetch")
)
LOCAL_PRODUCTION_ROOT = Path.home() / ".local" / "share" / "paperfetch-production"
PRODUCTION_PREFIX = f"{SERVER_PRODUCTION_ROOT}/"
LOCAL_PRODUCTION_PREFIX = f"{LOCAL_PRODUCTION_ROOT}/"


@dataclass(frozen=True)
class EnvironmentSpec:
    name: EnvironmentName
    state_root: Path
    data_root: Path
    cache_root: Path
    log_root: Path
    config_file: Path | None
    secrets_file: Path
    log_mode: str
    python_prefix: str | None
    package_prefix: str | None
    install_modes: tuple[str, ...]


def infer_environment(executable: str | None = None) -> EnvironmentName:
    path = str(executable or sys.executable)
    if path.startswith((PRODUCTION_PREFIX, LOCAL_PRODUCTION_PREFIX)):
        return "production"
    return "development"


def parse_environment(value: str | None) -> EnvironmentName:
    text = str(value or "").strip().lower()
    if not text:
        return infer_environment()
    if text not in ENVIRONMENTS:
        raise ValueError("SPC_ENVIRONMENT 必须是 development 或 production")
    return text  # type: ignore[return-value]


def environment_spec(
    name: str | None = None,
    *,
    executable: str | None = None,
) -> EnvironmentSpec:
    resolved = parse_environment(name)
    if resolved == "production":
        runtime_path = str(executable or sys.executable)
        local = runtime_path.startswith(LOCAL_PRODUCTION_PREFIX)
        root = LOCAL_PRODUCTION_ROOT if local else SERVER_PRODUCTION_ROOT
        prefix = LOCAL_PRODUCTION_PREFIX if local else PRODUCTION_PREFIX
        return EnvironmentSpec(
            name="production",
            state_root=root / "state",
            data_root=root / "data",
            cache_root=root / "cache",
            log_root=root / "logs",
            config_file=root / "config" / "spc.toml",
            secrets_file=(
                Path.home() / ".config" / "spc" / "secrets.env"
                if local
                else root / "config" / "secrets.env"
            ),
            log_mode="production",
            python_prefix=prefix,
            package_prefix=prefix,
            install_modes=("installed",),
        )
    home = Path.home()
    return EnvironmentSpec(
        name="development",
        state_root=home / ".spc" / "state",
        data_root=home / ".spc" / "data",
        cache_root=home / ".spc" / "cache",
        log_root=home / ".spc" / "logs",
        config_file=None,
        secrets_file=home / ".config" / "spc" / "secrets.env",
        log_mode="development",
        python_prefix=None,
        package_prefix=None,
        install_modes=("editable", "installed"),
    )


def current_environment() -> EnvironmentName:
    from paperfetch.core.settings import get_settings

    return parse_environment(get_settings().text("SPC_ENVIRONMENT"))


def current_environment_spec() -> EnvironmentSpec:
    return environment_spec(current_environment())


def environment_matches_runtime(
    name: str | None = None,
    *,
    executable: str | None = None,
) -> bool:
    resolved = parse_environment(name) if name is not None else current_environment()
    return resolved == infer_environment(executable)
