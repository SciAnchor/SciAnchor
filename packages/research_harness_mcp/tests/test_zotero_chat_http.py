"""Focused HTTP tests for Zotero chat/match route extraction."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class _ZoteroChatItemContext(BaseModel):
    title: str = ""
    zotero_item_key: str = ""
    library_id: str | int | None = None


class _ZoteroChatRequest(BaseModel):
    message: str = Field(min_length=1)
    item: _ZoteroChatItemContext = Field(default_factory=_ZoteroChatItemContext)
    conversation_id: str = ""


def test_zotero_chat_module_imports_and_routes_registered():
    from research_harness_mcp import http_api, zotero_chat_http

    assert callable(zotero_chat_http.register_zotero_chat_routes)

    def route_index(path: str, method: str) -> int:
        for index, route in enumerate(http_api.app.routes):
            if route.path == path and method in route.methods:
                return index
        raise AssertionError(f"route not registered: {method} {path}")

    assert (
        route_index("/api/zotero/seed-papers/apply", "POST")
        < route_index("/api/zotero/chat", "POST")
        < route_index("/api/zotero/match", "POST")
        < route_index("/api/zotero/warmup", "POST")
    )


def _build_zotero_chat_client(
    db_path: Path,
    *,
    token_required: bool = False,
) -> tuple[TestClient, list[str]]:
    from research_harness_mcp import zotero_chat_http

    calls: list[str] = []

    @contextmanager
    def get_db_context():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def require_token(request: Request) -> None:
        calls.append(f"token:{request.url.path}")
        if token_required and request.headers.get("X-RH-Zotero-Token") != "secret":
            raise HTTPException(status_code=401, detail="Unauthorized")

    def resolve_match(_conn: sqlite3.Connection, item: Any) -> dict[str, Any]:
        calls.append(f"match:{item.title}")
        return {
            "paper": {"id": 7, "title": item.title or "Untitled"},
            "topic": {"id": 3, "name": "demo-topic"},
        }

    def context_payload(_body: Any, matched: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "paper", "paper_id": matched["paper"]["id"]}

    app = FastAPI()
    zotero_chat_http.register_zotero_chat_routes(
        app,
        zotero_chat_request_model=_ZoteroChatRequest,
        zotero_chat_item_context_model=_ZoteroChatItemContext,
        require_zotero_chat_token=require_token,
        get_db_context=get_db_context,
        resolve_zotero_chat_match=resolve_match,
        build_zotero_codex_handoff_prompt=lambda body, matched: (
            f"prompt:{body.message}:{matched['paper']['id']}"
        ),
        build_zotero_chat_assistant_message=lambda body, matched: (
            f"assistant:{body.message}:{matched['topic']['name']}"
        ),
        zotero_context_payload=context_payload,
        zotero_available_actions=lambda context, _matched: [
            {"kind": "open", "context": context}
        ],
        stable_zotero_chat_conversation_id=lambda _body, matched: (
            f"conv-{matched['paper']['id']}"
        ),
        zotero_chat_suggested_actions=lambda matched: [
            {"kind": "codex_handoff", "paper_id": matched["paper"]["id"]}
        ],
    )
    return TestClient(app), calls


def test_zotero_chat_preserves_success_response_shape(tmp_path: Path):
    db_path = tmp_path / "zotero-chat.db"
    db_path.touch()
    client, calls = _build_zotero_chat_client(db_path)

    response = client.post(
        "/api/zotero/chat",
        json={
            "message": "下一步怎么读？",
            "item": {"title": "Agentic Zotero"},
        },
    )

    assert response.status_code == 200, response.text
    assert calls == ["token:/api/zotero/chat", "match:Agentic Zotero"]
    assert response.json() == {
        "status": "success",
        "summary": "Zotero chat request prepared",
        "output": {
            "conversation_id": "conv-7",
            "matched": {
                "paper": {"id": 7, "title": "Agentic Zotero"},
                "topic": {"id": 3, "name": "demo-topic"},
            },
            "context": {"kind": "paper", "paper_id": 7},
            "available_actions": [
                {"kind": "open", "context": {"kind": "paper", "paper_id": 7}}
            ],
            "assistant_message": "assistant:下一步怎么读？:demo-topic",
            "codex_handoff": {
                "mode": "manual",
                "prompt": "prompt:下一步怎么读？:7",
                "hint": (
                    "复制该 prompt 到 Codex 终端，或后续接入 Codex "
                    "app-server/longtask 自动执行。"
                ),
            },
            "suggested_actions": [{"kind": "codex_handoff", "paper_id": 7}],
        },
    }


def test_zotero_chat_preserves_conversation_id_override(tmp_path: Path):
    db_path = tmp_path / "zotero-chat-conversation.db"
    db_path.touch()
    client, _calls = _build_zotero_chat_client(db_path)

    response = client.post(
        "/api/zotero/chat",
        json={
            "conversation_id": "custom-conv",
            "message": "继续",
            "item": {"title": "Agentic Zotero"},
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["output"]["conversation_id"] == "custom-conv"


def test_zotero_match_preserves_success_response_shape(tmp_path: Path):
    db_path = tmp_path / "zotero-match.db"
    db_path.touch()
    client, calls = _build_zotero_chat_client(db_path)

    response = client.post(
        "/api/zotero/match",
        json={"title": "Match Me", "zotero_item_key": "ITEM1"},
    )

    assert response.status_code == 200, response.text
    assert calls == ["token:/api/zotero/match", "match:Match Me"]
    assert response.json() == {
        "status": "success",
        "summary": "Zotero item match resolved",
        "output": {
            "matched": {
                "paper": {"id": 7, "title": "Match Me"},
                "topic": {"id": 3, "name": "demo-topic"},
            }
        },
    }


def test_zotero_chat_and_match_preserve_token_gate(tmp_path: Path):
    db_path = tmp_path / "zotero-chat-token.db"
    db_path.touch()
    client, calls = _build_zotero_chat_client(db_path, token_required=True)

    chat_blocked = client.post(
        "/api/zotero/chat",
        json={"message": "ping", "item": {"title": "Blocked"}},
    )
    match_blocked = client.post(
        "/api/zotero/match",
        json={"title": "Blocked"},
    )
    allowed = client.post(
        "/api/zotero/match",
        headers={"X-RH-Zotero-Token": "secret"},
        json={"title": "Allowed"},
    )

    assert chat_blocked.status_code == 401
    assert match_blocked.status_code == 401
    assert allowed.status_code == 200, allowed.text
    assert calls == [
        "token:/api/zotero/chat",
        "token:/api/zotero/match",
        "token:/api/zotero/match",
        "match:Allowed",
    ]
