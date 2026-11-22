from __future__ import annotations


from research_harness._productization.boundary import (
    build_lg10_productization_boundary_payload,
    lg10_productization_boundary_components,
    productization_zotero_local_status,
)


def test_lg10_boundary_components_harden_previews_without_payload_shape_change():
    payload = build_lg10_productization_boundary_payload()
    components = lg10_productization_boundary_components()

    assert set(payload) == {
        "schema_version",
        "boundary_id",
        "scope",
        "lg8_lg9_prerequisite",
        "lg10_status",
        "public_surfaces",
        "allowed_future_pattern",
        "future_slice_policy",
        "required_pre_implementation_evidence",
        "stop_before",
        "risk_flags",
        "surface_boundaries",
    }
    assert payload["scope"] == "public-cli-opt-in-preview"
    assert payload["lg10_status"] == "gate_bound"

    components_by_surface = {item["surface"]: item for item in components}
    assert set(components_by_surface) == set(payload["public_surfaces"])

    stable_surfaces = {
        "CLI",
        "MCP",
        "HTTP",
        "Python facade",
        "doctor",
        "showcase",
        "skills/docs",
    }
    for surface in stable_surfaces:
        component = components_by_surface[surface]
        assert component["classification"] == "stable_internal_boundary_component"
        assert component["opt_in_required"] is True
        assert component["default_compatibility"] == "unchanged"
        assert component["public_payload_shape"] == "preserved"
        assert component["release_status"] == "not_release_ready"
        assert component["benchmark_claim_status"] == "not_approved"

    zotero = components_by_surface["Zotero"]
    assert zotero["classification"] == "stable_local_dry_run_validation_component"
    assert zotero["scope"] == "local-zotero-push-dry-run-validation"
    assert zotero["stable_direction"] == "push"
    assert zotero["dry_run_required"] is True
    assert zotero["release_status"] == "not_release_ready"
    assert "real_zotero_sync_apply" in zotero["deferred_paths"]


def test_productization_zotero_local_status_is_stable_local_only():
    status = productization_zotero_local_status()

    assert status["component_id"] == "productization-zotero-local-productization"
    assert status["status"] == "stable_local_productization_components"
    assert status["public_payload_shapes"] == "preserved"
    assert status["external_actions"] == "deferred"
    assert status["zotero"]["classification"] == (
        "stable_local_dry_run_validation_component"
    )
    assert status["zotero"]["dry_run_required"] is True
    assert status["zotero"]["stable_direction"] == "push"
    assert status["zotero"]["no_client_on_stable_path"] is True
    assert "zotero_ui" in status["zotero"]["deferred_paths"]


def test_lg10_boundary_component_registry_is_immutable_to_callers():
    first = lg10_productization_boundary_components()
    first[0]["classification"] = "mutated"

    second = lg10_productization_boundary_components()

    assert second[0]["classification"] == "stable_internal_boundary_component"
