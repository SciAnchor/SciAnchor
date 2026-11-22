"""Pure Zotero action preview helpers."""

from __future__ import annotations

import uuid
from typing import Any


def finalize_zotero_action_preview(
    preview: dict[str, Any],
    *,
    capability: str = "",
    target_source: str = "",
    target_record_count: int | None = None,
    writable_count: int | None = None,
    blocked_records: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    undo_supported: bool | None = None,
) -> dict[str, Any]:
    """Add additive review-card metadata while preserving legacy preview fields."""

    payload = dict(preview or {})
    action_type = str(payload.get("action_type") or "")
    if not payload.get("preview_id"):
        payload["preview_id"] = f"zotero-preview-{uuid.uuid4().hex[:12]}"
    if capability:
        payload.setdefault("capability", capability)
    if "target_set" not in payload:
        records = payload.get("records")
        record_count = (
            target_record_count
            if target_record_count is not None
            else len(records)
            if isinstance(records, list)
            else int(payload.get("planned_count") or 0)
        )
        blocked_count = len(blocked_records or [])
        payload["target_set"] = {
            "source": target_source or zotero_preview_target_source(action_type),
            "record_count": record_count,
            "writable_count": (
                writable_count
                if writable_count is not None
                else int(payload.get("planned_count") or 0)
            ),
            "blocked_count": blocked_count,
        }
    payload["warnings"] = unique_zotero_preview_warnings(
        [*list(payload.get("warnings") or []), *list(warnings or [])]
    )
    payload["blocked_records"] = list(
        blocked_records
        if blocked_records is not None
        else payload.get("blocked_records") or []
    )
    if undo_supported is None:
        undo_supported = action_type in {
            "zotero_attach_pdf",
            "zotero_create_collection",
            "zotero_write_note",
        }
    payload["undo_supported"] = bool(undo_supported)
    return payload


def zotero_preview_target_source(action_type: str) -> str:
    if action_type == "zotero_seed_paper_search":
        return "current_collection"
    if action_type == "sync_rh_papers_to_collection":
        return "current_topic"
    if action_type == "zotero_attach_pdf":
        return "current_item"
    if action_type == "zotero_create_collection":
        return "current_collection"
    return "zotero_context"


def unique_zotero_preview_warnings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text[:500])
        if len(cleaned) >= 20:
            break
    return cleaned


def zotero_available_actions(
    context: dict[str, Any], matched: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return mode-specific action descriptors for passive UI affordances."""

    kind = context.get("kind")
    paper = matched.get("paper") or {}
    topic = matched.get("topic") or {}
    directory = context.get("directory") or {}
    actions: list[dict[str, Any]] = []
    if kind == "paper":
        actions.append(
            {
                "action_type": "ask_rh_about_current_paper",
                "label": "围绕当前论文继续问 RH",
                "requires_preview": False,
                "paper_id": paper.get("id"),
                "topic_id": topic.get("id"),
            }
        )
        if paper.get("id"):
            actions.append(
                {
                    "action_type": "zotero_attach_pdf",
                    "label": "把 RH PDF 附加到当前 Zotero 条目",
                    "requires_preview": True,
                    "paper_id": paper.get("id"),
                    "topic_id": topic.get("id"),
                }
            )
        if paper.get("id") and directory.get("key"):
            actions.append(
                {
                    "action_type": "sync_current_paper_to_collection",
                    "label": "把当前 RH 论文同步到当前目录",
                    "requires_preview": True,
                    "paper_id": paper.get("id"),
                    "topic_id": topic.get("id"),
                    "target_collection_key": directory.get("key"),
                }
            )
        return actions

    actions.extend(
        [
            {
                "action_type": "init_topic_from_collection",
                "label": "从当前 Zotero 目录初始化 RH 主题",
                "requires_preview": True,
                "target_collection_key": directory.get("key"),
                "target_collection_name": directory.get("name"),
            },
            {
                "action_type": "sync_rh_missing_papers_to_collection",
                "label": "选择 RH 推荐/缺失论文补充到当前 Zotero 目录",
                "requires_preview": True,
                "target_collection_key": directory.get("key"),
                "target_collection_name": directory.get("name"),
            },
        ]
    )
    return actions
