from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from research_harness._core.storage.db import Database


RUNTIME_EVENT_COLUMNS = {
    "id",
    "event_id",
    "trace_id",
    "event_type",
    "created_at",
    "origin_surface",
    "actor",
    "topic_id",
    "job_id",
    "tool_name",
    "artifact_refs_json",
    "gate_decision",
    "error_code",
    "schema_version",
    "payload_json",
    "metadata_json",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA index_list({table})")}


def _trigger_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'trigger'
          AND tbl_name = ?
        """,
        (table,),
    ).fetchall()
    return {str(row["name"]) for row in rows}


def test_runtime_event_store_schema_exists_after_fresh_migration(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "runtime-events.db")
    db.migrate()

    conn = db.connect()
    try:
        assert "runtime_events" in _table_names(conn)
        assert RUNTIME_EVENT_COLUMNS <= _column_names(conn, "runtime_events")
        assert {
            "idx_runtime_events_event_id",
            "idx_runtime_events_trace_created",
            "idx_runtime_events_topic_created",
            "idx_runtime_events_job_created",
            "idx_runtime_events_type_created",
        } <= _index_names(conn, "runtime_events")
        assert {
            "trg_runtime_events_no_update",
            "trg_runtime_events_no_delete",
        } <= _trigger_names(conn, "runtime_events")
    finally:
        conn.close()


def test_runtime_event_store_accepts_inert_json_without_writers(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "runtime-event-inert-json.db")
    db.migrate()

    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'runtime events')")
        conn.execute(
            """
            INSERT INTO runtime_events (
                event_id,
                trace_id,
                event_type,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "selfdev:K113:1",
                "trace-1",
                "selfdev.handoff_created",
                "selfdev",
                "codex",
                1,
                "K113_RUNTIME_EVENT_STORE_SCHEMA_ONLY",
                "rh-selfdev",
                '[".rh-selfdev/handoffs/example.md"]',
                None,
                None,
                "runtime_event_record.v0",
                '{"status":"complete"}',
                '{"note":"inert json"}',
            ),
        )

        row = conn.execute(
            """
            SELECT event_id, artifact_refs_json, payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            ("selfdev:K113:1",),
        ).fetchone()

        assert row is not None
        assert row["artifact_refs_json"].startswith("[")
        assert row["payload_json"] == '{"status":"complete"}'
        assert row["metadata_json"] == '{"note":"inert json"}'
    finally:
        conn.close()


def test_runtime_event_store_is_append_only(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "runtime-event-append-only.db")
    db.migrate()

    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO runtime_events (
                event_id,
                event_type,
                origin_surface,
                schema_version
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "event:append-only",
                "tool.completed",
                "test",
                "runtime_event_record.v0",
            ),
        )
        with pytest.raises(
            sqlite3.DatabaseError, match="runtime_events is append-only"
        ):
            conn.execute(
                "UPDATE runtime_events SET event_type = ? WHERE event_id = ?",
                ("tool.failed", "event:append-only"),
            )
        with pytest.raises(
            sqlite3.DatabaseError, match="runtime_events is append-only"
        ):
            conn.execute(
                "DELETE FROM runtime_events WHERE event_id = ?",
                ("event:append-only",),
            )
    finally:
        conn.close()


def test_runtime_event_store_migration_records_writer_boundary() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "research_harness"
        / "storage"
        / "SCHEMA.md"
    )
    migration_path = (
        Path(__file__).resolve().parents[1] / "migrations" / "070_runtime_events.sql"
    )

    text = schema_path.read_text(encoding="utf-8")
    migration_text = migration_path.read_text(encoding="utf-8")

    assert "### `runtime_events`" in text
    assert "| `event_id` | `TEXT` | no |" in text
    assert "| `idx_runtime_events_event_id` | 1 | c | 0 |" in text
    assert "schema-only foundation" in migration_text
    assert "does not add writers" in migration_text
