"""FastAPI route registration for topic goal pools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class PatchGoalRequest(BaseModel):
    status: Literal["active", "done", "skipped"] | None = None
    priority_rank: int | None = None


def _normalize_goal_payload(row: Any, row_to_dict: Callable[[Any], dict[str, Any]]):
    payload = row_to_dict(row)
    if isinstance(payload.get("scoring_breakdown"), str):
        try:
            payload["scoring_breakdown"] = json.loads(payload["scoring_breakdown"])
        except (json.JSONDecodeError, TypeError):
            pass
    return payload


def register_goal_pool_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    topic_exists: Callable[[Any, int], bool],
    row_to_dict: Callable[[Any], dict[str, Any]],
    db_path_provider: Callable[[], Path],
) -> None:
    """Register goal-pool build, list, update, and soft-delete routes."""

    @app.post("/api/topics/{topic_id}/goal-pool")
    def build_goal_pool_endpoint(topic_id: int):
        """Build (or rebuild) the goal pool for a topic. Requires field_brief + intake_profile."""
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

        from research_harness.primitives.goal_pool_impl import build_goal_pool
        from research_harness.storage.db import Database

        db = Database(db_path_provider())
        db.migrate()
        try:
            goals = build_goal_pool(topic_id, db)
        except RuntimeError as exc:
            detail = str(exc)
            if "not found" in detail.lower():
                raise HTTPException(status_code=409, detail=detail) from exc
            raise HTTPException(status_code=500, detail=detail) from exc
        return [g.model_dump() for g in goals]

    @app.get("/api/topics/{topic_id}/goals")
    def list_goals_endpoint(topic_id: int):
        """List goal pool entries by priority_rank ascending."""
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            rows = conn.execute(
                "SELECT * FROM goal_pool WHERE topic_id = ? AND status != 'skipped' ORDER BY priority_rank ASC",
                (topic_id,),
            ).fetchall()
        return [_normalize_goal_payload(row, row_to_dict) for row in rows]

    @app.patch("/api/topics/{topic_id}/goals/{goal_id}")
    def update_goal_endpoint(topic_id: int, goal_id: int, body: PatchGoalRequest):
        """Update a goal's status or priority_rank."""
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            raise HTTPException(status_code=400, detail="No fields to update")

        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM goal_pool WHERE id = ? AND topic_id = ?",
                (goal_id, topic_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")

            sets = []
            vals = []
            for key, value in patch.items():
                sets.append(f"{key} = ?")
                vals.append(value)
            sets.append("updated_at = CURRENT_TIMESTAMP")
            vals.append(goal_id)
            conn.execute(
                f"UPDATE goal_pool SET {', '.join(sets)} WHERE id = ?",
                vals,
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM goal_pool WHERE id = ?", (goal_id,)
            ).fetchone()
        return _normalize_goal_payload(updated, row_to_dict)

    @app.delete("/api/topics/{topic_id}/goals/{goal_id}")
    def delete_goal_endpoint(topic_id: int, goal_id: int):
        """Soft-delete a goal (set status='skipped')."""
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM goal_pool WHERE id = ? AND topic_id = ?",
                (goal_id, topic_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
            conn.execute(
                "UPDATE goal_pool SET status = 'skipped', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (goal_id,),
            )
            conn.commit()
        return {"status": "skipped", "goal_id": goal_id}
