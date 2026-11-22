"""FastAPI route registration for dashboard and read-only usage views."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_papers: int
    total_topics: int
    total_domains: int
    total_artifacts: int
    total_provenance_records: int
    papers_with_pdf: int
    recent_papers: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]


class ProvenanceSummary(BaseModel):
    total_records: int
    total_cost_usd: float
    total_prompt_tokens: int
    total_completion_tokens: int
    by_backend: list[dict[str, Any]]
    by_primitive: list[dict[str, Any]]
    recent_records: list[dict[str, Any]]


def register_dashboard_routes(
    app: FastAPI,
    *,
    db_path_provider: Callable[[], Path],
    get_db_context: Callable[[], Any],
    rows_to_list: Callable[[list[Any]], list[dict[str, Any]]],
    service_factory: Callable[[Path], Any],
) -> None:
    """Register read-only dashboard, usage, provenance, and issue routes."""

    @app.get("/api/stats", response_model=DashboardStats)
    def dashboard_stats():
        with get_db_context() as conn:
            total_papers = conn.execute("SELECT COUNT(*) AS c FROM papers").fetchone()[
                "c"
            ]
            total_topics = conn.execute("SELECT COUNT(*) AS c FROM topics").fetchone()[
                "c"
            ]
            total_domains = conn.execute(
                "SELECT COUNT(*) AS c FROM domains"
            ).fetchone()["c"]
            total_artifacts = conn.execute(
                "SELECT COUNT(*) AS c FROM project_artifacts"
            ).fetchone()["c"]
            total_provenance = conn.execute(
                "SELECT COUNT(*) AS c FROM provenance_records"
            ).fetchone()["c"]
            papers_with_pdf = conn.execute(
                "SELECT COUNT(*) AS c FROM papers WHERE pdf_path IS NOT NULL AND pdf_path != ''"
            ).fetchone()["c"]

            recent_papers = conn.execute(
                """
                SELECT id, title, venue, year, status, created_at
                FROM papers
                ORDER BY created_at DESC
                LIMIT 10
                """
            ).fetchall()

            recent_events = conn.execute(
                """
                SELECT e.id, e.topic_id, e.from_stage, e.to_stage,
                       e.event_type, e.status, e.actor, e.created_at
                FROM orchestrator_stage_events e
                ORDER BY e.created_at DESC
                LIMIT 10
                """
            ).fetchall()

        return DashboardStats(
            total_papers=total_papers,
            total_topics=total_topics,
            total_domains=total_domains,
            total_artifacts=total_artifacts,
            total_provenance_records=total_provenance,
            papers_with_pdf=papers_with_pdf,
            recent_papers=rows_to_list(recent_papers),
            recent_events=rows_to_list(recent_events),
        )

    @app.get("/api/provenance/summary", response_model=ProvenanceSummary)
    def provenance_summary(topic_id: int | None = None):
        """Aggregate provenance metrics, optionally scoped to a single topic."""
        service_args = {"topic_id": topic_id} if topic_id is not None else {}
        where_sql = ""
        params: tuple = ()
        if topic_id is not None:
            where_sql = " WHERE topic_id = ?"
            params = (topic_id,)

        try:
            service_result = service_factory(db_path_provider()).invoke(
                "provenance_summary", service_args
            )
            if service_result.status != "success":
                message = (
                    service_result.error.get("message", service_result.summary)
                    if service_result.error
                    else service_result.summary
                )
                raise HTTPException(status_code=500, detail=message)

            with get_db_context() as conn:
                totals = conn.execute(
                    f"""
                    SELECT COUNT(*) AS total_records,
                           COALESCE(SUM(cost_usd), 0.0) AS total_cost,
                           COALESCE(SUM(prompt_tokens), 0) AS total_prompt,
                           COALESCE(SUM(completion_tokens), 0) AS total_completion
                    FROM provenance_records{where_sql}
                    """,
                    params,
                ).fetchone()

                by_backend = conn.execute(
                    f"""
                    SELECT backend,
                           model_used,
                           COUNT(*) AS call_count,
                           COALESCE(SUM(cost_usd), 0.0) AS total_cost,
                           COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                           COALESCE(SUM(completion_tokens), 0) AS completion_tokens
                    FROM provenance_records{where_sql}
                    GROUP BY backend, model_used
                    ORDER BY total_cost DESC
                    """,
                    params,
                ).fetchall()

                by_primitive = conn.execute(
                    f"""
                    SELECT primitive,
                           COUNT(*) AS call_count,
                           COALESCE(SUM(cost_usd), 0.0) AS total_cost,
                           COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                           COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                           SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
                           SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failure_count
                    FROM provenance_records{where_sql}
                    GROUP BY primitive
                    ORDER BY call_count DESC
                    LIMIT 30
                    """,
                    params,
                ).fetchall()

                recent = conn.execute(
                    f"""
                    SELECT id, primitive, backend, model_used, cost_usd,
                           prompt_tokens, completion_tokens, success, created_at
                    FROM provenance_records{where_sql}
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                    params,
                ).fetchall()

            return ProvenanceSummary(
                total_records=totals["total_records"],
                total_cost_usd=round(totals["total_cost"], 4),
                total_prompt_tokens=totals["total_prompt"] or 0,
                total_completion_tokens=totals["total_completion"] or 0,
                by_backend=rows_to_list(by_backend),
                by_primitive=rows_to_list(by_primitive),
                recent_records=rows_to_list(recent),
            )
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as exc:
            raise HTTPException(
                status_code=500,
                detail="provenance summary query failed",
            ) from exc

    @app.get("/api/usage/daily")
    def usage_daily(
        days: int = Query(30, ge=1, le=365),
        topic_id: int | None = Query(None),
    ):
        """Aggregate daily token usage from both token_ledger and provenance_records."""
        where_parts: list[str] = []
        params: list[Any] = []

        if topic_id is not None:
            where_parts.append("topic_id = ?")
            params.append(topic_id)

        where_sql = (" AND " + " AND ".join(where_parts)) if where_parts else ""

        ledger_rows: list = []
        prov_rows: list = []

        with get_db_context() as conn:
            try:
                ledger_rows = conn.execute(
                    f"""
                    SELECT substr(ts, 1, 10) AS day,
                           SUM(prompt_tokens) AS prompt_tokens,
                           SUM(completion_tokens) AS completion_tokens,
                           COALESCE(SUM(cost_usd), 0.0) AS cost_usd,
                           COUNT(*) AS calls
                    FROM token_ledger
                    WHERE ts >= date('now', '-' || ? || ' days'){where_sql}
                    GROUP BY day ORDER BY day
                    """,
                    [days] + params,
                ).fetchall()
            except sqlite3.OperationalError:
                pass

            try:
                prov_rows = conn.execute(
                    f"""
                    SELECT substr(created_at, 1, 10) AS day,
                           SUM(prompt_tokens) AS prompt_tokens,
                           SUM(completion_tokens) AS completion_tokens,
                           COALESCE(SUM(cost_usd), 0.0) AS cost_usd,
                           COUNT(*) AS calls
                    FROM provenance_records
                    WHERE created_at >= date('now', '-' || ? || ' days'){where_sql}
                    GROUP BY day ORDER BY day
                    """,
                    [days] + params,
                ).fetchall()
            except sqlite3.OperationalError:
                pass

        merged: dict[str, dict] = {}
        for source, rows in [("ledger", ledger_rows), ("provenance", prov_rows)]:
            for r in rows:
                day = r["day"]
                if day not in merged:
                    merged[day] = {
                        "day": day,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "cost_usd": 0.0,
                        "calls": 0,
                    }
                merged[day]["prompt_tokens"] += r["prompt_tokens"] or 0
                merged[day]["completion_tokens"] += r["completion_tokens"] or 0
                merged[day]["cost_usd"] += r["cost_usd"] or 0.0
                merged[day]["calls"] += r["calls"] or 0

        return sorted(merged.values(), key=lambda x: x["day"])

    @app.get("/api/topics/{topic_id}/issues")
    def list_topic_issues(
        topic_id: int,
        status: str | None = Query(
            None, description="Filter: open, in_progress, resolved, wontfix"
        ),
        blocking_only: bool = Query(False),
    ):
        with get_db_context() as conn:
            topic = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not topic:
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

            conditions = ["topic_id = ?"]
            params: list[Any] = [topic_id]

            if status:
                conditions.append("status = ?")
                params.append(status)

            if blocking_only:
                conditions.append("blocking = 1")

            where = " AND ".join(conditions)
            rows = conn.execute(
                f"""
                SELECT *
                FROM review_issues
                WHERE {where}
                ORDER BY created_at DESC
                """,
                params,
            ).fetchall()

        return {"topic_id": topic_id, "issues": rows_to_list(rows)}
