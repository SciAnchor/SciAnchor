"""SPC 2.0 唯一配置注册表与加载器。

字段名、类型、默认值、密级、所属能力只在本模块声明一次。
业务代码读 get_settings() / capability_proxy()，禁止再散落 os.getenv。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

Kind = Literal["str", "int", "float", "bool", "secret"]
Secrecy = Literal["public", "secret"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: Kind
    default: Any
    secrecy: Secrecy
    capability: str
    description: str
    allow_process_override: bool = True


def _field(
    name: str,
    kind: Kind,
    default: Any,
    *,
    capability: str,
    description: str,
    secrecy: Secrecy = "public",
) -> FieldSpec:
    return FieldSpec(
        name=name,
        kind=kind,
        default=default,
        secrecy=secrecy,
        capability=capability,
        description=description,
    )


SETTINGS_FIELDS: tuple[FieldSpec, ...] = (
    _field(
        "SPC_ENVIRONMENT",
        "str",
        None,
        capability="system.core",
        description="development 或 production；未设则按解释器位置推断",
    ),
    _field(
        "SPC_STATE_ROOT",
        "str",
        None,
        capability="system.core",
        description="运行状态根",
    ),
    _field(
        "SPC_CACHE_ROOT", "str", None, capability="system.core", description="缓存根"
    ),
    _field(
        "SPC_DATA_ROOT", "str", None, capability="system.core", description="数据根"
    ),
    _field(
        "SPC_CONFIG_FILE",
        "str",
        None,
        capability="system.core",
        description="非密 spc.toml 路径",
    ),
    _field(
        "SPC_LOG_MODE",
        "str",
        None,
        capability="system.core",
        description="development 或 production",
    ),
    _field(
        "SPC_LOG_LEVEL", "str", "INFO", capability="system.core", description="日志级别"
    ),
    _field(
        "SPC_LOG_FILE",
        "str",
        None,
        capability="system.core",
        description="UTF-8 日志文件",
    ),
    _field(
        "SPC_EVENT_FILE",
        "str",
        None,
        capability="system.core",
        description="脱敏事件 JSONL",
    ),
    _field(
        "SPC_NO_PROGRESS",
        "bool",
        False,
        capability="system.core",
        description="关闭动态进度",
    ),
    _field("SPC_RUN_ID", "str", None, capability="system.core", description="运行标识"),
    _field("SPC_JOB_ID", "str", None, capability="system.core", description="作业标识"),
    _field(
        "SPC_JOB_ROOT", "str", None, capability="system.core", description="作业状态根"
    ),
    _field(
        "SPC_HOST_ID", "str", None, capability="system.core", description="主机标识"
    ),
    _field(
        "SPC_PHASE1_PAPER_CONCURRENCY",
        "int",
        2,
        capability="paper.download",
        description="第一阶段论文并发",
    ),
    _field(
        "SPC_EXIT_IP_PROBE_URL",
        "secret",
        None,
        capability="system.core",
        description="出口探测 URL，不输出实值",
    ),
    _field(
        "SPC_DRYAD_DATA_ROOT",
        "str",
        None,
        capability="dataset.dryad",
        description="Dryad 数据根",
    ),
    _field(
        "SPC_GEO_DATA_ROOT",
        "str",
        None,
        capability="dataset.geo",
        description="GEO 数据根",
    ),
    _field(
        "SPC_GEO_MAX_DOWNLOAD_GB",
        "float",
        None,
        capability="dataset.geo",
        description="GEO 下载上限 GB",
    ),
    _field(
        "SPC_GEO_CONNECT_TIMEOUT",
        "float",
        30.0,
        capability="dataset.geo",
        description="GEO 连接超时",
    ),
    _field(
        "SPC_GEO_READ_TIMEOUT",
        "float",
        60.0,
        capability="dataset.geo",
        description="GEO 读取超时",
    ),
    _field(
        "SPC_GEO_PROGRESS_BYTES",
        "int",
        10485760,
        capability="dataset.geo",
        description="GEO 进度更新字节间隔",
    ),
    _field(
        "SPC_GEO_PROGRESS_INTERVAL",
        "float",
        2.0,
        capability="dataset.geo",
        description="GEO 进度更新时间间隔",
    ),
    _field(
        "SPC_GEO_PROXY",
        "secret",
        None,
        capability="dataset.geo",
        description="GEO 代理 URL",
    ),
    _field(
        "SPC_GEO_PROXY_MODE",
        "str",
        "direct",
        capability="dataset.geo",
        description="GEO 代理模式",
    ),
    _field(
        "SPC_GEO_STREAM_RETRIES",
        "int",
        3,
        capability="dataset.geo",
        description="GEO 流重试次数",
    ),
    _field(
        "SPC_API_KEY_STATE_DB",
        "str",
        None,
        capability="paper.metadata",
        description="API key 状态库",
    ),
    _field(
        "SPC_CODE_AUDIT_TIMEOUT_SECONDS",
        "float",
        30.0,
        capability="system.core",
        description="代码审计超时",
    ),
    _field(
        "SPC_METADATA_CACHE_DB",
        "str",
        None,
        capability="paper.metadata",
        description="元数据缓存库",
    ),
    _field(
        "SPC_JOURNAL_MASTER_DB",
        "str",
        None,
        capability="paper.metadata",
        description="用户自备的期刊主库 SQLite（CAS 分区等受限数据），未配置时相关字段为空",
    ),
    _field(
        "SPC_BIOMEDICAL_DATA_ROOT",
        "str",
        None,
        capability="dataset.biomedical",
        description="生物医学数据根",
    ),
    _field(
        "SPC_DOWNLOAD_COORDINATION_ROOT",
        "str",
        None,
        capability="dataset",
        description="数据下载协调根",
    ),
    _field(
        "METADATA_PROXY",
        "secret",
        None,
        capability="paper.metadata",
        description="元数据能力代理 URL",
    ),
    _field(
        "DOWNLOAD_PROXY",
        "secret",
        None,
        capability="paper.download",
        description="公开下载能力代理 URL",
    ),
    _field(
        "MINERU_PROXY",
        "secret",
        None,
        capability="paper.parse",
        description="MinerU 能力代理 URL",
    ),
    _field(
        "ARCHIVE_PROXY",
        "secret",
        None,
        capability="dataset.archive",
        description="归档能力代理 URL",
    ),
    _field(
        "DOWNLOAD_PROXY_MODE",
        "str",
        "route-aware",
        capability="paper.download",
        description="公开下载代理模式",
    ),
    _field(
        "PDF_DOWNLOAD_NO_PROXY",
        "bool",
        False,
        capability="paper.download",
        description="公开下载强制直连",
    ),
    _field(
        "PDF_DOWNLOAD_NO_PROXY_ROUTES",
        "str",
        "public_http,public_browser,elsevier_api,publisher_api_springer",
        capability="paper.download",
        description="route-aware 下直连的公开路由",
    ),
    _field(
        "ARCHIVE_PROXY_MODE",
        "str",
        "direct",
        capability="dataset.archive",
        description="归档代理模式",
    ),
    _field(
        "METADATA_CONNECT_TIMEOUT",
        "float",
        10.0,
        capability="paper.metadata",
        description="元数据连接超时",
    ),
    _field(
        "METADATA_READ_TIMEOUT",
        "float",
        20.0,
        capability="paper.metadata",
        description="元数据读超时",
    ),
    _field(
        "METADATA_WRITE_TIMEOUT",
        "float",
        15.0,
        capability="paper.metadata",
        description="元数据写超时",
    ),
    _field(
        "METADATA_POOL_TIMEOUT",
        "float",
        15.0,
        capability="paper.metadata",
        description="元数据连接池超时",
    ),
    _field(
        "HTTP_RETRY_AFTER_MAX_SECONDS",
        "float",
        120.0,
        capability="system.core",
        description="Retry-After 上限",
    ),
)

SETTINGS_BY_NAME: dict[str, FieldSpec] = {item.name: item for item in SETTINGS_FIELDS}

CAPABILITY_PROXY_ENV = {
    "metadata": "METADATA_PROXY",
    "download": "DOWNLOAD_PROXY",
    "mineru": "MINERU_PROXY",
    "archive": "ARCHIVE_PROXY",
}
CAPABILITY_PROXY_NAMES = frozenset(CAPABILITY_PROXY_ENV.values())

_MANAGED_PREFIXES = ("SPC_",)
_MANAGED_EXACT = CAPABILITY_PROXY_NAMES | frozenset(
    {
        "DOWNLOAD_PROXY_MODE",
        "ARCHIVE_PROXY_MODE",
        "METADATA_PROXY_MODE",
        "PDF_DOWNLOAD_PROXY_MODE",
        "PDF_DOWNLOAD_NO_PROXY",
        "PDF_DOWNLOAD_NO_PROXY_ROUTES",
        "CHROME_EXECUTABLE_PATH",
    }
)

_loaded: Settings | None = None


class Settings:
    """已解析的配置快照。密级字段可读取，schema 与日志不得输出实值。"""

    def __init__(self, values: dict[str, Any]):
        self._values = dict(values)

    def get(self, name: str) -> Any:
        spec = SETTINGS_BY_NAME.get(name)
        if spec is None:
            raise KeyError(f"未注册配置：{name}")
        if name in self._values:
            return self._values[name]
        return spec.default

    def text(self, name: str) -> str | None:
        value = self.get(name)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def boolean(self, name: str) -> bool:
        value = self.get(name)
        if isinstance(value, bool):
            return value
        return _parse_bool(value, SETTINGS_BY_NAME[name].default)

    def integer(self, name: str, minimum: int | None = None) -> int:
        spec = SETTINGS_BY_NAME[name]
        try:
            parsed = int(self.get(name))
        except (TypeError, ValueError):
            parsed = int(spec.default)
        if minimum is not None:
            return max(minimum, parsed)
        return parsed

    def number(self, name: str, minimum: float | None = None) -> float:
        spec = SETTINGS_BY_NAME[name]
        try:
            parsed = float(self.get(name))
        except (TypeError, ValueError):
            parsed = float(spec.default)
        if minimum is not None:
            return max(minimum, parsed)
        return parsed


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce(spec: FieldSpec, raw: Any) -> Any:
    if raw is None:
        return spec.default
    if spec.kind == "bool":
        return _parse_bool(raw, bool(spec.default))
    if spec.kind == "int":
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return spec.default
    if spec.kind == "float":
        try:
            return float(str(raw).strip())
        except (TypeError, ValueError):
            return spec.default
    text = str(raw).strip().strip("'\"")
    if spec.kind == "secret":
        return text or None
    return text or None if spec.default is None else (text or spec.default)


def _toml_settings(path: str | None) -> dict[str, Any]:
    resolved = Path(path or "").expanduser()
    if not str(resolved) or str(resolved) == "." or not resolved.is_file():
        return {}
    payload = tomllib.loads(resolved.read_text(encoding="utf-8"))
    section = payload.get("settings")
    if not isinstance(section, dict):
        return {}
    values: dict[str, Any] = {}
    for key, raw in section.items():
        name = str(key)
        spec = SETTINGS_BY_NAME.get(name)
        if spec is None:
            raise ValueError(f"spc.toml 含未注册配置：{name}")
        if spec.secrecy == "secret":
            raise ValueError(f"密级配置不得写入 spc.toml：{name}")
        values[name] = _coerce(spec, raw)
    return values


def load_settings(
    *, config_file: str | None = None, environ: dict[str, str] | None = None
) -> Settings:
    """按 代码默认 → 非密 toml → 进程环境 加载。dotenv 必须已先执行。"""

    env = environ if environ is not None else os.environ
    values = {spec.name: spec.default for spec in SETTINGS_FIELDS}
    toml_path = config_file or (env.get("SPC_CONFIG_FILE") or "").strip() or None
    values.update(_toml_settings(toml_path))
    for spec in SETTINGS_FIELDS:
        if spec.name not in env:
            continue
        if not spec.allow_process_override:
            continue
        values[spec.name] = _coerce(spec, env.get(spec.name))
    from paperfetch.core.environment import parse_environment

    values["SPC_ENVIRONMENT"] = parse_environment(values.get("SPC_ENVIRONMENT"))
    global _loaded
    _loaded = Settings(values)
    return _loaded


def get_settings() -> Settings:
    if _loaded is None:
        return load_settings()
    return _loaded


def reset_settings() -> None:
    global _loaded
    _loaded = None


def _normalize_proxy(value: str | None) -> str | None:
    text = (value or "").strip().strip("'\"").strip()
    if not text or text.casefold() in {
        "0",
        "false",
        "no",
        "off",
        "none",
        "null",
        "disabled",
        "direct",
    }:
        return None
    return text


def capability_proxy(name: str) -> str | None:
    """返回指定能力的代理 URL。能力之间互不复用。"""

    key = str(name or "").strip()
    env_name = CAPABILITY_PROXY_ENV.get(key.lower(), key.upper())
    if env_name not in CAPABILITY_PROXY_NAMES:
        raise ValueError(f"未知能力代理：{name}")
    return _normalize_proxy(get_settings().text(env_name))


def unknown_settings_env(environ: dict[str, str] | None = None) -> list[str]:
    """返回受管前缀或代理家族中未注册的名字。"""

    env = environ if environ is not None else os.environ
    unknown: list[str] = []
    for name in env:
        managed = name in _MANAGED_EXACT or name.startswith(_MANAGED_PREFIXES)
        if not managed:
            continue
        if name not in SETTINGS_BY_NAME:
            unknown.append(name)
    return sorted(unknown)


def config_schema_payload() -> dict[str, Any]:
    """spc schema config 的公共载荷。不输出密级实值。"""

    from paperfetch.core.environment import (
        ENVIRONMENTS,
        current_environment_spec,
        infer_environment,
    )

    environment = current_environment_spec()

    fields = [
        {
            "name": spec.name,
            "type": spec.kind,
            "default": None if spec.secrecy == "secret" else spec.default,
            "secrecy": spec.secrecy,
            "capability": spec.capability,
            "description": spec.description,
            "allow_process_override": spec.allow_process_override,
        }
        for spec in SETTINGS_FIELDS
    ]
    return {
        "schema": "spc.result.v2",
        "status": "completed",
        "data": {
            "command": "config",
            "fields": fields,
            "unknown_env": unknown_settings_env(),
            "environment": {
                "current": environment.name,
                "inferred": infer_environment(),
                "choices": list(ENVIRONMENTS),
                "matches_runtime": environment.name == infer_environment(),
                "secrets_file": str(environment.secrets_file),
                "state_root": str(environment.state_root),
                "data_root": str(environment.data_root),
                "cache_root": str(environment.cache_root),
                "log_root": str(environment.log_root),
                "log_mode": environment.log_mode,
            },
        },
    }


def write_settings_schema_json(path: Path | None = None) -> Path:
    import json

    target = path or (
        Path(__file__).resolve().parents[1] / "data" / "config" / "settings.schema.json"
    )
    payload = {
        "schema": "spc.settings.v1",
        "fields": [
            {
                "name": spec.name,
                "type": spec.kind,
                "default": None if spec.secrecy == "secret" else spec.default,
                "secrecy": spec.secrecy,
                "capability": spec.capability,
                "description": spec.description,
            }
            for spec in SETTINGS_FIELDS
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def iter_field_names() -> Iterable[str]:
    return (spec.name for spec in SETTINGS_FIELDS)
