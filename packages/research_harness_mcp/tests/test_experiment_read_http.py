"""Focused HTTP tests for experiment read routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "experiment-read.db"
    from research_harness.storage.db import Database

    Database(db_path).migrate()
    from research_harness_mcp import http_api

    original = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        yield TestClient(http_api.app)
    finally:
        http_api.DB_PATH = original


def _seed_experiment_data() -> None:
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        conn.execute(
            "INSERT INTO topics (id, name, status) VALUES (?, ?, ?)",
            (42, "experiment-topic", "active"),
        )
        conn.execute(
            """
            INSERT INTO experiments
                (id, topic_id, name, task_description, primary_metric, direction,
                 mode, budget_json, best_run_id, status, stopped_reason,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                5,
                42,
                "older experiment",
                "Older task",
                "accuracy",
                "max",
                "agent",
                '{"max_iterations": 2}',
                None,
                "completed",
                "done",
                "2026-06-12T10:00:00Z",
                "2026-06-12T10:10:00Z",
                6,
                42,
                "newer experiment",
                "Newer task",
                "loss",
                "min",
                "strict",
                '{"max_iterations": 3, "patience": 1}',
                61,
                "stopped",
                "patience",
                "2026-06-12T11:00:00Z",
                "2026-06-12T11:10:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO experiment_loop_runs
                (id, experiment_id, iteration, code_hash, primary_metric_value,
                 elapsed_sec, cost_usd, tokens_used, status, returncode,
                 stdout_tail, stderr_tail, feedback_to_next, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                61,
                6,
                2,
                "hash-2",
                0.25,
                2.5,
                0.07,
                20,
                "completed",
                0,
                "stdout-2",
                "",
                "keep going",
                "2026-06-12T11:03:00Z",
                60,
                6,
                1,
                "hash-1",
                0.4,
                3.5,
                0.05,
                10,
                "failed",
                1,
                "stdout-1",
                "stderr-1",
                "try again",
                "2026-06-12T11:02:00Z",
            ),
        )
        conn.commit()


def test_topic_experiments_order_parse_budget_and_hydrate_best_run(
    client: TestClient,
):
    _seed_experiment_data()

    response = client.get("/api/topics/42/experiments")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["topic_id"] == 42
    experiments = payload["experiments"]
    assert [experiment["id"] for experiment in experiments] == [6, 5]
    assert experiments[0]["budget"] == {"max_iterations": 3, "patience": 1}
    assert "budget_json" not in experiments[0]
    assert experiments[0]["best"] == {
        "iteration": 2,
        "primary_metric_value": 0.25,
        "cost_usd": 0.07,
        "tokens_used": 20,
    }
    assert experiments[1]["best"] is None


def test_topic_experiments_preserve_missing_topic_fallback(client: TestClient):
    response = client.get("/api/topics/999/experiments")

    assert response.status_code == 200
    assert response.json() == {"topic_id": 999, "experiments": []}


def test_experiment_runs_return_experiment_and_runs_in_iteration_order(
    client: TestClient,
):
    _seed_experiment_data()

    response = client.get("/api/experiments/6/runs")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["experiment"]["id"] == 6
    assert payload["experiment"]["primary_metric"] == "loss"
    assert [run["id"] for run in payload["runs"]] == [60, 61]
    assert payload["runs"][0]["iteration"] == 1
    assert payload["runs"][1]["iteration"] == 2


def test_experiment_runs_missing_experiment_returns_empty_payload(
    client: TestClient,
):
    response = client.get("/api/experiments/999/runs")

    assert response.status_code == 200
    assert response.json() == {"experiment": None, "runs": []}
