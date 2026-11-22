"""Focused HTTP tests for topic create/update route extraction."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class _CreateTopicRequest(BaseModel):
    name: str
    description: str = ""
    target_venue: str = ""
    deadline: str = ""
    domain_id: int | None = None


class _PatchTopicRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    domain_id: int | None = Field(
        default=None, description="Pass null via JSON to unset"
    )
    target_venue: str | None = None
    deadline: str | None = None
    status: str | None = None

    model_config = {"extra": "forbid"}


def test_topic_write_module_imports_and_routes_registered():
    from research_harness_mcp import http_api, topic_write_http

    assert callable(topic_write_http.register_topic_write_routes)

    def route_index(path: str, method: str) -> int:
        for index, route in enumerate(http_api.app.routes):
            if route.path == path and method in route.methods:
                return index
        raise AssertionError(f"route not registered: {method} {path}")

    assert (
        route_index("/api/topics/{topic_id}", "GET")
        < route_index("/api/topics", "POST")
        < route_index("/api/topics/{topic_id}", "PATCH")
        < route_index("/api/topics/{topic_id}/intake-profile", "GET")
    )


def _create_topic_schema(db_path: Path) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE domains (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute(
            """
            CREATE TABLE topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                status TEXT,
                target_venue TEXT,
                deadline TEXT,
                domain_id INTEGER,
                created_at TEXT
            )
            """
        )
        conn.execute("CREATE TABLE paper_topics (paper_id INTEGER, topic_id INTEGER)")
        conn.commit()


def _build_topic_write_client(
    db_path: Path,
) -> tuple[TestClient, list[dict[str, Any]], list[tuple[str, dict[str, Any]]]]:
    from research_harness_mcp import topic_write_http

    workspace_calls: list[dict[str, Any]] = []
    tool_calls: list[tuple[str, dict[str, Any]]] = []

    @contextmanager
    def get_db_context():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def materialize_topic_workspace(**kwargs: Any) -> str:
        workspace_calls.append(kwargs)
        return f"/tmp/topic-{kwargs['topic_id']}"

    def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append((name, arguments))
        return {"status": "resumed", "arguments": arguments}

    app = FastAPI()
    topic_write_http.register_topic_write_routes(
        app,
        create_topic_request_model=_CreateTopicRequest,
        patch_topic_request_model=_PatchTopicRequest,
        get_db_context=get_db_context,
        materialize_topic_workspace=materialize_topic_workspace,
        run_tool=run_tool,
        row_to_dict=dict,
        now_iso=lambda: "2026-06-13T10:12:00Z",
    )
    return TestClient(app), workspace_calls, tool_calls


def test_topic_create_preserves_domain_workspace_orchestrator_and_response(
    tmp_path: Path,
):
    db_path = tmp_path / "topic-create.db"
    _create_topic_schema(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO domains (id, name) VALUES (?, ?)", (5, "ML"))
        conn.commit()
    client, workspace_calls, tool_calls = _build_topic_write_client(db_path)

    response = client.post(
        "/api/topics",
        json={
            "name": "New Topic",
            "description": "A test topic",
            "target_venue": "ICLR",
            "deadline": "2026-07-01",
            "domain_id": 5,
        },
    )

    assert response.status_code == 200, response.text
    assert workspace_calls == [
        {
            "topic_id": 1,
            "topic_name": "New Topic",
            "description": "A test topic",
            "target_venue": "ICLR",
            "deadline": "2026-07-01",
            "domain_name": "ML",
        }
    ]
    assert tool_calls == [("orchestrator_resume", {"topic_id": 1})]
    assert response.json() == {
        "id": 1,
        "name": "New Topic",
        "description": "A test topic",
        "status": "active",
        "target_venue": "ICLR",
        "deadline": "2026-07-01",
        "domain_id": 5,
        "created_at": "2026-06-13T10:12:00Z",
        "domain_name": "ML",
        "orchestrator": {"status": "resumed", "arguments": {"topic_id": 1}},
        "workspace_path": "/tmp/topic-1",
    }


def test_topic_create_preserves_missing_domain_error(tmp_path: Path):
    db_path = tmp_path / "topic-create-missing-domain.db"
    _create_topic_schema(db_path)
    client, workspace_calls, tool_calls = _build_topic_write_client(db_path)

    response = client.post("/api/topics", json={"name": "Topic", "domain_id": 99})

    assert response.status_code == 404
    assert response.json() == {"detail": "Domain 99 not found"}
    assert workspace_calls == []
    assert tool_calls == []


def test_topic_patch_preserves_explicit_domain_clear_and_paper_count(
    tmp_path: Path,
):
    db_path = tmp_path / "topic-patch.db"
    _create_topic_schema(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("INSERT INTO domains (id, name) VALUES (?, ?)", (5, "ML"))
        conn.execute(
            """
            INSERT INTO topics
                (id, name, description, status, target_venue, deadline, domain_id,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (42, "Old", "Old desc", "active", "ICLR", "2026-07-01", 5, "created"),
        )
        conn.executemany(
            "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
            [(1, 42), (2, 42)],
        )
        conn.commit()
    client, _workspace_calls, _tool_calls = _build_topic_write_client(db_path)

    response = client.patch(
        "/api/topics/42",
        json={"name": "New", "domain_id": None, "status": "paused"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": 42,
        "name": "New",
        "description": "Old desc",
        "status": "paused",
        "target_venue": "ICLR",
        "deadline": "2026-07-01",
        "domain_id": None,
        "created_at": "created",
        "domain_name": None,
        "paper_count": 2,
    }


def test_topic_patch_preserves_empty_missing_topic_and_missing_domain_errors(
    tmp_path: Path,
):
    db_path = tmp_path / "topic-patch-errors.db"
    _create_topic_schema(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO topics
                (id, name, description, status, target_venue, deadline, domain_id,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (42, "Old", "Old desc", "active", "ICLR", "2026-07-01", None, "created"),
        )
        conn.commit()
    client, _workspace_calls, _tool_calls = _build_topic_write_client(db_path)

    empty = client.patch("/api/topics/42", json={})
    missing_topic = client.patch("/api/topics/99", json={"name": "New"})
    missing_domain = client.patch("/api/topics/42", json={"domain_id": 77})

    assert empty.status_code == 400
    assert empty.json() == {"detail": "No fields to update"}
    assert missing_topic.status_code == 404
    assert missing_topic.json() == {"detail": "Topic 99 not found"}
    assert missing_domain.status_code == 404
    assert missing_domain.json() == {"detail": "Domain 77 not found"}
