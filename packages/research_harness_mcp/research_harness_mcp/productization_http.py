"""FastAPI route registration for local health and productization boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from research_harness._productization import build_lg10_productization_boundary_payload

_PRODUCTIZATION_API_CACHE_CONTROL = "private, no-store"


def _productization_api_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers={"Cache-Control": _PRODUCTIZATION_API_CACHE_CONTROL},
    )


def register_productization_routes(
    app: FastAPI, *, db_path_provider: Callable[[], Path]
) -> None:
    """Register local health and productization boundary endpoints."""

    @app.get("/api/health")
    def health_check():
        """Basic liveness probe."""
        db_path = db_path_provider()
        exists = db_path.exists()
        return {"status": "ok" if exists else "db_missing", "db_path": str(db_path)}

    @app.get("/api/productization/boundary")
    def get_productization_boundary(
        experimental_lg10: bool = Query(default=False),
    ):
        """Show the opt-in LG10 public-productization boundary preview."""
        if not experimental_lg10:
            return _productization_api_error_response(
                status_code=403,
                code="lg10_opt_in_required",
                message="pass experimental_lg10=true to view the LG10 boundary",
            )

        return JSONResponse(
            content=build_lg10_productization_boundary_payload(
                scope="public-http-opt-in-preview"
            ),
            headers={"Cache-Control": _PRODUCTIZATION_API_CACHE_CONTROL},
        )
