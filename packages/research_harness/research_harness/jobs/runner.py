"""BUG-011: durable background job runner.

Lets a long operation return a ``job_id`` immediately and run in a background
thread, recording status/progress/result in the ``background_jobs`` table so a
caller polls instead of blocking past the MCP transport timeout. Cancellation is
cooperative: the job body checks ``handle.is_cancelled()``.

Each thread opens its own SQLite connection; the DB runs WAL + busy_timeout, so
concurrent writers are safe (same pattern as the acquisition pipeline pool).
"""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Callable

from research_harness.storage.db import Database


class JobHandle:
    """Handle passed to a job body for progress reporting and cancellation."""

    def __init__(self, db: Database, job_id: str) -> None:
        self._db = db
        self.job_id = job_id

    def is_cancelled(self) -> bool:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT status FROM background_jobs WHERE job_id = ?", (self.job_id,)
            ).fetchone()
            return bool(row) and row["status"] == "cancelled"
        finally:
            conn.close()

    def set_progress(self, done: int, total: int = 0) -> None:
        conn = self._db.connect()
        try:
            conn.execute(
                "UPDATE background_jobs SET progress = ?, total = ?, "
                "updated_at = datetime('now') WHERE job_id = ? AND status = 'running'",
                (float(done), int(total), self.job_id),
            )
            conn.commit()
        finally:
            conn.close()


def start_job(db: Database, name: str, fn: Callable[[JobHandle], Any]) -> str:
    """Register a job, run ``fn(handle)`` on a daemon thread, return its id."""
    job_id = uuid.uuid4().hex
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO background_jobs (job_id, name, status) VALUES (?, ?, 'running')",
            (job_id, name),
        )
        conn.commit()
    finally:
        conn.close()

    handle = JobHandle(db, job_id)

    def _run() -> None:
        try:
            result = fn(handle)
            if not handle.is_cancelled():
                _finish(db, job_id, "done", result=result)
        except Exception as exc:  # noqa: BLE001 - surfaced via job status
            _finish(db, job_id, "failed", error=str(exc))

    threading.Thread(target=_run, name=f"rh-job-{name}", daemon=True).start()
    return job_id


def _finish(
    db: Database,
    job_id: str,
    status: str,
    *,
    result: Any = None,
    error: str = "",
) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE background_jobs SET status = ?, result_json = ?, error = ?, "
            "progress = 1.0, updated_at = datetime('now') "
            "WHERE job_id = ? AND status = 'running'",
            (
                status,
                json.dumps(result, ensure_ascii=False, default=str)
                if result is not None
                else "",
                error,
                job_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_job_status(db: Database, job_id: str) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM background_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        result: Any = None
        if row["result_json"]:
            try:
                result = json.loads(row["result_json"])
            except (json.JSONDecodeError, TypeError):
                result = None
        return {
            "job_id": row["job_id"],
            "name": row["name"],
            "status": row["status"],
            "progress": float(row["progress"] or 0.0),
            "total": int(row["total"] or 0),
            "result": result,
            "error": row["error"] or "",
        }
    finally:
        conn.close()


def cancel_job(db: Database, job_id: str) -> bool:
    """Cooperatively cancel a running job. Returns True if it was running."""
    conn = db.connect()
    try:
        cur = conn.execute(
            "UPDATE background_jobs SET status = 'cancelled', "
            "updated_at = datetime('now') WHERE job_id = ? AND status = 'running'",
            (job_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
