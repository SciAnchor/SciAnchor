"""FastAPI route registration for workflow-memory recall."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_memory_routes(
    app: FastAPI,
    *,
    db_path_provider: Callable[[], Path],
    logger: logging.Logger | None = None,
) -> None:
    """Register workflow-memory recall routes on an existing FastAPI app."""

    route_logger = logger or logging.getLogger(__name__)

    @app.post("/api/memory/recall")
    def memory_recall(body: dict[str, Any]):
        """v2 Step 8 - workflow memory recall.

        Body: { query: str, exclude_topic_id?: int, top_k?: int,
                max_age_days?: int, require_success?: bool }
        """
        from research_harness.memory import recall_similar_runs

        query = str(body.get("query", "")).strip()
        if not query:
            return {"query": query, "hits": []}
        try:
            from research_harness.storage.db import Database as _DB

            db = _DB(Path(str(db_path_provider())))
            hits = recall_similar_runs(
                db,
                query,
                exclude_topic_id=body.get("exclude_topic_id"),
                top_k=int(body.get("top_k", 5)),
                max_age_days=body.get("max_age_days", 90),
                require_success=bool(body.get("require_success", True)),
            )
        except Exception as exc:
            route_logger.error(
                "memory_recall failed: %s\n%s", exc, traceback.format_exc()
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return {
            "query": query,
            "hits": [
                {
                    "topic_id": h.topic_id,
                    "topic_name": h.topic_name,
                    "description": h.description,
                    "created_at": h.created_at,
                    "score": h.score,
                    "lexical_score": h.lexical_score,
                    "provenance_success_count": h.provenance_success_count,
                    "decision_highlights": h.decision_highlights,
                }
                for h in hits
            ],
        }
