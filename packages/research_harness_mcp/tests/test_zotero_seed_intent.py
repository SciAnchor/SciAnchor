"""Focused tests for Zotero seed/search intent helper extraction."""

from __future__ import annotations

from types import SimpleNamespace


def test_zotero_seed_intent_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_chat_intent

    assert (
        http_api._last_zotero_path_segment
        is zotero_chat_intent.last_zotero_path_segment
    )
    assert http_api._zotero_names_equal is zotero_chat_intent.zotero_names_equal
    assert (
        http_api._looks_like_zotero_seed_search_request
        is zotero_chat_intent.looks_like_zotero_seed_search_request
    )
    assert (
        http_api._zotero_seed_request_flags
        is zotero_chat_intent.zotero_seed_request_flags
    )
    assert (
        http_api._zotero_explicit_seed_topic_name
        is zotero_chat_intent.zotero_explicit_seed_topic_name
    )
    assert (
        http_api._zotero_seed_search_query
        is zotero_chat_intent.zotero_seed_search_query
    )
    assert (
        http_api._is_zotero_seed_placeholder_phrase
        is zotero_chat_intent.is_zotero_seed_placeholder_phrase
    )
    assert (
        http_api._extract_explicit_topic_id
        is zotero_chat_intent.extract_explicit_topic_id
    )
    assert (
        http_api._message_targets_current_paper_only
        is zotero_chat_intent.message_targets_current_paper_only
    )
    assert (
        http_api._message_targets_deep_read_only
        is zotero_chat_intent.message_targets_deep_read_only
    )
    assert (
        http_api._extract_zotero_import_count
        is zotero_chat_intent.extract_zotero_import_count
    )
    assert http_api._simple_chinese_number is zotero_chat_intent.simple_chinese_number
    assert (
        http_api._looks_like_zotero_directory_capability_question
        is zotero_chat_intent.looks_like_zotero_directory_capability_question
    )


def test_seed_path_and_name_helpers_preserve_normalization():
    from research_harness_mcp import zotero_chat_intent

    assert (
        zotero_chat_intent.last_zotero_path_segment(
            "Research Harness / AI > Graph › RAG"
        )
        == "RAG"
    )
    assert (
        zotero_chat_intent.last_zotero_path_segment("  Single Folder  ")
        == "Single Folder"
    )
    assert zotero_chat_intent.last_zotero_path_segment("") == ""
    assert zotero_chat_intent.zotero_names_equal(" Graph   RAG ", "graph rag")
    assert not zotero_chat_intent.zotero_names_equal("Graph-RAG", "graph rag")


def test_seed_search_classifier_and_request_flags_are_preserved():
    from research_harness_mcp import zotero_chat_intent

    assert zotero_chat_intent.looks_like_zotero_seed_search_request(
        "帮我找到最开始的几篇文章"
    )
    assert zotero_chat_intent.looks_like_zotero_seed_search_request(
        "这个空目录先推荐 5 篇 seed papers"
    )
    assert zotero_chat_intent.looks_like_zotero_seed_search_request(
        "我想做一个新的研究方向 topic phrase，推荐第一批论文，pdf和笔记同步到zotero端"
    )
    assert not zotero_chat_intent.looks_like_zotero_seed_search_request(
        "把这个主题里精读过的 3 篇论文导入当前目录"
    )

    flags = zotero_chat_intent.zotero_seed_request_flags(
        "推荐第一批论文，并给 PDF 做高亮批注和精读"
    )
    assert flags == {
        "request_deep_read": True,
        "request_pdf_attachment": True,
        "request_pdf_annotations": True,
    }


def test_seed_topic_query_helpers_preserve_explicit_and_fallback_order():
    from research_harness_mcp import zotero_chat_intent

    assert (
        zotero_chat_intent.zotero_explicit_seed_topic_name(
            "新的研究方向 Agent Memory，推荐第一批论文"
        )
        == "Agent Memory"
    )
    assert (
        zotero_chat_intent.zotero_explicit_seed_topic_name(
            "新的研究方向 当前目录，推荐第一批论文"
        )
        == ""
    )
    assert zotero_chat_intent.is_zotero_seed_placeholder_phrase("推荐 5 篇论文")
    assert not zotero_chat_intent.is_zotero_seed_placeholder_phrase("Agent Memory")

    body = SimpleNamespace(
        message="围绕 多智能体检索 找第一批论文",
        item=SimpleNamespace(
            current_directory_path="Research Harness / Folder Topic",
            current_directory_name="Directory Topic",
            title="Item Topic",
        ),
    )
    assert zotero_chat_intent.zotero_seed_search_query(body) == "多智能体检索"
    assert (
        zotero_chat_intent.zotero_seed_search_query(body, topic_name="Explicit Topic")
        == "多智能体检索"
    )

    fallback_body = SimpleNamespace(
        message="推荐第一批论文",
        item=SimpleNamespace(
            current_directory_path="Research Harness / Folder Topic",
            current_directory_name="Directory Topic",
            title="Item Topic",
        ),
    )
    assert (
        zotero_chat_intent.zotero_seed_search_query(
            fallback_body, topic_name="Explicit Topic"
        )
        == "Explicit Topic"
    )
    assert zotero_chat_intent.zotero_seed_search_query(fallback_body) == "Folder Topic"


def test_topic_target_and_import_count_helpers_are_preserved():
    from research_harness_mcp import zotero_chat_intent

    assert zotero_chat_intent.extract_explicit_topic_id("topic_id: 42") == 42
    assert zotero_chat_intent.extract_explicit_topic_id("主题 9") == 9
    assert zotero_chat_intent.extract_explicit_topic_id("没有主题") is None
    assert zotero_chat_intent.message_targets_current_paper_only("请精读这篇论文")
    assert not zotero_chat_intent.message_targets_current_paper_only("请处理这个目录")
    assert zotero_chat_intent.message_targets_deep_read_only("deep-read only")
    assert zotero_chat_intent.message_targets_deep_read_only("只做精读")

    assert (
        zotero_chat_intent.extract_zotero_import_count("导入003篇论文到当前目录") == 3
    )
    assert (
        zotero_chat_intent.extract_zotero_import_count("导入十二篇论文到当前目录") == 12
    )
    assert (
        zotero_chat_intent.extract_zotero_import_count("导入二十篇论文到当前目录") == 20
    )
    assert (
        zotero_chat_intent.extract_zotero_import_count("导入二十三篇论文到当前目录")
        == 23
    )
    assert zotero_chat_intent.extract_zotero_import_count("导入论文到当前目录") is None
    assert zotero_chat_intent.simple_chinese_number("十") == 10
    assert zotero_chat_intent.simple_chinese_number("十一") == 11
    assert zotero_chat_intent.simple_chinese_number("三十") == 30
    assert zotero_chat_intent.simple_chinese_number("一百") is None


def test_directory_capability_question_classifier_preserves_context_rules():
    from research_harness_mcp import zotero_chat_intent
    from research_harness_mcp.zotero_models_http import ZoteroChatRequest

    collection_body = ZoteroChatRequest.model_validate(
        {
            "message": "这个目录可以怎么推进？",
            "item": {
                "current_directory_key": "COLL1",
                "current_directory_name": "Agent Reading",
            },
        }
    )
    assert zotero_chat_intent.looks_like_zotero_directory_capability_question(
        collection_body,
        {"paper": None, "topic": None},
    )

    library_body = ZoteroChatRequest.model_validate({"message": "文库可以做什么"})
    assert zotero_chat_intent.looks_like_zotero_directory_capability_question(
        library_body,
        {"paper": None, "topic": None},
    )

    paper_body = ZoteroChatRequest.model_validate(
        {
            "message": "这个目录可以怎么推进？",
            "item": {"title": "Matched Paper"},
        }
    )
    assert not zotero_chat_intent.looks_like_zotero_directory_capability_question(
        paper_body,
        {"paper": {"id": 7, "title": "Matched Paper"}, "topic": None},
    )

    unrelated_collection_body = ZoteroChatRequest.model_validate(
        {
            "message": "这里有哪些论文？",
            "item": {
                "current_directory_key": "COLL1",
                "current_directory_name": "Agent Reading",
            },
        }
    )
    assert not zotero_chat_intent.looks_like_zotero_directory_capability_question(
        unrelated_collection_body,
        {"paper": None, "topic": None},
    )
