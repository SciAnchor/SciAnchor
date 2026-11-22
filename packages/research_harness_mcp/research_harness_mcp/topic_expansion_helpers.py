"""Private helper functions shared by topic expansion HTTP wiring."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any


def pick_candidate_source(candidate: dict[str, Any]) -> str:
    for key in ("arxiv_id", "doi", "url", "title"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return ""


def search_papers_impl(
    api: Any,
    *,
    query: str,
    topic_id: int | None = None,
    max_results: int = 50,
    serialize_result: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    args: dict[str, Any] = {"query": query, "max_results": max_results}
    if topic_id is not None:
        args["topic_id"] = topic_id
    return serialize_result(api.paper_search(**args))


def ingest_paper_impl(
    api: Any,
    *,
    source: str,
    topic_id: int | None = None,
    relevance: str = "medium",
    serialize_result: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    args: dict[str, Any] = {"source": source, "relevance": relevance}
    if topic_id is not None:
        args["topic_id"] = topic_id
    return serialize_result(api.paper_ingest(**args))


def deep_read_paper_impl(
    *,
    paper_id: int,
    topic_id: int,
    focus: str = "",
    execute_tool_fn: Callable[[str, dict[str, Any]], Any],
    get_db_context: Callable[[], AbstractContextManager[sqlite3.Connection]],
    serialize_result: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    args: dict[str, Any] = {"paper_id": paper_id, "topic_id": topic_id}
    if focus:
        args["focus"] = focus
    result = execute_tool_fn("deep_read", args)
    with get_db_context() as conn:
        conn.execute(
            "UPDATE papers SET deep_read = 1 WHERE id = ?",
            (paper_id,),
        )
        conn.commit()
    return serialize_result(result)


def find_paper_id_in_topic_by_source(
    conn: sqlite3.Connection, topic_id: int, source: str
) -> int | None:
    source = str(source or "").strip()
    if not source:
        return None
    clause, params = _paper_source_clause(topic_id, source)
    row = conn.execute(
        f"""
        SELECT p.id
        FROM papers p
        JOIN paper_topics pt ON pt.paper_id = p.id
        WHERE pt.topic_id = ? AND ({clause})
        ORDER BY p.id ASC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return int(row["id"]) if row else None


def paper_already_in_topic(
    conn: sqlite3.Connection, topic_id: int, source: str
) -> bool:
    clause, params = _paper_source_clause(topic_id, source)
    row = conn.execute(
        f"""
        SELECT 1
        FROM papers p
        JOIN paper_topics pt ON pt.paper_id = p.id
        WHERE pt.topic_id = ? AND ({clause})
        LIMIT 1
        """,
        params,
    ).fetchone()
    return row is not None


def build_expansion_query(
    conn: sqlite3.Connection, topic_id: int, topic_name: str, topic_description: str
) -> str:
    base = " ".join(
        part.strip() for part in (topic_name, topic_description) if part.strip()
    )
    row_limit = 5
    rows = conn.execute(
        """
        SELECT p.title
        FROM papers p
        JOIN paper_topics pt ON pt.paper_id = p.id
        WHERE pt.topic_id = ?
        ORDER BY CASE pt.relevance
                    WHEN 'high' THEN 3
                    WHEN 'medium' THEN 2
                    ELSE 1
                 END DESC,
                 COALESCE(p.year, 0) DESC,
                 p.id DESC
        LIMIT ?
        """,
        (topic_id, row_limit),
    ).fetchall()
    phrases: list[str] = []
    for row in rows:
        title = str(row["title"] or "").strip()
        if not title:
            continue
        words = [word for word in title.split() if len(word) > 3][:6]
        phrase = " ".join(words).strip()
        if phrase:
            phrases.append(phrase)
    return (
        "\n".join(part for part in [base, *phrases[:3]] if part).strip() or topic_name
    )


def latest_expansion_job(conn: sqlite3.Connection, topic_id: int) -> sqlite3.Row | None:
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


def expansion_job_is_cancelled(
    job_id: int,
    *,
    get_db_context: Callable[[], AbstractContextManager[sqlite3.Connection]],
) -> bool:
    with get_db_context() as conn:
        row = conn.execute(
            "SELECT status FROM expansion_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return row is not None and row["status"] == "cancelled"


def update_expansion_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    now_iso: Callable[[], str],
    status: str | None = None,
    current_round: int | None = None,
    papers_fetched: int | None = None,
    papers_deep_read: int | None = None,
    last_error: str | None = None,
) -> None:
    updates: dict[str, Any] = {"updated_at": now_iso()}
    if status is not None:
        updates["status"] = status
    if current_round is not None:
        updates["current_round"] = current_round
    if papers_fetched is not None:
        updates["papers_fetched"] = papers_fetched
    if papers_deep_read is not None:
        updates["papers_deep_read"] = papers_deep_read
    if last_error is not None:
        updates["last_error"] = last_error[:2000]
    set_clause = ", ".join(f"{key} = ?" for key in updates)
    conn.execute(
        f"UPDATE expansion_jobs SET {set_clause} WHERE id = ?",
        [*updates.values(), job_id],
    )
    conn.commit()


def topic_paper_stats(conn: sqlite3.Connection, topic_id: int) -> dict[str, int]:
    """Return total and deep-read paper counts for a topic."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN COALESCE(p.deep_read, 0) = 1 THEN 1 ELSE 0 END), 0) AS deep_read
        FROM papers p
        JOIN paper_topics pt ON pt.paper_id = p.id
        WHERE pt.topic_id = ?
        """,
        (topic_id,),
    ).fetchone()
    if row is None:
        return {"total": 0, "deep_read": 0}
    return {"total": int(row["total"] or 0), "deep_read": int(row["deep_read"] or 0)}


def deep_read_provider_pool(
    *, available_providers: Callable[[], list[str]] | None = None
) -> list[str]:
    """Build the agent pool used to fan out expansion deep-reads."""
    override = os.environ.get("RESEARCH_HARNESS_DEEP_READ_PROVIDERS", "").strip()
    if override:
        pool = [
            provider.strip() for provider in override.split(",") if provider.strip()
        ]
        if pool:
            return pool
    if available_providers is None:
        try:
            from llm_router import available_providers as available_providers
        except Exception:
            return [""]
    pool = available_providers()
    return pool or [""]


def expansion_deep_read_concurrency(pool_size: int) -> int:
    """Max concurrent deep-read workers."""
    raw = os.environ.get("RESEARCH_HARNESS_DEEP_READ_CONCURRENCY", "").strip()
    if raw:
        try:
            concurrency = int(raw)
            if concurrency >= 1:
                return min(concurrency, 16)
        except ValueError:
            pass
    return min(8, max(2, max(1, pool_size) * 2))


def expansion_deep_read_paper_timeout() -> float:
    """Wall-clock cap per deep-read paper, in seconds."""
    raw = os.environ.get("RESEARCH_HARNESS_DEEP_READ_TIMEOUT", "").strip()
    if raw:
        try:
            timeout_seconds = int(raw)
            if timeout_seconds >= 30:
                return float(timeout_seconds)
        except ValueError:
            pass
    return 300.0


def _paper_source_clause(topic_id: int, source: str) -> tuple[str, list[Any]]:
    if source.startswith("10."):
        return "p.doi = ?", [topic_id, source]
    if "/" not in source and len(source) < 20:
        return "p.arxiv_id = ?", [topic_id, source]
    return "p.title = ? OR p.url = ?", [topic_id, source, source]
