"""Focused HTTP tests for Zotero warmup route extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class _ZoteroWarmupRequest(BaseModel):
    model: str = "gpt-5.4-mini"
    extra_models: list[str] = Field(default_factory=list)


def test_zotero_warmup_module_imports_and_routes_registered():
    from research_harness_mcp import http_api, zotero_warmup_http

    assert callable(zotero_warmup_http.register_zotero_warmup_routes)

    def route_index(path: str, method: str) -> int:
        for index, route in enumerate(http_api.app.routes):
            if route.path == path and method in route.methods:
                return index
        raise AssertionError(f"route not registered: {method} {path}")

    assert (
        route_index("/api/zotero/chat", "POST")
        < route_index("/api/zotero/match", "POST")
        < route_index("/api/zotero/warmup", "POST")
        < route_index("/api/zotero/translate/stream", "POST")
    )


def _build_zotero_warmup_client(
    *,
    token_required: bool = False,
    effort: str = "medium",
    translate_effort: str = "low",
    service_tier: str | None = "auto",
) -> tuple[TestClient, list[dict[str, Any]], list[str]]:
    from research_harness_mcp import zotero_warmup_http

    warm_calls: list[dict[str, Any]] = []
    token_calls: list[str] = []

    def require_token(request: Request) -> None:
        token_calls.append(request.url.path)
        if token_required and request.headers.get("X-RH-Zotero-Token") != "secret":
            raise HTTPException(status_code=401, detail="Unauthorized")

    app = FastAPI()
    zotero_warmup_http.register_zotero_warmup_routes(
        app,
        zotero_warmup_request_model=_ZoteroWarmupRequest,
        require_zotero_chat_token=require_token,
        zotero_codex_cwd=lambda: Path("/tmp/rh-zotero-warmup"),
        zotero_codex_effort=lambda: effort,
        zotero_codex_translate_effort=lambda: translate_effort,
        zotero_codex_service_tier=lambda: service_tier,
        warm_zotero_codex_pool=lambda **kwargs: warm_calls.append(kwargs),
    )
    return TestClient(app), warm_calls, token_calls


def test_zotero_warmup_preserves_primary_and_extra_tasks():
    client, warm_calls, token_calls = _build_zotero_warmup_client()

    response = client.post(
        "/api/zotero/warmup",
        json={
            "model": "gpt-5.3-codex-spark",
            "extra_models": ["gpt-5.4-mini"],
        },
    )

    assert response.status_code == 202, response.text
    assert token_calls == ["/api/zotero/warmup"]
    assert response.json() == {
        "status": "warming",
        "model": "gpt-5.3-codex-spark",
        "extra_models": ["gpt-5.4-mini"],
        "cwd": "/tmp/rh-zotero-warmup",
        "effort": "medium",
        "translate_effort": "low",
        "service_tier": "auto",
    }
    assert warm_calls == [
        {
            "cwd": Path("/tmp/rh-zotero-warmup"),
            "model": "gpt-5.3-codex-spark",
            "effort": "medium",
            "service_tier": "auto",
        },
        {
            "cwd": Path("/tmp/rh-zotero-warmup"),
            "model": "gpt-5.4-mini",
            "effort": "low",
            "service_tier": "auto",
        },
    ]


def test_zotero_warmup_skips_duplicate_extra_when_effort_matches():
    client, warm_calls, _token_calls = _build_zotero_warmup_client(
        effort="low",
        translate_effort="low",
    )

    response = client.post(
        "/api/zotero/warmup",
        json={
            "model": "gpt-5.4-mini",
            "extra_models": ["gpt-5.4-mini"],
        },
    )

    assert response.status_code == 202, response.text
    assert response.json()["extra_models"] == []
    assert warm_calls == [
        {
            "cwd": Path("/tmp/rh-zotero-warmup"),
            "model": "gpt-5.4-mini",
            "effort": "low",
            "service_tier": "auto",
        }
    ]


def test_zotero_warmup_preserves_token_gate():
    client, warm_calls, token_calls = _build_zotero_warmup_client(
        token_required=True,
    )

    blocked = client.post(
        "/api/zotero/warmup",
        json={"model": "gpt-5.4-mini"},
    )
    allowed = client.post(
        "/api/zotero/warmup",
        headers={"X-RH-Zotero-Token": "secret"},
        json={"model": "gpt-5.4-mini"},
    )

    assert blocked.status_code == 401
    assert allowed.status_code == 202, allowed.text
    assert token_calls == ["/api/zotero/warmup", "/api/zotero/warmup"]
    assert len(warm_calls) == 1
