"""Focused HTTP tests for rollback route extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_rollback_module_imports_and_routes_registered():
    from research_harness_mcp import http_api, rollback_http

    assert callable(rollback_http.register_rollback_routes)
    rollback_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}/rollback" and "POST" in route.methods
    ]
    rollback_log_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}/rollback/log"
        and "GET" in route.methods
    ]
    assert len(rollback_routes) == 1
    assert len(rollback_log_routes) == 1


def _seed_rollback_topic(db_path: Path) -> None:
    from research_harness.storage.db import Database

    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (7, "rollback"))
        conn.commit()


def test_rollback_post_preserves_success_payload_and_call_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness.orchestrator import snapshots
    from research_harness_mcp import http_api

    db_path = tmp_path / "rollback-http-success.db"
    _seed_rollback_topic(db_path)
    captured: dict[str, object] = {}

    def fake_rollback_to_stage(conn, topic_id, to_stage, reason, trigger):
        captured["topic_id"] = topic_id
        captured["to_stage"] = to_stage
        captured["reason"] = reason
        captured["trigger"] = trigger
        captured["topic_exists"] = bool(
            conn.execute("SELECT id FROM topics WHERE id = ?", (topic_id,)).fetchone()
        )
        return {
            "success": True,
            "topic_id": topic_id,
            "to_stage": to_stage,
            "reason": reason,
            "trigger": trigger,
        }

    monkeypatch.setattr(snapshots, "rollback_to_stage", fake_rollback_to_stage)
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).post(
            "/api/topics/7/rollback",
            json={"to_stage": "build", "reason": "paper pool changed"},
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "success": True,
        "topic_id": 7,
        "to_stage": "build",
        "reason": "paper pool changed",
        "trigger": "user",
    }
    assert captured == {
        "topic_id": 7,
        "to_stage": "build",
        "reason": "paper pool changed",
        "trigger": "user",
        "topic_exists": True,
    }


def test_rollback_post_preserves_missing_topic_and_failure_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness.orchestrator import snapshots
    from research_harness_mcp import http_api

    db_path = tmp_path / "rollback-http-errors.db"
    _seed_rollback_topic(db_path)

    def fake_rollback_to_stage(conn, topic_id, to_stage, reason, trigger):
        return {"success": False, "error": f"No snapshot found for stage '{to_stage}'"}

    monkeypatch.setattr(snapshots, "rollback_to_stage", fake_rollback_to_stage)
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        client = TestClient(http_api.app)
        missing = client.post(
            "/api/topics/999/rollback",
            json={"to_stage": "build", "reason": "missing topic"},
        )
        failed = client.post(
            "/api/topics/7/rollback",
            json={"to_stage": "build", "reason": "no snapshot"},
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Topic not found"}
    assert failed.status_code == 400
    assert failed.json() == {"detail": "No snapshot found for stage 'build'"}


def test_rollback_log_preserves_payload_order_and_missing_topic_error(
    tmp_path: Path,
):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "rollback-log-http.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (7, "rollback"))
        conn.execute(
            """
            INSERT INTO stage_snapshots
                (id, topic_id, stage, artifact_snapshot, token_cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (5, 7, "build", "{}", 0, "2026-06-13T08:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO rollback_log
                (topic_id, from_stage, to_stage, to_snapshot_id, trigger, reason,
                 rubric_snapshot, created_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?),
                (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                7,
                "analyze",
                "build",
                5,
                "user",
                "older",
                None,
                "2026-06-13T08:01:00Z",
                7,
                "write",
                "build",
                5,
                "gate",
                "newer",
                "{}",
                "2026-06-13T08:02:00Z",
            ),
        )
        conn.commit()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        client = TestClient(http_api.app)
        response = client.get("/api/topics/7/rollback/log")
        missing = client.get("/api/topics/999/rollback/log")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [row["reason"] for row in payload] == ["newer", "older"]
    assert payload[0]["topic_id"] == 7
    assert payload[0]["to_stage"] == "build"
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Topic not found"}


def test_rollback_routes_keep_original_order_before_rubric_routes():
    from research_harness_mcp import http_api

    paths = [route.path for route in http_api.app.routes]
    assert paths.index("/api/topics/{topic_id}/rollback") < paths.index(
        "/api/topics/{topic_id}/rubric-scores"
    )
