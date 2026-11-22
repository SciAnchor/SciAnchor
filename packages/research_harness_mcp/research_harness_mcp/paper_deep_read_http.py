"""FastAPI route registration for paper deep-read actions."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_paper_deep_read_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    api_factory: Callable[[], Any],
    deep_read_paper_impl: Callable[..., dict[str, Any]],
) -> None:
    """Register paper deep-read route with injected runtime dependencies."""

    @app.patch("/api/papers/{paper_id}/deep-read")
    def toggle_deep_read(paper_id: int, body: dict[str, Any] | None = None):
        with get_db_context() as conn:
            row = conn.execute(
                """
                SELECT p.id, pt.topic_id
                FROM papers p
                LEFT JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE p.id = ?
                ORDER BY pt.topic_id
                LIMIT 1
                """,
                (paper_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Paper not found")
            topic_id = body.get("topic_id") if body else None
            if topic_id is None:
                topic_id = row["topic_id"]
            if topic_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="topic_id is required for deep-read when paper has no topic",
                )
        api = api_factory()
        output = deep_read_paper_impl(api, paper_id=paper_id, topic_id=int(topic_id))
        return {"success": True, "deep_read": True, "output": output}
