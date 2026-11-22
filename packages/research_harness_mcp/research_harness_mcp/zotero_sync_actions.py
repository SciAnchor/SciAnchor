"""Preview helpers for syncing RH papers into Zotero collections."""

from __future__ import annotations

from typing import Any, Callable


SYNC_PAPERS_ACTION_TYPES = frozenset(
    {
        "sync_rh_papers_to_collection",
        "sync_current_paper_to_collection",
        "sync_rh_missing_papers_to_collection",
        "rh.zotero.sync_papers",
    }
)


def prepare_zotero_sync_papers_action(
    body: Any,
    matched: dict[str, Any],
    *,
    action_type: str,
    get_db: Callable[[], Any],
    infer_zotero_import_topic: Callable[
        [Any, Any, dict[str, Any]], dict[str, Any] | None
    ],
    load_topic_sync_records: Callable[..., list[Any]],
    filter_sync_records_by_paper_ids: Callable[[list[Any], list[int]], list[Any]],
    record_preview: Callable[[Any], dict[str, Any]],
    message_targets_current_paper_only: Callable[[str], bool],
    message_targets_deep_read_only: Callable[[str], bool],
    extract_zotero_import_count: Callable[[str], int | None],
    zotero_api_library_id: Callable[[Any, str], str],
    count_existing_zotero_collection_links: Callable[..., int],
    finalize_zotero_action_preview: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    if action_type not in SYNC_PAPERS_ACTION_TYPES:
        return None

    directory_name = (
        body.item.current_directory_path or body.item.current_directory_name or ""
    ).strip()
    if not directory_name or not str(body.item.current_directory_key or "").strip():
        return {
            "kind": "assistant_message",
            "message": "要把 RH 论文导入 Zotero，请先在左侧选中一个具体目录。",
        }

    with get_db() as conn:
        topic = infer_zotero_import_topic(conn, body, matched)
        if topic is None:
            return {
                "kind": "assistant_message",
                "message": (
                    "我还不知道该从哪个 RH 主题导入。请选中一篇已接入 RH 的论文，"
                    "或在消息里明确主题名 / topic id。"
                ),
            }

        records = load_topic_sync_records(conn, topic_name=topic["name"], limit=None)
        current_paper_only = message_targets_current_paper_only(body.message)
        matched_paper = matched.get("paper") or {}
        if current_paper_only and matched_paper.get("id"):
            records = filter_sync_records_by_paper_ids(
                records,
                [int(matched_paper["id"])],
            )

        deep_read_only = message_targets_deep_read_only(body.message)
        if deep_read_only:
            records = [record for record in records if record.deep_read]

        requested_count = extract_zotero_import_count(body.message)
        if requested_count is not None:
            records = records[:requested_count]

        if not records:
            if current_paper_only:
                return {
                    "kind": "assistant_message",
                    "message": "当前论文不在可导入范围内，或还没有关联到这个 RH 主题。",
                }
            if deep_read_only:
                return {
                    "kind": "assistant_message",
                    "message": f"主题“{topic['name']}”下暂时没有满足条件的精读论文可导入。",
                }
            return {
                "kind": "assistant_message",
                "message": f"主题“{topic['name']}”下暂时没有可导入论文。",
            }

        paper_ids = [record.paper_id for record in records]
        library_type = str(body.item.library_type or "user").strip() or "user"
        library_id = zotero_api_library_id(body.item.library_id, library_type)
        known_existing_count = count_existing_zotero_collection_links(
            conn,
            topic_id=int(topic["id"]),
            target_collection_key=body.item.current_directory_key,
            library_id=library_id,
            library_type=library_type,
            paper_ids=paper_ids,
        )
        filter_bits: list[str] = []
        if current_paper_only:
            filter_bits.append("当前论文")
        elif deep_read_only:
            filter_bits.append("仅精读")
        if requested_count is not None:
            filter_bits.append(f"前 {requested_count} 篇")
        filter_label = " · ".join(filter_bits)
        source_label = (
            f"当前论文 · {matched_paper.get('title', '')}".strip(" ·")
            if current_paper_only and matched_paper.get("title")
            else f"RH 主题 · {topic['name']}"
        )
        summary_scope = (
            f"当前论文《{matched_paper.get('title', '')}》"
            if current_paper_only and matched_paper.get("title")
            else f"主题“{topic['name']}”"
        )
        summary_filters = []
        if deep_read_only:
            summary_filters.append("精读")
        if requested_count is not None:
            summary_filters.append(f"{len(records)} 篇")
        elif len(records) == 1:
            summary_filters.append("1 篇")
        filter_text = f"（{'，'.join(summary_filters)}）" if summary_filters else ""
        return {
            "kind": "action_preview",
            "preview": finalize_zotero_action_preview(
                {
                    "action_type": "sync_rh_papers_to_collection",
                    "title": "导入到当前目录",
                    "message": (
                        f"我可以把 {summary_scope}{filter_text} 导入当前目录“{directory_name}”。"
                        "确认后我会直接执行。"
                    ),
                    "topic_id": int(topic["id"]),
                    "source_label": source_label,
                    "target_collection_key": body.item.current_directory_key,
                    "target_collection_name": body.item.current_directory_name
                    or directory_name,
                    "target_collection_path": directory_name,
                    "target_label": directory_name,
                    "library_id": library_id,
                    "library_type": library_type,
                    "planned_count": len(records),
                    "known_existing_count": known_existing_count,
                    "filter_label": filter_label,
                    "paper_ids": paper_ids,
                    "records": [record_preview(record) for record in records],
                    "notice": "将写入当前 Zotero 目录，并保留 RH 标签与来源映射。",
                    "confirm_label": "确认导入",
                    "cancel_label": "取消",
                    "list_label": "查看清单",
                    "apply": {
                        "type": "http_json",
                        "method": "POST",
                        "path": f"/api/topics/{int(topic['id'])}/zotero-sync",
                        "label": "确认导入",
                        "payload": {
                            "direction": "push",
                            "dry_run": False,
                            "paper_ids": paper_ids,
                            "target_collection_key": body.item.current_directory_key,
                            "target_collection_name": (
                                body.item.current_directory_name or directory_name
                            ),
                            "target_collection_path": directory_name,
                            "library_id": library_id,
                            "library_type": library_type,
                        },
                    },
                },
                capability="rh.zotero.sync_papers",
                target_source="current_topic",
                target_record_count=len(records),
                writable_count=len(records),
                undo_supported=False,
            ),
        }
