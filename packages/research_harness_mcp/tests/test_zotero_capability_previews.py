"""Focused tests for Zotero capability preview adapter extraction."""

from __future__ import annotations

from typing import Any

import pytest

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


def _body(message: str = "帮我处理当前 Zotero 目录") -> ZoteroChatRequest:
    return ZoteroChatRequest.model_validate(
        {
            "message": message,
            "item": {
                "zotero_item_key": "ITEM1",
                "current_directory_key": "COLL1",
                "current_directory_name": "Agent Seeds",
                "current_directory_path": "Root / Agent Seeds",
                "library_id": "1",
                "library_type": "user",
            },
        }
    )


def test_zotero_capability_previews_module_imports_and_http_wrappers_exist():
    from research_harness_mcp import http_api, zotero_capability_previews

    assert callable(zotero_capability_previews.zotero_preview_seed_import)
    assert callable(zotero_capability_previews.zotero_preview_create_collection)
    assert callable(zotero_capability_previews.zotero_preview_sync_papers)
    assert callable(zotero_capability_previews.zotero_preview_attach_pdf)
    assert callable(http_api._zotero_preview_seed_import)
    assert callable(http_api._zotero_preview_create_collection)
    assert callable(http_api._zotero_preview_sync_papers)
    assert callable(http_api._zotero_preview_attach_pdf)


def test_zotero_preview_seed_import_defaults_query_topic_and_flags():
    from research_harness_mcp.zotero_capability_previews import (
        zotero_preview_seed_import,
    )

    calls: list[dict[str, Any]] = []
    body = _body()
    matched = {"topic": {"id": 7}}

    result = zotero_preview_seed_import(
        body=body,
        matched=matched,
        args={"limit": "14", "request_pdf_annotations": True},
        last_zotero_path_segment=lambda path: str(path).split("/")[-1].strip(),
        coerce_zotero_capability_count=lambda value, default: min(int(value), 12),
        build_zotero_seed_papers_preview=lambda **kwargs: (
            calls.append(kwargs) or {"kind": "action_preview"}
        ),
    )

    assert result == {"kind": "action_preview"}
    assert calls == [
        {
            "body": body,
            "matched": matched,
            "topic_name": "Agent Seeds",
            "query": "Agent Seeds",
            "requested_count": 12,
            "request_flags": {
                "request_deep_read": False,
                "request_pdf_attachment": True,
                "request_pdf_annotations": True,
            },
        }
    ]


def test_zotero_preview_create_collection_requires_name_and_rewrites_message():
    from research_harness_mcp.zotero_capability_previews import (
        zotero_preview_create_collection,
    )

    calls: list[dict[str, Any]] = []

    with pytest.raises(ValueError, match="collection_name is required"):
        zotero_preview_create_collection(
            body=_body(),
            matched={},
            args={},
            prepare_zotero_create_collection_action=lambda *_args: {},
        )

    result = zotero_preview_create_collection(
        body=_body("原始消息"),
        matched={"source": "directory"},
        args={"name": "Reading Queue"},
        prepare_zotero_create_collection_action=lambda body, matched: (
            calls.append({"message": body.message, "matched": matched})
            or {"kind": "action_preview"}
        ),
    )

    assert result == {"kind": "action_preview"}
    assert calls == [
        {"message": "新建文件夹“Reading Queue”", "matched": {"source": "directory"}}
    ]


def test_zotero_preview_sync_papers_preserves_message_priority_and_action_type():
    from research_harness_mcp.zotero_capability_previews import (
        zotero_preview_sync_papers,
    )

    calls: list[dict[str, Any]] = []

    result = zotero_preview_sync_papers(
        body=_body("原始消息"),
        matched={"topic": {"id": 3}},
        args={"topic_id": 3, "limit": 2},
        maybe_prepare_zotero_chat_action=lambda body, matched: (
            calls.append(
                {
                    "message": body.message,
                    "requested_action_type": body.requested_action_type,
                    "matched": matched,
                }
            )
            or {"kind": "action_preview"}
        ),
    )

    assert result == {"kind": "action_preview"}
    assert calls == [
        {
            "message": "把前 2 篇论文导入当前目录",
            "requested_action_type": "sync_rh_papers_to_collection",
            "matched": {"topic": {"id": 3}},
        }
    ]


def test_zotero_preview_attach_pdf_passes_target_refs_and_source():
    from research_harness_mcp.zotero_capability_previews import (
        zotero_preview_attach_pdf,
    )

    calls: list[dict[str, Any]] = []
    body = _body()

    result = zotero_preview_attach_pdf(
        body=body,
        matched={"paper": {"id": 9}},
        args={"target_source": "last_preview"},
        zotero_attachment_target_refs=lambda body, target_source: [
            {"key": body.item.zotero_item_key, "source": target_source}
        ],
        prepare_zotero_pdf_attachment_action=lambda body, matched, **kwargs: (
            calls.append(
                {
                    "message": body.message,
                    "matched": matched,
                    "target_refs": kwargs["target_refs"],
                    "target_source": kwargs["target_source"],
                }
            )
            or {"kind": "action_preview"}
        ),
    )

    assert result == {"kind": "action_preview"}
    assert calls == [
        {
            "message": "给当前条目附加 PDF",
            "matched": {"paper": {"id": 9}},
            "target_refs": [{"key": "ITEM1", "source": "last_preview"}],
            "target_source": "last_preview",
        }
    ]
