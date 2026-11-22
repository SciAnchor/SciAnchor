"""Local contract helpers for semi-automatic RH offload task packs."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._workflow.orchestrator.artifacts import ArtifactManager
from .provenance import ProvenanceRecorder
from .storage.db import Database

OFFLOAD_STATUSES = frozenset(
    {
        "prepared",
        "uploaded",
        "running",
        "succeeded",
        "failed",
        "partial",
        "abandoned",
    }
)
OFFLOAD_STATUS_TRANSITIONS = {
    "prepared": frozenset({"prepared", "uploaded", "abandoned"}),
    "uploaded": frozenset({"uploaded", "running", "abandoned"}),
    "running": frozenset({"running", "succeeded", "failed", "partial", "abandoned"}),
    "succeeded": frozenset({"succeeded"}),
    "failed": frozenset({"failed", "abandoned"}),
    "partial": frozenset({"partial", "succeeded", "failed", "abandoned"}),
    "abandoned": frozenset({"abandoned"}),
}
TASK_TYPES = frozenset(
    {
        "wiki_embedding_batch",
        "paper_text_extraction_batch",
        "retrieval_eval_sweep",
        "researchflowbench_batch_eval",
    }
)
DEFAULT_REMOTE_ROOT = Path(".rh-offload")
DEFAULT_LOCAL_ROOT = Path(".tmp/rh-offload")
TASK_MANIFEST = "task_manifest.json"
RESULT_MANIFEST = "result_manifest.json"
RECEIPT_FILE = "offload_receipt.json"
REMOTE_OFFLOAD_ORIGIN = "remote_offload"
REMOTE_OFFLOAD_RESULT_ARTIFACT = "remote_offload_result"
REMOTE_OFFLOAD_DIAGNOSTIC_ARTIFACT = "remote_offload_diagnostic"
REMOTE_OFFLOAD_SCHEMA_VERSION = "remote_offload_result.v1"
REMOTE_RETRIEVAL_EVAL_ARTIFACT = "remote_retrieval_eval_result"
REMOTE_RETRIEVAL_EVAL_SCHEMA_VERSION = "remote_retrieval_eval_result.v1"
REMOTE_WIKI_EMBEDDING_ARTIFACT = "remote_wiki_embedding_index"
REMOTE_WIKI_EMBEDDING_SCHEMA_VERSION = "remote_wiki_embedding_index.v1"
REMOTE_OFFLOAD_RECEIPT_SCHEMA_VERSION = "remote_offload_receipt.v1"
BATCH_PLAN_SCHEMA_VERSION = "remote_offload_batch_plan.v1"
OFFLOAD_QUEUE_SCHEMA_VERSION = "remote_offload_queue.v1"
REMOTE_STATUS_SCHEMA_VERSION = "remote_offload_remote_status.v1"
REMOTE_CLEANUP_SCHEMA_VERSION = "remote_offload_remote_cleanup.v1"
WORKER_CAPABILITY_SCHEMA_VERSION = "rh_offload_worker_capabilities.v1"
REMOTE_OFFLOAD_SECTIONS = ("incoming", "runs", "results", "cache")
REMOTE_LIBRARY_SNAPSHOT_SCHEMA_VERSION = "remote_library_snapshot.v1"
REMOTE_LIBRARY_REQUIRED_SNAPSHOT_KEYS = frozenset(
    {
        "schema_version",
        "created_at",
        "query",
        "host_alias_hash",
        "library_root_hash",
        "max_files_scanned",
        "scanned_file_count",
        "matched_file_count",
        "truncated",
        "extension_counts",
        "samples",
        "warnings",
    }
)
REMOTE_LIBRARY_ALLOWED_SNAPSHOT_KEYS = (
    REMOTE_LIBRARY_REQUIRED_SNAPSHOT_KEYS
    | frozenset(
        {
            "document_frequency",
        }
    )
)
REMOTE_LIBRARY_REQUIRED_SAMPLE_KEYS = frozenset(
    {
        "basename",
        "extension",
        "size_bytes",
        "relative_path_hash",
        "path_depth",
        "matched_terms",
    }
)
REMOTE_LIBRARY_ALLOWED_SAMPLE_KEYS = REMOTE_LIBRARY_REQUIRED_SAMPLE_KEYS | frozenset(
    {
        "token_counts",
        "token_count",
    }
)
REMOTE_LIBRARY_ALLOWED_EXTENSIONS = frozenset(
    {".pdf", ".txt", ".json", ".jsonl", ".md", ".bib", ".ris", ".csv", ".tsv"}
)
PAPER_TEXT_SOURCE_MAX_BYTES = 2_000_000
PAPER_TEXT_STRUCTURE_MAX_BYTES = 5_000_000
PAPER_TEXT_SOURCE_MAX_PAGES = 1_000
PAPER_TEXT_PDF_MAX_BYTES = 100_000_000
WIKI_EMBEDDING_TEXT_MAX_BYTES = 200_000
MODEL_CAPABILITY_BY_TASK = {
    "wiki_embedding_batch": "embedding",
    "researchflowbench_batch_eval": "batch_eval",
}


class OffloadError(ValueError):
    """Raised when an offload package violates the local contract."""


@dataclass(frozen=True)
class _OffloadImportResult:
    primitive: str
    started_at: str
    finished_at: str
    backend: str
    model_used: str
    cost_usd: float
    success: bool
    error: str
    output_hash_value: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def output_hash(self) -> str:
        return self.output_hash_value


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_iso_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    collapsed = "-".join(part for part in slug.split("-") if part)
    return collapsed[:60] or "task"


def compute_file_hashes(root: str | Path) -> dict[str, str]:
    root_path = Path(root)
    if not root_path.exists():
        raise OffloadError(f"path does not exist: {root_path}")
    if root_path.is_symlink():
        raise OffloadError(f"unsafe symlink path: {root_path}")
    if root_path.is_file():
        return {root_path.name: _sha256_file(root_path)}
    hashes: dict[str, str] = {}
    for path in sorted(root_path.rglob("*")):
        if path.is_symlink():
            raise OffloadError(f"unsafe symlink path: {path}")
        if not path.is_file():
            continue
        rel = path.relative_to(root_path).as_posix()
        validate_relative_path(rel)
        if rel == RECEIPT_FILE:
            continue
        hashes[rel] = _sha256_file(path)
    return hashes


def validate_relative_path(value: str) -> str:
    if not value or "\x00" in value:
        raise OffloadError("unsafe path: empty path")
    if "\\" in value:
        raise OffloadError(f"unsafe path: {value}")
    path = Path(value)
    if path.is_absolute():
        raise OffloadError(f"unsafe path: {value}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise OffloadError(f"unsafe path: {value}")
    return path.as_posix()


def validate_task_manifest(manifest: dict[str, Any]) -> None:
    required = {
        "task_id",
        "task_type",
        "created_at",
        "status",
        "input_hashes",
        "expected_outputs",
        "resource_hint",
        "timeout",
        "cleanup_policy",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise OffloadError(f"task manifest missing fields: {', '.join(missing)}")
    validate_task_id(str(manifest["task_id"]))
    if manifest["task_type"] not in TASK_TYPES:
        raise OffloadError(f"unsupported task_type: {manifest['task_type']}")
    if manifest["status"] not in OFFLOAD_STATUSES:
        raise OffloadError(f"unsupported status: {manifest['status']}")
    _validate_hash_map(manifest["input_hashes"], field_name="input_hashes")
    _validate_path_list(manifest["expected_outputs"], field_name="expected_outputs")
    if not isinstance(manifest["resource_hint"], dict):
        raise OffloadError("resource_hint must be an object")
    if not isinstance(manifest["cleanup_policy"], dict):
        raise OffloadError("cleanup_policy must be an object")
    timeout = manifest["timeout"]
    if not isinstance(timeout, int) or timeout <= 0:
        raise OffloadError("timeout must be a positive integer")


def validate_result_manifest(manifest: dict[str, Any]) -> None:
    required = {
        "task_id",
        "task_type",
        "status",
        "started_at",
        "finished_at",
        "exit_code",
        "output_hashes",
        "warnings",
        "server_hostname",
        "git_commit",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise OffloadError(f"result manifest missing fields: {', '.join(missing)}")
    validate_task_id(str(manifest["task_id"]))
    if manifest["task_type"] not in TASK_TYPES:
        raise OffloadError(f"unsupported task_type: {manifest['task_type']}")
    if manifest["status"] not in OFFLOAD_STATUSES:
        raise OffloadError(f"unsupported status: {manifest['status']}")
    if not isinstance(manifest["exit_code"], int):
        raise OffloadError("exit_code must be an integer")
    _validate_hash_map(manifest["output_hashes"], field_name="output_hashes")
    _validate_string_list(manifest["warnings"], field_name="warnings", max_len=2000)
    _validate_short_string(
        manifest["server_hostname"],
        field_name="server_hostname",
        max_len=255,
    )
    _validate_short_string(manifest["git_commit"], field_name="git_commit", max_len=128)
    if manifest["status"] == "succeeded" and manifest["exit_code"] != 0:
        raise OffloadError("succeeded result must have exit_code 0")
    if manifest["status"] == "failed" and manifest["exit_code"] == 0:
        raise OffloadError("failed result must have nonzero exit_code")
    if manifest["status"] in {"partial", "abandoned"} and manifest["exit_code"] < 0:
        raise OffloadError(f"{manifest['status']} result has invalid exit_code")


def validate_status_transition(current: str, next_status: str) -> None:
    if current not in OFFLOAD_STATUSES:
        raise OffloadError(f"unsupported status: {current}")
    if next_status not in OFFLOAD_STATUSES:
        raise OffloadError(f"unsupported status: {next_status}")
    if next_status not in OFFLOAD_STATUS_TRANSITIONS[current]:
        raise OffloadError(f"invalid status transition: {current} -> {next_status}")


def validate_host_alias(host: str | None) -> str:
    if host is None:
        raise OffloadError("host is required; pass --host or set RH_OFFLOAD_HOST")
    if not host or host.strip() != host or host.startswith("-"):
        raise OffloadError(f"unsafe host alias: {host!r}")
    if not all(ch.isalnum() or ch in {"-", "_", ".", "@"} for ch in host):
        raise OffloadError(f"unsafe host alias: {host!r}")
    return host


def validate_remote_root(remote_root: str | Path) -> Path:
    path = Path(remote_root)
    raw = path.as_posix()
    if not raw or raw.strip() != raw or "\x00" in raw:
        raise OffloadError(f"unsafe remote_root: {remote_root!r}")
    if raw in {".", "/", "~"} or raw.startswith("-"):
        raise OffloadError(f"unsafe remote_root: {remote_root!r}")
    if any(part in {"", ".."} for part in path.parts):
        raise OffloadError(f"unsafe remote_root: {remote_root!r}")
    try:
        if path.expanduser() == Path.home():
            raise OffloadError(f"unsafe remote_root: {remote_root!r}")
    except RuntimeError:
        pass
    return path


def validate_remote_library_root(library_root: str | Path) -> str:
    raw = str(library_root)
    if not raw or raw.strip() != raw or "\x00" in raw:
        raise OffloadError(f"unsafe library_root: {library_root!r}")
    if raw.startswith("-"):
        raise OffloadError(f"unsafe library_root: {library_root!r}")
    path = Path(raw)
    if raw in {".", "/", "~"}:
        raise OffloadError(f"unsafe library_root: {library_root!r}")
    if any(part in {"", ".."} for part in path.parts):
        raise OffloadError(f"unsafe library_root: {library_root!r}")
    return path.as_posix()


def validate_remote_library_snapshot(snapshot: dict[str, Any]) -> None:
    extra = sorted(set(snapshot) - REMOTE_LIBRARY_ALLOWED_SNAPSHOT_KEYS)
    if extra:
        raise OffloadError(
            f"remote library snapshot fields not allowed: {', '.join(extra)}"
        )
    missing = sorted(REMOTE_LIBRARY_REQUIRED_SNAPSHOT_KEYS - set(snapshot))
    if missing:
        raise OffloadError(
            f"remote library snapshot missing fields: {', '.join(missing)}"
        )
    if snapshot["schema_version"] != REMOTE_LIBRARY_SNAPSHOT_SCHEMA_VERSION:
        raise OffloadError(
            f"unsupported remote library snapshot schema: {snapshot['schema_version']}"
        )
    _validate_short_string(snapshot["created_at"], field_name="created_at", max_len=64)
    _validate_short_string(snapshot["query"], field_name="query", max_len=512)
    _validate_hex_digest(snapshot["host_alias_hash"], field_name="host_alias_hash")
    _validate_hex_digest(snapshot["library_root_hash"], field_name="library_root_hash")
    for field_name in ("max_files_scanned", "scanned_file_count", "matched_file_count"):
        _coerce_nonnegative_int(snapshot[field_name], field_name=field_name)
    if not isinstance(snapshot["truncated"], bool):
        raise OffloadError("truncated must be a boolean")
    _validate_extension_counts(snapshot["extension_counts"])
    if "document_frequency" in snapshot:
        _validate_token_count_map(
            snapshot["document_frequency"],
            field_name="document_frequency",
            max_items=5000,
        )
    _validate_string_list(snapshot["warnings"], field_name="warnings", max_len=1000)
    samples = snapshot["samples"]
    if not isinstance(samples, list):
        raise OffloadError("samples must be a list")
    if len(samples) > 200:
        raise OffloadError("samples must contain at most 200 items")
    for sample in samples:
        _validate_remote_library_sample(sample)


def scan_remote_library(
    *,
    host: str | None,
    library_root: str | Path,
    query: str,
    out_path: str | Path,
    limit: int = 25,
    max_files: int = 5000,
    timeout_seconds: int = 30,
    command_runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
    | None = None,
) -> Path:
    resolved_host = validate_host_alias(configured_host(host))
    root = validate_remote_library_root(library_root)
    cleaned_query = _clean_snapshot_text(query, max_len=512)
    if limit <= 0 or limit > 200:
        raise OffloadError("limit must be between 1 and 200")
    if max_files <= 0 or max_files > 1_000_000:
        raise OffloadError("max_files must be between 1 and 1000000")
    timeout = _coerce_positive_int(timeout_seconds, field_name="timeout_seconds")
    runner = command_runner or (
        lambda command: _run_capture(command, timeout_seconds=timeout)
    )
    try:
        completed = runner(
            [
                "ssh",
                resolved_host,
                _remote_library_scan_script(
                    library_root=root,
                    query=cleaned_query,
                    limit=limit,
                    max_files=max_files,
                ),
            ]
        )
    except subprocess.TimeoutExpired as exc:
        raise OffloadError(
            f"remote library scan timed out after {exc.timeout:g} seconds"
        ) from exc
    if completed.returncode != 0:
        stderr = (completed.stderr or "")[-2000:]
        raise OffloadError(f"remote library scan failed: {stderr}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OffloadError("remote library scan did not return JSON") from exc
    if not isinstance(payload, dict):
        raise OffloadError("remote library scan must return an object")
    snapshot = {
        **payload,
        "host_alias_hash": _hash_text(resolved_host),
        "library_root_hash": _hash_text(root),
        "query": cleaned_query,
    }
    validate_remote_library_snapshot(snapshot)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, snapshot)
    return path


def configured_host(host: str | None) -> str | None:
    return host or os.environ.get("RH_OFFLOAD_HOST")


def validate_result_package(result_dir: str | Path) -> dict[str, Any]:
    result_path = Path(result_dir)
    _reject_symlinks(result_path)
    manifest = _read_json(result_path / RESULT_MANIFEST)
    validate_result_manifest(manifest)
    task_manifest_path = result_path / TASK_MANIFEST
    task_manifest: dict[str, Any] | None = None
    if task_manifest_path.exists():
        task_manifest = _read_json(task_manifest_path)
        validate_task_manifest(task_manifest)
        if task_manifest["task_id"] != manifest["task_id"]:
            raise OffloadError("task_id mismatch between task and result manifests")
        if task_manifest["task_type"] != manifest["task_type"]:
            raise OffloadError("task_type mismatch between task and result manifests")
    elif manifest["status"] == "succeeded":
        raise OffloadError("task_manifest.json is required for succeeded results")
    if manifest["status"] == "succeeded" and manifest["exit_code"] != 0:
        raise OffloadError("succeeded result must have exit_code 0")
    outputs_dir = result_path / "outputs"
    logs_dir = result_path / "logs"
    if not outputs_dir.is_dir():
        raise OffloadError("result package missing outputs/")
    if not (logs_dir / "stdout.log").is_file():
        raise OffloadError("result package missing logs/stdout.log")
    if not (logs_dir / "stderr.log").is_file():
        raise OffloadError("result package missing logs/stderr.log")
    actual = compute_file_hashes(outputs_dir)
    if actual != manifest["output_hashes"]:
        raise OffloadError("output_hashes do not match result outputs")
    if task_manifest is not None and manifest["status"] == "succeeded":
        expected = _expected_output_keys(task_manifest)
        actual_keys = set(actual)
        missing = sorted(expected - actual_keys)
        extra = sorted(actual_keys - expected)
        if missing:
            raise OffloadError(f"missing expected output: {missing[0]}")
        if extra:
            raise OffloadError(f"unexpected output: {extra[0]}")
    return manifest


def prepare_task(
    *,
    task_type: str,
    topic: str,
    out_dir: str | Path,
    db_path: str | Path,
    task_id: str | None = None,
    library_snapshot: str | Path | None = None,
    include_pdf_files: bool = False,
    max_pdf_bytes: int = PAPER_TEXT_PDF_MAX_BYTES,
    model_policy: dict[str, Any] | None = None,
) -> Path:
    if task_type not in TASK_TYPES:
        raise OffloadError(f"unsupported task_type: {task_type}")
    task_dir = Path(out_dir)
    if task_dir.exists() and any(task_dir.iterdir()):
        raise OffloadError(f"output directory is not empty: {task_dir}")
    task_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir = task_dir / "inputs"
    inputs_dir.mkdir(exist_ok=True)

    resolved_task_id = task_id or f"{task_type}-{utc_timestamp()}-{safe_slug(topic)}"
    expected_outputs = _PACK_BUILDERS[task_type](
        topic=topic,
        inputs_dir=inputs_dir,
        db_path=Path(db_path),
        library_snapshot=_load_remote_library_snapshot(library_snapshot),
        include_pdf_files=include_pdf_files,
        max_pdf_bytes=max_pdf_bytes,
        model_policy=_normalize_task_model_policy(model_policy, task_type=task_type),
    )
    _write_runner(task_dir / "runner.sh")
    _write_readme(task_dir / "README.md", task_id=resolved_task_id, task_type=task_type)
    manifest = {
        "task_id": resolved_task_id,
        "task_type": task_type,
        "created_at": utc_iso_timestamp(),
        "topic": topic,
        "status": "prepared",
        "input_hashes": compute_file_hashes(inputs_dir),
        "expected_outputs": expected_outputs,
        "resource_hint": _resource_hint(task_type),
        "timeout": _timeout_seconds(task_type),
        "cleanup_policy": {
            "remote_cache_root": "cache/",
            "cache_max_gb": 50,
            "remove_run_dir_after_fetch": False,
        },
    }
    validate_task_manifest(manifest)
    _write_json(task_dir / TASK_MANIFEST, manifest)
    _append_receipt_attempt(
        task_dir,
        manifest=manifest,
        operation="prepare",
        status="prepared",
        local_layout="task_pack",
    )
    return task_dir


def load_task_manifest(task_dir: str | Path) -> dict[str, Any]:
    manifest = _read_json(Path(task_dir) / TASK_MANIFEST)
    validate_task_manifest(manifest)
    return manifest


def upload_task(
    task_dir: str | Path,
    *,
    remote_root: str | Path = DEFAULT_REMOTE_ROOT,
    host: str | None = None,
    execute: bool = False,
    command_runner: Callable[[Sequence[str]], Any] | None = None,
) -> dict[str, Any]:
    manifest = load_task_manifest(task_dir)
    task_id = str(manifest["task_id"])
    validate_task_id(task_id)
    remote = validate_remote_root(remote_root)
    remote_path = remote / "incoming" / task_id
    if execute:
        resolved_host = validate_host_alias(configured_host(host))
        runner = command_runner or _run_checked
        _ensure_remote_offload_layout(
            runner,
            host=resolved_host,
            remote_root=remote,
        )
        runner(
            [
                "rsync",
                "-a",
                "--partial",
                "--checksum",
                f"{Path(task_dir).as_posix().rstrip('/')}/",
                f"{resolved_host}:{remote_path.as_posix()}/",
            ]
        )
    else:
        resolved_host = configured_host(host)
        _copy_tree_idempotent(Path(task_dir), remote_path)
    _append_receipt_attempt(
        Path(task_dir),
        manifest=manifest,
        operation="upload",
        status="uploaded",
        host_configured=bool(resolved_host),
        remote_root=remote.as_posix(),
        remote_layout=f"incoming/{task_id}",
        execute=execute,
    )
    return {
        "task_id": task_id,
        "task_type": manifest["task_type"],
        "status": "uploaded",
        "remote_path": remote_path.as_posix(),
        "host": resolved_host,
    }


def _ensure_remote_offload_layout(
    runner: Callable[[Sequence[str]], Any],
    *,
    host: str,
    remote_root: Path,
) -> None:
    paths = [
        remote_root / "incoming",
        remote_root / "runs",
        remote_root / "results",
        remote_root / "cache",
    ]
    script = "mkdir -p " + " ".join(shlex.quote(path.as_posix()) for path in paths)
    runner(["ssh", host, script])


def fetch_task(
    task_id: str,
    *,
    local_root: str | Path = DEFAULT_LOCAL_ROOT,
    remote_root: str | Path = DEFAULT_REMOTE_ROOT,
    host: str | None = None,
    execute: bool = False,
    command_runner: Callable[[Sequence[str]], Any] | None = None,
) -> dict[str, Any]:
    validate_task_id(task_id)
    remote = validate_remote_root(remote_root)
    local_path = Path(local_root) / task_id
    remote_path = remote / "results" / task_id
    if execute:
        resolved_host = validate_host_alias(configured_host(host))
        local_path.mkdir(parents=True, exist_ok=True)
        runner = command_runner or _run_checked
        runner(
            [
                "rsync",
                "-a",
                "--partial",
                "--checksum",
                f"{resolved_host}:{remote_path.as_posix()}/",
                f"{local_path.as_posix().rstrip('/')}/",
            ]
        )
    else:
        _copy_tree_idempotent(remote_path, local_path)
    manifest = validate_result_package(local_path)
    _append_receipt_attempt(
        local_path,
        manifest=manifest,
        operation="fetch",
        status=manifest["status"],
        host_configured=bool(configured_host(host)),
        remote_root=remote.as_posix(),
        remote_layout=f"results/{task_id}",
        local_layout=f"{Path(local_root).as_posix().rstrip('/')}/{task_id}",
        execute=execute,
    )
    return {
        "task_id": task_id,
        "task_type": manifest["task_type"],
        "status": manifest["status"],
        "local_path": str(local_path),
    }


def remote_status(
    *,
    remote_root: str | Path = DEFAULT_REMOTE_ROOT,
    host: str | None = None,
    execute: bool = False,
    command_runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
    | None = None,
) -> dict[str, Any]:
    remote = validate_remote_root(remote_root)
    if execute:
        resolved_host = validate_host_alias(configured_host(host))
        runner = command_runner or _run_capture
        completed = runner(["ssh", resolved_host, _remote_status_script(remote)])
        if completed.returncode != 0:
            raise OffloadError("remote status command failed")
        payload = _json_object_from_text(completed.stdout)
        return _validate_remote_status_payload(payload, remote_root=remote)
    return _local_remote_status(remote)


def remote_cleanup(
    *,
    remote_root: str | Path = DEFAULT_REMOTE_ROOT,
    host: str | None = None,
    task_ids: Sequence[str] | None = None,
    sections: Sequence[str] | None = None,
    older_than_days: int | None = None,
    dry_run: bool = True,
    execute: bool = False,
    command_runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
    | None = None,
) -> dict[str, Any]:
    remote = validate_remote_root(remote_root)
    normalized_task_ids = _normalize_cleanup_task_ids(task_ids)
    normalized_sections = _normalize_cleanup_sections(sections)
    normalized_age = (
        _coerce_nonnegative_int(older_than_days, field_name="older_than_days")
        if older_than_days is not None
        else None
    )
    if not normalized_task_ids and normalized_age is None:
        raise OffloadError("cleanup requires at least one task_id or older_than_days")
    if execute:
        resolved_host = validate_host_alias(configured_host(host))
        runner = command_runner or _run_capture
        completed = runner(
            [
                "ssh",
                resolved_host,
                _remote_cleanup_script(
                    remote,
                    task_ids=normalized_task_ids,
                    sections=normalized_sections,
                    older_than_days=normalized_age,
                    dry_run=dry_run,
                ),
            ]
        )
        if completed.returncode != 0:
            raise OffloadError("remote cleanup command failed")
        payload = _json_object_from_text(completed.stdout)
        return _validate_remote_cleanup_payload(payload, remote_root=remote)
    return _local_remote_cleanup(
        remote,
        task_ids=normalized_task_ids,
        sections=normalized_sections,
        older_than_days=normalized_age,
        dry_run=dry_run,
    )


def run_local_task(
    task_id: str,
    *,
    remote_root: str | Path = DEFAULT_REMOTE_ROOT,
) -> dict[str, Any]:
    validate_task_id(task_id)
    remote = validate_remote_root(remote_root)
    incoming = remote / "incoming" / task_id
    run_dir = remote / "runs" / task_id
    result_dir = remote / "results" / task_id
    if not incoming.is_dir():
        raise OffloadError(f"incoming task does not exist: {incoming}")

    result_logs = result_dir / "logs"
    result_logs.mkdir(parents=True, exist_ok=True)
    tmp_run_dir = run_dir.with_name(f"{run_dir.name}.tmp")
    if tmp_run_dir.exists():
        shutil.rmtree(tmp_run_dir)
    _copy_tree_idempotent(incoming, tmp_run_dir)
    if run_dir.exists():
        shutil.rmtree(run_dir)
    tmp_run_dir.rename(run_dir)

    env = dict(os.environ)
    env["RESULT_DIR"] = str(result_dir)
    started_at = utc_iso_timestamp()
    with (
        (result_logs / "stdout.log").open("w") as stdout_handle,
        (result_logs / "stderr.log").open("w") as stderr_handle,
    ):
        completed = subprocess.run(
            ["bash", "runner.sh"],
            cwd=run_dir,
            env=env,
            check=False,
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )

    if (run_dir / RESULT_MANIFEST).is_file() and not (
        result_dir / RESULT_MANIFEST
    ).exists():
        shutil.copy2(run_dir / RESULT_MANIFEST, result_dir / RESULT_MANIFEST)
    if (run_dir / "outputs").is_dir():
        output_dir = result_dir / "outputs"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        _copy_tree_idempotent(run_dir / "outputs", output_dir)
    (result_dir / "outputs").mkdir(parents=True, exist_ok=True)
    shutil.copy2(run_dir / TASK_MANIFEST, result_dir / TASK_MANIFEST)
    if not (result_dir / RESULT_MANIFEST).is_file():
        _write_fallback_result_manifest(
            result_dir,
            task_manifest=load_task_manifest(run_dir),
            exit_code=completed.returncode,
            started_at=started_at,
        )
    manifest = validate_result_package(result_dir)
    _append_receipt_attempt(
        result_dir,
        manifest=manifest,
        operation="run_local",
        status=manifest["status"],
        exit_code=manifest["exit_code"],
        remote_root=remote.as_posix(),
        remote_layout=f"results/{task_id}",
    )
    return {
        "task_id": task_id,
        "task_type": manifest["task_type"],
        "status": manifest["status"],
        "exit_code": manifest["exit_code"],
        "result_path": str(result_dir),
    }


def build_runner_command(
    task_id: str,
    *,
    host: str | None,
    remote_root: str | Path = DEFAULT_REMOTE_ROOT,
) -> str:
    validate_task_id(task_id)
    resolved_host = validate_host_alias(configured_host(host))
    remote = validate_remote_root(remote_root)
    incoming = remote / "incoming" / task_id
    run_dir = remote / "runs" / task_id
    result_dir = remote / "results" / task_id
    script = "\n".join(
        [
            "set -euo pipefail",
            f"incoming={shlex.quote(incoming.as_posix())}",
            f"run_dir={shlex.quote(run_dir.as_posix())}",
            f"result_dir={shlex.quote(result_dir.as_posix())}",
            'mkdir -p "$(dirname "$run_dir")" "$result_dir/logs"',
            'rm -rf "$run_dir.tmp"',
            'cp -a "$incoming" "$run_dir.tmp"',
            'rm -rf "$run_dir"',
            'mv "$run_dir.tmp" "$run_dir"',
            'cd "$run_dir"',
            "set +e",
            'RESULT_DIR="$result_dir" bash runner.sh >"$result_dir/logs/stdout.log" 2>"$result_dir/logs/stderr.log"',
            "exit_code=$?",
            "set -e",
            'if [ -f "result_manifest.json" ] && [ ! -f "$result_dir/result_manifest.json" ]; then cp result_manifest.json "$result_dir/result_manifest.json"; fi',
            'if [ -d "outputs" ]; then rm -rf "$result_dir/outputs"; cp -a outputs "$result_dir/outputs"; fi',
            'cp task_manifest.json "$result_dir/task_manifest.json"',
            'mkdir -p "$result_dir/outputs"',
            'if [ ! -f "$result_dir/result_manifest.json" ]; then',
            "export result_dir exit_code",
            "python3 - <<'PY'",
            "import hashlib, json, os, socket",
            "from datetime import datetime, timezone",
            "result_dir = os.environ['result_dir']",
            "manifest = json.load(open('task_manifest.json'))",
            "started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()",
            "output_hashes = {}",
            "outputs_dir = os.path.join(result_dir, 'outputs')",
            "for root, _, files in os.walk(outputs_dir):",
            "    for name in files:",
            "        path = os.path.join(root, name)",
            "        rel = os.path.relpath(path, outputs_dir)",
            "        with open(path, 'rb') as handle:",
            "            output_hashes[rel] = hashlib.sha256(handle.read()).hexdigest()",
            "payload = {",
            "  'task_id': manifest['task_id'],",
            "  'task_type': manifest['task_type'],",
            "  'status': 'partial' if int(os.environ['exit_code']) == 0 else 'failed',",
            "  'started_at': started_at,",
            "  'finished_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),",
            "  'exit_code': int(os.environ['exit_code']),",
            "  'output_hashes': output_hashes,",
            "  'warnings': ['runner did not write result_manifest.json'],",
            "  'server_hostname': socket.gethostname(),",
            "  'git_commit': os.environ.get('GIT_COMMIT', 'unknown'),",
            "}",
            "json.dump(payload, open(os.path.join(result_dir, 'result_manifest.json'), 'w'), indent=2, sort_keys=True)",
            "PY",
            "fi",
            "exit $exit_code",
        ]
    )
    return f"ssh {shlex.quote(resolved_host)} {shlex.quote(script)}"


def doctor(
    *,
    host: str | None,
    remote_root: str | Path = DEFAULT_REMOTE_ROOT,
    skip_ssh: bool = False,
    timeout_seconds: int = 30,
    command_runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
    | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    task_types = sorted(TASK_TYPES)
    if skip_ssh:
        checks.append({"check": "ssh", "ok": None, "skipped": True})
    else:
        resolved_host = validate_host_alias(configured_host(host))
        timeout = _coerce_positive_int(timeout_seconds, field_name="timeout_seconds")
        runner = command_runner or (
            lambda command: _run_capture(command, timeout_seconds=timeout)
        )
        remote = validate_remote_root(remote_root)
        remote_root_q = shlex.quote(remote.as_posix())
        packages = (
            "json",
            "sqlite3",
            "pypdf",
            "PyPDF2",
            "sentence_transformers",
            "transformers",
            "torch",
        )
        commands = ("pdftotext",)
        probe = (
            f"remote_root={remote_root_q}\n"
            "python3 --version\n"
            'test -d "$remote_root" && echo root_exists || echo root_missing\n'
            'test -d "$remote_root/incoming" && echo incoming_exists || echo incoming_missing\n'
            'test -d "$remote_root/runs" && echo runs_exists || echo runs_missing\n'
            'test -d "$remote_root/results" && echo results_exists || echo results_missing\n'
            'test -d "$remote_root/cache" && echo cache_exists || echo cache_missing\n'
            'df -h "$remote_root" 2>/dev/null || df -h "$(dirname "$remote_root")" 2>/dev/null || df -h . || true\n'
            "nvidia-smi -L || true\n"
            'test -x "$remote_root/runs/__doctor__/runner.sh" && echo runner_executable || echo runner_not_checked\n'
            "python3 - <<'PY'\n"
            "import importlib.util\n"
            f"packages = {list(packages)!r}\n"
            "for name in packages:\n"
            "    status = 'ok' if importlib.util.find_spec(name) is not None else 'missing'\n"
            "    print(f'package:{name}:{status}')\n"
            "PY\n"
            "python3 - <<'PY'\n"
            "import shutil\n"
            f"commands = {list(commands)!r}\n"
            "for name in commands:\n"
            "    status = 'ok' if shutil.which(name) else 'missing'\n"
            "    print(f'command:{name}:{status}')\n"
            "PY\n"
            'if [ -f "$remote_root/capabilities.json" ]; then printf "RH_OFFLOAD_CAPABILITIES_JSON="; cat "$remote_root/capabilities.json"; printf "\\n"; else echo RH_OFFLOAD_CAPABILITIES_JSON={}; fi'
        )
        try:
            completed = runner(
                [
                    "ssh",
                    resolved_host,
                    probe,
                ]
            )
        except subprocess.TimeoutExpired as exc:
            raise OffloadError(
                f"offload doctor timed out after {exc.timeout:g} seconds"
            ) from exc
        stdout = completed.stdout[-4000:]
        stderr = completed.stderr[-4000:]
        checks.append(
            {
                "check": "ssh",
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
        )
        checks.extend(_remote_probe_checks(stdout, remote_root=remote))
        worker_capability = next(
            (item for item in checks if item["check"] == "worker_capabilities"),
            None,
        )
        if worker_capability and worker_capability.get("supported_task_types"):
            task_types = sorted(
                str(item) for item in worker_capability["supported_task_types"]
            )
    resolved_host = configured_host(host)
    checks.append(
        {"check": "local_python", "ok": True, "version": platform.python_version()}
    )
    checks.append(
        {
            "check": "remote_root_policy",
            "ok": True,
            "path": validate_remote_root(remote_root).as_posix(),
            "note": "doctor is read-only; directory creation happens during upload/run",
        }
    )
    return {
        "host": resolved_host,
        "read_only": True,
        "task_types": task_types,
        "checks": checks,
    }


def _remote_library_scan_script(
    *,
    library_root: str,
    query: str,
    limit: int,
    max_files: int,
) -> str:
    return "\n".join(
        [
            "set -euo pipefail",
            f"library_root={shlex.quote(library_root)}",
            f"query={shlex.quote(query)}",
            f"limit={int(limit)}",
            f"max_files={int(max_files)}",
            "export library_root query limit max_files",
            "python3 - <<'PY'",
            "import hashlib, json, os, re",
            "from collections import Counter",
            "from datetime import datetime, timezone",
            "root = os.environ['library_root']",
            "query = os.environ['query']",
            "limit = int(os.environ['limit'])",
            "max_files = int(os.environ['max_files'])",
            "terms = [term.lower() for term in query.replace('_', ' ').replace('-', ' ').split() if term]",
            "def tokenize(*values):",
            "    text = ' '.join(str(value or '') for value in values)",
            "    return [token for token in re.findall(r'[a-z0-9]+', text.lower()) if len(token) >= 2]",
            "allowed_exts = {'.pdf', '.txt', '.json', '.jsonl', '.md', '.bib', '.ris', '.csv', '.tsv'}",
            "extension_counts = Counter()",
            "document_frequency = Counter()",
            "samples = []",
            "warnings = []",
            "scanned = 0",
            "matched = 0",
            "truncated = False",
            "if not os.path.isdir(root):",
            "    raise SystemExit(f'library root is not a directory: {root}')",
            "for current, dirs, files in os.walk(root):",
            "    dirs[:] = sorted(name for name in dirs if not name.startswith('.'))",
            "    for name in sorted(files):",
            "        path = os.path.join(current, name)",
            "        if os.path.islink(path):",
            "            continue",
            "        ext = os.path.splitext(name)[1].lower()",
            "        if ext not in allowed_exts:",
            "            continue",
            "        rel = os.path.relpath(path, root)",
            "        scanned += 1",
            "        extension_counts[ext] += 1",
            "        haystack = rel.lower().replace('_', ' ').replace('-', ' ')",
            "        matched_terms = [term for term in terms if term in haystack]",
            "        is_match = not terms or bool(matched_terms)",
            "        if is_match:",
            "            matched += 1",
            "            basename_tokens = tokenize(os.path.splitext(name)[0], ' '.join(matched_terms))",
            "            token_counts = Counter(basename_tokens)",
            "            document_frequency.update(token_counts.keys())",
            "            if len(samples) < limit:",
            "                try:",
            "                    size_bytes = os.path.getsize(path)",
            "                except OSError:",
            "                    size_bytes = 0",
            "                samples.append({",
            "                    'basename': os.path.basename(path)[:255],",
            "                    'extension': ext,",
            "                    'size_bytes': int(size_bytes),",
            "                    'relative_path_hash': hashlib.sha256(rel.encode('utf-8')).hexdigest(),",
            "                    'path_depth': len(rel.split(os.sep)),",
            "                    'matched_terms': matched_terms[:20],",
            "                    'token_counts': dict(sorted(token_counts.items())),",
            "                    'token_count': int(sum(token_counts.values())),",
            "                })",
            "        if scanned >= max_files:",
            "            truncated = True",
            "            break",
            "    if scanned >= max_files:",
            "        break",
            "payload = {",
            "    'schema_version': 'remote_library_snapshot.v1',",
            "    'created_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),",
            "    'query': query,",
            "    'host_alias_hash': '',",
            "    'library_root_hash': '',",
            "    'max_files_scanned': max_files,",
            "    'scanned_file_count': scanned,",
            "    'matched_file_count': matched,",
            "    'truncated': truncated,",
            "    'extension_counts': dict(sorted(extension_counts.items())),",
            "    'document_frequency': dict(sorted(document_frequency.items())),",
            "    'samples': samples,",
            "    'warnings': warnings,",
            "}",
            "print(json.dumps(payload, ensure_ascii=False, sort_keys=True))",
            "PY",
        ]
    )


def status_payload(
    path_or_task_id: str,
    *,
    local_root: str | Path = DEFAULT_LOCAL_ROOT,
) -> dict[str, Any]:
    candidate = Path(path_or_task_id)
    task_dir = candidate if candidate.exists() else Path(local_root) / path_or_task_id
    if (task_dir / RESULT_MANIFEST).exists():
        manifest = validate_result_package(task_dir)
        return {
            "kind": "result",
            "path": str(task_dir),
            "task_id": manifest["task_id"],
            "task_type": manifest["task_type"],
            "status": manifest["status"],
            "output_count": len(manifest["output_hashes"]),
        }
    if (task_dir / TASK_MANIFEST).exists():
        manifest = load_task_manifest(task_dir)
        return {
            "kind": "task",
            "path": str(task_dir),
            "task_id": manifest["task_id"],
            "task_type": manifest["task_type"],
            "status": manifest["status"],
            "input_count": len(manifest["input_hashes"]),
        }
    raise OffloadError(f"no offload manifest found at {task_dir}")


def create_batch_plan(
    items: Iterable[str | Path],
    *,
    out_path: str | Path,
    host: str | None,
    remote_root: str | Path,
    concurrency: int,
) -> Path:
    if concurrency <= 0:
        raise OffloadError("concurrency must be a positive integer")
    resolved_host = validate_host_alias(configured_host(host))
    remote = validate_remote_root(remote_root)
    plan_path = Path(out_path)
    plan_parent = plan_path.parent
    plan_parent.mkdir(parents=True, exist_ok=True)
    item_paths = [Path(item) for item in items]
    if not item_paths:
        raise OffloadError("batch plan must include at least one item")

    plan_items = [
        _batch_plan_item(
            item,
            plan_parent=plan_parent,
            host=resolved_host,
            remote_root=remote,
        )
        for item in item_paths
    ]
    payload = {
        "schema_version": BATCH_PLAN_SCHEMA_VERSION,
        "created_at": utc_iso_timestamp(),
        "host": resolved_host,
        "remote_root": remote.as_posix(),
        "concurrency": concurrency,
        "items": plan_items,
    }
    _write_json(plan_path, payload)
    return plan_path


def create_offload_queue(
    items: Iterable[str | Path],
    *,
    out_path: str | Path,
    host: str | None,
    remote_root: str | Path,
    local_root: str | Path = DEFAULT_LOCAL_ROOT,
) -> Path:
    resolved_host = validate_host_alias(configured_host(host))
    remote = validate_remote_root(remote_root)
    queue_path = Path(out_path)
    queue_parent = queue_path.parent
    queue_parent.mkdir(parents=True, exist_ok=True)
    item_paths = [Path(item) for item in items]
    if not item_paths:
        raise OffloadError("queue must include at least one item")
    queue_items = [
        _queue_item(
            item,
            queue_parent=queue_parent,
            host=resolved_host,
            remote_root=remote,
        )
        for item in item_paths
    ]
    payload = {
        "schema_version": OFFLOAD_QUEUE_SCHEMA_VERSION,
        "created_at": utc_iso_timestamp(),
        "host": resolved_host,
        "remote_root": remote.as_posix(),
        "local_root": Path(local_root).as_posix(),
        "items": queue_items,
    }
    _write_json(queue_path, payload)
    return queue_path


def status_offload_queue(queue_path: str | Path) -> dict[str, Any]:
    path = Path(queue_path)
    queue = _load_offload_queue(path)
    by_next_action: dict[str, int] = {}
    by_queue_status: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for item in queue["items"]:
        queue_item = _validate_queue_item(item)
        by_next_action[queue_item["next_action"]] = (
            by_next_action.get(queue_item["next_action"], 0) + 1
        )
        by_queue_status[queue_item["queue_status"]] = (
            by_queue_status.get(queue_item["queue_status"], 0) + 1
        )
        items.append(queue_item)
    return {
        "schema_version": OFFLOAD_QUEUE_SCHEMA_VERSION,
        "path": str(path),
        "total": len(items),
        "by_next_action": by_next_action,
        "by_queue_status": by_queue_status,
        "items": items,
    }


def run_offload_queue_once(
    queue_path: str | Path,
    *,
    local_copy: bool = False,
    command_runner: Callable[[Sequence[str]], Any] | None = None,
) -> dict[str, Any]:
    path = Path(queue_path)
    queue = _load_offload_queue(path)
    items = [_validate_queue_item(item) for item in queue["items"]]
    index = next(
        (
            idx
            for idx, item in enumerate(items)
            if item["next_action"] in {"upload", "fetch", "import"}
        ),
        None,
    )
    if index is None:
        return {
            "schema_version": OFFLOAD_QUEUE_SCHEMA_VERSION,
            "path": str(path),
            "action": None,
            "status": "idle",
        }
    item = items[index]
    action = item["next_action"]
    started_at = utc_iso_timestamp()
    success = False
    error = ""
    result: dict[str, Any] = {}
    try:
        if action == "upload":
            result = upload_task(
                path.parent / item["path"],
                remote_root=queue["remote_root"],
                host=queue.get("host"),
                execute=not local_copy,
                command_runner=command_runner,
            )
            success = True
            item["queue_status"] = "waiting_remote_run"
            item["next_action"] = "fetch"
        elif action == "fetch":
            result = fetch_task(
                item["task_id"],
                local_root=queue.get("local_root", DEFAULT_LOCAL_ROOT),
                remote_root=queue["remote_root"],
                host=queue.get("host"),
                execute=not local_copy,
                command_runner=command_runner,
            )
            success = True
            item["queue_status"] = "ready_to_import"
            item["next_action"] = "import"
            item["path"] = _relative_plan_path(
                Path(result["local_path"]),
                plan_parent=path.parent,
            )
            item["kind"] = "result"
            item["status"] = result["status"]
        elif action == "import":
            item["queue_status"] = "manual_import_ready"
            item["next_action"] = "import"
            result = {"status": "manual_import_required"}
            success = True
        else:
            raise OffloadError(f"unsupported queue action: {action}")
    except (OSError, OffloadError, subprocess.CalledProcessError) as exc:
        error = str(exc)
        item["queue_status"] = "retryable_error"
        result = {"status": "retryable_error"}
    attempt = {
        "action": action,
        "started_at": started_at,
        "finished_at": utc_iso_timestamp(),
        "success": success,
        "status": result.get("status"),
    }
    if error:
        attempt["error"] = error[:500]
    item["attempts"] = [*item.get("attempts", []), attempt]
    queue["items"] = [
        item if idx == index else other for idx, other in enumerate(items)
    ]
    queue["updated_at"] = utc_iso_timestamp()
    _write_json(path, queue)
    return {
        "schema_version": OFFLOAD_QUEUE_SCHEMA_VERSION,
        "path": str(path),
        "task_id": item["task_id"],
        "task_type": item["task_type"],
        "action": action,
        "status": result.get("status"),
        "success": success,
        "next_action": item["next_action"],
        "queue_status": item["queue_status"],
    }


def status_batch_plan(plan_path: str | Path) -> dict[str, Any]:
    path = Path(plan_path)
    items = _load_batch_plan(path)["items"]

    by_status: dict[str, int] = {}
    ready_to_upload = 0
    ready_to_import = 0
    for item in items:
        if not isinstance(item, dict):
            raise OffloadError("batch plan item must be an object")
        status = str(item.get("status") or "")
        if status not in OFFLOAD_STATUSES:
            raise OffloadError(f"unsupported status: {status}")
        by_status[status] = by_status.get(status, 0) + 1
        kind = item.get("kind")
        if kind == "task" and status == "prepared":
            ready_to_upload += 1
        elif kind == "result" and status in {"succeeded", "partial", "failed"}:
            ready_to_import += 1
        elif kind not in {"task", "result"}:
            raise OffloadError(f"unsupported batch item kind: {kind}")
    return {
        "schema_version": BATCH_PLAN_SCHEMA_VERSION,
        "path": str(path),
        "total": len(items),
        "by_status": by_status,
        "ready_to_upload": ready_to_upload,
        "ready_to_import": ready_to_import,
    }


def reconcile_batch_plan(plan_path: str | Path) -> dict[str, Any]:
    path = Path(plan_path)
    items = _load_batch_plan(path)["items"]
    plan_parent = path.parent
    reconciled_items: list[dict[str, Any]] = []
    by_plan_status: dict[str, int] = {}
    by_actual_status: dict[str, int] = {}
    resume: dict[str, list[str]] = {
        "ready_to_upload": [],
        "ready_to_import": [],
        "manual_remote_action": [],
        "missing": [],
        "invalid": [],
    }
    drift_count = 0
    missing_count = 0
    invalid_count = 0

    for item in items:
        plan_item = _validate_batch_plan_item(item)
        plan_status = str(plan_item["status"])
        task_id = str(plan_item["task_id"])
        by_plan_status[plan_status] = by_plan_status.get(plan_status, 0) + 1
        try:
            actual = _inspect_batch_plan_item(
                plan_item,
                plan_parent=plan_parent,
            )
        except OffloadError as exc:
            actual = {
                "actual_kind": "invalid",
                "actual_status": "invalid",
                "task_id": task_id,
                "task_type": str(plan_item.get("task_type") or ""),
                "error": str(exc),
            }

        actual_status = str(actual["actual_status"])
        actual_kind = str(actual["actual_kind"])
        by_actual_status[actual_status] = by_actual_status.get(actual_status, 0) + 1
        drift = (
            actual_kind != plan_item["kind"]
            or actual_status != plan_status
            or actual.get("task_id") != task_id
            or actual.get("task_type") != plan_item.get("task_type")
        )
        if drift:
            drift_count += 1
        if actual_kind == "missing":
            missing_count += 1
            resume["missing"].append(task_id)
        elif actual_kind == "invalid":
            invalid_count += 1
            resume["invalid"].append(task_id)
        elif actual_kind == "task" and actual_status == "prepared":
            resume["ready_to_upload"].append(task_id)
        elif actual_kind == "result" and actual_status in {"succeeded", "partial"}:
            resume["ready_to_import"].append(task_id)
        elif actual_kind == "result" and actual_status in {"failed", "abandoned"}:
            resume["manual_remote_action"].append(task_id)
        elif actual_status in {"uploaded", "running"}:
            resume["manual_remote_action"].append(task_id)

        reconciled_items.append(
            {
                **plan_item,
                "plan_status": plan_status,
                "actual_kind": actual_kind,
                "actual_status": actual_status,
                "actual_task_id": actual.get("task_id"),
                "actual_task_type": actual.get("task_type"),
                "drift": drift,
                **({"error": actual["error"]} if actual.get("error") else {}),
            }
        )

    return {
        "schema_version": BATCH_PLAN_SCHEMA_VERSION,
        "path": str(path),
        "total": len(items),
        "by_plan_status": by_plan_status,
        "by_actual_status": by_actual_status,
        "drift_count": drift_count,
        "missing_count": missing_count,
        "invalid_count": invalid_count,
        "resume": resume,
        "items": reconciled_items,
    }


def preflight_batch_plan(
    plan_path: str | Path,
    *,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(plan_path)
    items = _load_batch_plan(path)["items"]
    parsed_capabilities = _normalize_worker_capabilities(capabilities)
    preflight_items: list[dict[str, Any]] = []
    allowed_count = 0
    blocked_count = 0
    warning_count = 0

    for item in items:
        plan_item = _validate_batch_plan_item(item)
        if plan_item["kind"] != "task":
            preflight_items.append(
                {
                    **plan_item,
                    "allowed": True,
                    "reasons": [],
                    "warnings": ["result_item_no_worker_policy_needed"],
                    "resource_hint": {},
                }
            )
            allowed_count += 1
            warning_count += 1
            continue
        task_dir = path.parent / str(plan_item["path"])
        manifest = load_task_manifest(task_dir)
        reasons: list[str] = []
        warnings: list[str] = []
        task_type = str(manifest["task_type"])
        resource_hint = dict(manifest.get("resource_hint", {}))
        supported_task_types = parsed_capabilities.get("supported_task_types")
        resources = parsed_capabilities.get("resources", {})
        features = parsed_capabilities.get("features", {})
        cache_policy = parsed_capabilities.get("cache_policy", {})
        model_policy = _model_policy_for_task(task_type, features)
        pdf_input_count = _task_pdf_input_count(task_dir, task_type)
        if supported_task_types is None:
            warnings.append("worker_capabilities_not_provided")
        elif task_type not in supported_task_types:
            reasons.append("unsupported_task_type")
        if resource_hint.get("gpu") is True and resources.get("gpu") is False:
            reasons.append("gpu_required_unavailable")
        if _resource_too_small(resource_hint, resources, "cpu"):
            reasons.append("cpu_below_hint")
        if _resource_too_small(resource_hint, resources, "memory_gb"):
            reasons.append("memory_below_hint")
        if (
            capabilities is not None
            and pdf_input_count
            and not features.get("pdf_parsers")
        ):
            reasons.append("pdf_parser_unavailable")
        if capabilities is not None and model_policy["required"]:
            if not model_policy["available"]:
                reasons.append("model_capability_not_declared")
            if not cache_policy:
                reasons.append("cache_policy_missing")
            elif not _cache_policy_ready(cache_policy):
                reasons.append("cache_policy_invalid")
        allowed = not reasons
        allowed_count += int(allowed)
        blocked_count += int(not allowed)
        warning_count += len(warnings)
        preflight_items.append(
            {
                **plan_item,
                "allowed": allowed,
                "reasons": reasons,
                "warnings": warnings,
                "resource_hint": resource_hint,
                "resources": resources,
                "features": features,
                "cache_policy": cache_policy,
                "cleanup_policy": dict(manifest.get("cleanup_policy", {})),
                "model_policy": model_policy,
                "pdf_input_count": pdf_input_count,
            }
        )

    return {
        "schema_version": BATCH_PLAN_SCHEMA_VERSION,
        "path": str(path),
        "capabilities_provided": capabilities is not None,
        "total": len(preflight_items),
        "allowed_count": allowed_count,
        "blocked_count": blocked_count,
        "warning_count": warning_count,
        "items": preflight_items,
    }


def import_task_result(
    result_dir: str | Path,
    *,
    db_path: str | Path,
    topic: str,
) -> dict[str, Any]:
    result_path = Path(result_dir)
    manifest = validate_result_package(result_path)
    task_manifest = _optional_task_manifest(result_path, manifest)
    db = Database(db_path)
    db.migrate()
    topic_id = _topic_id_or_error(db, topic)
    paper_artifact_imports = _import_paper_text_extraction_artifacts(
        db,
        result_dir=result_path,
        manifest=manifest,
    )
    artifact_type = (
        REMOTE_OFFLOAD_RESULT_ARTIFACT
        if manifest["status"] == "succeeded"
        else REMOTE_OFFLOAD_DIAGNOSTIC_ARTIFACT
    )
    payload = {
        "schema_version": REMOTE_OFFLOAD_SCHEMA_VERSION,
        "task_manifest": task_manifest,
        "result_manifest": manifest,
        "result_path": f"results/{manifest['task_id']}",
        "outputs": sorted(manifest["output_hashes"]),
        "paper_artifact_imports": paper_artifact_imports,
    }
    metadata = {
        "origin": REMOTE_OFFLOAD_ORIGIN,
        "task_id": manifest["task_id"],
        "task_type": manifest["task_type"],
        "status": manifest["status"],
        "input_hashes": task_manifest.get("input_hashes", {}),
        "output_hashes": manifest["output_hashes"],
        "server_result_path": f"results/{manifest['task_id']}",
        "untrusted_remote_metadata": {
            "server_hostname": manifest["server_hostname"],
            "git_commit": manifest["git_commit"],
        },
    }
    artifact = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="build",
        artifact_type=artifact_type,
        title=f"Remote offload {manifest['task_type']} {manifest['status']}",
        path=f"results/{manifest['task_id']}",
        payload=payload,
        metadata=metadata,
    )
    if artifact is None:
        raise OffloadError("failed to record offload artifact")
    provenance_record_id = _record_import_provenance(
        db,
        topic_id=topic_id,
        artifact_id=artifact.id,
        manifest=manifest,
        task_manifest=task_manifest,
    )
    _link_artifact_provenance(db, artifact.id, provenance_record_id)
    deep_result_imports = _import_deep_result_artifacts(
        db,
        topic_id=topic_id,
        receipt_artifact_id=artifact.id,
        provenance_record_id=provenance_record_id,
        result_dir=result_path,
        manifest=manifest,
        task_manifest=task_manifest,
    )
    payload["deep_result_imports"] = deep_result_imports
    _update_project_artifact_payload(db, artifact.id, payload)
    _append_receipt_attempt(
        result_path,
        manifest=manifest,
        operation="import",
        status=manifest["status"],
        artifact_id=artifact.id,
        artifact_type=artifact_type,
        provenance_record_id=provenance_record_id,
        topic=str(topic),
        deep_result_imports=deep_result_imports,
    )
    return {
        "task_id": manifest["task_id"],
        "task_type": manifest["task_type"],
        "status": manifest["status"],
        "artifact_id": artifact.id,
        "artifact_type": artifact_type,
        "provenance_record_id": provenance_record_id,
        "paper_artifact_imports": paper_artifact_imports,
        "deep_result_imports": deep_result_imports,
    }


def validate_task_id(task_id: str) -> None:
    if not task_id or any(ch in task_id for ch in "/\\\x00"):
        raise OffloadError(f"unsafe task_id: {task_id}")
    if not all(ch.isalnum() or ch in {"-", "_", "."} for ch in task_id):
        raise OffloadError(f"unsafe task_id: {task_id}")
    if task_id in {".", ".."}:
        raise OffloadError(f"unsafe task_id: {task_id}")


def _record_import_provenance(
    db: Database,
    *,
    topic_id: int,
    artifact_id: int,
    manifest: dict[str, Any],
    task_manifest: dict[str, Any],
) -> int:
    status = str(manifest["status"])
    success = status == "succeeded"
    output_hash_value = _hash_json(manifest["output_hashes"])
    timestamp = utc_iso_timestamp()
    result = _OffloadImportResult(
        primitive="offload_import",
        started_at=timestamp,
        finished_at=timestamp,
        backend=REMOTE_OFFLOAD_ORIGIN,
        model_used="none",
        cost_usd=0.0,
        success=success,
        error="" if success else status,
        output_hash_value=output_hash_value,
    )
    return ProvenanceRecorder(db).record(
        result,
        {
            "task_id": manifest["task_id"],
            "task_type": manifest["task_type"],
            "status": status,
            "input_hashes": task_manifest.get("input_hashes", {}),
            "output_hashes": manifest["output_hashes"],
            "untrusted_remote_metadata": {
                "server_hostname": manifest["server_hostname"],
                "git_commit": manifest["git_commit"],
            },
        },
        topic_id=topic_id,
        stage="build",
        artifact_id=artifact_id,
        actor="rh offload import",
        origin=REMOTE_OFFLOAD_ORIGIN,
        category="offload",
    )


def _remote_probe_checks(stdout: str, *, remote_root: Path) -> list[dict[str, Any]]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    python_line = next((line for line in lines if line.startswith("Python ")), "")
    gpu_lines = [line for line in lines if line.startswith("GPU ")]
    package_lines = [line for line in lines if line.startswith("package:")]
    packages = _parse_package_probe_lines(package_lines)
    command_lines = [line for line in lines if line.startswith("command:")]
    commands = _parse_command_probe_lines(command_lines)
    capabilities = _parse_capabilities_lines(lines)
    disk_lines = [
        line
        for line in lines
        if "%" in line and not line.lower().startswith("filesystem")
    ]
    directory_status = {
        "incoming": "exists" if "incoming_exists" in lines else "missing",
        "runs": "exists" if "runs_exists" in lines else "missing",
        "results": "exists" if "results_exists" in lines else "missing",
        "cache": "exists" if "cache_exists" in lines else "missing",
    }
    return [
        {
            "check": "remote_python",
            "ok": bool(python_line),
            "version": python_line or None,
        },
        {
            "check": "remote_root",
            "ok": "root_exists" in lines,
            "path": remote_root.as_posix(),
        },
        {
            "check": "remote_directories",
            "ok": all(value == "exists" for value in directory_status.values()),
            "status": directory_status,
            "optional": True,
        },
        {
            "check": "remote_disk",
            "ok": bool(disk_lines),
            "summary": disk_lines[0] if disk_lines else None,
        },
        {
            "check": "remote_gpu",
            "ok": bool(gpu_lines),
            "devices": gpu_lines,
            "count": len(gpu_lines),
            "optional": True,
        },
        {
            "check": "remote_packages",
            "ok": bool(packages),
            "packages": packages,
            "optional": True,
        },
        {
            "check": "remote_commands",
            "ok": bool(commands),
            "commands": commands,
            "optional": True,
        },
        {
            "check": "worker_capabilities",
            "ok": bool(capabilities),
            "supported_task_types": capabilities.get("supported_task_types", []),
            "resources": capabilities.get("resources", {}),
            "features": capabilities.get("features", {}),
            "cache_policy": capabilities.get("cache_policy", {}),
            "notes": capabilities.get("notes", []),
            "schema_version": capabilities.get("schema_version"),
            "optional": True,
        },
        {
            "check": "remote_runner",
            "ok": "runner_executable" in lines or "runner_not_checked" in lines,
            "note": (
                "runner executable check is meaningful only inside a prepared run directory"
            ),
        },
    ]


def _parse_package_probe_lines(lines: list[str]) -> dict[str, str]:
    packages: dict[str, str] = {}
    for line in lines:
        _, name, status = line.split(":", 2)
        packages[name] = status
    return packages


def _parse_command_probe_lines(lines: list[str]) -> dict[str, str]:
    commands: dict[str, str] = {}
    for line in lines:
        _, name, status = line.split(":", 2)
        commands[name] = status
    return commands


def _parse_capabilities_lines(lines: list[str]) -> dict[str, Any]:
    prefix = "RH_OFFLOAD_CAPABILITIES_JSON="
    raw = next(
        (line.removeprefix(prefix) for line in lines if line.startswith(prefix)), "{}"
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        normalized = _normalize_worker_capabilities(payload)
    except OffloadError:
        return {}
    return {
        "schema_version": normalized.get("schema_version"),
        "supported_task_types": sorted(normalized.get("supported_task_types") or []),
        "resources": normalized.get("resources", {}),
        "features": normalized.get("features", {}),
        "cache_policy": normalized.get("cache_policy", {}),
        "notes": normalized.get("notes", []),
    }


def _optional_task_manifest(
    result_dir: Path, result_manifest: dict[str, Any]
) -> dict[str, Any]:
    path = result_dir / TASK_MANIFEST
    if not path.exists():
        return {
            "task_id": result_manifest["task_id"],
            "task_type": result_manifest["task_type"],
            "input_hashes": {},
        }
    manifest = _read_json(path)
    validate_task_manifest(manifest)
    if manifest["task_id"] != result_manifest["task_id"]:
        raise OffloadError("task_id mismatch between task and result manifests")
    if manifest["task_type"] != result_manifest["task_type"]:
        raise OffloadError("task_type mismatch between task and result manifests")
    return manifest


def _batch_plan_item(
    item_path: Path,
    *,
    plan_parent: Path,
    host: str,
    remote_root: Path,
) -> dict[str, Any]:
    if item_path.is_symlink():
        raise OffloadError(f"unsafe symlink path: {item_path}")
    if (item_path / RESULT_MANIFEST).exists():
        manifest = validate_result_package(item_path)
        return {
            "kind": "result",
            "path": _relative_plan_path(item_path, plan_parent=plan_parent),
            "task_id": manifest["task_id"],
            "task_type": manifest["task_type"],
            "status": manifest["status"],
            "commands": {},
        }
    if (item_path / TASK_MANIFEST).exists():
        manifest = load_task_manifest(item_path)
        return {
            "kind": "task",
            "path": _relative_plan_path(item_path, plan_parent=plan_parent),
            "task_id": manifest["task_id"],
            "task_type": manifest["task_type"],
            "status": "prepared",
            "commands": {
                "run": build_runner_command(
                    str(manifest["task_id"]),
                    host=host,
                    remote_root=remote_root,
                )
            },
        }
    raise OffloadError(f"no offload manifest found at {item_path}")


def _queue_item(
    item_path: Path,
    *,
    queue_parent: Path,
    host: str,
    remote_root: Path,
) -> dict[str, Any]:
    base = _batch_plan_item(
        item_path,
        plan_parent=queue_parent,
        host=host,
        remote_root=remote_root,
    )
    next_action = "upload" if base["kind"] == "task" else "import"
    return {
        **base,
        "queue_status": "queued",
        "next_action": next_action,
        "attempts": [],
    }


def _load_offload_queue(path: Path) -> dict[str, Any]:
    queue = _read_json(path)
    if queue.get("schema_version") != OFFLOAD_QUEUE_SCHEMA_VERSION:
        raise OffloadError(f"unsupported offload queue schema: {path}")
    items = queue.get("items")
    if not isinstance(items, list):
        raise OffloadError("offload queue items must be a list")
    remote_root = validate_remote_root(queue.get("remote_root") or "")
    local_root = Path(str(queue.get("local_root") or DEFAULT_LOCAL_ROOT)).as_posix()
    return {
        **queue,
        "remote_root": remote_root.as_posix(),
        "local_root": local_root,
        "items": items,
    }


def _validate_queue_item(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise OffloadError("offload queue item must be an object")
    base = _validate_batch_plan_item(item)
    queue_status = str(item.get("queue_status") or "")
    if queue_status not in {
        "queued",
        "waiting_remote_run",
        "ready_to_import",
        "manual_import_ready",
        "retryable_error",
        "done",
        "abandoned",
    }:
        raise OffloadError(f"unsupported queue_status: {queue_status}")
    next_action = str(item.get("next_action") or "")
    if next_action not in {"upload", "fetch", "import", "none"}:
        raise OffloadError(f"unsupported queue next_action: {next_action}")
    attempts = item.get("attempts", [])
    if not isinstance(attempts, list):
        raise OffloadError("offload queue attempts must be a list")
    return {
        **base,
        "queue_status": queue_status,
        "next_action": next_action,
        "attempts": [attempt for attempt in attempts if isinstance(attempt, dict)],
    }


def _load_batch_plan(path: Path) -> dict[str, Any]:
    plan = _read_json(path)
    if plan.get("schema_version") != BATCH_PLAN_SCHEMA_VERSION:
        raise OffloadError(f"unsupported batch plan schema: {path}")
    items = plan.get("items")
    if not isinstance(items, list):
        raise OffloadError("batch plan items must be a list")
    return {**plan, "items": items}


def _validate_batch_plan_item(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise OffloadError("batch plan item must be an object")
    kind = item.get("kind")
    if kind not in {"task", "result"}:
        raise OffloadError(f"unsupported batch item kind: {kind}")
    status = str(item.get("status") or "")
    if status not in OFFLOAD_STATUSES:
        raise OffloadError(f"unsupported status: {status}")
    task_id = str(item.get("task_id") or "")
    validate_task_id(task_id)
    task_type = item.get("task_type")
    if task_type not in TASK_TYPES:
        raise OffloadError(f"unsupported task_type: {task_type}")
    path = _validate_batch_plan_relative_path(str(item.get("path") or ""))
    return {
        "kind": kind,
        "path": path,
        "task_id": task_id,
        "task_type": task_type,
        "status": status,
        "commands": item.get("commands")
        if isinstance(item.get("commands"), dict)
        else {},
    }


def _inspect_batch_plan_item(
    item: dict[str, Any],
    *,
    plan_parent: Path,
) -> dict[str, Any]:
    item_path = plan_parent / str(item["path"])
    if item_path.is_symlink():
        raise OffloadError(f"unsafe symlink path: {item_path}")
    if not item_path.exists():
        return {
            "actual_kind": "missing",
            "actual_status": "missing",
            "task_id": item["task_id"],
            "task_type": item["task_type"],
        }
    if (item_path / RESULT_MANIFEST).exists():
        manifest = validate_result_package(item_path)
        return {
            "actual_kind": "result",
            "actual_status": manifest["status"],
            "task_id": manifest["task_id"],
            "task_type": manifest["task_type"],
        }
    if (item_path / TASK_MANIFEST).exists():
        manifest = load_task_manifest(item_path)
        return {
            "actual_kind": "task",
            "actual_status": manifest["status"],
            "task_id": manifest["task_id"],
            "task_type": manifest["task_type"],
        }
    raise OffloadError(f"no offload manifest found at {item_path}")


def _normalize_worker_capabilities(
    capabilities: dict[str, Any] | None,
) -> dict[str, Any]:
    if capabilities is None:
        return {
            "schema_version": None,
            "supported_task_types": None,
            "resources": {},
            "features": {},
            "cache_policy": {},
            "notes": [],
        }
    if not isinstance(capabilities, dict):
        raise OffloadError("worker capabilities must be an object")
    supported = capabilities.get("supported_task_types")
    if supported is None:
        supported_task_types: set[str] | None = None
    elif isinstance(supported, list):
        supported_task_types = {
            str(item) for item in supported if str(item) in TASK_TYPES
        }
    else:
        raise OffloadError("supported_task_types must be a list")
    resources = capabilities.get("resources", {})
    if not isinstance(resources, dict):
        raise OffloadError("capability resources must be an object")
    normalized_resources: dict[str, Any] = {}
    if "gpu" in resources:
        normalized_resources["gpu"] = bool(resources["gpu"])
    for key in ("cpu", "memory_gb"):
        value = resources.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            normalized_resources[key] = float(value)
    features = capabilities.get("features", {})
    if not isinstance(features, dict):
        raise OffloadError("capability features must be an object")
    cache_policy = capabilities.get("cache_policy", {})
    if not isinstance(cache_policy, dict):
        raise OffloadError("capability cache_policy must be an object")
    notes = capabilities.get("notes", [])
    if not isinstance(notes, list):
        raise OffloadError("capability notes must be a list")
    return {
        "schema_version": str(
            capabilities.get("schema_version") or WORKER_CAPABILITY_SCHEMA_VERSION
        ),
        "supported_task_types": supported_task_types,
        "resources": normalized_resources,
        "features": _normalize_capability_features(features),
        "cache_policy": _normalize_cache_policy(cache_policy),
        "notes": [str(item)[:200] for item in notes],
    }


def _normalize_task_model_policy(
    policy: dict[str, Any] | None,
    *,
    task_type: str,
) -> dict[str, Any] | None:
    if policy is None:
        return None
    if task_type not in {"wiki_embedding_batch", "retrieval_eval_sweep"}:
        raise OffloadError(f"model_policy is not supported for {task_type}")
    if not isinstance(policy, dict):
        raise OffloadError("model_policy must be an object")
    backend = str(policy.get("backend") or "").strip()
    if backend not in {"fake_model"}:
        raise OffloadError(f"unsupported model_policy backend: {backend}")
    model_id = str(policy.get("model_id") or "").strip()
    if not model_id or "\x00" in model_id or len(model_id) > 128:
        raise OffloadError("model_policy.model_id must be a short string")
    device = str(policy.get("device") or "cpu").strip()[:64]
    normalized: dict[str, Any] = {
        "backend": backend,
        "model_id": model_id,
        "device": device,
        "quality_claim": False,
    }
    if task_type == "wiki_embedding_batch":
        dim = _coerce_positive_int(
            policy.get("embedding_dim", 16),
            field_name="model_policy.embedding_dim",
        )
        if dim > 4096:
            raise OffloadError("model_policy.embedding_dim is too large")
        normalized["embedding_dim"] = dim
    cache_policy = policy.get("cache_policy", {})
    if not isinstance(cache_policy, dict):
        raise OffloadError("model_policy.cache_policy must be an object")
    normalized_cache = _normalize_cache_policy(cache_policy)
    if cache_policy and not _cache_policy_ready(normalized_cache):
        raise OffloadError("model_policy.cache_policy is invalid")
    if normalized_cache:
        normalized["cache_policy"] = normalized_cache
    return normalized


def _normalize_capability_features(features: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    pdf_parsers = _normalize_string_list(
        features.get("pdf_parsers", []), field_name="features.pdf_parsers"
    )
    if pdf_parsers:
        normalized["pdf_parsers"] = pdf_parsers
    for capability in ("embedding", "rerank", "batch_eval"):
        value = features.get(capability, {})
        if value in (None, {}):
            continue
        if not isinstance(value, dict):
            raise OffloadError(f"features.{capability} must be an object")
        feature_payload: dict[str, Any] = {}
        for key in ("backends", "models"):
            entries = _normalize_string_list(
                value.get(key, []), field_name=f"features.{capability}.{key}"
            )
            if entries:
                feature_payload[key] = entries
        default_device = value.get("default_device")
        if isinstance(default_device, str) and default_device.strip():
            feature_payload["default_device"] = default_device.strip()[:64]
        if feature_payload:
            normalized[capability] = feature_payload
    return normalized


def _normalize_cache_policy(cache_policy: dict[str, Any]) -> dict[str, Any]:
    if not cache_policy:
        return {}
    normalized: dict[str, Any] = {}
    max_gb = cache_policy.get("max_gb", cache_policy.get("cache_max_gb"))
    if isinstance(max_gb, (int, float)) and max_gb >= 0:
        normalized["max_gb"] = float(max_gb)
    cleanup = cache_policy.get("cleanup")
    if isinstance(cleanup, str) and cleanup in {"manual", "ttl", "none"}:
        normalized["cleanup"] = cleanup
    cache_root = cache_policy.get("cache_root")
    if isinstance(cache_root, str) and cache_root:
        normalized["cache_root"] = validate_relative_path(cache_root.rstrip("/"))
    max_age_days = cache_policy.get("max_age_days")
    if isinstance(max_age_days, (int, float)) and max_age_days >= 0:
        normalized["max_age_days"] = float(max_age_days)
    return normalized


def _normalize_string_list(value: Any, *, field_name: str) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise OffloadError(f"{field_name} must be a list")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or "\x00" in text:
            continue
        text = text[:128]
        if text not in seen:
            cleaned.append(text)
            seen.add(text)
    return cleaned


def _task_pdf_input_count(task_dir: Path, task_type: str) -> int:
    if task_type != "paper_text_extraction_batch":
        return 0
    payload_path = task_dir / "inputs" / "paper_text_extraction_inputs.json"
    try:
        payload = _read_json(payload_path)
    except OffloadError:
        return 0
    papers = payload.get("papers", [])
    if not isinstance(papers, list):
        return 0
    return sum(
        1
        for paper in papers
        if isinstance(paper, dict) and isinstance(paper.get("pdf_file"), str)
    )


def _model_policy_for_task(task_type: str, features: dict[str, Any]) -> dict[str, Any]:
    capability = MODEL_CAPABILITY_BY_TASK.get(task_type)
    if capability is None:
        return {"required": False, "capability": None, "available": True}
    payload = features.get(capability, {})
    available = (
        isinstance(payload, dict)
        and bool(payload.get("backends"))
        and (bool(payload.get("models")) or capability == "batch_eval")
    )
    policy: dict[str, Any] = {
        "required": True,
        "capability": capability,
        "available": available,
    }
    if isinstance(payload, dict):
        policy["backends"] = list(payload.get("backends", []))
        policy["models"] = list(payload.get("models", []))
        if "default_device" in payload:
            policy["default_device"] = payload["default_device"]
    return policy


def _cache_policy_ready(cache_policy: dict[str, Any]) -> bool:
    return isinstance(cache_policy.get("max_gb"), (int, float)) and bool(
        cache_policy.get("cleanup")
    )


def _resource_too_small(
    resource_hint: dict[str, Any],
    resources: dict[str, Any],
    key: str,
) -> bool:
    hinted = resource_hint.get(key)
    available = resources.get(key)
    if not isinstance(hinted, (int, float)) or not isinstance(available, (int, float)):
        return False
    return float(available) < float(hinted)


def _relative_plan_path(path: Path, *, plan_parent: Path) -> str:
    try:
        raw = os.path.relpath(path, start=plan_parent)
    except ValueError as exc:
        raise OffloadError(f"cannot make batch item path relative: {path}") from exc
    rel = Path(raw)
    if rel.is_absolute() or not raw or "\x00" in raw or "\\" in raw:
        raise OffloadError(f"unsafe batch item path: {raw}")
    if any(part in {"", "."} for part in rel.parts):
        raise OffloadError(f"unsafe batch item path: {raw}")
    return rel.as_posix()


def _validate_batch_plan_relative_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise OffloadError(f"unsafe batch item path: {value}")
    path = Path(value)
    if path.is_absolute():
        raise OffloadError(f"unsafe batch item path: {value}")
    if any(part in {"", "."} for part in path.parts):
        raise OffloadError(f"unsafe batch item path: {value}")
    return path.as_posix()


def _append_receipt_attempt(
    directory: Path,
    *,
    manifest: dict[str, Any],
    operation: str,
    status: str,
    **fields: Any,
) -> None:
    receipt_path = directory / RECEIPT_FILE
    receipt = _read_receipt(receipt_path)
    attempt = {
        "operation": operation,
        "status": status,
        "recorded_at": utc_iso_timestamp(),
    }
    for key, value in fields.items():
        attempt[key] = _receipt_safe_value(value)
    receipt["task_id"] = manifest["task_id"]
    receipt["task_type"] = manifest["task_type"]
    receipt["attempts"] = [*receipt.get("attempts", []), attempt]
    _write_json(receipt_path, receipt)


def _read_receipt(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": REMOTE_OFFLOAD_RECEIPT_SCHEMA_VERSION,
            "task_id": None,
            "task_type": None,
            "attempts": [],
        }
    payload = _read_json(path)
    if payload.get("schema_version") != REMOTE_OFFLOAD_RECEIPT_SCHEMA_VERSION:
        raise OffloadError(f"unsupported receipt schema: {path}")
    attempts = payload.get("attempts", [])
    if not isinstance(attempts, list):
        raise OffloadError(f"receipt attempts must be a list: {path}")
    return payload


def _receipt_safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:512]
    if isinstance(value, bool) or isinstance(value, int) or value is None:
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, dict):
        return {
            str(key)[:128]: _receipt_safe_value(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_receipt_safe_value(item) for item in value[:50]]
    return str(value)[:512]


def _link_artifact_provenance(
    db: Database,
    artifact_id: int,
    provenance_record_id: int,
) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE project_artifacts SET provenance_record_id = ? WHERE id = ?",
            (provenance_record_id, artifact_id),
        )
        conn.commit()
    finally:
        conn.close()


def _update_project_artifact_payload(
    db: Database,
    artifact_id: int,
    payload: dict[str, Any],
) -> None:
    conn = db.connect()
    try:
        conn.execute(
            """
            UPDATE project_artifacts
            SET payload_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (json.dumps(payload, ensure_ascii=False), artifact_id),
        )
        conn.commit()
    finally:
        conn.close()


def _empty_deep_result_imports() -> dict[str, Any]:
    return {"imported": 0, "skipped": 0, "warnings": [], "artifacts": []}


def _import_deep_result_artifacts(
    db: Database,
    *,
    topic_id: int,
    receipt_artifact_id: int,
    provenance_record_id: int,
    result_dir: Path,
    manifest: dict[str, Any],
    task_manifest: dict[str, Any],
) -> dict[str, Any]:
    summary = _empty_deep_result_imports()
    if manifest["status"] != "succeeded":
        return summary

    try:
        spec = _deep_result_import_spec(
            result_dir=result_dir,
            manifest=manifest,
            task_manifest=task_manifest,
            receipt_artifact_id=receipt_artifact_id,
        )
    except OffloadError as exc:
        summary["skipped"] = 1
        summary["warnings"] = [str(exc)]
        return summary
    if spec is None:
        return summary

    existing_id = _find_existing_deep_result_artifact(
        db,
        topic_id=topic_id,
        artifact_type=spec["artifact_type"],
        metadata=spec["metadata"],
    )
    if existing_id is not None:
        summary["skipped"] = 1
        summary["artifacts"] = [
            {
                "artifact_id": existing_id,
                "artifact_type": spec["artifact_type"],
                "status": "skipped",
                "reason": "already_imported",
            }
        ]
        return summary

    artifact_id = _insert_deep_result_artifact(
        db,
        topic_id=topic_id,
        artifact_type=spec["artifact_type"],
        title=spec["title"],
        path=spec["path"],
        payload=spec["payload"],
        metadata=spec["metadata"],
        parent_artifact_id=receipt_artifact_id,
        provenance_record_id=provenance_record_id,
    )
    summary["imported"] = 1
    summary["artifacts"] = [
        {
            "artifact_id": artifact_id,
            "artifact_type": spec["artifact_type"],
            "status": "imported",
        }
    ]
    return summary


def _deep_result_import_spec(
    *,
    result_dir: Path,
    manifest: dict[str, Any],
    task_manifest: dict[str, Any],
    receipt_artifact_id: int,
) -> dict[str, Any] | None:
    task_type = manifest["task_type"]
    if task_type == "retrieval_eval_sweep":
        return _retrieval_eval_import_spec(
            result_dir=result_dir,
            manifest=manifest,
            task_manifest=task_manifest,
            receipt_artifact_id=receipt_artifact_id,
        )
    if task_type == "wiki_embedding_batch":
        return _wiki_embedding_import_spec(
            result_dir=result_dir,
            manifest=manifest,
            task_manifest=task_manifest,
            receipt_artifact_id=receipt_artifact_id,
        )
    return None


def _base_deep_result_metadata(
    *,
    manifest: dict[str, Any],
    task_manifest: dict[str, Any],
    artifact_role: str,
) -> dict[str, Any]:
    return {
        "origin": REMOTE_OFFLOAD_ORIGIN,
        "task_id": manifest["task_id"],
        "task_type": manifest["task_type"],
        "status": manifest["status"],
        "artifact_role": artifact_role,
        "canonical": False,
        "trusted_remote_metadata": False,
        "input_hashes": task_manifest.get("input_hashes", {}),
        "output_hashes": manifest["output_hashes"],
        "result_output_hash": _hash_json(manifest["output_hashes"]),
        "server_result_path": f"results/{manifest['task_id']}",
        "untrusted_remote_metadata": {
            "server_hostname": manifest["server_hostname"],
            "git_commit": manifest["git_commit"],
        },
    }


def _retrieval_eval_import_spec(
    *,
    result_dir: Path,
    manifest: dict[str, Any],
    task_manifest: dict[str, Any],
    receipt_artifact_id: int,
) -> dict[str, Any]:
    outputs_dir = result_dir / "outputs"
    report = _read_json(outputs_dir / "retrieval_eval_report.json")
    predictions = _read_jsonl_objects(outputs_dir / "predictions.jsonl")
    payload = {
        "schema_version": REMOTE_RETRIEVAL_EVAL_SCHEMA_VERSION,
        "receipt_artifact_id": receipt_artifact_id,
        "task_id": manifest["task_id"],
        "task_type": manifest["task_type"],
        "result_path": f"results/{manifest['task_id']}/outputs",
        "report": _deep_import_safe_value(report),
        "prediction_summary": _retrieval_prediction_summary(predictions),
        "output_hashes": manifest["output_hashes"],
        "interpretation": (
            "Remote retrieval-eval output imported as a conservative evidence "
            "artifact. It is not a benchmark, promotion, or quality claim."
        ),
    }
    metadata = _base_deep_result_metadata(
        manifest=manifest,
        task_manifest=task_manifest,
        artifact_role="remote_retrieval_eval",
    )
    metadata.update(
        {
            "report_schema_version": str(report.get("schema_version") or ""),
            "method": str(report.get("method") or ""),
        }
    )
    return {
        "artifact_type": REMOTE_RETRIEVAL_EVAL_ARTIFACT,
        "title": f"Remote retrieval eval {manifest['task_id']}",
        "path": f"results/{manifest['task_id']}/outputs",
        "payload": payload,
        "metadata": metadata,
    }


def _wiki_embedding_import_spec(
    *,
    result_dir: Path,
    manifest: dict[str, Any],
    task_manifest: dict[str, Any],
    receipt_artifact_id: int,
) -> dict[str, Any]:
    outputs_dir = result_dir / "outputs"
    summary = _read_json(outputs_dir / "summary.json")
    rows = _read_jsonl_objects(outputs_dir / "wiki_embeddings.jsonl")
    embedding_summary = _wiki_embedding_summary(rows)
    payload = {
        "schema_version": REMOTE_WIKI_EMBEDDING_SCHEMA_VERSION,
        "receipt_artifact_id": receipt_artifact_id,
        "task_id": manifest["task_id"],
        "task_type": manifest["task_type"],
        "result_path": f"results/{manifest['task_id']}/outputs",
        "summary": _deep_import_safe_value(summary),
        "embedding_summary": embedding_summary,
        "source_links": [
            f"project_artifacts:{artifact_id}"
            for artifact_id in embedding_summary["source_artifact_ids"]
        ],
        "retrieval_index_role": "remote_candidate_index",
        "output_hashes": manifest["output_hashes"],
        "interpretation": (
            "Remote embedding output imported as a candidate Topic Knowledge "
            "retrieval-index artifact. It does not replace local canonical "
            "indexes or assert retrieval quality."
        ),
    }
    metadata = _base_deep_result_metadata(
        manifest=manifest,
        task_manifest=task_manifest,
        artifact_role="topic_knowledge_retrieval_index",
    )
    metadata.update(
        {
            "summary_schema_version": str(summary.get("schema_version") or ""),
            "method": str(summary.get("method") or ""),
        }
    )
    return {
        "artifact_type": REMOTE_WIKI_EMBEDDING_ARTIFACT,
        "title": f"Remote wiki embedding index {manifest['task_id']}",
        "path": f"results/{manifest['task_id']}/outputs",
        "payload": payload,
        "metadata": metadata,
    }


def _retrieval_prediction_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sample_top_matches: list[dict[str, Any]] = []
    top_match_count = 0
    ranked_count = 0
    for row in rows:
        if str(row.get("status") or "") == "ranked":
            ranked_count += 1
        matches = row.get("top_matches", [])
        if not isinstance(matches, list):
            continue
        top_match_count += len(matches)
        for match in matches:
            if not isinstance(match, dict):
                continue
            if len(sample_top_matches) >= 5:
                break
            sample_top_matches.append(_safe_remote_match_summary(match))
    return {
        "row_count": len(rows),
        "ranked_count": ranked_count,
        "top_match_count": top_match_count,
        "sample_top_matches": sample_top_matches,
    }


def _safe_remote_match_summary(match: dict[str, Any]) -> dict[str, Any]:
    score = match.get("score")
    safe_score = float(score) if isinstance(score, (int, float)) else None
    relative_path_hash = str(match.get("relative_path_hash") or "")
    if len(relative_path_hash) != 64:
        relative_path_hash = ""
    return {
        "basename": _clean_snapshot_text(str(match.get("basename") or ""), max_len=255),
        "relative_path_hash": relative_path_hash,
        "score": safe_score,
    }


def _wiki_embedding_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_artifact_ids: list[int] = []
    methods: set[str] = set()
    embedding_dims: list[int] = []
    succeeded_count = 0
    for row in rows:
        method = str(row.get("method") or "")
        if method:
            methods.add(method)
        dim = _optional_positive_int(row.get("embedding_dim"))
        if dim is not None:
            embedding_dims.append(dim)
        if str(row.get("status") or "") != "succeeded":
            continue
        succeeded_count += 1
        artifact_id = _optional_positive_int(row.get("artifact_id"))
        if artifact_id is not None and artifact_id not in source_artifact_ids:
            source_artifact_ids.append(artifact_id)
    unique_dims = sorted(set(embedding_dims))
    return {
        "row_count": len(rows),
        "succeeded_count": succeeded_count,
        "skipped_count": max(0, len(rows) - succeeded_count),
        "embedding_dim": unique_dims[0] if len(unique_dims) == 1 else None,
        "embedding_dims": unique_dims,
        "methods": sorted(methods),
        "source_artifact_ids": source_artifact_ids,
    }


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        integer = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return integer if integer > 0 else None


def _deep_import_safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, bool) or isinstance(value, int) or value is None:
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, dict):
        return {
            str(key)[:128]: _deep_import_safe_value(item)
            for key, item in list(value.items())[:200]
        }
    if isinstance(value, list):
        return [_deep_import_safe_value(item) for item in value[:200]]
    return str(value)[:2000]


def _find_existing_deep_result_artifact(
    db: Database,
    *,
    topic_id: int,
    artifact_type: str,
    metadata: dict[str, Any],
) -> int | None:
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT id, metadata_json
            FROM project_artifacts
            WHERE topic_id = ? AND stage = 'build' AND artifact_type = ?
            ORDER BY id
            """,
            (topic_id, artifact_type),
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        existing = _json_object_from_text(row["metadata_json"] or "{}")
        if (
            existing.get("origin") == REMOTE_OFFLOAD_ORIGIN
            and existing.get("task_id") == metadata["task_id"]
            and existing.get("task_type") == metadata["task_type"]
            and existing.get("result_output_hash") == metadata["result_output_hash"]
        ):
            return int(row["id"])
    return None


def _insert_deep_result_artifact(
    db: Database,
    *,
    topic_id: int,
    artifact_type: str,
    title: str,
    path: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
    parent_artifact_id: int,
    provenance_record_id: int,
) -> int:
    conn = db.connect()
    try:
        project = conn.execute(
            "SELECT id FROM projects WHERE topic_id = ? ORDER BY id LIMIT 1",
            (topic_id,),
        ).fetchone()
        version_row = conn.execute(
            """
            SELECT MAX(version) AS version
            FROM project_artifacts
            WHERE topic_id = ? AND stage = 'build' AND artifact_type = ?
            """,
            (topic_id, artifact_type),
        ).fetchone()
        version = 1
        if version_row is not None and version_row["version"] is not None:
            version = int(version_row["version"]) + 1
        cur = conn.execute(
            """
            INSERT INTO project_artifacts
                (project_id, topic_id, stage, artifact_type, status, version,
                 title, path, payload_json, metadata_json, parent_artifact_id,
                 provenance_record_id)
            VALUES (?, ?, 'build', ?, 'active', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(project["id"]) if project is not None else None,
                topic_id,
                artifact_type,
                version,
                title,
                path,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(metadata, ensure_ascii=False),
                parent_artifact_id,
                provenance_record_id,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _import_paper_text_extraction_artifacts(
    db: Database,
    *,
    result_dir: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "imported": 0,
        "skipped": 0,
        "warnings": [],
    }
    if (
        manifest["status"] != "succeeded"
        or manifest["task_type"] != "paper_text_extraction_batch"
    ):
        return summary

    output_path = result_dir / "outputs" / "paper_text_extraction_results.jsonl"
    rows = _read_jsonl_objects(output_path)
    artifacts_root = (
        Path(db.db_path).parent
        / "artifacts"
        / REMOTE_OFFLOAD_ORIGIN
        / manifest["task_id"]
    )
    conn = db.connect()
    try:
        for index, row in enumerate(rows, start=1):
            try:
                outcome = _import_one_paper_text_artifact(
                    conn,
                    artifacts_root=artifacts_root,
                    manifest=manifest,
                    output_path=output_path,
                    row=row,
                )
            except OffloadError as exc:
                summary["warnings"].append(f"row {index}: {exc}")
                summary["skipped"] += 1
                continue
            summary[outcome] += 1
        conn.commit()
    finally:
        conn.close()
    return summary


def _import_one_paper_text_artifact(
    conn: Any,
    *,
    artifacts_root: Path,
    manifest: dict[str, Any],
    output_path: Path,
    row: dict[str, Any],
) -> str:
    if str(row.get("status", "succeeded")) != "succeeded":
        return "skipped"
    paper_id = _coerce_positive_int(row.get("paper_id"), field_name="paper_id")
    pdf_hash = str(row.get("pdf_hash") or "")
    if not pdf_hash:
        raise OffloadError("missing pdf_hash")
    pages_text = row.get("pages_text")
    if not isinstance(pages_text, list) or not all(
        isinstance(page, str) for page in pages_text
    ):
        raise OffloadError("pages_text must be a list of strings")
    page_count = _coerce_positive_int(
        row.get("page_count") or len(pages_text),
        field_name="page_count",
    )
    paper = conn.execute(
        "SELECT id, pdf_hash FROM papers WHERE id = ?",
        (paper_id,),
    ).fetchone()
    if paper is None:
        raise OffloadError(f"paper not found: {paper_id}")
    local_pdf_hash = str(paper["pdf_hash"] or "")
    if local_pdf_hash and local_pdf_hash != pdf_hash:
        raise OffloadError(
            f"pdf_hash mismatch for paper {paper_id}: local paper hash differs"
        )
    existing = conn.execute(
        """
        SELECT path, metadata
        FROM paper_artifacts
        WHERE paper_id = ? AND artifact_type = 'paperindex_structure'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (paper_id,),
    ).fetchone()
    if existing is not None:
        if _existing_structure_matches(
            existing, pdf_hash=pdf_hash, pages_text=pages_text
        ):
            return "skipped"
        return "skipped"

    structure_path = artifacts_root / f"paper_{paper_id}" / "structure.json"
    structure_path.parent.mkdir(parents=True, exist_ok=True)
    parser = str(row.get("parser") or row.get("extractor") or "remote")
    structure_payload = {
        "doc_name": str(row.get("doc_name") or f"paper_{paper_id}"),
        "pdf_hash": pdf_hash,
        "page_count": page_count,
        "structure": row.get("structure")
        if isinstance(row.get("structure"), list)
        else [],
        "raw": {
            "parser": parser,
            "pages_text": pages_text,
            "source": REMOTE_OFFLOAD_ORIGIN,
        },
    }
    _write_json(structure_path, structure_payload)
    metadata = {
        "source": REMOTE_OFFLOAD_ORIGIN,
        "task_id": manifest["task_id"],
        "task_type": manifest["task_type"],
        "parser": parser,
        "pdf_hash": pdf_hash,
        "page_count": page_count,
        "output_hash": _sha256_file(output_path),
        "imported_at": utc_iso_timestamp(),
        "server_hostname": manifest["server_hostname"],
        "git_commit": manifest["git_commit"],
        "trusted_remote_metadata": False,
    }
    conn.execute(
        """
        INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata)
        VALUES (?, 'paperindex_structure', ?, ?)
        """,
        (paper_id, str(structure_path), json.dumps(metadata, sort_keys=True)),
    )
    return "imported"


def _paper_text_extraction_builder(
    *,
    topic: str,
    inputs_dir: Path,
    db_path: Path,
    library_snapshot: dict[str, Any] | None = None,
    include_pdf_files: bool = False,
    max_pdf_bytes: int = PAPER_TEXT_PDF_MAX_BYTES,
    model_policy: dict[str, Any] | None = None,
) -> list[str]:
    papers = _topic_papers(db_path, topic)
    if model_policy is not None:
        raise OffloadError(
            "model_policy is not supported for paper_text_extraction_batch"
        )
    if library_snapshot is not None:
        raise OffloadError(
            "paper_text_extraction_batch does not accept library_snapshot"
        )
    max_pdf_size = _coerce_positive_int(max_pdf_bytes, field_name="max_pdf_bytes")
    payload = {
        "schema_version": "paper_text_extraction_batch.inputs.v1",
        "topic": topic,
        "papers": _paper_text_rows_for_pack(
            db_path,
            papers,
            inputs_dir=inputs_dir,
            include_pdf_files=include_pdf_files,
            max_pdf_bytes=max_pdf_size,
        ),
        "note": (
            "Minimal paper metadata plus explicitly packaged PaperIndex text "
            "when already present. PDF binaries are copied only when explicitly "
            "requested with a local packaging policy; the main RH database and "
            "local paths are intentionally not copied."
        ),
    }
    _write_json(inputs_dir / "paper_text_extraction_inputs.json", payload)
    return ["outputs/paper_text_extraction_results.jsonl", "outputs/summary.json"]


def _wiki_embedding_builder(
    *,
    topic: str,
    inputs_dir: Path,
    db_path: Path,
    library_snapshot: dict[str, Any] | None = None,
    include_pdf_files: bool = False,
    max_pdf_bytes: int = PAPER_TEXT_PDF_MAX_BYTES,
    model_policy: dict[str, Any] | None = None,
) -> list[str]:
    if include_pdf_files:
        raise OffloadError(
            "include_pdf_files is only supported for paper_text_extraction_batch"
        )
    payload = {
        "schema_version": "wiki_embedding_batch.inputs.v1",
        "topic": topic,
        "artifacts": _topic_artifacts_for_embedding_pack(
            db_path,
            topic,
            artifact_types=("wiki_context_pack", "topic_knowledge_snapshot"),
        ),
        "note": (
            "Safe artifact text features only; no full RH database, artifact "
            "paths, or arbitrary payload fields are copied."
        ),
    }
    if model_policy is not None:
        payload["model_policy"] = model_policy
    if library_snapshot is not None:
        payload["external_corpus_snapshot"] = library_snapshot
    _write_json(inputs_dir / "wiki_embedding_inputs.json", payload)
    return ["outputs/wiki_embeddings.jsonl", "outputs/summary.json"]


def _retrieval_eval_builder(
    *,
    topic: str,
    inputs_dir: Path,
    db_path: Path,
    library_snapshot: dict[str, Any] | None = None,
    include_pdf_files: bool = False,
    max_pdf_bytes: int = PAPER_TEXT_PDF_MAX_BYTES,
    model_policy: dict[str, Any] | None = None,
) -> list[str]:
    if include_pdf_files:
        raise OffloadError(
            "include_pdf_files is only supported for paper_text_extraction_batch"
        )
    papers = _topic_papers(db_path, topic)
    payload = {
        "schema_version": "retrieval_eval_sweep.inputs.v1",
        "topic": topic,
        "paper_count": len(papers),
        "papers": _redacted_papers_for_pack(papers),
    }
    if library_snapshot is not None:
        payload["external_corpus_snapshot"] = library_snapshot
    if model_policy is not None:
        payload["model_policy"] = model_policy
    _write_json(inputs_dir / "retrieval_eval_inputs.json", payload)
    return ["outputs/retrieval_eval_report.json", "outputs/predictions.jsonl"]


def _researchflowbench_builder(
    *,
    topic: str,
    inputs_dir: Path,
    db_path: Path,
    library_snapshot: dict[str, Any] | None = None,
    include_pdf_files: bool = False,
    max_pdf_bytes: int = PAPER_TEXT_PDF_MAX_BYTES,
    model_policy: dict[str, Any] | None = None,
) -> list[str]:
    if model_policy is not None:
        raise OffloadError(
            "model_policy is not supported for researchflowbench_batch_eval"
        )
    if include_pdf_files:
        raise OffloadError(
            "include_pdf_files is only supported for paper_text_extraction_batch"
        )
    if library_snapshot is not None:
        raise OffloadError(
            "researchflowbench_batch_eval does not accept library_snapshot"
        )
    payload = {
        "schema_version": "researchflowbench_batch_eval.inputs.v1",
        "topic": topic,
        "warning": "First-version pack contains topic metadata only; benchmark gold stays local unless explicitly packaged later.",
        "topic_record": _topic_record(db_path, topic),
    }
    _write_json(inputs_dir / "researchflowbench_inputs.json", payload)
    return ["outputs/predictions.json", "outputs/score_report.json"]


_PACK_BUILDERS: dict[str, Callable[..., list[str]]] = {
    "paper_text_extraction_batch": _paper_text_extraction_builder,
    "wiki_embedding_batch": _wiki_embedding_builder,
    "retrieval_eval_sweep": _retrieval_eval_builder,
    "researchflowbench_batch_eval": _researchflowbench_builder,
}


def _resource_hint(task_type: str) -> dict[str, object]:
    hints: dict[str, dict[str, object]] = {
        "paper_text_extraction_batch": {"cpu": 8, "memory_gb": 32, "gpu": False},
        "wiki_embedding_batch": {"cpu": 8, "memory_gb": 48, "gpu": True},
        "retrieval_eval_sweep": {"cpu": 16, "memory_gb": 64, "gpu": False},
        "researchflowbench_batch_eval": {"cpu": 16, "memory_gb": 64, "gpu": True},
    }
    return dict(hints[task_type])


def _timeout_seconds(task_type: str) -> int:
    timeouts = {
        "paper_text_extraction_batch": 7200,
        "wiki_embedding_batch": 14400,
        "retrieval_eval_sweep": 14400,
        "researchflowbench_batch_eval": 28800,
    }
    return timeouts[task_type]


def _topic_papers(db_path: Path, topic: str) -> list[dict[str, object]]:
    conn = _connect_readonly(db_path)
    try:
        topic_id = _topic_id_from_conn(conn, topic)
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.authors, p.venue, p.year, p.arxiv_id, p.doi,
                   p.s2_id, p.status, p.pdf_path, p.pdf_hash, pt.relevance
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
            ORDER BY p.id
            """,
            (topic_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _topic_artifacts(
    db_path: Path,
    topic: str,
    *,
    artifact_types: Iterable[str],
) -> list[dict[str, object]]:
    conn = _connect_readonly(db_path)
    try:
        topic_id = _topic_id_from_conn(conn, topic)
        artifact_type_list = tuple(artifact_types)
        placeholders = ",".join("?" for _ in artifact_type_list)
        rows = conn.execute(
            f"""
            SELECT id, stage, artifact_type, title, path, payload_json, metadata_json
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type IN ({placeholders})
            ORDER BY created_at DESC, id DESC
            LIMIT 50
            """,
            [topic_id, *artifact_type_list],
        ).fetchall()
        return [_artifact_pack_row(row) for row in rows]
    finally:
        conn.close()


def _topic_artifacts_for_embedding_pack(
    db_path: Path,
    topic: str,
    *,
    artifact_types: Iterable[str],
) -> list[dict[str, object]]:
    conn = _connect_readonly(db_path)
    try:
        topic_id = _topic_id_from_conn(conn, topic)
        artifact_type_list = tuple(artifact_types)
        placeholders = ",".join("?" for _ in artifact_type_list)
        rows = conn.execute(
            f"""
            SELECT id, stage, artifact_type, title, path, payload_json, metadata_json
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type IN ({placeholders})
            ORDER BY created_at DESC, id DESC
            LIMIT 50
            """,
            [topic_id, *artifact_type_list],
        ).fetchall()
        return [_embedding_artifact_pack_row(row) for row in rows]
    finally:
        conn.close()


def _embedding_artifact_pack_row(row: Any) -> dict[str, object]:
    packed = _artifact_pack_row(row)
    payload_text = str(row["payload_json"] or "")
    embedding_text = _safe_embedding_text_from_payload(payload_text)
    if embedding_text:
        packed.update(
            {
                "embedding_text": embedding_text,
                "embedding_text_sha256": _hash_text(embedding_text),
                "embedding_text_origin": "project_artifact_payload",
            }
        )
    return packed


def _safe_embedding_text_from_payload(payload_text: str) -> str:
    if not payload_text:
        return ""
    if len(payload_text.encode("utf-8")) > WIKI_EMBEDDING_TEXT_MAX_BYTES:
        return ""
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return ""
    chunks = _embedding_text_chunks(payload, key_path=())
    cleaned = [_clean_embedding_text_chunk(chunk) for chunk in chunks]
    nonempty = [chunk for chunk in cleaned if chunk]
    text = "\n\n".join(nonempty)
    if len(text.encode("utf-8")) > WIKI_EMBEDDING_TEXT_MAX_BYTES:
        return ""
    return text


def _embedding_text_chunks(value: Any, *, key_path: tuple[str, ...]) -> list[str]:
    if isinstance(value, str):
        if not key_path or _embedding_text_key_allowed(key_path[-1]):
            return [value]
        return []
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value[:100]:
            chunks.extend(_embedding_text_chunks(item, key_path=key_path))
        return chunks
    if isinstance(value, dict):
        chunks = []
        for key, item in value.items():
            key_text = str(key)
            next_path = (*key_path, key_text)
            if _embedding_key_blocked(key_text):
                continue
            if isinstance(item, str) and not _embedding_text_key_allowed(key_text):
                continue
            chunks.extend(_embedding_text_chunks(item, key_path=next_path))
        return chunks
    return []


def _embedding_text_key_allowed(key: str) -> bool:
    normalized = key.lower()
    allowed = {
        "action_name",
        "claim",
        "claims",
        "content",
        "covered",
        "description",
        "excerpt",
        "finding",
        "findings",
        "gap",
        "gaps",
        "label",
        "matched_terms",
        "method",
        "methods",
        "next_actions",
        "page_type",
        "query",
        "research_state",
        "selection_reason",
        "status",
        "summary",
        "text",
        "title",
        "weak_spots",
    }
    return normalized in allowed


def _embedding_key_blocked(key: str) -> bool:
    normalized = key.lower()
    blocked_fragments = (
        "path",
        "url",
        "uri",
        "href",
        "file",
        "secret",
        "token",
        "credential",
        "password",
        "key",
    )
    return any(fragment in normalized for fragment in blocked_fragments)


def _clean_embedding_text_chunk(value: str) -> str:
    cleaned = " ".join(str(value).replace("\x00", " ").split())
    if not cleaned or len(cleaned) > 2000:
        return ""
    lowered = cleaned.lower()
    if "://" in cleaned or lowered.startswith(("file:", "ssh:", "s3:")):
        return ""
    if re.search(r"(^|\\s)(/|~/?|[a-zA-Z]:\\\\)", cleaned):
        return ""
    if re.search(r"\\.(json|jsonl|pdf|db|sqlite|txt|md|csv|tsv)(\\s|$)", lowered):
        return ""
    return cleaned


def _paper_text_rows_for_pack(
    db_path: Path,
    papers: list[dict[str, object]],
    *,
    inputs_dir: Path,
    include_pdf_files: bool,
    max_pdf_bytes: int,
) -> list[dict[str, object]]:
    rows = _redacted_papers_for_pack(papers)
    source_texts = _explicit_paper_text_sources(db_path, papers)
    pdf_files = (
        _explicit_pdf_files_for_pack(
            db_path,
            papers,
            inputs_dir=inputs_dir,
            max_pdf_bytes=max_pdf_bytes,
        )
        if include_pdf_files
        else {}
    )
    packed: list[dict[str, object]] = []
    for row in rows:
        paper_id = row.get("id")
        enriched = dict(row)
        if isinstance(paper_id, int) and paper_id in source_texts:
            enriched.update(source_texts[paper_id])
        if isinstance(paper_id, int) and paper_id in pdf_files:
            enriched.update(pdf_files[paper_id])
        packed.append(enriched)
    return packed


def _explicit_pdf_files_for_pack(
    db_path: Path,
    papers: list[dict[str, object]],
    *,
    inputs_dir: Path,
    max_pdf_bytes: int,
) -> dict[int, dict[str, object]]:
    db_root = db_path.resolve().parent
    pdf_dir = inputs_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    packed: dict[int, dict[str, object]] = {}
    for paper in papers:
        paper_id = paper.get("id")
        if not isinstance(paper_id, int):
            continue
        path = _safe_local_pdf_path(str(paper.get("pdf_path") or ""), db_root)
        size = path.stat().st_size
        if size > max_pdf_bytes:
            raise OffloadError("pdf_file_too_large")
        digest = _sha256_file(path)
        pdf_hash = str(paper.get("pdf_hash") or "")
        if pdf_hash and pdf_hash != digest:
            raise OffloadError("pdf_hash_mismatch")
        relative_pdf = Path("pdfs") / f"paper_{paper_id}_{digest[:16]}.pdf"
        target = inputs_dir / relative_pdf
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or _sha256_file(target) != digest:
            shutil.copy2(path, target)
        packed[paper_id] = {
            "pdf_file": relative_pdf.as_posix(),
            "pdf_file_sha256": digest,
            "pdf_file_size_bytes": size,
            "pdf_file_origin": "explicit_pdf_pack",
        }
    return packed


def _safe_local_pdf_path(raw_path: str, db_root: Path) -> Path:
    if not raw_path or "\x00" in raw_path:
        raise OffloadError("missing_pdf_path")
    path = Path(raw_path)
    if path.suffix.lower() != ".pdf":
        raise OffloadError("unsupported_pdf_file_type")
    candidates = [path] if path.is_absolute() else [db_root / path, path]
    saw_existing_outside = False
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        try:
            resolved.relative_to(db_root)
        except ValueError:
            saw_existing_outside = True
            continue
        if _has_symlink_component(candidate) or not resolved.is_file():
            raise OffloadError("unsafe_pdf_path")
        if resolved.suffix.lower() != ".pdf":
            raise OffloadError("unsupported_pdf_file_type")
        try:
            with resolved.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise OffloadError("unsupported_pdf_file_type")
        except OSError as exc:
            raise OffloadError("missing_pdf_path") from exc
        return resolved
    if saw_existing_outside:
        raise OffloadError("outside_db_root")
    raise OffloadError("missing_pdf_path")


def _explicit_paper_text_sources(
    db_path: Path,
    papers: list[dict[str, object]],
) -> dict[int, dict[str, object]]:
    paper_ids = [
        int(paper["id"])
        for paper in papers
        if isinstance(paper.get("id"), int) and int(paper["id"]) > 0
    ]
    if not paper_ids:
        return {}
    conn = _connect_readonly(db_path)
    try:
        rows = _latest_paperindex_rows(conn, paper_ids)
    finally:
        conn.close()
    db_root = db_path.resolve().parent
    sources: dict[int, dict[str, object]] = {}
    for paper in papers:
        paper_id = paper.get("id")
        if not isinstance(paper_id, int):
            continue
        artifact = rows.get(paper_id)
        if artifact is None:
            continue
        sources[paper_id] = _paperindex_text_source_from_artifact(
            db_root=db_root,
            artifact=artifact,
            paper_pdf_hash=str(paper.get("pdf_hash") or ""),
        )
    return sources


def _latest_paperindex_rows(conn: Any, paper_ids: list[int]) -> dict[int, Any]:
    placeholders = ",".join("?" for _ in paper_ids)
    rows = conn.execute(
        f"""
        SELECT paper_id, path, metadata
        FROM paper_artifacts
        WHERE paper_id IN ({placeholders})
          AND artifact_type = 'paperindex_structure'
        ORDER BY paper_id ASC, created_at DESC, id DESC
        """,
        paper_ids,
    ).fetchall()
    latest: dict[int, Any] = {}
    for row in rows:
        paper_id = int(row["paper_id"])
        latest.setdefault(paper_id, row)
    return latest


def _paperindex_text_source_from_artifact(
    *,
    db_root: Path,
    artifact: Any,
    paper_pdf_hash: str,
) -> dict[str, object]:
    try:
        structure_path = _safe_local_artifact_path(str(artifact["path"]), db_root)
        payload = _read_small_json(
            structure_path,
            max_bytes=PAPER_TEXT_STRUCTURE_MAX_BYTES,
        )
        source = _paperindex_text_source_from_payload(
            payload,
            paper_pdf_hash=paper_pdf_hash,
        )
    except OffloadError as exc:
        return {"source_text_warning": _paper_text_warning_code(str(exc))}
    source["source_text_origin"] = "paperindex_structure"
    return source


def _safe_local_artifact_path(raw_path: str, db_root: Path) -> Path:
    if not raw_path or "\x00" in raw_path:
        raise OffloadError("missing_structure_path")
    path = Path(raw_path)
    candidates = [path] if path.is_absolute() else [db_root / path, path]
    saw_existing_outside = False
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        try:
            resolved.relative_to(db_root)
        except ValueError:
            saw_existing_outside = True
            continue
        if _has_symlink_component(candidate) or not resolved.is_file():
            raise OffloadError("unsafe_structure_path")
        return resolved
    if saw_existing_outside:
        raise OffloadError("outside_db_root")
    raise OffloadError("missing_structure_path")


def _has_symlink_component(path: Path) -> bool:
    candidates = (path, *path.parents)
    return any(
        candidate.exists() and candidate.is_symlink() for candidate in candidates
    )


def _read_small_json(path: Path, *, max_bytes: int) -> dict[str, Any]:
    if path.is_symlink():
        raise OffloadError("unsafe_structure_path")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise OffloadError("missing_structure_path") from exc
    if size > max_bytes:
        raise OffloadError("structure_too_large")
    return _read_json(path)


def _paperindex_text_source_from_payload(
    payload: dict[str, Any],
    *,
    paper_pdf_hash: str,
) -> dict[str, object]:
    pdf_hash = str(payload.get("pdf_hash") or "")
    if paper_pdf_hash and pdf_hash and pdf_hash != paper_pdf_hash:
        raise OffloadError("pdf_hash_mismatch")
    raw = payload.get("raw")
    if not isinstance(raw, dict):
        raise OffloadError("missing_raw_text")
    pages_text = raw.get("pages_text")
    if not isinstance(pages_text, list) or not pages_text:
        raise OffloadError("missing_raw_text")
    if len(pages_text) > PAPER_TEXT_SOURCE_MAX_PAGES:
        raise OffloadError("source_text_too_many_pages")
    if not all(isinstance(page, str) for page in pages_text):
        raise OffloadError("invalid_raw_text")
    source_text = "\n\n".join(page.strip() for page in pages_text if page.strip())
    if not source_text:
        raise OffloadError("missing_raw_text")
    if len(source_text.encode("utf-8")) > PAPER_TEXT_SOURCE_MAX_BYTES:
        raise OffloadError("source_text_too_large")
    return {
        "source_text": source_text,
        "source_text_sha256": _hash_text(source_text),
        "source_text_page_count": len(pages_text),
    }


def _paper_text_warning_code(value: str) -> str:
    if not value:
        return "unavailable"
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")[:80] or "unavailable"


def _topic_record(db_path: Path, topic: str) -> dict[str, object]:
    conn = _connect_readonly(db_path)
    try:
        topic_id = _topic_id_from_conn(conn, topic)
        row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return dict(row) if row is not None else {}
    finally:
        conn.close()


def _load_remote_library_snapshot(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = _read_json(Path(path))
    validate_remote_library_snapshot(payload)
    return payload


def _artifact_pack_row(row: Any) -> dict[str, object]:
    payload_text = str(row["payload_json"] or "")
    metadata_text = str(row["metadata_json"] or "")
    return {
        "id": row["id"],
        "stage": row["stage"],
        "artifact_type": row["artifact_type"],
        "title": row["title"],
        "payload_sha256": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
        "metadata_sha256": hashlib.sha256(metadata_text.encode("utf-8")).hexdigest(),
    }


def _redacted_papers_for_pack(
    papers: list[dict[str, object]],
) -> list[dict[str, object]]:
    safe_keys = {
        "id",
        "title",
        "authors",
        "venue",
        "year",
        "arxiv_id",
        "doi",
        "s2_id",
        "status",
        "pdf_hash",
        "relevance",
    }
    return [
        {key: value for key, value in paper.items() if key in safe_keys}
        for paper in papers
    ]


def _topic_id_or_error(db: Database, topic: str) -> int:
    conn = db.connect()
    try:
        return _topic_id_from_conn(conn, topic)
    finally:
        conn.close()


def _topic_id_from_conn(conn: Any, topic: str) -> int:
    if topic.isdigit():
        row = conn.execute(
            "SELECT id FROM topics WHERE id = ?", (int(topic),)
        ).fetchone()
    else:
        row = conn.execute("SELECT id FROM topics WHERE name = ?", (topic,)).fetchone()
    if row is None:
        raise OffloadError(f"topic not found: {topic}")
    return int(row["id"])


def _connect_readonly(db_path: Path) -> Any:
    import sqlite3

    if not db_path.exists():
        raise OffloadError(f"database does not exist: {db_path}")
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink():
        raise OffloadError(f"unsafe symlink path: {path}")
    if not path.is_file():
        raise OffloadError(f"missing JSONL file: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OffloadError(f"invalid JSONL row {line_number}: {path}") from exc
        if not isinstance(payload, dict):
            raise OffloadError(f"JSONL row {line_number} must contain an object")
        rows.append(payload)
    return rows


def _coerce_positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise OffloadError(f"{field_name} must be a positive integer")
    try:
        integer = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise OffloadError(f"{field_name} must be a positive integer") from exc
    if integer <= 0:
        raise OffloadError(f"{field_name} must be a positive integer")
    return integer


def _coerce_nonnegative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise OffloadError(f"{field_name} must be a nonnegative integer")
    try:
        integer = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise OffloadError(f"{field_name} must be a nonnegative integer") from exc
    if integer < 0:
        raise OffloadError(f"{field_name} must be a nonnegative integer")
    return integer


def _existing_structure_matches(
    existing: Any,
    *,
    pdf_hash: str,
    pages_text: list[str],
) -> bool:
    metadata = _json_object_from_text(existing["metadata"] or "{}")
    if metadata.get("pdf_hash") == pdf_hash:
        return True
    path = Path(existing["path"] or "")
    if path.is_file() and not path.is_symlink():
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("pdf_hash") != pdf_hash:
            return False
        existing_pages = payload.get("raw", {}).get("pages_text", [])
        return existing_pages == pages_text
    return False


def _json_object_from_text(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _validate_hash_map(value: object, *, field_name: str) -> None:
    if not isinstance(value, dict):
        raise OffloadError(f"{field_name} must be an object")
    for path, digest in value.items():
        validate_relative_path(str(path))
        if not isinstance(digest, str) or len(digest) != 64:
            raise OffloadError(f"{field_name} has invalid sha256 for {path}")


def _validate_hex_digest(value: object, *, field_name: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise OffloadError(f"{field_name} must be a sha256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise OffloadError(f"{field_name} must be a sha256 hex digest") from exc


def _validate_extension_counts(value: object) -> None:
    if not isinstance(value, dict):
        raise OffloadError("extension_counts must be an object")
    if len(value) > len(REMOTE_LIBRARY_ALLOWED_EXTENSIONS):
        raise OffloadError("extension_counts contains too many extensions")
    for extension, count in value.items():
        if extension not in REMOTE_LIBRARY_ALLOWED_EXTENSIONS:
            raise OffloadError(f"unsupported extension in snapshot: {extension}")
        _coerce_nonnegative_int(count, field_name=f"extension_counts[{extension}]")


def _validate_remote_library_sample(sample: object) -> None:
    if not isinstance(sample, dict):
        raise OffloadError("remote library sample must be an object")
    extra = sorted(set(sample) - REMOTE_LIBRARY_ALLOWED_SAMPLE_KEYS)
    if extra:
        raise OffloadError(
            f"remote library sample fields not allowed: {', '.join(extra)}"
        )
    missing = sorted(REMOTE_LIBRARY_REQUIRED_SAMPLE_KEYS - set(sample))
    if missing:
        raise OffloadError(
            f"remote library sample missing fields: {', '.join(missing)}"
        )
    basename = sample["basename"]
    _validate_short_string(basename, field_name="basename", max_len=255)
    if str(basename) in {".", ".."} or "/" in str(basename) or "\\" in str(basename):
        raise OffloadError("basename must not contain path separators")
    extension = sample["extension"]
    if extension not in REMOTE_LIBRARY_ALLOWED_EXTENSIONS:
        raise OffloadError(f"unsupported sample extension: {extension}")
    _coerce_nonnegative_int(sample["size_bytes"], field_name="size_bytes")
    _validate_hex_digest(sample["relative_path_hash"], field_name="relative_path_hash")
    _coerce_nonnegative_int(sample["path_depth"], field_name="path_depth")
    _validate_string_list(
        sample["matched_terms"],
        field_name="matched_terms",
        max_len=128,
    )
    if "token_counts" in sample:
        _validate_token_count_map(
            sample["token_counts"],
            field_name="token_counts",
            max_items=500,
        )
    if "token_count" in sample:
        _coerce_nonnegative_int(sample["token_count"], field_name="token_count")


def _validate_token_count_map(
    value: object, *, field_name: str, max_items: int
) -> None:
    if not isinstance(value, dict):
        raise OffloadError(f"{field_name} must be an object")
    if len(value) > max_items:
        raise OffloadError(f"{field_name} contains too many tokens")
    for token, count in value.items():
        if not isinstance(token, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{1,63}", token
        ):
            raise OffloadError(f"{field_name} contains unsafe token")
        _coerce_nonnegative_int(count, field_name=f"{field_name}[{token}]")


def _validate_path_list(value: object, *, field_name: str) -> None:
    if not isinstance(value, list):
        raise OffloadError(f"{field_name} must be a list")
    for item in value:
        validate_relative_path(str(item))


def _validate_short_string(value: object, *, field_name: str, max_len: int) -> None:
    if not isinstance(value, str) or len(value) > max_len or "\x00" in value:
        raise OffloadError(f"{field_name} must be a string up to {max_len} chars")


def _validate_string_list(value: object, *, field_name: str, max_len: int) -> None:
    if not isinstance(value, list):
        raise OffloadError(f"{field_name} must be a list")
    for item in value:
        _validate_short_string(item, field_name=field_name, max_len=max_len)


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise OffloadError(f"unsafe symlink path: {path}")
    if not path.is_file():
        raise OffloadError(f"missing JSON file: {path}")
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise OffloadError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise OffloadError(f"JSON file must contain an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _expected_output_keys(task_manifest: dict[str, Any]) -> set[str]:
    expected: set[str] = set()
    for item in task_manifest.get("expected_outputs", []):
        rel = validate_relative_path(str(item))
        if not rel.startswith("outputs/"):
            raise OffloadError(f"expected output must be under outputs/: {rel}")
        expected.add(rel.removeprefix("outputs/"))
    return expected


def _write_fallback_result_manifest(
    result_dir: Path,
    *,
    task_manifest: dict[str, Any],
    exit_code: int,
    started_at: str,
) -> None:
    status = "partial" if exit_code == 0 else "failed"
    payload = {
        "task_id": task_manifest["task_id"],
        "task_type": task_manifest["task_type"],
        "status": status,
        "started_at": started_at,
        "finished_at": utc_iso_timestamp(),
        "exit_code": exit_code,
        "output_hashes": compute_file_hashes(result_dir / "outputs"),
        "warnings": ["runner did not write result_manifest.json"],
        "server_hostname": platform.node() or "localhost",
        "git_commit": os.environ.get("GIT_COMMIT", "unknown"),
    }
    _write_json(result_dir / RESULT_MANIFEST, payload)


def _hash_json(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_snapshot_text(value: str, *, max_len: int) -> str:
    cleaned = " ".join(str(value).replace("\x00", " ").split())
    return cleaned[:max_len]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_tree_idempotent(source: Path, destination: Path) -> None:
    if not source.exists():
        raise OffloadError(f"source does not exist: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise OffloadError(f"unsafe symlink path: {path}")
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        validate_relative_path(rel.as_posix())
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and _sha256_file(target) == _sha256_file(path):
            continue
        shutil.copy2(path, target)


def _local_remote_status(remote_root: Path) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    total_size = 0
    now = datetime.now(timezone.utc)
    for section in REMOTE_OFFLOAD_SECTIONS:
        section_path = remote_root / section
        items = _remote_section_items(
            remote_root=remote_root,
            section=section,
            now=now,
        )
        section_size = sum(int(item["size_bytes"]) for item in items)
        total_size += section_size
        sections[section] = {
            "exists": section_path.is_dir(),
            "count": len(items),
            "size_bytes": section_size,
            "items": items,
        }
    return {
        "schema_version": REMOTE_STATUS_SCHEMA_VERSION,
        "remote_root": remote_root.as_posix(),
        "read_only": True,
        "generated_at": utc_iso_timestamp(),
        "total_size_bytes": total_size,
        "sections": sections,
    }


def _remote_section_items(
    *,
    remote_root: Path,
    section: str,
    now: datetime,
) -> list[dict[str, Any]]:
    section_path = remote_root / section
    if not section_path.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(section_path.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            items.append(
                {
                    "task_id": path.name[:255],
                    "path": f"{section}/{path.name}",
                    "kind": "symlink",
                    "status": "unsafe_symlink",
                    "size_bytes": 0,
                    "age_seconds": 0,
                    "warning": "symlink_not_followed",
                }
            )
            continue
        if not path.is_dir():
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        items.append(
            {
                "task_id": path.name[:255],
                "path": f"{section}/{path.name}",
                "kind": "directory",
                "status": _remote_item_status(path, section=section),
                "size_bytes": _directory_size(path),
                "age_seconds": max(0, int((now - modified_at).total_seconds())),
                "modified_at": modified_at.replace(microsecond=0).isoformat(),
            }
        )
    return items


def _directory_size(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_symlink():
            continue
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                continue
    return total


def _remote_item_status(path: Path, *, section: str) -> str:
    if section == "results":
        manifest_path = path / RESULT_MANIFEST
        if manifest_path.is_file():
            try:
                manifest = _read_json(manifest_path)
            except OffloadError:
                return "invalid_manifest"
            status = manifest.get("status")
            return str(status) if status in OFFLOAD_STATUSES else "invalid_manifest"
        return "missing_result_manifest"
    if section == "incoming":
        manifest_path = path / TASK_MANIFEST
        if manifest_path.is_file():
            try:
                manifest = _read_json(manifest_path)
            except OffloadError:
                return "invalid_manifest"
            status = manifest.get("status")
            return str(status) if status in OFFLOAD_STATUSES else "invalid_manifest"
        return "missing_task_manifest"
    if section == "runs":
        return "run_dir"
    return "cache_entry"


def _local_remote_cleanup(
    remote_root: Path,
    *,
    task_ids: set[str],
    sections: tuple[str, ...],
    older_than_days: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    candidates = _cleanup_candidates(
        remote_root,
        task_ids=task_ids,
        sections=sections,
        older_than_days=older_than_days,
    )
    deleted: list[dict[str, Any]] = []
    if not dry_run:
        for candidate in candidates:
            path = _cleanup_candidate_path(remote_root, candidate)
            if path.exists():
                shutil.rmtree(path)
            deleted.append(candidate)
    return {
        "schema_version": REMOTE_CLEANUP_SCHEMA_VERSION,
        "remote_root": remote_root.as_posix(),
        "dry_run": dry_run,
        "generated_at": utc_iso_timestamp(),
        "filters": {
            "task_ids": sorted(task_ids),
            "sections": list(sections),
            "older_than_days": older_than_days,
        },
        "candidate_count": len(candidates),
        "deleted_count": len(deleted),
        "candidates": candidates,
        "deleted": deleted,
    }


def _cleanup_candidates(
    remote_root: Path,
    *,
    task_ids: set[str],
    sections: tuple[str, ...],
    older_than_days: int | None,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    candidates: list[dict[str, Any]] = []
    for section in sections:
        section_path = remote_root / section
        if not section_path.is_dir():
            continue
        for path in sorted(section_path.iterdir(), key=lambda item: item.name):
            if path.is_symlink() or not path.is_dir():
                continue
            if task_ids and path.name not in task_ids:
                continue
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            age_seconds = max(0, int((now - modified_at).total_seconds()))
            if older_than_days is not None and age_seconds < older_than_days * 86400:
                continue
            candidate = {
                "section": section,
                "task_id": path.name,
                "path": f"{section}/{path.name}",
                "size_bytes": _directory_size(path),
                "age_seconds": age_seconds,
            }
            _cleanup_candidate_path(remote_root, candidate)
            candidates.append(candidate)
    return candidates


def _cleanup_candidate_path(remote_root: Path, candidate: dict[str, Any]) -> Path:
    section = str(candidate.get("section") or "")
    if section not in REMOTE_OFFLOAD_SECTIONS:
        raise OffloadError(f"unsafe cleanup section: {section!r}")
    task_id = str(candidate.get("task_id") or "")
    if section != "cache":
        validate_task_id(task_id)
    elif not task_id or task_id in {".", ".."} or "/" in task_id or "\\" in task_id:
        raise OffloadError(f"unsafe cache cleanup id: {task_id!r}")
    path = remote_root / section / task_id
    try:
        path.resolve().relative_to(remote_root.resolve())
    except ValueError as exc:
        raise OffloadError("cleanup candidate escapes remote_root") from exc
    return path


def _normalize_cleanup_task_ids(task_ids: Sequence[str] | None) -> set[str]:
    normalized: set[str] = set()
    for task_id in task_ids or []:
        validate_task_id(str(task_id))
        normalized.add(str(task_id))
    return normalized


def _normalize_cleanup_sections(sections: Sequence[str] | None) -> tuple[str, ...]:
    raw = tuple(sections or ("incoming", "runs", "results"))
    normalized: list[str] = []
    for section in raw:
        text = str(section)
        if text not in REMOTE_OFFLOAD_SECTIONS:
            raise OffloadError(f"unsupported cleanup section: {text}")
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


def _validate_remote_status_payload(
    payload: dict[str, Any],
    *,
    remote_root: Path,
) -> dict[str, Any]:
    if payload.get("schema_version") != REMOTE_STATUS_SCHEMA_VERSION:
        raise OffloadError("unsupported remote status schema")
    if payload.get("remote_root") != remote_root.as_posix():
        raise OffloadError("remote status root mismatch")
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        raise OffloadError("remote status sections must be an object")
    return payload


def _validate_remote_cleanup_payload(
    payload: dict[str, Any],
    *,
    remote_root: Path,
) -> dict[str, Any]:
    if payload.get("schema_version") != REMOTE_CLEANUP_SCHEMA_VERSION:
        raise OffloadError("unsupported remote cleanup schema")
    if payload.get("remote_root") != remote_root.as_posix():
        raise OffloadError("remote cleanup root mismatch")
    if not isinstance(payload.get("candidates"), list):
        raise OffloadError("remote cleanup candidates must be a list")
    return payload


def _remote_status_script(remote_root: Path) -> str:
    return _remote_management_script(
        remote_root,
        mode="status",
        task_ids=[],
        sections=list(REMOTE_OFFLOAD_SECTIONS),
        older_than_days=None,
        dry_run=True,
    )


def _remote_cleanup_script(
    remote_root: Path,
    *,
    task_ids: set[str],
    sections: tuple[str, ...],
    older_than_days: int | None,
    dry_run: bool,
) -> str:
    return _remote_management_script(
        remote_root,
        mode="cleanup",
        task_ids=sorted(task_ids),
        sections=list(sections),
        older_than_days=older_than_days,
        dry_run=dry_run,
    )


def _remote_management_script(
    remote_root: Path,
    *,
    mode: str,
    task_ids: list[str],
    sections: list[str],
    older_than_days: int | None,
    dry_run: bool,
) -> str:
    payload = {
        "allowed_sections": list(REMOTE_OFFLOAD_SECTIONS),
        "cleanup_schema": REMOTE_CLEANUP_SCHEMA_VERSION,
        "dry_run": dry_run,
        "mode": mode,
        "older_than_days": older_than_days,
        "remote_root": remote_root.as_posix(),
        "sections": sections,
        "status_schema": REMOTE_STATUS_SCHEMA_VERSION,
        "task_ids": task_ids,
    }
    return (
        "python3 - <<'PY'\n"
        "import datetime, json, os, shutil\n"
        f"cfg = json.loads({json.dumps(json.dumps(payload, sort_keys=True))})\n"
        "root = cfg['remote_root']\n"
        "now = datetime.datetime.now(datetime.timezone.utc)\n"
        "allowed = tuple(cfg['allowed_sections'])\n"
        "def safe_section(section):\n"
        "    if section not in allowed:\n"
        "        raise SystemExit(f'unsafe section: {section}')\n"
        "def safe_name(name):\n"
        "    if not name or name in {'.', '..'} or '/' in name or '\\\\' in name:\n"
        "        raise SystemExit(f'unsafe cleanup id: {name!r}')\n"
        "def dir_size(path):\n"
        "    total = 0\n"
        "    for cur, dirs, files in os.walk(path, followlinks=False):\n"
        "        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(cur, d))]\n"
        "        for name in files:\n"
        "            p = os.path.join(cur, name)\n"
        "            if os.path.islink(p):\n"
        "                continue\n"
        "            try:\n"
        "                total += os.path.getsize(p)\n"
        "            except OSError:\n"
        "                pass\n"
        "    return total\n"
        "def item_status(path, section):\n"
        "    manifest = 'result_manifest.json' if section == 'results' else 'task_manifest.json'\n"
        "    if section in {'incoming', 'results'}:\n"
        "        p = os.path.join(path, manifest)\n"
        "        if not os.path.isfile(p):\n"
        "            return 'missing_' + manifest\n"
        "        try:\n"
        "            value = json.load(open(p)).get('status')\n"
        "        except Exception:\n"
        "            return 'invalid_manifest'\n"
        "        return str(value)\n"
        "    return 'run_dir' if section == 'runs' else 'cache_entry'\n"
        "def section_items(section):\n"
        "    safe_section(section)\n"
        "    base = os.path.join(root, section)\n"
        "    if not os.path.isdir(base):\n"
        "        return []\n"
        "    rows = []\n"
        "    for name in sorted(os.listdir(base)):\n"
        "        p = os.path.join(base, name)\n"
        "        rel = f'{section}/{name}'\n"
        "        if os.path.islink(p):\n"
        "            rows.append({'task_id': name[:255], 'path': rel, 'kind': 'symlink', 'status': 'unsafe_symlink', 'size_bytes': 0, 'age_seconds': 0, 'warning': 'symlink_not_followed'})\n"
        "            continue\n"
        "        if not os.path.isdir(p):\n"
        "            continue\n"
        "        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(p), datetime.timezone.utc)\n"
        "        rows.append({'task_id': name[:255], 'path': rel, 'kind': 'directory', 'status': item_status(p, section), 'size_bytes': dir_size(p), 'age_seconds': max(0, int((now - mtime).total_seconds())), 'modified_at': mtime.replace(microsecond=0).isoformat()})\n"
        "    return rows\n"
        "if cfg['mode'] == 'status':\n"
        "    sections = {}\n"
        "    total = 0\n"
        "    for section in allowed:\n"
        "        items = section_items(section)\n"
        "        size = sum(int(item['size_bytes']) for item in items)\n"
        "        total += size\n"
        "        sections[section] = {'exists': os.path.isdir(os.path.join(root, section)), 'count': len(items), 'size_bytes': size, 'items': items}\n"
        "    print(json.dumps({'schema_version': cfg['status_schema'], 'remote_root': root, 'read_only': True, 'generated_at': now.replace(microsecond=0).isoformat(), 'total_size_bytes': total, 'sections': sections}, sort_keys=True))\n"
        "else:\n"
        "    task_ids = set(cfg['task_ids'])\n"
        "    max_age = None if cfg['older_than_days'] is None else int(cfg['older_than_days']) * 86400\n"
        "    candidates = []\n"
        "    for section in cfg['sections']:\n"
        "        safe_section(section)\n"
        "        base = os.path.join(root, section)\n"
        "        if not os.path.isdir(base):\n"
        "            continue\n"
        "        for name in sorted(os.listdir(base)):\n"
        "            safe_name(name)\n"
        "            p = os.path.realpath(os.path.join(base, name))\n"
        "            if not p.startswith(os.path.realpath(root) + os.sep):\n"
        "                continue\n"
        "            if not os.path.isdir(p) or os.path.islink(os.path.join(base, name)):\n"
        "                continue\n"
        "            if task_ids and name not in task_ids:\n"
        "                continue\n"
        "            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(p), datetime.timezone.utc)\n"
        "            age = max(0, int((now - mtime).total_seconds()))\n"
        "            if max_age is not None and age < max_age:\n"
        "                continue\n"
        "            candidates.append({'section': section, 'task_id': name, 'path': f'{section}/{name}', 'size_bytes': dir_size(p), 'age_seconds': age})\n"
        "    deleted = []\n"
        "    if not cfg['dry_run']:\n"
        "        for item in candidates:\n"
        "            shutil.rmtree(os.path.join(root, item['section'], item['task_id']))\n"
        "            deleted.append(item)\n"
        "    print(json.dumps({'schema_version': cfg['cleanup_schema'], 'remote_root': root, 'dry_run': bool(cfg['dry_run']), 'generated_at': now.replace(microsecond=0).isoformat(), 'filters': {'task_ids': sorted(task_ids), 'sections': cfg['sections'], 'older_than_days': cfg['older_than_days']}, 'candidate_count': len(candidates), 'deleted_count': len(deleted), 'candidates': candidates, 'deleted': deleted}, sort_keys=True))\n"
        "PY"
    )


def _reject_symlinks(root: Path) -> None:
    if root.is_symlink():
        raise OffloadError(f"unsafe symlink path: {root}")
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_symlink():
            raise OffloadError(f"unsafe symlink path: {path}")


def _write_runner(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
mkdir -p outputs
python3 - <<'PY'
import hashlib
import json
import math
import os
import re
import socket
import subprocess
from datetime import datetime, timezone

manifest = json.load(open('task_manifest.json'))
task_type = manifest['task_type']
started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_input(name):
    with open(os.path.join('inputs', name), encoding='utf-8') as handle:
        return json.load(handle)


def write_json(path, payload):
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write('\\n')


def write_jsonl(path, rows):
    with open(path, 'w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + '\\n')


def external_summary(input_payload):
    external = input_payload.get('external_corpus_snapshot') or {}
    samples = external.get('samples', [])
    return {
        'present': bool(external),
        'schema_version': external.get('schema_version'),
        'matched_file_count': external.get('matched_file_count'),
        'scanned_file_count': external.get('scanned_file_count'),
        'sample_count': len(samples) if isinstance(samples, list) else 0,
    }


def summary(input_payload, *, status='partial', method=None):
    payload = {
        'schema_version': 'remote_offload_contract_output.v1',
        'task_id': manifest['task_id'],
        'task_type': task_type,
        'status': status,
        'input_schema_version': input_payload.get('schema_version'),
        'input_counts': {
            'papers': len(input_payload.get('papers', [])),
            'artifacts': len(input_payload.get('artifacts', [])),
        },
        'external_corpus_snapshot': external_summary(input_payload),
    }
    if method:
        payload['method'] = method
    if status == 'partial':
        payload['note'] = 'contract runner placeholder; replace with task implementation on worker'
    return payload


def tokens_from_text(*values):
    text = ' '.join(str(value or '') for value in values)
    return [
        token
        for token in re.findall(r'[a-z0-9]+', text.lower())
        if len(token) >= 2
    ]


def sample_terms(sample):
    basename = str(sample.get('basename') or '')
    name_without_ext = os.path.splitext(basename)[0]
    matched_terms = sample.get('matched_terms', [])
    if not isinstance(matched_terms, list):
        matched_terms = []
    return set(tokens_from_text(name_without_ext, ' '.join(str(term) for term in matched_terms)))


def sample_token_counts(sample):
    counts = sample.get('token_counts') if isinstance(sample, dict) else None
    if isinstance(counts, dict):
        clean = {}
        for token, count in counts.items():
            token_text = str(token).lower()
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,63}', token_text):
                continue
            try:
                integer = int(count)
            except (TypeError, ValueError):
                continue
            if integer > 0:
                clean[token_text] = integer
        if clean:
            return clean
    return {token: 1 for token in sample_terms(sample)}


def sample_token_count(sample, counts):
    value = sample.get('token_count') if isinstance(sample, dict) else 0
    try:
        integer = int(value)
    except (TypeError, ValueError):
        integer = 0
    return max(integer, sum(counts.values()), 1)


def sample_size(sample):
    value = sample.get('size_bytes') if isinstance(sample, dict) else 0
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def safe_match(sample, *, score, overlap_terms):
    matched_terms = sample.get('matched_terms', [])
    if not isinstance(matched_terms, list):
        matched_terms = []
    return {
        'basename': str(sample.get('basename') or '')[:255],
        'extension': str(sample.get('extension') or '')[:32],
        'matched_terms': [
            str(term)[:128]
            for term in matched_terms[:20]
            if isinstance(term, str)
        ],
        'overlap_terms': sorted(overlap_terms)[:20],
        'relative_path_hash': str(sample.get('relative_path_hash') or ''),
        'score': round(float(score), 6),
        'size_bytes': sample_size(sample),
    }


def runner_model_policy(payload, *, expected_backend='fake_model'):
    policy = payload.get('model_policy') if isinstance(payload, dict) else None
    if not isinstance(policy, dict):
        return None
    if policy.get('backend') != expected_backend:
        return None
    return policy


def public_model_policy(policy):
    if not isinstance(policy, dict):
        return None
    public = {
        'backend': str(policy.get('backend') or ''),
        'model_id': str(policy.get('model_id') or ''),
        'device': str(policy.get('device') or ''),
        'quality_claim': bool(policy.get('quality_claim') is True),
    }
    if isinstance(policy.get('cache_policy'), dict):
        public['cache_policy'] = dict(policy['cache_policy'])
    if 'embedding_dim' in policy:
        public['embedding_dim'] = policy.get('embedding_dim')
    return public


def fake_model_embedding(text, *, model_id, dim):
    vector = [0.0 for _ in range(dim)]
    for index, token in enumerate(tokens_from_text(model_id, text)):
        digest = hashlib.sha256(f'{model_id}:{index}:{token}'.encode('utf-8')).digest()
        bucket = int.from_bytes(digest[:2], 'big') % dim
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[bucket] += sign * (1.0 + digest[3] / 255.0)
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 6) for value in vector]


def retrieval_eval_sweep(payload):
    external = payload.get('external_corpus_snapshot') or {}
    samples = external.get('samples', [])
    if not isinstance(samples, list):
        samples = []
    predictions = []
    policy = runner_model_policy(payload)
    method = 'fake_model_snapshot_rerank_v1' if policy else 'bm25_remote_snapshot_rerank'
    indexed_samples = []
    document_frequency = external.get('document_frequency') if isinstance(external, dict) else {}
    if not isinstance(document_frequency, dict):
        document_frequency = {}
    fallback_document_frequency = {}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        counts = sample_token_counts(sample)
        length = sample_token_count(sample, counts)
        terms = set(counts)
        for token in terms:
            fallback_document_frequency[token] = fallback_document_frequency.get(token, 0) + 1
        indexed_samples.append((sample, counts, length, terms))
    if not document_frequency:
        document_frequency = fallback_document_frequency
    avg_doc_len = (
        sum(item[2] for item in indexed_samples) / len(indexed_samples)
        if indexed_samples
        else 1.0
    )
    doc_count = max(1, int(external.get('matched_file_count') or len(indexed_samples) or 1))

    def idf(token):
        try:
            df = int(document_frequency.get(token, 0))
        except (TypeError, ValueError):
            df = 0
        df = max(0, min(df, doc_count))
        return math.log(1 + ((doc_count - df + 0.5) / (df + 0.5)))

    def bm25_score(query_terms, counts, doc_len):
        k1 = 1.2
        b = 0.75
        score = 0.0
        for token in query_terms:
            tf = counts.get(token, 0)
            if tf <= 0:
                continue
            denominator = tf + k1 * (1 - b + b * (doc_len / max(avg_doc_len, 1.0)))
            score += idf(token) * ((tf * (k1 + 1)) / denominator)
        return score

    for paper in payload.get('papers', []):
        paper_terms = set(tokens_from_text(
            paper.get('title'),
            paper.get('authors'),
            paper.get('venue'),
            payload.get('topic'),
        ))
        ranked = []
        for sample, counts, length, candidate_terms in indexed_samples:
            overlap = paper_terms & candidate_terms
            matched_terms = sample.get('matched_terms', [])
            if not isinstance(matched_terms, list):
                matched_terms = []
            matched_overlap = paper_terms & set(tokens_from_text(' '.join(str(term) for term in matched_terms)))
            score = bm25_score(paper_terms, counts, length)
            if policy:
                model_terms = set(tokens_from_text(policy.get('model_id'), sample.get('basename')))
                score += len(paper_terms & model_terms) / max(1, len(paper_terms))
            if score <= 0:
                score = (2 * len(overlap) + len(matched_overlap)) / max(1, len(paper_terms))
            ranked.append(safe_match(sample, score=score, overlap_terms=overlap))
        ranked.sort(key=lambda item: (-item['score'], item['basename']))
        top_matches = ranked[:5]
        predictions.append(
            {
                'paper_id': paper.get('id'),
                'title': paper.get('title'),
                'method': method,
                'score': top_matches[0]['score'] if top_matches else 0.0,
                'status': 'ranked' if top_matches else 'no_remote_samples',
                'top_matches': top_matches,
            }
        )
    report = summary(payload, status='succeeded', method=method)
    report.update(
        {
            'schema_version': 'retrieval_eval_sweep.report.v1',
            'paper_count': len(payload.get('papers', [])),
            'prediction_count': len(predictions),
            'note': (
                'Deterministic fake-model/BM25-style rerank over redacted '
                'remote-library snapshot samples and basename-derived token '
                'statistics; it is a sanity-check worker, not a semantic '
                'retrieval quality claim.'
            ),
        }
    )
    if policy:
        report['model_policy'] = public_model_policy(policy)
    write_jsonl('outputs/predictions.jsonl', predictions)
    write_json('outputs/retrieval_eval_report.json', report)
    return 'succeeded', []


def source_text_pages(paper):
    text = paper.get('source_text') if isinstance(paper, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None, 'missing_explicit_source_text'
    if len(text.encode('utf-8')) > 2_000_000:
        return None, 'source_text_too_large'
    expected_hash = paper.get('source_text_sha256')
    actual_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if expected_hash and str(expected_hash) != actual_hash:
        return None, 'source_text_hash_mismatch'
    raw_count = paper.get('source_text_page_count')
    try:
        page_count = int(raw_count)
    except (TypeError, ValueError):
        page_count = 0
    if page_count > 1000:
        return None, 'source_text_too_many_pages'
    if page_count > 1:
        pages = [page.strip() for page in text.split('\\n\\n') if page.strip()]
    else:
        pages = [block.strip() for block in re.split(r'\\n\\s*\\n+', text) if block.strip()]
    if not pages:
        return None, 'missing_explicit_source_text'
    return pages, None


def pdf_file_pages(paper):
    rel = paper.get('pdf_file') if isinstance(paper, dict) else None
    if not isinstance(rel, str) or not rel:
        return None, 'missing_explicit_pdf_file'
    if rel.startswith('/') or '\\\\' in rel or '..' in rel.split('/'):
        return None, 'unsafe_pdf_file'
    path = os.path.join('inputs', rel)
    if os.path.islink(path) or not os.path.isfile(path):
        return None, 'missing_explicit_pdf_file'
    if not path.lower().endswith('.pdf'):
        return None, 'unsupported_pdf_file_type'
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, 'missing_explicit_pdf_file'
    if size > 100_000_000:
        return None, 'pdf_file_too_large'
    expected_hash = paper.get('pdf_file_sha256')
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
    except OSError:
        return None, 'missing_explicit_pdf_file'
    actual_hash = digest.hexdigest()
    if expected_hash and str(expected_hash) != actual_hash:
        return None, 'pdf_file_hash_mismatch'
    pages, parser, reason = python_pdf_pages(path)
    if pages is None:
        pages, parser, reason = pdftotext_pages(path)
    if pages is None:
        return None, reason
    if not pages:
        return None, 'pdf_text_empty'
    text_bytes = '\\n\\n'.join(pages).encode('utf-8')
    if len(text_bytes) > 2_000_000:
        return None, 'source_text_too_large'
    return (pages, parser), None


def python_pdf_pages(path):
    if os.environ.get('RH_OFFLOAD_DISABLE_PYTHON_PDF') == '1':
        return None, None, 'pdf_parser_unavailable'
    reader_cls = None
    try:
        from pypdf import PdfReader as reader_cls
    except Exception:
        try:
            from PyPDF2 import PdfReader as reader_cls
        except Exception:
            reader_cls = None
    if reader_cls is None:
        return None, None, 'pdf_parser_unavailable'
    try:
        reader = reader_cls(path)
        pages = []
        for page in list(reader.pages)[:1000]:
            text = page.extract_text() or ''
            text = ' '.join(text.replace('\\x00', ' ').split())
            if text:
                pages.append(text)
    except Exception:
        return None, None, 'pdf_parse_failed'
    return pages, 'explicit_pdf_pack_pypdf_v1', None


def pdftotext_pages(path):
    try:
        completed = subprocess.run(
            ['pdftotext', '-layout', path, '-'],
            check=False,
            text=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError:
        return None, None, 'pdf_parser_unavailable'
    except subprocess.TimeoutExpired:
        return None, None, 'pdf_parse_timeout'
    if completed.returncode != 0:
        return None, None, 'pdf_parse_failed'
    pages = [
        ' '.join(page.replace('\\x00', ' ').split())
        for page in completed.stdout.split('\\f')
    ]
    pages = [page for page in pages if page]
    if not pages:
        return None, None, 'pdf_text_empty'
    return pages[:1000], 'explicit_pdf_pack_pdftotext_v1', None


def paper_text_extraction_batch(payload):
    rows = []
    succeeded = 0
    skipped = 0
    for paper in payload.get('papers', []):
        if not isinstance(paper, dict):
            skipped += 1
            rows.append({'status': 'skipped', 'reason': 'invalid_paper_row'})
            continue
        pages, reason = source_text_pages(paper)
        parser = 'explicit_text_pack_v1'
        if pages is None and reason == 'missing_explicit_source_text':
            pdf_result, reason = pdf_file_pages(paper)
            if pdf_result is not None:
                pages, parser = pdf_result
        paper_id = paper.get('id')
        if pages is None:
            skipped += 1
            rows.append(
                {
                    'paper_id': paper_id,
                    'status': 'pending_text_extraction',
                    'reason': reason or 'missing_explicit_source_text',
                }
            )
            continue
        succeeded += 1
        rows.append(
            {
                'paper_id': paper_id,
                'status': 'succeeded',
                'pdf_hash': str(paper.get('pdf_hash') or ''),
                'page_count': len(pages),
                'pages_text': pages,
                'parser': parser,
                'doc_name': str(paper.get('title') or f'paper_{paper_id}')[:255],
                'structure': [],
                'source_text_sha256': hashlib.sha256(
                    ('\\n\\n'.join(pages)).encode('utf-8')
                ).hexdigest(),
            }
        )
    status = 'succeeded' if succeeded else 'partial'
    report = summary(
        payload,
        status=status,
        method='explicit_text_or_pdf_pack_v1',
    )
    report.update(
        {
            'paper_text_schema_version': 'paper_text_extraction_batch.summary.v1',
            'paper_count': len(payload.get('papers', [])),
            'succeeded_count': succeeded,
            'skipped_count': skipped,
            'note': (
                'Processed only explicit source_text or explicitly packaged PDF '
                'files inside the task pack; no external paths were read on the worker.'
            ),
        }
    )
    write_jsonl('outputs/paper_text_extraction_results.jsonl', rows)
    write_json('outputs/summary.json', report)
    warnings = []
    if skipped:
        warnings.append(f'{skipped} paper(s) missing explicit source_text')
    return status, warnings


def deterministic_embedding(text, *, dim=16):
    vector = [0.0 for _ in range(dim)]
    tokens = tokens_from_text(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.sha256(token.encode('utf-8')).digest()
        bucket = int.from_bytes(digest[:2], 'big') % dim
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        weight = 1.0 + (digest[3] / 255.0)
        vector[bucket] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 6) for value in vector]


def wiki_embedding_batch(payload):
    rows = []
    succeeded = 0
    skipped = 0
    policy = runner_model_policy(payload)
    method = 'fake_model_embedding_v1' if policy else 'deterministic_hash_embedding_v1'
    embedding_dim = 16
    if policy:
        try:
            embedding_dim = int(policy.get('embedding_dim') or 16)
        except (TypeError, ValueError):
            embedding_dim = 16
        embedding_dim = max(1, min(4096, embedding_dim))
    for artifact in payload.get('artifacts', []):
        if not isinstance(artifact, dict):
            skipped += 1
            rows.append({'status': 'skipped', 'reason': 'invalid_artifact_row'})
            continue
        artifact_id = artifact.get('id')
        text = artifact.get('embedding_text')
        if not isinstance(text, str) or not text.strip():
            skipped += 1
            rows.append(
                {
                    'artifact_id': artifact_id,
                    'status': 'pending_embedding',
                    'reason': 'missing_explicit_embedding_text',
                }
            )
            continue
        if len(text.encode('utf-8')) > 200_000:
            skipped += 1
            rows.append(
                {
                    'artifact_id': artifact_id,
                    'status': 'pending_embedding',
                    'reason': 'embedding_text_too_large',
                }
            )
            continue
        expected_hash = artifact.get('embedding_text_sha256')
        actual_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if expected_hash and str(expected_hash) != actual_hash:
            skipped += 1
            rows.append(
                {
                    'artifact_id': artifact_id,
                    'status': 'pending_embedding',
                    'reason': 'embedding_text_hash_mismatch',
                }
            )
            continue
        succeeded += 1
        row = {
            'artifact_id': artifact_id,
            'status': 'succeeded',
            'artifact_type': artifact.get('artifact_type'),
            'method': method,
            'embedding_dim': embedding_dim,
            'embedding': (
                fake_model_embedding(
                    text,
                    model_id=str(policy.get('model_id') or ''),
                    dim=embedding_dim,
                )
                if policy
                else deterministic_embedding(text, dim=embedding_dim)
            ),
            'embedding_text_sha256': actual_hash,
        }
        if policy:
            row['model_id'] = str(policy.get('model_id') or '')
            row['device'] = str(policy.get('device') or '')
        rows.append(row)
    status = 'succeeded' if succeeded else 'partial'
    report = summary(
        payload,
        status=status,
        method=method,
    )
    report.update(
        {
            'wiki_embedding_schema_version': 'wiki_embedding_batch.summary.v1',
            'artifact_count': len(payload.get('artifacts', [])),
            'succeeded_count': succeeded,
            'skipped_count': skipped,
            'note': (
                'Deterministic or explicitly declared fake-model embedding '
                'over explicit artifact text packaged inside the task pack; '
                'no RH database, artifact paths, external files, automatic '
                'model download, or retrieval quality claim is involved.'
            ),
        }
    )
    if policy:
        report['model_policy'] = public_model_policy(policy)
    write_jsonl('outputs/wiki_embeddings.jsonl', rows)
    write_json('outputs/summary.json', report)
    warnings = []
    if skipped:
        warnings.append(f'{skipped} artifact(s) missing explicit embedding_text')
    return status, warnings


result_status = 'partial'
result_warnings = ['contract runner placeholder; replace with task implementation on worker']

if task_type == 'paper_text_extraction_batch':
    payload = read_input('paper_text_extraction_inputs.json')
    result_status, result_warnings = paper_text_extraction_batch(payload)
elif task_type == 'wiki_embedding_batch':
    payload = read_input('wiki_embedding_inputs.json')
    result_status, result_warnings = wiki_embedding_batch(payload)
elif task_type == 'retrieval_eval_sweep':
    payload = read_input('retrieval_eval_inputs.json')
    result_status, result_warnings = retrieval_eval_sweep(payload)
elif task_type == 'researchflowbench_batch_eval':
    payload = read_input('researchflowbench_inputs.json')
    write_json(
        'outputs/predictions.json',
        {'schema_version': 'remote_offload_contract_output.v1', 'predictions': []},
    )
    write_json('outputs/score_report.json', summary(payload))
else:
    raise SystemExit(f'unsupported task_type: {task_type}')

outputs = {}
for root, _, files in os.walk('outputs'):
    for name in files:
        path = os.path.join(root, name)
        rel = os.path.relpath(path, 'outputs')
        digest = hashlib.sha256(open(path, 'rb').read()).hexdigest()
        outputs[rel] = digest

result = {
    'task_id': manifest['task_id'],
    'task_type': task_type,
    'status': result_status,
    'started_at': started_at,
    'finished_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    'exit_code': 0,
    'output_hashes': outputs,
    'warnings': result_warnings,
    'server_hostname': socket.gethostname(),
    'git_commit': os.environ.get('GIT_COMMIT', 'unknown'),
}
json.dump(result, open('result_manifest.json', 'w'), indent=2, sort_keys=True)
PY
"""
    )
    path.chmod(0o755)


def _write_readme(path: Path, *, task_id: str, task_type: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"# RH offload task {task_id}",
                "",
                f"- Task type: `{task_type}`",
                "- Run from the copied server run directory with `bash runner.sh`.",
                "- Write importable outputs under `outputs/`.",
                "- Write `result_manifest.json` with output hashes before returning.",
                "- Do not write the Mac RH database or credentials.",
            ]
        )
        + "\n"
    )


def _run_checked(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=True)


def _run_capture(
    command: Sequence[str], *, timeout_seconds: int = 30
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
