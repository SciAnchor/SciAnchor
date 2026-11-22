"""Focused tests for Zotero chat action dispatcher extraction."""

from __future__ import annotations

from typing import Any

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


def _body(
    message: str = "把当前论文导入当前目录",
    requested_action_type: str | None = "sync_rh_papers_to_collection",
) -> ZoteroChatRequest:
    payload: dict[str, Any] = {
        "message": message,
        "item": {
            "current_directory_key": "COLL1",
            "current_directory_name": "Agent Seeds",
            "current_directory_path": "Library / Agent Seeds",
            "zotero_item_key": "ITEM1",
        },
    }
    if requested_action_type is not None:
        payload["requested_action_type"] = requested_action_type
    return ZoteroChatRequest.model_validate(payload)


def _noop_dependencies() -> dict[str, Any]:
    return {
        "extract_zotero_import_count": lambda _message: None,
        "zotero_seed_request_flags": lambda _message: {},
        "zotero_explicit_seed_topic_name": lambda _message: "",
        "zotero_seed_search_query": lambda _body, *, topic_name: topic_name,
        "zotero_preview_seed_import": lambda **_kwargs: {
            "kind": "action_preview",
            "preview": {"action_type": "zotero_seed_paper_search"},
        },
        "zotero_context_payload": lambda _body, _matched: {"kind": "collection"},
        "zotero_attachment_target_source_for_plan": lambda _body, kind: kind,
        "zotero_attachment_target_refs": lambda _body, target_source: [
            {"target_source": target_source}
        ],
        "prepare_zotero_pdf_attachment_action": lambda *_args, **_kwargs: {
            "kind": "action_preview",
            "preview": {"action_type": "zotero_attach_pdf"},
        },
        "prepare_zotero_create_collection_action": lambda *_args: {
            "kind": "action_preview",
            "preview": {"action_type": "zotero_create_collection"},
        },
        "zotero_available_actions": lambda _context, _matched: [
            {"label": "导入当前主题论文"},
            {"label": ""},
            {"label": "新建文件夹"},
        ],
        "sync_papers_action_types": frozenset({"sync_rh_papers_to_collection"}),
        "prepare_zotero_sync_papers_action": lambda *_args, **_kwargs: {
            "kind": "action_preview",
            "preview": {"action_type": "sync_rh_papers_to_collection"},
        },
    }


def test_zotero_chat_actions_module_imports_and_http_wrapper_exists():
    from research_harness_mcp import http_api, zotero_chat_actions

    assert callable(zotero_chat_actions.maybe_prepare_zotero_chat_action)
    assert callable(http_api._maybe_prepare_zotero_chat_action)


def test_maybe_prepare_zotero_chat_action_ignores_missing_action_type():
    from research_harness_mcp.zotero_chat_actions import (
        maybe_prepare_zotero_chat_action,
    )

    result = maybe_prepare_zotero_chat_action(
        _body(requested_action_type=None),
        {},
        **_noop_dependencies(),
    )

    assert result is None


def test_maybe_prepare_zotero_chat_action_builds_seed_preview_args():
    from research_harness_mcp.zotero_chat_actions import (
        maybe_prepare_zotero_chat_action,
    )

    calls: list[dict[str, Any]] = []
    body = _body(
        "为“agentic discovery”找 8 篇种子论文",
        requested_action_type="rh.zotero.prepare_seed_import",
    )
    deps = _noop_dependencies()
    deps.update(
        {
            "extract_zotero_import_count": lambda _message: 8,
            "zotero_seed_request_flags": lambda _message: {
                "include_pdf": True,
                "deep_read": False,
            },
            "zotero_explicit_seed_topic_name": lambda _message: "agentic discovery",
            "zotero_seed_search_query": (
                lambda _body, *, topic_name: f"query:{topic_name}"
            ),
            "zotero_preview_seed_import": lambda **kwargs: (
                calls.append(kwargs)
                or {
                    "kind": "action_preview",
                    "preview": {"args": kwargs["args"]},
                }
            ),
        }
    )

    result = maybe_prepare_zotero_chat_action(
        body,
        {"topic": {"id": 3}},
        **deps,
    )

    assert result == {
        "kind": "action_preview",
        "preview": {
            "args": {
                "count": 8,
                "include_pdf": True,
                "deep_read": False,
                "topic_name": "agentic discovery",
                "query": "query:agentic discovery",
            }
        },
    }
    assert calls == [
        {
            "body": body,
            "matched": {"topic": {"id": 3}},
            "args": {
                "count": 8,
                "include_pdf": True,
                "deep_read": False,
                "topic_name": "agentic discovery",
                "query": "query:agentic discovery",
            },
        }
    ]


def test_maybe_prepare_zotero_chat_action_delegates_pdf_attachment_targets():
    from research_harness_mcp.zotero_chat_actions import (
        maybe_prepare_zotero_chat_action,
    )

    calls: list[dict[str, Any]] = []
    deps = _noop_dependencies()
    deps.update(
        {
            "zotero_context_payload": lambda _body, _matched: {"kind": "paper"},
            "zotero_attachment_target_source_for_plan": (
                lambda body, kind: f"{body.item.zotero_item_key}:{kind}"
            ),
            "zotero_attachment_target_refs": lambda body, target_source: [
                {"item": body.item.zotero_item_key, "source": target_source}
            ],
            "prepare_zotero_pdf_attachment_action": lambda body, matched, **kwargs: (
                calls.append(
                    {
                        "body": body,
                        "matched": matched,
                        "target_refs": kwargs["target_refs"],
                        "target_source": kwargs["target_source"],
                    }
                )
                or {"kind": "action_preview"}
            ),
        }
    )
    body = _body(requested_action_type="zotero_attach_pdf")

    result = maybe_prepare_zotero_chat_action(
        body,
        {"paper": {"id": 7}},
        **deps,
    )

    assert result == {"kind": "action_preview"}
    assert calls == [
        {
            "body": body,
            "matched": {"paper": {"id": 7}},
            "target_refs": [{"item": "ITEM1", "source": "ITEM1:paper"}],
            "target_source": "ITEM1:paper",
        }
    ]


def test_maybe_prepare_zotero_chat_action_formats_directory_capabilities():
    from research_harness_mcp.zotero_chat_actions import (
        maybe_prepare_zotero_chat_action,
    )

    result = maybe_prepare_zotero_chat_action(
        _body(requested_action_type="available_actions"),
        {"source": "directory"},
        **_noop_dependencies(),
    )

    assert result == {
        "kind": "assistant_message",
        "message": (
            "当前是 Zotero 目录/文库模式。我会把这里当作一个待初始化或待补全的 RH 入口，"
            "而不是套用单篇论文界面。\n\n"
            "可用能力：\n- 导入当前主题论文\n- 新建文件夹"
        ),
    }


def test_maybe_prepare_zotero_chat_action_delegates_collection_sync_and_unknown():
    from research_harness_mcp.zotero_chat_actions import (
        maybe_prepare_zotero_chat_action,
    )

    calls: list[dict[str, Any]] = []
    deps = _noop_dependencies()
    deps["prepare_zotero_create_collection_action"] = lambda body, matched: (
        calls.append({"branch": "collection", "body": body, "matched": matched})
        or {"kind": "action_preview", "preview": {"action_type": "collection"}}
    )
    deps["prepare_zotero_sync_papers_action"] = lambda body, matched, *, action_type: (
        calls.append(
            {
                "branch": "sync",
                "body": body,
                "matched": matched,
                "action_type": action_type,
            }
        )
        or {"kind": "action_preview", "preview": {"action_type": "sync"}}
    )

    collection_body = _body(requested_action_type="zotero_create_collection")
    sync_body = _body(requested_action_type="sync_rh_papers_to_collection")
    unknown_body = _body(requested_action_type="not_supported")

    assert maybe_prepare_zotero_chat_action(collection_body, {}, **deps) == {
        "kind": "action_preview",
        "preview": {"action_type": "collection"},
    }
    assert maybe_prepare_zotero_chat_action(
        sync_body, {"topic": {"id": 3}}, **deps
    ) == {
        "kind": "action_preview",
        "preview": {"action_type": "sync"},
    }
    assert maybe_prepare_zotero_chat_action(unknown_body, {}, **deps) is None
    assert calls == [
        {"branch": "collection", "body": collection_body, "matched": {}},
        {
            "branch": "sync",
            "body": sync_body,
            "matched": {"topic": {"id": 3}},
            "action_type": "sync_rh_papers_to_collection",
        },
    ]
