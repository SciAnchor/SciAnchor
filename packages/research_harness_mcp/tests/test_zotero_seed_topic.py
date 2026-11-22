"""Focused tests for Zotero seed-topic helper extraction."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import HTTPException


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE topics (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT,
            created_at TEXT
        );
        """
    )
    return conn


def _conn_context(conn: sqlite3.Connection):
    @contextmanager
    def _ctx():
        yield conn

    return _ctx


class _MissingTopicError(Exception):
    pass


def _missing_topic_error(topic_id: int) -> _MissingTopicError:
    return _MissingTopicError(f"Topic {topic_id} not found")


def test_zotero_seed_topic_helper_reuses_existing_topic_id_without_side_effects():
    from research_harness_mcp import zotero_seed_topic

    conn = _conn()
    calls: dict[str, list[Any]] = {"materialize": [], "tool": []}
    conn.execute(
        "INSERT INTO topics (id, name, description) VALUES (7, 'Existing', 'old')"
    )

    try:
        assert zotero_seed_topic.get_or_create_zotero_seed_topic(
            topic_id=7,
            topic_name="Ignored",
            description="new",
            get_db_context=_conn_context(conn),
            materialize_topic_workspace=lambda **kwargs: calls["materialize"].append(
                kwargs
            ),
            run_tool=lambda name, arguments: calls["tool"].append((name, arguments)),
            now_iso=lambda: "2026-06-14T00:00:00+00:00",
            missing_topic_error=_missing_topic_error,
        ) == (7, False)

        with pytest.raises(_MissingTopicError, match="Topic 99 not found"):
            zotero_seed_topic.get_or_create_zotero_seed_topic(
                topic_id=99,
                topic_name="Missing",
                description="new",
                get_db_context=_conn_context(conn),
                materialize_topic_workspace=lambda **kwargs: calls[
                    "materialize"
                ].append(kwargs),
                run_tool=lambda name, arguments: calls["tool"].append(
                    (name, arguments)
                ),
                now_iso=lambda: "2026-06-14T00:00:00+00:00",
                missing_topic_error=_missing_topic_error,
            )

        assert calls == {"materialize": [], "tool": []}
    finally:
        conn.close()


def test_zotero_seed_topic_helper_reuses_existing_topic_name_first_id():
    from research_harness_mcp import zotero_seed_topic

    conn = _conn()
    conn.executemany(
        "INSERT INTO topics (id, name, description) VALUES (?, ?, ?)",
        [(3, "Seed Topic", "newer"), (1, "Seed Topic", "older")],
    )

    try:
        assert zotero_seed_topic.get_or_create_zotero_seed_topic(
            topic_id=None,
            topic_name=" Seed Topic ",
            description="ignored",
            get_db_context=_conn_context(conn),
            materialize_topic_workspace=lambda **_kwargs: None,
            run_tool=lambda _name, _arguments: None,
            now_iso=lambda: "2026-06-14T00:00:00+00:00",
            missing_topic_error=_missing_topic_error,
        ) == (1, False)
    finally:
        conn.close()


def test_zotero_seed_topic_helper_creates_topic_and_bootstraps_workspace():
    from research_harness_mcp import zotero_seed_topic

    conn = _conn()
    calls: dict[str, list[Any]] = {"materialize": [], "tool": []}

    try:
        assert zotero_seed_topic.get_or_create_zotero_seed_topic(
            topic_id=None,
            topic_name=" New Seed Topic ",
            description="Initial query: agents",
            get_db_context=_conn_context(conn),
            materialize_topic_workspace=lambda **kwargs: calls["materialize"].append(
                kwargs
            ),
            run_tool=lambda name, arguments: calls["tool"].append(
                (name, dict(arguments))
            ),
            now_iso=lambda: "2026-06-14T00:00:00+00:00",
            missing_topic_error=_missing_topic_error,
        ) == (1, True)

        row = conn.execute(
            "SELECT name, description, status, created_at FROM topics WHERE id = 1"
        ).fetchone()
        assert dict(row) == {
            "name": "New Seed Topic",
            "description": "Initial query: agents",
            "status": "active",
            "created_at": "2026-06-14T00:00:00+00:00",
        }
        assert calls["materialize"] == [
            {
                "topic_id": 1,
                "topic_name": "New Seed Topic",
                "description": "Initial query: agents",
            }
        ]
        assert calls["tool"] == [("orchestrator_resume", {"topic_id": 1})]
    finally:
        conn.close()


def test_zotero_seed_topic_helper_preserves_bootstrap_error_handling():
    from research_harness_mcp import zotero_seed_topic

    class _BootstrapHttpError(Exception):
        pass

    conn = _conn()
    warnings: list[tuple[str, dict[str, Any]]] = []

    try:
        with pytest.raises(_BootstrapHttpError):
            zotero_seed_topic.get_or_create_zotero_seed_topic(
                topic_id=None,
                topic_name="Propagate",
                description="desc",
                get_db_context=_conn_context(conn),
                materialize_topic_workspace=lambda **_kwargs: None,
                run_tool=lambda _name, _arguments: (_ for _ in ()).throw(
                    _BootstrapHttpError("propagate")
                ),
                now_iso=lambda: "2026-06-14T00:00:00+00:00",
                missing_topic_error=_missing_topic_error,
                bootstrap_exception_types=(_BootstrapHttpError,),
                log_warning=lambda message, **kwargs: warnings.append(
                    (message, kwargs)
                ),
            )

        assert zotero_seed_topic.get_or_create_zotero_seed_topic(
            topic_id=None,
            topic_name="Swallow",
            description="desc",
            get_db_context=_conn_context(conn),
            materialize_topic_workspace=lambda **_kwargs: None,
            run_tool=lambda _name, _arguments: (_ for _ in ()).throw(
                RuntimeError("transient")
            ),
            now_iso=lambda: "2026-06-14T00:00:00+00:00",
            missing_topic_error=_missing_topic_error,
            bootstrap_exception_types=(_BootstrapHttpError,),
            log_warning=lambda message, **kwargs: warnings.append((message, kwargs)),
        ) == (2, True)

        assert warnings == [
            ("Failed to bootstrap Zotero seed topic", {"exc_info": True})
        ]
    finally:
        conn.close()


def test_http_api_zotero_seed_topic_wrapper_uses_dynamic_dependencies(monkeypatch):
    from research_harness_mcp import http_api

    conn = _conn()
    calls: dict[str, list[Any]] = {"materialize": [], "tool": []}

    @contextmanager
    def fake_get_db():
        yield conn

    try:
        monkeypatch.setattr(http_api, "get_db", fake_get_db)
        monkeypatch.setattr(
            http_api,
            "_materialize_topic_workspace_http",
            lambda **kwargs: calls["materialize"].append(kwargs),
        )
        monkeypatch.setattr(
            http_api,
            "_run_tool",
            lambda name, arguments: calls["tool"].append((name, dict(arguments))),
        )
        monkeypatch.setattr(http_api, "_now_iso", lambda: "2026-06-14T00:00:00+00:00")

        assert http_api._get_or_create_zotero_seed_topic(
            topic_id=None,
            topic_name=" Wrapped Topic ",
            description="desc",
        ) == (1, True)
        assert calls["materialize"] == [
            {"topic_id": 1, "topic_name": "Wrapped Topic", "description": "desc"}
        ]
        assert calls["tool"] == [("orchestrator_resume", {"topic_id": 1})]

        with pytest.raises(HTTPException) as exc_info:
            http_api._get_or_create_zotero_seed_topic(
                topic_id=404,
                topic_name="Missing",
                description="desc",
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Topic 404 not found"
    finally:
        conn.close()
