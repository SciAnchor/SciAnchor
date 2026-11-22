"""FastAPI route registration for domain detail reads."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_domain_detail_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    domain_detail_model: type[Any],
    topic_summary_model: type[Any],
) -> None:
    """Register domain detail route with injected runtime dependencies."""

    @app.get("/api/domains/{domain_id}", response_model=domain_detail_model)
    def get_domain(domain_id: int):
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT * FROM domains WHERE id = ?", (domain_id,)
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=404, detail=f"Domain {domain_id} not found"
                )

            topic_rows = conn.execute(
                """
                SELECT t.*,
                       d.name AS domain_name,
                       COUNT(pt.paper_id) AS paper_count
                FROM topics t
                LEFT JOIN domains d ON d.id = t.domain_id
                LEFT JOIN paper_topics pt ON pt.topic_id = t.id
                WHERE t.domain_id = ?
                GROUP BY t.id
                ORDER BY t.id
                """,
                (domain_id,),
            ).fetchall()

        topics = [
            topic_summary_model(
                id=topic_row["id"],
                name=topic_row["name"],
                description=topic_row["description"] or "",
                status=topic_row["status"] or "active",
                target_venue=topic_row["target_venue"] or "",
                deadline=topic_row["deadline"] or "",
                created_at=topic_row["created_at"] or "",
                paper_count=topic_row["paper_count"],
                domain_id=topic_row["domain_id"],
                domain_name=topic_row["domain_name"],
            )
            for topic_row in topic_rows
        ]

        return domain_detail_model(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            status=row["status"] or "active",
            created_at=row["created_at"] or "",
            topics=topics,
        )
