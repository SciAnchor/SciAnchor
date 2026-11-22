"""FastAPI route registration for local paper PDF reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def register_paper_pdf_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    pdf_roots_provider: Callable[[], list[Path]],
) -> None:
    """Register local PDF streaming routes."""

    @app.get("/api/papers/{paper_id}/pdf")
    def get_paper_pdf(paper_id: int):
        """Stream the PDF file for a paper, if locally available and trusted."""
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT pdf_path, title FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")

        raw = (row["pdf_path"] or "").strip()
        if not raw:
            raise HTTPException(status_code=404, detail="No PDF on file for this paper")

        try:
            candidate = Path(raw).expanduser().resolve()
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid pdf_path: {exc}")

        pdf_roots = pdf_roots_provider()
        if not pdf_roots:
            raise HTTPException(
                status_code=500,
                detail="No allowed PDF roots configured (set RESEARCH_HARNESS_PDF_ROOTS)",
            )

        if not any(candidate.is_relative_to(root) for root in pdf_roots):
            raise HTTPException(
                status_code=403,
                detail="PDF path is outside the allowed roots",
            )

        if not candidate.is_file():
            raise HTTPException(
                status_code=404,
                detail="PDF path is recorded but the file is missing on disk",
            )

        return FileResponse(
            candidate,
            media_type="application/pdf",
            filename=candidate.name,
            headers={"Cache-Control": "private, max-age=3600"},
        )
