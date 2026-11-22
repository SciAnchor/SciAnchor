"""LG10 public-productization boundary payloads and internal component records."""

from __future__ import annotations

from typing import Any


PUBLIC_SURFACES = [
    "CLI",
    "MCP",
    "HTTP",
    "Python facade",
    "Zotero",
    "doctor",
    "showcase",
    "skills/docs",
]

REQUIRED_PRE_IMPLEMENTATION_EVIDENCE = [
    "shape-lock tests",
    "opt-in default",
    "compatibility proof",
    "docs claim review",
    "rollback/fallback plan",
]

STOP_BEFORE = [
    "public surface changes",
    "storage/provenance semantic changes",
    "artifact lineage changes",
    "orchestrator gate/transition/rollback behavior",
    "benchmark or public performance claims",
    "dependency changes",
    "external actions",
    "credential/config mutation",
    "local/private data exposure",
    "compatibility-name removal",
    "Zotero/HTTP/MCP/RH/ARE scope changes",
    "commits",
    "pushes",
    "PRs",
    "releases",
    "publishing",
]

PRODUCTIZATION_BOUNDARY_COMPONENT_SCHEMA_VERSION = (
    "lg10_productization_boundary_component.v1"
)
PRODUCTIZATION_ZOTERO_LOCAL_COMPONENT_ID = "productization-zotero-local-productization"

_STABLE_INTERNAL_COMPONENT_SURFACES = {
    "CLI": "public-cli-opt-in-preview",
    "MCP": "public-mcp-opt-in-preview",
    "HTTP": "public-http-opt-in-preview",
    "Python facade": "public-python-opt-in-preview",
    "doctor": "public-doctor-opt-in-preview",
    "showcase": "public-showcase-opt-in-preview",
    "skills/docs": "public-skills-docs-opt-in-preview",
}


def _component_record(surface: str) -> dict[str, Any]:
    scope = _STABLE_INTERNAL_COMPONENT_SURFACES.get(surface, "")
    if surface == "Zotero":
        return {
            "schema_version": PRODUCTIZATION_BOUNDARY_COMPONENT_SCHEMA_VERSION,
            "surface": surface,
            "scope": "local-zotero-push-dry-run-validation",
            "classification": "stable_local_dry_run_validation_component",
            "opt_in_required": True,
            "default_compatibility": "unchanged",
            "public_payload_shape": "preserved",
            "release_status": "not_release_ready",
            "benchmark_claim_status": "not_approved",
            "stable_direction": "push",
            "dry_run_required": True,
            "no_client_on_stable_path": True,
            "deferred_paths": [
                "pull_dry_run",
                "both_dry_run",
                "real_zotero_sync_apply",
                "zotero_ui",
            ],
        }
    return {
        "schema_version": PRODUCTIZATION_BOUNDARY_COMPONENT_SCHEMA_VERSION,
        "surface": surface,
        "scope": scope,
        "classification": "stable_internal_boundary_component",
        "opt_in_required": True,
        "default_compatibility": "unchanged",
        "public_payload_shape": "preserved",
        "release_status": "not_release_ready",
        "benchmark_claim_status": "not_approved",
    }


PRODUCTIZATION_BOUNDARY_COMPONENTS = tuple(
    _component_record(surface) for surface in PUBLIC_SURFACES
)


def lg10_productization_boundary_components() -> list[dict[str, Any]]:
    """Return internal ST03 stabilization records without changing public payloads."""
    return [
        _copy_component(component) for component in PRODUCTIZATION_BOUNDARY_COMPONENTS
    ]


def productization_zotero_local_status() -> dict[str, Any]:
    """Return local productization readiness for boundary components and Zotero."""

    components = lg10_productization_boundary_components()
    zotero = next(
        component for component in components if component["surface"] == "Zotero"
    )
    stable_components = [
        component
        for component in components
        if component["classification"]
        in {
            "stable_internal_boundary_component",
            "stable_local_dry_run_validation_component",
        }
    ]
    return {
        "component_id": PRODUCTIZATION_ZOTERO_LOCAL_COMPONENT_ID,
        "status": "stable_local_productization_components",
        "scope": "private-rh-selfdev-local-productization",
        "public_payload_shapes": "preserved",
        "external_actions": "deferred",
        "release_status": "not_release_ready",
        "benchmark_claim_status": "not_approved",
        "stable_component_count": len(stable_components),
        "productization_surfaces": components,
        "zotero": zotero,
        "deferred": [
            {
                "id": "real-zotero-sync-apply",
                "reason": "requires Zotero credentials/network/apply permission",
            },
            {
                "id": "zotero-ui-release",
                "reason": "requires separate UI/release gate and external action approval",
            },
            {
                "id": "public-release-readiness",
                "reason": "no release, publishing, benchmark, or performance claim is approved",
            },
        ],
    }


def build_lg10_productization_boundary_payload(
    *, scope: str = "public-cli-opt-in-preview"
) -> dict[str, Any]:
    """Build the public-safe LG10 boundary preview payload."""
    return {
        "schema_version": "lg10_productization_boundary.v1",
        "boundary_id": "lg10-public-productization-boundary",
        "scope": scope,
        "lg8_lg9_prerequisite": "complete",
        "lg10_status": "gate_bound",
        "public_surfaces": list(PUBLIC_SURFACES),
        "allowed_future_pattern": "one_public_surface_per_gate_slice",
        "future_slice_policy": (
            "A future human-approved LG10 slice may change exactly one public "
            "surface, must be opt-in by default, and must preserve existing "
            "behavior unless the gate explicitly approves a compatibility break."
        ),
        "required_pre_implementation_evidence": list(
            REQUIRED_PRE_IMPLEMENTATION_EVIDENCE
        ),
        "stop_before": list(STOP_BEFORE),
        "risk_flags": {
            "public_surface_changed": False,
            "storage_or_provenance_changed": False,
            "orchestrator_gate_changed": False,
            "benchmark_claim_changed": False,
            "dependency_changed": False,
        },
        "surface_boundaries": [
            {
                "surface": surface,
                "future_scope": "gate_required",
                "minimum_evidence": list(REQUIRED_PRE_IMPLEMENTATION_EVIDENCE),
                "default_policy": "opt_in_and_backwards_compatible",
            }
            for surface in PUBLIC_SURFACES
        ],
    }


def lg10_productization_boundary(*, experimental_lg10: bool = False) -> dict[str, Any]:
    """Return the opt-in LG10 productization boundary preview for Python callers."""
    if not experimental_lg10:
        raise ValueError(
            "lg10_opt_in_required: pass experimental_lg10=True to view the "
            "LG10 boundary"
        )
    return build_lg10_productization_boundary_payload(
        scope="public-python-opt-in-preview"
    )


def _copy_component(component: dict[str, Any]) -> dict[str, Any]:
    copied = dict(component)
    for key, value in component.items():
        if isinstance(value, list):
            copied[key] = list(value)
    return copied
