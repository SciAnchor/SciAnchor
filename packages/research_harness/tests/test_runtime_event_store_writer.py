from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from research_harness._core.storage.db import Database
from research_harness.runtime.event_normalizer import RuntimeEventRecord
from research_harness.runtime.event_store import _append_runtime_event


def _migrated_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "runtime-event-store.db")
    db.migrate()
    return db


def _record(**overrides: object) -> RuntimeEventRecord:
    record = RuntimeEventRecord(
        event_id="runtime:test:1",
        trace_id="trace-1",
        event_type="tool.completed",
        created_at="2026-06-09T17:50:00Z",
        origin_surface="test",
        actor="codex",
        job_id="job-1",
        tool_name="sample_tool",
        artifact_refs=("artifacts:beta", "artifacts:alpha"),
        payload={"z": 2, "a": {"nested": True}},
    )
    return replace(record, **overrides)


def test_append_runtime_event_writes_deterministic_json(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        result = _append_runtime_event(
            conn,
            _record(),
            metadata={"z": 3, "a": 1},
        )

        assert result.ok is True
        assert result.status == "inserted"
        assert result.event_id == "runtime:test:1"
        assert result.row_id is not None

        row = conn.execute(
            """
            SELECT event_id, trace_id, event_type, created_at, origin_surface,
                   actor, job_id, tool_name, artifact_refs_json,
                   schema_version, payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            ("runtime:test:1",),
        ).fetchone()

        assert row is not None
        assert row["trace_id"] == "trace-1"
        assert row["created_at"] == "2026-06-09T17:50:00Z"
        assert row["artifact_refs_json"] == '["artifacts:beta","artifacts:alpha"]'
        assert row["payload_json"] == '{"a":{"nested":true},"z":2}'
        assert row["metadata_json"] == '{"a":1,"z":3}'
    finally:
        conn.close()


def test_append_runtime_event_reports_duplicate_without_upsert(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        first = _append_runtime_event(conn, _record())
        duplicate = _append_runtime_event(conn, _record())

        assert first.status == "inserted"
        assert duplicate.ok is False
        assert duplicate.status == "duplicate"
        assert duplicate.error_code == "duplicate_event_id"
        assert duplicate.event_id == "runtime:test:1"
        assert duplicate.row_id is None
        assert (
            conn.execute(
                "SELECT COUNT(*) AS count FROM runtime_events WHERE event_id = ?",
                ("runtime:test:1",),
            ).fetchone()["count"]
            == 1
        )
    finally:
        conn.close()


def test_append_runtime_event_rejects_invalid_required_fields(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        result = _append_runtime_event(conn, _record(event_id=" "))

        assert result.ok is False
        assert result.status == "invalid"
        assert result.error_code == "invalid_record"
        assert result.row_id is None
        assert (
            conn.execute("SELECT COUNT(*) AS count FROM runtime_events").fetchone()[
                "count"
            ]
            == 0
        )
    finally:
        conn.close()


def test_append_runtime_event_reports_json_serialization_failure(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        result = _append_runtime_event(
            conn,
            _record(payload={"bad": object()}),
        )

        assert result.ok is False
        assert result.status == "invalid"
        assert result.error_code == "invalid_json"
        assert result.row_id is None
        assert (
            conn.execute("SELECT COUNT(*) AS count FROM runtime_events").fetchone()[
                "count"
            ]
            == 0
        )
    finally:
        conn.close()


def test_append_runtime_event_does_not_mutate_inputs(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        payload = {"z": [{"b": 1}], "a": 2}
        metadata = {"m": {"z": 1, "a": 2}}
        record = _record(payload=payload)
        payload_before = deepcopy(payload)
        metadata_before = deepcopy(metadata)

        result = _append_runtime_event(conn, record, metadata=metadata)

        assert result.ok is True
        assert payload == payload_before
        assert metadata == metadata_before
    finally:
        conn.close()


def test_append_runtime_event_accepts_database_without_public_runtime_export(
    tmp_path: Path,
) -> None:
    import research_harness.runtime as runtime

    db = _migrated_db(tmp_path)

    result = _append_runtime_event(db, _record(event_id="runtime:test:database"))

    assert result.status == "inserted"
    assert "append_runtime_event" not in runtime.__all__
    assert "_append_runtime_event" not in runtime.__all__


def test_append_runtime_event_commits_helper_owned_database_connection(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)

    result = _append_runtime_event(
        db,
        _record(event_id="runtime:test:database-committed"),
    )

    conn = db.connect()
    try:
        assert result.status == "inserted"
        assert (
            conn.execute(
                "SELECT COUNT(*) AS count FROM runtime_events WHERE event_id = ?",
                ("runtime:test:database-committed",),
            ).fetchone()["count"]
            == 1
        )
    finally:
        conn.close()


def test_append_runtime_event_reports_bad_caller_connection(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    conn.close()

    result = _append_runtime_event(conn, _record(event_id="runtime:test:closed"))

    assert result.ok is False
    assert result.status == "error"
    assert result.error_code == "bad_connection"
    assert result.row_id is None


def test_append_runtime_event_reports_helper_owned_database_connect_failure(
    tmp_path: Path,
) -> None:
    bad_db_path = tmp_path / "runtime-event-store-directory.db"
    bad_db_path.mkdir()
    db = Database(bad_db_path)

    result = _append_runtime_event(
        db,
        _record(event_id="runtime:test:bad-database-connect"),
    )

    assert result.ok is False
    assert result.status == "error"
    assert result.event_id == "runtime:test:bad-database-connect"
    assert result.error_code == "bad_connection"
    assert result.row_id is None


def test_append_runtime_event_does_not_close_caller_owned_connection(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        result = _append_runtime_event(conn, _record(event_id="runtime:test:open"))

        assert result.status == "inserted"
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()


def test_append_runtime_event_does_not_commit_caller_owned_transaction(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        conn.execute(
            "CREATE TABLE caller_owned_marker (id INTEGER PRIMARY KEY, value TEXT)"
        )
        conn.commit()
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO caller_owned_marker (id, value) VALUES (?, ?)",
            (1, "uncommitted"),
        )

        result = _append_runtime_event(
            conn,
            _record(event_id="runtime:test:caller-transaction"),
        )

        assert result.status == "inserted"
        assert conn.in_transaction is True
        conn.rollback()
        assert (
            conn.execute(
                "SELECT COUNT(*) AS count FROM caller_owned_marker"
            ).fetchone()["count"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) AS count FROM runtime_events WHERE event_id = ?",
                ("runtime:test:caller-transaction",),
            ).fetchone()["count"]
            == 0
        )
    finally:
        conn.close()


def test_append_runtime_event_rejects_invalid_metadata_json(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        result = _append_runtime_event(
            conn,
            _record(event_id="runtime:test:bad-metadata"),
            metadata={"bad": object()},
        )

        assert result.ok is False
        assert result.status == "invalid"
        assert result.error_code == "invalid_json"
        assert (
            conn.execute("SELECT COUNT(*) AS count FROM runtime_events").fetchone()[
                "count"
            ]
            == 0
        )
    finally:
        conn.close()


def test_append_runtime_event_preserves_large_inert_payload_json(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    payload = {
        f"k_{index:03d}": {"value": index, "label": f"item-{index}"}
        for index in range(80)
    }
    try:
        result = _append_runtime_event(
            conn,
            _record(event_id="runtime:test:large", payload=payload),
        )

        row = conn.execute(
            "SELECT payload_json FROM runtime_events WHERE event_id = ?",
            ("runtime:test:large",),
        ).fetchone()

        assert result.status == "inserted"
        assert row is not None
        assert row["payload_json"] == json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    finally:
        conn.close()
