from __future__ import annotations

import pytest
from fastapi import HTTPException


class _Request:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


def test_zotero_chat_auth_preserves_http_api_alias():
    from research_harness_mcp import http_api, zotero_chat_auth

    assert (
        http_api._require_zotero_chat_token
        is zotero_chat_auth.require_zotero_chat_token
    )


def test_zotero_chat_auth_is_inert_without_expected_token(
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import zotero_chat_auth

    monkeypatch.delenv("RESEARCH_HARNESS_ZOTERO_CHAT_TOKEN", raising=False)

    zotero_chat_auth.require_zotero_chat_token(_Request())


def test_zotero_chat_auth_accepts_configured_header_tokens(
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import zotero_chat_auth

    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_CHAT_TOKEN", "secret-token")

    zotero_chat_auth.require_zotero_chat_token(
        _Request({"X-RH-Zotero-Token": "secret-token"})
    )
    zotero_chat_auth.require_zotero_chat_token(
        _Request({"Authorization": "Bearer secret-token"})
    )


def test_zotero_chat_auth_rejects_missing_or_wrong_tokens(
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import zotero_chat_auth

    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_CHAT_TOKEN", "secret-token")

    with pytest.raises(HTTPException) as missing:
        zotero_chat_auth.require_zotero_chat_token(_Request())
    assert missing.value.status_code == 401
    assert missing.value.detail == "Zotero chat token required"

    with pytest.raises(HTTPException) as wrong:
        zotero_chat_auth.require_zotero_chat_token(
            _Request({"X-RH-Zotero-Token": "wrong"})
        )
    assert wrong.value.status_code == 401
    assert wrong.value.detail == "Zotero chat token required"
