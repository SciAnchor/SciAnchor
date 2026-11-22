"""Zotero workflow receipt construction helpers."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def build_zotero_workflow_receipt(
    *,
    action_type: str,
    topic_id: int | None,
    topic_name: str,
    push_result: Any,
    target_collection_key: str | None,
    parent_collection_key: str | None,
    target_collection_name: str,
    target_collection_path: str,
    include_notes: bool,
    request_deep_read: bool,
    request_pdf_attachment: bool,
    request_pdf_annotations: bool,
    dry_run: bool | None = None,
    ingest_errors: list[dict[str, str]] | None = None,
    postprocess_errors: list[dict[str, str]] | None = None,
    postprocess_warnings: list[str] | None = None,
    pdf_annotation_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    push = zotero_push_result_dict(push_result)
    records = list(push.get("records") or [])
    papers = list(push.get("papers") or [])
    planned = int(push.get("planned_count") or len(records) or 0)
    synced = int(push.get("synced_count") or 0)
    skipped = int(push.get("skipped_count") or 0)
    dry_run = bool(push.get("dry_run")) if dry_run is None and push else bool(dry_run)
    deep_read_notes = len([r for r in records if bool(r.get("deep_read"))])
    pdf_ready = len([r for r in records if bool(r.get("has_pdf"))])
    pdf_missing = max(planned - pdf_ready, 0)
    annotation_receipts = list(pdf_annotation_receipts or [])
    pdf_annotation_planned = sum(
        int(item.get("planned_count") or 0)
        for item in annotation_receipts
        if isinstance(item, dict)
    )
    pdf_annotations = sum(
        int(item.get("verified_count") or item.get("applied_count") or 0)
        for item in annotation_receipts
        if isinstance(item, dict)
    )
    pdf_annotation_missing = sum(
        int(item.get("missing_count") or 0)
        for item in annotation_receipts
        if isinstance(item, dict)
    )
    pdf_annotation_failures = len(
        [
            item
            for item in annotation_receipts
            if isinstance(item, dict)
            and str(item.get("status") or "") not in {"completed"}
        ]
    )
    error_count = (
        len(ingest_errors or [])
        + len(postprocess_errors or [])
        + pdf_annotation_failures
    )
    notes_written = synced if include_notes and not dry_run and push else 0
    pdfs_attached = (
        min(pdf_ready, synced) if request_pdf_attachment and not dry_run and push else 0
    )

    if dry_run:
        status = "dry_run"
    elif error_count:
        status = "partial"
    elif request_pdf_attachment and pdf_missing:
        status = "partial"
    elif request_pdf_annotations and (
        not annotation_receipts or pdf_annotation_missing > 0
    ):
        status = "partial"
    else:
        status = "completed"

    collection_key = str(
        push.get("topic_collection_key") or target_collection_key or ""
    )
    warnings: list[str] = []
    if request_pdf_attachment and pdf_missing:
        warnings.append(f"{pdf_missing} 篇论文暂时没有可同步的本地 PDF。")
    if request_pdf_annotations and not annotation_receipts and not dry_run:
        warnings.append("PDF 高亮/批注没有执行成功，未写入完成计数。")
    for receipt in annotation_receipts:
        if not isinstance(receipt, dict):
            continue
        receipt_status = str(receipt.get("status") or "")
        if receipt_status == "completed":
            continue
        title = str(receipt.get("title") or f"paper #{receipt.get('paper_id', '?')}")
        error = str(receipt.get("error") or receipt.get("warning") or "")
        if error:
            warnings.append(f"PDF 批注未完整完成：{title} - {error}")
        else:
            warnings.append(f"PDF 批注未完整完成：{title}")
    for error in ingest_errors or []:
        source = error.get("source") or "unknown source"
        warnings.append(f"入库失败：{source} - {error.get('error', '')}")
    for error in postprocess_errors or []:
        step = error.get("step") or "postprocess"
        warnings.append(f"{step} 未完成：{error.get('error', '')}")
    warnings.extend(str(warning) for warning in postprocess_warnings or [])

    return {
        "schema": "rh-zotero-workflow-receipt/v1",
        "action_type": action_type,
        "status": status,
        "summary": zotero_workflow_receipt_summary(
            action_type=action_type,
            status=status,
            planned=planned,
            synced=synced,
            skipped=skipped,
            target_collection_name=target_collection_name,
        ),
        "target": {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "collection_key": collection_key,
            "collection_name": target_collection_name,
            "collection_path": target_collection_path,
            "parent_collection_key": str(parent_collection_key or ""),
        },
        "counts": {
            "papers_planned": planned,
            "papers_synced": synced,
            "papers_skipped": skipped,
            "notes_written": notes_written,
            "deep_read_notes": deep_read_notes,
            "pdfs_ready": pdf_ready,
            "pdfs_attached": pdfs_attached,
            "pdfs_missing": pdf_missing,
            "pdf_annotations": pdf_annotations,
            "pdf_annotation_planned": pdf_annotation_planned,
            "pdf_annotation_missing": pdf_annotation_missing,
            "pdf_annotation_failures": pdf_annotation_failures,
            "failures": error_count,
        },
        "requested": {
            "deep_read": bool(request_deep_read),
            "pdf_attachment": bool(request_pdf_attachment),
            "pdf_annotations": bool(request_pdf_annotations),
        },
        "steps": zotero_workflow_receipt_steps(
            planned=planned,
            synced=synced,
            skipped=skipped,
            notes_written=notes_written,
            deep_read_notes=deep_read_notes,
            request_deep_read=request_deep_read,
            request_pdf_attachment=request_pdf_attachment,
            request_pdf_annotations=request_pdf_annotations,
            pdfs_attached=pdfs_attached,
            pdf_missing=pdf_missing,
            pdf_annotations=pdf_annotations,
            pdf_annotation_planned=pdf_annotation_planned,
            pdf_annotation_missing=pdf_annotation_missing,
            pdf_annotation_failures=pdf_annotation_failures,
            dry_run=dry_run,
            error_count=error_count,
        ),
        "items": [
            {
                "paper_id": paper.get("paper_id"),
                "title": paper.get("title") or "",
                "action": paper.get("action") or "",
                "zotero_item_key": paper.get("zotero_item_key") or "",
                "zotero_note_key": paper.get("zotero_note_key") or "",
            }
            for paper in papers[:50]
            if isinstance(paper, dict)
        ],
        "annotation_receipts": annotation_receipts[:50],
        "warnings": warnings,
    }


def build_zotero_phase_b_gate_evidence(
    *,
    action_type: str,
    topic_id: int | None,
    topic_name: str,
    direction: str,
    dry_run: bool,
    sandbox_adapter: bool,
    push_preview: Any = None,
    pull_preview: Any = None,
    push_result: Any = None,
    pull_result: Any = None,
    workflow_receipt: dict[str, Any] | None = None,
    candidate_sources_count: int | None = None,
    paper_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Build local Phase B evidence without exposing credentials or debug data."""

    push_preview_payload = _compact_zotero_push_result(push_preview)
    pull_preview_payload = _compact_zotero_pull_result(pull_preview)
    push_receipt_payload = _compact_zotero_push_result(push_result)
    pull_receipt_payload = _compact_zotero_pull_result(pull_result)
    requires_sandbox = (not dry_run) or direction in {"pull", "both"}
    mode = (
        "fake_sandbox"
        if sandbox_adapter
        else "dry_run_no_client"
        if dry_run and not requires_sandbox
        else "blocked_real"
    )
    stages = []
    if push_preview_payload:
        stages.append("push_preview")
    if pull_preview_payload:
        stages.append("pull_preview")
    if push_receipt_payload:
        stages.append("push_apply" if not dry_run else "push_dry_run")
    if pull_receipt_payload:
        stages.append("pull_apply" if not dry_run else "pull_dry_run")

    receipt_status = ""
    if workflow_receipt:
        receipt_status = str(workflow_receipt.get("status") or "")
    elif dry_run:
        receipt_status = "dry_run"
    elif push_receipt_payload or pull_receipt_payload:
        receipt_status = "completed"

    intent_plan: dict[str, Any] = {
        "action_type": action_type,
        "topic_id": topic_id,
        "topic_name": topic_name,
        "direction": direction,
        "dry_run": dry_run,
        "sandbox_required": requires_sandbox,
        "sandbox_adapter": sandbox_adapter,
        "stages": stages,
    }
    if candidate_sources_count is not None:
        intent_plan["candidate_sources_count"] = candidate_sources_count
    if paper_ids is not None:
        intent_plan["paper_ids"] = [int(paper_id) for paper_id in paper_ids[:50]]

    return {
        "schema": "rh-zotero-phase-b-gate-evidence/v1",
        "mode": mode,
        "intent_plan": intent_plan,
        "preview": {
            "push": push_preview_payload or None,
            "pull": pull_preview_payload or None,
        },
        "receipt": {
            "workflow_schema": str(workflow_receipt.get("schema") or "")
            if workflow_receipt
            else "",
            "workflow_status": receipt_status,
            "push": push_receipt_payload or None,
            "pull": pull_receipt_payload or None,
        },
        "rollback_recovery": {
            "automatic_rollback": False,
            "external_writes": "fake_sandbox_only" if sandbox_adapter else "none",
            "local_recovery_tables": [
                "zotero_item_links",
                "zotero_import_links",
                "topic_paper_notes",
            ],
            "recovery_hint": (
                "Phase B execution is limited to fake/sandbox adapters. For local "
                "recovery, reset the sandbox adapter state and remove RH Zotero "
                "link/import rows produced by the receipt before rerunning. Real "
                "Zotero rollback remains deferred until a separately authorized "
                "network sync/apply gate."
            ),
        },
    }


def zotero_push_result_dict(push_result: Any) -> dict[str, Any]:
    if push_result is None:
        return {}
    if isinstance(push_result, dict):
        return push_result
    to_dict = getattr(push_result, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    if is_dataclass(push_result):
        return dict(asdict(push_result))
    return {}


def zotero_pull_result_dict(pull_result: Any) -> dict[str, Any]:
    if pull_result is None:
        return {}
    if isinstance(pull_result, dict):
        return pull_result
    to_dict = getattr(pull_result, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    if is_dataclass(pull_result):
        return dict(asdict(pull_result))
    return {}


def _compact_zotero_push_result(push_result: Any) -> dict[str, Any]:
    push = zotero_push_result_dict(push_result)
    if not push:
        return {}
    records = [
        item for item in list(push.get("records") or []) if isinstance(item, dict)
    ]
    papers = [item for item in list(push.get("papers") or []) if isinstance(item, dict)]
    return {
        "dry_run": bool(push.get("dry_run")),
        "planned_count": int(push.get("planned_count") or len(records) or 0),
        "synced_count": int(push.get("synced_count") or 0),
        "skipped_count": int(push.get("skipped_count") or 0),
        "records": records[:10],
        "papers": [
            {
                "paper_id": paper.get("paper_id"),
                "title": paper.get("title") or "",
                "action": paper.get("action") or "",
                "zotero_item_key": paper.get("zotero_item_key") or "",
                "zotero_note_key": paper.get("zotero_note_key") or "",
            }
            for paper in papers[:10]
        ],
    }


def _compact_zotero_pull_result(pull_result: Any) -> dict[str, Any]:
    pull = zotero_pull_result_dict(pull_result)
    if not pull:
        return {}
    items = [item for item in list(pull.get("items") or []) if isinstance(item, dict)]
    return {
        "dry_run": bool(pull.get("dry_run")),
        "planned_count": int(pull.get("planned_count") or 0),
        "imported_count": int(pull.get("imported_count") or 0),
        "skipped_count": int(pull.get("skipped_count") or 0),
        "items": [
            {
                "paper_id": item.get("paper_id"),
                "title": item.get("title") or "",
                "action": item.get("action") or "",
                "zotero_item_key": item.get("zotero_item_key") or "",
                "zotero_child_key": item.get("zotero_child_key") or "",
                "target_table": item.get("target_table") or "",
                "target_id": item.get("target_id"),
            }
            for item in items[:10]
        ],
    }


def zotero_workflow_receipt_summary(
    *,
    action_type: str,
    status: str,
    planned: int,
    synced: int,
    skipped: int,
    target_collection_name: str,
) -> str:
    if status == "dry_run":
        return f"将同步 {planned} 篇论文到 Zotero，等待确认。"
    target = target_collection_name or "目标 Zotero 目录"
    if action_type == "zotero_seed_paper_search":
        return (
            f"已创建/复用 topic 子文件夹“{target}”，"
            f"同步 {synced} 篇论文，跳过 {skipped} 篇。"
        )
    return f"已同步 {synced} 篇论文到“{target}”，跳过 {skipped} 篇。"


def zotero_workflow_receipt_steps(
    *,
    planned: int,
    synced: int,
    skipped: int,
    notes_written: int,
    deep_read_notes: int,
    request_deep_read: bool,
    request_pdf_attachment: bool,
    request_pdf_annotations: bool,
    pdfs_attached: int,
    pdf_missing: int,
    pdf_annotations: int,
    pdf_annotation_planned: int,
    pdf_annotation_missing: int,
    pdf_annotation_failures: int,
    dry_run: bool,
    error_count: int,
) -> list[dict[str, Any]]:
    pending = "pending" if dry_run else "completed"
    steps = [
        {
            "key": "papers",
            "label": "论文同步",
            "status": "partial" if error_count else pending,
            "count": synced if not dry_run else planned,
            "skipped": skipped,
        },
        {
            "key": "notes",
            "label": "RH 笔记",
            "status": "not_requested" if not notes_written and not dry_run else pending,
            "count": notes_written,
        },
    ]
    if request_deep_read:
        steps.append(
            {
                "key": "deep_read",
                "label": "精读",
                "status": "completed"
                if deep_read_notes >= planned and planned
                else "partial",
                "count": deep_read_notes,
            }
        )
    if request_pdf_attachment:
        steps.append(
            {
                "key": "pdf_attachment",
                "label": "PDF 附件",
                "status": "partial" if pdf_missing else pending,
                "count": pdfs_attached,
                "missing": pdf_missing,
            }
        )
    if request_pdf_annotations:
        if dry_run:
            annotation_status = "pending"
        elif pdf_annotations <= 0:
            annotation_status = "not_completed"
        elif pdf_annotation_missing or pdf_annotation_failures:
            annotation_status = "partial"
        else:
            annotation_status = "completed"
        steps.append(
            {
                "key": "pdf_annotations",
                "label": "PDF 高亮/批注",
                "status": annotation_status,
                "count": pdf_annotations,
                "planned": pdf_annotation_planned,
                "missing": pdf_annotation_missing,
                "failures": pdf_annotation_failures,
            }
        )
    return steps
