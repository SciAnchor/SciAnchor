"""Refuse a suite that would waste a run or touch real data.

Two conditions, each named in the message: cwd is not the suite root, and
RESEARCH_HARNESS_DB_PATH is the live pool (RH's global default database).
"""
import os
import subprocess
from pathlib import Path

import pytest

LIVE_POOL = Path.home() / ".research-harness" / "pool.db"


def refuse_bad_suite_run(root: Path) -> None:
    """``root`` is where the suite must be invoked from: the repo root, or the
    package directory when that is what the suite's imports require."""
    if Path.cwd().resolve() != Path(root).resolve():
        raise pytest.UsageError(
            f"cwd is {Path.cwd()}, not {root}; refusing the suite"
        )
    db = os.environ.get("RESEARCH_HARNESS_DB_PATH")
    if db and Path(db).expanduser().resolve() == LIVE_POOL.resolve():
        raise pytest.UsageError(
            f"RESEARCH_HARNESS_DB_PATH is the live pool {LIVE_POOL}; refusing the suite"
        )


def copy_worker_db(worker: str | None = None) -> None:
    """Point this xdist worker at its own copy of RESEARCH_HARNESS_DB_PATH."""
    worker = worker or os.environ.get("PYTEST_XDIST_WORKER")
    db = os.environ.get("RESEARCH_HARNESS_DB_PATH")
    if not worker or not db or not Path(db).is_file():
        return
    source = Path(db)
    # pytest_configure fires again after the copy is installed. A spawned suite
    # inherits PYTEST_XDIST_WORKER too, and its worker ids collide with the
    # parent's, so the guard is this process, not the name.
    # ponytail: one copy per worker, per-file locks if two suites share a db name.
    if os.environ.get("E1_DB_COPIED_BY") == str(os.getpid()):
        return
    copy = source.with_name(f"{source.stem}.{worker}{source.suffix}")
    os.environ["E1_DB_COPIED_BY"] = str(os.getpid())
    if not copy.exists():
        subprocess.run(["cp", "-c", str(source), str(copy)], check=True)
    os.environ["RESEARCH_HARNESS_DB_PATH"] = str(copy)
