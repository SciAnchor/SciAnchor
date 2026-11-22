"""FastAPI route registration for domain listing."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI


def register_domain_list_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    domain_summary_model: type[Any],
) -> None:
    """Register domain listing route with injected runtime dependencies."""

    @app.get("/api/domains", response_model=list[domain_summary_model])
    def list_domains():
        with get_db_context() as conn:
            rows = conn.execute(
                """
                SELECT d.*,
                       COUNT(t.id) AS topic_count
                FROM domains d
                LEFT JOIN topics t ON t.domain_id = d.id
                GROUP BY d.id
                ORDER BY d.id
                """
            ).fetchall()
        return [
            domain_summary_model(
                id=row["id"],
                name=row["name"],
                description=row["description"] or "",
                status=row["status"] or "active",
                topic_count=row["topic_count"],
                created_at=row["created_at"] or "",
            )
            for row in rows
        ]
