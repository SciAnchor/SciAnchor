"""FastAPI route registration for algorithm candidate generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from pydantic import BaseModel


class AlgorithmCandidateRequest(BaseModel):
    focus: str | None = None
    n_candidates: int = 3
    brief: dict[str, Any] | None = None


def register_algorithm_candidate_routes(
    app: FastAPI,
    *,
    run_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
    db_path_provider: Callable[[], Path],
    get_db_context: Callable[[], Any],
) -> None:
    """Register algorithm-candidate route with injected runtime dependencies."""

    @app.post("/api/topics/{topic_id}/algorithm-candidates")
    def generate_algorithm_candidates(topic_id: int, body: AlgorithmCandidateRequest):
        """Generate algorithm improvement candidates by combinatorial innovation."""
        brief = body.brief or {
            "topic_id": topic_id,
            "focus": body.focus or "",
            "n_candidates": body.n_candidates,
        }
        # Auto-fetch deep_read notes so the LLM has richer context.
        deep_read_notes: list[dict[str, Any]] = []
        try:
            from research_harness.execution.compiled_summary import (
                ensure_compiled_summary,
                format_compiled_for_context,
            )
            from research_harness.storage.db import Database

            db = Database(db_path=db_path_provider())
            with get_db_context() as conn:
                rows = conn.execute(
                    """
                    SELECT p.id, p.title FROM papers p
                    JOIN paper_topics pt ON pt.paper_id = p.id
                    WHERE pt.topic_id = ? AND p.deep_read = 1
                    ORDER BY p.id DESC LIMIT 10
                    """,
                    (topic_id,),
                ).fetchall()
            for row in rows:
                compiled = ensure_compiled_summary(db, int(row["id"]))
                ctx = format_compiled_for_context(compiled)
                if ctx.strip():
                    deep_read_notes.append(
                        {
                            "paper_id": row["id"],
                            "title": row["title"],
                            "notes": ctx[:500],
                        }
                    )
        except Exception:
            pass
        args: dict[str, Any] = {
            "topic_id": topic_id,
            "brief": brief,
            "deep_read_notes": deep_read_notes or None,
        }
        if body.focus:
            args["focus"] = body.focus
        return run_tool("algorithm_candidate_generate", args)
