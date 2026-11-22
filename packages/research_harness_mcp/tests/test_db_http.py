from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def test_open_http_db_configures_sqlite_connection(tmp_path: Path):
    from research_harness_mcp import db_http

    db_path = tmp_path / "http.db"

    with db_http.open_http_db(db_path) as conn:
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))")
        row = conn.execute("SELECT 42 AS answer").fetchone()

        assert isinstance(row, sqlite3.Row)
        assert row["answer"] == 42
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO child(parent_id) VALUES (99)")

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_http_api_get_db_preserves_dynamic_db_path_wrapper(
    tmp_path: Path,
    monkeypatch,
):
    from research_harness_mcp import http_api

    db_path = tmp_path / "wrapper.db"
    monkeypatch.setattr(http_api, "DB_PATH", db_path)

    with http_api.get_db() as conn:
        conn.execute("CREATE TABLE sample (value TEXT)")
        conn.execute("INSERT INTO sample(value) VALUES ('ok')")
        conn.commit()
        row = conn.execute("SELECT value FROM sample").fetchone()

    assert db_path.exists()
    assert isinstance(row, sqlite3.Row)
    assert row["value"] == "ok"
