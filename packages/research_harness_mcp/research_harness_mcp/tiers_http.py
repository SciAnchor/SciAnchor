"""FastAPI route registration for budgets, autonomy, and tiers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class CreateBudgetRequest(BaseModel):
    scope: str  # 'global' | 'topic'
    scope_id: int | None = None
    monthly_cap_usd: float
    hard_stop: int = 1


class PatchBudgetRequest(BaseModel):
    monthly_cap_usd: float | None = None
    hard_stop: int | None = None

    model_config = {"extra": "forbid"}


class PatchAutonomyRequest(BaseModel):
    level: str = Field(pattern=r"^L[0-3]$")


class PatchTierRequest(BaseModel):
    tier: str = Field(pattern=r"^(economy|standard|premium)$")


def register_tier_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    rows_to_list: Callable[[list[Any]], list[dict[str, Any]]],
) -> None:
    """Register budget, autonomy, and tier routes."""

    @app.get("/api/budgets")
    def list_budgets():
        with get_db_context() as conn:
            rows = conn.execute(
                "SELECT * FROM budgets ORDER BY scope, scope_id"
            ).fetchall()
        return rows_to_list(rows)

    @app.post("/api/budgets", status_code=201)
    def create_budget(body: CreateBudgetRequest):
        now = datetime.now(timezone.utc).isoformat()
        with get_db_context() as conn:
            cur = conn.execute(
                """
                INSERT INTO budgets (scope, scope_id, monthly_cap_usd, hard_stop, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (body.scope, body.scope_id, body.monthly_cap_usd, body.hard_stop, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM budgets WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return row_to_dict(row)

    @app.patch("/api/budgets/{budget_id}")
    def update_budget(budget_id: int, body: PatchBudgetRequest):
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            raise HTTPException(status_code=400, detail="No fields to update")

        with get_db_context() as conn:
            existing = conn.execute(
                "SELECT id FROM budgets WHERE id = ?", (budget_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(
                    status_code=404, detail=f"Budget {budget_id} not found"
                )

            allowed = {"monthly_cap_usd", "hard_stop"}
            updates = {k: v for k, v in patch.items() if k in allowed and v is not None}
            if not updates:
                raise HTTPException(status_code=400, detail="No valid fields")

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            params = list(updates.values()) + [budget_id]
            conn.execute(f"UPDATE budgets SET {set_clause} WHERE id = ?", params)
            conn.commit()
            row = conn.execute(
                "SELECT * FROM budgets WHERE id = ?", (budget_id,)
            ).fetchone()
        return row_to_dict(row)

    @app.get("/api/topics/{topic_id}/autonomy")
    def get_topic_autonomy(topic_id: int):
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id, autonomy_level FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Topic not found")
            auto_row = conn.execute(
                "SELECT * FROM topic_autonomy WHERE topic_id = ?", (topic_id,)
            ).fetchone()
        return {
            "topic_id": topic_id,
            "level": row["autonomy_level"] or "L2",
            "overrides": row_to_dict(auto_row) if auto_row else None,
        }

    @app.patch("/api/topics/{topic_id}/autonomy")
    def patch_topic_autonomy(topic_id: int, body: PatchAutonomyRequest):
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Topic not found")
            conn.execute(
                "UPDATE topics SET autonomy_level = ? WHERE id = ?",
                (body.level, topic_id),
            )
            conn.execute(
                """
                INSERT INTO topic_autonomy (topic_id, level)
                VALUES (?, ?)
                ON CONFLICT(topic_id) DO UPDATE SET
                    level = excluded.level,
                    updated_at = datetime('now')
                """,
                (topic_id, body.level),
            )
            conn.commit()
        return {"topic_id": topic_id, "level": body.level}

    @app.get("/api/topics/{topic_id}/tier")
    def get_topic_tier(topic_id: int):
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id, quality_tier, target_venue_tier FROM topics WHERE id = ?",
                (topic_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Topic not found")
        from research_harness.tiers import get_tier

        cfg = get_tier(row["quality_tier"])
        return {
            "topic_id": topic_id,
            "quality_tier": row["quality_tier"] or "standard",
            "target_venue_tier": row["target_venue_tier"] or "B",
            "config": {
                "judge_mode": cfg.judge_mode,
                "retries": cfg.retries_after_rubric_miss,
                "rubric_dimensions": cfg.rubric_dimensions,
                "cost_estimate": cfg.cost_estimate_usd,
            },
        }

    @app.patch("/api/topics/{topic_id}/tier")
    def patch_topic_tier(topic_id: int, body: PatchTierRequest):
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Topic not found")
            conn.execute(
                "UPDATE topics SET quality_tier = ? WHERE id = ?",
                (body.tier, topic_id),
            )
            conn.commit()
        return {"topic_id": topic_id, "quality_tier": body.tier}
