"""Read-only PaperVault local metadata source.

PaperVault is a curated CS/AI top-venue corpus (~660k papers) that
paperfetch syncs into a local SQLite/FTS5 database via
``spc sync-papervault``. RH reads that database directly — metadata recall
is a millisecond-latency inline query, and going through the SPC CLI would
erase the benefit — while syncing stays SPC's single job. RH never writes
to the file and opens it in SQLite read-only mode.

The schema is owned by SPC and treated as a frozen read contract:

    papers(id TEXT PRIMARY KEY, title, abstract, authors /* JSON array */,
           venue, year INTEGER, pdf_url, code_url, arxiv_id)
    papers_fts(id UNINDEXED, title, abstract)   -- FTS5 virtual table

Absent or unconfigured database means the provider is simply unavailable;
it never errors the search fan-out.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .paper_sources import PaperRecord, PDFCandidate, SearchQuery

logger = logging.getLogger(__name__)

PAPERVAULT_DB_ENV = "RESEARCH_HARNESS_PAPERVAULT_DB"

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _fts_match_query(raw: str) -> str:
    """Assemble a safe FTS5 MATCH expression: quoted tokens, implicit AND."""
    tokens = _TOKEN_RE.findall(raw or "")
    return " ".join(f'"{token}"' for token in tokens)


def _parse_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [raw.strip()] if raw.strip() else []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


class PaperVaultProvider:
    name = "papervault"

    def __init__(self, db_path: str | Path | None = None) -> None:
        raw = str(db_path) if db_path else os.environ.get(PAPERVAULT_DB_ENV, "")
        self.db_path: Path | None = Path(raw).expanduser() if raw.strip() else None

    def available(self) -> bool:
        return self.db_path is not None and self.db_path.is_file()

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        if not self.available():
            return []
        match_query = _fts_match_query(query.query)
        if not match_query:
            return []

        sql = (
            "SELECT p.id, p.title, p.abstract, p.authors, p.venue, p.year,"
            " p.pdf_url, p.code_url, p.arxiv_id"
            " FROM papers p JOIN papers_fts f ON p.id = f.id"
            " WHERE papers_fts MATCH ?"
        )
        params: list[object] = [match_query]
        if query.year_from is not None:
            sql += " AND p.year >= ?"
            params.append(query.year_from)
        if query.year_to is not None:
            sql += " AND p.year <= ?"
            params.append(query.year_to)
        sql += " LIMIT ?"
        params.append(query.per_provider_limit or query.limit)

        try:
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro", uri=True, timeout=2.0
            )
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            logger.warning("papervault query failed", exc_info=True)
            return []

        retrieved_at = datetime.now(timezone.utc).isoformat()
        return [
            self._row_to_record(row, match_query, retrieved_at, rank)
            for rank, row in enumerate(rows, start=1)
        ]

    def _row_to_record(
        self, row: sqlite3.Row, match_query: str, retrieved_at: str, rank: int
    ) -> PaperRecord:
        title = row["title"] or ""
        abstract = row["abstract"] or ""
        arxiv_id = (row["arxiv_id"] or "").strip()
        pdf_url = (row["pdf_url"] or "").strip()
        code_url = (row["code_url"] or "").strip()

        pdf_candidates: list[PDFCandidate] = []
        if arxiv_id:
            pdf_candidates.append(
                PDFCandidate(
                    url=f"https://arxiv.org/pdf/{arxiv_id}",
                    source_type="arxiv_pdf",
                    provider=self.name,
                    confidence=0.9,
                )
            )
        if pdf_url and ".pdf" in pdf_url.lower():
            pdf_candidates.append(
                PDFCandidate(
                    url=pdf_url,
                    source_type="open_access_pdf",
                    provider=self.name,
                    confidence=0.6,
                )
            )

        source_refs = [
            {
                "source": self.name,
                "source_record_id": row["id"],
                "field": field,
                "value": value,
                "retrieved_at": retrieved_at,
                "query_or_endpoint": match_query,
                "confidence": 1.0,
            }
            for field, value in (("title", title), ("abstract", abstract))
            if value
        ]
        curation_signals: dict[str, object] = {}
        if code_url:
            curation_signals["code_url"] = code_url

        return PaperRecord(
            title=title,
            authors=_parse_authors(row["authors"]),
            year=row["year"],
            venue=row["venue"] or "",
            abstract=abstract,
            arxiv_id=arxiv_id,
            url=pdf_url,
            provider=self.name,
            pdf_candidates=pdf_candidates,
            source_rank=rank,
            source_refs=source_refs,
            recall_hits=[
                {
                    "source": self.name,
                    "query": match_query,
                    "source_rank": rank,
                    "retrieved_at": retrieved_at,
                }
            ],
            curation_signals=curation_signals,
        )
