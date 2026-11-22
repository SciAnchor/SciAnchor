"""Focused tests for Zotero Codex dynamic-tool pure helpers."""

from __future__ import annotations


def test_zotero_codex_tooling_imports_and_http_private_aliases():
    from research_harness_mcp import http_api, zotero_codex_tooling

    assert (
        http_api._zotero_capability_mode is zotero_codex_tooling.zotero_capability_mode
    )
    assert (
        http_api._normalize_zotero_codex_tool_name
        is zotero_codex_tooling.normalize_zotero_codex_tool_name
    )
    assert (
        http_api._coerce_codex_tool_arguments
        is zotero_codex_tooling.coerce_codex_tool_arguments
    )
    assert (
        http_api._coerce_zotero_capability_count
        is zotero_codex_tooling.coerce_zotero_capability_count
    )
    assert (
        http_api._codex_output_requests_seed_import_preview
        is zotero_codex_tooling.codex_output_requests_seed_import_preview
    )


def test_zotero_capability_mode_preserves_context_kind_rules():
    from research_harness_mcp import zotero_codex_tooling

    assert zotero_codex_tooling.zotero_capability_mode({"kind": "paper"}) == "item"
    assert (
        zotero_codex_tooling.zotero_capability_mode({"kind": "collection"})
        == "collection"
    )
    assert zotero_codex_tooling.zotero_capability_mode({"kind": "library"}) == "library"
    assert (
        zotero_codex_tooling.zotero_capability_mode({"selected_text": "excerpt"})
        == "reader_selection"
    )
    assert zotero_codex_tooling.zotero_capability_mode({}) == "library"


def test_normalize_zotero_codex_tool_name_preserves_aliases_and_namespace():
    from research_harness_mcp import zotero_codex_tooling

    assert (
        zotero_codex_tooling.normalize_zotero_codex_tool_name("paper.list")
        == "rh.paper.list"
    )
    assert (
        zotero_codex_tooling.normalize_zotero_codex_tool_name(
            "prepare_seed_import",
            namespace="zotero",
        )
        == "rh.zotero.prepare_seed_import"
    )
    assert (
        zotero_codex_tooling.normalize_zotero_codex_tool_name("rh.paper.search")
        == "rh.paper.search"
    )
    assert zotero_codex_tooling.normalize_zotero_codex_tool_name(None) == ""


def test_coerce_codex_tool_arguments_preserves_json_behavior():
    from research_harness_mcp import zotero_codex_tooling

    original = {"limit": 3}
    coerced = zotero_codex_tooling.coerce_codex_tool_arguments(original)
    assert coerced == {"limit": 3}
    assert coerced is not original
    assert zotero_codex_tooling.coerce_codex_tool_arguments('{"limit": 2}') == {
        "limit": 2
    }
    assert zotero_codex_tooling.coerce_codex_tool_arguments("[1, 2]") == {
        "value": [1, 2]
    }
    assert zotero_codex_tooling.coerce_codex_tool_arguments("plain text") == {
        "text": "plain text"
    }
    assert zotero_codex_tooling.coerce_codex_tool_arguments(None) == {}


def test_coerce_zotero_capability_count_preserves_default_and_clamp():
    from research_harness_mcp import zotero_codex_tooling

    assert zotero_codex_tooling.coerce_zotero_capability_count(None, default=5) == 5
    assert zotero_codex_tooling.coerce_zotero_capability_count("0", default=5) == 1
    assert zotero_codex_tooling.coerce_zotero_capability_count("3", default=5) == 3
    assert zotero_codex_tooling.coerce_zotero_capability_count("99", default=5) == 12
    assert zotero_codex_tooling.coerce_zotero_capability_count("bad", default=4) == 4


def test_codex_output_requests_seed_import_preview_requires_preview_seed_and_write():
    from research_harness_mcp import zotero_codex_tooling

    assert zotero_codex_tooling.codex_output_requests_seed_import_preview(
        "action_preview: 找种子论文，确认后导入"
    )
    assert zotero_codex_tooling.codex_output_requests_seed_import_preview(
        "确认卡：候选论文准备好了，确认后写入"
    )
    assert zotero_codex_tooling.codex_output_requests_seed_import_preview(
        "action_preview seed import 确认后同步"
    )

    assert not zotero_codex_tooling.codex_output_requests_seed_import_preview(
        "找种子论文并导入"
    )
    assert not zotero_codex_tooling.codex_output_requests_seed_import_preview(
        "action_preview: 可以导入"
    )
    assert not zotero_codex_tooling.codex_output_requests_seed_import_preview("")
