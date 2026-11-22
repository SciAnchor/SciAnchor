from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from research_harness_mcp.zotero_capabilities import (
    CapabilityResult,
    ZoteroCapability,
    ZoteroCapabilityBroker,
    rejection_to_dynamic_tool_response,
    result_to_dynamic_tool_response,
    zotero_capability_paper_list,
    zotero_capability_paper_search,
    zotero_execute_read_tool,
)


def test_zotero_capability_registry_lists_registered_metadata():
    broker = ZoteroCapabilityBroker()
    broker.register(
        ZoteroCapability(
            name="rh.paper.list",
            description="List papers",
            context_modes=("library",),
            read_only=True,
            handler=lambda _args, _ctx: {"papers": []},
        )
    )

    assert broker.get("rh.paper.list") is not None
    assert broker.list() == [
        {
            "name": "rh.paper.list",
            "description": "List papers",
            "input_schema": {},
            "context_modes": ["library"],
            "read_only": True,
            "requires_confirmation": False,
        }
    ]


def test_read_only_capability_executes_immediately():
    broker = ZoteroCapabilityBroker()
    calls: list[dict] = []

    def handler(args, context):
        calls.append({"args": args, "context": context})
        return {"summary": "Listed 1 paper", "papers": [{"id": 1}]}

    broker.register(
        ZoteroCapability(
            name="rh.paper.list",
            description="List papers",
            context_modes=("collection",),
            handler=handler,
        )
    )

    result = broker.invoke(
        "rh.paper.list",
        {"limit": 1},
        context={"mode": "collection"},
    )

    assert result.status == "completed"
    assert result.success is True
    assert result.output["papers"] == [{"id": 1}]
    assert calls == [{"args": {"limit": 1}, "context": {"mode": "collection"}}]


def test_write_capability_returns_preview_without_apply():
    broker = ZoteroCapabilityBroker()
    applied: list[dict] = []

    broker.register(
        ZoteroCapability(
            name="rh.zotero.create_collection",
            description="Create collection",
            context_modes=("collection",),
            read_only=False,
            requires_confirmation=True,
            preview_handler=lambda _args, _ctx: {
                "kind": "action_preview",
                "preview": {
                    "action_type": "zotero_create_collection",
                    "title": "新建 Zotero 文件夹",
                    "message": "准备新建文件夹",
                    "apply": {"type": "zotero_local"},
                },
            },
            apply_handler=lambda args, _ctx: applied.append(args) or {"ok": True},
        )
    )

    result = broker.invoke(
        "rh.zotero.create_collection",
        {"collection_name": "demo"},
        context={"mode": "collection"},
    )

    assert result.status == "preview"
    assert result.success is True
    assert result.action_preview["action_type"] == "zotero_create_collection"
    assert applied == []


def test_write_capability_preserves_preview_builder_assistant_message():
    broker = ZoteroCapabilityBroker()
    broker.register(
        ZoteroCapability(
            name="rh.zotero.prepare_seed_import",
            description="Prepare seed import",
            context_modes=("collection",),
            read_only=False,
            requires_confirmation=True,
            preview_handler=lambda _args, _ctx: {
                "kind": "assistant_message",
                "message": "请先选中一个具体 Zotero 目录。",
            },
        )
    )

    result = broker.invoke(
        "rh.zotero.prepare_seed_import",
        {},
        context={"mode": "collection"},
    )

    assert result.status == "assistant_message"
    assert result.success is True
    assert result.message == "请先选中一个具体 Zotero 目录。"
    assert result.output["kind"] == "assistant_message"
    assert result.action_preview is None


def test_unknown_or_wrong_mode_capability_is_rejected():
    broker = ZoteroCapabilityBroker()
    broker.register(
        ZoteroCapability(
            name="rh.zotero.attach_pdf",
            description="Attach PDF",
            context_modes=("item",),
            read_only=False,
            requires_confirmation=True,
            preview_handler=lambda _args, _ctx: {"action_type": "zotero_attach_pdf"},
        )
    )

    unknown = broker.invoke("rh.unknown", {}, context={"mode": "item"})
    wrong_mode = broker.invoke(
        "rh.zotero.attach_pdf",
        {},
        context={"mode": "collection"},
    )

    assert unknown.status == "rejected"
    assert unknown.success is False
    assert wrong_mode.status == "rejected"
    assert "collection" in wrong_mode.message


def test_dynamic_tool_response_uses_codex_content_item_shape():
    response = result_to_dynamic_tool_response(
        CapabilityResult(
            capability="rh.paper.list",
            status="completed",
            success=True,
            message="ok",
            output={"papers": []},
        )
    )

    assert response["success"] is True
    assert response["contentItems"][0]["type"] == "inputText"
    payload = json.loads(response["contentItems"][0]["text"])
    assert payload["capability"] == "rh.paper.list"
    assert payload["status"] == "completed"

    rejected = rejection_to_dynamic_tool_response("not allowed")
    assert rejected["success"] is False
    assert json.loads(rejected["contentItems"][0]["text"])["message"] == "not allowed"


def test_zotero_execute_read_tool_preserves_http_api_alias_and_shape():
    from research_harness_mcp import http_api

    calls: list[dict[str, object]] = []

    def run_tool(name: str, arguments: dict) -> dict:
        calls.append({"name": name, "arguments": dict(arguments)})
        return {"ok": True, "topic_id": arguments["topic_id"]}

    assert http_api._zotero_execute_read_tool is zotero_execute_read_tool
    result = zotero_execute_read_tool(
        "provenance_summary",
        {"topic_id": 7},
        run_tool=run_tool,
    )

    assert result == {
        "summary": "Executed provenance_summary",
        "tool": "provenance_summary",
        "output": {"ok": True, "topic_id": 7},
    }
    assert calls == [{"name": "provenance_summary", "arguments": {"topic_id": 7}}]


def test_zotero_execute_read_tool_requires_scope_for_selected_primitives():
    with pytest.raises(
        ValueError, match="claim_extract requires paper_ids or topic_id"
    ):
        zotero_execute_read_tool(
            "claim_extract",
            {},
            run_tool=lambda _name, _arguments: {},
        )

    with pytest.raises(ValueError, match="gap_detect requires paper_ids or topic_id"):
        zotero_execute_read_tool(
            "gap_detect",
            {},
            run_tool=lambda _name, _arguments: {},
        )


def test_zotero_capability_paper_list_preserves_filtering_and_shape(tmp_path: Path):
    from research_harness_mcp import http_api

    db_path = tmp_path / "paper-list.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            authors TEXT,
            year INTEGER,
            venue TEXT,
            doi TEXT,
            arxiv_id TEXT,
            status TEXT,
            deep_read INTEGER
        );
        CREATE TABLE topics (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE paper_topics (paper_id INTEGER, topic_id INTEGER);
        """
    )
    conn.execute(
        "INSERT INTO topics (id, name) VALUES (?, ?)",
        (3, "demo-topic"),
    )
    conn.execute(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            7,
            "Matched Paper",
            json.dumps(["Ada", "Lin"]),
            2026,
            "ICML",
            "10.1000/demo",
            "2601.00001",
            "active",
            1,
        ),
    )
    conn.execute("INSERT INTO paper_topics VALUES (?, ?)", (7, 3))
    conn.execute(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (8, "Other Paper", "[]", 2024, "", "", "", "", 0),
    )
    conn.commit()
    conn.close()

    @contextmanager
    def get_db_context():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    result = zotero_capability_paper_list(
        {"limit": 99, "topic_name": "demo-topic", "deep_read": True},
        {},
        get_db_context=get_db_context,
        parse_json_field=lambda value, fallback: (
            json.loads(value) if value else fallback
        ),
    )

    assert callable(http_api._zotero_capability_paper_list)
    assert result == {
        "summary": "Found 1 RH papers",
        "papers": [
            {
                "id": 7,
                "title": "Matched Paper",
                "authors": ["Ada", "Lin"],
                "year": 2026,
                "venue": "ICML",
                "doi": "10.1000/demo",
                "arxiv_id": "2601.00001",
                "status": "active",
                "deep_read": True,
            }
        ],
        "limit": 50,
    }


def test_zotero_capability_paper_search_preserves_query_and_scope():
    api = object()
    calls: list[dict[str, Any]] = []

    def search_papers_impl(api_arg: object, **kwargs: Any) -> dict[str, Any]:
        calls.append({"api": api_arg, **kwargs})
        return {
            "papers": [{"id": index} for index in range(20)],
            "provider_errors": ["rate limited"],
        }

    result = zotero_capability_paper_search(
        {"query": " agent memory ", "topic_id": "7", "max_results": 99},
        {},
        api_factory=lambda: api,
        search_papers_impl=search_papers_impl,
    )

    assert result["summary"] == "Found 12 candidate papers for agent memory"
    assert result["query"] == "agent memory"
    assert result["papers"] == [{"id": index} for index in range(12)]
    assert result["provider_errors"] == ["rate limited"]
    assert calls == [
        {
            "api": api,
            "query": "agent memory",
            "topic_id": 7,
            "max_results": 12,
        }
    ]

    with pytest.raises(ValueError, match="query is required"):
        zotero_capability_paper_search(
            {"query": " "},
            {},
            api_factory=lambda: api,
            search_papers_impl=search_papers_impl,
        )
