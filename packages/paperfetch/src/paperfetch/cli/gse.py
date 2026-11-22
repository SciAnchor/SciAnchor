"""GEO 数据获取命令适配器。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from paperfetch.datasets.acquisition import (
    AcquisitionBusy,
    AcquisitionConfigurationError,
    error_payload,
)
from paperfetch.datasets.geo import (
    GeoDataError,
    GeoDatasetStore,
    GeoLargeDownloadBlocked,
)
from paperfetch.observability import get_event_logger, write_output

logger = get_event_logger("paperfetch.datasets.geo")


def _file_names(value: str | None) -> list[str] | None:
    if not value:
        return None
    names = [item.strip() for item in value.split(",") if item.strip()]
    return names or None


def _format_bytes(value: int) -> str:
    amount = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def _emit_download_text(result: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        totals = result["totals"]
        gate = result["size_gate"]
        write_output(
            f"{result['gse_id']}：文件数={totals['files']}，"
            f"已知大小={_format_bytes(totals['known_bytes'])}，已阻断={gate['blocked']}"
        )
        for item in result["files"]:
            size = (
                "未知"
                if item["size_bytes"] is None
                else _format_bytes(item["size_bytes"])
            )
            write_output(f"- {item['kind']}：{item['filename']}（{size}）")
        return
    files = result.get("files", {})
    write_output(
        f"{result['gse_id']}：状态={result['status']}，"
        f"完成={files.get('complete', 0)}/{files.get('total', 0)}，"
        f"已下载={_format_bytes(files.get('downloaded_bytes', 0))}"
    )
    write_output(f"  归档：{result.get('archive_path', '-')}")
    if result.get("last_error"):
        write_output(f"  错误：{result['last_error']}")


def run_download_gse(parsed_args: Any) -> int:
    names = _file_names(parsed_args.files)
    concurrency = int(parsed_args.dataset_concurrency)

    def process(gse_id: str) -> tuple[dict[str, Any], int]:
        try:
            with GeoDatasetStore(
                parsed_args.output_dir,
                max_download_gb=parsed_args.max_size_gb,
                dataset_concurrency=concurrency,
                lock_timeout_seconds=parsed_args.lock_timeout_seconds,
            ) as store:
                if parsed_args.dry_run:
                    result = store.plan(gse_id, names)
                else:
                    result = store.download(
                        gse_id,
                        filenames=names,
                        force=parsed_args.force,
                        allow_large=parsed_args.allow_large,
                    )
                    if result["status"] != "complete":
                        return result, 2
                return result, 0
        except GeoLargeDownloadBlocked as exc:
            failure = error_payload(exc)
            return {
                **exc.plan,
                "status": "blocked",
                **failure,
                "error": failure["message"],
            }, 2
        except (AcquisitionBusy, AcquisitionConfigurationError) as exc:
            failure = error_payload(exc)
            return {
                "schema_version": "spc.geo.command-result.v1",
                "gse_id": str(gse_id).upper(),
                "status": "failed",
                **failure,
                "error": failure["message"],
            }, 3 if isinstance(exc, AcquisitionBusy) else 1
        except (GeoDataError, OSError) as exc:
            failure = error_payload(exc)
            result = {
                "schema_version": "spc.geo.command-result.v1",
                "gse_id": str(gse_id).upper(),
                "status": "failed",
                **failure,
                "error": failure["message"],
            }
            logger.error(
                "GEO 数据处理失败",
                error_class=failure["error_class"],
                diagnostics={
                    "gse_id": gse_id,
                    "error_code": failure["error_code"],
                    "exception_type": type(exc).__name__,
                },
            )
            return result, 2

    if len(parsed_args.gse_ids) == 1 or concurrency == 1:
        outcomes = [process(gse_id) for gse_id in parsed_args.gse_ids]
    else:
        with ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="spc-geo"
        ) as executor:
            outcomes = list(executor.map(process, parsed_args.gse_ids))
    results = [item[0] for item in outcomes]
    exit_code = max((item[1] for item in outcomes), default=0)

    payload = {
        "schema_version": "spc.geo.batch-result.v1",
        "mode": "plan" if parsed_args.dry_run else "download",
        "results": results,
    }
    if parsed_args.output_format == "json":
        write_output(payload, pretty=True)
    else:
        for result in results:
            if result.get("status") == "failed":
                write_output(
                    f"{result['gse_id']}：失败 - "
                    f"{result.get('error_code', 'unclassified_error')}：{result['error']}"
                )
            elif result.get("status") == "blocked":
                _emit_download_text(result, dry_run=True)
                write_output(
                    f"  已阻断：请使用 {result['size_gate']['approval_flag']} 明确授权后重试"
                )
            else:
                _emit_download_text(result, dry_run=parsed_args.dry_run)
    return exit_code


def run_inspect_gse(parsed_args: Any) -> int:
    with GeoDatasetStore(parsed_args.output_dir) as store:
        if parsed_args.gse_ids:
            results = [
                store.inspect(gse_id, verify=parsed_args.verify)
                for gse_id in parsed_args.gse_ids
            ]
        else:
            results = store.list_local(verify=parsed_args.verify)
    payload = {
        "schema_version": "spc.geo.inspect-result.v1",
        "results": results,
    }
    if parsed_args.output_format == "json":
        write_output(payload, pretty=True)
    elif not results:
        write_output("没有本地 GSE 数据集。")
    else:
        for result in results:
            _emit_download_text(result, dry_run=False)
    return (
        1
        if parsed_args.gse_ids
        and any(item["status"] == "not_downloaded" for item in results)
        else 0
    )


def register_gse_dataset_commands(dataset_subparsers):
    """注册 dataset geo download/inspect。"""
    from paperfetch.cli.common import env_float as _env_float, env_int as _env_int

    geo_parser = dataset_subparsers.add_parser("geo", help="管理公开 GEO GSE 数据集")
    geo_subparsers = geo_parser.add_subparsers(
        dest="dataset_source_action", required=True
    )
    download_gse_parser = geo_subparsers.add_parser(
        "download",
        help="下载并归档一个或多个公开 GEO GSE 数据集",
    )
    download_gse_parser.add_argument(
        "gse_ids", nargs="+", help="GSE 编号，可一次传入多个"
    )
    download_gse_parser.add_argument(
        "--output-dir", type=str, default=None, help="GEO 数据根目录"
    )
    download_gse_parser.add_argument(
        "--files", type=str, default=None, help="只下载指定文件，逗号分隔"
    )
    download_gse_parser.add_argument(
        "--dry-run", action="store_true", help="只列出远端文件、大小和落盘位置"
    )
    download_gse_parser.add_argument(
        "--force", action="store_true", help="下载成功后原子替换已有文件"
    )
    download_gse_parser.add_argument(
        "--allow-large", action="store_true", help="允许超过大小门禁的数据集"
    )
    download_gse_parser.add_argument(
        "--detach", action="store_true", help="后台运行并立即返回持久 job_id"
    )
    download_gse_parser.add_argument(
        "--max-size-gb",
        type=float,
        default=_env_float("SPC_GEO_MAX_DOWNLOAD_GB", 20.0),
        help="无需确认即可下载的总量上限，默认 20 GiB",
    )
    download_gse_parser.add_argument(
        "--dataset-concurrency",
        type=int,
        default=_env_int("SPC_DATASET_CONCURRENCY", 2),
        help="主机允许同时活动的数据集上限，1-4，默认2；单一来源仍保持单流",
    )
    download_gse_parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=_env_float("SPC_DATASET_LOCK_TIMEOUT_SECONDS", 30.0),
        help="等待主机/数据集/来源锁的秒数，默认30",
    )
    download_gse_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    inspect_gse_parser = geo_subparsers.add_parser(
        "inspect",
        help="查看或校验本地 GEO GSE 数据集",
    )
    inspect_gse_parser.add_argument("gse_ids", nargs="*", help="省略时列出全部本地 GSE")
    inspect_gse_parser.add_argument(
        "--output-dir", type=str, default=None, help="GEO 数据根目录"
    )
    inspect_gse_parser.add_argument(
        "--verify", action="store_true", help="重新计算大小与 SHA-256 校验"
    )
    inspect_gse_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )
    return [download_gse_parser, inspect_gse_parser]
