"""Dispatcher helpers for deterministic Zotero chat actions."""

from __future__ import annotations

from typing import Any, Callable


SEED_IMPORT_ACTION_TYPES = frozenset(
    {
        "zotero_seed_paper_search",
        "init_topic_from_collection",
        "rh.zotero.prepare_seed_import",
    }
)
DIRECTORY_CAPABILITY_ACTION_TYPES = frozenset(
    {"zotero_directory_capabilities", "available_actions"}
)


def maybe_prepare_zotero_chat_action(
    body: Any,
    matched: dict[str, Any],
    *,
    extract_zotero_import_count: Callable[[str], int | None],
    zotero_seed_request_flags: Callable[[str], dict[str, bool]],
    zotero_explicit_seed_topic_name: Callable[[str], str],
    zotero_seed_search_query: Callable[..., str],
    zotero_preview_seed_import: Callable[..., dict[str, Any]],
    zotero_context_payload: Callable[[Any, dict[str, Any]], dict[str, Any]],
    zotero_attachment_target_source_for_plan: Callable[[Any, str], str],
    zotero_attachment_target_refs: Callable[..., list[Any]],
    prepare_zotero_pdf_attachment_action: Callable[..., dict[str, Any] | None],
    prepare_zotero_create_collection_action: Callable[
        [Any, dict[str, Any]], dict[str, Any] | None
    ],
    zotero_available_actions: Callable[
        [dict[str, Any], dict[str, Any]], list[dict[str, Any]]
    ],
    sync_papers_action_types: frozenset[str],
    prepare_zotero_sync_papers_action: Callable[..., dict[str, Any] | None],
) -> dict[str, Any] | None:
    action_type = str(body.requested_action_type or "").strip()
    if not action_type:
        return None

    if action_type in SEED_IMPORT_ACTION_TYPES:
        seed_args: dict[str, Any] = {
            "count": extract_zotero_import_count(body.message) or 5,
            **zotero_seed_request_flags(body.message),
        }
        explicit_topic_name = zotero_explicit_seed_topic_name(body.message)
        if explicit_topic_name:
            seed_args["topic_name"] = explicit_topic_name
            seed_args["query"] = zotero_seed_search_query(
                body,
                topic_name=explicit_topic_name,
            )
        return zotero_preview_seed_import(
            body=body,
            matched=matched,
            args=seed_args,
        )

    if action_type == "zotero_attach_pdf":
        context_payload = zotero_context_payload(body, matched)
        target_source = zotero_attachment_target_source_for_plan(
            body,
            str(context_payload.get("kind") or ""),
        )
        return prepare_zotero_pdf_attachment_action(
            body,
            matched,
            target_refs=zotero_attachment_target_refs(
                body,
                target_source=target_source,
            ),
            target_source=target_source,
        )

    if action_type == "zotero_create_collection":
        return prepare_zotero_create_collection_action(body, matched)

    if action_type in DIRECTORY_CAPABILITY_ACTION_TYPES:
        context_payload = zotero_context_payload(body, matched)
        actions = zotero_available_actions(context_payload, matched)
        action_lines = "\n".join(
            f"- {action['label']}" for action in actions if action.get("label")
        )
        return {
            "kind": "assistant_message",
            "message": (
                "当前是 Zotero 目录/文库模式。我会把这里当作一个待初始化或待补全的 RH 入口，"
                "而不是套用单篇论文界面。\n\n"
                f"可用能力：\n{action_lines}"
            ),
        }

    if action_type not in sync_papers_action_types:
        return None

    return prepare_zotero_sync_papers_action(
        body,
        matched,
        action_type=action_type,
    )
