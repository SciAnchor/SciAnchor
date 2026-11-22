"""Focused HTTP tests for topic artifact record route extraction."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_topic_artifact_record_module_imports_and_route_registered():
    from research_harness_mcp import http_api, topic_artifact_record_http

    assert callable(topic_artifact_record_http.register_topic_artifact_record_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}/artifacts" and "POST" in route.methods
    ]
    assert len(matching_routes) == 1

    post_paths = [
        route.path
        for route in http_api.app.routes
        if "POST" in getattr(route, "methods", set())
    ]
    assert post_paths.index("/api/topics/{topic_id}/artifacts") < post_paths.index(
        "/api/topics/{topic_id}/force-advance"
    )


def test_topic_artifact_record_omits_empty_stage_and_passthrough(monkeypatch):
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict]] = []

    def fake_run_tool(name: str, arguments: dict):
        calls.append((name, arguments))
        if name == "orchestrator_status":
            return {"output": {"run": {"current_stage": "build"}}}
        return {"status": "success", "arguments": arguments}

    monkeypatch.setattr(http_api, "_run_tool", fake_run_tool)

    response = TestClient(http_api.app).post(
        "/api/topics/77/artifacts",
        json={"artifact_type": "topic_brief", "payload": {"brief": "text"}},
    )

    assert response.status_code == 200, response.text
    assert calls == [
        (
            "orchestrator_status",
            {
                "topic_id": 77,
            },
        ),
        (
            "orchestrator_record_artifact",
            {
                "topic_id": 77,
                "stage": "build",
                "artifact_type": "topic_brief",
                "payload": {"brief": "text"},
            },
        ),
    ]
    assert response.json() == {
        "status": "success",
        "arguments": {
            "topic_id": 77,
            "stage": "build",
            "artifact_type": "topic_brief",
            "payload": {"brief": "text"},
        },
    }


def test_topic_artifact_record_preserves_stage_override(monkeypatch):
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict]] = []

    def fake_run_tool(name: str, arguments: dict):
        calls.append((name, arguments))
        return {"status": "success", "stage": arguments["stage"]}

    monkeypatch.setattr(http_api, "_run_tool", fake_run_tool)

    response = TestClient(http_api.app).post(
        "/api/topics/12/artifacts",
        json={
            "artifact_type": "evidence_pack",
            "payload": {"claims": []},
            "stage": "analyze",
        },
    )

    assert response.status_code == 200, response.text
    assert calls == [
        (
            "orchestrator_record_artifact",
            {
                "topic_id": 12,
                "artifact_type": "evidence_pack",
                "payload": {"claims": []},
                "stage": "analyze",
            },
        )
    ]
    assert response.json() == {"status": "success", "stage": "analyze"}


def test_topic_artifact_record_rejects_missing_payload():
    from research_harness_mcp import http_api

    response = TestClient(http_api.app).post(
        "/api/topics/77/artifacts",
        json={"artifact_type": "topic_brief", "content": "legacy string"},
    )

    assert response.status_code == 422
