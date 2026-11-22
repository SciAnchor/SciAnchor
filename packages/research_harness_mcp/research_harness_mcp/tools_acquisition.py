"""MCP acquisition compatibility tool definitions and execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.types import Tool


def ingest_manual_downloads(db: Any) -> list[Any]:
    from research_harness.acquisition.pipeline import ingest_manual_downloads as _impl

    return _impl(db)


def backfill_pdf_paths(
    db: Any,
    *,
    topic_id: int | None,
    dry_run: bool,
) -> Any:
    from research_harness.acquisition.pdf_resolver import backfill_pdf_paths as _impl

    return _impl(db, topic_id=topic_id, dry_run=dry_run)


_ACQUISITION_TOOLS: dict[str, Tool] = {
    # NOTE: paper_acquire is registered as a primitive (PAPER_ACQUIRE_SPEC); do not re-declare here.
    "paper_ingest_manual": Tool(
        name="paper_ingest_manual",
        description="Ingest manually downloaded PDFs from the manual_downloads directory",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    "paper_resolve_pdfs": Tool(
        name="paper_resolve_pdfs",
        description="Discover existing PDFs on disk and link them to papers.pdf_path in the DB. Use this to fix papers that have PDFs downloaded but pdf_path is empty.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Topic ID to scope resolution (optional, resolves all if omitted)",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, report matches without writing to DB",
                    "default": False,
                },
            },
        },
    ),
}


def _execute_acquisition(
    name: str,
    arguments: dict[str, Any],
    *,
    db_resolver: Callable[[], Any],
) -> dict[str, Any]:
    """Execute an acquisition compatibility tool."""
    db = db_resolver()

    if name == "paper_ingest_manual":
        results = ingest_manual_downloads(db)
        return {"results": results, "count": len(results)}

    if name == "paper_resolve_pdfs":
        stats = backfill_pdf_paths(
            db,
            topic_id=arguments.get("topic_id"),
            dry_run=arguments.get("dry_run", False),
        )
        return stats.to_dict()

    return {"error": f"Unknown acquisition tool: {name}"}
