"""Pure Zotero identity and text normalization helpers."""

from __future__ import annotations

import re


def normalize_zotero_chat_tags(tags: list[str]) -> list[str]:
    return [str(tag or "").strip() for tag in tags if str(tag or "").strip()]


def extract_rh_paper_id_tag(tags: list[str]) -> int | None:
    for tag in tags:
        match = re.match(r"^rh-paper-id:(\d+)$", tag.strip(), flags=re.I)
        if match:
            return int(match.group(1))
    return None


def extract_rh_topic_tag(tags: list[str]) -> str:
    for tag in tags:
        match = re.match(r"^rh-topic:(.+)$", tag.strip(), flags=re.I)
        if match:
            return match.group(1).strip()
    return ""


def normalize_zotero_library_id(value: str | int | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_doi(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text, flags=re.I)
    text = text.removeprefix("doi:").strip()
    return text


def normalize_arxiv_id(value: str) -> str:
    text = str(value or "").strip()
    match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", text)
    if match:
        return match.group(1)
    text = text.removeprefix("arxiv:").removeprefix("arXiv:").strip()
    return text


def normalize_title_for_match(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def truncate_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}…"
