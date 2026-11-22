"""FastAPI route registration for topic expansion jobs."""

import threading
from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_topic_expansion_routes(
    app: FastAPI,
    *,
    expansion_request_model: type[Any],
    get_db_context: Callable[[], Any],
    topic_exists: Callable[[Any, int], bool],
    get_latest_expansion_job: Callable[[Any, int], Any],
    topic_paper_stats: Callable[[Any, int], dict[str, int]],
    update_expansion_job: Callable[..., None],
    run_expansion_job: Callable[[int, int], None],
    row_to_dict: Callable[[Any], dict[str, Any]],
    now_iso: Callable[[], str],
    thread_factory: Callable[..., Any] = threading.Thread,
) -> None:
    """Register topic expansion routes with injected runtime dependencies."""

    @app.post("/api/topics/{topic_id}/expansion")
    def create_expansion_job(topic_id: int, body: expansion_request_model):
        limits = {
            "retrieval_target": (body.retrieval_target, 500),
            "deep_read_target": (body.deep_read_target, 100),
            "rounds": (body.rounds, 10),
        }
        for field_name, (value, cap) in limits.items():
            if value <= 0 or value > cap:
                raise HTTPException(
                    status_code=400,
                    detail=f"{field_name} must be between 1 and {cap}",
                )

        now = now_iso()
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            active = conn.execute(
                """
                SELECT id FROM expansion_jobs
                WHERE topic_id = ? AND status IN ('pending', 'running')
                LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if active is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "An expansion job is already pending or running for this topic"
                    ),
                )
            cur = conn.execute(
                """
                INSERT INTO expansion_jobs (
                    topic_id, status, retrieval_target, deep_read_target, rounds_target,
                    current_round, papers_fetched, papers_deep_read, last_error,
                    created_at, updated_at
                ) VALUES (?, 'pending', ?, ?, ?, 0, 0, 0, NULL, ?, ?)
                """,
                (
                    topic_id,
                    body.retrieval_target,
                    body.deep_read_target,
                    body.rounds,
                    now,
                    now,
                ),
            )
            conn.commit()
            job_id = int(cur.lastrowid)

        thread = thread_factory(
            target=run_expansion_job,
            args=(job_id, topic_id),
            daemon=True,
            name=f"expansion-job-{job_id}",
        )
        thread.start()
        return {"job_id": job_id, "status": "pending"}

    @app.get("/api/topics/{topic_id}/expansion")
    def get_expansion_job(topic_id: int):
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            row = get_latest_expansion_job(conn, topic_id)
            stats = topic_paper_stats(conn, topic_id)
        if row is None:
            return None
        payload = row_to_dict(row)
        payload["topic_paper_count"] = stats["total"]
        payload["topic_deep_read_count"] = stats["deep_read"]
        return payload

    @app.post("/api/topics/{topic_id}/expansion/cancel")
    def cancel_expansion_job(topic_id: int):
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            row = conn.execute(
                """
                SELECT id FROM expansion_jobs
                WHERE topic_id = ? AND status IN ('pending', 'running')
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail="No pending or running expansion job found",
                )
            update_expansion_job(conn, int(row["id"]), status="cancelled")
        return {"job_id": int(row["id"]), "status": "cancelled"}
