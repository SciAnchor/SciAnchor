from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils import first_nonempty_line
from .markdown import extract_markdown_toc, normalize_heading
from .types import ParsedDocument


class MinerUArtifactParser:
    """Parse from pre-produced MinerU artifacts instead of the PDF binary.

    MinerU runs elsewhere (SPC is the producer); RH imports its ``full.md``
    and optional ``*_content_list.json`` next to the paper. This parser turns
    those artifacts into a ``ParsedDocument`` whose Markdown heading outline
    drives structure extraction, so PDFs without an embedded TOC no longer
    need an LLM guess and section text gets character-precise boundaries via
    ``attach_markdown_section_text``.

    The ``pdf_path`` given to :meth:`parse` is only used for provenance
    (source path / title fallback); the PDF bytes are never read.
    """

    parser_name = "mineru"

    def __init__(
        self,
        markdown_path: str | Path,
        content_list_path: str | Path | None = None,
    ):
        self._markdown_path = Path(markdown_path)
        self._content_list_path = Path(content_list_path) if content_list_path else None

    def parse(self, pdf_path: str | Path) -> ParsedDocument:
        if not self._markdown_path.is_file():
            raise FileNotFoundError(self._markdown_path)
        markdown = self._markdown_path.read_text(encoding="utf-8")

        warnings: list[str] = []
        entries = self._load_content_list(warnings)
        heading_pages, pages_text, page_count = _digest_content_list(entries)

        toc = extract_markdown_toc(markdown, heading_pages=heading_pages)
        if not pages_text:
            pages_text = (markdown,) if markdown.strip() else ()
        if page_count <= 0:
            page_count = max(1, len(pages_text))

        title = _first_top_heading(toc) or first_nonempty_line(markdown)
        return ParsedDocument(
            source_path=str(pdf_path),
            parser_name=self.parser_name,
            page_count=page_count,
            title=title or Path(pdf_path).stem,
            pages_text=pages_text,
            markdown=markdown,
            toc=toc,
            raw={
                "structure_source": "markdown_headings" if toc else "",
                "markdown_path": str(self._markdown_path),
                "content_list_path": str(self._content_list_path or ""),
            },
            warnings=tuple(warnings),
        )

    def _load_content_list(self, warnings: list[str]) -> list[dict[str, Any]]:
        path = self._content_list_path
        if path is None:
            return []
        if not path.is_file():
            warnings.append(f"content list not found: {path}")
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            warnings.append(f"content list unreadable ({exc}); markdown-only parse")
            return []
        if not isinstance(payload, list):
            warnings.append("content list is not a JSON array; markdown-only parse")
            return []
        return [item for item in payload if isinstance(item, dict)]


def _digest_content_list(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, int], tuple[str, ...], int]:
    """Fold a MinerU content list into heading pages, page texts, page count.

    Entries carry 0-based ``page_idx``; headings are text entries with a
    ``text_level``. Pages without any text entry become empty strings so page
    numbering stays aligned for downstream 1-based indexing.
    """

    heading_pages: dict[str, int] = {}
    page_texts: dict[int, list[str]] = {}
    max_idx = -1
    for entry in entries:
        try:
            page_idx = int(entry.get("page_idx"))
        except (TypeError, ValueError):
            continue
        if page_idx < 0:
            continue
        max_idx = max(max_idx, page_idx)
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        page_texts.setdefault(page_idx, []).append(text)
        level = entry.get("text_level")
        if isinstance(level, int) and level >= 1:
            heading_pages.setdefault(normalize_heading(text), page_idx + 1)

    if max_idx < 0:
        return {}, (), 0
    pages = tuple("\n".join(page_texts.get(idx, [])) for idx in range(max_idx + 1))
    return heading_pages, pages, max_idx + 1


def _first_top_heading(toc: tuple[tuple[int, str, int], ...]) -> str:
    for level, title, _ in toc:
        if level == 1:
            return title
    return toc[0][1] if toc else ""
