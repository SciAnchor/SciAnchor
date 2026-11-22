from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    from research_harness_mcp import http_api

    def fail_get_db():
        raise AssertionError("productization boundary HTTP route must not open the DB")

    monkeypatch.setattr(http_api, "get_db", fail_get_db)
    yield TestClient(http_api.app)


def test_productization_boundary_http_requires_explicit_lg10_opt_in(
    client: TestClient,
):
    response = client.get("/api/productization/boundary")

    assert response.status_code == 403, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "error": {
            "code": "lg10_opt_in_required",
            "message": ("pass experimental_lg10=true to view the LG10 boundary"),
        }
    }


def test_productization_boundary_http_outputs_shape_locked_json_without_db(
    client: TestClient,
):
    response = client.get("/api/productization/boundary?experimental_lg10=true")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    payload = response.json()
    assert payload["boundary_id"] == "lg10-public-productization-boundary"
    assert payload["schema_version"] == "lg10_productization_boundary.v1"
    assert payload["scope"] == "public-http-opt-in-preview"
    assert payload["lg8_lg9_prerequisite"] == "complete"
    assert payload["lg10_status"] == "gate_bound"
    assert payload["allowed_future_pattern"] == "one_public_surface_per_gate_slice"
    assert payload["public_surfaces"] == [
        "CLI",
        "MCP",
        "HTTP",
        "Python facade",
        "Zotero",
        "doctor",
        "showcase",
        "skills/docs",
    ]
    assert payload["required_pre_implementation_evidence"] == [
        "shape-lock tests",
        "opt-in default",
        "compatibility proof",
        "docs claim review",
        "rollback/fallback plan",
    ]
    assert payload["risk_flags"] == {
        "public_surface_changed": False,
        "storage_or_provenance_changed": False,
        "orchestrator_gate_changed": False,
        "benchmark_claim_changed": False,
        "dependency_changed": False,
    }

    encoded = json.dumps(payload, sort_keys=True)
    for fragment in (
        ".research-harness",
        "SELECT ",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "sk-",
        "env_",
    ):
        assert fragment not in encoded
