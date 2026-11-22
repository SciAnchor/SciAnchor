"""Focused HTTP tests for Zotero translate stream route extraction."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class _ZoteroTranslateRequest(BaseModel):
    text: str = Field(min_length=1)
    model: str = "gpt-5.4-mini"
    target_locale: str = "zh-CN"
    source_locale: str = ""


class _TranslateEvent:
    def __init__(self, event: str, data: dict[str, Any]):
        self.event = event
        self.data = data


def _encode_sse(event: str, payload: dict[str, Any]) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def test_zotero_translate_module_imports_and_routes_registered():
    from research_harness_mcp import http_api, zotero_translate_http

    assert callable(zotero_translate_http.register_zotero_translate_routes)

    def route_index(path: str, method: str) -> int:
        for index, route in enumerate(http_api.app.routes):
            if route.path == path and method in route.methods:
                return index
        raise AssertionError(f"route not registered: {method} {path}")

    assert (
        route_index("/api/zotero/warmup", "POST")
        < route_index("/api/zotero/translate/stream", "POST")
        < route_index("/api/zotero/chat/stream", "POST")
    )


def _build_zotero_translate_client(
    *,
    token_required: bool = False,
    stream_events: list[_TranslateEvent] | None = None,
) -> tuple[TestClient, list[dict[str, Any]], list[str]]:
    from research_harness_mcp import zotero_translate_http

    stream_calls: list[dict[str, Any]] = []
    token_calls: list[str] = []

    def require_token(request: Request) -> None:
        token_calls.append(request.url.path)
        if token_required and request.headers.get("X-RH-Zotero-Token") != "secret":
            raise HTTPException(status_code=401, detail="Unauthorized")

    def stream_translate(**kwargs):
        stream_calls.append(kwargs)
        yield from (
            stream_events
            or [
                _TranslateEvent("started", {"thread_id": "ephemeral"}),
                _TranslateEvent("status", {"message": "running"}),
                _TranslateEvent("delta", {"text": "你好"}),
                _TranslateEvent("delta", {"text": "，世界"}),
                _TranslateEvent("done", {}),
            ]
        )

    app = FastAPI()
    zotero_translate_http.register_zotero_translate_routes(
        app,
        zotero_translate_request_model=_ZoteroTranslateRequest,
        require_zotero_chat_token=require_token,
        stream_zotero_codex_translate=stream_translate,
        sse_encode=_encode_sse,
    )
    return TestClient(app), stream_calls, token_calls


def test_zotero_translate_stream_preserves_sse_shape_and_stream_call():
    client, stream_calls, token_calls = _build_zotero_translate_client()

    response = client.post(
        "/api/zotero/translate/stream",
        json={
            "text": "Hello, world",
            "model": "gpt-5.4-mini",
            "target_locale": "fr",
            "source_locale": "en",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"
    assert response.headers["x-accel-buffering"] == "no"
    assert token_calls == ["/api/zotero/translate/stream"]
    assert stream_calls == [
        {
            "text": "Hello, world",
            "model": "gpt-5.4-mini",
            "target_locale": "fr",
            "source_locale": "en",
        }
    ]
    assert (
        'event: ready\ndata: {"model":"gpt-5.4-mini","target_locale":"fr","source_chars":12}'
        in response.text
    )
    assert 'event: started\ndata: {"thread_id":"ephemeral"}' in response.text
    assert 'event: status\ndata: {"message":"running"}' in response.text
    assert 'event: delta\ndata: {"text":"你好"}' in response.text
    assert 'event: delta\ndata: {"text":"，世界"}' in response.text
    assert (
        'event: done\ndata: {"model":"gpt-5.4-mini","assistant_message":"你好，世界"}'
    ) in response.text


def test_zotero_translate_stream_preserves_error_event_shape():
    def failing_stream(**kwargs):
        del kwargs
        raise RuntimeError("translate failed")
        yield  # pragma: no cover

    _client, _stream_calls, _token_calls = _build_zotero_translate_client(
        stream_events=[]
    )
    from research_harness_mcp import zotero_translate_http

    app = FastAPI()
    zotero_translate_http.register_zotero_translate_routes(
        app,
        zotero_translate_request_model=_ZoteroTranslateRequest,
        require_zotero_chat_token=lambda _request: None,
        stream_zotero_codex_translate=failing_stream,
        sse_encode=_encode_sse,
    )

    response = TestClient(app).post(
        "/api/zotero/translate/stream",
        json={"text": "Hello"},
    )

    assert response.status_code == 200, response.text
    assert (
        'event: error\ndata: {"message":"translate failed","model":"gpt-5.4-mini"}'
        in response.text
    )


def test_zotero_translate_stream_preserves_token_gate():
    client, stream_calls, token_calls = _build_zotero_translate_client(
        token_required=True,
    )

    blocked = client.post(
        "/api/zotero/translate/stream",
        json={"text": "Hello"},
    )
    allowed = client.post(
        "/api/zotero/translate/stream",
        headers={"X-RH-Zotero-Token": "secret"},
        json={"text": "Hello"},
    )

    assert blocked.status_code == 401
    assert allowed.status_code == 200, allowed.text
    assert token_calls == [
        "/api/zotero/translate/stream",
        "/api/zotero/translate/stream",
    ]
    assert len(stream_calls) == 1
