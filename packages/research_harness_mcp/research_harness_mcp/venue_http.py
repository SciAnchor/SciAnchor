"""FastAPI route registration for venue decision and style kit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def _normalize_json_fields(
    row: Any, row_to_dict: Callable[[Any], dict[str, Any]], fields: tuple[str, ...]
):
    payload = row_to_dict(row)
    for field in fields:
        if isinstance(payload.get(field), str):
            try:
                payload[field] = json.loads(payload[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return payload


def register_venue_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    topic_exists: Callable[[Any, int], bool],
    row_to_dict: Callable[[Any], dict[str, Any]],
    db_path_provider: Callable[[], Path],
) -> None:
    """Register venue-decision and venue-style-kit routes."""

    @app.post("/api/topics/{topic_id}/venue-decision")
    def venue_decision_endpoint(topic_id: int):
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

        from research_harness.primitives.venue_decision_impl import decide_venue
        from research_harness.storage.db import Database

        db = Database(db_path_provider())
        db.migrate()
        try:
            decision = decide_venue(topic_id, db)
        except RuntimeError as exc:
            detail = str(exc)
            if "not found" in detail.lower():
                raise HTTPException(status_code=409, detail=detail) from exc
            raise HTTPException(status_code=500, detail=detail) from exc
        return decision.model_dump()

    @app.get("/api/topics/{topic_id}/venue-decision")
    def get_venue_decision_endpoint(topic_id: int):
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            row = conn.execute(
                "SELECT * FROM venue_decision WHERE topic_id = ?", (topic_id,)
            ).fetchone()
        if not row:
            return None
        return _normalize_json_fields(
            row,
            row_to_dict,
            ("decision_basis", "fit_risk", "source_venues"),
        )

    @app.post("/api/topics/{topic_id}/venue-style-kit")
    def build_style_kit_endpoint(topic_id: int):
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

        from research_harness.primitives.venue_decision_impl import build_style_kit
        from research_harness.storage.db import Database

        db = Database(db_path_provider())
        db.migrate()
        try:
            kit = build_style_kit(topic_id, db)
        except RuntimeError as exc:
            detail = str(exc)
            if "not found" in detail.lower() or "need at least" in detail.lower():
                raise HTTPException(status_code=409, detail=detail) from exc
            raise HTTPException(status_code=500, detail=detail) from exc
        return kit.model_dump()

    @app.get("/api/topics/{topic_id}/venue-style-kit")
    def get_style_kit_endpoint(topic_id: int):
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            row = conn.execute(
                "SELECT * FROM venue_style_kit WHERE topic_id = ?", (topic_id,)
            ).fetchone()
        if not row:
            return None
        return _normalize_json_fields(
            row,
            row_to_dict,
            (
                "avg_section_lengths",
                "hedging_terms",
                "source_paper_ids",
                "source_venues",
            ),
        )
