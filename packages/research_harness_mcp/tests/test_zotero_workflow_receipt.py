"""Focused tests for Zotero workflow receipt helper extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class _ObjectPushResult:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def to_dict(self) -> dict[str, Any]:
        return self._payload


@dataclass(frozen=True)
class _DataclassPushResult:
    planned_count: int
    synced_count: int
    skipped_count: int
    dry_run: bool
    topic_collection_key: str
    records: list[dict[str, Any]]
    papers: list[dict[str, Any]]


def _build_receipt(**overrides: Any) -> dict[str, Any]:
    from research_harness_mcp import zotero_workflow_receipt

    kwargs: dict[str, Any] = {
        "action_type": "sync_rh_papers_to_collection",
        "topic_id": 7,
        "topic_name": "agentic-zotero",
        "push_result": None,
        "target_collection_key": "TARGET1",
        "parent_collection_key": "PARENT1",
        "target_collection_name": "Agentic Zotero",
        "target_collection_path": "Research Harness / Agentic Zotero",
        "include_notes": True,
        "request_deep_read": False,
        "request_pdf_attachment": False,
        "request_pdf_annotations": False,
    }
    kwargs.update(overrides)
    return zotero_workflow_receipt.build_zotero_workflow_receipt(**kwargs)


def test_zotero_workflow_receipt_module_imports_and_http_api_preserves_aliases():
    from research_harness_mcp import http_api, zotero_workflow_receipt

    assert (
        http_api._build_zotero_workflow_receipt
        is zotero_workflow_receipt.build_zotero_workflow_receipt
    )
    assert (
        http_api._zotero_push_result_dict
        is zotero_workflow_receipt.zotero_push_result_dict
    )
    assert (
        http_api._zotero_workflow_receipt_summary
        is zotero_workflow_receipt.zotero_workflow_receipt_summary
    )
    assert (
        http_api._zotero_workflow_receipt_steps
        is zotero_workflow_receipt.zotero_workflow_receipt_steps
    )


def test_dry_run_sync_receipt_preserves_summary_counts_steps_and_items():
    receipt = _build_receipt(
        push_result={
            "planned_count": 2,
            "synced_count": 0,
            "skipped_count": 1,
            "dry_run": True,
            "topic_collection_key": "TOPICCOLL",
            "records": [
                {"paper_id": 1, "title": "Paper A", "deep_read": True},
                {"paper_id": 2, "title": "Paper B", "deep_read": False},
            ],
            "papers": [
                {
                    "paper_id": 1,
                    "title": "Paper A",
                    "action": "plan_create",
                    "zotero_item_key": "ITEM1",
                    "zotero_note_key": "NOTE1",
                }
            ],
        },
        request_deep_read=True,
    )

    assert receipt["schema"] == "rh-zotero-workflow-receipt/v1"
    assert receipt["action_type"] == "sync_rh_papers_to_collection"
    assert receipt["status"] == "dry_run"
    assert receipt["summary"] == "将同步 2 篇论文到 Zotero，等待确认。"
    assert receipt["target"]["collection_key"] == "TOPICCOLL"
    assert receipt["counts"]["papers_planned"] == 2
    assert receipt["counts"]["papers_synced"] == 0
    assert receipt["counts"]["papers_skipped"] == 1
    assert receipt["counts"]["deep_read_notes"] == 1
    assert receipt["items"] == [
        {
            "paper_id": 1,
            "title": "Paper A",
            "action": "plan_create",
            "zotero_item_key": "ITEM1",
            "zotero_note_key": "NOTE1",
        }
    ]
    assert any(
        step["key"] == "papers" and step["status"] == "pending" and step["count"] == 2
        for step in receipt["steps"]
    )
    assert any(
        step["key"] == "deep_read"
        and step["status"] == "partial"
        and step["count"] == 1
        for step in receipt["steps"]
    )


def test_dry_run_receipt_without_push_result_preserves_dry_run_status():
    receipt = _build_receipt(
        action_type="zotero_seed_paper_search",
        push_result=None,
        dry_run=True,
        target_collection_name="Seed Topic",
        ingest_errors=[{"source": "bad-source", "error": "provider down"}],
    )

    assert receipt["status"] == "dry_run"
    assert receipt["summary"] == "将同步 0 篇论文到 Zotero，等待确认。"
    assert receipt["counts"]["papers_planned"] == 0
    assert receipt["counts"]["failures"] == 1
    assert "入库失败：bad-source - provider down" in receipt["warnings"]


def test_seed_apply_completed_receipt_preserves_to_dict_push_result_and_pdf_counts():
    receipt = _build_receipt(
        action_type="zotero_seed_paper_search",
        push_result=_ObjectPushResult(
            {
                "planned_count": 2,
                "synced_count": 2,
                "skipped_count": 0,
                "dry_run": False,
                "topic_collection_key": "TOPICCOLL",
                "records": [
                    {"paper_id": 1, "deep_read": True, "has_pdf": True},
                    {"paper_id": 2, "deep_read": True, "has_pdf": True},
                ],
            }
        ),
        target_collection_name="Seed Topic",
        include_notes=True,
        request_deep_read=True,
        request_pdf_attachment=True,
        request_pdf_annotations=True,
        pdf_annotation_receipts=[
            {
                "status": "completed",
                "paper_id": 1,
                "title": "Paper A",
                "planned_count": 4,
                "applied_count": 3,
                "verified_count": 4,
                "missing_count": 0,
            }
        ],
    )

    assert receipt["status"] == "completed"
    assert (
        receipt["summary"]
        == "已创建/复用 topic 子文件夹“Seed Topic”，同步 2 篇论文，跳过 0 篇。"
    )
    assert receipt["counts"]["notes_written"] == 2
    assert receipt["counts"]["pdfs_attached"] == 2
    assert receipt["counts"]["pdf_annotations"] == 4
    assert receipt["counts"]["pdf_annotation_planned"] == 4
    assert receipt["counts"]["pdf_annotation_failures"] == 0
    assert receipt["warnings"] == []
    assert any(
        step["key"] == "pdf_attachment"
        and step["status"] == "completed"
        and step["count"] == 2
        for step in receipt["steps"]
    )
    assert any(
        step["key"] == "pdf_annotations"
        and step["status"] == "completed"
        and step["count"] == 4
        for step in receipt["steps"]
    )


def test_partial_receipt_preserves_dataclass_push_result_and_warning_aggregation():
    receipt = _build_receipt(
        push_result=_DataclassPushResult(
            planned_count=2,
            synced_count=1,
            skipped_count=1,
            dry_run=False,
            topic_collection_key="TOPICCOLL",
            records=[
                {"paper_id": 1, "deep_read": True, "has_pdf": True},
                {"paper_id": 2, "deep_read": False, "has_pdf": False},
            ],
            papers=[],
        ),
        request_pdf_attachment=True,
        request_pdf_annotations=True,
        ingest_errors=[{"source": "10.1234/demo", "error": "provider down"}],
        postprocess_errors=[{"step": "deep_read", "error": "timeout"}],
        pdf_annotation_receipts=[
            {
                "status": "partial",
                "paper_id": 2,
                "title": "Paper B",
                "planned_count": 3,
                "applied_count": 1,
                "missing_count": 2,
                "warning": "missing selectors",
            }
        ],
    )

    assert receipt["status"] == "partial"
    assert receipt["counts"]["notes_written"] == 1
    assert receipt["counts"]["pdfs_ready"] == 1
    assert receipt["counts"]["pdfs_attached"] == 1
    assert receipt["counts"]["pdfs_missing"] == 1
    assert receipt["counts"]["pdf_annotation_missing"] == 2
    assert receipt["counts"]["pdf_annotation_failures"] == 1
    assert receipt["counts"]["failures"] == 3
    assert "1 篇论文暂时没有可同步的本地 PDF。" in receipt["warnings"]
    assert "PDF 批注未完整完成：Paper B - missing selectors" in receipt["warnings"]
    assert "入库失败：10.1234/demo - provider down" in receipt["warnings"]
    assert "deep_read 未完成：timeout" in receipt["warnings"]
    assert any(
        step["key"] == "pdf_attachment"
        and step["status"] == "partial"
        and step["missing"] == 1
        for step in receipt["steps"]
    )
    assert any(
        step["key"] == "pdf_annotations"
        and step["status"] == "partial"
        and step["missing"] == 2
        and step["failures"] == 1
        for step in receipt["steps"]
    )
