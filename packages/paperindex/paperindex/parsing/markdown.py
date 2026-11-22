from __future__ import annotations

import re


def normalize_heading(title: str) -> str:
    """Light heading normalization for matching across artifact variants."""

    text = re.sub(r"[*_`#]+", "", str(title or ""))
    return re.sub(r"\s+", " ", text).strip().lower()


def extract_markdown_toc(
    markdown: str,
    heading_pages: dict[str, int] | None = None,
) -> tuple[tuple[int, str, int], ...]:
    """Extract a (level, title, page) outline from Markdown headings.

    Markdown itself carries no page numbers; callers that know real heading
    pages (e.g. from a MinerU content list) pass them via ``heading_pages``
    keyed by :func:`normalize_heading`. Unmatched headings fall back to page 1
    as a safe lower bound so the heading tree stays usable without an LLM.
    """

    headings: list[tuple[int, str, int]] = []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.strip())
        if not match:
            continue
        title = re.sub(r"\s+", " ", match.group(2)).strip()
        title = re.sub(r"<!--.*?-->", "", title).strip()
        if not title:
            continue
        page = 1
        if heading_pages:
            page = heading_pages.get(normalize_heading(title), 1)
        headings.append((len(match.group(1)), title, page))
    return tuple(headings)
