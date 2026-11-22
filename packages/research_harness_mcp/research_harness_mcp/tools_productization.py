"""MCP productization tool definitions and fallback execution."""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from research_harness._productization import (
    build_lg10_productization_boundary_payload,
)

_PRODUCTIZATION_TOOLS: dict[str, Tool] = {
    "productization_boundary": Tool(
        name="productization_boundary",
        description=(
            "Show the LG10 public-productization boundary preview. This tool is "
            "read-only and requires experimental_lg10=true; it does not approve "
            "new public implementation work."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "experimental_lg10": {
                    "type": "boolean",
                    "default": False,
                    "description": "Explicit opt-in for the LG10 boundary preview.",
                },
            },
        },
    ),
}


def _execute_productization_tool(
    name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    if name != "productization_boundary":
        return {"error": f"Unknown productization tool: {name}"}
    if arguments.get("experimental_lg10") is not True:
        return {
            "error": "pass experimental_lg10=true to view the LG10 boundary",
            "code": "lg10_opt_in_required",
        }
    return build_lg10_productization_boundary_payload(scope="public-mcp-opt-in-preview")
