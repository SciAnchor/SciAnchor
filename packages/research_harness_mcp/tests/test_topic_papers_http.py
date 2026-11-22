"""Focused HTTP tests for topic paper listing route extraction."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_topic_papers_module_imports_and_route_registered():
    from research_harness_mcp import http_api, topic_papers_http

    assert callable(topic_papers_http.register_topic_paper_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}/papers" and "GET" in route.methods
    ]
    assert len(matching_routes) == 1


def test_topic_papers_returns_filtered_paginated_shape(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-papers-http.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (42, "papers"))
        conn.execute(
            """
            INSERT INTO papers
                (id, title, authors, year, venue, doi, arxiv_id, s2_id, url,
                 abstract, citation_count, status, created_at, deep_read)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Alpha Paper",
                '["Ada", "Ben"]',
                2024,
                "ICLR",
                "10.1/alpha",
                "2401.00001",
                "s2-alpha",
                "https://example.test/alpha",
                "Alpha abstract",
                12,
                "deep_read",
                "2026-06-01T09:00:00Z",
                1,
                2,
                "Beta Paper",
                '["Cy"]',
                2023,
                "NeurIPS",
                "10.1/beta",
                "2401.00002",
                "s2-beta",
                "https://example.test/beta",
                "Beta abstract",
                5,
                "meta_only",
                "2026-06-02T09:00:00Z",
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO paper_topics (paper_id, topic_id, relevance, created_at)
            VALUES (?, ?, ?, ?), (?, ?, ?, ?)
            """,
            (
                1,
                42,
                "high",
                "2026-06-03T09:00:00Z",
                2,
                42,
                "medium",
                "2026-06-03T10:00:00Z",
            ),
        )
        conn.commit()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get(
            "/api/topics/42/papers?search=Alpha&sort=title&order=asc&page=1&per_page=50"
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "data": [
            {
                "id": 1,
                "title": "Alpha Paper",
                "authors": ["Ada", "Ben"],
                "year": 2024,
                "venue": "ICLR",
                "doi": "10.1/alpha",
                "arxiv_id": "2401.00001",
                "s2_id": "s2-alpha",
                "pmid": None,
                "pmcid": None,
                "pdf_path": "",
                "pdf_hash": "",
                "status": "deep_read",
                "created_at": "2026-06-01T09:00:00Z",
                "url": "https://example.test/alpha",
                "abstract": "Alpha abstract",
                "bibtex_auto": "",
                "concepts_json": "",
                "citation_count": 12,
                "affiliations": "[]",
                "compiled_summary": "",
                "compiled_from_hash": "",
                "deep_read": 1,
                "relevance": "high",
            }
        ],
        "pagination": {"page": 1, "per_page": 50, "total": 1, "total_pages": 1},
    }


def test_topic_papers_returns_404_for_unknown_topic(tmp_path: Path):
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "topic-papers-http-404.db"
    Database(db_path).migrate()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get("/api/topics/999/papers")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 404
    assert response.json() == {"detail": "Topic 999 not found"}
