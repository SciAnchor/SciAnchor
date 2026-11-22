"""Focused tests for Zotero chat match helper extraction."""

from __future__ import annotations

import json
import sqlite3

from research_harness_mcp.zotero_models_http import (
    ZoteroChatItemContext,
    ZoteroChatRequest,
    ZoteroChatTargetRef,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE topics (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT,
            year INTEGER,
            venue TEXT,
            doi TEXT,
            arxiv_id TEXT,
            url TEXT,
            abstract TEXT,
            status TEXT,
            deep_read INTEGER
        );
        CREATE TABLE paper_topics (
            paper_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL
        );
        CREATE TABLE zotero_item_links (
            paper_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            zotero_library_id TEXT,
            zotero_library_type TEXT,
            zotero_collection_key TEXT,
            zotero_item_key TEXT,
            zotero_note_key TEXT,
            last_synced_at TEXT
        );
        """
    )
    return conn


def _insert_demo_paper(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (3, 'demo-topic')")
    conn.execute(
        """
        INSERT INTO papers (
            id, title, authors, year, venue, doi, arxiv_id, url,
            abstract, status, deep_read
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            7,
            "Agentic Zotero API Sync",
            json.dumps(["Ada Lovelace"]),
            2026,
            "ICLR",
            "10.1234/zotero-api",
            "2602.99999",
            "https://arxiv.org/abs/2602.99999",
            "A paper for Zotero API sync tests.",
            "pdf_ready",
            1,
        ),
    )
    conn.execute("INSERT INTO paper_topics (paper_id, topic_id) VALUES (7, 3)")
    conn.commit()


def test_zotero_chat_match_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_chat_match

    assert (
        http_api._resolve_zotero_chat_match
        is zotero_chat_match.resolve_zotero_chat_match
    )
    assert (
        http_api._find_zotero_linked_paper is zotero_chat_match.find_zotero_linked_paper
    )
    assert (
        http_api._find_paper_topic_for_chat
        is zotero_chat_match.find_paper_topic_for_chat
    )
    assert (
        http_api._find_paper_by_bibliographic_context
        is zotero_chat_match.find_paper_by_bibliographic_context
    )
    assert http_api._find_paper_by_field is zotero_chat_match.find_paper_by_field
    assert (
        http_api._zotero_chat_match_payload
        is zotero_chat_match.zotero_chat_match_payload
    )
    assert (
        http_api._build_zotero_chat_assistant_message
        is zotero_chat_match.build_zotero_chat_assistant_message
    )
    assert http_api._zotero_context_payload is zotero_chat_match.zotero_context_payload


def test_resolve_zotero_chat_match_prefers_existing_link_with_library_filter():
    from research_harness_mcp import zotero_chat_match

    conn = _conn()
    _insert_demo_paper(conn)
    conn.execute(
        """
        INSERT INTO zotero_item_links (
            paper_id, topic_id, zotero_library_id, zotero_library_type,
            zotero_collection_key, zotero_item_key, zotero_note_key, last_synced_at
        )
        VALUES (7, 3, '2', 'group', 'COLL', 'ITEM1', 'NOTE1', '2026-06-13')
        """
    )

    matched = zotero_chat_match.resolve_zotero_chat_match(
        conn,
        ZoteroChatItemContext(
            zotero_item_key="ITEM1",
            library_id="2",
            library_type="group",
            title="Different local title",
            tags=["rh-paper-id:999"],
        ),
    )

    assert matched["source"] == "zotero_item_links"
    assert matched["confidence"] == 1.0
    assert matched["paper"]["id"] == 7
    assert matched["paper"]["authors"] == ["Ada Lovelace"]
    assert matched["paper"]["venue_tier"] == "CCF-A*"
    assert matched["topic"] == {"id": 3, "name": "demo-topic"}
    assert matched["zotero_link"]["zotero_item_key"] == "ITEM1"


def test_resolve_zotero_chat_match_falls_back_from_bad_topic_tag_to_paper():
    from research_harness_mcp import zotero_chat_match

    conn = _conn()
    _insert_demo_paper(conn)

    matched = zotero_chat_match.resolve_zotero_chat_match(
        conn,
        ZoteroChatItemContext(
            title="Not used",
            tags=["rh-paper-id:7", "rh-topic:missing-topic"],
        ),
    )

    assert matched["source"] == "rh_tags"
    assert matched["paper"]["id"] == 7
    assert matched["topic"] == {"id": 3, "name": "demo-topic"}
    assert matched["zotero_link"] is None


def test_resolve_zotero_chat_match_uses_bibliographic_fallbacks():
    from research_harness_mcp import zotero_chat_match

    conn = _conn()
    _insert_demo_paper(conn)

    by_doi = zotero_chat_match.resolve_zotero_chat_match(
        conn,
        ZoteroChatItemContext(doi="https://doi.org/10.1234/zotero-api"),
    )
    by_arxiv = zotero_chat_match.resolve_zotero_chat_match(
        conn,
        ZoteroChatItemContext(url="https://arxiv.org/abs/2602.99999"),
    )
    by_title = zotero_chat_match.resolve_zotero_chat_match(
        conn,
        ZoteroChatItemContext(title="  Agentic   Zotero API Sync  "),
    )

    assert by_doi["source"] == "bibliographic_fallback"
    assert by_arxiv["paper"]["id"] == 7
    assert by_title["paper"]["id"] == 7
    assert by_doi["confidence"] == 0.7


def test_zotero_assistant_message_and_context_payload_are_preserved():
    from research_harness_mcp import zotero_chat_match

    body = ZoteroChatRequest(
        message="下一步",
        item=ZoteroChatItemContext(
            zotero_item_key="ITEM1",
            library_id=2,
            library_type="group",
            title="Local title",
            selected_text="important passage",
            current_directory_key="COLL",
            current_directory_name="Folder",
            current_directory_path="Library / Folder",
            selected_items=[ZoteroChatTargetRef(title="A")],
            last_preview_targets=[ZoteroChatTargetRef(title="B")],
        ),
    )
    matched = {
        "paper": {
            "id": 7,
            "title": "Agentic Zotero API Sync",
            "status": "pdf_ready",
            "deep_read": True,
        },
        "topic": {"id": 3, "name": "demo-topic"},
    }

    message = zotero_chat_match.build_zotero_chat_assistant_message(body, matched)
    context = zotero_chat_match.zotero_context_payload(body, matched)

    assert "RH paper #7" in message
    assert "主题：demo-topic" in message
    assert "已精读" in message
    assert "选择的文本" in message
    assert context == {
        "kind": "paper",
        "zotero_item_key": "ITEM1",
        "zotero_title": "Local title",
        "paper_id": 7,
        "paper_title": "Agentic Zotero API Sync",
        "topic_id": 3,
        "topic_name": "demo-topic",
        "directory": {
            "key": "COLL",
            "name": "Folder",
            "path": "Library / Folder",
            "library_id": "2",
            "library_type": "group",
        },
        "selected_items_count": 1,
        "last_preview_targets_count": 1,
    }
