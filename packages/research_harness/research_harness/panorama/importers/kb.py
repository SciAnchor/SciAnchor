"""Deterministic markdown importer for the innovation KB (``docs/innovation-kb/``).

No LLM involved: direction files become ``claim`` entities occupying territory
cells, ``lessons.md`` sections become ``limitation`` entities, and
``evidence/prior-art.md`` sections become ``paper`` entities — each with a
4-tuple anchor quoting the source paragraph. Parsing tolerates formatting
noise (fences, comments, rules, tables) by skipping non-prose blocks.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..store import PanoramaStore
from .pooldb import _ensure_anchor

_BLOCK_SPLIT = re.compile(r"\n\s*\n")
_HR_CHARS = frozenset("-*_= ")


def _first_paragraph(text: str) -> str:
    """First prose paragraph: skips headings, fences, comments, tables, rules."""
    for block in _BLOCK_SPLIT.split(text):
        block = block.strip()
        if not block:
            continue
        first = block.splitlines()[0].lstrip()
        if first.startswith(("#", "```", "<!--", "|", ">")):
            continue
        if set(first) <= _HR_CHARS:
            continue
        return " ".join(line.strip() for line in block.splitlines()).strip()
    return ""


def _sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into top-level ``## `` sections (code-fence aware)."""
    sections: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            heading = line[3:].strip()
            if heading:
                sections.append((heading, []))
                current = sections[-1][1]
                continue
        if not in_fence and line.startswith("# ") and not line.startswith("## "):
            current = None
            continue
        if current is not None:
            current.append(line)
    return [(heading, "\n".join(body)) for heading, body in sections]


def import_innovation_kb(
    store: PanoramaStore,
    direction_id: int,
    kb_dir: Path | str,
) -> dict[str, int]:
    """Import the innovation KB markdown tree into the panorama store.

    Missing files or subdirectories are skipped gracefully; re-running is
    idempotent (entities/cells dedupe in the store, anchors dedupe locally).
    """
    kb = Path(kb_dir).expanduser()
    counts = {
        "direction_claims": 0,
        "cells": 0,
        "lessons": 0,
        "prior_art_papers": 0,
        "anchors": 0,
    }

    directions_dir = kb / "directions"
    if directions_dir.is_dir():
        for md_path in sorted(directions_dir.glob("*.md")):
            slug = md_path.stem
            paragraph = _first_paragraph(md_path.read_text(encoding="utf-8"))
            entity_id = store.upsert_entity(
                direction_id,
                "claim",
                slug,
                summary=paragraph,
                source="kb",
            )
            counts["direction_claims"] += 1
            source_ref = md_path.relative_to(kb).as_posix()
            if paragraph and _ensure_anchor(
                store, "entity", entity_id, quote_text=paragraph, source_ref=source_ref
            ):
                counts["anchors"] += 1
            cell_id = store.upsert_cell(direction_id, slug, "rh-direction", "kb")
            store.occupy_cell(cell_id, entity_id)
            counts["cells"] += 1

    lessons_path = kb / "lessons.md"
    if lessons_path.is_file():
        for heading, body in _sections(lessons_path.read_text(encoding="utf-8")):
            paragraph = _first_paragraph(body)
            entity_id = store.upsert_entity(
                direction_id,
                "limitation",
                heading,
                summary=paragraph,
                source="kb",
            )
            counts["lessons"] += 1
            if paragraph and _ensure_anchor(
                store,
                "entity",
                entity_id,
                quote_text=paragraph,
                source_ref="lessons.md",
            ):
                counts["anchors"] += 1

    prior_art_path = kb / "evidence" / "prior-art.md"
    if prior_art_path.is_file():
        for heading, body in _sections(prior_art_path.read_text(encoding="utf-8")):
            paragraph = _first_paragraph(body)
            entity_id = store.upsert_entity(
                direction_id,
                "paper",
                heading,
                summary=paragraph,
                source="kb",
            )
            counts["prior_art_papers"] += 1
            if paragraph and _ensure_anchor(
                store,
                "entity",
                entity_id,
                quote_text=paragraph,
                source_ref="evidence/prior-art.md",
            ):
                counts["anchors"] += 1

    return counts
