from __future__ import annotations

from pathlib import Path

import pytest

from paperfetch.runtime_paths import configured_path


def test_windows_rejects_linux_absolute_path_before_resolution():
    with pytest.raises(ValueError, match="Linux 路径"):
        configured_path(
            "SPC_JOURNAL_MASTER_DB", "/opt/data/journal_master.db", system="Windows"
        )


def test_linux_rejects_windows_drive_path_before_resolution():
    with pytest.raises(ValueError, match="Windows 路径"):
        configured_path(
            "SPC_JOURNAL_MASTER_DB",
            "D:/Research/spc-data/journal_master.db",
            system="Linux",
        )


def test_platform_native_path_is_resolved(tmp_path: Path):
    result = configured_path("SPC_JOURNAL_MASTER_DB", tmp_path / "journal_master.db")

    assert result == (tmp_path / "journal_master.db").resolve()
