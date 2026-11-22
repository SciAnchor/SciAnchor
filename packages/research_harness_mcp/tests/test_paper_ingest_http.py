"""Focused HTTP tests for paper ingest and batch-enrich route extraction."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel


class _PaperIngestRequest(BaseModel):
    source: str
    topic_id: int | None = None
    relevance: str = "medium"


class _BatchEnrichRequest(BaseModel):
    topic_id: int | None = None
    missing_fields: list[str] = ["venue", "citation_count"]
    limit: int = 50


def test_paper_ingest_module_imports_and_routes_registered():
    from research_harness_mcp import http_api, paper_ingest_http

    assert callable(paper_ingest_http.register_paper_ingest_routes)
    assert callable(paper_ingest_http.register_paper_enrich_batch_routes)

    def route_index(path: str, method: str) -> int:
        for index, route in enumerate(http_api.app.routes):
            if route.path == path and method in route.methods:
                return index
        raise AssertionError(f"route not registered: {method} {path}")

    assert (
        route_index("/api/papers/ingest", "POST")
        < route_index("/api/papers/{paper_id}/enrich", "POST")
        < route_index("/api/papers/enrich-batch", "POST")
    )


def _build_paper_ingest_client(
    db_path: Path,
) -> tuple[TestClient, list[tuple[str, int | None, str]]]:
    from research_harness_mcp import paper_ingest_http

    calls: list[tuple[str, int | None, str]] = []

    @contextmanager
    def get_db_context():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def ingest_paper_impl(
        _api: object,
        *,
        source: str,
        topic_id: int | None = None,
        relevance: str = "medium",
    ) -> dict[str, Any]:
        calls.append((source, topic_id, relevance))
        return {"paper_id": 123, "source": source}

    app = FastAPI()
    paper_ingest_http.register_paper_ingest_routes(
        app,
        paper_ingest_request_model=_PaperIngestRequest,
        api_factory=lambda: object(),
        ingest_paper_impl=ingest_paper_impl,
        get_db_context=get_db_context,
    )
    return TestClient(app), calls


def test_paper_ingest_preserves_response_and_stale_field_brief_update(
    tmp_path: Path,
):
    db_path = tmp_path / "paper-ingest.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE field_brief_meta (
                topic_id INTEGER PRIMARY KEY,
                paper_count_at_build INTEGER NOT NULL,
                stale INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("CREATE TABLE paper_topics (paper_id INTEGER, topic_id INTEGER)")
        conn.execute(
            """
            INSERT INTO field_brief_meta
                (topic_id, paper_count_at_build, stale)
            VALUES (?, ?, ?)
            """,
            (7, 10, 0),
        )
        conn.executemany(
            "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
            [(paper_id, 7) for paper_id in range(1, 13)],
        )
        conn.commit()

    client, calls = _build_paper_ingest_client(db_path)

    response = client.post(
        "/api/papers/ingest",
        json={"source": "10.2606/test", "topic_id": 7, "relevance": "high"},
    )

    assert response.status_code == 200, response.text
    assert calls == [("10.2606/test", 7, "high")]
    assert response.json() == {
        "status": "success",
        "summary": "Ingested paper 123",
        "output": {"paper_id": 123, "source": "10.2606/test"},
    }
    with sqlite3.connect(str(db_path)) as conn:
        stale = conn.execute(
            "SELECT stale FROM field_brief_meta WHERE topic_id = ?", (7,)
        ).fetchone()[0]
    assert stale == 1


def test_paper_ingest_stale_tracking_errors_remain_non_critical(tmp_path: Path):
    db_path = tmp_path / "paper-ingest-no-stale-tables.db"
    client, calls = _build_paper_ingest_client(db_path)

    response = client.post(
        "/api/papers/ingest",
        json={"source": "2606.00001", "topic_id": 9},
    )

    assert response.status_code == 200, response.text
    assert calls == [("2606.00001", 9, "medium")]
    assert response.json()["summary"] == "Ingested paper 123"


def _build_paper_enrich_batch_client(
    db_path: Path,
    failure: Exception | None = None,
) -> tuple[TestClient, list[int]]:
    from research_harness_mcp import paper_ingest_http

    enriched: list[int] = []
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(
            (
                Path(__file__).parents[2]
                / "research_harness/migrations/040_async_jobs.sql"
            ).read_text()
        )

    @contextmanager
    def get_db_context():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    class _FakePaperPool:
        def __init__(self, _conn: sqlite3.Connection) -> None:
            pass

        def enrich_metadata(self, paper_id: int) -> None:
            if failure is not None:
                raise failure
            enriched.append(paper_id)

    app = FastAPI()
    paper_ingest_http.register_paper_enrich_batch_routes(
        app,
        batch_enrich_request_model=_BatchEnrichRequest,
        get_db_context=get_db_context,
        paper_pool_factory=_FakePaperPool,
        sleep_fn=lambda _seconds: None,
    )
    from research_harness_mcp.jobs_http import register_job_routes

    register_job_routes(
        app,
        get_db_context=get_db_context,
        row_to_dict=dict,
        parse_json_field=json.loads,
    )
    return TestClient(app), enriched


def test_paper_enrich_batch_preserves_response_and_selection_filters(
    tmp_path: Path,
):
    db_path = tmp_path / "paper-enrich-batch.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE papers (
                id INTEGER PRIMARY KEY,
                arxiv_id TEXT,
                doi TEXT,
                s2_id TEXT,
                venue TEXT,
                citation_count INTEGER
            )
            """
        )
        conn.execute("CREATE TABLE paper_topics (paper_id INTEGER, topic_id INTEGER)")
        conn.executemany(
            """
            INSERT INTO papers
                (id, arxiv_id, doi, s2_id, venue, citation_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "2606.00001", "", "", "arxiv", 0),
                (2, "", "10.2606/two", "", "ICLR", 0),
                (3, "", "", "", "arxiv", 0),
                (4, "", "", "s2-four", "NeurIPS", 10),
            ],
        )
        conn.executemany(
            "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
            [(paper_id, 7) for paper_id in range(1, 5)],
        )
        conn.commit()

    client, enriched = _build_paper_enrich_batch_client(db_path)

    response = client.post(
        "/api/papers/enrich-batch",
        json={
            "topic_id": 7,
            "missing_fields": ["venue", "citation_count"],
            "limit": 2,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "job_id": response.json()["job_id"],
        "status": "started",
        "limit": 2,
        "missing_fields": ["venue", "citation_count"],
    }
    assert enriched == [2, 1]

    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "completed"
    assert job["result"] == {"enriched_count": 2}


def test_paper_enrich_batch_reports_spc_failure_in_existing_job(tmp_path):
    from research_harness.acquisition.spc_bridge import SPCAcquisitionError

    db_path = tmp_path / "failed.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY, arxiv_id TEXT, doi TEXT, s2_id TEXT, venue TEXT, citation_count INTEGER)"
        )
        conn.execute("INSERT INTO papers VALUES (1, '2606.00001', '', '', 'arxiv', 0)")
    failure = SPCAcquisitionError(
        "lookup",
        {"error": {"code": "rate_limited", "retryable": True, "message": "secret"}},
    )
    client, enriched = _build_paper_enrich_batch_client(db_path, failure)
    response = client.post("/api/papers/enrich-batch", json={"limit": 2})
    assert response.status_code == 200
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "failed"
    assert json.loads(job["error"]) == {"code": "rate_limited", "retryable": True}
    assert "secret" not in str(job)
    assert enriched == []
