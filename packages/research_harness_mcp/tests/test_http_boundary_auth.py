from __future__ import annotations

import os
import subprocess
import sys

from fastapi.testclient import TestClient


def _import_http_api_with_uvicorn_host(
    host: str,
    *,
    unsafe_bind: str | None = None,
    token: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    env.pop("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", None)
    env.pop("RESEARCH_HARNESS_HTTP_API_TOKEN", None)
    if unsafe_bind is not None:
        env["RESEARCH_HARNESS_UNSAFE_HTTP_BIND"] = unsafe_bind
    if token is not None:
        env["RESEARCH_HARNESS_HTTP_API_TOKEN"] = token
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.argv = ['uvicorn', 'research_harness_mcp.http_api:app', "
                f"'--host', {host!r}]; "
                "from research_harness_mcp import http_api"
            ),
        ],
        cwd=os.environ.get("PWD"),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_resolve_http_bind_host_rejects_non_loopback_without_unsafe_flag(monkeypatch):
    from research_harness_mcp import http_auth

    monkeypatch.setenv("RESEARCH_HARNESS_HTTP_HOST", "0.0.0.0")
    monkeypatch.delenv("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", raising=False)

    try:
        http_auth.resolve_http_bind_host()
    except RuntimeError as exc:
        assert "Non-loopback HTTP binding is unsupported" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected non-loopback bind rejection")


def test_resolve_http_bind_host_rejects_127_prefixed_hostname_without_unsafe_flag(
    monkeypatch,
):
    from research_harness_mcp import http_auth

    monkeypatch.setenv("RESEARCH_HARNESS_HTTP_HOST", "127.example.com")
    monkeypatch.delenv("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", raising=False)

    try:
        http_auth.resolve_http_bind_host()
    except RuntimeError as exc:
        assert "Non-loopback HTTP binding is unsupported" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected 127-prefixed hostname bind rejection")


def test_resolve_http_bind_host_rejects_unsafe_non_loopback_without_global_token(
    monkeypatch,
):
    from research_harness_mcp import http_auth

    monkeypatch.setenv("RESEARCH_HARNESS_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", "1")
    monkeypatch.delenv("RESEARCH_HARNESS_HTTP_API_TOKEN", raising=False)

    try:
        http_auth.resolve_http_bind_host()
    except RuntimeError as exc:
        assert "requires RESEARCH_HARNESS_HTTP_API_TOKEN" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected public bind auth rejection")


def test_resolve_http_bind_host_allows_explicit_unsafe_flag_with_global_token(
    monkeypatch,
):
    from research_harness_mcp import http_auth

    monkeypatch.setenv("RESEARCH_HARNESS_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", "1")
    monkeypatch.setenv("RESEARCH_HARNESS_HTTP_API_TOKEN", "secret")

    assert http_auth.resolve_http_bind_host() == "0.0.0.0"


def test_http_api_direct_asgi_rejects_non_loopback_uvicorn_host_without_unsafe_flag():
    result = _import_http_api_with_uvicorn_host("0.0.0.0")

    assert result.returncode != 0
    assert "Non-loopback HTTP binding is unsupported" in result.stderr


def test_http_api_direct_asgi_rejects_127_prefixed_hostname_without_unsafe_flag():
    result = _import_http_api_with_uvicorn_host("127.example.com")

    assert result.returncode != 0
    assert "Non-loopback HTTP binding is unsupported" in result.stderr


def test_http_api_direct_asgi_rejects_unsafe_non_loopback_without_global_token():
    result = _import_http_api_with_uvicorn_host("0.0.0.0", unsafe_bind="1")

    assert result.returncode != 0
    assert "requires RESEARCH_HARNESS_HTTP_API_TOKEN" in result.stderr


def test_http_api_direct_asgi_allows_unsafe_non_loopback_with_global_token():
    result = _import_http_api_with_uvicorn_host(
        "0.0.0.0",
        unsafe_bind="1",
        token="secret",
    )

    assert result.returncode == 0


def test_http_api_direct_asgi_allows_loopback_uvicorn_host_without_global_token():
    result = _import_http_api_with_uvicorn_host("127.0.0.1")

    assert result.returncode == 0


def test_http_sensitive_routes_require_global_token_when_configured(monkeypatch):
    from research_harness_mcp import http_api

    monkeypatch.setenv("RESEARCH_HARNESS_HTTP_API_TOKEN", "secret")

    missing = TestClient(http_api.app).post(
        "/api/llm/explain",
        json={"text": "passage"},
    )
    allowed = TestClient(http_api.app).post(
        "/api/llm/explain",
        headers={"Authorization": "Bearer secret"},
        json={"text": "   "},
    )

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Research Harness HTTP token required"
    assert allowed.status_code == 400


def test_http_sensitive_routes_fail_closed_for_unsafe_bind_without_token(monkeypatch):
    from research_harness_mcp import http_api

    monkeypatch.setenv("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", "1")
    monkeypatch.delenv("RESEARCH_HARNESS_HTTP_API_TOKEN", raising=False)

    response = TestClient(http_api.app).post(
        "/api/llm/explain",
        json={"text": "passage"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Research Harness HTTP token required"


def test_http_read_routes_require_global_token_for_unsafe_bind(monkeypatch):
    from research_harness_mcp import http_api

    monkeypatch.setenv("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", "1")
    monkeypatch.setenv("RESEARCH_HARNESS_HTTP_API_TOKEN", "secret")

    missing = TestClient(http_api.app).get("/api/topics/1/knowledge-status")
    allowed = TestClient(http_api.app).get(
        "/api/topics/1/knowledge-status",
        headers={"X-RH-HTTP-Token": "secret"},
    )

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Research Harness HTTP token required"
    assert allowed.status_code != 401


def test_http_discovery_routes_require_global_token_for_unsafe_bind(monkeypatch):
    from research_harness_mcp import http_api

    monkeypatch.setenv("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", "1")
    monkeypatch.setenv("RESEARCH_HARNESS_HTTP_API_TOKEN", "secret")
    client = TestClient(http_api.app)

    for path in ("/docs", "/redoc", "/openapi.json"):
        missing = client.get(path)
        allowed = client.get(path, headers={"Authorization": "Bearer secret"})

        assert missing.status_code == 401
        assert missing.json()["detail"] == "Research Harness HTTP token required"
        assert allowed.status_code == 200


def test_http_discovery_routes_require_global_token_for_non_loopback_request_host(
    monkeypatch,
):
    from research_harness_mcp import http_api

    monkeypatch.delenv("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", raising=False)
    monkeypatch.setenv("RESEARCH_HARNESS_HTTP_API_TOKEN", "secret")
    client = TestClient(http_api.app, base_url="http://203.0.113.10")

    missing = client.get("/openapi.json")
    allowed = client.get(
        "/openapi.json",
        headers={"X-RH-HTTP-Token": "secret"},
    )

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Research Harness HTTP token required"
    assert allowed.status_code == 200


def test_http_discovery_routes_require_global_token_for_127_prefixed_request_host(
    monkeypatch,
):
    from research_harness_mcp import http_api

    monkeypatch.delenv("RESEARCH_HARNESS_UNSAFE_HTTP_BIND", raising=False)
    monkeypatch.setenv("RESEARCH_HARNESS_HTTP_API_TOKEN", "secret")
    client = TestClient(http_api.app, base_url="http://127.example.com")

    missing = client.get("/openapi.json")
    allowed = client.get(
        "/openapi.json",
        headers={"X-RH-HTTP-Token": "secret"},
    )

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Research Harness HTTP token required"
    assert allowed.status_code == 200


def test_http_api_rejects_wildcard_credentialed_cors_on_import():
    env = {
        **os.environ,
        "RESEARCH_HARNESS_CORS_ORIGINS": "*",
    }

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from research_harness_mcp import http_api",
        ],
        cwd=os.environ.get("PWD"),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Wildcard credentialed CORS is unsupported" in result.stderr
