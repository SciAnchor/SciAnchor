"""Focused HTTP tests for topic artifacts, events, and decisions reads."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "topic-read.db"
    from research_harness.storage.db import Database

    Database(db_path).migrate()
    from research_harness_mcp import http_api

    original = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        yield TestClient(http_api.app)
    finally:
        http_api.DB_PATH = original


def _seed_topic_read_data() -> None:
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        conn.execute(
            "INSERT INTO topics (id, name, status) VALUES (?, ?, ?)",
            (42, "topic-read", "active"),
        )
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (?, ?, ?, ?)",
            (9, 42, "topic-read-project", "Topic read test"),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (id, project_id, topic_id, stage, artifact_type, status, version,
                 title, path, payload_json, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                9,
                42,
                "analyze",
                "evidence_pack",
                "active",
                1,
                "Evidence",
                "artifacts/evidence.json",
                '{"claims": ["c1"]}',
                '{"source": "test"}',
                "2026-06-12T10:00:00Z",
                "2026-06-12T10:01:00Z",
                2,
                9,
                42,
                "write",
                "draft_pack",
                "active",
                1,
                "Draft",
                "artifacts/draft.json",
                '{"sections": {"intro": "Hello"}}',
                '{"reviewed": true}',
                "2026-06-12T11:00:00Z",
                "2026-06-12T11:01:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO orchestrator_runs
                (id, topic_id, mode, current_stage, stage_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                3,
                42,
                "standard",
                "analyze",
                "in_progress",
                "2026-06-12T09:00:00Z",
                "2026-06-12T09:05:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO orchestrator_stage_events
                (id, run_id, topic_id, from_stage, to_stage, event_type, status,
                 actor, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                10,
                3,
                42,
                "build",
                "analyze",
                "advance",
                "accepted",
                "tester",
                '{"reason": "ready"}',
                "2026-06-12T12:00:00Z",
                11,
                3,
                42,
                "analyze",
                "write",
                "gate_check",
                "blocked",
                "tester",
                '{"blocking": true}',
                "2026-06-12T13:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO decision_log
                (id, project_id, topic_id, stage, checkpoint, choice, reasoning,
                 params_snapshot, created_at, actor, origin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                20,
                9,
                42,
                "analyze",
                "evidence_gate",
                "continue",
                "Enough evidence",
                '{"threshold": 0.8}',
                "2026-06-12T14:00:00Z",
                "codex",
                "self-dev",
            ),
        )
        conn.commit()


def test_topic_artifacts_group_by_stage_and_parse_json(client: TestClient):
    _seed_topic_read_data()

    response = client.get("/api/topics/42/artifacts")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["topic_id"] == 42
    assert sorted(payload["artifacts_by_stage"]) == ["analyze", "write"]
    analyze = payload["artifacts_by_stage"]["analyze"][0]
    assert analyze["artifact_type"] == "evidence_pack"
    assert analyze["payload"] == {"claims": ["c1"]}
    assert analyze["metadata"] == {"source": "test"}
    assert "payload_json" not in analyze
    assert "metadata_json" not in analyze


def test_topic_artifacts_filter_stage_and_404_missing_topic(client: TestClient):
    _seed_topic_read_data()

    filtered = client.get("/api/topics/42/artifacts?stage=write")
    missing = client.get("/api/topics/999/artifacts")

    assert filtered.status_code == 200, filtered.text
    assert sorted(filtered.json()["artifacts_by_stage"]) == ["write"]
    assert missing.status_code == 404


def test_topic_events_parse_payload_and_order_newest_first(client: TestClient):
    _seed_topic_read_data()

    response = client.get("/api/topics/42/events")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["topic_id"] == 42
    assert [event["id"] for event in payload["events"]] == [11, 10]
    assert payload["events"][0]["payload"] == {"blocking": True}
    assert "payload_json" not in payload["events"][0]


def test_topic_events_404_missing_topic(client: TestClient):
    response = client.get("/api/topics/999/events")

    assert response.status_code == 404


def test_topic_decisions_parse_params_and_preserve_missing_topic_behavior(
    client: TestClient,
):
    _seed_topic_read_data()

    response = client.get("/api/topics/42/decisions")
    missing = client.get("/api/topics/999/decisions")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "topic_id": 42,
        "decisions": [
            {
                "id": 20,
                "project_id": 9,
                "topic_id": 42,
                "stage": "analyze",
                "checkpoint": "evidence_gate",
                "choice": "continue",
                "reasoning": "Enough evidence",
                "created_at": "2026-06-12T14:00:00Z",
                "actor": "codex",
                "origin": "self-dev",
                "params": {"threshold": 0.8},
            }
        ],
    }
    assert missing.status_code == 200
    assert missing.json() == {"topic_id": 999, "decisions": []}
