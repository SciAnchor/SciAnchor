# -*- coding: utf-8 -*-
"""针对 Issue #12: Preflight 权限探测与 Observability 容错降级回归测试。"""

import os
import stat
import tempfile
from pathlib import Path
import pytest

from paperfetch.cli.system import _path_check, build_preflight_result
from paperfetch.observability import (
    configure_observability,
    emit_event,
    get_event_logger,
    reset_event_state,
)


def test_path_check_detects_unwritable_existing_log_file():
    """测试当日志根目录可写但其中的 spc.log 文件不可写时，_path_check 能正确判定 writable=False。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        log_file = dir_path / "spc.log"
        # 创建只读文件
        log_file.write_text("existing log", encoding="utf-8")
        log_file.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)

        try:
            passed, data = _path_check(dir_path, require_writable=True)
            # 行内注释：必须准确识别出已有日志文件不可写，不得误报 writable=True
            assert passed is False
            assert data["writable"] is False
            assert "unwritable_file" in data
            assert data["unwritable_file"] == str(log_file)
        finally:
            # 恢复写权限以允许临时目录正常清理
            log_file.chmod(stat.S_IWRITE | stat.S_IREAD)


def test_path_check_detects_unwritable_audit_dir():
    """测试当 audit 子目录不可写时，_path_check 能正确判定 writable=False。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        audit_dir = dir_path / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        # 设为只读目录（在 Linux 下取消写权限）
        audit_dir.chmod(stat.S_IREAD | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)

        try:
            passed, data = _path_check(dir_path, require_writable=True)
            # 在非 Windows/支持 chmod 的系统下断言不可写
            if os.name != "nt":
                assert passed is False
                assert data["writable"] is False
        finally:
            audit_dir.chmod(stat.S_IRWXU)


def test_emit_event_gracefully_degrades_when_log_file_permission_denied():
    """测试当日志文件无法写入时，emit_event 不会崩溃抛出 PermissionError，而是安全降级。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        log_file = dir_path / "read_only.log"
        event_file = dir_path / "read_only.events.jsonl"
        for f in (log_file, event_file):
            f.write_text("header\n", encoding="utf-8")
            f.chmod(stat.S_IREAD)

        reset_event_state()
        configure_observability(
            log_file=str(log_file),
            event_file=str(event_file),
            stderr=False,
            mode="development",
        )

        try:
            logger = get_event_logger("test.observability")
            # 行内注释：即使底层日志文件是只读的，emit_event 必须正常完成而不抛出异常
            event = logger.info("测试安全降级日志消息")
            assert (
                event.outcome == "success"
                or event.outcome == "started"
                or event.message == "测试安全降级日志消息"
            )
        finally:
            for f in (log_file, event_file):
                f.chmod(stat.S_IWRITE | stat.S_IREAD)
