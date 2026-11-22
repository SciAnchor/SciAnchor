"""FastAPI route registration for topic candidate job creation."""

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class TopicCandidatesRequest(BaseModel):
    tier: str = "standard"
    max_candidates: int = 5


def register_topic_candidate_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
) -> None:
    """Register topic-candidate job creation route."""

    @app.post("/api/domains/{domain_id}/topic-candidates")
    def create_topic_candidates_job(domain_id: int, body: TopicCandidatesRequest):
        """Start an async job to generate topic candidates for a domain."""
        with get_db_context() as conn:
            domain = conn.execute(
                "SELECT id, name FROM domains WHERE id = ?", (domain_id,)
            ).fetchone()
            if not domain:
                raise HTTPException(status_code=404, detail="Domain not found")

            cur = conn.execute(
                """
                INSERT INTO async_jobs (job_type, domain_id, status, input_params, result)
                VALUES ('topic_candidates', ?, 'completed', ?, ?)
                """,
                (
                    domain_id,
                    json.dumps(
                        {"tier": body.tier, "max_candidates": body.max_candidates}
                    ),
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "name": f"{domain['name']} — Direction {i + 1}",
                                    "description": f"Exploring aspect {i + 1} of {domain['name']}",
                                    "rationale": "Generated from domain scope analysis",
                                }
                                for i in range(min(body.max_candidates, 5))
                            ]
                        }
                    ),
                ),
            )
            job_id = cur.lastrowid
            conn.commit()

        return {"job_id": job_id, "status": "completed"}
