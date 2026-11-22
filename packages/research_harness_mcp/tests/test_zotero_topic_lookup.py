"""Focused tests for Zotero topic lookup helper extraction."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE topics (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE zotero_item_links (
            paper_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            zotero_collection_key TEXT NOT NULL,
            zotero_library_id TEXT NOT NULL,
            zotero_library_type TEXT NOT NULL
        );
        """
    )
    return conn


def _body(message: str, *, name: str = "", path: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        message=message,
        item=SimpleNamespace(
            current_directory_name=name,
            current_directory_path=path,
        ),
    )


def test_zotero_topic_lookup_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_topic_lookup

    assert (
        http_api._infer_zotero_import_topic
        is zotero_topic_lookup.infer_zotero_import_topic
    )
    assert (
        http_api._zotero_directory_topic_hints
        is zotero_topic_lookup.zotero_directory_topic_hints
    )
    assert (
        http_api._find_zotero_topic_by_name
        is zotero_topic_lookup.find_zotero_topic_by_name
    )
    assert (
        http_api._count_existing_zotero_collection_links
        is zotero_topic_lookup.count_existing_zotero_collection_links
    )


def test_infer_zotero_import_topic_prefers_existing_match_then_explicit_id():
    from research_harness_mcp import zotero_topic_lookup

    conn = _conn()
    conn.executemany(
        "INSERT INTO topics (id, name) VALUES (?, ?)",
        [(1, "Agent Memory"), (2, "Graph RAG")],
    )

    assert zotero_topic_lookup.infer_zotero_import_topic(
        conn,
        _body("topic_id: 2"),
        {"topic": {"id": 1, "name": "Agent Memory"}},
    ) == {"id": 1, "name": "Agent Memory"}
    assert zotero_topic_lookup.infer_zotero_import_topic(
        conn,
        _body("topic_id: 2"),
        {},
    ) == {"id": 2, "name": "Graph RAG"}


def test_infer_zotero_import_topic_uses_text_and_directory_hints():
    from research_harness_mcp import zotero_topic_lookup

    conn = _conn()
    conn.executemany(
        "INSERT INTO topics (id, name) VALUES (?, ?)",
        [(1, "Agent"), (2, "Agent Memory"), (3, "Graph RAG")],
    )

    assert zotero_topic_lookup.infer_zotero_import_topic(
        conn,
        _body("请导入到 Agent Memory 主题"),
        {},
    ) == {"id": 2, "name": "Agent Memory"}
    assert (
        zotero_topic_lookup.infer_zotero_import_topic(
            conn,
            _body("导入当前目录"),
            {},
        )
        is None
    )
    assert zotero_topic_lookup.infer_zotero_import_topic(
        conn,
        _body(
            "导入当前目录",
            name="Folder",
            path="Library / Graph RAG",
        ),
        {},
    ) == {"id": 3, "name": "Graph RAG"}


def test_zotero_directory_hints_and_find_topic_by_name_are_preserved():
    from research_harness_mcp import zotero_topic_lookup

    conn = _conn()
    conn.executemany(
        "INSERT INTO topics (id, name) VALUES (?, ?)",
        [(1, "Graph RAG"), (2, "graph rag")],
    )

    item = SimpleNamespace(
        current_directory_name="Folder",
        current_directory_path="Library / Graph RAG > Seed",
    )
    assert zotero_topic_lookup.zotero_directory_topic_hints(item) == {
        "Folder",
        "Library / Graph RAG > Seed",
        "Library",
        "Graph RAG",
        "Seed",
    }
    assert zotero_topic_lookup.find_zotero_topic_by_name(conn, " GRAPH RAG ") == {
        "id": 2,
        "name": "graph rag",
    }
    assert zotero_topic_lookup.find_zotero_topic_by_name(conn, "") is None


def test_count_existing_zotero_collection_links_filters_and_deduplicates():
    from research_harness_mcp import zotero_topic_lookup

    conn = _conn()
    conn.executemany(
        """
        INSERT INTO zotero_item_links (
            paper_id, topic_id, zotero_collection_key,
            zotero_library_id, zotero_library_type
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (1, 10, "COLL", "42", "user"),
            (1, 10, "COLL", "42", "user"),
            (2, 10, "COLL", "42", "user"),
            (3, 10, "OTHER", "42", "user"),
            (4, 99, "COLL", "42", "user"),
        ],
    )

    assert (
        zotero_topic_lookup.count_existing_zotero_collection_links(
            conn,
            topic_id=10,
            target_collection_key="COLL",
            library_id=42,
            library_type="user",
            paper_ids=[1, 2, 3, 4],
        )
        == 2
    )
    assert (
        zotero_topic_lookup.count_existing_zotero_collection_links(
            conn,
            topic_id=10,
            target_collection_key="COLL",
            library_id="42",
            library_type="",
            paper_ids=[1, 2],
        )
        == 2
    )
    assert (
        zotero_topic_lookup.count_existing_zotero_collection_links(
            conn,
            topic_id=10,
            target_collection_key="",
            library_id="42",
            library_type="user",
            paper_ids=[1],
        )
        == 0
    )
