"""Focused tests for MCP productization tool helpers."""

from __future__ import annotations


def test_productization_tool_definition_preserves_public_schema() -> None:
    from research_harness_mcp.tools_productization import _PRODUCTIZATION_TOOLS

    tool = _PRODUCTIZATION_TOOLS["productization_boundary"]

    assert tool.name == "productization_boundary"
    assert "LG10 public-productization boundary preview" in tool.description
    assert tool.inputSchema == {
        "type": "object",
        "properties": {
            "experimental_lg10": {
                "type": "boolean",
                "default": False,
                "description": "Explicit opt-in for the LG10 boundary preview.",
            },
        },
    }


def test_execute_productization_tool_preserves_opt_in_and_payload_shape() -> None:
    from research_harness_mcp.tools_productization import _execute_productization_tool

    missing_opt_in = _execute_productization_tool("productization_boundary", {})
    assert missing_opt_in == {
        "error": "pass experimental_lg10=true to view the LG10 boundary",
        "code": "lg10_opt_in_required",
    }

    unknown = _execute_productization_tool("unknown_productization_tool", {})
    assert unknown == {
        "error": "Unknown productization tool: unknown_productization_tool"
    }

    payload = _execute_productization_tool(
        "productization_boundary",
        {"experimental_lg10": True},
    )
    assert payload["boundary_id"] == "lg10-public-productization-boundary"
    assert payload["schema_version"] == "lg10_productization_boundary.v1"
    assert payload["scope"] == "public-mcp-opt-in-preview"
    assert payload["risk_flags"] == {
        "public_surface_changed": False,
        "storage_or_provenance_changed": False,
        "orchestrator_gate_changed": False,
        "benchmark_claim_changed": False,
        "dependency_changed": False,
    }
