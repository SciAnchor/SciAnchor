"""FastAPI route registration for single-paper metadata enrichment."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_paper_enrich_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
) -> None:
    """Register single-paper metadata enrich route."""

    @app.post("/api/papers/{paper_id}/enrich")
    def enrich_paper(paper_id: int):
        """Enrich a single paper's metadata via Semantic Scholar."""
        from research_harness.core.paper_pool import PaperPool

        with get_db_context() as conn:
            pool = PaperPool(conn)
            row = conn.execute(
                "SELECT id FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Paper not found")
            result = pool.enrich_metadata(paper_id)
        return {"paper_id": paper_id, "fields_updated": result}
