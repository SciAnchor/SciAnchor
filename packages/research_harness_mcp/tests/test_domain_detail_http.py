"""Focused HTTP tests for domain detail route extraction."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_domain_detail_module_imports_and_route_registered():
    from research_harness_mcp import domain_detail_http, http_api

    assert callable(domain_detail_http.register_domain_detail_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/domains/{domain_id}" and "GET" in route.methods
    ]
    assert len(matching_routes) == 1


def _seed_domain_detail_db(db_path: Path) -> None:
    from research_harness.storage.db import Database

    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO domains (id, name, description, status, created_at)
            VALUES (?, ?, ?, ?, ?), (?, ?, ?, ?, ?)
            """,
            (
                7,
                "Systems",
                "Systems research",
                "active",
                "2026-06-05T10:00:00Z",
                8,
                "Theory",
                "Theory research",
                "active",
                "2026-06-05T11:00:00Z",
            ),
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
                "Systems topic description",
                "active",
                "OSDI",
                "2026-09-01",
                "2026-06-06T10:00:00Z",
                7,
                43,
                "systems-topic-empty-fields",
                None,
                None,
                None,
                None,
                None,
                7,
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
        conn.commit()


def test_domain_detail_preserves_payload_shape_counts_and_defaults(tmp_path: Path):
    from research_harness_mcp import http_api

    db_path = tmp_path / "domain-detail-http.db"
    _seed_domain_detail_db(db_path)
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get("/api/domains/7")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": 7,
        "name": "Systems",
        "description": "Systems research",
        "status": "active",
        "created_at": "2026-06-05T10:00:00Z",
        "topics": [
            {
                "id": 42,
                "name": "systems-topic",
                "description": "Systems topic description",
                "status": "active",
                "target_venue": "OSDI",
                "deadline": "2026-09-01",
                "created_at": "2026-06-06T10:00:00Z",
                "paper_count": 2,
                "domain_id": 7,
                "domain_name": "Systems",
                "current_stage": None,
                "stage_status": None,
            },
            {
                "id": 43,
                "name": "systems-topic-empty-fields",
                "description": "",
                "status": "active",
                "target_venue": "",
                "deadline": "",
                "created_at": "",
                "paper_count": 0,
                "domain_id": 7,
                "domain_name": "Systems",
                "current_stage": None,
                "stage_status": None,
            },
        ],
    }


def test_domain_detail_preserves_missing_domain_error_and_route_order(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "domain-detail-route-order.db"
    Database(db_path).migrate()
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        client = TestClient(http_api.app)
        trends = client.get("/api/domains/trends")
        missing = client.get("/api/domains/999999")
    finally:
        http_api.DB_PATH = original_db_path

    assert trends.status_code == 200, trends.text
    assert isinstance(trends.json(), list)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Domain 999999 not found"}
