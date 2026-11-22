"""Focused HTTP tests for topic force-advance route extraction."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_topic_force_advance_module_imports_and_route_registered():
    from research_harness_mcp import http_api, topic_force_advance_http

    assert callable(topic_force_advance_http.register_topic_force_advance_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}/force-advance"
        and "POST" in route.methods
    ]
    assert len(matching_routes) == 1

    paths = [route.path for route in http_api.app.routes]
    assert paths.index("/api/topics/{topic_id}/artifacts") < paths.index(
        "/api/topics/{topic_id}/force-advance"
    )
    assert paths.index("/api/topics/{topic_id}/force-advance") < paths.index(
        "/api/topics/{topic_id}/primitives"
    )


def _seed_force_advance_run(db_path: Path, *, current_stage: str) -> None:
    from research_harness.storage.db import Database

    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (42, "force"))
        conn.execute(
            """
            INSERT INTO orchestrator_runs
                (id, topic_id, mode, current_stage, stage_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                7,
                42,
                "standard",
                current_stage,
                "blocked",
                "2026-06-13T09:00:00Z",
                "2026-06-13T09:00:00Z",
            ),
        )
        conn.commit()


def test_topic_force_advance_preserves_default_next_stage_and_persistence(
    tmp_path: Path,
):
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-force-advance-default.db"
    _seed_force_advance_run(db_path, current_stage="build")
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).post(
            "/api/topics/42/force-advance",
            json={},
        )
        with http_api.get_db() as conn:
            row = conn.execute(
                "SELECT current_stage, stage_status FROM orchestrator_runs WHERE id = ?",
                (7,),
            ).fetchone()
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "topic_id": 42,
        "previous_stage": "build",
        "current_stage": "analyze",
    }
    assert dict(row) == {"current_stage": "analyze", "stage_status": "in_progress"}


def test_topic_force_advance_preserves_explicit_target_stage(tmp_path: Path):
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-force-advance-target.db"
    _seed_force_advance_run(db_path, current_stage="analyze")
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).post(
            "/api/topics/42/force-advance",
            json={"target_stage": "write", "actor": "release-ui"},
        )
        with http_api.get_db() as conn:
            current_stage = conn.execute(
                "SELECT current_stage FROM orchestrator_runs WHERE id = ?",
                (7,),
            ).fetchone()["current_stage"]
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "topic_id": 42,
        "previous_stage": "analyze",
        "current_stage": "write",
    }
    assert current_stage == "write"


def test_topic_force_advance_preserves_missing_run_error(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-force-advance-missing.db"
    Database(db_path).migrate()
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).post(
            "/api/topics/999/force-advance",
            json={},
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 404
    assert response.json() == {
        "detail": "No orchestrator run found for topic 999",
    }
