"""Focused tests for Zotero Codex dynamic tool handler extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


@dataclass
class _Result:
    capability: str
    status: str
    message: str
    success: bool = True
    output: dict[str, Any] | None = None
    action_preview: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None


def _body() -> ZoteroChatRequest:
    return ZoteroChatRequest.model_validate(
        {
            "message": "use a tool",
            "item": {
                "zotero_item_key": "ITEM1",
                "current_directory_key": "COLL1",
                "current_directory_name": "Agent Seeds",
                "current_directory_path": "Library / Agent Seeds",
            },
        }
    )


def test_zotero_codex_dynamic_tools_module_imports_and_http_wrapper_exists():
    from research_harness_mcp import http_api, zotero_codex_dynamic_tools

    assert callable(zotero_codex_dynamic_tools.zotero_codex_dynamic_tool_handler)
    assert callable(http_api._zotero_codex_dynamic_tool_handler)


def test_zotero_codex_dynamic_tool_handler_lists_capabilities():
    from research_harness_mcp.zotero_codex_dynamic_tools import (
        zotero_codex_dynamic_tool_handler,
    )

    class Broker:
        def list(self) -> list[dict[str, str]]:
            return [{"name": "rh.paper.list"}]

        def invoke(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("list path should not invoke a capability")

    converted: list[_Result] = []
    handler = zotero_codex_dynamic_tool_handler(
        body=_body(),
        matched={"source": "directory"},
        context_payload={"kind": "collection"},
        build_zotero_capability_broker=lambda **_kwargs: Broker(),
        zotero_capability_mode=lambda context: context["kind"],
        normalize_zotero_codex_tool_name=lambda tool, *, namespace=None: (
            f"{namespace}.{tool}" if namespace else str(tool)
        ),
        coerce_codex_tool_arguments=lambda _value: {"should": "not-run"},
        capability_result_cls=_Result,
        result_to_dynamic_tool_response=lambda result: (
            converted.append(result)
            or {
                "capability": result.capability,
                "output": result.output,
            }
        ),
    )

    result = handler({"namespace": "rh.capabilities", "tool": "list"})

    assert result == {
        "response": {
            "capability": "rh.capabilities.list",
            "output": {"capabilities": [{"name": "rh.paper.list"}]},
        },
        "activity": {
            "capability": "rh.capabilities.list",
            "status": "completed",
            "message": "Available RH Zotero capabilities",
        },
    }
    assert converted == [
        _Result(
            capability="rh.capabilities.list",
            status="completed",
            success=True,
            message="Available RH Zotero capabilities",
            output={"capabilities": [{"name": "rh.paper.list"}]},
        )
    ]


def test_zotero_codex_dynamic_tool_handler_invokes_broker_and_filters_activity():
    from research_harness_mcp.zotero_codex_dynamic_tools import (
        zotero_codex_dynamic_tool_handler,
    )

    calls: list[dict[str, Any]] = []

    class Broker:
        def list(self) -> list[dict[str, str]]:
            return []

        def invoke(
            self,
            tool_name: str,
            arguments: dict[str, Any],
            *,
            context: dict[str, Any],
        ) -> _Result:
            calls.append(
                {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "context": context,
                }
            )
            return _Result(
                capability="rh.zotero.attach_pdf",
                status="preview",
                message="ready",
                action_preview={"action_type": "zotero_attach_pdf"},
            )

    body = _body()
    matched = {"paper": {"id": 9}}
    context_payload = {"kind": "item", "item_key": "ITEM1"}
    handler = zotero_codex_dynamic_tool_handler(
        body=body,
        matched=matched,
        context_payload=context_payload,
        build_zotero_capability_broker=lambda **kwargs: (
            calls.append({"broker_kwargs": kwargs}) or Broker()
        ),
        zotero_capability_mode=lambda context: context["kind"],
        normalize_zotero_codex_tool_name=lambda tool, *, namespace=None: (
            f"{namespace}.{tool}" if namespace else str(tool)
        ),
        coerce_codex_tool_arguments=lambda value: {"coerced": value},
        capability_result_cls=_Result,
        result_to_dynamic_tool_response=lambda result: {
            "capability": result.capability,
            "status": result.status,
        },
    )

    result = handler(
        {
            "namespace": "rh.zotero",
            "tool": "attach_pdf",
            "arguments": {"target_source": "last_preview"},
        }
    )

    assert result == {
        "response": {
            "capability": "rh.zotero.attach_pdf",
            "status": "preview",
        },
        "activity": {
            "capability": "rh.zotero.attach_pdf",
            "status": "preview",
            "message": "ready",
            "action_preview": {"action_type": "zotero_attach_pdf"},
        },
    }
    assert calls == [
        {
            "broker_kwargs": {
                "body": body,
                "matched": matched,
                "context_payload": context_payload,
            }
        },
        {
            "tool_name": "rh.zotero.attach_pdf",
            "arguments": {"coerced": {"target_source": "last_preview"}},
            "context": {
                "mode": "item",
                "matched": matched,
                "zotero_context": context_payload,
            },
        },
    ]
