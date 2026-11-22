"""Focused HTTP tests for topic gate route extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_topic_gate_module_imports_and_route_registered():
    from research_harness_mcp import http_api, topic_gate_http

    assert callable(topic_gate_http.register_topic_gate_routes)
    matching_routes = [
        route
        for route in http_api.app.routes
        if route.path == "/api/topics/{topic_id}/gate" and "GET" in route.methods
    ]
    assert len(matching_routes) == 1

    paths = [route.path for route in http_api.app.routes]
    assert paths.index("/api/topics/{topic_id}/advance") < paths.index(
        "/api/topics/{topic_id}/gate"
    )
    assert paths.index("/api/topics/{topic_id}/gate") < paths.index(
        "/api/topics/{topic_id}/expansion"
    )


@dataclass
class _FakeServiceResult:
    status: str
    output: Any
    error: dict[str, str] | None = None
    summary: str = ""


class _FakeResearchService:
    result = _FakeServiceResult(status="success", output={})
    calls: list[tuple[Any, str, dict[str, Any]]] = []

    def __init__(self, *, db: Any):
        self.db = db

    def invoke(self, command: str, payload: dict[str, Any]) -> _FakeServiceResult:
        self.calls.append((self.db, command, payload))
        return self.result


def _build_topic_gate_client(monkeypatch, result: _FakeServiceResult) -> TestClient:
    from research_harness_mcp import topic_gate_http

    _FakeResearchService.result = result
    _FakeResearchService.calls = []
    monkeypatch.setattr(topic_gate_http, "ResearchService", _FakeResearchService)

    app = FastAPI()
    topic_gate_http.register_topic_gate_routes(
        app,
        db_path_provider=lambda: "topic-gate.db",
        classify_error_fn=lambda message: f"classified:{message}",
    )
    return TestClient(app)


def test_topic_gate_preserves_success_response_shape(monkeypatch):
    client = _build_topic_gate_client(
        monkeypatch,
        _FakeServiceResult(
            status="success",
            output={"gate_decision": "pass", "detail": "ready"},
        ),
    )

    response = client.get("/api/topics/77/gate")

    assert response.status_code == 200, response.text
    assert _FakeResearchService.calls == [
        (
            "topic-gate.db",
            "orchestrator_gate_check",
            {"topic_id": 77},
        )
    ]
    assert response.json() == {
        "status": "success",
        "summary": "Gate decision: pass",
        "output": {"gate_decision": "pass", "detail": "ready"},
        "next_actions": ["orchestrator_advance — gate passed"],
        "artifacts": [],
        "recovery_hint": "",
        "primitive": "orchestrator_gate_check",
        "backend": "orchestrator",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": "",
    }


def test_topic_gate_preserves_service_error_response_shape(monkeypatch):
    client = _build_topic_gate_client(
        monkeypatch,
        _FakeServiceResult(
            status="error",
            output={"gate_decision": "fail"},
            error={"message": "missing artifacts"},
            summary="fallback summary",
        ),
    )

    response = client.get("/api/topics/12/gate")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "error",
        "summary": "missing artifacts",
        "output": {"gate_decision": "fail", "error": "missing artifacts"},
        "next_actions": [],
        "artifacts": [],
        "recovery_hint": "classified:missing artifacts",
        "primitive": "orchestrator_gate_check",
        "backend": "orchestrator",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": "",
    }


def test_topic_gate_preserves_invalid_service_payload_response_shape(monkeypatch):
    client = _build_topic_gate_client(
        monkeypatch,
        _FakeServiceResult(status="success", output="not-a-dict"),
    )

    response = client.get("/api/topics/5/gate")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "error",
        "summary": "ResearchService orchestrator_gate_check returned an invalid payload",
        "output": {
            "error": "ResearchService orchestrator_gate_check returned an invalid payload"
        },
        "next_actions": [],
        "artifacts": [],
        "recovery_hint": (
            "classified:ResearchService orchestrator_gate_check returned "
            "an invalid payload"
        ),
        "primitive": "orchestrator_gate_check",
        "backend": "orchestrator",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": "",
    }
