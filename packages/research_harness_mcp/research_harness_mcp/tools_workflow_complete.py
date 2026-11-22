"""Complete workflow MCP tools for pure CLI usage in Claude Code and Codex.

These tools enable users to perform entire research workflows without leaving
the Claude Code / Codex environment.
"""

from __future__ import annotations

from mcp.types import Tool

__all__ = ["_WORKFLOW_COMPLETE_TOOLS", "_execute_workflow_complete"]

_WORKFLOW_COMPLETE_TOOLS: dict[str, Tool] = {
    "topic_init": Tool(
        name="topic_init",
        description=(
            "Initialize a new research topic. Creates topic record in database "
            "and returns topic_id for subsequent operations."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Topic name (e.g., 'Temporal Graph Neural Networks')",
                },
                "description": {
                    "type": "string",
                    "description": "Optional detailed description",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for categorization",
                },
            },
            "required": ["name"],
        },
    ),
    "paper_production_start": Tool(
        name="paper_production_start",
        description=(
            "Start the paper production workflow for a topic. This initiates "
            "the full 6-stage process: init → build → analyze → propose → "
            "experiment → write. Returns workflow run ID and initial status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Topic ID from topic_init or topic_list",
                },
                "target_venue": {
                    "type": "string",
                    "description": "Target conference/journal (e.g., 'NeurIPS', 'ICML')",
                },
                "interaction_mode": {
                    "type": "string",
                    "enum": ["autonomous", "checkpoint", "interactive"],
                    "description": (
                        "autonomous: AI auto-decides; "
                        "checkpoint: pause at decisions (default); "
                        "interactive: AI can ask questions"
                    ),
                },
                "paper_mode": {
                    "type": "string",
                    "enum": ["main"],
                    "description": "main: real results expected",
                },
                "budget": {
                    "type": "number",
                    "description": "Max budget in USD (default: 100.0)",
                },
                "local_only": {
                    "type": "boolean",
                    "description": "Only use local papers, no external search",
                },
            },
            "required": ["topic_id", "target_venue"],
        },
    ),
    "paper_production_status": Tool(
        name="paper_production_status",
        description=(
            "Get detailed status of a running paper production workflow. "
            "Shows current stage, gate status, pending decisions, artifacts, "
            "cost, and next actions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Topic ID",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "topic_state": Tool(
        name="topic_state",
        description=(
            "Unified single-call topic introspection (rh.topic_state.v1): "
            "resolved DB path and competing state trees, orchestrator "
            "stage/gate, checkpoint state, pending human decision, blockers, "
            "and a computed next_action with runnable commands. Call this "
            "first when orienting on a topic."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Topic ID",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "paper_production_resume": Tool(
        name="paper_production_resume",
        description=(
            "Resume a paused paper production workflow. Use after making a "
            "decision or fixing blockers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Topic ID",
                },
                "auto_approve": {
                    "type": "boolean",
                    "description": "Temporarily use autonomous mode for this resume",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "paper_production_set_mode": Tool(
        name="paper_production_set_mode",
        description=(
            "Change interaction mode for a running workflow. Allows switching "
            "between autonomous, checkpoint, and interactive modes mid-workflow."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Topic ID",
                },
                "mode": {
                    "type": "string",
                    "enum": ["autonomous", "checkpoint", "interactive"],
                    "description": "New interaction mode",
                },
            },
            "required": ["topic_id", "mode"],
        },
    ),
    "paper_production_mode": Tool(
        name="paper_production_mode",
        description="Get current interaction mode for a topic's workflow.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Topic ID",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "paper_production_export": Tool(
        name="paper_production_export",
        description=(
            "Export generated paper and artifacts. Returns paths to generated "
            "LaTeX, PDF, figures, and intermediate artifacts."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Topic ID",
                },
                "format": {
                    "type": "string",
                    "enum": ["latex", "pdf", "both"],
                    "description": "Export format (default: both)",
                },
                "include_artifacts": {
                    "type": "boolean",
                    "description": "Include intermediate artifacts (proposals, analyses)",
                },
            },
            "required": ["topic_id"],
        },
    ),
}


def _execute_workflow_complete(name: str, arguments: dict) -> dict:
    """Execute complete workflow tools through the service dispatcher.

    These names are service-backed (see
    ``research_harness.service.registry``); this fallback keeps direct
    executor calls working with the same implementation.
    """
    from .tools_service_dispatch import _execute_service_backed_convenience

    if name not in _WORKFLOW_COMPLETE_TOOLS:
        return {
            "status": "error",
            "summary": f"Unknown tool: {name}",
            "output": {},
            "next_actions": [],
        }
    return _execute_service_backed_convenience(name, arguments)
