"""FastAPI route registration for topic intake profiles."""

from __future__ import annotations

from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class IntakeProfileBody(BaseModel):
    persona: Literal[
        "p1_no_domain", "p2_domain_no_topic", "p3_topic_weak", "p4_topic_strong"
    ]
    domain_confidence: int = Field(ge=0, le=100)
    topic_confidence: int = Field(ge=0, le=100)
    venue_constraint: Literal["locked", "preferred", "open"]
    target_venue: str | None = None
    compute_budget: Literal["cpu_only", "single_gpu", "multi_gpu", "cluster"]
    time_to_deadline_days: int | None = None
    seed_present: int = 0
    raw_notes: str | None = None


def register_intake_profile_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    run_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> None:
    """Register intake-profile read and upsert routes."""

    @app.get("/api/topics/{topic_id}/intake-profile")
    def get_intake_profile(topic_id: int):
        with get_db_context() as conn:
            topic = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not topic:
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            row = conn.execute(
                "SELECT * FROM topic_intake_profile WHERE topic_id = ?", (topic_id,)
            ).fetchone()
            if not row:
                return None
        return row_to_dict(row)

    @app.put("/api/topics/{topic_id}/intake-profile")
    def put_intake_profile(topic_id: int, body: IntakeProfileBody):
        with get_db_context() as conn:
            topic = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not topic:
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            conn.execute(
                """INSERT INTO topic_intake_profile
                   (topic_id, persona, domain_confidence, topic_confidence,
                    venue_constraint, target_venue, compute_budget,
                    time_to_deadline_days, seed_present, raw_notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(topic_id) DO UPDATE SET
                     persona = excluded.persona,
                     domain_confidence = excluded.domain_confidence,
                     topic_confidence = excluded.topic_confidence,
                     venue_constraint = excluded.venue_constraint,
                     target_venue = excluded.target_venue,
                     compute_budget = excluded.compute_budget,
                     time_to_deadline_days = excluded.time_to_deadline_days,
                     seed_present = excluded.seed_present,
                     raw_notes = excluded.raw_notes,
                     updated_at = CURRENT_TIMESTAMP""",
                (
                    topic_id,
                    body.persona,
                    body.domain_confidence,
                    body.topic_confidence,
                    body.venue_constraint,
                    body.target_venue,
                    body.compute_budget,
                    body.time_to_deadline_days,
                    body.seed_present,
                    body.raw_notes,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM topic_intake_profile WHERE topic_id = ?", (topic_id,)
            ).fetchone()

        run_tool(
            "orchestrator_record_artifact",
            {
                "topic_id": topic_id,
                "artifact_type": "intake_profile",
                "title": "Intake Profile",
                "payload": body.model_dump(),
                "stage": "init",
            },
        )

        return row_to_dict(row)
