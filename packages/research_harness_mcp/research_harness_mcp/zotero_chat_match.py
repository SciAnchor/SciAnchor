"""Zotero chat matching and context payload helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from research_harness.venue_facts import venue_tier_label
from research_harness_mcp.zotero_identity import (
    extract_rh_paper_id_tag,
    extract_rh_topic_tag,
    normalize_arxiv_id,
    normalize_doi,
    normalize_title_for_match,
    normalize_zotero_chat_tags,
    normalize_zotero_library_id,
)
from research_harness_mcp.zotero_models_http import (
    ZoteroChatItemContext,
    ZoteroChatRequest,
)


def _parse_json_field(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def resolve_zotero_chat_match(
    conn: sqlite3.Connection, item: ZoteroChatItemContext
) -> dict[str, Any]:
    """Resolve Zotero-side context to RH paper/topic records.

    Match order is deliberately RH-first:
    1. Existing zotero_item_links entry, if this item was pushed by RH.
    2. RH tags (`rh-paper-id:*`, `rh-topic:*`) written during sync.
    3. Bibliographic fallback by DOI, arXiv ID, then title.
    """
    tag_values = normalize_zotero_chat_tags(item.tags)
    library_id = normalize_zotero_library_id(item.library_id)

    link_row = find_zotero_linked_paper(
        conn,
        zotero_item_key=item.zotero_item_key,
        library_id=library_id,
        library_type=item.library_type,
    )
    if link_row is not None:
        return zotero_chat_match_payload(link_row, source="zotero_item_links")

    tag_paper_id = extract_rh_paper_id_tag(tag_values)
    tag_topic = extract_rh_topic_tag(tag_values)
    if tag_paper_id is not None:
        row = find_paper_topic_for_chat(
            conn,
            paper_id=tag_paper_id,
            topic_hint=tag_topic,
        )
        if row is not None:
            return zotero_chat_match_payload(row, source="rh_tags")

    bibliographic_row = find_paper_by_bibliographic_context(conn, item)
    if bibliographic_row is not None:
        return zotero_chat_match_payload(
            bibliographic_row, source="bibliographic_fallback"
        )

    return {
        "source": "unmatched",
        "paper": None,
        "topic": None,
        "zotero_link": None,
        "confidence": 0.0,
    }


def find_zotero_linked_paper(
    conn: sqlite3.Connection,
    *,
    zotero_item_key: str,
    library_id: str,
    library_type: str,
) -> sqlite3.Row | None:
    item_key = str(zotero_item_key or "").strip()
    if not item_key:
        return None
    library_id = str(library_id or "").strip()
    library_type = str(library_type or "").strip()
    library_filter = ""
    params: list[Any] = [item_key]
    if library_id:
        library_filter = "AND zil.zotero_library_id = ?"
        params.append(library_id)
        if library_type:
            library_filter += " AND zil.zotero_library_type = ?"
            params.append(library_type)
    try:
        return conn.execute(
            f"""
            SELECT
                p.id AS paper_id, p.title, p.authors, p.year, p.venue, p.doi,
                p.arxiv_id, p.url, p.abstract, p.status, p.deep_read,
                t.id AS topic_id, t.name AS topic_name,
                zil.zotero_library_id, zil.zotero_library_type,
                zil.zotero_collection_key, zil.zotero_item_key,
                zil.zotero_note_key, zil.last_synced_at
            FROM zotero_item_links zil
            JOIN papers p ON p.id = zil.paper_id
            JOIN topics t ON t.id = zil.topic_id
            WHERE zil.zotero_item_key = ?
              {library_filter}
            ORDER BY
                CASE WHEN zil.zotero_library_id = ? THEN 0 ELSE 1 END,
                CASE WHEN zil.zotero_library_type = ? THEN 0 ELSE 1 END,
                zil.last_synced_at DESC
            LIMIT 1
            """,
            (*params, library_id, library_type),
        ).fetchone()
    except sqlite3.OperationalError:
        return None


def find_paper_topic_for_chat(
    conn: sqlite3.Connection, *, paper_id: int, topic_hint: str
) -> sqlite3.Row | None:
    topic_hint = topic_hint.strip()
    params: list[Any] = [paper_id]
    topic_filter = ""
    if topic_hint:
        if topic_hint.isdigit():
            topic_filter = "AND t.id = ?"
            params.append(int(topic_hint))
        else:
            topic_filter = "AND t.name = ?"
            params.append(topic_hint)
    row = conn.execute(
        f"""
        SELECT
            p.id AS paper_id, p.title, p.authors, p.year, p.venue, p.doi,
            p.arxiv_id, p.url, p.abstract, p.status, p.deep_read,
            t.id AS topic_id, t.name AS topic_name,
            '' AS zotero_library_id, '' AS zotero_library_type,
            '' AS zotero_collection_key, '' AS zotero_item_key,
            '' AS zotero_note_key, '' AS last_synced_at
        FROM papers p
        LEFT JOIN paper_topics pt ON pt.paper_id = p.id
        LEFT JOIN topics t ON t.id = pt.topic_id
        WHERE p.id = ?
        {topic_filter}
        ORDER BY t.id IS NULL, t.id
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None and topic_hint:
        return find_paper_topic_for_chat(conn, paper_id=paper_id, topic_hint="")
    return row


def find_paper_by_bibliographic_context(
    conn: sqlite3.Connection, item: ZoteroChatItemContext
) -> sqlite3.Row | None:
    doi = normalize_doi(item.doi)
    if doi:
        row = find_paper_by_field(conn, "doi", doi)
        if row is not None:
            return row
    arxiv_id = normalize_arxiv_id(item.arxiv_id or item.url)
    if arxiv_id:
        row = find_paper_by_field(conn, "arxiv_id", arxiv_id)
        if row is not None:
            return row
    title = normalize_title_for_match(item.title)
    if title:
        return conn.execute(
            """
            SELECT
                p.id AS paper_id, p.title, p.authors, p.year, p.venue, p.doi,
                p.arxiv_id, p.url, p.abstract, p.status, p.deep_read,
                t.id AS topic_id, t.name AS topic_name,
                '' AS zotero_library_id, '' AS zotero_library_type,
                '' AS zotero_collection_key, '' AS zotero_item_key,
                '' AS zotero_note_key, '' AS last_synced_at
            FROM papers p
            LEFT JOIN paper_topics pt ON pt.paper_id = p.id
            LEFT JOIN topics t ON t.id = pt.topic_id
            WHERE lower(trim(p.title)) = lower(trim(?))
            ORDER BY t.id IS NULL, t.id
            LIMIT 1
            """,
            (title,),
        ).fetchone()
    return None


def find_paper_by_field(
    conn: sqlite3.Connection, field: Literal["doi", "arxiv_id"], value: str
) -> sqlite3.Row | None:
    return conn.execute(
        f"""
        SELECT
            p.id AS paper_id, p.title, p.authors, p.year, p.venue, p.doi,
            p.arxiv_id, p.url, p.abstract, p.status, p.deep_read,
            t.id AS topic_id, t.name AS topic_name,
            '' AS zotero_library_id, '' AS zotero_library_type,
            '' AS zotero_collection_key, '' AS zotero_item_key,
            '' AS zotero_note_key, '' AS last_synced_at
        FROM papers p
        LEFT JOIN paper_topics pt ON pt.paper_id = p.id
        LEFT JOIN topics t ON t.id = pt.topic_id
        WHERE lower(p.{field}) = lower(?)
        ORDER BY t.id IS NULL, t.id
        LIMIT 1
        """,
        (value,),
    ).fetchone()


def zotero_chat_match_payload(row: sqlite3.Row, *, source: str) -> dict[str, Any]:
    paper = {
        "id": int(row["paper_id"]),
        "title": row["title"] or "",
        "authors": _parse_json_field(row["authors"], []),
        "year": row["year"],
        "venue": row["venue"] or "",
        "venue_tier": venue_tier_label(row["venue"] or ""),
        "doi": row["doi"] or "",
        "arxiv_id": row["arxiv_id"] or "",
        "url": row["url"] or "",
        "abstract": row["abstract"] or "",
        "status": row["status"] or "",
        "deep_read": bool(row["deep_read"]),
    }
    topic_id = row["topic_id"]
    topic = (
        {"id": int(topic_id), "name": row["topic_name"] or ""}
        if topic_id is not None
        else None
    )
    zotero_link = None
    if row["zotero_item_key"]:
        zotero_link = {
            "zotero_library_id": row["zotero_library_id"] or "",
            "zotero_library_type": row["zotero_library_type"] or "",
            "zotero_collection_key": row["zotero_collection_key"] or "",
            "zotero_item_key": row["zotero_item_key"] or "",
            "zotero_note_key": row["zotero_note_key"] or "",
            "last_synced_at": row["last_synced_at"] or "",
        }
    confidence = 1.0 if source in {"zotero_item_links", "rh_tags"} else 0.7
    return {
        "source": source,
        "paper": paper,
        "topic": topic,
        "zotero_link": zotero_link,
        "confidence": confidence,
    }


def build_zotero_chat_assistant_message(
    body: ZoteroChatRequest, matched: dict[str, Any]
) -> str:
    paper = matched.get("paper")
    topic = matched.get("topic")
    if not paper:
        return (
            "我还没有把当前 Zotero 条目匹配到 RH 论文库。建议先执行一次 "
            "`rh zotero sync --direction push` 或在 Zotero 条目里保留 "
            "`rh-paper-id:*` 标签；也可以把 DOI/arXiv/title 发给 RH 入库。"
        )

    topic_text = f"；主题：{topic['name']}" if topic else ""
    deep_read_text = "已精读" if paper.get("deep_read") else "尚未标记精读"
    selected_text_hint = (
        "我也收到了你在 Zotero 中选择的文本，会把它作为局部阅读上下文。"
        if body.item.selected_text
        else "如果你在 PDF/笔记中选中文本再提问，我会把选区一起交给 RH/Codex。"
    )
    return (
        f"我已匹配到 RH paper #{paper['id']}《{paper['title']}》"
        f"{topic_text}；当前状态：{paper.get('status') or 'unknown'}，{deep_read_text}。"
        f"{selected_text_hint} 下一步可以让 Codex 基于 RH provenance 检查 deepread、"
        "导入人类笔记，或生成针对当前问题的阅读/实验建议。"
    )


def zotero_context_payload(
    body: ZoteroChatRequest, matched: dict[str, Any]
) -> dict[str, Any]:
    """Summarize the Zotero surface state for the side panel.

    The plugin needs to render different capabilities when the user is on a
    concrete item vs. when they have navigated back to a collection/library.
    Keep this payload model-owned and deterministic; action execution still
    requires a later backend-provided preview/apply spec.
    """

    item = body.item
    paper = matched.get("paper") or {}
    topic = matched.get("topic") or {}
    directory = {
        "key": item.current_directory_key,
        "name": item.current_directory_name,
        "path": item.current_directory_path,
        "library_id": normalize_zotero_library_id(item.library_id),
        "library_type": str(item.library_type or "user").strip() or "user",
    }
    has_item_context = bool(
        item.zotero_item_key
        or item.title
        or item.doi
        or item.arxiv_id
        or paper.get("id")
    )
    has_collection_context = bool(
        directory["key"] or directory["name"] or directory["path"]
    )
    if has_item_context:
        kind = "paper"
    elif has_collection_context:
        kind = "collection"
    else:
        kind = "library"
    return {
        "kind": kind,
        "zotero_item_key": item.zotero_item_key,
        "zotero_title": item.title,
        "paper_id": paper.get("id"),
        "paper_title": paper.get("title"),
        "topic_id": topic.get("id"),
        "topic_name": topic.get("name"),
        "directory": directory,
        "selected_items_count": len(item.selected_items),
        "last_preview_targets_count": len(item.last_preview_targets),
    }
