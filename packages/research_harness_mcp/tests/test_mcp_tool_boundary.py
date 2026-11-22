from __future__ import annotations

import asyncio
import json


def test_mcp_call_tool_blocks_non_public_internal_tool_names():
    from research_harness_mcp.server import handle_call_tool

    response = asyncio.run(handle_call_tool("provenance_token_report", {}))
    result = json.loads(response[0].text)

    assert result["status"] == "error"
    assert result["summary"] == "Tool is not part of the public MCP surface."
    assert result["output"]["tool"] == "provenance_token_report"
