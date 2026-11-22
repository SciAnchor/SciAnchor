"""Focused tests for the extracted topic expansion background job runner."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _seed_expansion_job_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE topics (
                id INTEGER PRIMARY KEY,
                name TEXT,
                description TEXT
            );
            CREATE TABLE papers (
                id INTEGER PRIMARY KEY,
                title TEXT,
                doi TEXT,
                arxiv_id TEXT,
                url TEXT,
                year INTEGER,
                deep_read INTEGER
            );
            CREATE TABLE paper_topics (
                paper_id INTEGER,
                topic_id INTEGER,
                relevance TEXT
            );
            CREATE TABLE expansion_jobs (
                id INTEGER PRIMARY KEY,
                topic_id INTEGER,
                status TEXT,
                retrieval_target INTEGER,
                deep_read_target INTEGER,
                rounds_target INTEGER,
                current_round INTEGER,
                papers_fetched INTEGER,
                papers_deep_read INTEGER,
                last_error TEXT,
                updated_at TEXT
            );
            INSERT INTO topics (id, name, description)
            VALUES (7, 'Retrieval Agents', 'Survey methods');
            INSERT INTO expansion_jobs (
                id, topic_id, status, retrieval_target, deep_read_target,
                rounds_target, current_round, papers_fetched, papers_deep_read,
                last_error, updated_at
            )
            VALUES (1, 7, 'pending', 1, 0, 1, 0, 0, 0, NULL, 'old');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_topic_expansion_job_runner_preserves_fetch_progress_and_completion(
    tmp_path: Path,
) -> None:
    from research_harness_mcp import topic_expansion_helpers
    from research_harness_mcp.topic_expansion_job import run_expansion_job

    db_path = tmp_path / "expansion-job.db"
    _seed_expansion_job_db(db_path)
    api_paths: list[Path] = []
    search_calls: list[dict[str, Any]] = []
    ingest_calls: list[dict[str, Any]] = []

    @contextmanager
    def get_db_context():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    class FakeApi:
        pass

    def api_factory(*, db_path: Path) -> FakeApi:
        api_paths.append(db_path)
        return FakeApi()

    def update_expansion_job(
        conn: sqlite3.Connection,
        job_id: int,
        **kwargs: Any,
    ) -> None:
        topic_expansion_helpers.update_expansion_job(
            conn,
            job_id,
            now_iso=lambda: "2026-06-14T06:30:00Z",
            **kwargs,
        )

    def expansion_job_is_cancelled(job_id: int) -> bool:
        return topic_expansion_helpers.expansion_job_is_cancelled(
            job_id,
            get_db_context=get_db_context,
        )

    def search_papers_impl(
        api: FakeApi,
        *,
        query: str,
        topic_id: int,
        max_results: int,
    ) -> dict[str, Any]:
        search_calls.append(
            {
                "api": api,
                "query": query,
                "topic_id": topic_id,
                "max_results": max_results,
            }
        )
        return {
            "papers": [
                {
                    "title": "Expansion Candidate",
                    "doi": "10.2606/expansion",
                    "year": 2026,
                }
            ],
            "provider_errors": [],
        }

    def ingest_paper_impl(
        api: FakeApi,
        *,
        source: str,
        topic_id: int,
        relevance: str,
    ) -> dict[str, Any]:
        ingest_calls.append(
            {"api": api, "source": source, "topic_id": topic_id, "relevance": relevance}
        )
        with get_db_context() as conn:
            conn.execute(
                """
                INSERT INTO papers (id, title, doi, arxiv_id, url, year, deep_read)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (101, "Expansion Candidate", source, "", "", 2026, 0),
            )
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
                (101, topic_id, relevance),
            )
            conn.commit()
        return {"paper_id": 101}

    run_expansion_job(
        1,
        7,
        db_path=db_path,
        api_factory=api_factory,
        get_db_context=get_db_context,
        update_expansion_job=update_expansion_job,
        expansion_job_is_cancelled=expansion_job_is_cancelled,
        build_expansion_query=topic_expansion_helpers.build_expansion_query,
        search_papers_impl=search_papers_impl,
        ingest_paper_impl=ingest_paper_impl,
        deep_read_paper_impl=lambda *args, **kwargs: {"model_used": "none"},
        pick_candidate_source=topic_expansion_helpers.pick_candidate_source,
        paper_already_in_topic=topic_expansion_helpers.paper_already_in_topic,
        deep_read_provider_pool=lambda: [""],
        expansion_deep_read_concurrency=lambda _pool_size: 1,
        expansion_deep_read_paper_timeout=lambda: 30.0,
    )

    assert api_paths == [db_path]
    assert search_calls[0]["query"] == "Retrieval Agents Survey methods"
    assert search_calls[0]["topic_id"] == 7
    assert search_calls[0]["max_results"] == 1
    assert ingest_calls == [
        {
            "api": search_calls[0]["api"],
            "source": "10.2606/expansion",
            "topic_id": 7,
            "relevance": "high",
        }
    ]
    with get_db_context() as conn:
        job = conn.execute("SELECT * FROM expansion_jobs WHERE id = 1").fetchone()
        assert job is not None
        assert job["status"] == "completed"
        assert job["current_round"] == 1
        assert job["papers_fetched"] == 1
        assert job["papers_deep_read"] == 0
        assert job["last_error"] == ""
        assert job["updated_at"] == "2026-06-14T06:30:00Z"
