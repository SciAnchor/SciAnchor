from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException


class _CapturingLogger:
    def __init__(self) -> None:
        self.errors: list[tuple[str, tuple[Any, ...]]] = []

    def error(self, message: str, *args: Any) -> None:
        self.errors.append((message, args))


def test_tool_execution_helper_preserves_http_api_wrapper(monkeypatch):
    from research_harness_mcp import http_api, tool_execution_http

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, arguments))
        return {"status": "ok", "name": name, "arguments": arguments}

    monkeypatch.setattr(http_api, "execute_tool", fake_execute_tool)

    assert http_api._run_tool("orchestrator_advance", {"topic_id": 9}) == (
        tool_execution_http.run_tool(
            "orchestrator_advance",
            {"topic_id": 9},
            execute_tool_fn=fake_execute_tool,
            logger=http_api.logger,
        )
    )
    assert calls == [
        ("orchestrator_advance", {"topic_id": 9}),
        ("orchestrator_advance", {"topic_id": 9}),
    ]


def test_run_tool_returns_execute_tool_result():
    from research_harness_mcp import tool_execution_http

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, arguments))
        return {"status": "success", "tool": name}

    assert tool_execution_http.run_tool(
        "paper_search",
        {"query": "agent benchmark"},
        execute_tool_fn=fake_execute_tool,
        logger=_CapturingLogger(),
    ) == {"status": "success", "tool": "paper_search"}
    assert calls == [("paper_search", {"query": "agent benchmark"})]


def test_run_tool_maps_exceptions_to_http_500_and_logs_traceback():
    from research_harness_mcp import tool_execution_http

    logger = _CapturingLogger()

    def broken_execute_tool(_name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("backend unavailable")

    with pytest.raises(HTTPException) as exc_info:
        tool_execution_http.run_tool(
            "orchestrator_resume",
            {"topic_id": 11},
            execute_tool_fn=broken_execute_tool,
            logger=logger,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "backend unavailable"
    assert len(logger.errors) == 1
    message, args = logger.errors[0]
    assert message == "execute_tool(%s) failed: %s\n%s"
    assert args[0] == "orchestrator_resume"
    assert isinstance(args[1], RuntimeError)
    assert "RuntimeError: backend unavailable" in args[2]
