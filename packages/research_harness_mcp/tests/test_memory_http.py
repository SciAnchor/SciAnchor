"""Focused HTTP tests for workflow-memory recall."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_memory_recall_empty_query_returns_no_hits():
    from research_harness_mcp.http_api import app

    response = TestClient(app).post("/api/memory/recall", json={"query": "   "})

    assert response.status_code == 200
    assert response.json() == {"query": "", "hits": []}


def test_memory_recall_forwards_options_and_serializes_hits(
    monkeypatch, tmp_path: Path
):
    from research_harness.memory import MemoryHit
    from research_harness.storage import db as storage_db
    from research_harness_mcp import http_api

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = tmp_path / "memory.db"
    calls: list[dict[str, object]] = []

    class FakeDatabase:
        def __init__(self, path: Path):
            self.path = path

    def fake_recall(db, query: str, **kwargs):
        calls.append({"db_path": db.path, "query": query, **kwargs})
        return [
            MemoryHit(
                topic_id=7,
                topic_name="Prior run",
                description="Prior description",
                created_at="2026-01-02T03:04:05+00:00",
                score=0.75,
                lexical_score=0.5,
                provenance_success_count=2,
                decision_highlights=["stage/checkpoint: choice"],
            )
        ]

    monkeypatch.setattr(storage_db, "Database", FakeDatabase)
    monkeypatch.setattr("research_harness.memory.recall_similar_runs", fake_recall)
    try:
        response = TestClient(http_api.app).post(
            "/api/memory/recall",
            json={
                "query": " retrieval memory ",
                "exclude_topic_id": 3,
                "top_k": "4",
                "max_age_days": 30,
                "require_success": False,
            },
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "query": "retrieval memory",
        "hits": [
            {
                "topic_id": 7,
                "topic_name": "Prior run",
                "description": "Prior description",
                "created_at": "2026-01-02T03:04:05+00:00",
                "score": 0.75,
                "lexical_score": 0.5,
                "provenance_success_count": 2,
                "decision_highlights": ["stage/checkpoint: choice"],
            }
        ],
    }
    assert calls == [
        {
            "db_path": tmp_path / "memory.db",
            "query": "retrieval memory",
            "exclude_topic_id": 3,
            "top_k": 4,
            "max_age_days": 30,
            "require_success": False,
        }
    ]


def test_memory_recall_returns_500_on_recall_failure(monkeypatch, tmp_path: Path):
    from research_harness.storage import db as storage_db
    from research_harness_mcp import http_api

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = tmp_path / "memory.db"

    class FakeDatabase:
        def __init__(self, path: Path):
            self.path = path

    def fake_recall(*_args, **_kwargs):
        raise RuntimeError("memory unavailable")

    monkeypatch.setattr(storage_db, "Database", FakeDatabase)
    monkeypatch.setattr("research_harness.memory.recall_similar_runs", fake_recall)
    try:
        response = TestClient(http_api.app).post(
            "/api/memory/recall", json={"query": "retrieval"}
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 500
    assert response.json()["detail"] == "memory unavailable"
