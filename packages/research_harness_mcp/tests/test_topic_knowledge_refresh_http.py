"""Focused HTTP tests for topic knowledge refresh route extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_topic_knowledge_refresh_module_imports_and_routes_registered():
    from research_harness_mcp import http_api, topic_knowledge_refresh_http

    assert callable(
        topic_knowledge_refresh_http.register_topic_knowledge_refresh_routes
    )
    refresh_all_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/knowledge-refresh-all" and "POST" in route.methods
    ]
    refresh_topic_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}/knowledge-refresh"
        and "POST" in route.methods
    ]
    assert len(refresh_all_routes) == 1
    assert len(refresh_topic_routes) == 1


def test_topic_knowledge_refresh_routes_keep_literal_route_order():
    from research_harness_mcp import http_api

    post_paths = [
        route.path
        for route in http_api.app.routes
        if "POST" in getattr(route, "methods", set())
    ]
    assert post_paths.index("/api/topics/knowledge-refresh-all") < post_paths.index(
        "/api/topics/{topic_id}/knowledge-refresh"
    )


def test_topic_knowledge_refresh_route_uses_research_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness.service import ServiceResult
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-knowledge-refresh-service.db"
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
                    "topic_id": arguments["topic_id"],
                    "status": "refreshed",
                    "artifact_id": 11,
                },
            )

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "ResearchService", FakeService)
    try:
        response = TestClient(http_api.app).post("/api/topics/42/knowledge-refresh")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "refreshed"
    assert calls == [("topic_knowledge_refresh", {"topic_id": 42})]
