"""Prompt and environment helpers for Zotero translation streams."""

from __future__ import annotations

import os


TRANSLATE_LOCALE_LABELS: dict[str, str] = {
    "zh-cn": "简体中文",
    "zh": "简体中文",
    "zh-hans": "简体中文",
    "zh-tw": "繁體中文",
    "zh-hant": "繁體中文",
    "en": "English",
    "en-us": "English",
    "en-gb": "English",
    "ja": "日本語",
    "ja-jp": "日本語",
    "ko": "한국어",
    "ko-kr": "한국어",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "ru": "Русский",
}


def zotero_codex_translate_effort() -> str:
    return (
        os.environ.get("RESEARCH_HARNESS_ZOTERO_TRANSLATE_EFFORT", "").strip() or "low"
    )


def locale_label(locale: str) -> str:
    key = str(locale or "").strip().lower()
    if not key:
        return "简体中文"
    if key in TRANSLATE_LOCALE_LABELS:
        return TRANSLATE_LOCALE_LABELS[key]
    head = key.split("-", 1)[0]
    return TRANSLATE_LOCALE_LABELS.get(head, "简体中文")


def zotero_codex_translate_instructions(target_locale: str) -> str:
    # Kept intentionally short because it is reprocessed for each ephemeral
    # translation thread.
    return (
        f"只翻译用户文本为{locale_label(target_locale)}；"
        "保留段落/列表/公式/专名；"
        "不要解释、不要原文、不要 Markdown 标题、不要前后缀；"
        "若原文已是目标语言原样返回。"
    )


def zotero_codex_translate_prompt(
    *,
    text: str,
    target_locale: str,
    source_locale: str = "",
) -> str:
    target_label = locale_label(target_locale)
    cleaned = (text or "").strip()
    source_locale = (source_locale or "").strip()
    source_hint = f"(原文 {locale_label(source_locale)}) " if source_locale else ""
    return f"译为 {target_label}：{source_hint}\n<text>\n{cleaned}\n</text>"
