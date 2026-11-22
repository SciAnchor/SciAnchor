"""Focused tests for Zotero attachment target helper extraction."""

from __future__ import annotations

import sqlite3
from typing import Any

from research_harness_mcp.zotero_models_http import (
    ZoteroChatItemContext,
    ZoteroChatRequest,
    ZoteroChatTargetRef,
)


def _target(key: str) -> ZoteroChatTargetRef:
    return ZoteroChatTargetRef(zotero_item_key=key, title=f"Paper {key}")


def _body(
    message: str,
    *,
    selected: list[ZoteroChatTargetRef] | None = None,
    preview: list[ZoteroChatTargetRef] | None = None,
) -> ZoteroChatRequest:
    return ZoteroChatRequest(
        message=message,
        item=ZoteroChatItemContext(
            selected_items=list(selected or []),
            last_preview_targets=list(preview or []),
        ),
    )


def _keys(targets: list[ZoteroChatTargetRef]) -> list[str]:
    return [target.zotero_item_key for target in targets]


def _paper_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            doi TEXT,
            arxiv_id TEXT,
            pdf_path TEXT
        )
        """
    )
    conn.execute("CREATE TABLE topics (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE paper_topics (paper_id INTEGER, topic_id INTEGER)")
    conn.executemany(
        "INSERT INTO papers (id, title, doi, arxiv_id, pdf_path) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Resolved Direct", "10.1234/direct", "2601.00001", "/tmp/one.pdf"),
            (2, "Resolved Match", "10.1234/match", "2601.00002", "/tmp/two.pdf"),
        ],
    )
    conn.execute("INSERT INTO topics (id, name) VALUES (10, 'Direct Topic')")
    conn.execute("INSERT INTO paper_topics (paper_id, topic_id) VALUES (1, 10)")
    conn.commit()
    return conn


def test_zotero_attachment_target_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_attachment_targets

    assert (
        http_api._zotero_attachment_target_refs
        is zotero_attachment_targets.zotero_attachment_target_refs
    )
    assert (
        http_api._message_targets_last_preview
        is zotero_attachment_targets.message_targets_last_preview
    )
    assert (
        http_api._zotero_attachment_target_source_for_plan
        is zotero_attachment_targets.zotero_attachment_target_source_for_plan
    )


def test_attachment_target_refs_honor_explicit_source():
    from research_harness_mcp import zotero_attachment_targets

    selected = [_target("SELECTED1")]
    preview = [_target("PREVIEW1"), _target("PREVIEW2")]
    body = _body("附加 PDF", selected=selected, preview=preview)

    assert _keys(
        zotero_attachment_targets.zotero_attachment_target_refs(
            body,
            target_source="last_preview_targets",
        )
    ) == ["PREVIEW1", "PREVIEW2"]
    assert _keys(
        zotero_attachment_targets.zotero_attachment_target_refs(
            body,
            target_source="selected_items",
        )
    ) == ["SELECTED1"]
    assert (
        zotero_attachment_targets.zotero_attachment_target_refs(
            body,
            target_source="unknown",
        )
        == []
    )


def test_attachment_target_refs_prefers_referenced_preview_then_selected_items():
    from research_harness_mcp import zotero_attachment_targets

    selected = [_target("SELECTED1")]
    preview = [_target("PREVIEW1")]

    assert _keys(
        zotero_attachment_targets.zotero_attachment_target_refs(
            _body("把上述候选附加 PDF", selected=selected, preview=preview)
        )
    ) == ["PREVIEW1"]
    assert _keys(
        zotero_attachment_targets.zotero_attachment_target_refs(
            _body("attach PDF", selected=selected, preview=preview)
        )
    ) == ["SELECTED1"]
    assert (
        zotero_attachment_targets.zotero_attachment_target_refs(_body("attach PDF"))
        == []
    )


def test_attachment_target_refs_falls_back_to_selected_when_preview_missing():
    from research_harness_mcp import zotero_attachment_targets

    selected = [_target("SELECTED1")]

    assert _keys(
        zotero_attachment_targets.zotero_attachment_target_refs(
            _body("把这些候选附加 PDF", selected=selected)
        )
    ) == ["SELECTED1"]


def test_message_targets_last_preview_tokens_are_preserved():
    from research_harness_mcp import zotero_attachment_targets

    assert zotero_attachment_targets.message_targets_last_preview("请处理上述候选")
    assert zotero_attachment_targets.message_targets_last_preview("use PREVIEW results")
    assert zotero_attachment_targets.message_targets_last_preview("use selected items")
    assert not zotero_attachment_targets.message_targets_last_preview("attach PDF")


def test_attachment_target_source_for_plan_preserves_selection_order():
    from research_harness_mcp import zotero_attachment_targets

    selected = [_target("SELECTED1")]
    preview = [_target("PREVIEW1")]

    assert (
        zotero_attachment_targets.zotero_attachment_target_source_for_plan(
            _body("给上述候选附加 PDF", selected=selected, preview=preview),
            "collection",
        )
        == "last_preview_targets"
    )
    assert (
        zotero_attachment_targets.zotero_attachment_target_source_for_plan(
            _body("给当前选中的条目附加 PDF", selected=selected, preview=preview),
            "collection",
        )
        == "selected_items"
    )
    assert (
        zotero_attachment_targets.zotero_attachment_target_source_for_plan(
            _body("attach PDF", preview=preview),
            "collection",
        )
        == "last_preview_targets"
    )


def test_attachment_target_source_for_plan_preserves_empty_fallback_boundaries():
    from research_harness_mcp import zotero_attachment_targets

    preview = [_target("PREVIEW1")]

    assert (
        zotero_attachment_targets.zotero_attachment_target_source_for_plan(
            _body("attach PDF", preview=preview),
            "item",
        )
        == ""
    )
    assert (
        zotero_attachment_targets.zotero_attachment_target_source_for_plan(
            _body("attach PDF", preview=preview),
            "reader_selection",
        )
        == ""
    )
    assert (
        zotero_attachment_targets.zotero_attachment_target_source_for_plan(
            _body("attach PDF"),
            "collection",
        )
        == ""
    )


def test_resolve_zotero_attachment_target_uses_explicit_paper_id():
    from research_harness_mcp import zotero_attachment_targets

    conn = _paper_conn()
    target = ZoteroChatTargetRef(
        paper_id=1,
        topic_id=99,
        zotero_item_key="ITEM1",
        title="Target Title",
        doi="10.fallback/target",
        arxiv_id="fallback-arxiv",
    )

    result = zotero_attachment_targets.resolve_zotero_attachment_target(
        conn,
        target,
        normalize_zotero_chat_tags=lambda tags: list(tags),
        extract_rh_paper_id_tag=lambda _tags: (_ for _ in ()).throw(
            AssertionError("tag extraction should not run when paper_id is explicit")
        ),
        resolve_zotero_chat_match=lambda *_args: (_ for _ in ()).throw(
            AssertionError("chat match should not run when paper_id is explicit")
        ),
    )

    assert result == {
        "paper_id": 1,
        "topic_id": 10,
        "title": "Resolved Direct",
        "doi": "10.1234/direct",
        "arxiv_id": "2601.00001",
        "pdf_path": "/tmp/one.pdf",
        "zotero_item_key": "ITEM1",
    }


def test_resolve_zotero_attachment_target_falls_back_to_chat_match():
    from research_harness_mcp import zotero_attachment_targets

    conn = _paper_conn()
    calls: list[dict[str, Any]] = []
    target = ZoteroChatTargetRef(
        zotero_item_key="ITEM2",
        library_id="42",
        library_type="group",
        title="Target Match",
        doi="10.1234/match",
        arxiv_id="2601.00002",
        url="https://example.test/paper",
        tags=["raw-tag"],
    )

    def fake_match(db_conn: sqlite3.Connection, item: ZoteroChatItemContext):
        assert db_conn is conn
        calls.append(item.model_dump())
        return {"paper": {"id": 2}, "topic": {"id": 22}}

    result = zotero_attachment_targets.resolve_zotero_attachment_target(
        conn,
        target,
        normalize_zotero_chat_tags=lambda tags: [f"normalized:{tag}" for tag in tags],
        extract_rh_paper_id_tag=lambda tags: (
            calls.append({"normalized_tags": tags}) or None
        ),
        resolve_zotero_chat_match=fake_match,
    )

    assert calls[0] == {"normalized_tags": ["normalized:raw-tag"]}
    assert calls[1]["zotero_item_key"] == "ITEM2"
    assert calls[1]["library_id"] == "42"
    assert calls[1]["library_type"] == "group"
    assert calls[1]["title"] == "Target Match"
    assert result == {
        "paper_id": 2,
        "topic_id": 22,
        "title": "Resolved Match",
        "doi": "10.1234/match",
        "arxiv_id": "2601.00002",
        "pdf_path": "/tmp/two.pdf",
        "zotero_item_key": "ITEM2",
    }


def test_http_api_resolve_zotero_attachment_target_uses_dynamic_dependencies(
    monkeypatch,
):
    from research_harness_mcp import http_api

    conn = _paper_conn()
    calls: list[Any] = []

    monkeypatch.setattr(
        http_api,
        "_normalize_zotero_chat_tags",
        lambda tags: calls.append(("normalize", list(tags))) or ["normalized"],
    )
    monkeypatch.setattr(
        http_api,
        "_extract_rh_paper_id_tag",
        lambda tags: calls.append(("extract", list(tags))) or 2,
    )
    monkeypatch.setattr(
        http_api,
        "_resolve_zotero_chat_match",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("chat match should not run when tag resolves")
        ),
    )

    result = http_api._resolve_zotero_attachment_target(
        conn,
        ZoteroChatTargetRef(tags=["rh-paper-id:2"], zotero_item_key="ITEM2"),
    )

    assert calls == [
        ("normalize", ["rh-paper-id:2"]),
        ("extract", ["normalized"]),
    ]
    assert result["paper_id"] == 2
    assert result["title"] == "Resolved Match"
