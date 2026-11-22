"""Authentication helpers for local Zotero chat HTTP endpoints."""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request


def require_zotero_chat_token(request: Request) -> None:
    expected = os.environ.get("RESEARCH_HARNESS_ZOTERO_CHAT_TOKEN", "").strip()
    if not expected:
        return
    provided = request.headers.get("X-RH-Zotero-Token", "").strip()
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        provided = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Zotero chat token required")
