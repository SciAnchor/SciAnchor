"""Private helpers for local Topic Knowledge HTTP boundary behavior."""

from __future__ import annotations

import hmac
import os
import re
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

_KNOWLEDGE_API_TOKEN_ENV = "RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN"
_KNOWLEDGE_API_TOKEN_HEADER = "X-RH-Knowledge-Token"
_KNOWLEDGE_API_CACHE_CONTROL = "private, no-store"
_CORS_ORIGINS_ENV = "RESEARCH_HARNESS_CORS_ORIGINS"


def _configured_cors_origins() -> list[str]:
    origins = [
        origin.strip()
        for origin in os.environ.get(
            _CORS_ORIGINS_ENV,
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ]
    if "*" in origins:
        raise RuntimeError(
            f"Wildcard credentialed CORS is unsupported; configure "
            f"{_CORS_ORIGINS_ENV} with explicit origins."
        )
    return origins


_CORS_ALLOWED_ORIGINS = _configured_cors_origins()


def _is_knowledge_api_path(path: str) -> bool:
    return path in {
        "/api/topics/cross-topic-atlas",
        "/api/topics/knowledge-refresh-all",
    } or bool(
        re.fullmatch(r"/api/topics/[^/]+/(knowledge-status|knowledge-refresh)", path)
    )


def _knowledge_api_token_candidates(request: Request) -> list[str]:
    candidates: list[str] = []
    header_token = request.headers.get(_KNOWLEDGE_API_TOKEN_HEADER, "").strip()
    if header_token:
        candidates.append(header_token)

    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        bearer_token = authorization.removeprefix("Bearer ").strip()
        if bearer_token:
            candidates.append(bearer_token)
    return candidates


def _knowledge_api_token_matches(request: Request, expected: str) -> bool:
    return any(
        hmac.compare_digest(candidate, expected)
        for candidate in _knowledge_api_token_candidates(request)
    )


def _knowledge_api_cors_headers(request: Request | None) -> dict[str, str]:
    if request is None:
        return {}
    origin = request.headers.get("origin")
    if not origin:
        return {}
    if origin not in _CORS_ALLOWED_ORIGINS:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


def _knowledge_api_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request: Request | None = None,
) -> JSONResponse:
    headers = {"Cache-Control": _KNOWLEDGE_API_CACHE_CONTROL}
    headers.update(_knowledge_api_cors_headers(request))
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


def _knowledge_api_beta_token_error(request: Request) -> JSONResponse | None:
    if not _is_knowledge_api_path(request.url.path) or request.method == "OPTIONS":
        return None

    expected = os.environ.get(_KNOWLEDGE_API_TOKEN_ENV, "").strip()
    if not expected or _knowledge_api_token_matches(request, expected):
        return None

    return _knowledge_api_error_response(
        status_code=401,
        code="knowledge_api_token_required",
        message="knowledge API beta token required",
        request=request,
    )


def _apply_knowledge_api_cache_control(
    *, request: Request, response: Response
) -> Response:
    if _is_knowledge_api_path(request.url.path):
        response.headers["Cache-Control"] = _KNOWLEDGE_API_CACHE_CONTROL
    return response


async def knowledge_api_beta_token_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    token_error = _knowledge_api_beta_token_error(request)
    if token_error is not None:
        return token_error
    response = await call_next(request)
    return _apply_knowledge_api_cache_control(request=request, response=response)


def _parse_positive_topic_id(raw_topic_id: str) -> int | None:
    try:
        topic_id = int(raw_topic_id)
    except ValueError:
        return None
    return topic_id if topic_id > 0 else None


def _parse_cross_topic_max_results(raw_max_results: str) -> int | None:
    try:
        max_results = int(raw_max_results)
    except ValueError:
        return None
    return max_results if 1 <= max_results <= 20 else None
