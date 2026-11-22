"""Preview helpers for Zotero collection write actions."""

from __future__ import annotations

from typing import Any, Callable


def prepare_zotero_create_collection_action(
    body: Any,
    matched: dict[str, Any],
    *,
    looks_like_zotero_create_collection_request: Callable[[str], bool],
    zotero_context_payload: Callable[[Any, dict[str, Any]], dict[str, Any]],
    extract_zotero_create_collection_name: Callable[[str], str],
    normalize_zotero_library_id: Callable[[Any], str],
    finalize_zotero_action_preview: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    if not looks_like_zotero_create_collection_request(body.message):
        return None

    context = zotero_context_payload(body, matched)
    if context.get("kind") not in {"collection", "library"}:
        return {
            "kind": "assistant_message",
            "message": "要新建 Zotero 文件夹，请先在左侧选中父目录或文库位置。",
        }

    collection_name = extract_zotero_create_collection_name(body.message)
    if not collection_name:
        return {
            "kind": "assistant_message",
            "message": "我可以新建 Zotero 文件夹，但需要你明确文件夹名称，例如：新建文件夹“AI discovery”。",
        }

    directory_name = (
        body.item.current_directory_path or body.item.current_directory_name or ""
    ).strip()
    parent_collection_key = str(body.item.current_directory_key or "").strip()
    library_type = str(body.item.library_type or "user").strip() or "user"
    local_library_id = normalize_zotero_library_id(body.item.library_id)
    target_label = (
        f"{directory_name} / {collection_name}" if directory_name else collection_name
    )
    return {
        "kind": "action_preview",
        "preview": finalize_zotero_action_preview(
            {
                "action_type": "zotero_create_collection",
                "title": "新建 Zotero 文件夹",
                "message": (
                    f"我可以在"
                    f"{'当前目录“' + directory_name + '”下' if directory_name else '当前 Zotero 文库中'}"
                    f"新建文件夹“{collection_name}”。确认后会调用 Zotero 本地 Collection API。"
                ),
                "collection_name": collection_name,
                "source_label": "Zotero 本地目录",
                "target_label": target_label,
                "target_collection_name": collection_name,
                "parent_collection_key": parent_collection_key,
                "parent_collection_name": body.item.current_directory_name or "",
                "target_collection_path": target_label,
                "library_id": local_library_id,
                "library_type": library_type,
                "planned_count": 1,
                "count_label": "文件夹",
                "notice": "这是 Zotero 本地写入动作；先预览，确认后才创建 Collection。",
                "confirm_label": "确认新建",
                "cancel_label": "取消",
                "apply": {
                    "type": "zotero_local",
                    "handler": "zotero_create_collection",
                    "label": "确认新建",
                    "payload": {
                        "collection_name": collection_name,
                        "name": collection_name,
                        "parent_collection_key": parent_collection_key,
                        "library_id": local_library_id,
                        "library_type": library_type,
                    },
                },
            },
            capability="rh.zotero.create_collection",
            target_source="current_collection",
            target_record_count=1,
            writable_count=1,
            undo_supported=True,
        ),
    }
