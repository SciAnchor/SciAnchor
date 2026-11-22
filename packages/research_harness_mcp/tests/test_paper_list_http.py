"""Focused HTTP tests for paper list route extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from research_harness.service import ServiceResult


def test_paper_list_module_imports_and_route_registered():
    from research_harness_mcp import http_api, paper_list_http

    assert callable(paper_list_http.register_paper_list_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/papers" and "GET" in route.methods
    ]
    assert len(matching_routes) == 1


def _seed_paper_list_db(db_path: Path) -> None:
    from research_harness.storage.db import Database

    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO domains (id, name) VALUES (?, ?)", (7, "Systems"))
        conn.execute("INSERT INTO domains (id, name) VALUES (?, ?)", (8, "Theory"))
        conn.execute(
            "INSERT INTO topics (id, name, domain_id) VALUES (?, ?, ?), (?, ?, ?)",
            (42, "systems-topic", 7, 43, "theory-topic", 8),
        )
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
            VALUES (?, ?, ?, ?), (?, ?, ?, ?), (?, ?, ?, ?)
            """,
            (
                1,
                42,
                "high",
                "2026-06-03T09:00:00Z",
                1,
                43,
                "medium",
                "2026-06-03T09:30:00Z",
                2,
                43,
                "low",
                "2026-06-03T10:00:00Z",
            ),
        )
        conn.commit()


def test_paper_list_unscoped_shape_and_domain_filter_are_preserved(tmp_path: Path):
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-list-http.db"
    _seed_paper_list_db(db_path)

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        unscoped = TestClient(http_api.app).get(
            "/api/papers?search=Alpha&sort=title&order=asc"
        )
        domain = TestClient(http_api.app).get(
            "/api/papers?domain_id=7&sort=title&order=asc"
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert unscoped.status_code == 200, unscoped.text
    assert unscoped.json()["pagination"] == {
        "page": 1,
        "per_page": 50,
        "total": 1,
        "total_pages": 1,
    }
    assert unscoped.json()["data"][0]["id"] == 1
    assert unscoped.json()["data"][0]["authors"] == ["Ada", "Ben"]
    assert unscoped.json()["data"][0]["relevance"] is None

    assert domain.status_code == 200, domain.text
    assert domain.json()["pagination"]["total"] == 1
    assert [paper["id"] for paper in domain.json()["data"]] == [1]


def test_paper_list_topic_filter_routes_through_service_preserving_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-list-http-service.db"
    _seed_paper_list_db(db_path)
    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            calls.append((command_name, arguments))
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={"papers": [{"id": 1}, {"id": "not-an-int"}]},
            )

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)
    try:
        response = TestClient(http_api.app).get(
            "/api/papers?topic_id=42&status=deep_read&sort=title&order=asc"
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert calls == [("paper_list", {"topic": "systems-topic"})]
    assert response.json()["pagination"] == {
        "page": 1,
        "per_page": 50,
        "total": 1,
        "total_pages": 1,
    }
    assert response.json()["data"][0]["id"] == 1
    assert response.json()["data"][0]["relevance"] == "high"


def test_paper_list_unknown_topic_returns_empty_without_service_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-list-http-unknown-topic.db"
    _seed_paper_list_db(db_path)

    class FailingResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            raise AssertionError("paper_list service should not be called")

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    monkeypatch.setattr(http_api, "ResearchService", FailingResearchService)
    try:
        response = TestClient(http_api.app).get("/api/papers?topic_id=999")
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 200, response.text
    assert response.json() == {
        "data": [],
        "pagination": {"page": 1, "per_page": 50, "total": 0, "total_pages": 1},
    }
