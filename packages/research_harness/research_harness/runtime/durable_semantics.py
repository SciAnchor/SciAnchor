"""Private executable guards for RH durable runtime semantics."""

from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DurableSemanticCheck:
    """One read-only durable-semantics schema/read-model guard."""

    check_id: str
    ok: bool
    present: tuple[str, ...]
    missing: tuple[str, ...]
    evidence: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "ok": self.ok,
            "present": list(self.present),
            "missing": list(self.missing),
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class DurableSemanticsReport:
    """Private read-only durable-semantics diagnostic report."""

    ok: bool
    status: str
    checks: tuple[DurableSemanticCheck, ...]
    schema_migration_required: bool
    rollback_or_dry_run_evidence: str
    error_code: str | None = None
    message: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "schema_migration_required": self.schema_migration_required,
            "rollback_or_dry_run_evidence": self.rollback_or_dry_run_evidence,
            "error_code": self.error_code,
            "message": self.message,
            "checks": [check.to_payload() for check in self.checks],
        }


def diagnose_durable_semantics(
    target: sqlite3.Connection | Any,
) -> DurableSemanticsReport:
    """Inspect local runtime/orchestrator/artifact durable semantics guards."""

    try:
        conn, owns_connection = _connect_target(target)
    except sqlite3.Error as exc:
        return DurableSemanticsReport(
            ok=False,
            status="local_guard_failed",
            checks=(),
            schema_migration_required=True,
            rollback_or_dry_run_evidence="local_read_only_diagnostics_failed",
            error_code=_sqlite_error_code(exc),
            message=str(exc),
        )

    try:
        checks = (
            _runtime_events_append_only_check(conn),
            _project_artifact_lineage_columns_check(conn),
            _artifact_dependency_unique_edge_check(conn),
            _orchestrator_run_read_model_columns_check(conn),
            _orchestrator_stage_event_read_model_columns_check(conn),
        )
    except sqlite3.Error as exc:
        return DurableSemanticsReport(
            ok=False,
            status="local_guard_failed",
            checks=(),
            schema_migration_required=True,
            rollback_or_dry_run_evidence="local_read_only_diagnostics_failed",
            error_code=_sqlite_error_code(exc),
            message=str(exc),
        )
    finally:
        if owns_connection:
            conn.close()

    ok = all(check.ok for check in checks)
    return DurableSemanticsReport(
        ok=ok,
        status=("stable_local_executable_guards" if ok else "local_guard_failed"),
        checks=checks,
        schema_migration_required=not ok,
        rollback_or_dry_run_evidence="local_read_only_diagnostics",
    )


def diagnose_current_migrated_schema() -> DurableSemanticsReport:
    """Diagnose the package's current migrated schema without touching user DBs."""

    with tempfile.TemporaryDirectory(prefix="rh-durable-semantics-") as tmp:
        db_path = Path(tmp) / "schema.db"
        _migrate_sqlite_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            return diagnose_durable_semantics(conn)
        finally:
            conn.close()


def _runtime_events_append_only_check(
    conn: sqlite3.Connection,
) -> DurableSemanticCheck:
    required_columns = (
        "event_id",
        "trace_id",
        "event_type",
        "origin_surface",
        "topic_id",
        "job_id",
        "tool_name",
        "artifact_refs_json",
        "gate_decision",
        "error_code",
        "schema_version",
        "payload_json",
        "metadata_json",
    )
    required_indexes = (
        "idx_runtime_events_event_id",
        "idx_runtime_events_trace_created",
        "idx_runtime_events_topic_created",
        "idx_runtime_events_job_created",
        "idx_runtime_events_type_created",
    )
    required_triggers = (
        "trg_runtime_events_no_update",
        "trg_runtime_events_no_delete",
    )
    present = (
        *_present_columns(conn, "runtime_events", required_columns),
        *_present_indexes(conn, "runtime_events", required_indexes),
        *_present_triggers(conn, "runtime_events", required_triggers),
    )
    missing = _missing(
        (
            *required_columns,
            *required_indexes,
            *required_triggers,
        ),
        present,
    )
    return DurableSemanticCheck(
        check_id="runtime-events-append-only",
        ok=not missing,
        present=present,
        missing=missing,
        evidence="runtime_events columns, unique/read indexes, and no-update/no-delete triggers",
    )


def _project_artifact_lineage_columns_check(
    conn: sqlite3.Connection,
) -> DurableSemanticCheck:
    required = (
        "parent_artifact_id",
        "provenance_record_id",
        "stale",
        "stale_reason",
    )
    present = _present_columns(conn, "project_artifacts", required)
    missing = _missing(required, present)
    return DurableSemanticCheck(
        check_id="project-artifact-lineage-columns",
        ok=not missing,
        present=present,
        missing=missing,
        evidence="project_artifacts lineage/provenance/staleness columns",
    )


def _artifact_dependency_unique_edge_check(
    conn: sqlite3.Connection,
) -> DurableSemanticCheck:
    required_columns = (
        "from_artifact_id",
        "to_artifact_id",
        "dependency_type",
    )
    present_columns = _present_columns(conn, "artifact_dependencies", required_columns)
    has_unique_edge = _has_unique_index(
        conn,
        "artifact_dependencies",
        required_columns,
    )
    present = (
        *present_columns,
        *(
            ("unique(from_artifact_id,to_artifact_id,dependency_type)",)
            if has_unique_edge
            else ()
        ),
    )
    missing = _missing(required_columns, present_columns)
    if not has_unique_edge:
        missing = (
            *missing,
            "unique(from_artifact_id,to_artifact_id,dependency_type)",
        )
    return DurableSemanticCheck(
        check_id="artifact-dependency-unique-edge",
        ok=not missing,
        present=present,
        missing=missing,
        evidence="artifact_dependencies lineage edge columns and unique edge guard",
    )


def _orchestrator_run_read_model_columns_check(
    conn: sqlite3.Connection,
) -> DurableSemanticCheck:
    required = (
        "current_stage",
        "stage_status",
        "gate_status",
        "blocking_issue_count",
        "unresolved_issue_count",
        "latest_plan_artifact_id",
        "latest_draft_artifact_id",
        "stop_before",
    )
    present = _present_columns(conn, "orchestrator_runs", required)
    missing = _missing(required, present)
    return DurableSemanticCheck(
        check_id="orchestrator-run-read-model-columns",
        ok=not missing,
        present=present,
        missing=missing,
        evidence="orchestrator_runs stage/gate read-model and stop_before columns",
    )


def _orchestrator_stage_event_read_model_columns_check(
    conn: sqlite3.Connection,
) -> DurableSemanticCheck:
    required = (
        "run_id",
        "from_stage",
        "to_stage",
        "event_type",
        "status",
        "gate_type",
        "actor",
        "rationale",
        "payload_json",
    )
    present = _present_columns(conn, "orchestrator_stage_events", required)
    missing = _missing(required, present)
    return DurableSemanticCheck(
        check_id="orchestrator-stage-event-read-model-columns",
        ok=not missing,
        present=present,
        missing=missing,
        evidence="orchestrator_stage_events transition/gate event read-model columns",
    )


def _connect_target(
    target: sqlite3.Connection | Any,
) -> tuple[sqlite3.Connection, bool]:
    if isinstance(target, sqlite3.Connection):
        target.row_factory = sqlite3.Row
        return target, False
    return target.connect(), True


def _migrate_sqlite_db(db_path: Path) -> None:
    migrations_dir = _migrations_dir()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        applied = {
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations")
        }
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            version = int(sql_file.name.split("_")[0])
            if version in applied:
                continue
            try:
                conn.executescript(sql_file.read_text(encoding="utf-8"))
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, sql_file.stem),
            )
            conn.commit()
    finally:
        conn.close()


def _migrations_dir() -> Path:
    package_migrations = Path(__file__).resolve().parents[2] / "migrations"
    source_migrations = Path(__file__).resolve().parents[3] / "migrations"
    if package_migrations.is_dir():
        return package_migrations
    return source_migrations


def _present_columns(
    conn: sqlite3.Connection,
    table_name: str,
    required: tuple[str, ...],
) -> tuple[str, ...]:
    if not _table_exists(conn, table_name):
        return ()
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    columns = {str(row["name"]) for row in rows}
    return tuple(name for name in required if name in columns)


def _present_indexes(
    conn: sqlite3.Connection,
    table_name: str,
    required: tuple[str, ...],
) -> tuple[str, ...]:
    if not _table_exists(conn, table_name):
        return ()
    indexes = _index_names(conn, table_name)
    return tuple(name for name in required if name in indexes)


def _present_triggers(
    conn: sqlite3.Connection,
    table_name: str,
    required: tuple[str, ...],
) -> tuple[str, ...]:
    if not _table_exists(conn, table_name):
        return ()
    triggers = _trigger_names(conn, table_name)
    return tuple(name for name in required if name in triggers)


def _has_unique_index(
    conn: sqlite3.Connection,
    table_name: str,
    required_columns: tuple[str, ...],
) -> bool:
    if not _table_exists(conn, table_name):
        return False
    for index in conn.execute(f"PRAGMA index_list({table_name})").fetchall():
        if int(index["unique"]) != 1:
            continue
        index_name = str(index["name"])
        columns = tuple(
            str(row["name"])
            for row in conn.execute(f"PRAGMA index_info({index_name})").fetchall()
        )
        if columns == required_columns:
            return True
    return False


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _index_names(conn: sqlite3.Connection, table_name: str) -> frozenset[str]:
    rows = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
    return frozenset(str(row["name"]) for row in rows)


def _trigger_names(conn: sqlite3.Connection, table_name: str) -> frozenset[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'trigger'
          AND tbl_name = ?
        """,
        (table_name,),
    ).fetchall()
    return frozenset(str(row["name"]) for row in rows)


def _missing(required: tuple[str, ...], present: tuple[str, ...]) -> tuple[str, ...]:
    present_set = set(present)
    return tuple(name for name in required if name not in present_set)


def _sqlite_error_code(exc: sqlite3.Error) -> str:
    name = getattr(exc, "sqlite_errorname", None)
    return str(name) if name else exc.__class__.__name__
