"""Importer from the RH pool DB into a PanoramaStore direction.

The pool DB remains the source of truth for paper metadata; panorama paper
entities reference it via ``pool_paper_id`` plus external ids (arxiv/doi/s2)
and only carry a truncated abstract as a local summary.

The pool ``claims`` table has drifted across migrations, so its schema is
discovered at runtime (PRAGMA table_info): claims may link papers through a
direct ``paper_id`` column or a ``paper_ids_json`` JSON array; if neither is
present (or no claim touches an imported paper) the claim import is skipped
gracefully.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..store import PanoramaStore

_SUMMARY_MAX = 600
_CLAIM_NAME_MAX = 120
_CLAIM_TEXT_COLUMNS = ("text", "claim_text", "claim", "content")


def _truncate(text: str | None, limit: int = _SUMMARY_MAX) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _connect_readonly(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_anchor(
    store: PanoramaStore,
    target_kind: str,
    target_id: int,
    *,
    quote_text: str,
    source_ref: str,
    keywords: str = "",
    summary: str = "",
    insight: str = "",
) -> bool:
    """Add a 4-tuple evidence anchor unless an identical one already exists.

    ``PanoramaStore.add_anchor`` is append-only, so importer idempotency for
    anchors is enforced here by (quote, source_ref) equality.
    """
    for anchor in store.anchors_for(target_kind, target_id):
        if anchor["quote"] == quote_text and anchor["source_ref"] == source_ref:
            return False
    store.add_anchor(
        target_kind,
        target_id,
        keywords=keywords,
        summary=summary,
        insight=insight,
        quote=quote_text,
        source_ref=source_ref,
    )
    return True


def _claims_columns(conn: sqlite3.Connection) -> set[str]:
    try:
        rows = conn.execute("PRAGMA table_info(claims)").fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {row[1] for row in rows}


def _linked_paper_ids(row: sqlite3.Row, cols: set[str]) -> list[int]:
    if "paper_id" in cols and row["paper_id"] is not None:
        try:
            return [int(row["paper_id"])]
        except (TypeError, ValueError):
            return []
    if "paper_ids_json" in cols and row["paper_ids_json"]:
        try:
            parsed = json.loads(row["paper_ids_json"])
        except (TypeError, ValueError):
            return []
        if not isinstance(parsed, list):
            return []
        out: list[int] = []
        for item in parsed:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out
    return []


def _import_claims(
    store: PanoramaStore,
    direction_id: int,
    conn: sqlite3.Connection,
    paper_entity_ids: dict[int, int],
    counts: dict[str, int],
) -> None:
    cols = _claims_columns(conn)
    if not cols:
        return
    text_col = next((c for c in _CLAIM_TEXT_COLUMNS if c in cols), None)
    if text_col is None:
        return
    if "paper_id" not in cols and "paper_ids_json" not in cols:
        return
    for row in conn.execute("SELECT * FROM claims").fetchall():
        text = (row[text_col] or "").strip()
        if not text:
            continue
        linked = [
            pid for pid in _linked_paper_ids(row, cols) if pid in paper_entity_ids
        ]
        if not linked:
            continue
        attrs: dict[str, Any] = {}
        ext_ids: dict[str, str] = {}
        if "id" in cols and row["id"] is not None:
            attrs["pool_claim_id"] = int(row["id"])
            ext_ids["pool_claim"] = str(row["id"])
        if "claim_type" in cols and row["claim_type"]:
            attrs["claim_type"] = row["claim_type"]
        claim_entity_id = store.upsert_entity(
            direction_id,
            "claim",
            text[:_CLAIM_NAME_MAX].strip(),
            summary=text,
            attrs=attrs,
            ext_ids=ext_ids,
            source="pooldb",
        )
        counts["claims_imported"] += 1
        for pid in linked:
            store.add_edge(
                direction_id, paper_entity_ids[pid], claim_entity_id, "claims"
            )
            counts["claim_edges"] += 1
            added = _ensure_anchor(
                store,
                "entity",
                claim_entity_id,
                quote_text=text,
                source_ref=f"pool:paper:{pid}",
            )
            if added:
                counts["claim_anchors"] += 1


def import_pool_papers(
    store: PanoramaStore,
    direction_id: int,
    pool_db_path: Path | str,
    rh_domain_id: int,
) -> dict[str, int]:
    """Import all pool papers tagged with ``rh_domain_id`` (plus their claims).

    Returns a counts dict; re-running is idempotent (entity/edge dedupe is
    delegated to the store, anchor dedupe is handled locally).
    """
    counts = {
        "papers_imported": 0,
        "papers_skipped": 0,
        "claims_imported": 0,
        "claim_edges": 0,
        "claim_anchors": 0,
    }
    conn = _connect_readonly(pool_db_path)
    try:
        rows = conn.execute(
            "SELECT p.id, p.title, p.authors, p.year, p.venue, p.doi, "
            "p.arxiv_id, p.s2_id, p.url, p.abstract, p.citation_count "
            "FROM papers p JOIN paper_domains pd ON pd.paper_id = p.id "
            "WHERE pd.domain_id = ? ORDER BY p.id",
            (rh_domain_id,),
        ).fetchall()
        paper_entity_ids: dict[int, int] = {}
        for row in rows:
            title = (row["title"] or "").strip()
            if not title:
                counts["papers_skipped"] += 1
                continue
            ext_ids = {
                scheme: value
                for scheme, value in (
                    ("arxiv", row["arxiv_id"]),
                    ("doi", row["doi"]),
                    ("s2", row["s2_id"]),
                )
                if value
            }
            attrs = {
                key: row[key]
                for key in ("year", "venue", "citation_count", "url")
                if row[key] not in (None, "")
            }
            entity_id = store.upsert_entity(
                direction_id,
                "paper",
                title,
                summary=_truncate(row["abstract"]),
                attrs=attrs,
                ext_ids=ext_ids,
                pool_paper_id=int(row["id"]),
                source="pooldb",
            )
            paper_entity_ids[int(row["id"])] = entity_id
            counts["papers_imported"] += 1
        _import_claims(store, direction_id, conn, paper_entity_ids, counts)
    finally:
        conn.close()
    return counts
