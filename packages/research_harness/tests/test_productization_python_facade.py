from __future__ import annotations

import json

import pytest


def test_productization_boundary_python_facade_requires_explicit_lg10_opt_in():
    from research_harness import lg10_productization_boundary

    with pytest.raises(ValueError, match="lg10_opt_in_required"):
        lg10_productization_boundary()


def test_productization_boundary_python_facade_outputs_shape_locked_payload_without_db(
    monkeypatch: pytest.MonkeyPatch,
):
    import research_harness.api as api_module
    from research_harness import lg10_productization_boundary

    def fail_database(*args, **kwargs):
        raise AssertionError("productization boundary facade must not open the DB")

    monkeypatch.setattr(api_module, "Database", fail_database)

    payload = lg10_productization_boundary(experimental_lg10=True)

    assert payload["boundary_id"] == "lg10-public-productization-boundary"
    assert payload["schema_version"] == "lg10_productization_boundary.v1"
    assert payload["scope"] == "public-python-opt-in-preview"
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
