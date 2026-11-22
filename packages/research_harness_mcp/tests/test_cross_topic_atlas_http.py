"""Focused HTTP tests for cross-topic atlas route extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


def test_cross_topic_atlas_module_imports_and_route_registered():
    from research_harness_mcp import cross_topic_atlas_http, http_api

    assert callable(cross_topic_atlas_http.register_cross_topic_atlas_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/cross-topic-atlas" and "GET" in route.methods
    ]
    assert len(matching_routes) == 1


def test_cross_topic_atlas_route_preserves_service_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness.service.types import ServiceResult
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "cross-topic-atlas-http.db"
    Database(db_path).migrate()
    captured: dict[str, object] = {}

    class FakeService:
        def __init__(self, *, db):
            captured["db_path"] = db

        def invoke(self, command_name: str, arguments: dict[str, Any]) -> ServiceResult:
            captured["command_name"] = command_name
            captured["arguments"] = arguments
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={
                    "schema_version": "cross_topic_knowledge_atlas.v1",
                    "topic_ids": list(arguments["topic_ids"]),
                    "query": arguments["query"],
                    "link_count": 0,
                    "links": [],
                    "warnings": [],
                },
            )

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "ResearchService", FakeService)
    try:
        response = TestClient(http_api.app).get(
            "/api/topics/cross-topic-atlas",
            params=[
                ("topic_id", "3"),
                ("topic_id", "3"),
                ("topic_id", "4"),
                ("query", "  provenance audit  "),
                ("max_results", "7"),
            ],
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert captured == {
        "db_path": db_path,
        "command_name": "cross_topic_atlas",
        "arguments": {
            "topic_ids": [3, 4],
            "query": "provenance audit",
            "max_results": 7,
        },
    }
    assert response.json()["topic_ids"] == [3, 4]
    assert response.json()["query"] == "provenance audit"


def test_cross_topic_atlas_route_invokes_service():
    from fastapi import FastAPI
    from research_harness.service.types import ServiceResult
    from research_harness_mcp import cross_topic_atlas_http

    calls: list[dict[str, Any]] = []
    app = FastAPI()

    def fake_invoke_service(
        command_name: str, arguments: dict[str, Any]
    ) -> ServiceResult:
        calls.append({"command_name": command_name, "arguments": arguments})
        return ServiceResult(
            command=command_name,
            status="success",
            summary="ok",
            output={
                "schema_version": "cross_topic_knowledge_atlas.v1",
                "topic_ids": list(arguments["topic_ids"]),
                "query": arguments["query"],
                "link_count": 0,
                "links": [],
                "warnings": [],
            },
        )

    cross_topic_atlas_http.register_cross_topic_atlas_routes(
        app,
        invoke_service=fake_invoke_service,
    )

    response = TestClient(app).get(
        "/api/topics/cross-topic-atlas",
        params=[
            ("topic_id", "3"),
            ("topic_id", "3"),
            ("topic_id", "4"),
            ("query", "  provenance audit  "),
            ("max_results", "7"),
        ],
    )

    assert response.status_code == 200, response.text
    assert calls == [
        {
            "command_name": "cross_topic_atlas",
            "arguments": {
                "topic_ids": [3, 4],
                "query": "provenance audit",
                "max_results": 7,
            },
        }
    ]
    assert response.json()["topic_ids"] == [3, 4]


def test_cross_topic_atlas_route_preserves_public_validation_errors():
    from research_harness_mcp import http_api

    client = TestClient(http_api.app)
    invalid_topic = client.get(
        "/api/topics/cross-topic-atlas",
        params=[("topic_id", "1"), ("topic_id", "not-an-int")],
    )
    duplicate_topic = client.get(
        "/api/topics/cross-topic-atlas",
        params=[("topic_id", "1"), ("topic_id", "1")],
    )
    invalid_max_results = client.get(
        "/api/topics/cross-topic-atlas",
        params=[("topic_id", "1"), ("topic_id", "2"), ("max_results", "21")],
    )

    assert invalid_topic.status_code == 400
    assert invalid_topic.headers["cache-control"] == "private, no-store"
    assert invalid_topic.json() == {
        "error": {
            "code": "invalid_topic_id",
            "message": "topic_id must be a positive integer",
        }
    }
    assert duplicate_topic.status_code == 400
    assert duplicate_topic.headers["cache-control"] == "private, no-store"
    assert duplicate_topic.json() == {
        "error": {
            "code": "invalid_topic_ids",
            "message": "at least two distinct topic ids are required",
        }
    }
    assert invalid_max_results.status_code == 400
    assert invalid_max_results.headers["cache-control"] == "private, no-store"
    assert invalid_max_results.json() == {
        "error": {
            "code": "invalid_max_results",
            "message": "max_results must be between 1 and 20",
        }
    }
