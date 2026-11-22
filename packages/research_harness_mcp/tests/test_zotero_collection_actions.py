"""Focused tests for Zotero collection action helper extraction."""

from __future__ import annotations

from typing import Any

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


def _body(message: str = "新建文件夹“Reading Queue”") -> ZoteroChatRequest:
    return ZoteroChatRequest.model_validate(
        {
            "message": message,
            "item": {
                "current_directory_key": "PARENT1",
                "current_directory_name": "Root",
                "current_directory_path": "Library / Root",
                "library_id": "1",
                "library_type": "user",
            },
        }
    )


def test_zotero_collection_actions_module_imports_and_http_wrapper_exists():
    from research_harness_mcp import http_api, zotero_collection_actions

    assert callable(zotero_collection_actions.prepare_zotero_create_collection_action)
    assert callable(http_api._prepare_zotero_create_collection_action)


def test_prepare_zotero_create_collection_action_ignores_non_create_messages():
    from research_harness_mcp.zotero_collection_actions import (
        prepare_zotero_create_collection_action,
    )

    result = prepare_zotero_create_collection_action(
        _body("请总结当前目录"),
        {},
        looks_like_zotero_create_collection_request=lambda _message: False,
        zotero_context_payload=lambda _body, _matched: {"kind": "collection"},
        extract_zotero_create_collection_name=lambda _message: "unused",
        normalize_zotero_library_id=lambda value: str(value or ""),
        finalize_zotero_action_preview=lambda payload, **_kwargs: payload,
    )

    assert result is None


def test_prepare_zotero_create_collection_action_requires_library_or_collection():
    from research_harness_mcp.zotero_collection_actions import (
        prepare_zotero_create_collection_action,
    )

    result = prepare_zotero_create_collection_action(
        _body(),
        {},
        looks_like_zotero_create_collection_request=lambda _message: True,
        zotero_context_payload=lambda _body, _matched: {"kind": "paper"},
        extract_zotero_create_collection_name=lambda _message: "Reading Queue",
        normalize_zotero_library_id=lambda value: str(value or ""),
        finalize_zotero_action_preview=lambda payload, **_kwargs: payload,
    )

    assert result == {
        "kind": "assistant_message",
        "message": "要新建 Zotero 文件夹，请先在左侧选中父目录或文库位置。",
    }


def test_prepare_zotero_create_collection_action_requires_name():
    from research_harness_mcp.zotero_collection_actions import (
        prepare_zotero_create_collection_action,
    )

    result = prepare_zotero_create_collection_action(
        _body("新建文件夹"),
        {},
        looks_like_zotero_create_collection_request=lambda _message: True,
        zotero_context_payload=lambda _body, _matched: {"kind": "collection"},
        extract_zotero_create_collection_name=lambda _message: "",
        normalize_zotero_library_id=lambda value: str(value or ""),
        finalize_zotero_action_preview=lambda payload, **_kwargs: payload,
    )

    assert result == {
        "kind": "assistant_message",
        "message": "我可以新建 Zotero 文件夹，但需要你明确文件夹名称，例如：新建文件夹“AI discovery”。",
    }


def test_prepare_zotero_create_collection_action_builds_preview_payload():
    from research_harness_mcp.zotero_collection_actions import (
        prepare_zotero_create_collection_action,
    )

    finalize_calls: list[dict[str, Any]] = []

    def finalize(payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        finalize_calls.append({"payload": payload, "kwargs": kwargs})
        return {**payload, "finalized": kwargs}

    result = prepare_zotero_create_collection_action(
        _body(),
        {"source": "directory"},
        looks_like_zotero_create_collection_request=lambda _message: True,
        zotero_context_payload=lambda _body, matched: {
            "kind": "collection",
            "source": matched["source"],
        },
        extract_zotero_create_collection_name=lambda _message: "Reading Queue",
        normalize_zotero_library_id=lambda value: f"local-{value}",
        finalize_zotero_action_preview=finalize,
    )

    assert result is not None
    assert result["kind"] == "action_preview"
    preview = result["preview"]
    assert preview["action_type"] == "zotero_create_collection"
    assert preview["collection_name"] == "Reading Queue"
    assert preview["target_label"] == "Library / Root / Reading Queue"
    assert preview["parent_collection_key"] == "PARENT1"
    assert preview["library_id"] == "local-1"
    assert preview["library_type"] == "user"
    assert preview["apply"]["payload"] == {
        "collection_name": "Reading Queue",
        "name": "Reading Queue",
        "parent_collection_key": "PARENT1",
        "library_id": "local-1",
        "library_type": "user",
    }
    assert finalize_calls[0]["kwargs"] == {
        "capability": "rh.zotero.create_collection",
        "target_source": "current_collection",
        "target_record_count": 1,
        "writable_count": 1,
        "undo_supported": True,
    }
