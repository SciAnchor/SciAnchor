"""Focused HTTP tests for paper deep-read route extraction."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_paper_deep_read_module_imports_and_route_registered():
    from research_harness_mcp import http_api, paper_deep_read_http

    assert callable(paper_deep_read_http.register_paper_deep_read_routes)
    assert any(
        route.path == "/api/papers/{paper_id}/deep-read" and "PATCH" in route.methods
        for route in http_api.app.routes
    )


def test_paper_deep_read_uses_topic_fallback_and_dispatches_callback(
    monkeypatch, tmp_path: Path
):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-deep-read.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (5, "topic"))
        conn.execute(
            "INSERT INTO papers (id, title, status) VALUES (?, ?, ?)",
            (11, "Paper", "meta_only"),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
            (11, 5),
        )
        conn.commit()

    calls: list[dict[str, object]] = []

    def fake_deep_read(api, *, paper_id: int, topic_id: int):
        calls.append(
            {"api_db_path": api.db_path, "paper_id": paper_id, "topic_id": topic_id}
        )
        return {"paper_id": paper_id, "topic_id": topic_id, "ok": True}

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "_deep_read_paper_impl", fake_deep_read)
    try:
        response = TestClient(http_api.app).patch("/api/papers/11/deep-read")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "success": True,
        "deep_read": True,
        "output": {"paper_id": 11, "topic_id": 5, "ok": True},
    }
    assert calls == [{"api_db_path": db_path, "paper_id": 11, "topic_id": 5}]


def test_paper_deep_read_requires_topic_when_paper_has_none(
    monkeypatch, tmp_path: Path
):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-deep-read-missing-topic.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO papers (id, title, status) VALUES (?, ?, ?)",
            (12, "Paper Without Topic", "meta_only"),
        )
        conn.commit()

    calls: list[dict[str, object]] = []

    def fake_deep_read(api, *, paper_id: int, topic_id: int):
        calls.append({"api": api, "paper_id": paper_id, "topic_id": topic_id})
        return {}

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "_deep_read_paper_impl", fake_deep_read)
    try:
        response = TestClient(http_api.app).patch("/api/papers/12/deep-read")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 400
    assert response.json() == {
        "detail": "topic_id is required for deep-read when paper has no topic"
    }
    assert calls == []


def test_paper_deep_read_returns_404_for_unknown_paper(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-deep-read-404.db"
    Database(db_path).migrate()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).patch("/api/papers/999/deep-read")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 404
    assert response.json() == {"detail": "Paper not found"}
