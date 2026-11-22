# -*- coding: utf-8 -*-
"""SPC 命令行入口：解析、加载环境、写运行事件，再交给领域分发。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import argparse
import json
import time
from typing import List, Optional

from paperfetch.cli.common import (
    add_runtime_flags,
    configure_standard_stream_encoding,
    validate_parsed_args,
)
from paperfetch.cli.dispatch import dispatch
from paperfetch.cli.register import register_all_commands
from paperfetch.observability import (
    configure_observability,
    current_business_status,
    get_event_logger,
    reset_event_state,
    public_result_projection,
    write_output,
)

logger = get_event_logger("paperfetch.cli")

# 测试与旧导入仍从 root 取这些名字。
_configure_standard_stream_encoding = configure_standard_stream_encoding


class SPCArgumentParser(argparse.ArgumentParser):
    """参数失败也只向 stdout 提交一个稳定 JSON。"""

    def error(self, message: str) -> None:
        from paperfetch.observability.events import redact_sensitive

        payload = {
            "schema": "spc.result.v2",
            "status": "failed",
            "error": {
                "code": "invalid_arguments",
                "message": str(redact_sensitive(message)),
            },
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        raise SystemExit(1)


def _prog_name() -> str:
    """Show whichever entry point was invoked: ``paperfetch`` or its alias ``spc``."""
    invoked = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else ""
    return invoked if invoked in {"paperfetch", "spc"} else "paperfetch"


def build_parser() -> argparse.ArgumentParser:
    """构建唯一 CLI 命令树，供执行、schema 与契约测试共用。"""
    parser = SPCArgumentParser(
        prog=_prog_name(),
        description="paperfetch - Linux 科研资源 CLI（命令别名：spc）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "AGENT QUICKSTART:\n"
            "  浏览命令: spc <domain> --help\n"
            "  查看参数: spc schema <command path>\n"
            "  查看配置: spc schema config\n"
            "  后台终局: spc job wait <job-id> --timeout-seconds 300\n"
            "  默认输出: spc.result.v2 JSON"
        ),
    )
    subparsers = parser.add_subparsers(
        dest="command", metavar="COMMAND", help="子命令列表"
    )
    add_runtime_flags(register_all_commands(subparsers))
    _decorate_command_help(parser)
    return parser


def _decorate_command_help(
    parser: argparse.ArgumentParser, path: tuple[str, ...] = ()
) -> None:
    """让每个 help 直接展示 risk/execution，详细参数仍只由 schema 生成。"""
    from paperfetch.cli.schema import command_metadata

    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        descriptions = {
            choice.dest: choice.help
            for choice in action._choices_actions
            if choice.help and choice.help is not argparse.SUPPRESS
        }
        for name, child in action.choices.items():
            child_path = (*path, name)
            metadata = command_metadata(list(child_path))
            if not child.description:
                child.description = descriptions.get(name, "")
            child.formatter_class = argparse.RawDescriptionHelpFormatter
            child.epilog = (
                f"Risk: {metadata['risk']}\n"
                f"Execution: {metadata['execution']}\n"
                f"Machine contract: spc schema {' '.join(child_path)}"
            )
            _decorate_command_help(child, child_path)


def _main_impl(args_list: Optional[List[str]] = None) -> int:
    """解析参数、加载环境并分发到领域处理器。"""
    parser = build_parser()

    parsed_args = parser.parse_args(
        args_list if args_list is not None else sys.argv[1:]
    )

    if not parsed_args.command:
        parser.print_help()
        return 0

    from dotenv import load_dotenv
    from paperfetch.cli.common import default_secrets_file

    environment_opt = getattr(parsed_args, "environment", None)
    if environment_opt:
        os.environ["SPC_ENVIRONMENT"] = environment_opt
    env_file_opt = getattr(parsed_args, "env_file", None)
    if env_file_opt:
        load_dotenv(env_file_opt, override=True)
    else:
        secrets_path = default_secrets_file()
        if os.path.isfile(secrets_path):
            load_dotenv(secrets_path, override=False)
    if environment_opt:
        os.environ["SPC_ENVIRONMENT"] = environment_opt

    from paperfetch.core.settings import load_settings
    from paperfetch.llm_provider import activate_llm_provider

    activate_llm_provider()

    log_mode = getattr(parsed_args, "log_mode", None)
    log_level = getattr(parsed_args, "log_level", None)
    log_file = getattr(parsed_args, "log_file", None)
    event_file = getattr(parsed_args, "event_file", None)
    no_progress = getattr(parsed_args, "no_progress", False)
    output_format = getattr(parsed_args, "output_format", None)
    verbose = int(getattr(parsed_args, "verbose", 0) or 0)
    debug = bool(getattr(parsed_args, "debug", False))
    if debug:
        log_level = "DEBUG"
    elif verbose and not log_level:
        log_level = "INFO"
    if not event_file and log_file:
        event_file = f"{log_file}.events.jsonl"
    if no_progress or getattr(parsed_args, "output_format", None) == "json":
        os.environ["SPC_NO_PROGRESS"] = "true"
    settings = load_settings()
    configure_observability(
        level=log_level or settings.text("SPC_LOG_LEVEL") or "INFO",
        log_file=log_file or settings.text("SPC_LOG_FILE"),
        event_file=event_file or settings.text("SPC_EVENT_FILE"),
        mode=log_mode or ("development" if verbose or debug else None),
        stderr=output_format != "json" or verbose > 0 or debug,
    )
    logger.info(f"[命令行] 执行子命令，名称={parsed_args.command}")

    invalid = validate_parsed_args(parsed_args)
    if invalid is not None:
        return invalid

    if getattr(parsed_args, "detach", False):
        from paperfetch.jobs import detach

        original_arguments = list(args_list if args_list is not None else sys.argv[1:])
        job_state = detach(original_arguments, cwd=os.getcwd())
        write_output(job_state, pretty=True)
        return 0

    if parsed_args.command == "schema":
        from paperfetch.cli.schema import command_schema

        try:
            schema_payload = command_schema(parser, list(parsed_args.command_path))
        except ValueError as exc:
            write_output(
                {
                    "schema": "spc.result.v2",
                    "status": "failed",
                    "error": {
                        "code": "invalid_command_path",
                        "message": str(exc),
                    },
                },
                pretty=True,
            )
            return 1
        except Exception:
            write_output(
                {
                    "schema": "spc.result.v2",
                    "status": "failed",
                    "error": {
                        "code": "schema_generation_failed",
                        "message": "无法生成命令 Schema；使用 --debug 或 --log-file 保存详细诊断",
                    },
                },
                pretty=True,
            )
            return 1
        write_output(schema_payload, pretty=True)
        return 0

    try:
        return dispatch(parsed_args)
    except Exception as e:
        error = {
            "schema": "spc.result.v2",
            "status": "failed",
            "error": {
                "code": "internal_error",
                "message": "SPC 内部错误；使用 --debug 或 --log-file 保存详细诊断",
            },
        }
        write_output(error, pretty=output_format == "json")
        if os.getenv("SPC_LOG_LEVEL", "").upper() == "DEBUG" or log_level == "DEBUG":
            logger.exception(f"[命令行] 命令执行失败，原因={e}")
        return 1


def _main(args_list: Optional[List[str]] = None) -> int:
    """公共 CLI 调用只在本调用内启用 v2 投影。"""
    raw_args = list(args_list if args_list is not None else sys.argv[1:])
    text_requested = any(
        raw_args[index] in {"--output-format", "--format"}
        and index + 1 < len(raw_args)
        and raw_args[index + 1] == "text"
        for index in range(len(raw_args))
    )
    with public_result_projection(not text_requested):
        return _main_impl(args_list)


def _run_command_with_events(args_list: Optional[List[str]] = None) -> int:
    """建立运行上下文并保证每个命令恰好产生一个最终事件。"""
    _configure_standard_stream_encoding()
    run_id = reset_event_state(os.getenv("SPC_RUN_ID"))
    raw_args = args_list if args_list is not None else sys.argv[1:]
    command = next(
        (item for item in raw_args if item and not item.startswith("-")), "help"
    )
    started = time.perf_counter()
    try:
        exit_code = _main(args_list)
    except SystemExit:
        raise
    except BaseException as exc:
        try:
            logger.event(
                "cli.command.terminal",
                phase="command",
                action=command,
                outcome="failed",
                terminal=True,
                level="ERROR",
                run_id=run_id,
                task_id=command,
                error_class=type(exc).__name__,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                message=f"命令异常终止: {exc}",
            )
        except BaseException as inner_exc:
            sys.stderr.write(f"[错误] 无法记录命令终止事件: {inner_exc}\n")
            sys.stderr.flush()
        raise
    action = raw_args[1] if len(raw_args) > 1 else None
    readiness_gate = exit_code == 2 and (
        (command == "dataset" and action in {"readiness", "handoff"})
        or (command == "workflow" and action in {"check", "prepare", "status"})
    )
    business_status = current_business_status()
    partial = business_status == "partial"
    rejected = business_status == "rejected"
    logger.event(
        "cli.command.terminal",
        phase="command",
        action=command,
        outcome="success"
        if exit_code == 0
        else "partial"
        if partial
        else "blocked"
        if readiness_gate or rejected
        else "failed",
        terminal=True,
        level="INFO"
        if exit_code == 0
        else "WARNING"
        if partial or readiness_gate or rejected
        else "ERROR",
        run_id=run_id,
        task_id=command,
        error_class=(
            None
            if exit_code == 0
            else "partial_result"
            if partial
            else "readiness_not_allowed"
            if readiness_gate or rejected
            else f"exit_code_{exit_code}"
        ),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        message=(
            f"{command} 成功"
            if exit_code == 0
            else f"{command} 部分完成；请按业务结果中的 error 处理未完成阶段"
            if partial
            else f"{command} 已完成，但就绪门禁未通过"
            if readiness_gate or rejected
            else f"{command} 失败，退出码={exit_code}"
        ),
    )
    return exit_code


def main(args_list: Optional[List[str]] = None) -> int:
    """运行一个 CLI 任务。"""
    return _run_command_with_events(args_list)
