"""Tests for shared default-env loading across CLI and service/MCP surfaces."""

from __future__ import annotations

from research_harness import env_bootstrap
from research_harness.integrations.figure_image_provider import (
    figure_image_generation_ready,
)


def _write_provider_env(tmp_path):
    env_file = tmp_path / "rh-test.env"
    env_file.write_text(
        "\n".join(
            [
                "GROK_BASE_URL=https://gateway.example/v1",
                "GROK_API_KEY=test-secret",
            ]
        ),
        encoding="utf-8",
    )
    return env_file


def test_readiness_probe_loads_default_env_without_cli(tmp_path, monkeypatch):
    """figure_image_generation_ready must see env-file config on any surface.

    Before env_bootstrap, only the CLI ran the autoload: the same probe
    invoked via service/MCP said "not ready" and let ILLUSTRATION_PENDING
    fallbacks ship even though a provider backend was fully configured.
    """
    env_file = _write_provider_env(tmp_path)
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "1")
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
    monkeypatch.setenv("RESEARCH_HARNESS_ENV_FILE", str(env_file))
    # Keep the developer's private.env and repo/cwd .env candidates out of
    # this test's view.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RESEARCH_HARNESS_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    env_bootstrap.reset_ensure_cache_for_tests()

    assert figure_image_generation_ready() is True

    monkeypatch.delenv("GROK_BASE_URL", raising=False)
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    env_bootstrap.reset_ensure_cache_for_tests()


def test_auto_env_opt_out_keeps_probe_unready(tmp_path, monkeypatch):
    env_file = _write_provider_env(tmp_path)
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "0")
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
    monkeypatch.setenv("RESEARCH_HARNESS_ENV_FILE", str(env_file))
    env_bootstrap.reset_ensure_cache_for_tests()

    assert env_bootstrap.ensure_default_env_loaded() == {}
    assert figure_image_generation_ready() is False


def test_ensure_default_env_loaded_scans_once_per_process(monkeypatch):
    calls = {"count": 0}

    def _counting_loader():
        calls["count"] += 1
        return {"stub": ["NAME"]}

    env_bootstrap.reset_ensure_cache_for_tests()
    monkeypatch.setattr(env_bootstrap, "load_default_env_files", _counting_loader)

    first = env_bootstrap.ensure_default_env_loaded()
    second = env_bootstrap.ensure_default_env_loaded()

    assert first == second == {"stub": ["NAME"]}
    assert calls["count"] == 1


def test_env_file_never_overrides_existing_values(tmp_path, monkeypatch):
    env_file = _write_provider_env(tmp_path)
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "1")
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
    monkeypatch.setenv("RESEARCH_HARNESS_ENV_FILE", str(env_file))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RESEARCH_HARNESS_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROK_API_KEY", "already-set")
    env_bootstrap.reset_ensure_cache_for_tests()

    loaded = env_bootstrap.load_default_env_files()

    import os

    assert os.environ["GROK_API_KEY"] == "already-set"
    loaded_names = [name for names in loaded.values() for name in names]
    assert "GROK_API_KEY" not in loaded_names
    assert "GROK_BASE_URL" in loaded_names
    monkeypatch.delenv("GROK_BASE_URL", raising=False)
