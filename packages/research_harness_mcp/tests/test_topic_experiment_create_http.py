"""Focused HTTP tests for topic experiment create route extraction."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def test_topic_experiment_create_module_imports_and_route_registered():
    from research_harness_mcp import http_api, topic_experiment_create_http

    assert callable(
        topic_experiment_create_http.register_topic_experiment_create_routes
    )
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}/experiments"
        and "POST" in route.methods
    ]
    assert len(matching_routes) == 1


def test_topic_experiment_create_preserves_defaults_and_payload_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness.primitives import experiment_loop_impl
    from research_harness_mcp import http_api

    captured: dict[str, object] = {}

    def fake_experiment_loop(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            experiment_id=11,
            total_iterations=2,
            best_iteration=1,
            best_value=0.87,
            best_run_id=101,
            stopped_reason="patience",
            total_cost_usd=0.25,
            total_tokens=1234,
        )

    monkeypatch.setattr(experiment_loop_impl, "experiment_loop", fake_experiment_loop)
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = tmp_path / "experiment-create-defaults.db"
    try:
        response = TestClient(http_api.app).post(
            "/api/topics/42/experiments",
            json={
                "task_description": "Improve retrieval",
                "primary_metric": "quality",
            },
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "experiment_id": 11,
        "total_iterations": 2,
        "best_iteration": 1,
        "best_value": 0.87,
        "best_run_id": 101,
        "stopped_reason": "patience",
        "total_cost_usd": 0.25,
        "total_tokens": 1234,
    }
    assert captured["topic_id"] == 42
    assert captured["name"] == ""
    assert captured["task_description"] == "Improve retrieval"
    assert captured["fixture_files"] == {}
    assert captured["mutable_entry"] == "main.py"
    assert captured["primary_metric"] == "quality"
    assert captured["direction"] == "max"
    assert captured["mode"] == "agent"
    assert captured["timeout_sec"] == 300.0
    assert captured["env_vars"] == {}
    budget = captured["budget"]
    assert budget.max_iterations == 5
    assert budget.max_cost_usd == 0.0
    assert budget.max_tokens == 0
    assert budget.patience == 3


def test_topic_experiment_create_preserves_overrides_and_route_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness.primitives import experiment_loop_impl
    from research_harness_mcp import http_api

    captured: dict[str, object] = {}

    def fake_experiment_loop(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            experiment_id=12,
            total_iterations=1,
            best_iteration=1,
            best_value=0.42,
            best_run_id=202,
            stopped_reason="budget",
            total_cost_usd=0.5,
            total_tokens=456,
        )

    monkeypatch.setattr(experiment_loop_impl, "experiment_loop", fake_experiment_loop)
    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = tmp_path / "experiment-create-overrides.db"
    try:
        response = TestClient(http_api.app).post(
            "/api/topics/43/experiments",
            json={
                "name": "retrieval-ablation",
                "task_description": "Ablate retriever",
                "fixture_files": {"main.py": "print('ok')"},
                "mutable_entry": "agent.py",
                "primary_metric": "loss",
                "direction": "min",
                "mode": "local",
                "timeout_sec": 12.5,
                "env_vars": {"RH_TEST": "1"},
                "max_iterations": 7,
                "max_cost_usd": 1.25,
                "max_tokens": 2048,
                "patience": 4,
            },
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json()["experiment_id"] == 12
    assert captured["topic_id"] == 43
    assert captured["name"] == "retrieval-ablation"
    assert captured["fixture_files"] == {"main.py": "print('ok')"}
    assert captured["mutable_entry"] == "agent.py"
    assert captured["direction"] == "min"
    assert captured["mode"] == "local"
    assert captured["timeout_sec"] == 12.5
    assert captured["env_vars"] == {"RH_TEST": "1"}
    budget = captured["budget"]
    assert budget.max_iterations == 7
    assert budget.max_cost_usd == 1.25
    assert budget.max_tokens == 2048
    assert budget.patience == 4

    paths = [route.path for route in http_api.app.routes]
    assert paths.index("/api/topics/{topic_id}/experiments") < paths.index("/api/stats")
