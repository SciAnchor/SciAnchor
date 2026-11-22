"""Focused HTTP tests for Zotero chat stream route extraction."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class _ZoteroChatItemContext(BaseModel):
    title: str = ""
    screenshots: list[str] = Field(default_factory=list)


class _ZoteroChatRequest(BaseModel):
    message: str = Field(min_length=1)
    item: _ZoteroChatItemContext = Field(default_factory=_ZoteroChatItemContext)
    conversation_id: str = ""
    model: str = "gpt-5.4-mini"
    requested_action_type: str = ""


class _CodexEvent:
    def __init__(self, event: str, data: dict[str, Any]):
        self.event = event
        self.data = data


class _PreviewResult:
    def __init__(self, action_preview: dict[str, Any]):
        self.action_preview = action_preview
        self.status = "action_preview"
        self.message = ""
        self.capability = "rh.zotero.demo"


class _Store:
    def __init__(self, existing_thread_id: str | None = None):
        self.existing_thread_id = existing_thread_id

    def get_thread_id(self, conversation_id: str) -> str | None:
        assert conversation_id
        return self.existing_thread_id


def _encode_sse(event: str, payload: dict[str, Any]) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def test_zotero_chat_stream_module_imports_and_routes_registered():
    from research_harness_mcp import http_api, zotero_chat_stream_http

    assert callable(zotero_chat_stream_http.register_zotero_chat_stream_routes)
    assert http_api._sse_encode is zotero_chat_stream_http.sse_encode
    assert zotero_chat_stream_http.sse_encode("ready", {"ok": True}) == (
        'event: ready\ndata: {"ok":true}\n\n'
    )

    def route_index(path: str, method: str) -> int:
        for index, route in enumerate(http_api.app.routes):
            if route.path == path and method in route.methods:
                return index
        raise AssertionError(f"route not registered: {method} {path}")

    assert route_index("/api/zotero/translate/stream", "POST") < route_index(
        "/api/zotero/chat/stream", "POST"
    )


def _build_zotero_chat_stream_client(
    db_path: Path,
    *,
    token_required: bool = False,
    plan_kind: str = "chat",
    existing_thread_id: str | None = None,
) -> tuple[TestClient, dict[str, Any]]:
    from research_harness_mcp import zotero_chat_stream_http

    calls: dict[str, Any] = {
        "token_paths": [],
        "stream_calls": [],
        "saved_threads": [],
        "preview_calls": [],
    }

    @contextmanager
    def get_db_context():
        conn = sqlite3.connect(str(db_path))
        try:
            yield conn
        finally:
            conn.close()

    def require_token(request: Request) -> None:
        calls["token_paths"].append(request.url.path)
        if token_required and request.headers.get("X-RH-Zotero-Token") != "secret":
            raise HTTPException(status_code=401, detail="Unauthorized")

    def resolve_match(_conn: sqlite3.Connection, item: Any) -> dict[str, Any]:
        return {
            "paper": {"id": 7, "title": item.title or "Untitled"},
            "topic": {"id": 3, "name": "demo-topic"},
        }

    def stream_codex_turn(**kwargs):
        calls["stream_calls"].append(kwargs)
        yield _CodexEvent("started", {"thread_id": "thread-1", "turn_id": "turn-1"})
        yield _CodexEvent(
            "reasoning",
            {
                "kind": "summary",
                "delta": "checking",
                "summary_index": 0,
                "content_index": 1,
                "item_id": "reason-1",
            },
        )
        yield _CodexEvent(
            "tool_call",
            {
                "tool": "paper.list",
                "capability": "rh.paper.list",
                "arguments": {"limit": 1},
            },
        )
        yield _CodexEvent("delta", {"text": "第一段"})
        yield _CodexEvent("delta", {"text": "，第二段"})
        yield _CodexEvent("done", {"thread_id": "thread-1", "turn_id": "turn-1"})

    app = FastAPI()
    zotero_chat_stream_http.register_zotero_chat_stream_routes(
        app,
        zotero_chat_request_model=_ZoteroChatRequest,
        require_zotero_chat_token=require_token,
        get_db_context=get_db_context,
        resolve_zotero_chat_match=resolve_match,
        stable_zotero_chat_conversation_id=lambda _body, matched: (
            f"conv-{matched['paper']['id']}"
        ),
        zotero_codex_thread_store=lambda: _Store(existing_thread_id),
        build_zotero_codex_turn_prompt=lambda body, matched, is_followup: (
            f"prompt:{body.message}:{matched['paper']['id']}:{is_followup}"
        ),
        zotero_context_payload=lambda _body, matched: {
            "kind": "paper",
            "paper_id": matched["paper"]["id"],
        },
        zotero_available_actions=lambda context, _matched: [
            {"kind": "open", "context": context}
        ],
        zotero_chat_suggested_actions=lambda matched: [
            {"kind": "codex_handoff", "paper_id": matched["paper"]["id"]}
        ],
        plan_zotero_write_intent=lambda **_kwargs: {"kind": plan_kind},
        maybe_prepare_zotero_chat_action=lambda _body, _matched: None,
        preview_zotero_write_plan=lambda **kwargs: (
            calls["preview_calls"].append(kwargs)
            or _PreviewResult(
                {
                    "message": "preview ready",
                    "action_type": "demo_action",
                    "paper_id": kwargs["matched"]["paper"]["id"],
                }
            )
        ),
        stream_zotero_codex_turn=stream_codex_turn,
        save_zotero_codex_thread=lambda **kwargs: calls["saved_threads"].append(kwargs),
        maybe_prepare_zotero_codex_output_action=lambda **_kwargs: None,
        extract_zotero_import_count=lambda _message: None,
        sse_encode=_encode_sse,
    )
    return TestClient(app), calls


def test_zotero_chat_stream_preserves_codex_sse_shape_and_thread_save(
    tmp_path: Path,
):
    db_path = tmp_path / "chat-stream.db"
    db_path.touch()
    client, calls = _build_zotero_chat_stream_client(db_path)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "继续分析",
            "item": {
                "title": "Agentic Zotero",
                "screenshots": ["data:image/png;base64,abc"],
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"
    assert response.headers["x-accel-buffering"] == "no"
    assert calls["token_paths"] == ["/api/zotero/chat/stream"]
    assert calls["stream_calls"][0]["conversation_id"] == "conv-7"
    assert calls["stream_calls"][0]["existing_thread_id"] is None
    assert calls["stream_calls"][0]["image_urls"] == ["data:image/png;base64,abc"]
    assert calls["saved_threads"][0]["thread_id"] == "thread-1"
    assert 'event: ready\ndata: {"conversation_id":"conv-7"' in response.text
    assert 'event: status\ndata: {"conversation_id":"conv-7"' in response.text
    assert 'event: started\ndata: {"thread_id":"thread-1","turn_id":"turn-1"}' in (
        response.text
    )
    assert (
        'event: reasoning\ndata: {"kind":"summary","delta":"checking",'
        '"summary_index":0,"content_index":1,"item_id":"reason-1"}'
    ) in response.text
    assert 'event: tool_call\ndata: {"tool":"paper.list"' in response.text
    assert 'event: delta\ndata: {"text":"第一段"}' in response.text
    assert (
        'event: done\ndata: {"conversation_id":"conv-7","thread_id":"thread-1",'
        '"model":"gpt-5.4-mini","assistant_message":"第一段，第二段"'
    ) in response.text


def test_zotero_chat_stream_preserves_existing_thread_followup(tmp_path: Path):
    db_path = tmp_path / "chat-stream-followup.db"
    db_path.touch()
    client, calls = _build_zotero_chat_stream_client(
        db_path,
        existing_thread_id="thread-existing",
    )

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "conversation_id": "custom-conv",
            "message": "继续",
            "item": {"title": "Agentic Zotero"},
        },
    )

    assert response.status_code == 200, response.text
    stream_call = calls["stream_calls"][0]
    assert stream_call["conversation_id"] == "custom-conv"
    assert stream_call["existing_thread_id"] == "thread-existing"
    assert stream_call["prompt"] == "prompt:继续:7:True"


def test_zotero_chat_stream_action_preview_skips_codex(tmp_path: Path):
    db_path = tmp_path / "chat-stream-preview.db"
    db_path.touch()
    client, calls = _build_zotero_chat_stream_client(
        db_path,
        plan_kind="capability_preview",
    )

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "导入当前目录",
            "item": {"title": "Agentic Zotero"},
        },
    )

    assert response.status_code == 200, response.text
    assert calls["stream_calls"] == []
    assert len(calls["preview_calls"]) == 1
    assert 'event: action_preview\ndata: {"message":"preview ready"' in response.text
    assert '"action_preview":true' in response.text


def test_zotero_chat_stream_preserves_token_gate(tmp_path: Path):
    db_path = tmp_path / "chat-stream-token.db"
    db_path.touch()
    client, calls = _build_zotero_chat_stream_client(db_path, token_required=True)

    blocked = client.post(
        "/api/zotero/chat/stream",
        json={"message": "ping", "item": {"title": "Blocked"}},
    )
    allowed = client.post(
        "/api/zotero/chat/stream",
        headers={"X-RH-Zotero-Token": "secret"},
        json={"message": "ping", "item": {"title": "Allowed"}},
    )

    assert blocked.status_code == 401
    assert allowed.status_code == 200, allowed.text
    assert calls["token_paths"] == [
        "/api/zotero/chat/stream",
        "/api/zotero/chat/stream",
    ]
    assert len(calls["stream_calls"]) == 1
