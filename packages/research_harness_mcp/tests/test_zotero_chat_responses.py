"""Focused tests for Zotero chat response helper extraction."""

from __future__ import annotations

from research_harness_mcp.zotero_models_http import (
    ZoteroChatItemContext,
    ZoteroChatRequest,
)


def _body(
    message: str,
    *,
    zotero_item_key: str = "",
    title: str = "",
    arxiv_id: str = "",
) -> ZoteroChatRequest:
    return ZoteroChatRequest(
        message=message,
        item=ZoteroChatItemContext(
            zotero_item_key=zotero_item_key,
            title=title,
            arxiv_id=arxiv_id,
        ),
    )


def test_zotero_chat_response_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_chat_responses

    assert (
        http_api._unsupported_zotero_write_message
        is zotero_chat_responses.unsupported_zotero_write_message
    )
    assert (
        http_api._zotero_chat_suggested_actions
        is zotero_chat_responses.zotero_chat_suggested_actions
    )
    assert (
        http_api._stable_zotero_chat_conversation_id
        is zotero_chat_responses.stable_zotero_chat_conversation_id
    )


def test_stable_zotero_chat_conversation_id_uses_topic_paper_and_item_identity():
    from research_harness_mcp import zotero_chat_responses

    matched = {
        "paper": {"id": 7},
        "topic": {"id": 3},
    }
    body = _body("下一步", zotero_item_key="ITEM1", title="Demo")

    first = zotero_chat_responses.stable_zotero_chat_conversation_id(body, matched)
    second = zotero_chat_responses.stable_zotero_chat_conversation_id(body, matched)
    changed = zotero_chat_responses.stable_zotero_chat_conversation_id(
        _body("下一步", zotero_item_key="ITEM1", title="Different"),
        matched,
    )

    assert first == second
    assert first.startswith("zotero-chat-")
    assert len(first) == len("zotero-chat-") + 16
    assert changed != first


def test_zotero_chat_suggested_actions_preserve_unmatched_and_matched_flows():
    from research_harness_mcp import zotero_chat_responses

    assert zotero_chat_responses.zotero_chat_suggested_actions({}) == [
        {
            "kind": "sync_or_ingest",
            "label": "先把当前 Zotero 条目同步/入库到 RH",
            "requires_confirmation": True,
        }
    ]

    actions = zotero_chat_responses.zotero_chat_suggested_actions(
        {"paper": {"id": 7}, "topic": {"id": 3}}
    )

    assert [action["kind"] for action in actions] == [
        "codex_handoff",
        "pull_human_notes",
        "paper_reading_annotation",
    ]
    assert {action["paper_id"] for action in actions} == {7}
    assert {action["topic_id"] for action in actions} == {3}
    assert actions[-1]["skill"] == "paper-reading-annotation"


def test_unsupported_zotero_write_message_preserves_pdf_identity_bits():
    from research_harness_mcp import zotero_chat_responses

    message = zotero_chat_responses.unsupported_zotero_write_message(
        _body(
            "请把 PDF 附加到当前条目",
            zotero_item_key="ITEM1",
            arxiv_id="2401.00001",
        ),
        {
            "paper": {"id": 7, "arxiv_id": "2301.00001"},
            "topic": {"id": 3},
        },
    )

    assert "PDF 附件写入" in message
    assert "RH paper_id=7" in message
    assert "Zotero ITEM1" in message
    assert "arXiv 2301.00001" in message
    assert "topic_id=3" in message


def test_unsupported_zotero_write_message_preserves_generic_current_item_text():
    from research_harness_mcp import zotero_chat_responses

    message = zotero_chat_responses.unsupported_zotero_write_message(
        _body("改一下元数据"),
        {},
    )

    assert "当前条目" in message
    assert "这个 Zotero/RH 写入动作" in message
