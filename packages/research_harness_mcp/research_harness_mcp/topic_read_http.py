"""FastAPI route registration for read-only topic detail side panels."""

from __future__ import annotations

import sqlite3
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query


def register_topic_read_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
) -> None:
    """Register topic artifacts, events, and decisions read routes."""

    @app.get("/api/topics/{topic_id}/artifacts")
    def list_topic_artifacts(
        topic_id: int,
        stage: str | None = Query(None, description="Filter by stage"),
    ):
        with get_db_context() as conn:
            topic = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not topic:
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

            conditions = ["topic_id = ?"]
            params: list[Any] = [topic_id]
            if stage:
                conditions.append("stage = ?")
                params.append(stage)

            where = " AND ".join(conditions)
            rows = conn.execute(
                f"""
                SELECT id, project_id, topic_id, stage, artifact_type, status,
                       version, title, path, payload_json, metadata_json,
                       parent_artifact_id, created_at, updated_at
                FROM project_artifacts
                WHERE {where}
                ORDER BY stage, created_at DESC
                """,
                params,
            ).fetchall()

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            artifact = row_to_dict(row)
            artifact["payload"] = parse_json_field(
                artifact.pop("payload_json", None), {}
            )
            artifact["metadata"] = parse_json_field(
                artifact.pop("metadata_json", None), {}
            )
            grouped.setdefault(artifact["stage"], []).append(artifact)

        return {"topic_id": topic_id, "artifacts_by_stage": grouped}

    @app.get("/api/topics/{topic_id}/events")
    def list_topic_events(topic_id: int):
        with get_db_context() as conn:
            topic = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not topic:
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

            rows = conn.execute(
                """
                SELECT e.*
                FROM orchestrator_stage_events e
                WHERE e.topic_id = ?
                ORDER BY e.created_at DESC
                """,
                (topic_id,),
            ).fetchall()

        events = []
        for row in rows:
            event = row_to_dict(row)
            event["payload"] = parse_json_field(event.pop("payload_json", None), {})
            events.append(event)

        return {"topic_id": topic_id, "events": events}

    @app.get("/api/topics/{topic_id}/decisions")
    def list_topic_decisions(topic_id: int):
        """Return decision_log entries for this topic, newest first."""
        with get_db_context() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT id, project_id, topic_id, stage, checkpoint, choice,
                           reasoning, params_snapshot, created_at, actor, origin
                    FROM decision_log
                    WHERE topic_id = ?
                    ORDER BY created_at DESC
                    """,
                    (topic_id,),
                ).fetchall()
            except sqlite3.OperationalError:
                # Legacy DBs pre-migration 055: fall back to the smaller column set.
                try:
                    rows = conn.execute(
                        """
                        SELECT id, project_id, topic_id, stage, checkpoint, choice,
                               reasoning, params_snapshot, created_at
                        FROM decision_log
                        WHERE topic_id = ?
                        ORDER BY created_at DESC
                        """,
                        (topic_id,),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []

        decisions = []
        for row in rows:
            decision = row_to_dict(row)
            decision["params"] = parse_json_field(
                decision.pop("params_snapshot", None), {}
            )
            decision.setdefault("actor", None)
            decision.setdefault("origin", None)
            decisions.append(decision)

        return {"topic_id": topic_id, "decisions": decisions}
