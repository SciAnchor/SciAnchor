"""Focused HTTP tests for topic candidate job route extraction."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_topic_candidates_module_imports_and_route_registered():
    from research_harness_mcp import http_api, topic_candidates_http

    assert callable(topic_candidates_http.register_topic_candidate_routes)
    assert any(
        route.path == "/api/domains/{domain_id}/topic-candidates"
        and "POST" in route.methods
        for route in http_api.app.routes
    )


def test_create_topic_candidates_job_persists_completed_async_job(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-candidates-http.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO domains (id, name) VALUES (?, ?)", (7, "Systems"))
        conn.commit()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).post(
            "/api/domains/7/topic-candidates",
            json={"tier": "premium", "max_candidates": 8},
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "completed"
    assert isinstance(payload["job_id"], int)

    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM async_jobs WHERE id = ?", (payload["job_id"],)
        ).fetchone()

    assert row is not None
    assert row["job_type"] == "topic_candidates"
    assert row["domain_id"] == 7
    assert row["status"] == "completed"
    assert json.loads(row["input_params"]) == {
        "tier": "premium",
        "max_candidates": 8,
    }
    result = json.loads(row["result"])
    assert result == {
        "candidates": [
            {
                "name": f"Systems — Direction {index}",
                "description": f"Exploring aspect {index} of Systems",
                "rationale": "Generated from domain scope analysis",
            }
            for index in range(1, 6)
        ]
    }


def test_create_topic_candidates_job_returns_404_for_unknown_domain(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-candidates-http-404.db"
    Database(db_path).migrate()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).post(
            "/api/domains/999/topic-candidates",
            json={"tier": "standard", "max_candidates": 5},
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 404
    assert response.json() == {"detail": "Domain not found"}
