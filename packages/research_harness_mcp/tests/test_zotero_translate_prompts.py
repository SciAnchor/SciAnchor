"""Focused tests for Zotero translate prompt helper extraction."""

from __future__ import annotations


def test_zotero_translate_prompt_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_translate_prompts

    assert (
        http_api._zotero_codex_translate_effort
        is zotero_translate_prompts.zotero_codex_translate_effort
    )
    assert http_api._locale_label is zotero_translate_prompts.locale_label
    assert (
        http_api._zotero_codex_translate_instructions
        is zotero_translate_prompts.zotero_codex_translate_instructions
    )
    assert (
        http_api._zotero_codex_translate_prompt
        is zotero_translate_prompts.zotero_codex_translate_prompt
    )


def test_zotero_translate_effort_preserves_env_default(monkeypatch):
    from research_harness_mcp import zotero_translate_prompts

    monkeypatch.delenv("RESEARCH_HARNESS_ZOTERO_TRANSLATE_EFFORT", raising=False)
    assert zotero_translate_prompts.zotero_codex_translate_effort() == "low"

    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_TRANSLATE_EFFORT", " medium ")
    assert zotero_translate_prompts.zotero_codex_translate_effort() == "medium"


def test_locale_label_preserves_aliases_and_default_fallback():
    from research_harness_mcp import zotero_translate_prompts

    assert zotero_translate_prompts.locale_label("zh-CN") == "简体中文"
    assert zotero_translate_prompts.locale_label("en-GB") == "English"
    assert zotero_translate_prompts.locale_label("fr") == "Français"
    assert zotero_translate_prompts.locale_label("unknown") == "简体中文"
    assert zotero_translate_prompts.locale_label("") == "简体中文"


def test_zotero_translate_instructions_and_prompt_are_stable():
    from research_harness_mcp import zotero_translate_prompts

    instructions = zotero_translate_prompts.zotero_codex_translate_instructions("ja")
    prompt = zotero_translate_prompts.zotero_codex_translate_prompt(
        text="  Hello\nworld  ",
        target_locale="de",
        source_locale="en-US",
    )
    prompt_without_source = zotero_translate_prompts.zotero_codex_translate_prompt(
        text="Bonjour",
        target_locale="zh-Hant",
    )

    assert instructions == (
        "只翻译用户文本为日本語；"
        "保留段落/列表/公式/专名；"
        "不要解释、不要原文、不要 Markdown 标题、不要前后缀；"
        "若原文已是目标语言原样返回。"
    )
    assert prompt == "译为 Deutsch：(原文 English) \n<text>\nHello\nworld\n</text>"
    assert prompt_without_source == "译为 繁體中文：\n<text>\nBonjour\n</text>"
