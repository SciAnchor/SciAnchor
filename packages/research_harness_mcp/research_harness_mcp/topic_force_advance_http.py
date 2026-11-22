"""FastAPI route registration for topic force-advance."""

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_topic_force_advance_routes(
    app: FastAPI,
    *,
    force_advance_request_model: type[Any],
    get_db_context: Callable[[], Any],
) -> None:
    """Register topic force-advance route with injected runtime dependencies."""

    @app.post("/api/topics/{topic_id}/force-advance")
    def force_advance_topic(topic_id: int, body: force_advance_request_model):
        """Force-advance a topic to the next (or specified) stage, skipping gate checks.

        This is for demo / development use. In production, use /advance which
        respects artifact gates.
        """
        stages = ["init", "build", "analyze", "propose", "experiment", "write"]
        with get_db_context() as conn:
            run = conn.execute(
                """
                SELECT id, current_stage FROM orchestrator_runs
                WHERE topic_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if not run:
                raise HTTPException(
                    status_code=404,
                    detail=f"No orchestrator run found for topic {topic_id}",
                )
            current = run["current_stage"] or "init"
            if body.target_stage:
                next_stage = body.target_stage
            else:
                idx = stages.index(current) if current in stages else 0
                next_stage = stages[min(idx + 1, len(stages) - 1)]
            conn.execute(
                "UPDATE orchestrator_runs SET current_stage = ?, "
                "stage_status = 'in_progress', updated_at = datetime('now') "
                "WHERE id = ?",
                (next_stage, run["id"]),
            )
            conn.commit()
        return {
            "topic_id": topic_id,
            "previous_stage": current,
            "current_stage": next_stage,
        }
