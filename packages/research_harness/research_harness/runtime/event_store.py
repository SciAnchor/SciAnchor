"""Private storage helpers for normalized runtime event records."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from research_harness._core.storage.db import Database

from .event_normalizer import RuntimeEventRecord


RuntimeEventWriteStatus = Literal["inserted", "duplicate", "invalid", "error"]

_RUNTIME_EVENT_REQUIRED_INDEXES = frozenset(
    {
        "idx_runtime_events_event_id",
        "idx_runtime_events_trace_created",
        "idx_runtime_events_topic_created",
        "idx_runtime_events_job_created",
        "idx_runtime_events_type_created",
    }
)
_RUNTIME_EVENT_APPEND_ONLY_TRIGGERS = frozenset(
    {
        "trg_runtime_events_no_update",
        "trg_runtime_events_no_delete",
    }
)


@dataclass(frozen=True)
class RuntimeEventWriteResult:
    """Internal result for runtime event store append attempts."""

    ok: bool
    status: RuntimeEventWriteStatus
    event_id: str | None
    row_id: int | None = None
    error_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class RuntimeEventStoreRecord:
    """Internal readback wrapper for one stored runtime event row."""

    row_id: int
    record: RuntimeEventRecord
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class RuntimeEventStoreHealth:
    """Internal read-only diagnostic summary for the runtime event store."""

    ok: bool
    table_exists: bool
    append_only_triggers_present: bool
    required_indexes_present: bool
    row_count: int
    invalid_json_event_ids: tuple[str, ...] = ()
    missing_triggers: tuple[str, ...] = ()
    missing_indexes: tuple[str, ...] = ()
    error_code: str | None = None
    message: str | None = None


def _append_runtime_event(
    target: sqlite3.Connection | Database,
    record: RuntimeEventRecord,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> RuntimeEventWriteResult:
    """Append one already-normalized event record to ``runtime_events``."""

    validation_error = _validate_runtime_event_record(record)
    if validation_error is not None:
        return RuntimeEventWriteResult(
            ok=False,
            status="invalid",
            event_id=_text_or_none(record.event_id),
            error_code="invalid_record",
            message=validation_error,
        )

    try:
        artifact_refs_json = _stable_json(list(record.artifact_refs))
        payload_json = _stable_json(dict(record.payload or {}))
        metadata_json = _stable_json(dict(metadata or {}))
    except (TypeError, ValueError) as exc:
        return RuntimeEventWriteResult(
            ok=False,
            status="invalid",
            event_id=record.event_id,
            error_code="invalid_json",
            message=str(exc),
        )

    try:
        conn, owns_connection = _connect_target(target)
    except sqlite3.Error as exc:
        return RuntimeEventWriteResult(
            ok=False,
            status="error",
            event_id=record.event_id,
            error_code=_sqlite_error_code(exc),
            message=str(exc),
        )

    try:
        cursor = conn.execute(
            """
            INSERT INTO runtime_events (
                event_id,
                trace_id,
                event_type,
                created_at,
                origin_surface,
                actor,
                topic_id,
                job_id,
                tool_name,
                artifact_refs_json,
                gate_decision,
                error_code,
                schema_version,
                payload_json,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.event_id,
                record.trace_id,
                record.event_type,
                record.created_at,
                record.origin_surface,
                record.actor,
                record.topic_id,
                record.job_id,
                record.tool_name,
                artifact_refs_json,
                record.gate_decision,
                record.error_code,
                record.schema_version,
                payload_json,
                metadata_json,
            ),
        )
        if owns_connection:
            conn.commit()
        return RuntimeEventWriteResult(
            ok=True,
            status="inserted",
            event_id=record.event_id,
            row_id=int(cursor.lastrowid),
        )
    except sqlite3.IntegrityError as exc:
        if _is_duplicate_event_id(exc):
            return RuntimeEventWriteResult(
                ok=False,
                status="duplicate",
                event_id=record.event_id,
                error_code="duplicate_event_id",
                message=str(exc),
            )
        return RuntimeEventWriteResult(
            ok=False,
            status="error",
            event_id=record.event_id,
            error_code="integrity_error",
            message=str(exc),
        )
    except sqlite3.Error as exc:
        error_code = _sqlite_error_code(exc)
        return RuntimeEventWriteResult(
            ok=False,
            status="error",
            event_id=record.event_id,
            error_code=error_code,
            message=str(exc),
        )
    finally:
        if owns_connection:
            conn.close()


def _diagnose_runtime_event_store(
    target: sqlite3.Connection | Database,
) -> RuntimeEventStoreHealth:
    """Return private read-only health diagnostics for ``runtime_events``."""

    try:
        conn, owns_connection = _connect_target(target)
    except sqlite3.Error as exc:
        return RuntimeEventStoreHealth(
            ok=False,
            table_exists=False,
            append_only_triggers_present=False,
            required_indexes_present=False,
            row_count=0,
            error_code=_sqlite_error_code(exc),
            message=str(exc),
        )

    try:
        if not _table_exists(conn, "runtime_events"):
            return RuntimeEventStoreHealth(
                ok=False,
                table_exists=False,
                append_only_triggers_present=False,
                required_indexes_present=False,
                row_count=0,
                error_code="missing_table",
                message="runtime_events table is missing",
            )

        index_names = _index_names(conn, "runtime_events")
        trigger_names = _trigger_names(conn, "runtime_events")
        missing_indexes = tuple(sorted(_RUNTIME_EVENT_REQUIRED_INDEXES - index_names))
        missing_triggers = tuple(
            sorted(_RUNTIME_EVENT_APPEND_ONLY_TRIGGERS - trigger_names)
        )
        invalid_json_event_ids = _invalid_json_event_ids(conn)
        row_count = int(
            conn.execute("SELECT COUNT(*) AS count FROM runtime_events").fetchone()[
                "count"
            ]
        )
        ok = not missing_indexes and not missing_triggers and not invalid_json_event_ids
        return RuntimeEventStoreHealth(
            ok=ok,
            table_exists=True,
            append_only_triggers_present=not missing_triggers,
            required_indexes_present=not missing_indexes,
            row_count=row_count,
            invalid_json_event_ids=invalid_json_event_ids,
            missing_triggers=missing_triggers,
            missing_indexes=missing_indexes,
        )
    except sqlite3.Error as exc:
        return RuntimeEventStoreHealth(
            ok=False,
            table_exists=False,
            append_only_triggers_present=False,
            required_indexes_present=False,
            row_count=0,
            error_code=_sqlite_error_code(exc),
            message=str(exc),
        )
    finally:
        if owns_connection:
            conn.close()


def _read_runtime_event_by_event_id(
    target: sqlite3.Connection | Database,
    event_id: str,
) -> RuntimeEventStoreRecord | None:
    """Return one stored runtime event by exact event id."""

    event_id_text = _text_or_none(event_id)
    if event_id_text is None:
        return None

    try:
        conn, owns_connection = _connect_target(target)
    except sqlite3.Error:
        return None

    try:
        row = conn.execute(
            """
            SELECT *
            FROM runtime_events
            WHERE event_id = ?
            """,
            (event_id_text,),
        ).fetchone()
        if row is None:
            return None
        return _stored_runtime_event_from_row(row)
    finally:
        if owns_connection:
            conn.close()


def _read_runtime_events(
    target: sqlite3.Connection | Database,
    *,
    trace_id: str | None = None,
    job_id: str | None = None,
    topic_id: int | None = None,
    limit: int = 100,
) -> tuple[RuntimeEventStoreRecord, ...]:
    """Return stored runtime events matching private diagnostic filters."""

    filters: list[str] = []
    values: list[Any] = []
    if trace_id is not None:
        filters.append("trace_id = ?")
        values.append(trace_id)
    if job_id is not None:
        filters.append("job_id = ?")
        values.append(job_id)
    if topic_id is not None:
        filters.append("topic_id = ?")
        values.append(topic_id)
    if not filters:
        return ()

    values.append(_bounded_limit(limit))
    try:
        conn, owns_connection = _connect_target(target)
    except sqlite3.Error:
        return ()

    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM runtime_events
            WHERE {" AND ".join(filters)}
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            tuple(values),
        ).fetchall()
        return tuple(_stored_runtime_event_from_row(row) for row in rows)
    finally:
        if owns_connection:
            conn.close()


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
    return frozenset(
        str(row["name"]) for row in conn.execute(f"PRAGMA index_list({table_name})")
    )


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


def _invalid_json_event_ids(conn: sqlite3.Connection) -> tuple[str, ...]:
    invalid: list[str] = []
    rows = conn.execute(
        """
        SELECT event_id, artifact_refs_json, payload_json, metadata_json
        FROM runtime_events
        ORDER BY id ASC
        """
    ).fetchall()
    for row in rows:
        if (
            not _json_is_kind(row["artifact_refs_json"], list)
            or not _json_is_kind(row["payload_json"], dict)
            or not _json_is_kind(row["metadata_json"], dict)
        ):
            invalid.append(str(row["event_id"]))
    return tuple(invalid)


def _connect_target(
    target: sqlite3.Connection | Database,
) -> tuple[sqlite3.Connection, bool]:
    if isinstance(target, sqlite3.Connection):
        return target, False
    return target.connect(), True


def _stored_runtime_event_from_row(row: sqlite3.Row) -> RuntimeEventStoreRecord:
    artifact_refs = _json_list(row["artifact_refs_json"])
    payload = _json_object(row["payload_json"])
    metadata = _json_object(row["metadata_json"])
    return RuntimeEventStoreRecord(
        row_id=int(row["id"]),
        record=RuntimeEventRecord(
            event_id=row["event_id"],
            trace_id=row["trace_id"],
            event_type=row["event_type"],
            created_at=row["created_at"],
            origin_surface=row["origin_surface"],
            actor=row["actor"],
            topic_id=row["topic_id"],
            job_id=row["job_id"],
            tool_name=row["tool_name"],
            artifact_refs=tuple(str(value) for value in artifact_refs),
            gate_decision=row["gate_decision"],
            error_code=row["error_code"],
            schema_version=row["schema_version"],
            payload=payload,
        ),
        metadata=metadata,
    )


def _validate_runtime_event_record(record: RuntimeEventRecord) -> str | None:
    required_fields = {
        "event_id": record.event_id,
        "event_type": record.event_type,
        "origin_surface": record.origin_surface,
        "schema_version": record.schema_version,
    }
    for field_name, value in required_fields.items():
        if _text_or_none(value) is None:
            return f"{field_name} is required"
    return None


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_list(value: str) -> list[Any]:
    parsed = json.loads(value or "[]")
    if isinstance(parsed, list):
        return list(parsed)
    return []


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value or "{}")
    if isinstance(parsed, dict):
        return dict(parsed)
    return {}


def _json_is_kind(value: str, expected_type: type) -> bool:
    try:
        parsed = json.loads(value or "")
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, expected_type)


def _bounded_limit(limit: int) -> int:
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        return 100
    return max(1, min(parsed, 1000))


def _is_duplicate_event_id(exc: sqlite3.IntegrityError) -> bool:
    message = str(exc).lower()
    return "unique" in message and "runtime_events.event_id" in message


def _sqlite_error_code(exc: sqlite3.Error) -> str:
    message = str(exc).lower()
    if (
        "closed" in message
        or "bad parameter or other api misuse" in message
        or "unable to open database file" in message
    ):
        return "bad_connection"
    return "sqlite_error"


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
