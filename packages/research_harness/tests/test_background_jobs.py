"""BUG-011: durable background job runner (job_id + progress + cancel)."""

from __future__ import annotations

import threading
import time


from research_harness.jobs import cancel_job, get_job_status, start_job


def _wait_terminal(db, job_id, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = get_job_status(db, job_id)
        if status and status["status"] != "running":
            return status
        time.sleep(0.02)
    return get_job_status(db, job_id)


def test_background_job_completes_with_result(db):
    def work(handle):
        handle.set_progress(1, 2)
        return {"value": 42}

    job_id = start_job(db, "search", work)
    assert isinstance(job_id, str) and job_id

    status = _wait_terminal(db, job_id)
    assert status["status"] == "done"
    assert status["result"] == {"value": 42}
    assert status["progress"] == 1.0


def test_background_job_records_failure(db):
    def boom(_handle):
        raise ValueError("provider exploded")

    job_id = start_job(db, "boom", boom)
    status = _wait_terminal(db, job_id)
    assert status["status"] == "failed"
    assert "provider exploded" in status["error"]


def test_background_job_can_be_cancelled(db):
    started = threading.Event()
    release = threading.Event()

    def slow(handle):
        started.set()
        release.wait(2.0)
        if handle.is_cancelled():
            return None
        return {"finished": True}

    job_id = start_job(db, "slow", slow)
    assert started.wait(1.0)
    assert cancel_job(db, job_id) is True
    release.set()

    status = _wait_terminal(db, job_id)
    assert status["status"] == "cancelled"


def test_unknown_job_id_returns_none(db):
    assert get_job_status(db, "does-not-exist") is None
