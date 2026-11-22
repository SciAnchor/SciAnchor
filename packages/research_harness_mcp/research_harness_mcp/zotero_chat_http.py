"""FastAPI route registration for Zotero chat and match endpoints."""

from typing import Any, Callable

from fastapi import FastAPI, Request


def register_zotero_chat_routes(
    app: FastAPI,
    *,
    zotero_chat_request_model: type[Any],
    zotero_chat_item_context_model: type[Any],
    require_zotero_chat_token: Callable[[Request], None],
    get_db_context: Callable[[], Any],
    resolve_zotero_chat_match: Callable[[Any, Any], dict[str, Any]],
    build_zotero_codex_handoff_prompt: Callable[[Any, dict[str, Any]], str],
    build_zotero_chat_assistant_message: Callable[[Any, dict[str, Any]], str],
    zotero_context_payload: Callable[[Any, dict[str, Any]], dict[str, Any]],
    zotero_available_actions: Callable[
        [dict[str, Any], dict[str, Any]], list[dict[str, Any]]
    ],
    stable_zotero_chat_conversation_id: Callable[[Any, dict[str, Any]], str],
    zotero_chat_suggested_actions: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> None:
    """Register Zotero chat and item-match routes with injected dependencies."""

    @app.post("/api/zotero/chat")
    def zotero_chat(body: zotero_chat_request_model, request: Request):
        """Local Zotero side-panel bridge for RH-owned paper/topic conversations."""
        require_zotero_chat_token(request)
        with get_db_context() as conn:
            matched = resolve_zotero_chat_match(conn, body.item)

        prompt = build_zotero_codex_handoff_prompt(body, matched)
        assistant_message = build_zotero_chat_assistant_message(body, matched)
        context_payload = zotero_context_payload(body, matched)
        return {
            "status": "success",
            "summary": "Zotero chat request prepared",
            "output": {
                "conversation_id": body.conversation_id
                or stable_zotero_chat_conversation_id(body, matched),
                "matched": matched,
                "context": context_payload,
                "available_actions": zotero_available_actions(context_payload, matched),
                "assistant_message": assistant_message,
                "codex_handoff": {
                    "mode": "manual",
                    "prompt": prompt,
                    "hint": (
                        "复制该 prompt 到 Codex 终端，或后续接入 Codex "
                        "app-server/longtask 自动执行。"
                    ),
                },
                "suggested_actions": zotero_chat_suggested_actions(matched),
            },
        }

    @app.post("/api/zotero/match")
    def zotero_match(body: zotero_chat_item_context_model, request: Request):
        """Resolve a Zotero item to RH paper/topic context without starting chat."""
        require_zotero_chat_token(request)
        with get_db_context() as conn:
            matched = resolve_zotero_chat_match(conn, body)
        return {
            "status": "success",
            "summary": "Zotero item match resolved",
            "output": {
                "matched": matched,
            },
        }
