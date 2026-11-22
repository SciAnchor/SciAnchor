"""FastAPI route registration for async job polling."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_job_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[..., Any],
) -> None:
    """Register async job polling route."""

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int):
        """Poll an async job status."""
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT * FROM async_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Job not found")
        job = row_to_dict(row)
        if isinstance(job.get("result"), str):
            job["result"] = parse_json_field(job["result"])
        if isinstance(job.get("input_params"), str):
            job["input_params"] = parse_json_field(job["input_params"])
        return job
