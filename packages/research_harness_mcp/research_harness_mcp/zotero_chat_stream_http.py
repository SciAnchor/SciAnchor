"""FastAPI route registration for Zotero chat streaming endpoint."""

import json
import logging
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse


logger = logging.getLogger(__name__)


def sse_encode(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def register_zotero_chat_stream_routes(
    app: FastAPI,
    *,
    zotero_chat_request_model: type[Any],
    require_zotero_chat_token: Callable[[Request], None],
    get_db_context: Callable[[], Any],
    resolve_zotero_chat_match: Callable[[Any, Any], dict[str, Any]],
    stable_zotero_chat_conversation_id: Callable[[Any, dict[str, Any]], str],
    zotero_codex_thread_store: Callable[[], Any],
    build_zotero_codex_turn_prompt: Callable[..., str],
    zotero_context_payload: Callable[[Any, dict[str, Any]], dict[str, Any]],
    zotero_available_actions: Callable[
        [dict[str, Any], dict[str, Any]], list[dict[str, Any]]
    ],
    zotero_chat_suggested_actions: Callable[[dict[str, Any]], list[dict[str, Any]]],
    plan_zotero_write_intent: Callable[..., dict[str, Any]],
    maybe_prepare_zotero_chat_action: Callable[
        [Any, dict[str, Any]], dict[str, Any] | None
    ],
    preview_zotero_write_plan: Callable[..., Any],
    stream_zotero_codex_turn: Callable[..., Any],
    save_zotero_codex_thread: Callable[..., None],
    maybe_prepare_zotero_codex_output_action: Callable[..., dict[str, Any] | None],
    extract_zotero_import_count: Callable[[str], int | None],
    sse_encode: Callable[[str, dict[str, Any]], str],
) -> None:
    """Register the stateful Zotero chat stream route."""

    @app.post("/api/zotero/chat/stream")
    def zotero_chat_stream(body: zotero_chat_request_model, request: Request):
        """Stream a real Codex app-server answer for the Zotero side panel."""

        require_zotero_chat_token(request)
        with get_db_context() as conn:
            matched = resolve_zotero_chat_match(conn, body.item)

        conversation_id = body.conversation_id or stable_zotero_chat_conversation_id(
            body, matched
        )
        store = zotero_codex_thread_store()
        existing_thread_id = store.get_thread_id(conversation_id)
        prompt = build_zotero_codex_turn_prompt(
            body,
            matched,
            is_followup=bool(existing_thread_id),
        )

        return StreamingResponse(
            _zotero_chat_sse_stream(
                body=body,
                matched=matched,
                conversation_id=conversation_id,
                existing_thread_id=existing_thread_id,
                prompt=prompt,
                store=store,
                zotero_context_payload=zotero_context_payload,
                zotero_available_actions=zotero_available_actions,
                zotero_chat_suggested_actions=zotero_chat_suggested_actions,
                plan_zotero_write_intent=plan_zotero_write_intent,
                maybe_prepare_zotero_chat_action=maybe_prepare_zotero_chat_action,
                preview_zotero_write_plan=preview_zotero_write_plan,
                stream_zotero_codex_turn=stream_zotero_codex_turn,
                save_zotero_codex_thread=save_zotero_codex_thread,
                maybe_prepare_zotero_codex_output_action=(
                    maybe_prepare_zotero_codex_output_action
                ),
                extract_zotero_import_count=extract_zotero_import_count,
                sse_encode=sse_encode,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


def _zotero_chat_sse_stream(
    *,
    body: Any,
    matched: dict[str, Any],
    conversation_id: str,
    existing_thread_id: str | None,
    prompt: str,
    store: Any,
    zotero_context_payload: Callable[[Any, dict[str, Any]], dict[str, Any]],
    zotero_available_actions: Callable[
        [dict[str, Any], dict[str, Any]], list[dict[str, Any]]
    ],
    zotero_chat_suggested_actions: Callable[[dict[str, Any]], list[dict[str, Any]]],
    plan_zotero_write_intent: Callable[..., dict[str, Any]],
    maybe_prepare_zotero_chat_action: Callable[
        [Any, dict[str, Any]], dict[str, Any] | None
    ],
    preview_zotero_write_plan: Callable[..., Any],
    stream_zotero_codex_turn: Callable[..., Any],
    save_zotero_codex_thread: Callable[..., None],
    maybe_prepare_zotero_codex_output_action: Callable[..., dict[str, Any] | None],
    extract_zotero_import_count: Callable[[str], int | None],
    sse_encode: Callable[[str, dict[str, Any]], str],
):
    full_text: list[str] = []
    current_thread_id = existing_thread_id
    action_preview_sent = False
    context_payload = zotero_context_payload(body, matched)
    available_actions = zotero_available_actions(context_payload, matched)
    yield sse_encode(
        "ready",
        {
            "conversation_id": conversation_id,
            "thread_id": current_thread_id,
            "model": body.model,
            "matched": matched,
            "context": context_payload,
            "available_actions": available_actions,
            "suggested_actions": zotero_chat_suggested_actions(matched),
        },
    )
    write_plan = plan_zotero_write_intent(
        body=body,
        matched=matched,
        context_payload=context_payload,
    )
    if str(body.requested_action_type or "").strip() or write_plan["kind"] in {
        "capability_preview",
        "unsupported_write",
    }:
        yield sse_encode(
            "status",
            {
                "conversation_id": conversation_id,
                "thread_id": current_thread_id,
                "model": body.model,
                "status": {
                    "type": "preparing_action_preview",
                    "message": "正在准备可确认的 Zotero 操作预览…",
                },
            },
        )
    action_response = maybe_prepare_zotero_chat_action(body, matched)
    if action_response is None and write_plan["kind"] == "capability_preview":
        capability_result = preview_zotero_write_plan(
            body=body,
            matched=matched,
            context_payload=context_payload,
            plan=write_plan,
        )
        if capability_result.action_preview is not None:
            action_response = {
                "kind": "action_preview",
                "preview": capability_result.action_preview,
            }
        elif capability_result.status == "assistant_message":
            action_response = {
                "kind": "assistant_message",
                "message": capability_result.message,
                "capability": capability_result.capability,
            }
        else:
            action_response = {
                "kind": "unsupported_write",
                "message": capability_result.message,
                "capability": capability_result.capability,
            }
    if action_response is None and write_plan["kind"] == "unsupported_write":
        action_response = {
            "kind": "unsupported_write",
            "message": write_plan["message"],
            "capability": None,
        }
    if action_response is not None:
        if action_response.get("kind") == "action_preview":
            preview_payload = dict(action_response["preview"])
            yield sse_encode("action_preview", preview_payload)
            yield sse_encode(
                "done",
                {
                    "conversation_id": conversation_id,
                    "thread_id": current_thread_id,
                    "model": body.model,
                    "assistant_message": preview_payload.get("message", ""),
                    "matched": matched,
                    "context": context_payload,
                    "available_actions": available_actions,
                    "action_preview": True,
                    "suggested_actions": zotero_chat_suggested_actions(matched),
                },
            )
            return
        if action_response.get("kind") == "unsupported_write":
            unsupported_payload = {
                "kind": "unsupported_write",
                "message": str(action_response.get("message") or ""),
                "capability": action_response.get("capability"),
                "available_actions": available_actions,
            }
            yield sse_encode("unsupported_write", unsupported_payload)
            yield sse_encode(
                "done",
                {
                    "conversation_id": conversation_id,
                    "thread_id": current_thread_id,
                    "model": body.model,
                    "assistant_message": unsupported_payload["message"],
                    "matched": matched,
                    "context": context_payload,
                    "available_actions": available_actions,
                    "action_preview": False,
                    "unsupported_write": True,
                    "suggested_actions": zotero_chat_suggested_actions(matched),
                },
            )
            return
        if action_response.get("kind") == "assistant_message":
            yield sse_encode(
                "done",
                {
                    "conversation_id": conversation_id,
                    "thread_id": current_thread_id,
                    "model": body.model,
                    "assistant_message": action_response.get("message", ""),
                    "matched": matched,
                    "context": context_payload,
                    "available_actions": available_actions,
                    "action_preview": False,
                    "suggested_actions": zotero_chat_suggested_actions(matched),
                },
            )
            return
    yield sse_encode(
        "status",
        {
            "conversation_id": conversation_id,
            "thread_id": current_thread_id,
            "model": body.model,
            "status": {
                "type": "warming",
                "message": "正在连接本地 Codex 通道…",
            },
        },
    )
    try:
        for event in stream_zotero_codex_turn(
            body=body,
            conversation_id=conversation_id,
            existing_thread_id=existing_thread_id,
            prompt=prompt,
            matched=matched,
            context_payload=context_payload,
            model=body.model,
            image_urls=body.item.screenshots,
        ):
            event_data = dict(event.data)
            thread_id = event_data.get("thread_id")
            if thread_id:
                current_thread_id = str(thread_id)
                save_zotero_codex_thread(
                    store=store,
                    conversation_id=conversation_id,
                    thread_id=current_thread_id,
                    matched=matched,
                    item=body.item,
                )
            if event.event == "delta":
                text = str(event_data.get("text") or "")
                if text:
                    full_text.append(text)
                yield sse_encode("delta", {"text": text})
            elif event.event == "reasoning":
                yield sse_encode(
                    "reasoning",
                    {
                        "kind": event_data.get("kind") or "summary",
                        "delta": str(event_data.get("delta") or ""),
                        "summary_index": event_data.get("summary_index"),
                        "content_index": event_data.get("content_index"),
                        "item_id": event_data.get("item_id"),
                    },
                )
            elif event.event == "done":
                assistant_text = "".join(full_text)
                if not action_preview_sent:
                    fallback_action = maybe_prepare_zotero_codex_output_action(
                        body=body,
                        matched=matched,
                        assistant_text=assistant_text,
                        context_payload=context_payload,
                    )
                    if (
                        fallback_action
                        and fallback_action.get("kind") == "action_preview"
                    ):
                        preview_payload = dict(fallback_action["preview"])
                        action_preview_sent = True
                        yield sse_encode(
                            "tool_call",
                            {
                                "tool": "rh.zotero.prepare_seed_import",
                                "capability": "rh.zotero.prepare_seed_import",
                                "arguments": {
                                    "count": extract_zotero_import_count(body.message)
                                    or 5,
                                },
                                "synthetic": True,
                            },
                        )
                        yield sse_encode(
                            "tool_result",
                            {
                                "tool": "rh.zotero.prepare_seed_import",
                                "capability": "rh.zotero.prepare_seed_import",
                                "success": True,
                                "status": "preview",
                                "message": preview_payload.get("message", ""),
                                "action_preview": preview_payload,
                                "synthetic": True,
                            },
                        )
                yield sse_encode(
                    "done",
                    {
                        "conversation_id": conversation_id,
                        "thread_id": current_thread_id,
                        "model": body.model,
                        "assistant_message": assistant_text,
                        "matched": matched,
                        "context": context_payload,
                        "available_actions": available_actions,
                        "action_preview": action_preview_sent,
                        "suggested_actions": zotero_chat_suggested_actions(matched),
                    },
                )
            elif event.event in {"started", "status"}:
                yield sse_encode(event.event, event_data)
            elif event.event in {
                "tool_call",
                "tool_result",
                "approval_request",
                "user_input_request",
                "command_output",
                "mcp_tool_progress",
            }:
                if event.event == "tool_result" and event_data.get("action_preview"):
                    action_preview_sent = True
                yield sse_encode(event.event, event_data)
    except Exception as exc:  # pragma: no cover - exact Codex failures vary by host
        logger.exception("Zotero Codex stream failed")
        yield sse_encode(
            "error",
            {
                "message": str(exc),
                "conversation_id": conversation_id,
                "thread_id": current_thread_id,
                "model": body.model,
            },
        )
