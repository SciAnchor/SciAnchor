"""FastAPI route registration for experiment matrix workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class ProxyPassRequest(BaseModel):
    max_cells: int = Field(default=20, ge=1, le=100)


def _normalize_matrix_payload(row: Any, row_to_dict: Callable[[Any], dict[str, Any]]):
    payload = row_to_dict(row)
    if isinstance(payload.get("atom_combo"), str):
        try:
            payload["atom_combo"] = json.loads(payload["atom_combo"])
        except (json.JSONDecodeError, TypeError):
            payload["atom_combo"] = []
    return payload


def register_experiment_matrix_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    topic_exists: Callable[[Any, int], bool],
    row_to_dict: Callable[[Any], dict[str, Any]],
    db_path_provider: Callable[[], Path],
) -> None:
    """Register experiment-matrix build, proxy, and list routes."""

    @app.post("/api/topics/{topic_id}/experiment-matrix/build")
    def build_matrix_endpoint(topic_id: int):
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

        from research_harness.primitives.experiment_matrix_impl import build_matrix
        from research_harness.storage.db import Database

        db = Database(db_path_provider())
        db.migrate()
        try:
            cells = build_matrix(topic_id, db)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return [c.model_dump() for c in cells]

    @app.post("/api/topics/{topic_id}/experiment-matrix/proxy")
    def run_proxy_endpoint(topic_id: int, body: ProxyPassRequest):
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

        from research_harness.primitives.experiment_matrix_impl import run_proxy_pass
        from research_harness.storage.db import Database

        db = Database(db_path_provider())
        db.migrate()
        try:
            cells = run_proxy_pass(topic_id, db, max_cells=body.max_cells)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return [c.model_dump() for c in cells]

    @app.get("/api/topics/{topic_id}/experiment-matrix")
    def get_matrix_endpoint(topic_id: int):
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            rows = conn.execute(
                "SELECT * FROM experiment_matrix_cell WHERE topic_id = ? ORDER BY goal_id, id",
                (topic_id,),
            ).fetchall()
        return [_normalize_matrix_payload(row, row_to_dict) for row in rows]
