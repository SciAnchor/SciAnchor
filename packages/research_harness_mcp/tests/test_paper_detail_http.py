"""Focused HTTP tests for paper detail route extraction."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_paper_detail_module_imports_and_route_registered():
    from research_harness_mcp import http_api, paper_detail_http

    assert callable(paper_detail_http.register_paper_detail_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/papers/{paper_id}" and "GET" in route.methods
    ]
    assert len(matching_routes) == 1


def test_paper_detail_shape_is_preserved(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-detail-http.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (42, "shape"))
        conn.execute(
            """
            INSERT INTO papers
                (id, title, authors, year, venue, doi, arxiv_id, s2_id, url,
                 abstract, citation_count, status, pdf_path, created_at, deep_read)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                11,
                "Paper Detail",
                '["Ada", "Ben"]',
                2024,
                "ICLR",
                "10.1/detail",
                "2401.00111",
                "s2-detail",
                "https://example.test/detail",
                "Detail abstract",
                17,
                "deep_read",
                "/tmp/detail.pdf",
                "2026-06-01T09:00:00Z",
                1,
            ),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
            (11, 42, "high"),
        )
        conn.execute(
            """
            INSERT INTO paper_annotations
                (paper_id, section, content, source, confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                11,
                "method",
                '{"note":"strong"}',
                "manual",
                0.9,
                "2026-06-04T09:00:00Z",
                "2026-06-04T10:00:00Z",
            ),
        )
        conn.commit()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get("/api/papers/11")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": 11,
        "title": "Paper Detail",
        "authors": ["Ada", "Ben"],
        "year": 2024,
        "venue": "ICLR",
        "doi": "10.1/detail",
        "arxiv_id": "2401.00111",
        "s2_id": "s2-detail",
        "url": "https://example.test/detail",
        "abstract": "Detail abstract",
        "citation_count": 17,
        "deep_read": True,
        "status": "deep_read",
        "pdf_path": "/tmp/detail.pdf",
        "created_at": "2026-06-01T09:00:00Z",
        "annotations": [
            {
                "id": 1,
                "section": "method",
                "content": {"note": "strong"},
                "source": "manual",
                "confidence": 0.9,
                "created_at": "2026-06-04T09:00:00Z",
                "updated_at": "2026-06-04T10:00:00Z",
            }
        ],
        "topics": [{"id": 42, "name": "shape", "relevance": "high"}],
    }


def test_paper_detail_returns_404_for_unknown_paper(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-detail-http-404.db"
    Database(db_path).migrate()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get("/api/papers/999")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 404
    assert response.json() == {"detail": "Paper 999 not found"}
