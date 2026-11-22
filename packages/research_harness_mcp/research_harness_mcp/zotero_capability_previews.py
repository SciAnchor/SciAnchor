"""Preview adapters for Zotero capability broker write actions."""

from __future__ import annotations

from typing import Any, Callable

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


def zotero_preview_seed_import(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    args: dict[str, Any],
    last_zotero_path_segment: Callable[[str], str],
    coerce_zotero_capability_count: Callable[..., int],
    build_zotero_seed_papers_preview: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    topic_name = str(
        args.get("topic_name")
        or args.get("research_direction")
        or args.get("direction")
        or ""
    ).strip()
    query = str(args.get("query") or "").strip()
    if not topic_name and not query:
        topic_name = (
            last_zotero_path_segment(body.item.current_directory_path)
            or body.item.current_directory_name
            or ""
        ).strip()
        query = topic_name
    elif not topic_name:
        topic_name = query
    elif not query:
        query = topic_name
    count = coerce_zotero_capability_count(
        args.get("count") or args.get("max_results") or args.get("limit"),
        default=5,
    )
    request_pdf_annotations = bool(args.get("request_pdf_annotations"))
    request_pdf_attachment = bool(
        args.get("request_pdf_attachment") or request_pdf_annotations
    )
    request_flags = {
        "request_deep_read": bool(args.get("request_deep_read")),
        "request_pdf_attachment": request_pdf_attachment,
        "request_pdf_annotations": request_pdf_annotations,
    }
    return build_zotero_seed_papers_preview(
        body=body,
        matched=matched,
        topic_name=topic_name,
        query=query,
        requested_count=count,
        request_flags=request_flags,
    )


def zotero_preview_create_collection(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    args: dict[str, Any],
    prepare_zotero_create_collection_action: Callable[..., dict[str, Any] | None],
) -> dict[str, Any]:
    name = str(args.get("collection_name") or args.get("name") or "").strip()
    if not name:
        raise ValueError("collection_name is required")
    return (
        prepare_zotero_create_collection_action(
            body.model_copy(update={"message": f"新建文件夹“{name}”"}),
            matched,
        )
        or {}
    )


def zotero_preview_sync_papers(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    args: dict[str, Any],
    maybe_prepare_zotero_chat_action: Callable[..., dict[str, Any] | None],
) -> dict[str, Any]:
    update_message = "把这些论文导入当前目录"
    if args.get("topic_id"):
        update_message = f"把 topic id {int(args['topic_id'])} 的论文导入当前目录"
    if args.get("limit"):
        update_message = f"把前 {int(args['limit'])} 篇论文导入当前目录"
    return (
        maybe_prepare_zotero_chat_action(
            body.model_copy(
                update={
                    "message": update_message,
                    "requested_action_type": "sync_rh_papers_to_collection",
                }
            ),
            matched,
        )
        or {}
    )


def zotero_preview_attach_pdf(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    args: dict[str, Any],
    zotero_attachment_target_refs: Callable[..., list[Any]],
    prepare_zotero_pdf_attachment_action: Callable[..., dict[str, Any] | None],
) -> dict[str, Any]:
    target_source = str(args.get("target_source") or "").strip()
    return (
        prepare_zotero_pdf_attachment_action(
            body.model_copy(update={"message": "给当前条目附加 PDF"}),
            matched,
            target_refs=zotero_attachment_target_refs(body, target_source),
            target_source=target_source,
        )
        or {}
    )
