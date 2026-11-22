# -*- coding: utf-8 -*-
"""CLI 启动共享：编码、环境与运行时旗标。"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Optional

from paperfetch.observability import get_event_logger

logger = get_event_logger("paperfetch.cli")


def default_secrets_file() -> str:
    from paperfetch.core.environment import environment_spec, parse_environment

    return str(
        environment_spec(
            parse_environment(os.environ.get("SPC_ENVIRONMENT"))
        ).secrets_file
    )


def configure_standard_stream_encoding() -> None:
    """Windows/重定向控制台统一使用 UTF-8，避免 JSON 输出因本地代码页中断。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def add_runtime_flags(parsers: Iterable[argparse.ArgumentParser]) -> None:
    for sp in parsers:
        output_action = next(
            (action for action in sp._actions if action.dest == "output_format"), None
        )
        if output_action is not None and "--format" not in sp._option_string_actions:
            output_action.option_strings.append("--format")
            sp._option_string_actions["--format"] = output_action
        sp.add_argument(
            "--environment",
            choices=["development", "production"],
            default=None,
            help="SPC_ENVIRONMENT：development 本机开发树，production 本机或服务器正式安装",
        )
        sp.add_argument(
            "--env-file", type=str, default=None, help="加载的 .env 凭证路径"
        )
        sp.add_argument(
            "--no-progress", action="store_true", help="关闭动态进度条，仅输出稳定日志"
        )
        sp.add_argument(
            "-v",
            "--verbose",
            action="count",
            default=0,
            help="向 stderr 输出阶段进度；可重复",
        )
        sp.add_argument(
            "--debug", action="store_true", help="启用详细诊断；业务 JSON 仍只写 stdout"
        )
        sp.add_argument(
            "--log-mode",
            choices=["development", "production"],
            default=None,
            help="development 输出详细诊断；production 仅输出用户进度和告警",
        )
        sp.add_argument(
            "--log-level",
            choices=["DEBUG", "INFO", "WARNING", "ERROR"],
            default=None,
            help="日志级别",
        )
        sp.add_argument(
            "--log-file",
            type=str,
            default=None,
            help="将完整 UTF-8 日志同时写入指定文件",
        )
        sp.add_argument(
            "--event-file", type=str, default=None, help="写入脱敏的结构化 JSONL 事件流"
        )


def validate_parsed_args(parsed_args: argparse.Namespace) -> Optional[int]:
    """参数范围检测。返回退出码；通过则返回 None。"""
    if (
        parsed_args.command == "seed-pack"
        and parsed_args.seed_pack_action == "enrich"
        and parsed_args.parse_only
        and parsed_args.download_only
    ):
        logger.error("--parse-only 与 --download-only 不能同时指定")
        return 1
    is_geo_download = (
        parsed_args.command == "dataset"
        and getattr(parsed_args, "dataset_action", None) == "geo"
        and getattr(parsed_args, "dataset_source_action", None) == "download"
    )
    is_dryad_download = (
        parsed_args.command == "dataset"
        and getattr(parsed_args, "dataset_action", None) == "dryad"
        and getattr(parsed_args, "dataset_source_action", None) == "download"
    )
    if is_geo_download and parsed_args.max_size_gb <= 0:
        logger.error("--max-size-gb 必须大于 0")
        return 1
    if is_dryad_download and parsed_args.max_size_gb <= 0:
        logger.error("--max-size-gb 必须大于 0")
        return 1
    if (
        is_geo_download or is_dryad_download
    ) and not 1 <= parsed_args.dataset_concurrency <= 4:
        logger.error("--dataset-concurrency 必须在 1 到 4 之间")
        return 1
    if (is_geo_download or is_dryad_download) and parsed_args.lock_timeout_seconds <= 0:
        logger.error("--lock-timeout-seconds 必须大于 0")
        return 1
    return None
