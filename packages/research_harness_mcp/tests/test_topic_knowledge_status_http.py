"""Focused HTTP tests for topic knowledge-status route extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_topic_knowledge_status_module_imports_and_route_registered():
    from research_harness_mcp import http_api, topic_knowledge_status_http

    assert callable(topic_knowledge_status_http.register_topic_knowledge_status_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}/knowledge-status"
        and "GET" in route.methods
    ]
    assert len(matching_routes) == 1


def test_topic_knowledge_status_route_preserves_builder_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness.service import ServiceResult
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-knowledge-status-http.db"
    Database(db_path).migrate()
    captured: dict[str, object] = {}

    class FakeService:
        def __init__(self, db=None) -> None:
            captured["db_path"] = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            captured["command"] = name
            captured["arguments"] = dict(arguments)
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={
                    "schema_version": "knowledge_status.v1",
                    "topic_id": arguments["topic_id"],
                    "snapshot": {
                        "artifact_ref": "artifact:topic_knowledge_snapshot:test"
                    },
                    "wiki": {"page_count": 1},
                    "next_actions": ["review"],
                },
            )

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "ResearchService", FakeService)
    try:
        response = TestClient(http_api.app).get(
            "/api/topics/42/knowledge-status",
            headers={"Origin": "http://localhost:3000"},
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert captured == {
        "db_path": db_path,
        "command": "topic_knowledge_status",
        "arguments": {"topic_id": 42},
    }
    assert response.json()["topic_id"] == 42


def test_topic_knowledge_status_route_uses_research_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness.service import ServiceResult
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-knowledge-status-service.db"
    Database(db_path).migrate()
    calls: list[tuple[str, dict]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={
                    "schema_version": "knowledge_status.v1",
                    "topic_id": arguments["topic_id"],
                    "status": "ready",
                    "readiness_status": "ready",
                },
            )

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "ResearchService", FakeService)
    try:
        response = TestClient(http_api.app).get("/api/topics/42/knowledge-status")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json()["topic_id"] == 42
    assert calls == [("topic_knowledge_status", {"topic_id": 42})]


def test_topic_knowledge_status_route_preserves_public_errors(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-knowledge-status-errors.db"
    Database(db_path).migrate()
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        client = TestClient(http_api.app)
        invalid = client.get("/api/topics/not-an-int/knowledge-status")
        missing = client.get("/api/topics/1/knowledge-status")
    finally:
        http_api.DB_PATH = original_db_path

    assert invalid.status_code == 400
    assert invalid.headers["cache-control"] == "private, no-store"
    assert invalid.json() == {
        "error": {
            "code": "invalid_topic_id",
            "message": "topic_id must be a positive integer",
        }
    }
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "private, no-store"
    assert missing.json() == {
        "error": {
            "code": "knowledge_status_unavailable",
            "message": "knowledge status is unavailable for topic 1",
        }
    }
