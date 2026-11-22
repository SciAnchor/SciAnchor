"""HTTP boundary helpers for the local Research Harness bridge."""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable, Iterable
from ipaddress import ip_address

from fastapi import Request
from fastapi.responses import JSONResponse, Response

HTTP_API_TOKEN_ENV = "RESEARCH_HARNESS_HTTP_API_TOKEN"
HTTP_API_TOKEN_HEADER = "X-RH-HTTP-Token"
HTTP_HOST_ENV = "RESEARCH_HARNESS_HTTP_HOST"
UNSAFE_HTTP_BIND_ENV = "RESEARCH_HARNESS_UNSAFE_HTTP_BIND"

_SENSITIVE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_LOCAL_TEST_HOSTS = {"testclient", "testserver"}


def resolve_http_bind_host(host: str | None = None) -> str:
    """Resolve and validate the configured HTTP bind host."""

    resolved = host or os.environ.get(HTTP_HOST_ENV, "127.0.0.1")
    if _is_loopback_host(resolved):
        return resolved
    if _truthy(os.environ.get(UNSAFE_HTTP_BIND_ENV)):
        _require_public_http_auth()
        return resolved
    raise RuntimeError(
        "Non-loopback HTTP binding is unsupported and not release-approved. "
        f"Set {UNSAFE_HTTP_BIND_ENV}=1 only for reviewed local experiments."
    )


def enforce_direct_asgi_bind_argv(argv: Iterable[str]) -> None:
    """Apply bind-host policy for direct ASGI runner imports."""

    args = tuple(str(arg) for arg in argv)
    if not any(_is_http_api_app_target(arg) for arg in args):
        return
    host = _uvicorn_host_arg(args)
    if host is None:
        return
    resolve_http_bind_host(host)


def http_token_error(request: Request) -> JSONResponse | None:
    """Return an auth error when the HTTP token gate applies."""

    auth_forced = _truthy(
        os.environ.get(UNSAFE_HTTP_BIND_ENV)
    ) or _request_has_non_loopback_boundary(request)
    if not _requires_http_token_auth(request, auth_forced=auth_forced):
        return None

    expected = os.environ.get(HTTP_API_TOKEN_ENV, "").strip()
    if not expected and not auth_forced:
        return None
    if expected and _http_token_matches(request, expected):
        return None
    return JSONResponse(
        {"detail": "Research Harness HTTP token required"},
        status_code=401,
    )


async def sensitive_route_token_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    token_error = http_token_error(request)
    if token_error is not None:
        return token_error
    return await call_next(request)


def _require_public_http_auth() -> None:
    if os.environ.get(HTTP_API_TOKEN_ENV, "").strip():
        return
    raise RuntimeError(
        "Non-loopback HTTP binding requires "
        f"{HTTP_API_TOKEN_ENV} to be configured. Public deployment also needs "
        "a reviewed TLS/proxy, network allowlist, scoped CORS, cache, rollback, "
        "and monitoring plan."
    )


def _is_http_api_app_target(arg: str) -> bool:
    return arg == "research_harness_mcp.http_api:app"


def _uvicorn_host_arg(args: tuple[str, ...]) -> str | None:
    for index, arg in enumerate(args):
        if arg == "--host" and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("--host="):
            return arg.split("=", 1)[1]
    return None


def _requires_http_token_auth(request: Request, *, auth_forced: bool) -> bool:
    if request.method == "OPTIONS":
        return False
    if auth_forced:
        return True
    return _requires_sensitive_route_auth(request)


def _requires_sensitive_route_auth(request: Request) -> bool:
    path = request.url.path
    if request.method in _SENSITIVE_METHODS:
        return True
    return (
        path.startswith("/api/zotero")
        or "/zotero" in path
        or path.startswith("/api/longtasks")
        or path.startswith("/api/llm")
        or path.startswith("/api/agents")
        or path.startswith("/api/reports")
        or path.startswith("/api/shared/reports")
        or (path.startswith("/api/topics/") and "/reports" in path)
    )


def _request_has_non_loopback_boundary(request: Request) -> bool:
    return any(
        _host_requires_public_http_auth(host)
        for host in _request_boundary_hosts(request)
    )


def _request_boundary_hosts(request: Request) -> list[str]:
    hosts: list[str] = []
    server = request.scope.get("server")
    if isinstance(server, (tuple, list)) and server:
        hosts.append(str(server[0]))
    if request.client is not None:
        hosts.append(str(request.client.host))
    header_host = _host_from_header(request.headers.get("host", ""))
    if header_host:
        hosts.append(header_host)
    return hosts


def _host_requires_public_http_auth(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    return bool(
        normalized
        and normalized not in _LOCAL_TEST_HOSTS
        and not _is_loopback_host(normalized)
    )


def _host_from_header(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped.startswith("[") and "]" in stripped:
        return stripped[1:].split("]", 1)[0]
    return stripped.split(":", 1)[0]


def _http_token_matches(request: Request, expected: str) -> bool:
    return any(
        hmac.compare_digest(candidate, expected)
        for candidate in _http_token_candidates(request)
    )


def _http_token_candidates(request: Request) -> list[str]:
    candidates: list[str] = []
    header_token = request.headers.get(HTTP_API_TOKEN_HEADER, "").strip()
    if header_token:
        candidates.append(header_token)
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        bearer = authorization.removeprefix("Bearer ").strip()
        if bearer:
            candidates.append(bearer)
    return candidates


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}
