"""Focused HTTP tests for algorithm candidate route extraction."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_algorithm_candidates_module_imports_and_route_registered():
    from research_harness_mcp import algorithm_candidates_http, http_api

    assert callable(algorithm_candidates_http.register_algorithm_candidate_routes)
    assert any(
        route.path == "/api/topics/{topic_id}/algorithm-candidates"
        and "POST" in route.methods
        for route in http_api.app.routes
    )


def test_algorithm_candidates_dispatches_tool_arguments_with_deep_read_notes(
    monkeypatch, tmp_path: Path
):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "algorithm-candidates.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (7, "demo"))
        conn.execute(
            """
            INSERT INTO papers (id, title, status, deep_read)
            VALUES (?, ?, ?, ?)
            """,
            (11, "Deep Paper", "meta_only", 1),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
            (11, 7),
        )
        conn.commit()

    calls: list[tuple[str, dict]] = []

    def fake_run_tool(name: str, arguments: dict):
        calls.append((name, arguments))
        return {"status": "success", "tool": name, "arguments": arguments}

    def fake_ensure_compiled_summary(db, paper_id: int):
        return SimpleNamespace(db_path=db.db_path, paper_id=paper_id)

    def fake_format_compiled_for_context(compiled) -> str:
        return f"compiled notes for paper {compiled.paper_id}"

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "_run_tool", fake_run_tool)
    monkeypatch.setattr(
        "research_harness.execution.compiled_summary.ensure_compiled_summary",
        fake_ensure_compiled_summary,
    )
    monkeypatch.setattr(
        "research_harness.execution.compiled_summary.format_compiled_for_context",
        fake_format_compiled_for_context,
    )
    try:
        response = TestClient(http_api.app).post(
            "/api/topics/7/algorithm-candidates",
            json={"focus": "retrieval", "n_candidates": 4},
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert calls == [
        (
            "algorithm_candidate_generate",
            {
                "topic_id": 7,
                "brief": {
                    "topic_id": 7,
                    "focus": "retrieval",
                    "n_candidates": 4,
                },
                "deep_read_notes": [
                    {
                        "paper_id": 11,
                        "title": "Deep Paper",
                        "notes": "compiled notes for paper 11",
                    }
                ],
                "focus": "retrieval",
            },
        )
    ]
    assert response.json()["arguments"] == calls[0][1]


def test_algorithm_candidates_preserves_explicit_brief_and_note_fallback(
    monkeypatch, tmp_path: Path
):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "algorithm-candidates-fallback.db"
    Database(db_path).migrate()

    calls: list[tuple[str, dict]] = []

    def fake_run_tool(name: str, arguments: dict):
        calls.append((name, arguments))
        return {"status": "success", "tool": name, "arguments": arguments}

    def fail_get_db():
        raise RuntimeError("compiled summaries unavailable")

    original_db_path = http_api.DB_PATH
    original_get_db = http_api.get_db
    http_api.DB_PATH = db_path
    http_api.get_db = fail_get_db
    monkeypatch.setattr(http_api, "_run_tool", fake_run_tool)
    try:
        response = TestClient(http_api.app).post(
            "/api/topics/9/algorithm-candidates",
            json={"focus": "latency", "brief": {"custom": True}},
        )
    finally:
        http_api.DB_PATH = original_db_path
        http_api.get_db = original_get_db

    assert response.status_code == 200, response.text
    assert calls == [
        (
            "algorithm_candidate_generate",
            {
                "topic_id": 9,
                "brief": {"custom": True},
                "deep_read_notes": None,
                "focus": "latency",
            },
        )
    ]
