"""SPC 1.0 system 命令的真实 parser/CLI 契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperfetch.cli.root import main
from paperfetch.cli import system as system_cli
from paperfetch.core.config_v1 import builtin_config, runtime_data_root
from paperfetch.runtime_info import collect_runtime_info
from paperfetch.downloaders.pipeline import cache as pdf_cache


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _development_profile() -> str:
    return "development"


def test_capabilities_uses_one_command_result_schema(capsys):
    assert (
        main(
            [
                "system",
                "capabilities",
                "--capability",
                "system.core",
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "spc.result.v2"
    assert payload["status"] == "completed"
    assert payload["data"]["ready"] is True


def test_preflight_accepts_exact_development_runtime(capsys, monkeypatch, tmp_path):
    from paperfetch.core.settings import reset_settings, unknown_settings_env

    reset_settings()
    for name in unknown_settings_env():
        monkeypatch.delenv(name, raising=False)
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    reset_settings()
    runtime = collect_runtime_info()
    assert (
        main(
            [
                "system",
                "preflight",
                "--profile",
                _development_profile(),
                "--capability",
                "system.core",
                "--expected-git-sha",
                runtime["git_sha"],
                "--expected-source-root",
                runtime["source_root"],
                "--env-file",
                str(empty_env),
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert all(item["status"] == "completed" for item in payload["results"])


def test_preflight_rejects_runtime_sha_drift(capsys):
    assert (
        main(
            [
                "system",
                "preflight",
                "--profile",
                _development_profile(),
                "--expected-git-sha",
                "0" * 40,
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    [item] = [item for item in payload["results"] if item["id"] == "runtime.git_sha"]
    assert item["error"]["code"] == "runtime_git_sha_mismatch"


def test_preflight_rejects_development_paths_for_server_profile(capsys):
    assert (
        main(
            [
                "system",
                "preflight",
                "--profile",
                "production",
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    failures = {item["id"] for item in payload["results"] if item["status"] == "failed"}
    assert "runtime.python_path" in failures
    assert "runtime.package_path" in failures


def test_invalid_toml_is_stable_configuration_error(tmp_path: Path, capsys):
    config = tmp_path / "spc.toml"
    config.write_text("[profiles.bad\n", encoding="utf-8")
    assert (
        main(
            [
                "system",
                "preflight",
                "--profile",
                "development",
                "--config",
                str(config),
                "--output-format",
                "json",
                "--no-progress",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "config_invalid"
    assert "[profiles.bad" not in json.dumps(payload)


def test_server_profile_rejects_research_harness_conda_copy(monkeypatch):
    monkeypatch.setattr(
        system_cli,
        "collect_runtime_info",
        lambda: {
            "package": "paperfetch",
            "version": "1.0.0",
            "installed_version": "1.0.0",
            "version_mismatch": False,
            "git_sha": "a" * 40,
            "build_time": None,
            "install_mode": "installed",
            "package_path": "/opt/conda/envs/paperfetch/lib/python3.12/site-packages/paperfetch",
            "source_root": None,
            "python_executable": "/opt/conda/envs/paperfetch/bin/python",
            "python_version": "3.12.11",
            "platform": "linux",
            "log_mode": "production",
        },
    )
    monkeypatch.setattr(system_cli.platform, "python_version", lambda: "3.12.11")
    result = system_cli.build_preflight_result(
        profile_name="production", capabilities=[]
    )
    failures = {item.entity.id for item in result.items if item.status == "rejected"}
    assert result.status == "rejected"
    assert {
        "runtime.python_path",
        "runtime.package_path",
        "runtime.environment",
    } <= failures


def test_builtin_profiles_define_one_development_and_one_server_runtime():
    profiles = builtin_config().profiles

    assert set(profiles) == {"development", "production"}
    assert profiles["development"].platform == "linux"
    assert profiles["production"].python_executable_prefix == "/opt/paperfetch/"


def test_runtime_data_root_uses_server_release_layout(monkeypatch):
    from paperfetch.core.settings import reset_settings

    monkeypatch.delenv("SPC_DATA_ROOT", raising=False)
    monkeypatch.setenv("SPC_ENVIRONMENT", "production")
    reset_settings()

    assert runtime_data_root() == Path("/opt/paperfetch/data")


def test_pdf_cache_defaults_to_runtime_cache_root(monkeypatch, tmp_path):
    monkeypatch.delenv("PDF_CACHE_ROOT", raising=False)
    monkeypatch.setattr(pdf_cache, "runtime_cache_root", lambda: tmp_path / "cache")

    assert pdf_cache.resolve_pdf_cache_root() == tmp_path / "cache" / "pdf"
