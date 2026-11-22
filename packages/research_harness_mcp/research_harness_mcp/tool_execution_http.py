"""Private HTTP helpers for MCP tool execution wrappers."""

from __future__ import annotations

import traceback
from typing import Any, Callable, Protocol

from fastapi import HTTPException


class ErrorLogger(Protocol):
    def error(self, message: str, *args: Any) -> None: ...


def run_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    execute_tool_fn: Callable[[str, dict[str, Any]], dict[str, Any]],
    logger: ErrorLogger,
) -> dict[str, Any]:
    """Call execute_tool and translate failures into HTTP 500."""
    try:
        return execute_tool_fn(name, arguments)
    except Exception as exc:
        logger.error(
            "execute_tool(%s) failed: %s\n%s", name, exc, traceback.format_exc()
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
