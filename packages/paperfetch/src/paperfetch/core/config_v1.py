"""SPC 非敏感运行 Profile。名字与 SPC_ENVIRONMENT 相同：development / production。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from paperfetch.core.environment import environment_spec


class RuntimeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["linux"]
    install_modes: list[Literal["installed", "editable"]]
    python_minor: Literal["3.12"] = "3.12"
    python_executable_prefix: str | None = None
    package_path_prefix: str | None = None
    state_root: Path
    data_root: Path
    cache_root: Path
    log_root: Path
    required_capabilities: list[str] = Field(default_factory=lambda: ["system.core"])


class SpcConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: dict[str, RuntimeProfile]


def _configured_path(name: str) -> str:
    from paperfetch.core.settings import get_settings

    return (get_settings().text(name) or "").strip()


def _environment_roots():
    from paperfetch.core.settings import get_settings

    return environment_spec(get_settings().text("SPC_ENVIRONMENT"))


def runtime_state_root() -> Path:
    configured = _configured_path("SPC_STATE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return _environment_roots().state_root


def runtime_cache_root() -> Path:
    configured = _configured_path("SPC_CACHE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return _environment_roots().cache_root


def runtime_data_root() -> Path:
    configured = _configured_path("SPC_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return _environment_roots().data_root


def builtin_config() -> SpcConfig:
    """返回不含凭证的内置 Profile；路径可由正式 spc.toml 覆盖。"""

    development = environment_spec("development")
    production = environment_spec("production")
    return SpcConfig(
        profiles={
            "development": RuntimeProfile(
                platform="linux",
                install_modes=["editable", "installed"],
                state_root=development.state_root,
                data_root=development.data_root,
                cache_root=development.cache_root,
                log_root=development.log_root,
            ),
            "production": RuntimeProfile(
                platform="linux",
                install_modes=["installed"],
                python_executable_prefix=production.python_prefix,
                package_path_prefix=production.package_prefix,
                state_root=production.state_root,
                data_root=production.data_root,
                cache_root=production.cache_root,
                log_root=production.log_root,
            ),
        }
    )


def load_config(path: str | os.PathLike[str] | None = None) -> tuple[SpcConfig, str]:
    """读取强类型非敏感配置；未提供文件时使用内置 Profile。"""

    resolved = Path(path or _configured_path("SPC_CONFIG_FILE") or "").expanduser()
    if not str(resolved) or str(resolved) == ".":
        return builtin_config(), "builtin"
    payload = tomllib.loads(resolved.read_text(encoding="utf-8"))
    return SpcConfig.model_validate(payload), str(resolved.resolve())
