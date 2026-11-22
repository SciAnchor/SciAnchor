"""Focused HTTP tests for calibration and rubric score endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from research_harness.storage.db import Database


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "rubric.db"
    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'rubric')")
        conn.execute(
            """
            INSERT INTO rubric_calibrations
                (stage, tier, threshold, false_rollback_rate, reject_rate,
                 anchor_count, calibrated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("analyze", "standard", 7.5, 0.1, 0.2, 12, "2026-06-12T10:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (id, topic_id, stage, artifact_type, title, path, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (99, 1, "analyze", "draft", "Draft", "draft.md", "{}"),
        )
        conn.execute(
            """
            INSERT INTO rubric_scores
                (id, topic_id, artifact_id, stage, tier, dimension_scores,
                 weighted_total, verdict, shadow_verdict, critique,
                 evidence_refs, rubric_version, scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                3,
                1,
                99,
                "analyze",
                "standard",
                json.dumps({"novelty": 8}),
                8.1,
                "pass",
                "pass",
                json.dumps({"summary": "solid"}),
                json.dumps(["artifact:99"]),
                "v1",
                "2026-06-12T10:05:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    from research_harness_mcp import http_api

    original = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        yield TestClient(http_api.app)
    finally:
        http_api.DB_PATH = original


def test_calibrations_list_returns_ordered_rows(client: TestClient):
    response = client.get("/api/calibrations")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "stage": "analyze",
            "tier": "standard",
            "threshold": 7.5,
            "false_rollback_rate": 0.1,
            "reject_rate": 0.2,
            "anchor_count": 12,
            "calibrated_at": "2026-06-12T10:00:00Z",
        }
    ]


def test_calibration_run_single_stage_uses_request_defaults(client: TestClient):
    result = SimpleNamespace(
        stage="write",
        tier="standard",
        threshold=8.0,
        anchor_count=5,
        false_rollback_rate=0.0,
        reject_rate=0.4,
        used_default=False,
    )
    with patch(
        "research_harness.calibration.calibrate_stage_tier", return_value=result
    ):
        response = client.post("/api/calibrations/run", json={"stage": "write"})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "count": 1,
        "results": [
            {
                "stage": "write",
                "tier": "standard",
                "threshold": 8.0,
                "anchor_count": 5,
                "false_rollback_rate": 0.0,
                "reject_rate": 0.4,
                "used_default": False,
            }
        ],
    }


def test_rubric_scores_hydrate_json_fields(client: TestClient):
    response = client.get("/api/topics/1/rubric-scores?stage=analyze")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "id": 3,
            "topic_id": 1,
            "artifact_id": 99,
            "stage": "analyze",
            "tier": "standard",
            "judge_agent_id": None,
            "dimension_scores": {"novelty": 8},
            "weighted_total": 8.1,
            "verdict": "pass",
            "shadow_verdict": "pass",
            "critique": {"summary": "solid"},
            "evidence_refs": ["artifact:99"],
            "rubric_version": "v1",
            "scored_at": "2026-06-12T10:05:00Z",
        }
    ]


def test_rubric_scores_unknown_topic_404(client: TestClient):
    response = client.get("/api/topics/999/rubric-scores")

    assert response.status_code == 404
