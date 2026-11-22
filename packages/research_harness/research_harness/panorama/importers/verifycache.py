"""Absorb gap_ground_verify retrieval into the panorama (living-KB feedback).

Every ``gap_ground_verify`` certification runs multi-query prior-art retrieval
whose results are cached in the RH pool DB ``search_cache``. Those records are
otherwise query-and-discard. This importer flattens the recent cache into the
harvest record shape and ingests it as an independent capture source
(``gap-verify``), so the act of certifying a gap also enriches the paper
library and adds a decorrelated sample for the coverage estimator.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..harvest import record_external_source
from ..store import PanoramaStore

_ID_FIELDS = (
    ("arxiv", "arxiv_id"),
    ("doi", "doi"),
    ("s2", "s2_id"),
    ("openalex", "openalex_id"),
)


def _flatten_cache(pool_db_path: Path | str, since: str | None) -> list[dict[str, Any]]:
    """Read search_cache rows (optionally created on/after ``since``) → records."""
    conn = sqlite3.connect(f"file:{pool_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if since:
            rows = conn.execute(
                "SELECT result_json FROM search_cache WHERE created_at >= ?",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT result_json FROM search_cache").fetchall()
    finally:
        conn.close()

    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["result_json"] or "[]")
        except (ValueError, TypeError):
            continue
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            ids: dict[str, str] = {}
            for scheme, field in _ID_FIELDS:
                value = str(item.get(field) or "").strip()
                if value:
                    ids[scheme] = value
            year = item.get("year")
            records.append(
                {
                    "title": title,
                    "abstract": str(item.get("abstract") or "").strip(),
                    "year": year if isinstance(year, int) else None,
                    "venue": str(item.get("venue") or "").strip(),
                    "ids": ids,
                    "url": str(item.get("url") or ""),
                }
            )
    return records


def absorb_verify_cache(
    store: PanoramaStore,
    direction_id: int,
    pool_db_path: Path | str,
    *,
    since: str | None = None,
    source_name: str = "gap-verify",
    triage_keywords: list[str] | None = None,
    import_budget: int = 400,
    round_no: int = 1,
) -> dict[str, Any]:
    """Ingest recent gap_ground_verify retrieval as a ``gap-verify`` capture source.

    Records are triaged (domain-keyword gate, same as academic harvest) so the
    wide net cast by contribution-level query decomposition does not pull
    off-topic noise into the library. Returns the ingest counts plus how many
    raw records were flattened from the cache.
    """
    records = _flatten_cache(pool_db_path, since)
    result = record_external_source(
        store,
        direction_id,
        source_name,
        records,
        triage_keywords=triage_keywords,
        import_budget=import_budget,
        round_no=round_no,
        query=f"gap-verify-cache since={since or 'all'}",
    )
    result["cache_records_flattened"] = len(records)
    return result
