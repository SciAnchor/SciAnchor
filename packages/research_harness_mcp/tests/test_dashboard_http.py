"""Focused HTTP tests for dashboard, usage, and review-issue read routes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "dashboard.db"
    from research_harness.storage.db import Database

    Database(db_path).migrate()
    from research_harness_mcp import http_api

    original = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        yield TestClient(http_api.app)
    finally:
        http_api.DB_PATH = original


def _seed_dashboard_data() -> str:
    from research_harness_mcp import http_api

    today = datetime.now(timezone.utc).date().isoformat()
    with http_api.get_db() as conn:
        conn.execute(
            "INSERT INTO domains (id, name, description) VALUES (?, ?, ?)",
            (7, "Systems", "Systems research"),
        )
        conn.execute(
            "INSERT INTO topics (id, name, domain_id) VALUES (?, ?, ?)",
            (42, "dashboard-topic", 7),
        )
        conn.execute(
            """
            INSERT INTO papers (id, title, venue, year, status, pdf_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Paper with PDF",
                "ICLR",
                2026,
                "active",
                "/tmp/paper.pdf",
                f"{today}T08:00:00Z",
                2,
                "Paper without PDF",
                "ACL",
                2025,
                "active",
                "",
                f"{today}T09:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts (id, topic_id, stage, artifact_type, title)
            VALUES (?, ?, ?, ?, ?)
            """,
            (10, 42, "analyze", "evidence_pack", "Evidence"),
        )
        conn.execute(
            """
            INSERT INTO provenance_records
                (id, primitive, category, started_at, finished_at, backend,
                 model_used, topic_id, stage, input_hash, output_hash, cost_usd,
                 success, error, created_at, prompt_tokens, completion_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                11,
                "paper_search",
                "search",
                f"{today}T10:00:00Z",
                f"{today}T10:00:01Z",
                "local",
                "model",
                42,
                "search",
                "input",
                "output",
                0.25,
                1,
                "",
                f"{today}T10:00:02Z",
                5,
                7,
            ),
        )
        conn.execute(
            """
            INSERT INTO agent_registry
                (id, nickname, provider, provider_family, model, api_key_env,
                 role_prefs, monthly_budget_usd, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Agent",
                "local",
                "local",
                "model",
                "",
                "{}",
                0.0,
                "active",
                f"{today}T10:04:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO token_ledger
                (agent_id, topic_id, stage, primitive, role, prompt_tokens,
                 completion_tokens, cost_usd, idempotency_key, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                42,
                "search",
                "paper_search",
                "assistant",
                3,
                4,
                0.5,
                "key-1",
                f"{today}T10:05:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO review_issues
                (id, topic_id, stage, review_type, severity, category, blocking,
                 status, summary, details, recommended_action, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                13,
                42,
                "write",
                "scholarly",
                "high",
                "citation",
                1,
                "open",
                "Missing citation",
                "Add citation",
                "Cite source",
                today,
                14,
                42,
                "write",
                "scholarly",
                "low",
                "style",
                0,
                "resolved",
                "Style nit",
                "Tighten prose",
                "Edit",
                today,
            ),
        )
        conn.commit()
    return today


def test_dashboard_stats_counts_recent_items(client: TestClient):
    _seed_dashboard_data()

    response = client.get("/api/stats")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_papers"] == 2
    assert payload["total_topics"] == 1
    assert payload["total_domains"] == 1
    assert payload["total_artifacts"] == 1
    assert payload["total_provenance_records"] == 1
    assert payload["papers_with_pdf"] == 1
    assert payload["recent_papers"][0]["title"] == "Paper without PDF"
    assert payload["recent_events"] == []


def test_usage_daily_merges_token_ledger_and_provenance(client: TestClient):
    today = _seed_dashboard_data()

    response = client.get("/api/usage/daily?days=365&topic_id=42")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "day": today,
            "prompt_tokens": 8,
            "completion_tokens": 11,
            "cost_usd": 0.75,
            "calls": 2,
        }
    ]


def test_topic_issues_filters_status_and_blocking(client: TestClient):
    _seed_dashboard_data()

    response = client.get("/api/topics/42/issues?status=open&blocking_only=true")

    assert response.status_code == 200, response.text
    assert response.json()["topic_id"] == 42
    issues = response.json()["issues"]
    assert len(issues) == 1
    assert issues[0]["id"] == 13
    assert issues[0]["summary"] == "Missing citation"
