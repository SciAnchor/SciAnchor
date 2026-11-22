# -*- coding: utf-8 -*-
"""诊断、作业与验证命令注册。"""

from __future__ import annotations


def register_ops_commands(subparsers):
    """注册诊断、作业与验证。"""
    version_parser = subparsers.add_parser(
        "version", help="输出版本、Git SHA 与运行来源"
    )
    version_parser.add_argument(
        "--output-format", type=str, choices=["text", "json"], default="json"
    )

    schema_parser = subparsers.add_parser(
        "schema", help="查看当前 CLI 命令参数、配置契约、风险和执行契约"
    )
    schema_parser.add_argument(
        "command_path",
        nargs="*",
        help="命令路径，例如 paper download；config 输出配置注册表",
    )
    schema_parser.add_argument("--output-format", choices=["json"], default="json")

    validate_parser = subparsers.add_parser("validate", help="真实验证公开下载能力")
    validate_subparsers = validate_parser.add_subparsers(
        dest="validate_action", required=True
    )

    download_validation_parser = validate_subparsers.add_parser(
        "download",
        help="使用固定真实样本连续验收 SPC PDF 下载质量与性能",
    )
    download_validation_parser.add_argument(
        "--suite", type=str, default=None, help="下载验收样本 JSON；默认使用内置样本"
    )
    download_validation_parser.add_argument(
        "--profile",
        choices=["smoke", "oa", "biomedical_oa", "full"],
        default="smoke",
    )
    download_validation_parser.add_argument(
        "--rounds", type=int, default=3, help="隔离缓存连续验收轮数"
    )
    download_validation_parser.add_argument(
        "--publisher", type=str, default=None, help="仅验收指定出版社，可逗号分隔"
    )
    download_validation_parser.add_argument(
        "--sample", type=str, default=None, help="仅验收指定样本 ID，可逗号分隔"
    )
    download_validation_parser.add_argument(
        "--output-dir", type=str, default=".spc_cache/download_validation"
    )
    download_validation_parser.add_argument(
        "--minimum-success-rate", type=float, default=1.0
    )
    download_validation_parser.add_argument(
        "--maximum-phase1-p95-ms", type=int, default=12500
    )
    download_validation_parser.add_argument(
        "--maximum-phase1-paper-ms", type=int, default=47000
    )
    download_validation_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )
    job_parser = subparsers.add_parser("job", help="列出、查看、等待或取消后台任务")
    job_subparsers = job_parser.add_subparsers(dest="job_action", required=True)
    job_action_parsers = []
    job_list_parser = job_subparsers.add_parser("list", help="列出最近的后台任务")
    job_list_parser.add_argument("--limit", type=int, default=20)
    job_list_parser.add_argument("--output-format", choices=["json"], default="json")
    job_action_parsers.append(job_list_parser)
    for action in ("show", "cancel"):
        action_parser = job_subparsers.add_parser(action)
        action_parser.add_argument("job_id")
        action_parser.add_argument("--output-format", choices=["json"], default="json")
        job_action_parsers.append(action_parser)
    job_wait_parser = job_subparsers.add_parser(
        "wait", help="等待任务并直接返回原命令最终结果"
    )
    job_wait_parser.add_argument("job_id")
    job_wait_parser.add_argument("--timeout-seconds", type=float, default=300.0)
    job_wait_parser.add_argument("--output-format", choices=["json"], default="json")
    job_action_parsers.append(job_wait_parser)
    return [
        version_parser,
        schema_parser,
        download_validation_parser,
        *job_action_parsers,
    ]
