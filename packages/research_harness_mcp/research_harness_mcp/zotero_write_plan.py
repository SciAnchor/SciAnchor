"""Write-intent planning helpers for Zotero chat turns."""

from __future__ import annotations

from typing import Any, Callable


def plan_zotero_write_intent(
    *,
    body: Any,
    matched: dict[str, Any],
    context_payload: dict[str, Any],
    zotero_capability_mode: Callable[[dict[str, Any]], str],
    looks_like_zotero_create_collection_request: Callable[[str], bool],
    extract_zotero_create_collection_name: Callable[[str], str],
    looks_like_zotero_seed_search_request: Callable[[str], bool],
    extract_zotero_import_count: Callable[[str], int | None],
    zotero_seed_request_flags: Callable[[str], dict[str, bool]],
    zotero_explicit_seed_topic_name: Callable[[str], str],
    zotero_seed_search_query: Callable[..., str],
    zotero_attachment_target_source_for_plan: Callable[[Any, str], str],
    looks_like_zotero_pdf_attachment_request: Callable[[str], bool],
    looks_like_zotero_import_request: Callable[[str], bool],
    looks_like_unsupported_zotero_write_request: Callable[[str], bool],
    unsupported_zotero_write_message: Callable[[Any, dict[str, Any]], str],
) -> dict[str, Any]:
    """Map clear write intent to an allowlisted Zotero capability preview."""

    if str(body.requested_action_type or "").strip():
        return {"kind": "chat"}

    message = str(body.message or "").strip()
    if not message:
        return {"kind": "chat"}

    mode = zotero_capability_mode(context_payload)
    if looks_like_zotero_create_collection_request(message):
        name = extract_zotero_create_collection_name(message)
        if name:
            return {
                "kind": "capability_preview",
                "capability": "rh.zotero.create_collection",
                "arguments": {"collection_name": name},
            }

    if mode == "collection" and looks_like_zotero_seed_search_request(message):
        args: dict[str, Any] = {
            "count": extract_zotero_import_count(message) or 5,
            **zotero_seed_request_flags(message),
        }
        explicit_topic_name = zotero_explicit_seed_topic_name(message)
        if explicit_topic_name:
            args["topic_name"] = explicit_topic_name
            args["query"] = zotero_seed_search_query(
                body,
                topic_name=explicit_topic_name,
            )
        return {
            "kind": "capability_preview",
            "capability": "rh.zotero.prepare_seed_import",
            "arguments": args,
        }

    attachment_source = zotero_attachment_target_source_for_plan(body, mode)
    if looks_like_zotero_pdf_attachment_request(message) and (
        mode in {"item", "reader_selection"} or attachment_source
    ):
        return {
            "kind": "capability_preview",
            "capability": "rh.zotero.attach_pdf",
            "arguments": {"target_source": attachment_source}
            if attachment_source
            else {},
        }

    if looks_like_zotero_import_request(message):
        args = {}
        count = extract_zotero_import_count(message)
        if count is not None:
            args["limit"] = count
        return {
            "kind": "capability_preview",
            "capability": "rh.zotero.sync_papers",
            "arguments": args,
        }

    if looks_like_unsupported_zotero_write_request(message):
        return {
            "kind": "unsupported_write",
            "message": unsupported_zotero_write_message(body, matched),
        }

    return {"kind": "chat"}


def preview_zotero_write_plan(
    *,
    body: Any,
    matched: dict[str, Any],
    context_payload: dict[str, Any],
    plan: dict[str, Any],
    build_zotero_capability_broker: Callable[..., Any],
    zotero_capability_mode: Callable[[dict[str, Any]], str],
) -> Any:
    broker = build_zotero_capability_broker(
        body=body,
        matched=matched,
        context_payload=context_payload,
    )
    return broker.invoke(
        str(plan.get("capability") or ""),
        dict(plan.get("arguments") or {}),
        context={
            "mode": zotero_capability_mode(context_payload),
            "matched": matched,
            "zotero_context": context_payload,
        },
    )
