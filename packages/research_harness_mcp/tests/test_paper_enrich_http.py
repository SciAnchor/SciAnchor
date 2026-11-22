"""Focused HTTP tests for paper enrich route extraction."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_paper_enrich_module_imports_and_route_registered():
    from research_harness_mcp import http_api, paper_enrich_http

    assert callable(paper_enrich_http.register_paper_enrich_routes)
    assert any(
        route.path == "/api/papers/{paper_id}/enrich" and "POST" in route.methods
        for route in http_api.app.routes
    )


def test_paper_enrich_dispatches_paper_pool(monkeypatch, tmp_path: Path):
    from research_harness.core.paper_pool import PaperPool
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-enrich.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO papers (id, title, status) VALUES (?, ?, ?)",
            (11, "Paper", "meta_only"),
        )
        conn.commit()

    calls: list[int] = []

    def fake_enrich_metadata(self, paper_id: int):
        calls.append(paper_id)
        return {"venue": "updated", "citation_count": 42}

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(PaperPool, "enrich_metadata", fake_enrich_metadata)
    try:
        response = TestClient(http_api.app).post("/api/papers/11/enrich")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "paper_id": 11,
        "fields_updated": {"venue": "updated", "citation_count": 42},
    }
    assert calls == [11]


def test_paper_enrich_returns_404_for_unknown_paper(monkeypatch, tmp_path: Path):
    from research_harness.core.paper_pool import PaperPool
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-enrich-404.db"
    Database(db_path).migrate()
    calls: list[int] = []

    def fake_enrich_metadata(self, paper_id: int):
        calls.append(paper_id)
        return {}

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(PaperPool, "enrich_metadata", fake_enrich_metadata)
    try:
        response = TestClient(http_api.app).post("/api/papers/999/enrich")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 404
    assert response.json() == {"detail": "Paper not found"}
    assert calls == []
