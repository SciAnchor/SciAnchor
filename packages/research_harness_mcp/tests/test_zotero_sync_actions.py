"""Focused tests for Zotero sync action helper extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


@dataclass(frozen=True)
class _SyncRecord:
    paper_id: int
    deep_read: bool = False


class _DbContext:
    def __init__(self, conn: object = "conn") -> None:
        self.conn = conn

    def __enter__(self) -> object:
        return self.conn

    def __exit__(self, *_args: object) -> None:
        return None


def _body(message: str = "把当前论文导入当前目录") -> ZoteroChatRequest:
    return ZoteroChatRequest.model_validate(
        {
            "message": message,
            "item": {
                "current_directory_key": "COLL1",
                "current_directory_name": "Agent Seeds",
                "current_directory_path": "Library / Agent Seeds",
                "library_id": "1",
                "library_type": "user",
            },
        }
    )


def test_zotero_sync_actions_module_imports_and_http_wrapper_exists():
    from research_harness_mcp import http_api, zotero_sync_actions

    assert callable(zotero_sync_actions.prepare_zotero_sync_papers_action)
    assert callable(http_api._prepare_zotero_sync_papers_action)


def test_prepare_zotero_sync_papers_action_ignores_unsupported_action_type():
    from research_harness_mcp.zotero_sync_actions import (
        prepare_zotero_sync_papers_action,
    )

    result = prepare_zotero_sync_papers_action(
        _body(),
        {},
        action_type="zotero_attach_pdf",
        get_db=lambda: _DbContext(),
        infer_zotero_import_topic=lambda _conn, _body, _matched: {"id": 1},
        load_topic_sync_records=lambda _conn, *, topic_name, limit=None: [],
        filter_sync_records_by_paper_ids=lambda records, paper_ids: records,
        record_preview=lambda record: {"paper_id": record.paper_id},
        message_targets_current_paper_only=lambda _message: False,
        message_targets_deep_read_only=lambda _message: False,
        extract_zotero_import_count=lambda _message: None,
        zotero_api_library_id=lambda value, library_type: str(value or ""),
        count_existing_zotero_collection_links=lambda *_args, **_kwargs: 0,
        finalize_zotero_action_preview=lambda payload, **_kwargs: payload,
    )

    assert result is None


def test_prepare_zotero_sync_papers_action_requires_directory_selection():
    from research_harness_mcp.zotero_sync_actions import (
        prepare_zotero_sync_papers_action,
    )

    body = ZoteroChatRequest.model_validate(
        {
            "message": "导入当前主题论文",
            "item": {"library_id": "1", "library_type": "user"},
        }
    )

    result = prepare_zotero_sync_papers_action(
        body,
        {},
        action_type="sync_rh_papers_to_collection",
        get_db=lambda: _DbContext(),
        infer_zotero_import_topic=lambda _conn, _body, _matched: {"id": 1},
        load_topic_sync_records=lambda _conn, *, topic_name, limit=None: [],
        filter_sync_records_by_paper_ids=lambda records, paper_ids: records,
        record_preview=lambda record: {"paper_id": record.paper_id},
        message_targets_current_paper_only=lambda _message: False,
        message_targets_deep_read_only=lambda _message: False,
        extract_zotero_import_count=lambda _message: None,
        zotero_api_library_id=lambda value, library_type: str(value or ""),
        count_existing_zotero_collection_links=lambda *_args, **_kwargs: 0,
        finalize_zotero_action_preview=lambda payload, **_kwargs: payload,
    )

    assert result == {
        "kind": "assistant_message",
        "message": "要把 RH 论文导入 Zotero，请先在左侧选中一个具体目录。",
    }


def test_prepare_zotero_sync_papers_action_requires_topic():
    from research_harness_mcp.zotero_sync_actions import (
        prepare_zotero_sync_papers_action,
    )

    result = prepare_zotero_sync_papers_action(
        _body(),
        {},
        action_type="rh.zotero.sync_papers",
        get_db=lambda: _DbContext(),
        infer_zotero_import_topic=lambda _conn, _body, _matched: None,
        load_topic_sync_records=lambda _conn, *, topic_name, limit=None: [],
        filter_sync_records_by_paper_ids=lambda records, paper_ids: records,
        record_preview=lambda record: {"paper_id": record.paper_id},
        message_targets_current_paper_only=lambda _message: False,
        message_targets_deep_read_only=lambda _message: False,
        extract_zotero_import_count=lambda _message: None,
        zotero_api_library_id=lambda value, library_type: str(value or ""),
        count_existing_zotero_collection_links=lambda *_args, **_kwargs: 0,
        finalize_zotero_action_preview=lambda payload, **_kwargs: payload,
    )

    assert result == {
        "kind": "assistant_message",
        "message": (
            "我还不知道该从哪个 RH 主题导入。请选中一篇已接入 RH 的论文，"
            "或在消息里明确主题名 / topic id。"
        ),
    }


def test_prepare_zotero_sync_papers_action_builds_filtered_preview_payload():
    from research_harness_mcp.zotero_sync_actions import (
        prepare_zotero_sync_papers_action,
    )

    records = [
        _SyncRecord(paper_id=3, deep_read=True),
        _SyncRecord(paper_id=7, deep_read=True),
        _SyncRecord(paper_id=9, deep_read=False),
    ]
    count_calls: list[dict[str, Any]] = []
    finalize_calls: list[dict[str, Any]] = []

    def filter_by_paper_ids(
        records: list[_SyncRecord], paper_ids: list[int]
    ) -> list[_SyncRecord]:
        return [record for record in records if record.paper_id in paper_ids]

    def count_existing(_conn: object, **kwargs: Any) -> int:
        count_calls.append(kwargs)
        return 1

    def finalize(payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        finalize_calls.append({"payload": payload, "kwargs": kwargs})
        return {**payload, "finalized": kwargs}

    result = prepare_zotero_sync_papers_action(
        _body("把当前论文前 1 篇导入当前目录"),
        {"paper": {"id": 7, "title": "Structured Agents"}},
        action_type="sync_current_paper_to_collection",
        get_db=lambda: _DbContext("db-conn"),
        infer_zotero_import_topic=lambda conn, _body, _matched: {
            "id": 5,
            "name": f"topic-from-{conn}",
        },
        load_topic_sync_records=lambda conn, *, topic_name, limit=None: records,
        filter_sync_records_by_paper_ids=filter_by_paper_ids,
        record_preview=lambda record: {
            "paper_id": record.paper_id,
            "deep_read": record.deep_read,
        },
        message_targets_current_paper_only=lambda _message: True,
        message_targets_deep_read_only=lambda _message: True,
        extract_zotero_import_count=lambda _message: 1,
        zotero_api_library_id=lambda value, library_type: f"api-{library_type}-{value}",
        count_existing_zotero_collection_links=count_existing,
        finalize_zotero_action_preview=finalize,
    )

    assert result is not None
    assert result["kind"] == "action_preview"
    preview = result["preview"]
    assert preview["action_type"] == "sync_rh_papers_to_collection"
    assert preview["topic_id"] == 5
    assert preview["source_label"] == "当前论文 · Structured Agents"
    assert preview["target_collection_key"] == "COLL1"
    assert preview["target_collection_path"] == "Library / Agent Seeds"
    assert preview["library_id"] == "api-user-1"
    assert preview["planned_count"] == 1
    assert preview["known_existing_count"] == 1
    assert preview["filter_label"] == "当前论文 · 前 1 篇"
    assert preview["paper_ids"] == [7]
    assert preview["records"] == [{"paper_id": 7, "deep_read": True}]
    assert preview["apply"]["path"] == "/api/topics/5/zotero-sync"
    assert preview["apply"]["payload"] == {
        "direction": "push",
        "dry_run": False,
        "paper_ids": [7],
        "target_collection_key": "COLL1",
        "target_collection_name": "Agent Seeds",
        "target_collection_path": "Library / Agent Seeds",
        "library_id": "api-user-1",
        "library_type": "user",
    }
    assert count_calls == [
        {
            "topic_id": 5,
            "target_collection_key": "COLL1",
            "library_id": "api-user-1",
            "library_type": "user",
            "paper_ids": [7],
        }
    ]
    assert finalize_calls[0]["kwargs"] == {
        "capability": "rh.zotero.sync_papers",
        "target_source": "current_topic",
        "target_record_count": 1,
        "writable_count": 1,
        "undo_supported": False,
    }
