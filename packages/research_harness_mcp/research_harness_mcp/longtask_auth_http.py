"""Private helpers for local LongTask HTTP auth boundary behavior."""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

_LONGTASK_ADMIN_TOKEN_ENV = "RESEARCH_HARNESS_LONGTASK_ADMIN_TOKEN"
_LONGTASK_API_PREFIX = "/api/longtasks"
_LONGTASK_ADMIN_TOKEN_HEADER = "X-LongTask-Token"


def longtask_admin_token_error(request: Request) -> JSONResponse | None:
    """Return the LongTask admin-token error response, or None when allowed."""
    if not _requires_longtask_admin_token(request):
        return None

    expected = os.environ.get(_LONGTASK_ADMIN_TOKEN_ENV)
    if not expected:
        return None

    if _longtask_admin_token_matches(request, expected):
        return None

    return JSONResponse(
        {"detail": "LongTask admin token required"},
        status_code=401,
    )


async def longtask_admin_token_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Apply the optional local admin token gate for LongTask endpoints."""
    token_error = longtask_admin_token_error(request)
    if token_error is not None:
        return token_error
    return await call_next(request)


def _requires_longtask_admin_token(request: Request) -> bool:
    return (
        request.url.path.startswith(_LONGTASK_API_PREFIX)
        and request.method != "OPTIONS"
    )


def _longtask_admin_token_matches(request: Request, expected: str) -> bool:
    return hmac.compare_digest(_longtask_admin_token(request), expected)


def _longtask_admin_token(request: Request) -> str:
    provided = request.headers.get(_LONGTASK_ADMIN_TOKEN_HEADER, "")
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        provided = authorization.removeprefix("Bearer ").strip()
    return provided
