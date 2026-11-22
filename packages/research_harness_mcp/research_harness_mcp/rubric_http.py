"""FastAPI route registration for rubric calibration and score endpoints."""

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class CalibrationRunRequest(BaseModel):
    stage: str | None = None  # None = calibrate all stages
    tier: str | None = None  # None = calibrate all tiers (only with stage=None)
    venue_tier: str = "B"

    model_config = {"extra": "forbid"}


def register_rubric_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
) -> None:
    """Register rubric calibration and score endpoints."""

    @app.get("/api/calibrations")
    def list_calibrations():
        """Return all rubric calibration rows (stage x tier x threshold + stats)."""
        with get_db_context() as conn:
            rows = conn.execute(
                "SELECT stage, tier, threshold, false_rollback_rate, reject_rate,"
                " anchor_count, calibrated_at FROM rubric_calibrations"
                " ORDER BY stage, tier"
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    @app.post("/api/calibrations/run")
    def run_calibration(body: CalibrationRunRequest | None = None):
        """Recalibrate thresholds from the bundled anchor corpus.

        Pass no body (or stage=null) to calibrate every (stage x tier) combination.
        """
        from research_harness.calibration import calibrate_all, calibrate_stage_tier

        payload = body or CalibrationRunRequest()
        with get_db_context() as conn:
            if payload.stage is None:
                results = calibrate_all(conn)
            else:
                tier = payload.tier or "standard"
                results = [
                    calibrate_stage_tier(
                        conn,
                        payload.stage,
                        tier,
                        venue_tier=payload.venue_tier,
                    )
                ]
        return {
            "count": len(results),
            "results": [
                {
                    "stage": r.stage,
                    "tier": r.tier,
                    "threshold": r.threshold,
                    "anchor_count": r.anchor_count,
                    "false_rollback_rate": r.false_rollback_rate,
                    "reject_rate": r.reject_rate,
                    "used_default": r.used_default,
                }
                for r in results
            ],
        }

    @app.get("/api/topics/{topic_id}/rubric-scores")
    def get_rubric_scores(topic_id: int, stage: str | None = None):
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Topic not found")
            if stage:
                rows = conn.execute(
                    "SELECT * FROM rubric_scores WHERE topic_id = ? AND stage = ? ORDER BY scored_at DESC",
                    (topic_id, stage),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM rubric_scores WHERE topic_id = ? ORDER BY scored_at DESC",
                    (topic_id,),
                ).fetchall()
        results = []
        for r in rows:
            d = row_to_dict(r)
            if isinstance(d.get("dimension_scores"), str):
                d["dimension_scores"] = json.loads(d["dimension_scores"])
            if isinstance(d.get("critique"), str):
                d["critique"] = json.loads(d["critique"])
            if isinstance(d.get("evidence_refs"), str):
                d["evidence_refs"] = json.loads(d["evidence_refs"])
            results.append(d)
        return results
