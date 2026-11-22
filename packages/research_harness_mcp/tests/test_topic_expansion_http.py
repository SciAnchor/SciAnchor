"""Focused HTTP tests for topic expansion route extraction."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class _ExpansionRequest(BaseModel):
    retrieval_target: int = Field(default=100)
    deep_read_target: int = Field(default=20)
    rounds: int = Field(default=3)


class _ImmediateThread:
    def __init__(
        self,
        *,
        target: Callable[..., Any],
        args: tuple[Any, ...],
        daemon: bool,
        name: str,
    ) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.name = name

    def start(self) -> None:
        self.target(*self.args)


def test_topic_expansion_module_imports_and_routes_registered():
    from research_harness_mcp import http_api, topic_expansion_http

    assert callable(topic_expansion_http.register_topic_expansion_routes)

    def route_index(path: str, method: str) -> int:
        for index, route in enumerate(http_api.app.routes):
            if route.path == path and method in route.methods:
                return index
        raise AssertionError(f"route not registered: {method} {path}")

    assert (
        route_index("/api/topics/{topic_id}/gate", "GET")
        < route_index("/api/topics/{topic_id}/expansion", "POST")
        < route_index("/api/topics/{topic_id}/expansion", "GET")
        < route_index("/api/topics/{topic_id}/expansion/cancel", "POST")
        < route_index("/api/papers/search", "POST")
    )


def _seed_expansion_topic(db_path: Path, *, topic_id: int = 42) -> None:
    from research_harness.storage.db import Database

    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (topic_id, "exp"))
        conn.commit()


def _build_topic_expansion_client(
    db_path: Path,
) -> tuple[TestClient, list[tuple[int, int]]]:
    from research_harness_mcp import topic_expansion_http

    calls: list[tuple[int, int]] = []

    @contextmanager
    def get_db_context():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def topic_exists(conn: sqlite3.Connection, topic_id: int) -> bool:
        row = conn.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return row is not None

    def get_latest_expansion_job(
        conn: sqlite3.Connection, topic_id: int
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT id, status, retrieval_target, deep_read_target, rounds_target,
                   current_round, papers_fetched, papers_deep_read, last_error,
                   created_at, updated_at
            FROM expansion_jobs
            WHERE topic_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (topic_id,),
        ).fetchone()

    def topic_paper_stats(conn: sqlite3.Connection, topic_id: int) -> dict[str, int]:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(
                    SUM(CASE WHEN COALESCE(p.deep_read, 0) = 1 THEN 1 ELSE 0 END),
                    0
                ) AS deep_read
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
            """,
            (topic_id,),
        ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "deep_read": int(row["deep_read"] or 0),
        }

    def update_expansion_job(
        conn: sqlite3.Connection,
        job_id: int,
        *,
        status: str | None = None,
    ) -> None:
        assert status is not None
        conn.execute(
            "UPDATE expansion_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, "2026-06-13T10:05:00Z", job_id),
        )
        conn.commit()

    def run_expansion_job(job_id: int, topic_id: int) -> None:
        calls.append((job_id, topic_id))

    app = FastAPI()
    topic_expansion_http.register_topic_expansion_routes(
        app,
        expansion_request_model=_ExpansionRequest,
        get_db_context=get_db_context,
        topic_exists=topic_exists,
        get_latest_expansion_job=get_latest_expansion_job,
        topic_paper_stats=topic_paper_stats,
        update_expansion_job=update_expansion_job,
        run_expansion_job=run_expansion_job,
        row_to_dict=dict,
        now_iso=lambda: "2026-06-13T10:00:00Z",
        thread_factory=_ImmediateThread,
    )
    return TestClient(app), calls


def test_topic_expansion_create_preserves_insert_response_and_worker_start(
    tmp_path: Path,
):
    db_path = tmp_path / "topic-expansion-create.db"
    _seed_expansion_topic(db_path)
    client, calls = _build_topic_expansion_client(db_path)

    response = client.post(
        "/api/topics/42/expansion",
        json={"retrieval_target": 12, "deep_read_target": 4, "rounds": 2},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"job_id": 1, "status": "pending"}
    assert calls == [(1, 42)]
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            """
            SELECT topic_id, status, retrieval_target, deep_read_target,
                   rounds_target, current_round, papers_fetched, papers_deep_read,
                   last_error, created_at, updated_at
            FROM expansion_jobs WHERE id = 1
            """
        ).fetchone()
    assert row == (
        42,
        "pending",
        12,
        4,
        2,
        0,
        0,
        0,
        None,
        "2026-06-13T10:00:00Z",
        "2026-06-13T10:00:00Z",
    )


def test_topic_expansion_create_preserves_validation_and_conflict_errors(
    tmp_path: Path,
):
    db_path = tmp_path / "topic-expansion-validation.db"
    _seed_expansion_topic(db_path)
    client, _calls = _build_topic_expansion_client(db_path)

    invalid = client.post(
        "/api/topics/42/expansion",
        json={"retrieval_target": 0, "deep_read_target": 4, "rounds": 2},
    )
    assert invalid.status_code == 400
    assert invalid.json() == {"detail": "retrieval_target must be between 1 and 500"}

    created = client.post(
        "/api/topics/42/expansion",
        json={"retrieval_target": 12, "deep_read_target": 4, "rounds": 2},
    )
    assert created.status_code == 200, created.text

    conflict = client.post(
        "/api/topics/42/expansion",
        json={"retrieval_target": 12, "deep_read_target": 4, "rounds": 2},
    )
    assert conflict.status_code == 409
    assert conflict.json() == {
        "detail": "An expansion job is already pending or running for this topic"
    }


def test_topic_expansion_routes_preserve_missing_topic_errors(tmp_path: Path):
    db_path = tmp_path / "topic-expansion-missing.db"
    from research_harness.storage.db import Database

    Database(db_path).migrate()
    client, _calls = _build_topic_expansion_client(db_path)

    create_response = client.post("/api/topics/999/expansion", json={})
    get_response = client.get("/api/topics/999/expansion")
    cancel_response = client.post("/api/topics/999/expansion/cancel")

    assert create_response.status_code == 404
    assert get_response.status_code == 404
    assert cancel_response.status_code == 404
    assert create_response.json() == {"detail": "Topic 999 not found"}
    assert get_response.json() == {"detail": "Topic 999 not found"}
    assert cancel_response.json() == {"detail": "Topic 999 not found"}


def test_topic_expansion_get_preserves_null_and_count_enriched_payload(
    tmp_path: Path,
):
    db_path = tmp_path / "topic-expansion-get.db"
    _seed_expansion_topic(db_path)
    client, _calls = _build_topic_expansion_client(db_path)

    empty_response = client.get("/api/topics/42/expansion")
    assert empty_response.status_code == 200, empty_response.text
    assert empty_response.json() is None

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO expansion_jobs (
                id, topic_id, status, retrieval_target, deep_read_target,
                rounds_target, current_round, papers_fetched, papers_deep_read,
                last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                7,
                42,
                "completed",
                20,
                5,
                3,
                3,
                18,
                5,
                None,
                "2026-06-13T09:00:00Z",
                "2026-06-13T09:10:00Z",
            ),
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
                "Alpha",
                "[]",
                2026,
                "ICLR",
                "10.2606/alpha",
                "2606.00001",
                "s2-alpha",
                "",
                "",
                0,
                "deep_read",
                "2026-06-13T09:01:00Z",
                1,
                2,
                "Beta",
                "[]",
                2026,
                "ICLR",
                "10.2606/beta",
                "2606.00002",
                "s2-beta",
                "",
                "",
                0,
                "meta_only",
                "2026-06-13T09:02:00Z",
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
                "2026-06-13T09:03:00Z",
                2,
                42,
                "medium",
                "2026-06-13T09:04:00Z",
            ),
        )
        conn.commit()

    response = client.get("/api/topics/42/expansion")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": 7,
        "status": "completed",
        "retrieval_target": 20,
        "deep_read_target": 5,
        "rounds_target": 3,
        "current_round": 3,
        "papers_fetched": 18,
        "papers_deep_read": 5,
        "last_error": None,
        "created_at": "2026-06-13T09:00:00Z",
        "updated_at": "2026-06-13T09:10:00Z",
        "topic_paper_count": 2,
        "topic_deep_read_count": 1,
    }


def test_topic_expansion_cancel_preserves_active_job_update_and_404(
    tmp_path: Path,
):
    db_path = tmp_path / "topic-expansion-cancel.db"
    _seed_expansion_topic(db_path)
    client, _calls = _build_topic_expansion_client(db_path)

    no_job_response = client.post("/api/topics/42/expansion/cancel")
    assert no_job_response.status_code == 404
    assert no_job_response.json() == {
        "detail": "No pending or running expansion job found"
    }

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO expansion_jobs (
                id, topic_id, status, retrieval_target, deep_read_target,
                rounds_target, current_round, papers_fetched, papers_deep_read,
                last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                9,
                42,
                "running",
                20,
                5,
                3,
                1,
                8,
                2,
                None,
                "2026-06-13T09:00:00Z",
                "2026-06-13T09:02:00Z",
            ),
        )
        conn.commit()

    response = client.post("/api/topics/42/expansion/cancel")

    assert response.status_code == 200, response.text
    assert response.json() == {"job_id": 9, "status": "cancelled"}
    with sqlite3.connect(str(db_path)) as conn:
        status = conn.execute(
            "SELECT status FROM expansion_jobs WHERE id = ?", (9,)
        ).fetchone()[0]
    assert status == "cancelled"
