"""Focused HTTP tests for topic list route extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from research_harness.service import ServiceResult


def test_topic_list_module_imports_and_route_registered():
    from research_harness_mcp import http_api, topic_list_http

    assert callable(topic_list_http.register_topic_list_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics" and "GET" in route.methods
    ]
    assert len(matching_routes) == 1


def _seed_topic_list_db(db_path: Path) -> None:
    from research_harness.storage.db import Database

    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO domains (id, name, description) VALUES (?, ?, ?)",
            (7, "Systems", "Systems research"),
        )
        conn.execute(
            "INSERT INTO domains (id, name, description) VALUES (?, ?, ?)",
            (8, "Theory", "Theory research"),
        )
        conn.execute(
            """
            INSERT INTO topics
                (id, name, description, status, target_venue, deadline, created_at,
                 domain_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                42,
                "systems-topic",
                "Systems DB description",
                "active",
                "OSDI",
                "2026-09-01",
                "2026-06-05T10:00:00Z",
                7,
                43,
                "theory-topic",
                "Theory DB description",
                "paused",
                "FOCS",
                "2026-10-01",
                "2026-06-05T11:00:00Z",
                8,
            ),
        )
        conn.execute(
            "INSERT INTO papers (id, title, status) VALUES (?, ?, ?), (?, ?, ?)",
            (1, "Paper One", "meta_only", 2, "Paper Two", "meta_only"),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?), (?, ?)",
            (1, 42, 2, 42),
        )
        conn.execute(
            """
            INSERT INTO orchestrator_runs
                (topic_id, mode, current_stage, stage_status)
            VALUES (?, ?, ?, ?)
            """,
            (42, "standard", "analyze", "in_progress"),
        )
        conn.commit()


def test_topic_list_preserves_service_order_and_db_enrichment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-list-http.db"
    _seed_topic_list_db(db_path)
    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            calls.append((command_name, arguments))
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={
                    "topics": [
                        {"id": 43, "name": "service-theory", "status": "active"},
                        {
                            "id": 42,
                            "name": "service-systems",
                            "description": "Service description",
                            "status": "paused",
                        },
                        {"id": "not-an-int", "name": "skip"},
                    ]
                },
            )

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)
    try:
        response = TestClient(http_api.app).get("/api/topics")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert calls == [("topic_list", {})]
    assert response.json() == [
        {
            "id": 43,
            "name": "service-theory",
            "description": "Theory DB description",
            "status": "active",
            "target_venue": "FOCS",
            "deadline": "2026-10-01",
            "created_at": "2026-06-05T11:00:00Z",
            "paper_count": 0,
            "domain_id": 8,
            "domain_name": "Theory",
            "current_stage": None,
            "stage_status": None,
        },
        {
            "id": 42,
            "name": "service-systems",
            "description": "Service description",
            "status": "paused",
            "target_venue": "OSDI",
            "deadline": "2026-09-01",
            "created_at": "2026-06-05T10:00:00Z",
            "paper_count": 2,
            "domain_id": 7,
            "domain_name": "Systems",
            "current_stage": "analyze",
            "stage_status": "in_progress",
        },
    ]


def test_topic_list_domain_filter_preserves_service_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-list-http-domain.db"
    _seed_topic_list_db(db_path)
    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            calls.append((command_name, arguments))
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={"topics": [{"id": 42}, {"id": 43}]},
            )

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)
    try:
        response = TestClient(http_api.app).get("/api/topics?domain_id=7")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert calls == [("topic_list", {})]
    assert [topic["id"] for topic in response.json()] == [42]


def test_topic_list_invalid_service_payload_returns_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-list-http-invalid.db"
    _seed_topic_list_db(db_path)

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={"topics": "invalid"},
            )

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)
    try:
        response = TestClient(http_api.app).get("/api/topics")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 500
    assert response.json() == {
        "detail": "ResearchService topic_list returned an invalid payload"
    }
