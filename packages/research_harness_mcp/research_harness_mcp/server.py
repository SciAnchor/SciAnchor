"""MCP server entry point — exposes research_harness primitives via stdio transport."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .tool_surface import PUBLIC_MCP_TOOL_NAMES
from .tools import execute_tool, list_tool_definitions

logger = logging.getLogger(__name__)

Executor = Callable[[str, dict[str, Any]], dict[str, Any]]


def build_server(
    name: str = "research-harness",
    allowed_tool_names: frozenset[str] | None = None,
    executor: Executor | None = None,
    extra_tools: list[Tool] | None = None,
) -> Server:
    """Low-level MCP server with an optional remote allowlist."""
    server = Server(name)
    run = executor or execute_tool
    permitted = (
        PUBLIC_MCP_TOOL_NAMES if allowed_tool_names is None else allowed_tool_names
    )
    extras = list(extra_tools or [])

    @server.list_tools()
    async def _handle_list_tools() -> list[Tool]:
        tools = list_tool_definitions()
        if allowed_tool_names is None:
            return tools
        listed = [tool for tool in tools if tool.name in allowed_tool_names]
        listed.extend(tool for tool in extras if tool.name in allowed_tool_names)
        return listed

    @server.call_tool()
    async def _handle_call_tool(
        tool_name: str, arguments: dict[str, Any] | None
    ) -> list[TextContent]:
        arguments = arguments or {}
        if tool_name not in permitted:
            return [_text_response(_public_tool_denied_response(tool_name))]
        return [_text_response(run(tool_name, arguments))]

    return server


app = Server("research-harness")


@app.list_tools()
async def handle_list_tools() -> list[Tool]:
    return list_tool_definitions()


@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any] | None
) -> list[TextContent]:
    arguments = arguments or {}
    if name not in PUBLIC_MCP_TOOL_NAMES:
        return [_text_response(_public_tool_denied_response(name))]
    result = execute_tool(name, arguments)
    return [_text_response(result)]


def _text_response(result: dict[str, Any]) -> TextContent:
    return [
        TextContent(
            type="text", text=json.dumps(result, ensure_ascii=False, default=str)
        )
    ][0]


def _public_tool_denied_response(name: str) -> dict[str, Any]:
    return {
        "status": "error",
        "summary": "Tool is not part of the public MCP surface.",
        "output": {"tool": name},
        "next_actions": [],
        "artifacts": [],
        "recovery_hint": (
            "Use tools/list and call one of the advertised public MCP tools."
        ),
        "primitive": name,
        "backend": "local",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": "",
    }


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run() -> None:
    # Match the CLI's env autoload so provider-readiness gates (for example
    # the illustration pending-fallback check) see the same configuration
    # here as `rh` commands do.
    from research_harness.env_bootstrap import ensure_default_env_loaded

    ensure_default_env_loaded()
    asyncio.run(main())


if __name__ == "__main__":
    run()
