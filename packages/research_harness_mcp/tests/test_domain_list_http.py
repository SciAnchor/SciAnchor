"""Focused HTTP tests for domain list route extraction."""

from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient


def test_domain_list_module_imports_and_route_registered():
    from research_harness_mcp import domain_list_http, http_api

    assert callable(domain_list_http.register_domain_list_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/domains" and "GET" in route.methods
    ]
    assert len(matching_routes) == 1


def _seed_domain_list_db(db_path: Path) -> None:
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
                None,
                None,
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO topics (id, name, description, status, domain_id)
            VALUES (?, ?, ?, ?, ?), (?, ?, ?, ?, ?), (?, ?, ?, ?, ?)
            """,
            (
                42,
                "systems-topic-one",
                "",
                "active",
                7,
                43,
                "systems-topic-two",
                "",
                "active",
                7,
                44,
                "theory-topic",
                "",
                "active",
                8,
            ),
        )
        conn.commit()


def test_domain_list_preserves_sql_ordering_counts_and_defaults(
    tmp_path: Path,
):
    from research_harness_mcp import http_api

    db_path = tmp_path / "domain-list-http.db"
    _seed_domain_list_db(db_path)
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get("/api/domains")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "id": 7,
            "name": "Systems",
            "description": "Systems research",
            "status": "active",
            "topic_count": 2,
            "created_at": "2026-06-05T10:00:00Z",
        },
        {
            "id": 8,
            "name": "Theory",
            "description": "",
            "status": "active",
            "topic_count": 1,
            "created_at": "",
        },
    ]


def test_domain_list_keeps_literal_domain_routes_before_domain_id(
    tmp_path: Path,
):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "domain-list-route-order.db"
    Database(db_path).migrate()
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        client = TestClient(http_api.app)
        trends = client.get("/api/domains/trends")
        missing_domain = client.get("/api/domains/999999")
    finally:
        http_api.DB_PATH = original_db_path

    assert trends.status_code == 200, trends.text
    assert isinstance(trends.json(), list)
    assert missing_domain.status_code == 404
