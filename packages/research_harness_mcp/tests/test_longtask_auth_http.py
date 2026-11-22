from __future__ import annotations

import asyncio

from starlette.responses import Response
from starlette.requests import Request


def _request(
    *,
    path: str = "/api/longtasks/runs",
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "http",
            "server": ("testserver", 80),
            "path": path,
            "root_path": "",
            "query_string": b"",
            "headers": raw_headers,
        }
    )


def test_longtask_auth_helper_ignores_non_longtask_paths_and_options(monkeypatch):
    from research_harness_mcp.longtask_auth_http import longtask_admin_token_error

    monkeypatch.setenv("RESEARCH_HARNESS_LONGTASK_ADMIN_TOKEN", "admin-secret")

    assert longtask_admin_token_error(_request(path="/api/topics")) is None
    assert longtask_admin_token_error(_request(method="OPTIONS")) is None


def test_longtask_auth_helper_allows_unconfigured_or_matching_header(monkeypatch):
    from research_harness_mcp.longtask_auth_http import longtask_admin_token_error

    monkeypatch.delenv("RESEARCH_HARNESS_LONGTASK_ADMIN_TOKEN", raising=False)
    assert longtask_admin_token_error(_request()) is None

    monkeypatch.setenv("RESEARCH_HARNESS_LONGTASK_ADMIN_TOKEN", "admin-secret")
    assert (
        longtask_admin_token_error(
            _request(headers={"X-LongTask-Token": "admin-secret"})
        )
        is None
    )


def test_longtask_auth_helper_accepts_bearer_and_rejects_missing_or_wrong(
    monkeypatch,
):
    from research_harness_mcp.longtask_auth_http import longtask_admin_token_error

    monkeypatch.setenv("RESEARCH_HARNESS_LONGTASK_ADMIN_TOKEN", "admin-secret")

    missing = longtask_admin_token_error(_request())
    wrong = longtask_admin_token_error(
        _request(headers={"X-LongTask-Token": "wrong-secret"})
    )

    assert missing is not None
    assert missing.status_code == 401
    assert wrong is not None
    assert wrong.status_code == 401
    assert (
        longtask_admin_token_error(
            _request(headers={"Authorization": "Bearer admin-secret"})
        )
        is None
    )


def test_longtask_auth_helper_preserves_bearer_precedence(monkeypatch):
    from research_harness_mcp.longtask_auth_http import longtask_admin_token_error

    monkeypatch.setenv("RESEARCH_HARNESS_LONGTASK_ADMIN_TOKEN", "admin-secret")

    bearer_overrides_header = longtask_admin_token_error(
        _request(
            headers={
                "X-LongTask-Token": "admin-secret",
                "Authorization": "Bearer wrong-secret",
            }
        )
    )
    assert bearer_overrides_header is not None
    assert bearer_overrides_header.status_code == 401

    assert (
        longtask_admin_token_error(
            _request(
                headers={
                    "X-LongTask-Token": "wrong-secret",
                    "Authorization": "Bearer admin-secret",
                }
            )
        )
        is None
    )


def test_longtask_auth_middleware_helper_short_circuits_or_calls_next(monkeypatch):
    from research_harness_mcp.longtask_auth_http import longtask_admin_token_middleware

    calls: list[str] = []

    async def call_next(_request: Request) -> Response:
        calls.append("next")
        return Response("ok", status_code=202)

    monkeypatch.setenv("RESEARCH_HARNESS_LONGTASK_ADMIN_TOKEN", "admin-secret")

    rejected = asyncio.run(longtask_admin_token_middleware(_request(), call_next))
    allowed = asyncio.run(
        longtask_admin_token_middleware(
            _request(headers={"X-LongTask-Token": "admin-secret"}),
            call_next,
        )
    )

    assert rejected.status_code == 401
    assert allowed.status_code == 202
    assert calls == ["next"]
