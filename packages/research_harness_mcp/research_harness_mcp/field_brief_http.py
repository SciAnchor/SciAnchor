"""FastAPI route registration for topic field briefs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_field_brief_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    topic_exists: Callable[[Any, int], bool],
    db_path_provider: Callable[[], Path],
) -> None:
    """Register field-brief build and read routes."""

    @app.post("/api/topics/{topic_id}/field-brief")
    def build_field_brief_endpoint(topic_id: int):
        """Build (or rebuild) a field brief from the topic's paper pool."""
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

        from research_harness.primitives.field_brief_impl import build_field_brief
        from research_harness.storage.db import Database

        db = Database(db_path_provider())
        db.migrate()
        try:
            brief = build_field_brief(topic_id, db)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return brief.model_dump()

    @app.get("/api/topics/{topic_id}/field-brief")
    def get_field_brief_endpoint(topic_id: int):
        """Return the latest field brief + freshness meta, or null."""
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

        from research_harness.primitives.field_brief_impl import get_latest_field_brief
        from research_harness.storage.db import Database

        db = Database(db_path_provider())
        db.migrate()
        return get_latest_field_brief(topic_id, db)
