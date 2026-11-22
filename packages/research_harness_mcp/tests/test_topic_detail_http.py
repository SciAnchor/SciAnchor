"""Focused HTTP tests for topic detail route extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from research_harness.service import ServiceResult


def test_topic_detail_module_imports_and_route_registered():
    from research_harness_mcp import http_api, topic_detail_http

    assert callable(topic_detail_http.register_topic_detail_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}" and "GET" in route.methods
    ]
    assert len(matching_routes) == 1


def test_topic_detail_shape_and_service_calls_are_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-detail-http.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO domains (id, name, description, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (7, "Systems", "Systems research", "active", "2026-06-05T08:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO topics
                (id, name, description, status, target_venue, deadline, created_at,
                 domain_id, contributions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                42,
                "db-topic",
                "DB topic detail",
                "active",
                "OSDI",
                "2026-09-01",
                "2026-06-05T10:00:00Z",
                7,
                "human: review",
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
            INSERT INTO paper_annotations
                (paper_id, section, content, source, confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "method",
                '{"note":"strong"}',
                "manual",
                0.9,
                "2026-06-04T09:00:00Z",
                "2026-06-04T09:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO orchestrator_runs
                (topic_id, mode, current_stage, stage_status, gate_status,
                 blocking_issue_count, unresolved_issue_count, stop_before,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                42,
                "standard",
                "db-stage",
                "db-status",
                "needs_review",
                2,
                3,
                "write",
                "2026-06-05T10:10:00Z",
                "2026-06-05T10:20:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (topic_id, stage, artifact_type, status, version, title,
                 payload_json, metadata_json, created_at, updated_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                42,
                "analyze",
                "evidence_pack",
                "active",
                1,
                "Evidence",
                "{}",
                "{}",
                "2026-06-05T10:30:00Z",
                "2026-06-05T10:30:00Z",
                42,
                "write",
                "draft_pack",
                "active",
                1,
                "Draft",
                "{}",
                "{}",
                "2026-06-05T10:40:00Z",
                "2026-06-05T10:40:00Z",
            ),
        )
        conn.commit()

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            calls.append((command_name, arguments))
            if command_name == "topic_show":
                return ServiceResult(
                    command=command_name,
                    status="success",
                    summary="ok",
                    output={
                        "name": "service-topic",
                        "description": "Service topic detail",
                        "status": "paused",
                    },
                )
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={
                    "run": {
                        "current_stage": "service-stage",
                        "stage_status": "service-status",
                        "mode": "service-mode",
                        "blocking_issue_count": 9,
                        "unresolved_issue_count": 8,
                    }
                },
            )

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)
    try:
        response = TestClient(http_api.app).get("/api/topics/42")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert calls == [
        ("topic_show", {"name": "db-topic"}),
        ("orchestrator_status", {"topic_id": 42}),
    ]
    assert response.json() == {
        "id": 42,
        "name": "service-topic",
        "description": "Service topic detail",
        "status": "paused",
        "target_venue": "OSDI",
        "deadline": "2026-09-01",
        "created_at": "2026-06-05T10:00:00Z",
        "paper_count": 2,
        "annotation_count": 1,
        "domain_id": 7,
        "domain_name": "Systems",
        "current_stage": "service-stage",
        "stage_status": "service-status",
        "gate_status": "needs_review",
        "contributions": "human: review",
        "mode": "service-mode",
        "stop_before": "write",
        "blocking_issue_count": 9,
        "unresolved_issue_count": 8,
        "artifact_counts": {"analyze": 1, "write": 1},
    }


def test_topic_detail_returns_404_for_unknown_topic(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-detail-http-404.db"
    Database(db_path).migrate()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get("/api/topics/999")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 404
    assert response.json() == {"detail": "Topic 999 not found"}
