"""Focused tests for Zotero identity/text helper extraction."""

from __future__ import annotations


def test_zotero_identity_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_identity

    assert (
        http_api._normalize_zotero_chat_tags
        is zotero_identity.normalize_zotero_chat_tags
    )
    assert http_api._extract_rh_paper_id_tag is zotero_identity.extract_rh_paper_id_tag
    assert http_api._extract_rh_topic_tag is zotero_identity.extract_rh_topic_tag
    assert (
        http_api._normalize_zotero_library_id
        is zotero_identity.normalize_zotero_library_id
    )
    assert http_api._normalize_doi is zotero_identity.normalize_doi
    assert http_api._normalize_arxiv_id is zotero_identity.normalize_arxiv_id
    assert (
        http_api._normalize_title_for_match is zotero_identity.normalize_title_for_match
    )
    assert http_api._truncate_text is zotero_identity.truncate_text


def test_zotero_tag_helpers_trim_filter_and_extract_rh_tags():
    from research_harness_mcp import zotero_identity

    tags = zotero_identity.normalize_zotero_chat_tags(
        ["  rh-paper-id:42  ", "", " rh-topic: Agent Memory ", "other"]
    )

    assert tags == ["rh-paper-id:42", "rh-topic: Agent Memory", "other"]
    assert zotero_identity.extract_rh_paper_id_tag(tags) == 42
    assert zotero_identity.extract_rh_topic_tag(tags) == "Agent Memory"
    assert zotero_identity.extract_rh_paper_id_tag(["rh-paper-id:nope"]) is None
    assert zotero_identity.extract_rh_topic_tag(["rh-topic:   "]) == ""


def test_zotero_library_and_identifier_normalizers_preserve_existing_rules():
    from research_harness_mcp import zotero_identity

    assert zotero_identity.normalize_zotero_library_id(None) == ""
    assert zotero_identity.normalize_zotero_library_id(1) == "1"
    assert zotero_identity.normalize_zotero_library_id("  local  ") == "local"
    assert (
        zotero_identity.normalize_doi("https://doi.org/10.1145/123 ") == "10.1145/123"
    )
    assert (
        zotero_identity.normalize_doi("doi:10.48550/arXiv.1234")
        == "10.48550/arXiv.1234"
    )
    assert (
        zotero_identity.normalize_arxiv_id("https://arxiv.org/abs/2401.01234v2")
        == "2401.01234v2"
    )
    assert zotero_identity.normalize_arxiv_id("arXiv:cs/9901001") == "cs/9901001"


def test_zotero_title_and_text_helpers_preserve_whitespace_and_truncation():
    from research_harness_mcp import zotero_identity

    assert (
        zotero_identity.normalize_title_for_match("  A\n  Graph   RAG Paper  ")
        == "A Graph RAG Paper"
    )
    assert zotero_identity.truncate_text("  short text  ", 20) == "short text"
    assert zotero_identity.truncate_text("abcdef", 3) == "abc…"
