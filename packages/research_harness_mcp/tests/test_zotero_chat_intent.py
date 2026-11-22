"""Focused tests for Zotero chat intent helper extraction."""

from __future__ import annotations


def test_zotero_chat_intent_module_imports_and_http_api_preserves_aliases():
    from research_harness_mcp import http_api, zotero_chat_intent

    assert (
        http_api._looks_like_zotero_create_collection_request
        is zotero_chat_intent.looks_like_zotero_create_collection_request
    )
    assert (
        http_api._extract_zotero_create_collection_name
        is zotero_chat_intent.extract_zotero_create_collection_name
    )
    assert (
        http_api._clean_zotero_collection_name
        is zotero_chat_intent.clean_zotero_collection_name
    )
    assert (
        http_api._looks_like_unsupported_zotero_write_request
        is zotero_chat_intent.looks_like_unsupported_zotero_write_request
    )
    assert (
        http_api._looks_like_zotero_pdf_attachment_request
        is zotero_chat_intent.looks_like_zotero_pdf_attachment_request
    )
    assert (
        http_api._looks_like_zotero_import_request
        is zotero_chat_intent.looks_like_zotero_import_request
    )
    assert (
        http_api._looks_like_zotero_metadata_edit_request
        is zotero_chat_intent.looks_like_zotero_metadata_edit_request
    )


def test_create_collection_intent_preserves_name_extraction_and_cleanup():
    from research_harness_mcp import zotero_chat_intent

    assert zotero_chat_intent.looks_like_zotero_create_collection_request(
        "新建文件夹 RH E2E Write Test 20260606-1354，先预览"
    )
    assert not zotero_chat_intent.looks_like_zotero_create_collection_request(
        "新建会话继续聊这篇论文"
    )
    assert (
        zotero_chat_intent.extract_zotero_create_collection_name(
            "新建文件夹 RH E2E Write Test 20260606-1354，先预览"
        )
        == "RH E2E Write Test 20260606-1354"
    )
    assert (
        zotero_chat_intent.extract_zotero_create_collection_name(
            "create a Zotero collection Graph RAG dry-run"
        )
        == "Graph RAG"
    )
    assert zotero_chat_intent.clean_zotero_collection_name(" 文件夹 ") == ""


def test_import_intent_preserves_metadata_edit_and_generic_sync_rejections():
    from research_harness_mcp import zotero_chat_intent

    assert not zotero_chat_intent.looks_like_zotero_import_request(
        "同步这篇论文和 RH 的关系"
    )
    assert not zotero_chat_intent.looks_like_zotero_import_request(
        "请问这篇论文如何同步到 RH？"
    )
    assert not zotero_chat_intent.looks_like_zotero_import_request(
        "请帮我给 Zotero 添加标签"
    )
    assert not zotero_chat_intent.looks_like_zotero_import_request(
        "给这篇论文添加 Zotero 标签"
    )
    assert zotero_chat_intent.looks_like_zotero_import_request("把这篇论文导入当前目录")
    assert zotero_chat_intent.looks_like_zotero_import_request("同步到当前目录")


def test_unsupported_write_intent_preserves_pdf_and_import_boundaries():
    from research_harness_mcp import zotero_chat_intent

    assert zotero_chat_intent.looks_like_zotero_pdf_attachment_request(
        "对当前条目 SG97W99P 同步，下载并附加 PDF"
    )
    assert zotero_chat_intent.looks_like_unsupported_zotero_write_request(
        "对当前条目 SG97W99P 同步，下载并附加 PDF"
    )
    assert zotero_chat_intent.looks_like_unsupported_zotero_write_request(
        "给这篇论文添加 Zotero 标签"
    )
    assert not zotero_chat_intent.looks_like_unsupported_zotero_write_request(
        "这篇论文为什么值得读？"
    )
    assert not zotero_chat_intent.looks_like_unsupported_zotero_write_request(
        "把这篇论文导入当前目录"
    )
