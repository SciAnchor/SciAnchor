"""MCP Paperindex tool definitions and fallback execution."""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from research_harness.config import find_workspace_root


def PaperIndexer() -> Any:
    from paperindex import PaperIndexer as _PaperIndexer

    return _PaperIndexer()


_PAPERINDEX_TOOLS: dict[str, Tool] = {
    "paperindex_search": Tool(
        name="paperindex_search",
        description="Search the local paper library by keyword",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        },
    ),
    "paperindex_structure": Tool(
        name="paperindex_structure",
        description="Extract hierarchical structure from a PDF file",
        inputSchema={
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string", "description": "Path to PDF file"},
            },
            "required": ["pdf_path"],
        },
    ),
    "paperindex_card": Tool(
        name="paperindex_card",
        description="Build a comprehensive paper card from a PDF",
        inputSchema={
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string", "description": "Path to PDF file"},
            },
            "required": ["pdf_path"],
        },
    ),
}


def _execute_paperindex(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a Paperindex tool."""
    indexer = PaperIndexer()

    if name == "paperindex_search":
        ws = find_workspace_root()
        library_root = str(ws / ".paperindex") if ws else ".paperindex"
        results = indexer.search(
            arguments["query"],
            library_root=library_root,
            limit=arguments.get("limit", 5),
        )
        return {"results": [r.to_dict() for r in results]}

    if name == "paperindex_structure":
        structure = indexer.extract_structure(arguments["pdf_path"])
        return structure.to_dict()

    if name == "paperindex_card":
        record = indexer.build_record(arguments["pdf_path"])
        card = record.card or {}
        return card

    return {"error": f"Unknown paperindex tool: {name}"}
