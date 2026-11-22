"""Focused tests for Zotero Codex output-action fallback extraction."""

from __future__ import annotations

from typing import Any

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


def _body(message: str = "请给当前目录推荐 8 篇起步文献") -> ZoteroChatRequest:
    return ZoteroChatRequest.model_validate(
        {
            "message": message,
            "item": {
                "current_directory_key": "COLL1",
                "current_directory_name": "Agent Seeds",
                "current_directory_path": "Root / Agent Seeds",
            },
        }
    )


def test_zotero_codex_output_module_imports_and_http_wrapper_exists():
    from research_harness_mcp import http_api, zotero_codex_output

    assert callable(zotero_codex_output.maybe_prepare_zotero_codex_output_action)
    assert callable(http_api._maybe_prepare_zotero_codex_output_action)


def test_codex_output_action_only_builds_seed_preview_for_collection_decision():
    from research_harness_mcp.zotero_codex_output import (
        maybe_prepare_zotero_codex_output_action,
    )

    calls: list[dict[str, Any]] = []
    body = _body()
    matched = {"topic": {"id": 7}}

    def preview_seed_import(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"kind": "action_preview", "preview": {"planned_count": 8}}

    result = maybe_prepare_zotero_codex_output_action(
        body=body,
        matched=matched,
        assistant_text=(
            "我已经识别出这里需要 seed import 候选预览（action_preview），"
            "确认后导入当前 Zotero 文件夹。"
        ),
        context_payload={"kind": "collection"},
        zotero_capability_mode=lambda payload: str(payload["kind"]),
        codex_output_requests_seed_import_preview=lambda text: "action_preview" in text,
        extract_zotero_import_count=lambda text: 8 if "8" in text else None,
        zotero_preview_seed_import=preview_seed_import,
    )

    assert result == {"kind": "action_preview", "preview": {"planned_count": 8}}
    assert calls == [{"body": body, "matched": matched, "args": {"count": 8}}]


def test_codex_output_action_rejects_non_collection_or_non_preview_output():
    from research_harness_mcp.zotero_codex_output import (
        maybe_prepare_zotero_codex_output_action,
    )

    calls: list[dict[str, Any]] = []

    def preview_seed_import(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"kind": "action_preview"}

    common_kwargs = {
        "body": _body("请找起步文献"),
        "matched": {},
        "zotero_capability_mode": lambda payload: str(payload["kind"]),
        "codex_output_requests_seed_import_preview": lambda text: (
            "action_preview" in text
        ),
        "extract_zotero_import_count": lambda _text: None,
        "zotero_preview_seed_import": preview_seed_import,
    }

    assert (
        maybe_prepare_zotero_codex_output_action(
            **common_kwargs,
            assistant_text="action_preview: 找种子论文，确认后导入",
            context_payload={"kind": "paper"},
        )
        is None
    )
    assert (
        maybe_prepare_zotero_codex_output_action(
            **common_kwargs,
            assistant_text="我可以先列出候选论文，但这里没有确认卡。",
            context_payload={"kind": "collection"},
        )
        is None
    )
    assert calls == []
