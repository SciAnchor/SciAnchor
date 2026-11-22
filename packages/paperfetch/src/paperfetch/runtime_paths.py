"""Cross-platform validation for configured runtime paths."""

from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import Optional


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def configured_path(
    name: str,
    value: str | Path,
    *,
    system: Optional[str] = None,
) -> Path:
    """Resolve a configured path only when it matches the current platform."""

    raw = str(value).strip()
    current = (system or platform.system()).strip().lower()
    if current == "windows" and raw.startswith("/"):
        raise ValueError(
            f"{name} 使用了 Linux 路径，Windows 环境必须配置盘符路径: {raw}"
        )
    if current != "windows" and _WINDOWS_DRIVE.match(raw):
        raise ValueError(
            f"{name} 使用了 Windows 路径，Linux 环境必须配置 POSIX 路径: {raw}"
        )
    return Path(raw).expanduser().resolve()
