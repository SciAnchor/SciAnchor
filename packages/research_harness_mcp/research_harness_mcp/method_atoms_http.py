"""FastAPI route registration for topic method atoms."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel


class HarvestAtomsRequest(BaseModel):
    paper_ids: list[int]


def _normalize_atom_payload(row: Any, row_to_dict: Callable[[Any], dict[str, Any]]):
    payload = row_to_dict(row)
    if isinstance(payload.get("deps"), str):
        try:
            payload["deps"] = json.loads(payload["deps"])
        except (json.JSONDecodeError, TypeError):
            payload["deps"] = []
    return payload


def register_method_atoms_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    topic_exists: Callable[[Any, int], bool],
    row_to_dict: Callable[[Any], dict[str, Any]],
    db_path_provider: Callable[[], Path],
) -> None:
    """Register method-atoms harvest, list, and delete routes."""

    @app.post("/api/topics/{topic_id}/method-atoms/harvest")
    def harvest_atoms_endpoint(topic_id: int, body: HarvestAtomsRequest):
        """Batch-harvest method atoms from a list of papers."""
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

        if not body.paper_ids:
            raise HTTPException(status_code=400, detail="paper_ids list is empty")

        from research_harness.primitives.harvest_atoms_impl import harvest_atoms_batch
        from research_harness.storage.db import Database

        db = Database(db_path_provider())
        db.migrate()
        summary = harvest_atoms_batch(topic_id, body.paper_ids, db)
        return summary

    @app.get("/api/topics/{topic_id}/method-atoms")
    def list_atoms_endpoint(
        topic_id: int,
        atom_type: str | None = Query(default=None),
    ):
        """List method atoms for a topic, optionally filtered by atom_type."""
        with get_db_context() as conn:
            if not topic_exists(conn, topic_id):
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )
            if atom_type:
                rows = conn.execute(
                    "SELECT * FROM method_atoms WHERE topic_id = ? AND atom_type = ? ORDER BY id",
                    (topic_id, atom_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM method_atoms WHERE topic_id = ? ORDER BY atom_type, id",
                    (topic_id,),
                ).fetchall()
        return [_normalize_atom_payload(row, row_to_dict) for row in rows]

    @app.delete("/api/method-atoms/{atom_id}")
    def delete_atom_endpoint(atom_id: int):
        """Delete a method atom."""
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM method_atoms WHERE id = ?", (atom_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Atom {atom_id} not found")
            conn.execute("DELETE FROM method_atoms WHERE id = ?", (atom_id,))
            conn.commit()
        return {"deleted": atom_id}
