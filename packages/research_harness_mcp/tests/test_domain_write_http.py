"""Focused HTTP tests for domain write route extraction."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_domain_write_module_imports_and_routes_registered():
    from research_harness_mcp import domain_write_http, http_api

    assert callable(domain_write_http.register_domain_write_routes)
    post_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/domains" and "POST" in route.methods
    ]
    patch_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/domains/{domain_id}" and "PATCH" in route.methods
    ]
    assert len(post_routes) == 1
    assert len(patch_routes) == 1


def _seed_domain_write_db(db_path: Path) -> None:
    from research_harness.storage.db import Database

    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO domains (id, name, description, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (7, "Systems", "Systems research", "active", "2026-06-05T10:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO topics (id, name, description, status, domain_id)
            VALUES (?, ?, ?, ?, ?), (?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()


def test_domain_create_preserves_payload_defaults_and_persistence(tmp_path: Path):
    from research_harness_mcp import http_api

    db_path = tmp_path / "domain-write-create-http.db"
    _seed_domain_write_db(db_path)
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).post(
            "/api/domains",
            json={"name": "Security", "description": "Security research"},
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] > 7
    assert payload["name"] == "Security"
    assert payload["description"] == "Security research"
    assert payload["status"] == "active"
    assert payload["topic_count"] == 0
    assert payload["created_at"]


def test_domain_patch_preserves_partial_update_count_and_defaults(tmp_path: Path):
    from research_harness_mcp import http_api

    db_path = tmp_path / "domain-write-patch-http.db"
    _seed_domain_write_db(db_path)
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).patch(
            "/api/domains/7",
            json={"description": None, "status": "paused"},
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": 7,
        "name": "Systems",
        "description": "",
        "status": "paused",
        "topic_count": 2,
        "created_at": "2026-06-05T10:00:00Z",
    }


def test_domain_patch_preserves_empty_body_and_missing_domain_errors(
    tmp_path: Path,
):
    from research_harness_mcp import http_api

    db_path = tmp_path / "domain-write-errors-http.db"
    _seed_domain_write_db(db_path)
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        client = TestClient(http_api.app)
        empty = client.patch("/api/domains/7", json={})
        missing = client.patch("/api/domains/999999", json={"name": "Missing"})
    finally:
        http_api.DB_PATH = original_db_path

    assert empty.status_code == 400
    assert empty.json() == {"detail": "No fields to update"}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Domain 999999 not found"}


def test_domain_write_keeps_adjacent_domain_route_order(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "domain-write-route-order.db"
    Database(db_path).migrate()
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        client = TestClient(http_api.app)
        list_response = client.get("/api/domains")
        trends_response = client.get("/api/domains/trends")
        detail_response = client.get("/api/domains/999999")
    finally:
        http_api.DB_PATH = original_db_path

    assert list_response.status_code == 200, list_response.text
    assert trends_response.status_code == 200, trends_response.text
    assert detail_response.status_code == 404
