"""Dynamic tool handler helpers for Zotero Codex turns."""

from __future__ import annotations

from typing import Any, Callable


def zotero_codex_dynamic_tool_handler(
    *,
    body: Any,
    matched: dict[str, Any],
    context_payload: dict[str, Any],
    build_zotero_capability_broker: Callable[..., Any],
    zotero_capability_mode: Callable[[dict[str, Any]], str],
    normalize_zotero_codex_tool_name: Callable[..., str],
    coerce_codex_tool_arguments: Callable[[Any], dict[str, Any]],
    capability_result_cls: type,
    result_to_dynamic_tool_response: Callable[[Any], dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    broker = build_zotero_capability_broker(
        body=body,
        matched=matched,
        context_payload=context_payload,
    )
    broker_context = {
        "mode": zotero_capability_mode(context_payload),
        "matched": matched,
        "zotero_context": context_payload,
    }

    def handle(params: dict[str, Any]) -> dict[str, Any]:
        tool_name = normalize_zotero_codex_tool_name(
            params.get("tool"),
            namespace=params.get("namespace"),
        )
        if tool_name == "rh.capabilities.list":
            result = capability_result_cls(
                capability=tool_name,
                status="completed",
                success=True,
                message="Available RH Zotero capabilities",
                output={"capabilities": broker.list()},
            )
        else:
            arguments = coerce_codex_tool_arguments(params.get("arguments"))
            result = broker.invoke(tool_name, arguments, context=broker_context)
        activity = {
            "capability": result.capability or tool_name,
            "status": result.status,
            "message": result.message,
            "action_preview": result.action_preview,
            "receipt": result.receipt,
        }
        return {
            "response": result_to_dynamic_tool_response(result),
            "activity": {key: value for key, value in activity.items() if value},
        }

    return handle
