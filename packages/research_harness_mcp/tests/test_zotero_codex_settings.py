"""Focused tests for Zotero Codex settings helper extraction."""

from __future__ import annotations

from pathlib import Path


def test_zotero_codex_settings_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_codex_settings

    assert http_api._zotero_codex_cwd is zotero_codex_settings.zotero_codex_cwd
    assert http_api._zotero_codex_effort is zotero_codex_settings.zotero_codex_effort
    assert (
        http_api._zotero_codex_service_tier
        is zotero_codex_settings.zotero_codex_service_tier
    )
    assert (
        http_api._zotero_codex_base_instructions
        is zotero_codex_settings.zotero_codex_base_instructions
    )


def test_zotero_codex_cwd_preserves_env_priority(monkeypatch, tmp_path: Path):
    from research_harness_mcp import zotero_codex_settings

    fallback = tmp_path / "fallback"
    primary = tmp_path / "primary"
    fallback.mkdir()
    primary.mkdir()

    monkeypatch.setenv("RESEARCH_HARNESS_CODEX_CWD", str(fallback))
    monkeypatch.delenv("RESEARCH_HARNESS_ZOTERO_CODEX_CWD", raising=False)
    assert zotero_codex_settings.zotero_codex_cwd() == fallback.resolve()

    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_CODEX_CWD", str(primary))
    assert zotero_codex_settings.zotero_codex_cwd() == primary.resolve()


def test_zotero_codex_effort_and_service_tier_preserve_defaults(monkeypatch):
    from research_harness_mcp import zotero_codex_settings

    monkeypatch.delenv("RESEARCH_HARNESS_ZOTERO_CODEX_EFFORT", raising=False)
    monkeypatch.delenv("RESEARCH_HARNESS_ZOTERO_CODEX_SERVICE_TIER", raising=False)
    assert zotero_codex_settings.zotero_codex_effort() == "low"
    assert zotero_codex_settings.zotero_codex_service_tier() is None

    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_CODEX_EFFORT", " high ")
    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_CODEX_SERVICE_TIER", " flex ")
    assert zotero_codex_settings.zotero_codex_effort() == "high"
    assert zotero_codex_settings.zotero_codex_service_tier() == "flex"


def test_zotero_codex_base_instructions_preserve_safety_boundaries():
    from research_harness_mcp import zotero_codex_settings

    instructions = zotero_codex_settings.zotero_codex_base_instructions()

    assert instructions == instructions.strip()
    assert "默认回答本身只读" in instructions
    assert "dry-run -> 用户确认 -> apply" in instructions
    assert "rh.zotero.prepare_seed_import" in instructions
    assert "rh.zotero.attach_pdf" in instructions
    assert "如果匹配不到 RH paper/topic，给出同步或入库路径。" in instructions
