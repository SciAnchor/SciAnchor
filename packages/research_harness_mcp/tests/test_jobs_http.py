"""Focused HTTP tests for async job polling route extraction."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_jobs_module_imports_and_route_registered():
    from research_harness_mcp import http_api, jobs_http

    assert callable(jobs_http.register_job_routes)
    assert any(
        route.path == "/api/jobs/{job_id}" and "GET" in route.methods
        for route in http_api.app.routes
    )


def test_get_job_parses_result_and_input_params(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "jobs.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO domains (id, name) VALUES (?, ?)", (7, "Systems"))
        cur = conn.execute(
            """
            INSERT INTO async_jobs (job_type, domain_id, status, input_params, result)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "topic_candidates",
                7,
                "completed",
                json.dumps({"tier": "standard", "max_candidates": 3}),
                json.dumps({"candidates": [{"name": "Direction 1"}]}),
            ),
        )
        job_id = cur.lastrowid
        conn.commit()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get(f"/api/jobs/{job_id}")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] == job_id
    assert payload["job_type"] == "topic_candidates"
    assert payload["domain_id"] == 7
    assert payload["status"] == "completed"
    assert payload["input_params"] == {"tier": "standard", "max_candidates": 3}
    assert payload["result"] == {"candidates": [{"name": "Direction 1"}]}


def test_get_job_returns_404_for_unknown_job(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "jobs-404.db"
    Database(db_path).migrate()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get("/api/jobs/999")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}
