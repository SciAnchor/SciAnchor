"""Read-only doctor diagnostics for the runtime-shell read model."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


DOCTOR_CHECK_RECORD_SCHEMA_VERSION = "doctor_check_record.v0"
RUNTIME_DIAGNOSTICS_PREVIEW_SCHEMA_VERSION = "runtime_diagnostics_preview.v0"
_EMBEDDED_LOCAL_PATH = re.compile(r"(?<![\w:])(?:~|/)[^\s,;()]+")

DoctorDiagnosticStatus = Literal[
    "pass",
    "warn",
    "fail",
    "skipped",
    "not_applicable",
]


@dataclass(frozen=True)
class DoctorCheckRecord:
    """Internal normalized view over current read-only health diagnostics."""

    record_id: str
    event_type: str
    check_name: str
    status: DoctorDiagnosticStatus
    origin_surface: str = "runtime"
    error_code: str | None = None
    created_at: str | None = None
    artifact_refs: tuple[str, ...] = ()
    schema_version: str = DOCTOR_CHECK_RECORD_SCHEMA_VERSION
    payload: Mapping[str, Any] | None = None


def normalize_doctor_check(
    source: Mapping[str, Any],
    *,
    origin_surface: str | None = None,
) -> DoctorCheckRecord:
    """Normalize the existing `rh doctor` check shape without changing it."""

    check_name = _first_text(source, "check", "name") or "unknown"
    status = _doctor_status(source)
    event_type = "doctor.check_failed" if status == "fail" else "doctor.check_completed"
    origin = (
        origin_surface or _first_text(source, "origin_surface", "origin") or "doctor"
    )
    artifact_refs = _compact_tuple(
        _first_text(source, "path"),
        _first_text(source, "config_path"),
        _first_text(source, "workspace_root"),
    )
    payload = _compact_dict(
        {
            key: _json_clone(value)
            for key, value in source.items()
            if key
            not in {
                "check",
                "name",
                "ok",
                "path",
                "config_path",
                "workspace_root",
                "origin",
                "origin_surface",
            }
        }
    )

    return DoctorCheckRecord(
        record_id=f"doctor_check:{origin}:{_slug(check_name)}",
        event_type=event_type,
        check_name=check_name,
        status=status,
        origin_surface=origin,
        error_code=f"{_slug(check_name)}_failed" if status == "fail" else None,
        artifact_refs=artifact_refs,
        payload=payload,
    )


def check_skill_manifest_validity(
    repo_root: Path,
    *,
    skills_dirname: str = "skills",
) -> DoctorCheckRecord:
    """Inspect the existing skill manifest and referenced skill paths."""

    manifest_path = Path(repo_root) / skills_dirname / "manifest.json"
    if not manifest_path.is_file():
        return _record(
            check_name="skill_manifest_validity",
            status="fail",
            error_code="skill_manifest_missing",
            artifact_refs=(str(manifest_path),),
            payload={"manifest_exists": False, "manifest_skill_count": 0},
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _record(
            check_name="skill_manifest_validity",
            status="fail",
            error_code="invalid_skill_manifest",
            artifact_refs=(str(manifest_path),),
            payload={
                "manifest_exists": True,
                "manifest_parse_error": "invalid_json",
                "manifest_skill_count": 0,
            },
        )

    if not isinstance(manifest, Mapping):
        return _record(
            check_name="skill_manifest_validity",
            status="fail",
            error_code="invalid_skill_manifest",
            artifact_refs=(str(manifest_path),),
            payload={
                "manifest_exists": True,
                "manifest_parse_error": "non_object_json",
                "manifest_skill_count": 0,
            },
        )

    entries = manifest.get("skills")
    skill_entries = (
        [entry for entry in entries if isinstance(entry, Mapping)]
        if isinstance(entries, list)
        else []
    )
    missing_paths = _missing_manifest_skill_paths(
        repo_root=Path(repo_root), entries=skill_entries
    )

    return _record(
        check_name="skill_manifest_validity",
        status="pass" if not missing_paths else "fail",
        error_code=None if not missing_paths else "skill_manifest_path_missing",
        artifact_refs=(str(manifest_path),),
        payload={
            "manifest_exists": True,
            "manifest_skill_count": len(skill_entries),
            "missing_skill_paths": missing_paths,
        },
    )


def check_generated_skill_cache(
    repo_root: Path,
    *,
    skills_dirname: str = "skills",
) -> DoctorCheckRecord:
    """Detect generated skill cache files that should not affect provenance."""

    skills_dir = Path(repo_root) / skills_dirname
    generated = _find_generated_cache_files(skills_dir)
    return _record(
        check_name="generated_skill_cache",
        status="warn" if generated else "pass",
        error_code="generated_skill_cache_present" if generated else None,
        artifact_refs=tuple(str(path) for path in generated),
        payload={"generated_cache_count": len(generated)},
    )


def check_job_ledger_state(records: Sequence[Mapping[str, Any]]) -> DoctorCheckRecord:
    """Summarize internal job-ledger states without mutating records."""

    state_counts = Counter(
        _first_text(record, "ledger_state", "status", "state") or "unknown"
        for record in records
    )
    source_type_counts = Counter(
        _first_text(record, "source_type") or "unknown" for record in records
    )
    attention_states = {"failed", "blocked_by_gate", "waiting_for_input"}
    needs_attention = any(state_counts.get(state, 0) for state in attention_states)

    return _record(
        check_name="job_ledger_state",
        status="warn" if needs_attention else "pass",
        error_code="job_ledger_attention_required" if needs_attention else None,
        payload={
            "record_count": len(records),
            "state_counts": dict(sorted(state_counts.items())),
            "source_type_counts": dict(sorted(source_type_counts.items())),
        },
    )


def check_event_source_integrity(
    records: Sequence[Mapping[str, Any]],
) -> DoctorCheckRecord:
    """Check event read-model rows for duplicate ids and missing event types."""

    event_ids = [
        event_id
        for event_id in (_first_text(record, "event_id", "id") for record in records)
        if event_id
    ]
    counts = Counter(event_ids)
    duplicate_event_ids = sorted(
        event_id for event_id, count in counts.items() if count > 1
    )
    missing_event_id_count = sum(
        1 for record in records if not _first_text(record, "event_id", "id")
    )
    missing_event_type_count = sum(
        1 for record in records if not _first_text(record, "event_type", "type")
    )
    failed = bool(
        duplicate_event_ids or missing_event_id_count or missing_event_type_count
    )

    return _record(
        check_name="event_source_integrity",
        status="fail" if failed else "pass",
        error_code="event_source_integrity_failed" if failed else None,
        payload={
            "event_count": len(records),
            "duplicate_event_ids": duplicate_event_ids,
            "missing_event_id_count": missing_event_id_count,
            "missing_event_type_count": missing_event_type_count,
        },
    )


def check_artifact_path_writability(path: Path) -> DoctorCheckRecord:
    """Check whether a path's parent is writable without creating a probe file."""

    target = Path(path)
    parent = target if target.is_dir() else target.parent
    writable = parent.is_dir() and os.access(parent, os.W_OK)
    return _record(
        check_name="artifact_path_writability",
        status="pass" if writable else "fail",
        error_code=None if writable else "artifact_path_not_writable",
        artifact_refs=(str(target),),
        payload={
            "checked_path": str(target),
            "writable_parent": str(parent),
            "parent_exists": parent.is_dir(),
        },
    )


def check_showcase_bundle_paths(paths: Sequence[Path]) -> DoctorCheckRecord:
    """Validate explicit showcase bundle paths supplied by a caller."""

    explicit_paths = tuple(Path(path) for path in paths)
    if not explicit_paths:
        return _record(
            check_name="showcase_bundle_paths",
            status="not_applicable",
            payload={"provided_path_count": 0, "missing_paths": []},
        )

    missing = [str(path) for path in explicit_paths if not path.exists()]
    return _record(
        check_name="showcase_bundle_paths",
        status="fail" if missing else "pass",
        error_code="showcase_bundle_missing" if missing else None,
        artifact_refs=tuple(str(path) for path in explicit_paths),
        payload={
            "provided_path_count": len(explicit_paths),
            "missing_paths": missing,
        },
    )


def doctor_check_record_to_dict(record: DoctorCheckRecord) -> dict[str, Any]:
    """Return a JSON-like dictionary for an internal doctor check record."""

    payload = asdict(record)
    payload["artifact_refs"] = list(record.artifact_refs)
    payload["payload"] = _json_clone(record.payload or {})
    return payload


def check_skill_provenance(repo_root: Path) -> DoctorCheckRecord:
    """Surface skill provenance (source/version/validation) and manifest drift.

    Read-only: runs the existing provenance scanner (previously only exercised by
    tests) so ``rh doctor`` reports the public skill surface, manifest drift, and
    per-skill validation status instead of leaving the data unsurfaced.
    """
    try:
        from .skill_provenance import scan_skill_provenance

        report = scan_skill_provenance(Path(repo_root))
    except Exception as exc:  # noqa: BLE001 — doctor is best-effort and read-only
        return _record(
            check_name="skill_provenance",
            status="warn",
            error_code="skill_provenance_unavailable",
            payload={"error": f"{type(exc).__name__}: {exc}"},
        )

    validation_counts: dict[str, int] = {}
    for record in report.records:
        key = str(getattr(record, "validation_status", "") or "unknown")
        validation_counts[key] = validation_counts.get(key, 0) + 1

    drift = bool(report.manifest_drift)
    missing = len(report.missing_from_manifest)
    extra = len(report.manifest_only)
    needs_attention = drift or missing or extra
    return _record(
        check_name="skill_provenance",
        status="warn" if needs_attention else "pass",
        error_code="skill_provenance_drift" if needs_attention else None,
        payload={
            "public_skill_count": report.public_skill_count,
            "manifest_drift": drift,
            "missing_from_manifest": missing,
            "manifest_only": extra,
            "validation_status_counts": dict(sorted(validation_counts.items())),
        },
    )


def load_job_ledger_records(longrun_db_path: Path) -> list[dict[str, Any]]:
    """Read-only load of job-ledger records from a longtask ``state.db``.

    Opens the DB read-only (no migrate/mkdir side effects, so the doctor check
    stays read-only) and normalizes longtask runs and gates into ledger records
    via the existing normalizers. Returns ``[]`` when the DB is absent or
    unreadable — doctor must be best-effort and never crash on optional state.
    """
    path = Path(longrun_db_path)
    if not path.is_file():
        return []
    try:
        import sqlite3

        from .job_ledger import (
            job_ledger_record_to_dict,
            normalize_longtask_gate,
            normalize_longtask_run,
        )

        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except Exception:  # noqa: BLE001 — optional, read-only state
        return []

    records: list[dict[str, Any]] = []
    try:
        for table, normalizer in (
            ("longtask_runs", normalize_longtask_run),
            ("longtask_gates", normalize_longtask_gate),
        ):
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            except Exception:  # noqa: BLE001 — table may not exist in this schema
                continue
            for row in rows:
                try:
                    records.append(job_ledger_record_to_dict(normalizer(dict(row))))
                except Exception:  # noqa: BLE001 — skip malformed rows
                    continue
    finally:
        conn.close()
    return records


def _default_longrun_db_path(repo_root: Path) -> Path:
    return Path(repo_root) / ".longrun" / "state.db"


def build_runtime_diagnostics_preview(
    checks: Sequence[Mapping[str, Any]],
    *,
    repo_root: Path,
    artifact_path: Path,
) -> dict[str, Any]:
    """Build a public-safe, read-only diagnostics preview payload."""

    records = [normalize_doctor_check(check, origin_surface="cli") for check in checks]
    records.extend(
        [
            check_skill_manifest_validity(repo_root),
            check_skill_provenance(repo_root),
            check_generated_skill_cache(repo_root),
            check_job_ledger_state(
                load_job_ledger_records(_default_longrun_db_path(repo_root))
            ),
            check_event_source_integrity([]),
            check_artifact_path_writability(artifact_path),
            check_showcase_bundle_paths([]),
        ]
    )
    diagnostics = [
        redact_runtime_diagnostic_output(doctor_check_record_to_dict(record), repo_root)
        for record in records
    ]
    status_counts: dict[str, int] = {}
    for item in diagnostics:
        if isinstance(item, Mapping):
            status = str(item.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
    overall_status = _runtime_diagnostics_overall_status(status_counts)
    return {
        "check": "runtime_diagnostics",
        "preview": True,
        "schema_version": RUNTIME_DIAGNOSTICS_PREVIEW_SCHEMA_VERSION,
        "origin": "rh doctor --runtime-diagnostics",
        "status": overall_status,
        "ok": overall_status != "fail",
        "summary": {
            "record_count": len(diagnostics),
            "status_counts": dict(sorted(status_counts.items())),
        },
        "diagnostics": diagnostics,
        "note": "preview: read-only runtime diagnostics",
    }


def redact_runtime_diagnostic_output(value: Any, repo_root: Path) -> Any:
    """Redact paths, URLs, and secret-like values for preview CLI output."""

    return _redact_runtime_diagnostic_value(value, repo_root)


def _runtime_diagnostics_overall_status(status_counts: Mapping[str, int]) -> str:
    if status_counts.get("fail"):
        return "fail"
    if status_counts.get("warn"):
        return "warn"
    return "pass"


def _redact_runtime_diagnostic_value(
    value: Any,
    repo_root: Path,
    *,
    key: str | None = None,
) -> Any:
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact_runtime_diagnostic_value(
                item_value,
                repo_root,
                key=str(item_key),
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_runtime_diagnostic_value(item, repo_root, key=key) for item in value
        ]
    if isinstance(value, tuple):
        return [
            _redact_runtime_diagnostic_value(item, repo_root, key=key) for item in value
        ]
    if isinstance(value, str):
        return _redact_runtime_diagnostic_text(value, repo_root, key=key)
    return value


def _redact_runtime_diagnostic_text(
    value: str,
    repo_root: Path,
    *,
    key: str | None = None,
) -> str:
    normalized_key = (key or "").lower()
    if normalized_key in {"api_key", "token", "authorization", "secret"}:
        return "<redacted>"
    if normalized_key in {"base_url", "url", "endpoint"}:
        return "<redacted:url>"
    if _looks_like_secret(value):
        return "<redacted>"
    if _looks_like_path_key(normalized_key) or _looks_like_absolute_path(value):
        return _public_path_ref(value, repo_root)
    return _EMBEDDED_LOCAL_PATH.sub(
        lambda match: _public_path_ref(match.group(0), repo_root),
        value,
    )


def _looks_like_secret(value: str) -> bool:
    lowered = value.lower()
    if lowered.startswith(("sk-", "sk_", "ghp_", "github_pat_")):
        return True
    return any(marker in lowered for marker in ("api_key=", "token=", "bearer "))


def _looks_like_path_key(key: str) -> bool:
    return key in {
        "artifact_refs",
        "checked_path",
        "config_path",
        "db_path",
        "missing_paths",
        "path",
        "workspace_root",
        "writable_parent",
    }


def _looks_like_absolute_path(value: str) -> bool:
    return value.startswith(("/", "~")) or bool(Path(value).anchor)


def _public_path_ref(value: str, repo_root: Path) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        return value
    try:
        relative = path.resolve().relative_to(repo_root.resolve())
    except (OSError, ValueError):
        return f"local:{path.name or 'path'}"
    return f"workspace:{relative.as_posix()}"


def _record(
    *,
    check_name: str,
    status: DoctorDiagnosticStatus,
    error_code: str | None = None,
    origin_surface: str = "runtime",
    artifact_refs: tuple[str, ...] = (),
    payload: Mapping[str, Any] | None = None,
) -> DoctorCheckRecord:
    return DoctorCheckRecord(
        record_id=f"doctor_check:{origin_surface}:{_slug(check_name)}",
        event_type="doctor.check_failed"
        if status == "fail"
        else "doctor.check_completed",
        check_name=check_name,
        status=status,
        origin_surface=origin_surface,
        error_code=error_code,
        artifact_refs=artifact_refs,
        payload=payload,
    )


def _doctor_status(source: Mapping[str, Any]) -> DoctorDiagnosticStatus:
    note = (_first_text(source, "note") or "").lower()
    if note == "optional":
        return "skipped"

    status = (_first_text(source, "status") or "").lower()
    if status in {"pass", "warn", "fail", "skipped", "not_applicable"}:
        return status  # type: ignore[return-value]
    if status in {"ok", "success", "completed", "complete"}:
        return "pass"
    if status in {"warning", "needs_attention"}:
        return "warn"
    if status in {"error", "failed", "failure"}:
        return "fail"

    ok = _bool(_get(source, "ok", "configured", "table_exists"))
    if ok is False:
        return "fail"
    return "pass"


def _missing_manifest_skill_paths(
    *,
    repo_root: Path,
    entries: Sequence[Mapping[str, Any]],
) -> list[str]:
    missing: list[str] = []
    for entry in entries:
        path = _first_text(entry, "path")
        if not path:
            continue
        if not (repo_root / path).exists():
            missing.append(path)
    return sorted(missing)


def _find_generated_cache_files(skills_dir: Path) -> tuple[Path, ...]:
    if not skills_dir.is_dir():
        return ()
    generated: list[Path] = []
    for path in skills_dir.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.parts)
        if (
            "__pycache__" in parts
            or ".pytest_cache" in parts
            or path.suffix in {".pyc", ".pyo"}
        ):
            generated.append(path)
    return tuple(sorted(generated))


def _get(source: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = source.get(name)
        if value is not None:
            return value
    return None


def _first_text(source: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = _get(source, name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "pass", "ok"}:
        return True
    if text in {"0", "false", "no", "n", "fail", "failed", "error"}:
        return False
    return None


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return text.strip("_") or "unknown"


def _compact_tuple(*values: str | None) -> tuple[str, ...]:
    return tuple(value for value in values if value)


def _compact_dict(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _json_clone(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_clone(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_clone(item) for item in value]
    if isinstance(value, list):
        return [_json_clone(item) for item in value]
    return value
