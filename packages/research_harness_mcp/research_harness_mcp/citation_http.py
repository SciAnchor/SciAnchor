"""FastAPI route registration for citation export and contradiction endpoints."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse


def register_citation_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
) -> None:
    """Register BibTeX export and contradiction routes."""

    @app.get("/api/topics/{topic_id}/bibtex", response_class=PlainTextResponse)
    def export_topic_bibtex(topic_id: int):
        """Export all papers in a topic as a single BibTeX file.

        Reuses the bib_entries table populated by `rh bib` CLI. Falls back to
        a minimal synthesized entry for papers without a registered entry.
        """
        with get_db_context() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.authors, p.year, p.venue,
                       p.doi, p.arxiv_id, b.bibtex, b.bibtex_key
                FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                LEFT JOIN bib_entries b ON b.paper_id = p.id
                WHERE pt.topic_id = ?
                ORDER BY p.year DESC NULLS LAST, p.id
                """,
                (topic_id,),
            ).fetchall()

        entries: list[str] = []
        for r in rows:
            if r["bibtex"]:
                entries.append(r["bibtex"])
                continue
            # Synthesize a minimal @misc entry so Zotero / BibLaTeX imports work.
            key = r["bibtex_key"] or _synthesize_bibkey(
                int(r["id"]), r["title"] or "", r["year"], r["authors"] or ""
            )
            author_str = _parse_author_list(r["authors"] or "")
            parts = [f"@misc{{{key},"]
            if r["title"]:
                parts.append(f"  title={{{r['title']}}},")
            if author_str:
                parts.append(f"  author={{{author_str}}},")
            if r["year"]:
                parts.append(f"  year={{{r['year']}}},")
            if r["venue"]:
                parts.append(f"  howpublished={{{r['venue']}}},")
            if r["arxiv_id"]:
                parts.append(f"  eprint={{{r['arxiv_id']}}},")
                parts.append("  archivePrefix={arXiv},")
            if r["doi"]:
                parts.append(f"  doi={{{r['doi']}}},")
            parts.append("}")
            entries.append("\n".join(parts))
        return PlainTextResponse("\n\n".join(entries) + "\n")

    @app.get("/api/topics/{topic_id}/contradictions")
    def list_contradictions(topic_id: int):
        """List persisted contradictions for a topic (from verify_claims)."""
        with get_db_context() as conn:
            rows = conn.execute(
                """
                SELECT id, topic_id, claim_a_id, claim_b_id, conflict_reason,
                       status, confidence, created_at
                FROM contradictions WHERE topic_id = ?
                ORDER BY id DESC
                """,
                (topic_id,),
            ).fetchall()
            items = [dict(r) for r in rows]
            # Hydrate claim text for UI convenience
            claim_ids: list[int] = []
            for it in items:
                claim_ids.extend([it["claim_a_id"], it["claim_b_id"]])
            texts: dict[int, dict[str, Any]] = {}
            if claim_ids:
                ph = ",".join("?" * len(claim_ids))
                crows = conn.execute(
                    f"SELECT id, claim_text, paper_id, modality, dataset, metric, task "
                    f"FROM normalized_claims WHERE id IN ({ph})",
                    claim_ids,
                ).fetchall()
                for cr in crows:
                    texts[int(cr["id"])] = dict(cr)
            for it in items:
                it["claim_a"] = texts.get(int(it["claim_a_id"]))
                it["claim_b"] = texts.get(int(it["claim_b_id"]))
        return {"topic_id": topic_id, "contradictions": items}


def _synthesize_bibkey(
    paper_id: int, title: str, year: int | str | None, authors: str
) -> str:
    first_author = ""
    try:
        arr = json.loads(authors)
        if isinstance(arr, list) and arr:
            first = arr[0]
            if isinstance(first, str):
                first_author = first.split()[-1].lower()
            elif isinstance(first, dict):
                first_author = str(first.get("name", "")).split()[-1].lower()
    except (ValueError, TypeError):
        first_author = ""
    first_word = ""
    if title:
        words = re.findall(r"[A-Za-z]{4,}", title)
        if words:
            first_word = words[0].lower()
    yr = str(year or "")
    parts = [p for p in (first_author, yr, first_word) if p]
    return "-".join(parts) or f"paper-{paper_id}"


def _parse_author_list(authors: str) -> str:
    try:
        arr = json.loads(authors)
    except (ValueError, TypeError):
        return authors
    if not isinstance(arr, list):
        return str(arr)
    names: list[str] = []
    for item in arr:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            if name:
                names.append(name)
    return " and ".join(names)
