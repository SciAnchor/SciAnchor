from __future__ import annotations

import asyncio
import importlib
import json

from starlette.responses import Response
from starlette.requests import Request


def _request(
    headers: dict[str, str] | None = None,
    *,
    path: str = "/api/topics/1/knowledge-status",
    method: str = "GET",
) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": raw_headers,
        }
    )


def test_knowledge_http_helpers_match_only_knowledge_paths():
    from research_harness_mcp.knowledge_http import _is_knowledge_api_path

    assert _is_knowledge_api_path("/api/topics/cross-topic-atlas") is True
    assert _is_knowledge_api_path("/api/topics/knowledge-refresh-all") is True
    assert _is_knowledge_api_path("/api/topics/42/knowledge-status") is True
    assert _is_knowledge_api_path("/api/topics/42/knowledge-refresh") is True
    assert _is_knowledge_api_path("/api/topics/42/papers") is False


def test_knowledge_http_helpers_parse_public_query_values():
    from research_harness_mcp.knowledge_http import (
        _parse_cross_topic_max_results,
        _parse_positive_topic_id,
    )

    assert _parse_positive_topic_id("42") == 42
    assert _parse_positive_topic_id("0") is None
    assert _parse_positive_topic_id("not-int") is None
    assert _parse_cross_topic_max_results("1") == 1
    assert _parse_cross_topic_max_results("20") == 20
    assert _parse_cross_topic_max_results("21") is None
    assert _parse_cross_topic_max_results("not-int") is None


def test_knowledge_http_helpers_match_header_and_bearer_tokens():
    from research_harness_mcp.knowledge_http import _knowledge_api_token_matches

    assert (
        _knowledge_api_token_matches(
            _request({"X-RH-Knowledge-Token": "secret"}), "secret"
        )
        is True
    )
    assert (
        _knowledge_api_token_matches(
            _request({"Authorization": "Bearer secret"}), "secret"
        )
        is True
    )
    assert (
        _knowledge_api_token_matches(
            _request({"X-RH-Knowledge-Token": "wrong"}), "secret"
        )
        is False
    )


def test_knowledge_http_helpers_use_configured_allowed_origins(monkeypatch):
    monkeypatch.setenv(
        "RESEARCH_HARNESS_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    import research_harness_mcp.knowledge_http as knowledge_http

    knowledge_http = importlib.reload(knowledge_http)

    assert knowledge_http._knowledge_api_cors_headers(
        _request({"Origin": "http://localhost:3000"})
    ) == {
        "Access-Control-Allow-Origin": "http://localhost:3000",
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }
    assert (
        knowledge_http._knowledge_api_cors_headers(
            _request({"Origin": "http://example.test"})
        )
        == {}
    )


def test_knowledge_http_helpers_build_beta_token_error(monkeypatch):
    from research_harness_mcp.knowledge_http import _knowledge_api_beta_token_error

    monkeypatch.setenv("RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN", "beta-secret")

    non_knowledge = _knowledge_api_beta_token_error(_request(path="/api/topics/42"))
    options = _knowledge_api_beta_token_error(
        _request(method="OPTIONS", headers={"X-RH-Knowledge-Token": "wrong"})
    )
    wrong = _knowledge_api_beta_token_error(
        _request(headers={"X-RH-Knowledge-Token": "wrong"})
    )
    allowed = _knowledge_api_beta_token_error(
        _request(headers={"Authorization": "Bearer beta-secret"})
    )

    assert non_knowledge is None
    assert options is None
    assert allowed is None
    assert wrong is not None
    assert wrong.status_code == 401
    assert json.loads(wrong.body) == {
        "error": {
            "code": "knowledge_api_token_required",
            "message": "knowledge API beta token required",
        }
    }


def test_knowledge_http_helpers_apply_cache_control_only_for_knowledge_paths():
    from research_harness_mcp.knowledge_http import _apply_knowledge_api_cache_control

    knowledge = Response()
    regular = Response()

    assert (
        _apply_knowledge_api_cache_control(request=_request(), response=knowledge)
        is knowledge
    )
    assert knowledge.headers["Cache-Control"] == "private, no-store"

    assert (
        _apply_knowledge_api_cache_control(
            request=_request(path="/api/topics/42"), response=regular
        )
        is regular
    )
    assert "Cache-Control" not in regular.headers


def test_knowledge_http_middleware_helper_short_circuits_or_calls_next(monkeypatch):
    from research_harness_mcp.knowledge_http import knowledge_api_beta_token_middleware

    calls: list[str] = []

    async def call_next(_request: Request) -> Response:
        calls.append("next")
        return Response("ok", status_code=202)

    monkeypatch.setenv("RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN", "beta-secret")

    rejected = asyncio.run(knowledge_api_beta_token_middleware(_request(), call_next))
    allowed = asyncio.run(
        knowledge_api_beta_token_middleware(
            _request(headers={"X-RH-Knowledge-Token": "beta-secret"}),
            call_next,
        )
    )

    assert rejected.status_code == 401
    assert allowed.status_code == 202
    assert allowed.headers["Cache-Control"] == "private, no-store"
    assert calls == ["next"]


def test_knowledge_http_helpers_preserve_http_api_error_alias():
    from research_harness_mcp import http_api
    from research_harness_mcp.knowledge_http import _knowledge_api_error_response

    assert http_api._knowledge_api_error is _knowledge_api_error_response

    response = http_api._knowledge_api_error(
        status_code=400,
        code="knowledge_bad_request",
        message="bad knowledge request",
    )

    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "private, no-store"
    assert json.loads(response.body) == {
        "error": {
            "code": "knowledge_bad_request",
            "message": "bad knowledge request",
        }
    }
