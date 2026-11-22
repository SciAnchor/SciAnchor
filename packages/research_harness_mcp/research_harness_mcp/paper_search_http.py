"""FastAPI route registration for paper search."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import FastAPI
from pydantic import BaseModel, Field


class PaperSearchRequest(BaseModel):
    query: str
    topic_id: int | None = None
    max_results: int = Field(default=50, ge=1, le=200)
    stage: str | None = None
    trigger_reason: str | None = None


def register_paper_search_routes(
    app: FastAPI,
    *,
    api_factory: Callable[[], Any],
    search_papers_impl: Callable[..., dict[str, Any]],
    get_db_context: Callable[[], Any],
    logger: logging.Logger,
) -> None:
    """Register paper-search route and retrieval-log side effect."""

    @app.post("/api/papers/search")
    def search_papers(body: PaperSearchRequest):
        """Search for papers via configured providers."""
        api = api_factory()
        output = search_papers_impl(
            api,
            query=body.query,
            topic_id=body.topic_id,
            max_results=body.max_results,
        )

        results_count = len(output.get("papers") or [])

        # Write retrieval_log if all three context fields are present.
        if body.topic_id is not None and body.stage and body.trigger_reason:
            valid_reasons = {
                "missing_evidence",
                "weak_baseline",
                "new_atom_idea",
                "venue_pattern",
                "user_request",
            }
            if body.trigger_reason in valid_reasons:
                try:
                    with get_db_context() as conn:
                        conn.execute(
                            """INSERT INTO retrieval_log
                               (topic_id, stage, trigger_reason, query, results_count)
                               VALUES (?, ?, ?, ?, ?)""",
                            (
                                body.topic_id,
                                body.stage,
                                body.trigger_reason,
                                body.query,
                                results_count,
                            ),
                        )
                        conn.commit()
                except Exception:
                    logger.warning("Failed to write retrieval_log", exc_info=True)

        return {
            "status": "success",
            "summary": f"Found {results_count} papers",
            "output": output,
        }
