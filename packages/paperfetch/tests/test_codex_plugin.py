from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "spc"


def _load_preflight():
    path = PLUGIN / "scripts" / "spc_preflight.py"
    spec = importlib.util.spec_from_file_location("spc_plugin_preflight", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_is_skill_only_and_resolvable():
    manifest = json.loads(
        (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == "spc"
    assert manifest["version"].startswith("2.0.0+codex.")
    assert manifest["skills"] == "./skills/"
    assert "mcpServers" not in manifest
    entry = marketplace["plugins"][0]
    assert (ROOT / entry["source"]["path"]).resolve() == PLUGIN.resolve()


def test_skill_uses_only_current_cli_surface():
    skill = (PLUGIN / "skills" / "spc-research-acquisition" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for command in (
        "spc schema",
        "spc paper lookup",
        "spc paper download",
        "spc paper parse",
        "spc seed-pack show",
        "spc job wait",
        "spc dataset geo",
        "spc dataset archive capabilities",
    ):
        assert command in skill
    for removed in ("agent-guide", "job watch", "job result", "cstcloud-validate"):
        assert removed not in skill
    assert "Never edit `papers.jsonl`" in skill
    assert "There is no SPC MCP" in skill


def test_preflight_accepts_v2_schema(monkeypatch, tmp_path):
    preflight = _load_preflight()
    python = tmp_path / "bin" / "python"
    spc = tmp_path / "bin" / "spc"
    python.parent.mkdir()
    python.touch()
    spc.touch()
    monkeypatch.setattr(preflight, "_expected_python", lambda profile, root: python)
    monkeypatch.setattr(preflight.sys, "executable", str(python))
    responses = iter(
        [
            (
                0,
                {
                    "schema": "spc.result.v2",
                    "status": "completed",
                    "data": {
                        "version": "2.0.0",
                        "git_sha": "a" * 40,
                        "install_mode": "editable",
                        "python_executable": str(python),
                    },
                },
            ),
            (
                0,
                {
                    "schema": "spc.result.v2",
                    "status": "completed",
                    "data": {"command": "paper download"},
                },
            ),
            (0, {"schema": "spc.result.v2", "status": "completed", "data": {}}),
        ]
    )
    monkeypatch.setattr(preflight, "_run_json", lambda prefix, args: next(responses))
    report = preflight.build_report(
        SimpleNamespace(
            runtime_profile="development",
            env_file=None,
            expected_git_sha=None,
            expected_source_root=None,
        )
    )
    assert report["ready"] is True
    assert report["checks"]["public_schema_compatible"] is True


def test_preflight_rejects_schema_drift(monkeypatch, tmp_path):
    preflight = _load_preflight()
    python = tmp_path / "bin" / "python"
    spc = tmp_path / "bin" / "spc"
    python.parent.mkdir()
    python.touch()
    spc.touch()
    monkeypatch.setattr(preflight, "_expected_python", lambda profile, root: python)
    monkeypatch.setattr(preflight.sys, "executable", str(python))
    responses = iter(
        [
            (
                0,
                {
                    "schema": "spc.result.v2",
                    "status": "completed",
                    "data": {
                        "git_sha": "a" * 40,
                        "python_executable": str(python),
                    },
                },
            ),
            (0, {"schema": "spc.result.v3", "status": "completed"}),
            (0, {"schema": "spc.result.v2", "status": "completed"}),
        ]
    )
    monkeypatch.setattr(preflight, "_run_json", lambda prefix, args: next(responses))
    report = preflight.build_report(
        SimpleNamespace(
            runtime_profile="development",
            env_file=None,
            expected_git_sha=None,
            expected_source_root=None,
        )
    )
    assert report["ready"] is False
    assert report["error_code"] == "spc_preflight_failed"


def test_preflight_resolves_production_roots(tmp_path):
    preflight = _load_preflight()

    assert preflight._expected_python("production") == (
        Path.home()
        / ".local"
        / "share"
        / "paperfetch-production"
        / "current"
        / "venv"
        / "bin"
        / "python"
    )
    assert preflight._expected_python("production", str(tmp_path)) == (
        tmp_path / "current" / "venv" / "bin" / "python"
    )
