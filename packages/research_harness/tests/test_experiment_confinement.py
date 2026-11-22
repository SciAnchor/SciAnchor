"""Model-generated experiment code runs under an OS confinement boundary, or does not run."""

from __future__ import annotations

import hashlib
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_harness.experiment import confine
from research_harness.experiment.sandbox import run_experiment

RH_COPY = Path(confine.__file__)
REPO_ROOT = Path(__file__).resolve().parents[3]
seatbelt = pytest.mark.skipif(
    sys.platform != "darwin" or not confine.SANDBOX_EXEC.is_file(),
    reason="Seatbelt (macOS sandbox-exec) not available",
)


# confine.py is security-sensitive: an edit has to update this pin on purpose.
PINNED_SHA256 = "f0ea5cdd65e0102e8101a6935695a69d1e1980d484219ae42523b45c8a07f2c3"


def test_rh_confine_matches_its_pin():
    assert hashlib.sha256(RH_COPY.read_bytes()).hexdigest() == PINNED_SHA256, (
        f"{RH_COPY} changed: review the confinement change, then update PINNED_SHA256"
    )


@seatbelt
def test_experiment_cannot_write_outside_its_root(tmp_path):
    outside = tmp_path / "outside.txt"
    code = (
        f"open({str(tmp_path / 'work' / 'inside.txt')!r}, 'w').write('1')\n"
        "try:\n"
        f"    open({str(outside)!r}, 'w').write('escaped')\n"
        "    print('write: escaped')\n"
        "except OSError:\n"
        "    print('write: denied')\n"
    )
    result = run_experiment(code, timeout_sec=30.0, work_dir=tmp_path / "work")
    assert result.returncode == 0, result.stderr
    assert "write: denied" in result.stdout
    assert not outside.exists()
    assert (tmp_path / "work" / "inside.txt").is_file()


@seatbelt
def test_experiment_cannot_open_a_socket(tmp_path):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    code = (
        "import socket\n"
        "try:\n"
        f"    socket.create_connection(('127.0.0.1', {port}), 3)\n"
        "    print('net: reached')\n"
        "except OSError:\n"
        "    print('net: denied')\n"
    )
    try:
        result = run_experiment(code, timeout_sec=30.0, work_dir=tmp_path / "work")
    finally:
        server.close()
    assert "net: denied" in result.stdout, (result.stdout, result.stderr)


@seatbelt
def test_experiment_cannot_fork(tmp_path):
    code = (
        "import os\n"
        "try:\n"
        "    pid = os.fork()\n"
        "    if pid == 0:\n"
        "        os._exit(0)\n"
        "    print('fork: allowed')\n"
        "except OSError:\n"
        "    print('fork: denied')\n"
    )
    result = run_experiment(code, timeout_sec=30.0, work_dir=tmp_path / "work")
    assert "fork: denied" in result.stdout, (result.stdout, result.stderr)


@pytest.mark.parametrize("platform", ["freebsd14", "win32"])
def test_unsupported_platform_refuses_before_running(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(confine, "sys", SimpleNamespace(platform=platform))
    marker = tmp_path / "work" / "ran.txt"
    with pytest.raises(confine.ConfinementUnavailable, match="refusing to run"):
        run_experiment(
            f"open({str(marker)!r}, 'w').write('1')\n", work_dir=tmp_path / "work"
        )
    assert not marker.exists()


def test_linux_without_a_verified_bwrap_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(confine, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(confine, "BWRAP", tmp_path / "no-bwrap")
    monkeypatch.setattr(confine, "_bwrap_verified", False)
    marker = tmp_path / "work" / "ran.txt"
    with pytest.raises(confine.ConfinementUnavailable, match="bwrap unavailable"):
        run_experiment(
            f"open({str(marker)!r}, 'w').write('1')\n", work_dir=tmp_path / "work"
        )
    assert not marker.exists()
