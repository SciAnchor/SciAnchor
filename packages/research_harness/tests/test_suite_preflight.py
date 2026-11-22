"""E1 (2026-09-28): the suite refuses the three runs that wasted full suites."""

import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
PKG = Path(__file__).resolve().parents[1]
PY = os.environ.get("PYTHON") or sys.executable
LIVE = str(Path.home() / ".research-harness" / "pool.db")


def _collect(cwd, *, db=None, extra=None):
    env = {k: v for k, v in os.environ.items() if k != "RESEARCH_HARNESS_DB_PATH"}
    if db is not None:
        env["RESEARCH_HARNESS_DB_PATH"] = db
    env.update(extra or {})
    return subprocess.run(
        # Not this file: collecting it from inside an xdist worker inherits the
        # worker env, and the check then sees the worker's copy of the db.
        [
            PY,
            "-m",
            "pytest",
            "-q",
            "--collect-only",
            str(PKG / "tests/test_acquisition_contracts.py"),
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def test_refuses_when_cwd_is_not_the_package_dir():
    result = _collect(REPO)
    text = result.stdout + result.stderr
    assert result.returncode != 0, text
    assert "cwd" in text


def test_refuses_when_db_path_is_the_live_pool():
    result = _collect(PKG, db=LIVE)
    text = result.stdout + result.stderr
    assert result.returncode != 0, text
    assert "live pool" in text


def test_a_clean_run_is_not_refused(tmp_path):
    result = _collect(PKG, db=str(tmp_path / "pool.db"))
    assert result.returncode in (0, 5), result.stdout + result.stderr


def test_serial_marker_keeps_timing_tests_out_of_xdist():
    env = {k: v for k, v in os.environ.items() if k != "RESEARCH_HARNESS_DB_PATH"}
    result = subprocess.run(
        [
            PY,
            "-m",
            "pytest",
            "-q",
            "--collect-only",
            "-m",
            "serial",
            "--override-ini",
            "addopts=",
            "--ignore=tests/test_eag_batch2.py",
            "--ignore=tests/test_eag_section_arcs.py",
            "--ignore=tests/test_hitl_objectivity.py",
        ],
        cwd=PKG,
        env=env,
        capture_output=True,
        text=True,
    )
    text = result.stdout + result.stderr
    assert result.returncode == 0, text
    assert (
        "test_threads_of_one_process_share_the_clock_without_queueing_behind_a_process_lock"
        in text
    )
    assert "test_open_to_half_open_after_cooldown" in text
