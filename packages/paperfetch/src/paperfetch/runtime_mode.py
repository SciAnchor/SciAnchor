"""SPC development / production 输出模式。默认跟随 SPC_ENVIRONMENT。"""

from __future__ import annotations

from typing import Literal, Optional, cast


LogMode = Literal["development", "production"]
LOG_MODES = frozenset({"development", "production"})


def resolve_log_mode(value: Optional[str] = None) -> LogMode:
    """解析显式参数、已加载 Settings，或当前环境的默认日志模式。"""

    if value is not None:
        resolved = str(value).strip().lower()
    else:
        from paperfetch.core.environment import current_environment_spec
        from paperfetch.core.settings import get_settings

        configured = get_settings().text("SPC_LOG_MODE")
        resolved = (configured or current_environment_spec().log_mode).strip().lower()
    if resolved not in LOG_MODES:
        raise ValueError(
            f"无效的 SPC_LOG_MODE={resolved!r}；仅支持 development 或 production"
        )
    return cast(LogMode, resolved)
