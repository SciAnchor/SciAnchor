"""Read-only Zotero topic lookup helpers."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from research_harness_mcp.zotero_chat_intent import extract_explicit_topic_id
from research_harness_mcp.zotero_identity import normalize_zotero_library_id


def infer_zotero_import_topic(
    conn: sqlite3.Connection,
    body: Any,
    matched: dict[str, Any],
) -> dict[str, Any] | None:
    topic = matched.get("topic")
    if topic:
        return {"id": int(topic["id"]), "name": str(topic["name"] or "")}

    explicit_topic_id = extract_explicit_topic_id(body.message)
    if explicit_topic_id is not None:
        row = conn.execute(
            "SELECT id, name FROM topics WHERE id = ?",
            (explicit_topic_id,),
        ).fetchone()
        if row is not None:
            return {"id": int(row["id"]), "name": str(row["name"] or "")}

    text = str(body.message or "").strip()
    directory_topic_hints = zotero_directory_topic_hints(body.item)
    rows = conn.execute(
        """
        SELECT id, name
        FROM topics
        WHERE name <> ''
        ORDER BY LENGTH(name) DESC, id
        LIMIT 200
        """
    ).fetchall()
    for row in rows:
        topic_name = str(row["name"] or "").strip()
        if topic_name and (topic_name in text or topic_name in directory_topic_hints):
            return {"id": int(row["id"]), "name": topic_name}
    return None


def zotero_directory_topic_hints(item: Any) -> set[str]:
    """Return topic-name candidates from the current Zotero collection context."""

    hints: set[str] = set()
    name = str(item.current_directory_name or "").strip()
    path = str(item.current_directory_path or "").strip()
    if name:
        hints.add(name)
    if path:
        hints.add(path)
        for segment in re.split(r"\s*(?:/|>|›|\\\\)\s*", path):
            segment = segment.strip()
            if segment:
                hints.add(segment)
    return hints


def find_zotero_topic_by_name(
    conn: sqlite3.Connection, topic_name: str
) -> dict[str, Any] | None:
    name = str(topic_name or "").strip()
    if not name:
        return None
    row = conn.execute(
        """
        SELECT id, name
        FROM topics
        WHERE lower(name) = lower(?)
        ORDER BY id DESC
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    if row is None:
        return None
    return {"id": int(row["id"]), "name": str(row["name"] or "")}


def count_existing_zotero_collection_links(
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    target_collection_key: str,
    library_id: str,
    library_type: str,
    paper_ids: list[int],
) -> int:
    collection_key = str(target_collection_key or "").strip()
    library_id = normalize_zotero_library_id(library_id)
    library_type = str(library_type or "").strip()
    if not collection_key or not library_id or not paper_ids:
        return 0
    placeholders = ",".join("?" for _ in paper_ids)
    library_type_filter = "AND zotero_library_type = ?" if library_type else ""
    params: list[Any] = [topic_id, collection_key, library_id]
    if library_type:
        params.append(library_type)
    params.extend(paper_ids)
    row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT paper_id) AS count
        FROM zotero_item_links
        WHERE topic_id = ?
          AND zotero_collection_key = ?
          AND zotero_library_id = ?
          {library_type_filter}
          AND paper_id IN ({placeholders})
        """,
        params,
    ).fetchone()
    return int(row["count"]) if row and row["count"] is not None else 0
