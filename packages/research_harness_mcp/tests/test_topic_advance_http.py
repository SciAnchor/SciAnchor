"""Focused HTTP tests for topic advance route extraction."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_topic_advance_module_imports_and_route_registered():
    from research_harness_mcp import http_api, topic_advance_http

    assert callable(topic_advance_http.register_topic_advance_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}/advance" and "POST" in route.methods
    ]
    assert len(matching_routes) == 1

    paths = [route.path for route in http_api.app.routes]
    assert paths.index("/api/topics/{topic_id}/advance") < paths.index(
        "/api/topics/{topic_id}/gate"
    )
    assert paths.index("/api/topics/{topic_id}/gate") < paths.index(
        "/api/topics/{topic_id}/expansion"
    )


def test_topic_advance_preserves_default_actor_and_response_passthrough(monkeypatch):
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict]] = []

    def fake_run_tool(name: str, arguments: dict):
        calls.append((name, arguments))
        return {"status": "success", "tool": name, "arguments": arguments}

    monkeypatch.setattr(http_api, "_run_tool", fake_run_tool)

    response = TestClient(http_api.app).post("/api/topics/77/advance", json={})

    assert response.status_code == 200, response.text
    assert calls == [
        (
            "orchestrator_advance",
            {"topic_id": 77, "actor": "web_ui"},
        )
    ]
    assert response.json() == {
        "status": "success",
        "tool": "orchestrator_advance",
        "arguments": {"topic_id": 77, "actor": "web_ui"},
    }


def test_topic_advance_preserves_actor_override(monkeypatch):
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict]] = []

    def fake_run_tool(name: str, arguments: dict):
        calls.append((name, arguments))
        return {"status": "success", "actor": arguments["actor"]}

    monkeypatch.setattr(http_api, "_run_tool", fake_run_tool)

    response = TestClient(http_api.app).post(
        "/api/topics/12/advance",
        json={"actor": "release-bot"},
    )

    assert response.status_code == 200, response.text
    assert calls == [
        (
            "orchestrator_advance",
            {"topic_id": 12, "actor": "release-bot"},
        )
    ]
    assert response.json() == {"status": "success", "actor": "release-bot"}
