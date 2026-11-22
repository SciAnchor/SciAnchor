"""NCBI E-utilities 与 Dryad 数据获取命令适配器。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from typing import Any

import requests

from paperfetch.datasets.acquisition import (
    AcquisitionBusy,
    AcquisitionConfigurationError,
    error_payload,
)
from paperfetch.datasets.dryad import (
    DryadDataError,
    DryadDatasetStore,
    DryadLargeDownloadBlocked,
)
from paperfetch.datasets.ncbi import NcbiEutilsClient, NcbiEutilsError
from paperfetch.datasets.archive import (
    ArchiveDatasetError,
    FigshareArchiveStore,
    ZenodoArchiveStore,
    persist_archive_record,
)
from paperfetch.observability import get_event_logger, write_output

logger = get_event_logger("paperfetch.cli.datasets")


ARCHIVE_CAPABILITIES = {
    "schema_version": "spc.archive-capabilities.v1",
    "supported_sources": {
        "zenodo": {
            "inspect": True,
            "download": True,
            "remote_zip_inventory": True,
            "record_kind": "record_id",
        },
        "figshare": {
            "inspect": True,
            "download": True,
            "remote_zip_inventory": True,
            "record_kind": "public_article_id",
            "doi_to_record_discovery": False,
        },
    },
    "unsupported_sources": {
        "proteomexchange": "registry_adapter_not_implemented",
        "iprox": "repository_adapter_not_implemented",
        "pride": "repository_adapter_not_implemented",
        "europe_pmc_supplementary": "supplementary_adapter_not_implemented",
    },
    "readiness_rule": "manifest_ready_does_not_imply_payload_ready",
}


def _archive_store(source: str, output_dir: str):
    stores = {
        "zenodo": ZenodoArchiveStore,
        "figshare": FigshareArchiveStore,
    }
    normalized = str(source or "").strip().lower()
    store_type = stores.get(normalized)
    if store_type is None:
        raise ArchiveDatasetError(
            f"当前不支持归档来源：{normalized or 'unknown'}",
            error_code="archive_source_capability_unsupported",
            error_class="capability_unsupported",
            diagnostics={
                "requested_source": normalized or None,
                "supported_sources": sorted(stores),
                "remediation": "先运行 spc dataset archive capabilities",
            },
        )
    return store_type(output_dir)


def _archive_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ArchiveDatasetError):
        return exc.error_code, exc.error_class
    if isinstance(exc, requests.RequestException):
        return "archive_transport_failed", "network_error"
    if isinstance(exc, UnicodeError):
        return "archive_entry_decode_failed", "archive_entry_decode_error"
    if isinstance(exc, OSError):
        return "archive_filesystem_operation_failed", "io_error"
    return "archive_dataset_invalid", "archive_format_error"


def run_archive_dataset(parsed_args: Any) -> int:
    """检查或下载独立的公开归档数据集记录。"""
    if parsed_args.archive_action == "capabilities":
        if parsed_args.output_format == "json":
            write_output(ARCHIVE_CAPABILITIES, pretty=True)
        else:
            write_output(
                "归档来源：已支持="
                + ",".join(ARCHIVE_CAPABILITIES["supported_sources"])
                + "；未支持="
                + ",".join(ARCHIVE_CAPABILITIES["unsupported_sources"])
            )
        return 0
    try:
        with _archive_store(parsed_args.source, parsed_args.output_dir) as store:
            if parsed_args.archive_action == "inspect":
                result = store.inspect(
                    str(parsed_args.record),
                    remote_inventory=parsed_args.remote_inventory,
                    max_small_text_bytes=parsed_args.max_small_text_bytes,
                )
            else:
                result = store.download(
                    str(parsed_args.record),
                    parsed_args.file,
                    resume=parsed_args.resume,
                    verify_checksum=parsed_args.verify_checksum,
                )
        exit_code = (
            2
            if result.get("status") in {"access_restricted", "files_not_available"}
            else 0
        )
    except (ArchiveDatasetError, requests.RequestException, OSError, ValueError) as exc:
        error_code, error_class = _archive_failure(exc)
        failure = {
            "schema_version": "spc.archive-dataset-record.v1",
            "source": parsed_args.source,
            "record": str(parsed_args.record),
            "status": "failed",
            "error_code": error_code,
            "error_class": error_class,
            "message": str(exc),
            "readiness": {"manifest_ready": False, "payload_ready": False},
        }
        if isinstance(exc, ArchiveDatasetError):
            failure.update(exc.diagnostics)
        result = failure
        record_path = (
            Path(parsed_args.output_dir).expanduser().resolve()
            / "archive_dataset_record.json"
        )
        try:
            existing = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = None
        if (
            isinstance(existing, dict)
            and existing.get("schema_version") == "spc.archive-dataset-record.v1"
            and existing.get("source") == parsed_args.source
            and str(existing.get("record")) == str(parsed_args.record)
            and (existing.get("readiness") or {}).get("manifest_ready") is True
        ):
            result = {
                **existing,
                **failure,
                "previous_status": existing.get("status"),
                "remote_archives": existing.get("remote_archives") or {},
                "warnings": existing.get("warnings") or [],
                "warning_count": int(existing.get("warning_count") or 0),
                "readiness": {"manifest_ready": True, "payload_ready": False},
            }
        if getattr(parsed_args, "archive_action", None) == "download":
            partial = Path(parsed_args.output_dir).expanduser().resolve() / (
                parsed_args.file + ".part"
            )
            result["file"] = {
                "key": parsed_args.file,
                "path": str(partial),
                "partial_bytes": partial.stat().st_size if partial.exists() else 0,
                "checksum_verified": False,
            }
        logger.error(
            "[归档数据集] 操作失败，来源=%s，record=%s，错误=%s",
            parsed_args.source,
            parsed_args.record,
            error_class,
            error_class=error_class,
        )
        try:
            persist_archive_record(parsed_args.output_dir, result)
        except OSError:
            logger.error(
                "[归档数据集] 失败终局无法持久化，record=%s",
                parsed_args.record,
                error_class="io_error",
            )
        exit_code = 2
    if parsed_args.output_format == "json":
        write_output(result, pretty=True)
    else:
        readiness = result.get("readiness") or {}
        write_output(
            f"{parsed_args.source}:{parsed_args.record}：状态={result.get('status', 'ready')}；"
            f"manifest_ready={readiness.get('manifest_ready')}；"
            f"payload_ready={readiness.get('payload_ready')}"
        )
    return exit_code


def _names(value: str | None) -> list[str] | None:
    if not value:
        return None
    result = [item.strip() for item in value.split(",") if item.strip()]
    return result or None


def _failure(schema: str, identity: str, exc: Exception) -> dict[str, Any]:
    failure = error_payload(exc)
    return {
        "schema_version": schema,
        "identity": identity,
        "status": "failed",
        **failure,
        "error": failure["message"],
    }


def _log_failure(message: str, exc: Exception, **diagnostics: Any) -> None:
    failure = error_payload(exc)
    logger.error(
        message,
        error_class=failure["error_class"],
        diagnostics={
            **diagnostics,
            "error_code": failure["error_code"],
            "exception_type": type(exc).__name__,
        },
    )


def run_ncbi_validate(parsed_args: Any) -> int:
    try:
        with NcbiEutilsClient(
            requests_per_second=parsed_args.requests_per_second
        ) as client:
            result = client.validate_accession(
                parsed_args.accession, db=parsed_args.database
            )
    except (NcbiEutilsError, OSError, ValueError) as exc:
        result = _failure("spc.ncbi.eutils-validation.v1", parsed_args.accession, exc)
        _log_failure("NCBI E-utilities 验证失败", exc, accession=parsed_args.accession)
        exit_code = 2
    else:
        exit_code = 0
    if parsed_args.output_format == "json":
        write_output(result, pretty=True)
    elif result["status"] == "validated":
        write_output(
            f"{result['accession']}：验证通过；记录数={result['fasta_records']}；"
            f"碱基数={result['fasta_bases']}；已认证={result['authenticated']}"
        )
    else:
        write_output(
            f"{parsed_args.accession}：失败 - {result['error_code']}：{result['message']}"
        )
    return exit_code


def run_download_ncbi_record(parsed_args: Any) -> int:
    try:
        with NcbiEutilsClient(
            requests_per_second=parsed_args.requests_per_second
        ) as client:
            result = client.download_record(
                db=parsed_args.database,
                identifier=parsed_args.identifier,
                rettype=parsed_args.rettype,
                retmode=parsed_args.retmode,
                output_path=Path(parsed_args.output),
            )
    except (NcbiEutilsError, OSError, ValueError) as exc:
        result = _failure("spc.ncbi.record-download.v1", parsed_args.identifier, exc)
        _log_failure("NCBI 记录下载失败", exc, identifier=parsed_args.identifier)
        exit_code = 2
    else:
        exit_code = 0
    if parsed_args.output_format == "json":
        write_output(result, pretty=True)
    elif result["status"] == "complete":
        write_output(
            f"{result['identifier']}：下载完成；字节数={result['bytes']}；路径={result['path']}"
        )
    else:
        write_output(
            f"{parsed_args.identifier}：失败 - {result['error_code']}：{result['message']}"
        )
    return exit_code


def run_download_dryad(parsed_args: Any) -> int:
    filenames = _names(parsed_args.files)
    concurrency = int(parsed_args.dataset_concurrency)

    def process(doi: str) -> tuple[dict[str, Any], int]:
        try:
            with DryadDatasetStore(
                parsed_args.output_dir,
                max_download_gb=parsed_args.max_size_gb,
                dataset_concurrency=concurrency,
                lock_timeout_seconds=parsed_args.lock_timeout_seconds,
            ) as store:
                result = (
                    store.plan(doi, filenames, route=parsed_args.route)
                    if parsed_args.dry_run
                    else store.download(
                        doi,
                        filenames=filenames,
                        route=parsed_args.route,
                        force=parsed_args.force,
                        allow_large=parsed_args.allow_large,
                    )
                )
                if parsed_args.dry_run:
                    result = {**result, "status": "planned"}
                return result, 0
        except DryadLargeDownloadBlocked as exc:
            failure = error_payload(exc)
            return {
                **exc.plan,
                "status": "blocked",
                **failure,
                "error": failure["message"],
            }, 2
        except AcquisitionBusy as exc:
            result = _failure("spc.dryad.command-result.v1", doi, exc)
            result["doi"] = doi
            return result, 3
        except AcquisitionConfigurationError as exc:
            result = _failure("spc.dryad.command-result.v1", doi, exc)
            result["doi"] = doi
            return result, 1
        except (DryadDataError, OSError, ValueError) as exc:
            result = _failure("spc.dryad.command-result.v1", doi, exc)
            result["doi"] = doi
            _log_failure("Dryad 数据处理失败", exc, doi=doi)
            return result, 2

    if len(parsed_args.dois) == 1 or concurrency == 1:
        outcomes = [process(doi) for doi in parsed_args.dois]
    else:
        with ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="spc-dryad"
        ) as executor:
            outcomes = list(executor.map(process, parsed_args.dois))
    results = [item[0] for item in outcomes]
    exit_code = max((item[1] for item in outcomes), default=0)
    payload = {
        "schema_version": "spc.dryad.batch-result.v1",
        "mode": "plan" if parsed_args.dry_run else "download",
        "results": results,
    }
    if parsed_args.output_format == "json":
        write_output(payload, pretty=True)
    else:
        for result in results:
            doi = result.get("doi") or result.get("identity")
            if result["status"] in {"failed", "blocked"}:
                write_output(
                    f"{doi}：{'已阻断' if result['status'] == 'blocked' else '失败'} - "
                    f"{result.get('error_code', 'unclassified_error')}：{result['error']}"
                )
            elif parsed_args.dry_run:
                write_output(
                    f"{doi}：计划完成；文件数={result['totals']['files']}；"
                    f"字节数={result['totals']['known_bytes']}；已阻断={result['size_gate']['blocked']}"
                )
            else:
                write_output(
                    f"{doi}：下载完成；文件数={result['files']['complete']}；"
                    f"字节数={result['files']['downloaded_bytes']}；路由={result['route']}"
                )
    return exit_code


def run_inspect_dryad(parsed_args: Any) -> int:
    with DryadDatasetStore(parsed_args.output_dir) as store:
        results = [
            store.inspect(doi, verify=parsed_args.verify) for doi in parsed_args.dois
        ]
    payload = {"schema_version": "spc.dryad.inspect-result.v1", "results": results}
    if parsed_args.output_format == "json":
        write_output(payload, pretty=True)
    else:
        for result in results:
            write_output(
                f"{result['doi']}：状态={result['status']}；"
                f"文件={result.get('files', {}).get('complete', 0)}/"
                f"{result.get('files', {}).get('total', 0)}"
            )
    return (
        1
        if any(item["status"] in {"not_downloaded", "invalid"} for item in results)
        else 0
    )


def register_external_dataset_commands(dataset_subparsers):
    """注册 dataset ncbi/dryad。"""
    from paperfetch.cli.common import env_float as _env_float, env_int as _env_int

    ncbi_parser = dataset_subparsers.add_parser("ncbi", help="验证和下载 NCBI 记录")
    ncbi_subparsers = ncbi_parser.add_subparsers(
        dest="dataset_source_action", required=True
    )
    ncbi_validate_parser = ncbi_subparsers.add_parser(
        "validate", help="验证 NCBI E-utilities 身份、限速和固定 accession"
    )
    ncbi_validate_parser.add_argument("--accession", default="NM_007294.4")
    ncbi_validate_parser.add_argument("--database", default="nuccore")
    ncbi_validate_parser.add_argument("--requests-per-second", type=float, default=None)
    ncbi_validate_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    download_ncbi_parser = ncbi_subparsers.add_parser(
        "download", help="原子下载并校验 NCBI EFetch 记录"
    )
    download_ncbi_parser.add_argument("identifier")
    download_ncbi_parser.add_argument("--database", default="nuccore")
    download_ncbi_parser.add_argument("--rettype", default="fasta")
    download_ncbi_parser.add_argument("--retmode", default="text")
    download_ncbi_parser.add_argument("--output", required=True)
    download_ncbi_parser.add_argument("--requests-per-second", type=float, default=None)
    download_ncbi_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    dryad_parser = dataset_subparsers.add_parser(
        "dryad", help="发现、下载和检查 Dryad 数据集"
    )
    dryad_subparsers = dryad_parser.add_subparsers(
        dest="dataset_source_action", required=True
    )
    download_dryad_parser = dryad_subparsers.add_parser(
        "download", help="发现、下载并校验 Dryad 数据集"
    )
    download_dryad_parser.add_argument("dois", nargs="+")
    download_dryad_parser.add_argument("--output-dir", default=None)
    download_dryad_parser.add_argument(
        "--files", default=None, help="只处理指定相对路径，逗号分隔"
    )
    download_dryad_parser.add_argument(
        "--route", choices=["auto", "api", "browser"], default="auto"
    )
    download_dryad_parser.add_argument("--dry-run", action="store_true")
    download_dryad_parser.add_argument("--force", action="store_true")
    download_dryad_parser.add_argument("--allow-large", action="store_true")
    download_dryad_parser.add_argument(
        "--max-size-gb",
        type=float,
        default=_env_float("SPC_DRYAD_MAX_DOWNLOAD_GB", 20.0),
    )
    download_dryad_parser.add_argument(
        "--dataset-concurrency",
        type=int,
        default=_env_int("SPC_DATASET_CONCURRENCY", 2),
        help="主机允许同时活动的数据集上限，1-4，默认2；单一来源仍保持单流",
    )
    download_dryad_parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=_env_float("SPC_DATASET_LOCK_TIMEOUT_SECONDS", 30.0),
    )
    download_dryad_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )

    inspect_dryad_parser = dryad_subparsers.add_parser(
        "inspect", help="校验本地 Dryad 数据集归档"
    )
    inspect_dryad_parser.add_argument("dois", nargs="+")
    inspect_dryad_parser.add_argument("--output-dir", default=None)
    inspect_dryad_parser.add_argument("--verify", action="store_true")
    inspect_dryad_parser.add_argument(
        "--output-format", choices=["text", "json"], default="json"
    )
    return [
        ncbi_validate_parser,
        download_ncbi_parser,
        download_dryad_parser,
        inspect_dryad_parser,
    ]
