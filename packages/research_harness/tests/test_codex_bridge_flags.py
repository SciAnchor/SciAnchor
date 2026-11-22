"""The codex exec flag set moves between CLI releases.

`--full-auto` existed through ~0.1.x and is gone by 0.147. Passing it makes
every call exit 2 with the prompt unread, and the caller reports a fallback
rather than a misconfiguration — so the review silently runs without codex.
"""

from __future__ import annotations

import subprocess

from research_harness.auto_runner import codex_bridge


def _fake_run(stdout: str):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return run


def test_probe_detects_a_supported_flag(monkeypatch):
    codex_bridge._codex_exec_supports.cache_clear()
    monkeypatch.setattr(subprocess, "run", _fake_run("  -s, --sandbox <MODE>\n"))
    assert codex_bridge._codex_exec_supports("codex", "--sandbox") is True


def test_probe_rejects_a_removed_flag(monkeypatch):
    codex_bridge._codex_exec_supports.cache_clear()
    monkeypatch.setattr(subprocess, "run", _fake_run("  -s, --sandbox <MODE>\n"))
    assert codex_bridge._codex_exec_supports("codex", "--full-auto") is False


def test_probe_failure_degrades_to_false(monkeypatch):
    codex_bridge._codex_exec_supports.cache_clear()

    def boom(cmd, **kwargs):
        raise OSError("codex not executable")

    monkeypatch.setattr(subprocess, "run", boom)
    # A probe that cannot run must not raise into the review path.
    assert codex_bridge._codex_exec_supports("codex", "--sandbox") is False
