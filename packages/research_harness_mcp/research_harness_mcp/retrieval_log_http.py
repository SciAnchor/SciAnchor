"""FastAPI route registration for topic retrieval-log reads."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_retrieval_log_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    topic_exists: Callable[[Any, int], bool],
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
) -> None:
    """Register read-only retrieval-log routes."""

    @app.get("/api/topics/{topic_id}/retrieval-log")
    def get_retrieval_log(topic_id: int):
        """Return retrieval log entries for a topic, newest first."""
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            rows = conn.execute(
                """SELECT * FROM retrieval_log
                   WHERE topic_id = ?
                   ORDER BY created_at DESC""",
                (topic_id,),
            ).fetchall()
        result = []
        for row in rows:
            entry = row_to_dict(row)
            if isinstance(entry.get("ingested_paper_ids"), str):
                entry["ingested_paper_ids"] = parse_json_field(
                    entry["ingested_paper_ids"], []
                )
            result.append(entry)
        return result
