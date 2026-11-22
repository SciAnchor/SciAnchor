"""MCP tools for human-in-the-loop decision making.

The implementations live in ``research_harness.auto_runner.hitl_commands`` so
the service layer and other transports share one code path; this module keeps
the MCP tool definitions and thin compatibility wrappers.
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool
from research_harness.auto_runner import hitl_commands
from research_harness.config import load_runtime_config
from research_harness.storage.db import Database


def paper_production_pending_decisions(topic_id: int) -> dict[str, Any]:
    """Get pending human decision requests for a paper-production workflow.

    Returns current waiting decisions with options, recommendations, and context.
    Works with both Claude Code and Codex.

    Args:
        topic_id: Research topic ID

    Returns:
        Schema: rh.pending_decisions.v1 with prompt, options, metadata
    """
    return hitl_commands.paper_production_pending_decisions(topic_id)


def paper_production_decide(
    topic_id: int,
    choice: str,
    reasoning: str = "",
) -> dict[str, Any]:
    """Record a human decision and resume paper-production workflow.

    Args:
        topic_id: Research topic ID
        choice: Selected action (must match one of the options from pending_decisions)
        reasoning: Human explanation for the choice

    Returns:
        Schema: rh.paper_production_decision.v1 with applied changes and next steps
    """
    config = load_runtime_config()
    db = Database(config.db_path)
    return hitl_commands.paper_production_decide(
        db,
        topic_id=topic_id,
        choice=choice,
        reasoning=reasoning,
        actor="mcp",
    )


def _execute_decision(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute decision tools.

    Args:
        name: Tool name
        arguments: Tool arguments

    Returns:
        Tool execution result
    """
    if name == "paper_production_pending_decisions":
        topic_id = arguments["topic_id"]
        return paper_production_pending_decisions(topic_id)
    elif name == "paper_production_decide":
        topic_id = arguments["topic_id"]
        choice = arguments["choice"]
        reasoning = arguments.get("reasoning", "")
        return paper_production_decide(topic_id, choice, reasoning)
    else:
        return {
            "status": "error",
            "summary": f"Unknown decision tool: {name}",
            "output": {},
            "next_actions": [],
        }


# MCP tool definitions
DECISION_TOOLS: list[Tool] = [
    Tool(
        name="paper_production_pending_decisions",
        description=(
            "Get pending human decision requests for a paper-production workflow. "
            "Returns structured decisions with AI recommendations, preference scores, "
            "and expected effects. Works with both Claude Code and Codex."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Research topic ID",
                },
            },
            "required": ["topic_id"],
        },
    ),
    Tool(
        name="paper_production_decide",
        description=(
            "Record a human decision and resume paper-production workflow. "
            "The choice must match one of the actions from pending_decisions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Research topic ID",
                },
                "choice": {
                    "type": "string",
                    "description": "Selected action (e.g., 'broaden_search', 'stop')",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Human explanation for the choice",
                    "default": "",
                },
            },
            "required": ["topic_id", "choice"],
        },
    ),
]
