"""Focused HTTP tests for domain suggest route extraction."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_domain_suggest_module_imports_and_route_registered():
    from research_harness_mcp import domain_suggest_http, http_api

    assert callable(domain_suggest_http.register_domain_suggest_routes)
    assert any(
        route.path == "/api/domains/suggest" and "POST" in route.methods
        for route in http_api.app.routes
    )


def test_domain_suggest_trims_idea_and_preserves_payload_shape():
    from research_harness_mcp.http_api import app

    response = TestClient(app).post(
        "/api/domains/suggest",
        json={
            "idea": "  scalable retrieval augmented generation for research agents  "
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "suggestion": {
            "name": "Scalable Retrieval Augmented Generation For",
            "description": "scalable retrieval augmented generation for research agents",
            "keywords": [
                "scalable",
                "retrieval",
                "augmented",
                "generation",
                "for",
                "research",
                "agents",
            ],
        },
        "source": "stub",
    }


def test_domain_suggest_rejects_empty_idea():
    from research_harness_mcp.http_api import app

    response = TestClient(app).post("/api/domains/suggest", json={"idea": "   "})

    assert response.status_code == 400
    assert response.json() == {"detail": "Idea text is required"}
