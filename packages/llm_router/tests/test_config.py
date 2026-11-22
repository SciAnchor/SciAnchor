"""Tests for the optional config file + backend detection."""

from __future__ import annotations

from pathlib import Path

import pytest


pytest.importorskip("tomllib", reason="TOML config support requires Python 3.11+")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Point LLM_ROUTER_CONFIG at a tmp file and clear overlapping env vars."""
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "CHATGPT_API_KEY",
        "KIMI_API_KEY",
        "KIMI_MODEL",
        "EVOLINK_API_KEY",
        "EVOLINK_MODEL",
        "EVOLINK_BASE_URL",
        "CURSOR_AGENT_ENABLED",
        "CODEX_ENABLED",
        "LLM_PROVIDER",
        "LLM_ROUTE_LIGHT",
        "LLM_ROUTE_MEDIUM",
        "LLM_ROUTE_HEAVY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_ROUTER_CONFIG", str(tmp_path / "config.toml"))
    # Keep provider auto-detection deterministic. Individual tests can add a
    # fake CLI binary to this PATH when they need to exercise CLI detection.
    monkeypatch.setenv("PATH", str(tmp_path))


def _write_config(path_env: str, body: str) -> None:
    Path(path_env).write_text(body, encoding="utf-8")


def test_missing_config_returns_empty_dict(monkeypatch):
    from llm_router.config import load_config

    monkeypatch.setenv("LLM_ROUTER_CONFIG", "/does/not/exist.toml")
    assert load_config() == {}


def test_invalid_toml_is_swallowed(monkeypatch, tmp_path, caplog):
    import logging

    cfg = tmp_path / "broken.toml"
    cfg.write_text("this = is [not valid\n", encoding="utf-8")
    monkeypatch.setenv("LLM_ROUTER_CONFIG", str(cfg))

    from llm_router.config import load_config

    with caplog.at_level(logging.WARNING, logger="llm_router.config"):
        assert load_config() == {}
    assert any("config load failed" in rec.message for rec in caplog.records)


def test_get_provider_order_parsed(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nprovider_order = ["openai", "anthropic"]\n',
    )
    from llm_router.config import get_provider_order

    assert get_provider_order() == ["openai", "anthropic"]


def test_get_tier_route_parsed(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nheavy = "anthropic:claude-opus-4-6"\n',
    )
    from llm_router.config import get_tier_route

    assert get_tier_route("heavy") == ("anthropic", "claude-opus-4-6")
    assert get_tier_route("medium") is None


def test_resolve_route_uses_config_when_env_unset(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nheavy = "anthropic:claude-opus-4-6"\n',
    )

    from llm_router.client import resolve_route

    assert resolve_route("heavy") == ("anthropic", "claude-opus-4-6")


def test_env_var_beats_config_for_route(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nheavy = "anthropic:claude-opus-4-6"\n',
    )
    monkeypatch.setenv("LLM_ROUTE_HEAVY", "openai:gpt-4o")

    from llm_router.client import resolve_route

    assert resolve_route("heavy") == ("openai", "gpt-4o")


def test_provider_order_picks_first_available(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nprovider_order = ["kimi", "openai", "anthropic"]\n',
    )
    # Only OPENAI has credentials — config order should skip kimi.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    from llm_router.client import resolve_llm_config

    cfg = resolve_llm_config()
    assert cfg.provider == "openai"


def test_provider_order_falls_through_when_none_available(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nprovider_order = ["kimi", "cursor_agent"]\n',
    )
    # No credentials for either entry — built-in auto-detect should kick in.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    from llm_router.client import resolve_llm_config

    cfg = resolve_llm_config()
    assert cfg.provider == "anthropic"


def test_resolve_llm_config_detects_cursor_agent_on_path(monkeypatch, tmp_path):
    agent = tmp_path / "agent"
    agent.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    agent.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    from llm_router.client import resolve_llm_config

    cfg = resolve_llm_config()
    assert cfg.provider == "cursor_agent"
    assert cfg.model == "composer-2.5-fast"


def test_provider_order_can_pick_cursor_agent_on_path(monkeypatch, tmp_path):
    import os

    agent = tmp_path / "agent"
    agent.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    agent.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nprovider_order = ["cursor_agent", "openai"]\n',
    )

    from llm_router.client import resolve_llm_config

    cfg = resolve_llm_config()
    assert cfg.provider == "cursor_agent"


def test_llm_provider_env_forces_selected_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    from llm_router.client import resolve_llm_config

    cfg = resolve_llm_config()
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-sonnet-4-6"


def test_cursor_agent_strips_null_bytes_before_subprocess(monkeypatch):
    from llm_router import client as client_mod

    captured = {}

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Result()

    monkeypatch.setattr(client_mod.subprocess, "run", fake_run)

    assert client_mod._chat_cursor_agent("hello\x00world", "composer-2.5-fast") == "ok"
    assert "\x00" not in captured["cmd"][-1]
    assert captured["cmd"][-1] == "helloworld"


def test_provider_order_respects_plugin_providers(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nprovider_order = ["fake_plugin"]\n',
    )
    # No built-in credentials.
    from llm_router import client as client_mod

    snapshot = dict(client_mod._PROVIDER_REGISTRY)
    try:
        client_mod._PROVIDER_REGISTRY["fake_plugin"] = lambda prompt, model, **_: "ok"
        cfg = client_mod.resolve_llm_config()
        assert cfg.provider == "fake_plugin"
    finally:
        client_mod._PROVIDER_REGISTRY.clear()
        client_mod._PROVIDER_REGISTRY.update(snapshot)


def test_detect_available_providers(monkeypatch):
    from llm_router.config import detect_available_providers

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("KIMI_API_KEY", "sk-test")

    available = detect_available_providers()
    assert "openai" in available
    assert "kimi" in available
    assert "anthropic" not in available


def test_detect_available_provider_details_reports_proxy_route(monkeypatch):
    from llm_router.config import detect_available_provider_details

    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8765/v1")

    details = detect_available_provider_details()
    mapping = {item.provider: item for item in details}
    assert mapping["openai"].route_kind == "openai-compatible"
    assert mapping["openai"].source == "env"


def test_detect_available_providers_includes_evolink(monkeypatch):
    from llm_router.config import detect_available_providers

    monkeypatch.setenv("EVOLINK_API_KEY", "sk-evolink-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    available = detect_available_providers()
    assert "evolink" in available
    assert "openai" in available


def test_detect_available_provider_details_reports_evolink(monkeypatch):
    from llm_router.config import detect_available_provider_details

    monkeypatch.setenv("EVOLINK_API_KEY", "sk-evolink-test")

    details = detect_available_provider_details()
    mapping = {item.provider: item for item in details}
    assert "evolink" in mapping
    assert mapping["evolink"].route_kind == "openai-compatible"
    assert mapping["evolink"].source == "env"


def test_evolink_provider_resolves_defaults(monkeypatch):
    from llm_router.client import resolve_llm_config

    monkeypatch.setenv("EVOLINK_API_KEY", "sk-evolink-test")

    cfg = resolve_llm_config()
    assert cfg.provider == "evolink"
    assert cfg.model == "gpt-5.2"
    assert cfg.api_key == "sk-evolink-test"
    assert "direct.evolink.ai" in cfg.base_url


def test_evolink_provider_resolves_custom_model(monkeypatch):
    from llm_router.client import resolve_llm_config

    monkeypatch.setenv("EVOLINK_API_KEY", "sk-evolink-test")
    monkeypatch.setenv("EVOLINK_MODEL", "deepseek-v4-pro")

    cfg = resolve_llm_config()
    assert cfg.provider == "evolink"
    assert cfg.model == "deepseek-v4-pro"


def test_evolink_provider_resolves_custom_base_url(monkeypatch):
    from llm_router.client import resolve_llm_config

    monkeypatch.setenv("EVOLINK_API_KEY", "sk-evolink-test")
    monkeypatch.setenv("EVOLINK_BASE_URL", "https://custom-evolink.example.com/v1")

    cfg = resolve_llm_config()
    assert cfg.base_url == "https://custom-evolink.example.com/v1"


def test_evolink_provider_can_be_forced_via_llm_provider_env(monkeypatch):
    from llm_router.client import resolve_llm_config

    monkeypatch.setenv("EVOLINK_API_KEY", "sk-evolink-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("LLM_PROVIDER", "evolink")

    cfg = resolve_llm_config()
    assert cfg.provider == "evolink"


def test_evolink_provider_shows_in_list_providers():
    from llm_router import list_providers

    providers = list_providers()
    assert "evolink" in providers


def test_evolink_chat_requires_api_key():
    from llm_router.client import _chat_evolink

    with pytest.raises(ValueError, match="EVOLINK_API_KEY"):
        _chat_evolink("test prompt", "gpt-5.2", api_key="")
