from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from research_harness._core.storage.db import Database
from research_harness.runtime.event_normalizer import RuntimeEventRecord
from research_harness.runtime.event_store import (
    _append_runtime_event,
    _read_runtime_event_by_event_id,
    _read_runtime_events,
)


def _migrated_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "runtime-event-readback.db")
    db.migrate()
    return db


def _record(**overrides: object) -> RuntimeEventRecord:
    record = RuntimeEventRecord(
        event_id="runtime:readback:1",
        trace_id="trace-readback",
        event_type="tool.completed",
        created_at="2026-06-09T17:58:00Z",
        origin_surface="test",
        actor="codex",
        topic_id=1,
        job_id="job-readback",
        tool_name="readback_tool",
        artifact_refs=("artifacts:readback",),
        payload={"result": {"ok": True}, "count": 2},
    )
    return replace(record, **overrides)


def test_read_runtime_event_by_event_id_round_trips_writer_record(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'runtime')")
        write_result = _append_runtime_event(
            conn,
            _record(),
            metadata={"source": "writer-test", "order": 1},
        )

        stored = _read_runtime_event_by_event_id(conn, "runtime:readback:1")

        assert write_result.status == "inserted"
        assert stored is not None
        assert stored.row_id == write_result.row_id
        assert stored.record == _record()
        assert stored.metadata == {"order": 1, "source": "writer-test"}
    finally:
        conn.close()


def test_read_runtime_events_filters_by_trace_job_and_topic(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'runtime one')")
        conn.execute("INSERT INTO topics (id, name) VALUES (2, 'runtime two')")
        records = (
            _record(event_id="runtime:readback:a", trace_id="trace-a", job_id="job-a"),
            _record(event_id="runtime:readback:b", trace_id="trace-a", job_id="job-b"),
            _record(event_id="runtime:readback:c", trace_id="trace-c", topic_id=2),
        )
        for record in records:
            result = _append_runtime_event(conn, record)
            assert result.status == "inserted"

        by_trace = _read_runtime_events(conn, trace_id="trace-a")
        by_job = _read_runtime_events(conn, job_id="job-b")
        by_topic = _read_runtime_events(conn, topic_id=2)

        assert [stored.record.event_id for stored in by_trace] == [
            "runtime:readback:a",
            "runtime:readback:b",
        ]
        assert [stored.record.event_id for stored in by_job] == ["runtime:readback:b"]
        assert [stored.record.event_id for stored in by_topic] == ["runtime:readback:c"]
    finally:
        conn.close()


def test_read_runtime_events_returns_empty_tuple_for_missing_filters(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)

    assert _read_runtime_event_by_event_id(db, "runtime:missing") is None
    assert _read_runtime_events(db, trace_id="trace-missing") == ()


def test_read_runtime_event_by_event_id_returns_none_on_database_connect_failure(
    tmp_path: Path,
) -> None:
    bad_db_path = tmp_path / "runtime-event-readback-directory.db"
    bad_db_path.mkdir()
    db = Database(bad_db_path)

    assert _read_runtime_event_by_event_id(db, "runtime:readback:missing") is None


def test_read_runtime_events_returns_empty_tuple_on_database_connect_failure(
    tmp_path: Path,
) -> None:
    bad_db_path = tmp_path / "runtime-event-readback-directory.db"
    bad_db_path.mkdir()
    db = Database(bad_db_path)

    assert _read_runtime_events(db, trace_id="trace-readback") == ()


def test_readback_helper_is_not_public_runtime_export() -> None:
    import research_harness.runtime as runtime

    assert "_read_runtime_event_by_event_id" not in runtime.__all__
    assert "_read_runtime_events" not in runtime.__all__
