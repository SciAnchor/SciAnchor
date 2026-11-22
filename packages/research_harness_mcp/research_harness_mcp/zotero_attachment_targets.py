"""Target selection helpers for Zotero PDF attachment previews."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable

from research_harness_mcp.zotero_models_http import (
    ZoteroChatItemContext,
    ZoteroChatRequest,
    ZoteroChatTargetRef,
)

NormalizeZoteroChatTagsFn = Callable[[list[str]], list[str]]
ExtractRhPaperIdTagFn = Callable[[list[str]], int | None]
ResolveZoteroChatMatchFn = Callable[
    [sqlite3.Connection, ZoteroChatItemContext], dict[str, Any]
]


def zotero_attachment_target_refs(
    body: ZoteroChatRequest, target_source: str = ""
) -> list[ZoteroChatTargetRef]:
    source = str(target_source or "").strip()
    if source == "last_preview_targets":
        return list(body.item.last_preview_targets)
    if source == "selected_items":
        return list(body.item.selected_items)
    if source:
        return []
    if message_targets_last_preview(body.message) and body.item.last_preview_targets:
        return list(body.item.last_preview_targets)
    if body.item.selected_items:
        return list(body.item.selected_items)
    return []


def zotero_attachment_target_source_for_plan(body: ZoteroChatRequest, mode: str) -> str:
    if body.item.last_preview_targets and message_targets_last_preview(body.message):
        return "last_preview_targets"
    if body.item.selected_items:
        return "selected_items"
    if mode not in {"item", "reader_selection"} and body.item.last_preview_targets:
        return "last_preview_targets"
    return ""


def message_targets_last_preview(message: str) -> bool:
    compact = re.sub(r"\s+", "", str(message or ""))
    lowered = compact.lower()
    return any(
        token in compact or token in lowered
        for token in (
            "这",
            "这些",
            "上述",
            "上面",
            "候选",
            "清单",
            "preview",
            "selected",
        )
    )


def resolve_zotero_attachment_target(
    conn: sqlite3.Connection,
    target: ZoteroChatTargetRef,
    *,
    normalize_zotero_chat_tags: NormalizeZoteroChatTagsFn,
    extract_rh_paper_id_tag: ExtractRhPaperIdTagFn,
    resolve_zotero_chat_match: ResolveZoteroChatMatchFn,
) -> dict[str, Any]:
    paper_id = target.paper_id
    if not paper_id:
        paper_id = extract_rh_paper_id_tag(normalize_zotero_chat_tags(target.tags))
    if paper_id:
        row = conn.execute(
            """
            SELECT id, title, doi, arxiv_id, pdf_path
            FROM papers
            WHERE id = ?
            """,
            (int(paper_id),),
        ).fetchone()
        if row is None:
            return {
                "paper_id": int(paper_id),
                "title": target.title,
                "zotero_item_key": target.zotero_item_key,
            }
        topic_row = conn.execute(
            """
            SELECT t.id, t.name
            FROM paper_topics pt
            JOIN topics t ON t.id = pt.topic_id
            WHERE pt.paper_id = ?
            ORDER BY t.id
            LIMIT 1
            """,
            (int(paper_id),),
        ).fetchone()
        return {
            "paper_id": int(row["id"]),
            "topic_id": int(topic_row["id"]) if topic_row else target.topic_id,
            "title": row["title"] or target.title,
            "doi": row["doi"] or target.doi,
            "arxiv_id": row["arxiv_id"] or target.arxiv_id,
            "pdf_path": row["pdf_path"] or "",
            "zotero_item_key": target.zotero_item_key,
        }

    item = ZoteroChatItemContext(
        zotero_item_key=target.zotero_item_key,
        library_id=target.library_id,
        library_type=target.library_type,
        title=target.title,
        doi=target.doi,
        arxiv_id=target.arxiv_id,
        url=target.url,
        tags=target.tags,
    )
    matched = resolve_zotero_chat_match(conn, item)
    paper = matched.get("paper") or {}
    if not paper.get("id"):
        return {
            "title": target.title,
            "zotero_item_key": target.zotero_item_key,
        }
    row = conn.execute(
        "SELECT id, title, doi, arxiv_id, pdf_path FROM papers WHERE id = ?",
        (int(paper["id"]),),
    ).fetchone()
    if row is None:
        return {
            "paper_id": int(paper["id"]),
            "title": target.title,
            "zotero_item_key": target.zotero_item_key,
        }
    topic = matched.get("topic") or {}
    return {
        "paper_id": int(row["id"]),
        "topic_id": int(topic["id"]) if topic.get("id") else target.topic_id,
        "title": row["title"] or target.title,
        "doi": row["doi"] or target.doi,
        "arxiv_id": row["arxiv_id"] or target.arxiv_id,
        "pdf_path": row["pdf_path"] or "",
        "zotero_item_key": target.zotero_item_key,
    }
