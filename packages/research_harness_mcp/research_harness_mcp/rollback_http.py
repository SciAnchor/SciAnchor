"""FastAPI route registration for topic rollback operations."""

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def _rollback_to_stage(
    conn: Any,
    topic_id: int,
    to_stage: str,
    reason: str,
    *,
    trigger: str,
) -> dict[str, Any]:
    from research_harness.orchestrator.snapshots import rollback_to_stage

    return rollback_to_stage(conn, topic_id, to_stage, reason, trigger=trigger)


def register_rollback_routes(
    app: FastAPI,
    *,
    db_path_provider: Callable[[], Any],
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    rollback_request_model: type[Any],
    rollback_to_stage_fn: Callable[..., dict[str, Any]] | None = None,
) -> None:
    """Register rollback routes with injected runtime dependencies."""

    rollback_impl = rollback_to_stage_fn or _rollback_to_stage

    @app.post("/api/topics/{topic_id}/rollback")
    def rollback_topic(topic_id: int, body: rollback_request_model):
        from research_harness.storage.db import Database

        db = Database(db_path_provider())
        db.migrate()
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Topic not found")

            result = rollback_impl(
                conn, topic_id, body.to_stage, body.reason, trigger="user"
            )
            if not result.get("success"):
                raise HTTPException(
                    status_code=400, detail=result.get("error", "Rollback failed")
                )
        finally:
            conn.close()
        return result

    @app.get("/api/topics/{topic_id}/rollback/log")
    def get_rollback_log(topic_id: int):
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Topic not found")
            rows = conn.execute(
                "SELECT * FROM rollback_log WHERE topic_id = ? ORDER BY created_at DESC",
                (topic_id,),
            ).fetchall()
        return [row_to_dict(r) for r in rows]
