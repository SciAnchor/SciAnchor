"""Focused tests for Zotero HTTP request model extraction."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_zotero_model_module_imports_and_http_api_preserves_aliases():
    from research_harness_mcp import http_api, zotero_models_http

    assert http_api.ZoteroSyncRequest is zotero_models_http.ZoteroSyncRequest
    assert http_api.ZoteroChatTargetRef is zotero_models_http.ZoteroChatTargetRef
    assert http_api.ZoteroChatItemContext is zotero_models_http.ZoteroChatItemContext
    assert http_api.ZoteroChatRequest is zotero_models_http.ZoteroChatRequest
    assert http_api.ZoteroWarmupRequest is zotero_models_http.ZoteroWarmupRequest
    assert http_api.ZoteroTranslateRequest is zotero_models_http.ZoteroTranslateRequest
    assert (
        http_api.ZoteroSeedPaperApplyRequest
        is zotero_models_http.ZoteroSeedPaperApplyRequest
    )
    assert (
        http_api._default_zotero_codex_model
        is zotero_models_http.default_zotero_codex_model
    )
    assert (
        http_api._validate_zotero_codex_model
        is zotero_models_http.validate_zotero_codex_model
    )


def test_zotero_sync_request_preserves_paper_id_dedupe():
    from research_harness_mcp import zotero_models_http

    body = zotero_models_http.ZoteroSyncRequest(
        paper_ids=[1, 1, 0, -3, 2],
    )

    assert body.paper_ids == [1, 2]


def test_zotero_chat_request_preserves_model_and_screenshot_validation(
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import zotero_models_http

    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_CODEX_MODEL", "gpt-5.4")

    body = zotero_models_http.ZoteroChatRequest(
        message="ping",
        item={
            "screenshots": [
                "data:image/png;base64,abc",
                "data:image/webp;base64,def",
            ],
            "tags": [" rh ", "", "topic"],
            "creators": [" Ada ", ""],
        },
    )

    assert body.model == "gpt-5.4"
    assert body.item.screenshots == [
        "data:image/png;base64,abc",
        "data:image/webp;base64,def",
    ]
    assert body.item.tags == ["rh", "topic"]
    assert body.item.creators == ["Ada"]

    with pytest.raises(ValidationError):
        zotero_models_http.ZoteroChatRequest(message="ping", model="not-a-model")

    with pytest.raises(ValidationError):
        zotero_models_http.ZoteroChatRequest(
            message="ping",
            item={"screenshots": ["https://example.com/image.png"]},
        )


def test_zotero_warmup_request_preserves_extra_model_cleanup():
    from research_harness_mcp import zotero_models_http

    body = zotero_models_http.ZoteroWarmupRequest(
        model="gpt-5.4-mini",
        extra_models=["not-a-model", "gpt-5.4", "gpt-5.4", ""],
    )

    assert body.extra_models == ["gpt-5.4"]


def test_zotero_seed_apply_request_preserves_candidate_source_cleanup():
    from research_harness_mcp import zotero_models_http

    body = zotero_models_http.ZoteroSeedPaperApplyRequest(
        query="seed",
        candidate_sources=[" 10.1234/demo ", "", "10.1234/demo", " arxiv-1 "],
        target_collection_key="COLL",
    )

    assert body.candidate_sources == ["10.1234/demo", "arxiv-1"]


def test_zotero_seed_apply_request_defaults_to_dry_run():
    from research_harness_mcp import zotero_models_http

    body = zotero_models_http.ZoteroSeedPaperApplyRequest(
        query="seed",
        candidate_sources=["10.1234/demo"],
        target_collection_key="COLL",
    )

    assert body.dry_run is True
