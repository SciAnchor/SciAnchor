"""Zotero PDF attachment materialization helpers."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ContextManager

from research_harness.acquisition.downloader import DownloadResult, download_single
from research_harness.pdf_download import PaperDownloadCandidate
from research_harness_mcp.zotero_models_http import (
    ZoteroChatRequest,
    ZoteroChatTargetRef,
)

TrustedPdfPathFn = Callable[[str], tuple[Path | None, str | None]]
TrustedPdfRootsFn = Callable[[], tuple[list[Path], str | None]]
DownloadZoteroAttachablePdfFn = Callable[[PaperDownloadCandidate, Path], DownloadResult]
GetDbContextFn = Callable[[], ContextManager[sqlite3.Connection]]
ResolveZoteroAttachmentTargetFn = Callable[
    [sqlite3.Connection, ZoteroChatTargetRef], dict[str, Any]
]
EnsureZoteroAttachablePdfFn = Callable[[sqlite3.Connection, int], "ZoteroAttachablePdf"]
NormalizeZoteroLibraryIdFn = Callable[[Any], Any]
FinalizeZoteroActionPreviewFn = Callable[..., dict[str, Any]]
LooksLikeZoteroPdfAttachmentRequestFn = Callable[[str], bool]
PrepareZoteroPdfAttachmentBatchActionFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ZoteroAttachablePdf:
    ok: bool
    paper_id: int
    row: dict[str, Any] | None = None
    pdf_path: Path | None = None
    reason: str = ""
    materialized: bool = False
    provider: str = ""
    download_status: str = ""


def zotero_paper_has_download_source(row: dict[str, Any]) -> bool:
    return any(
        str(row.get(key) or "").strip() for key in ("doi", "arxiv_id", "pmcid", "url")
    )


def download_zotero_attachable_pdf(
    candidate: PaperDownloadCandidate,
    output_dir: Path,
    *,
    download_single_fn=download_single,
) -> DownloadResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    def run() -> DownloadResult:
        return asyncio.run(
            download_single_fn(candidate, output_dir, asyncio.Semaphore(1))
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(run).result()


def zotero_attachable_pdf_download_dir(
    *,
    db_path: Path,
    trusted_pdf_roots_for_zotero: TrustedPdfRootsFn,
) -> tuple[Path | None, str | None]:
    try:
        download_dir = (db_path.parent / "papers").expanduser().resolve()
    except OSError as exc:
        return None, f"PDF 下载目录无效：{exc}"

    trusted_roots, roots_error = trusted_pdf_roots_for_zotero()
    if roots_error:
        return None, roots_error
    if not any(download_dir.is_relative_to(root) for root in trusted_roots):
        return None, "RH PDF 下载目录不在允许的 RH PDF 根目录下"
    return download_dir, None


def ensure_zotero_attachable_pdf(
    conn: sqlite3.Connection,
    paper_id: int,
    *,
    db_path: Path,
    trusted_pdf_path_for_zotero: TrustedPdfPathFn,
    trusted_pdf_roots_for_zotero: TrustedPdfRootsFn,
    download_zotero_attachable_pdf: DownloadZoteroAttachablePdfFn = (
        download_zotero_attachable_pdf
    ),
    logger: logging.Logger | None = None,
) -> ZoteroAttachablePdf:
    """Ensure a paper has a local PDF that is safe for Zotero attachment."""

    paper_id = int(paper_id)
    row = conn.execute(
        """
        SELECT id, title, year, venue, doi, arxiv_id, pmid, pmcid, url, pdf_path
        FROM papers
        WHERE id = ?
        """,
        (paper_id,),
    ).fetchone()
    if row is None:
        return ZoteroAttachablePdf(
            ok=False,
            paper_id=paper_id,
            reason=f"RH paper #{paper_id} 不存在",
        )

    row_dict = dict(row)
    existing_path, existing_error = trusted_pdf_path_for_zotero(
        row_dict.get("pdf_path") or ""
    )
    if existing_path is not None:
        return ZoteroAttachablePdf(
            ok=True,
            paper_id=paper_id,
            row=row_dict,
            pdf_path=existing_path,
        )

    if not zotero_paper_has_download_source(row_dict):
        source_error = "没有 DOI/arXiv/PMCID/url 可用于 RH 下载"
        reason = f"{existing_error}；{source_error}" if existing_error else source_error
        return ZoteroAttachablePdf(
            ok=False,
            paper_id=paper_id,
            row=row_dict,
            reason=reason,
        )

    download_dir, download_dir_error = zotero_attachable_pdf_download_dir(
        db_path=db_path,
        trusted_pdf_roots_for_zotero=trusted_pdf_roots_for_zotero,
    )
    if download_dir_error:
        return ZoteroAttachablePdf(
            ok=False,
            paper_id=paper_id,
            row=row_dict,
            reason=(
                f"{existing_error}；RH PDF 下载目录不可用：{download_dir_error}"
                if existing_error
                else f"RH PDF 下载目录不可用：{download_dir_error}"
            ),
        )
    assert download_dir is not None

    candidate = PaperDownloadCandidate(
        paper_id=paper_id,
        title=str(row_dict.get("title") or f"paper-{paper_id}"),
        year=row_dict.get("year"),
        venue=str(row_dict.get("venue") or ""),
        doi=str(row_dict.get("doi") or ""),
        arxiv_id=str(row_dict.get("arxiv_id") or ""),
        pmid=str(row_dict.get("pmid") or ""),
        pmcid=str(row_dict.get("pmcid") or ""),
        url=str(row_dict.get("url") or ""),
    )
    try:
        result = download_zotero_attachable_pdf(candidate, download_dir)
    except Exception as exc:
        log = logger or logging.getLogger(__name__)
        log.warning(
            "Failed to materialize Zotero attachable PDF for paper %d",
            paper_id,
            exc_info=True,
        )
        return ZoteroAttachablePdf(
            ok=False,
            paper_id=paper_id,
            row=row_dict,
            reason=f"已尝试用 RH 下载 PDF，但下载器异常：{exc}",
        )

    if result.status != "success" or result.path is None:
        reason = result.failure_reason or "all candidate URLs failed"
        return ZoteroAttachablePdf(
            ok=False,
            paper_id=paper_id,
            row=row_dict,
            reason=f"已尝试用 RH 下载 PDF，但下载失败：{reason}",
            download_status=str(result.status),
        )

    verified_path, verified_error = trusted_pdf_path_for_zotero(str(result.path))
    if verified_path is None:
        return ZoteroAttachablePdf(
            ok=False,
            paper_id=paper_id,
            row={**row_dict, "pdf_path": str(result.path)},
            reason=(
                "已尝试用 RH 下载 PDF，但结果不可安全导入："
                f"{verified_error or 'pdf_path unavailable'}"
            ),
            materialized=True,
            provider=result.provider or "",
            download_status=str(result.status),
        )

    conn.execute(
        "UPDATE papers SET pdf_path = ?, status = 'downloaded' WHERE id = ?",
        (str(verified_path), paper_id),
    )
    conn.commit()

    return ZoteroAttachablePdf(
        ok=True,
        paper_id=paper_id,
        row={**row_dict, "pdf_path": str(verified_path), "status": "downloaded"},
        pdf_path=verified_path,
        materialized=True,
        provider=result.provider or "",
        download_status=str(result.status),
    )


def prepare_zotero_pdf_attachment_action(
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    *,
    target_refs: list[ZoteroChatTargetRef] | None = None,
    target_source: str = "",
    looks_like_zotero_pdf_attachment_request: LooksLikeZoteroPdfAttachmentRequestFn,
    get_db_context: GetDbContextFn,
    ensure_zotero_attachable_pdf: EnsureZoteroAttachablePdfFn,
    normalize_zotero_library_id: NormalizeZoteroLibraryIdFn,
    finalize_zotero_action_preview: FinalizeZoteroActionPreviewFn,
    prepare_zotero_pdf_attachment_batch_action: (
        PrepareZoteroPdfAttachmentBatchActionFn
    ),
) -> dict[str, Any] | None:
    if target_refs:
        return prepare_zotero_pdf_attachment_batch_action(
            body=body,
            matched=matched,
            target_refs=target_refs,
            target_source=target_source,
        )

    if not looks_like_zotero_pdf_attachment_request(body.message):
        return None

    paper = matched.get("paper") or {}
    topic = matched.get("topic") or {}
    parent_item_key = str(body.item.zotero_item_key or "").strip()
    if not parent_item_key:
        return {
            "kind": "assistant_message",
            "message": "要附加 PDF，请先选中一个具体 Zotero 条目，而不是目录或文库。",
        }

    if not paper.get("id"):
        return {
            "kind": "assistant_message",
            "message": (
                "我识别到你想给当前 Zotero 条目附加 PDF，但当前条目还没有匹配到 RH paper。"
                "请先通过 DOI/arXiv/title 入库或同步到 RH，再执行 PDF 附件动作。"
            ),
        }

    with get_db_context() as conn:
        attachable = ensure_zotero_attachable_pdf(conn, int(paper["id"]))
    row = attachable.row or {}
    if not attachable.ok or attachable.pdf_path is None:
        arxiv_id = row.get("arxiv_id") or body.item.arxiv_id
        source_hint = f"（arXiv {arxiv_id}）" if arxiv_id else ""
        return {
            "kind": "assistant_message",
            "message": (
                f"我识别到要附加 PDF{source_hint}，已尝试用 RH 下载 PDF，"
                f"但仍无法生成安全预览：{attachable.reason}。"
            ),
        }

    pdf_path = attachable.pdf_path
    library_type = str(body.item.library_type or "user").strip() or "user"
    local_library_id = normalize_zotero_library_id(body.item.library_id)
    title = row.get("title") or paper.get("title") or body.item.title or "RH PDF"
    arxiv_id = row.get("arxiv_id") or body.item.arxiv_id
    source_bits = ["RH PDF"]
    if arxiv_id:
        source_bits.append(f"arXiv {arxiv_id}")
    if attachable.materialized:
        source_bits.append("已由 RH 下载补齐")
    return {
        "kind": "action_preview",
        "preview": finalize_zotero_action_preview(
            {
                "action_type": "zotero_attach_pdf",
                "title": "附加 PDF 到当前 Zotero 条目",
                "message": (
                    f"我可以把 RH paper #{paper['id']} 的 PDF 附加到当前 Zotero 条目 "
                    f"`{parent_item_key}`。这是 dry-run 预览；确认后只新增 PDF 附件，"
                    "不修改 topic、claims 或 deepread 记录。"
                ),
                "paper_id": int(paper["id"]),
                "topic_id": int(topic["id"]) if topic.get("id") else None,
                "source_label": " · ".join(source_bits),
                "target_label": f"Zotero item {parent_item_key}",
                "planned_count": 1,
                "count_label": "PDF 附件",
                "pdf_path": str(pdf_path),
                "records": [
                    {
                        "paper_id": int(paper["id"]),
                        "title": title,
                        "doi": row.get("doi") or "",
                        "arxiv_id": arxiv_id or "",
                        "pdf_path": str(pdf_path),
                    }
                ],
                "notice": (
                    "将调用 Zotero 本地附件导入；不会改 RH topic、claims、deepread。"
                    "若 Zotero 条目已有同一 PDF，可能产生重复附件。"
                ),
                "confirm_label": "确认附加 PDF",
                "cancel_label": "取消",
                "apply": {
                    "type": "zotero_local",
                    "handler": "zotero_import_file_attachment",
                    "label": "确认附加 PDF",
                    "payload": {
                        "parent_item_key": parent_item_key,
                        "parent_library_id": local_library_id,
                        "library_type": library_type,
                        "paper_id": int(paper["id"]),
                        "topic_id": int(topic["id"]) if topic.get("id") else None,
                        "pdf_path": str(pdf_path),
                        "title": title,
                        "replace_existing": False,
                    },
                },
            },
            capability="rh.zotero.attach_pdf",
            target_source="current_item",
            target_record_count=1,
            writable_count=1,
            undo_supported=True,
        ),
    }


def prepare_zotero_pdf_attachment_batch_action(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    target_refs: list[ZoteroChatTargetRef],
    target_source: str,
    get_db_context: GetDbContextFn,
    resolve_zotero_attachment_target: ResolveZoteroAttachmentTargetFn,
    ensure_zotero_attachable_pdf: EnsureZoteroAttachablePdfFn,
    normalize_zotero_library_id: NormalizeZoteroLibraryIdFn,
    finalize_zotero_action_preview: FinalizeZoteroActionPreviewFn,
) -> dict[str, Any]:
    """Build a dry-run batch PDF attachment preview for Zotero targets."""

    del matched
    writable_records: list[dict[str, Any]] = []
    blocked_records: list[dict[str, Any]] = []
    warnings: list[str] = []
    identity_missing_count = 0
    download_failed_count = 0
    with get_db_context() as conn:
        for index, target in enumerate(target_refs[:100]):
            resolved = resolve_zotero_attachment_target(conn, target)
            paper_id = resolved.get("paper_id")
            block_base = {
                "index": index,
                "paper_id": paper_id,
                "title": resolved.get("title") or target.title,
                "zotero_item_key": resolved.get("zotero_item_key")
                or target.zotero_item_key,
            }
            if not paper_id:
                reason = "无法把该 Zotero 目标重新解析到 RH paper"
                identity_missing_count += 1
                blocked_records.append({**block_base, "reason": reason})
                warnings.append(reason)
                continue
            if not block_base["zotero_item_key"]:
                reason = f"RH paper #{paper_id} 缺少可写入的 Zotero item key"
                identity_missing_count += 1
                blocked_records.append({**block_base, "reason": reason})
                warnings.append(reason)
                continue

            attachable = ensure_zotero_attachable_pdf(conn, int(paper_id))
            if not attachable.ok or attachable.pdf_path is None:
                reason = f"RH paper #{paper_id}: {attachable.reason}"
                download_failed_count += 1
                blocked_records.append({**block_base, "reason": reason})
                warnings.append(reason)
                continue
            pdf_path = attachable.pdf_path
            row = attachable.row or {}
            record = {
                "record_id": f"paper:{int(paper_id)}",
                "paper_id": int(paper_id),
                "topic_id": resolved.get("topic_id"),
                "title": row.get("title")
                or resolved.get("title")
                or target.title
                or "RH PDF",
                "doi": row.get("doi") or resolved.get("doi") or target.doi or "",
                "arxiv_id": row.get("arxiv_id")
                or resolved.get("arxiv_id")
                or target.arxiv_id
                or "",
                "pdf_path": str(pdf_path),
                "zotero_item_key": block_base["zotero_item_key"],
                "parent_item_key": block_base["zotero_item_key"],
                "parent_library_id": normalize_zotero_library_id(
                    target.library_id or body.item.library_id
                ),
                "library_type": str(
                    target.library_type or body.item.library_type or "user"
                ).strip()
                or "user",
            }
            writable_records.append(record)

    target_label = (
        f"{len(writable_records)} 个 Zotero 条目"
        if writable_records
        else "所选 Zotero 条目"
    )
    apply_spec = {
        "type": "zotero_local",
        "handler": "zotero_import_file_attachments",
        "label": "确认附加 PDF",
        "payload": {
            "records": writable_records,
            "blocked_count": len(blocked_records),
        },
    }
    return {
        "kind": "action_preview",
        "preview": finalize_zotero_action_preview(
            {
                "action_type": "zotero_attach_pdf",
                "title": "批量附加 PDF 到 Zotero 条目",
                "message": (
                    f"已尝试用 RH 下载/验证 PDF：可写 {len(writable_records)} / "
                    f"下载失败 {download_failed_count} / "
                    f"identity 缺失 {identity_missing_count}。"
                    "确认时只会写入可写记录。"
                ),
                "source_label": "RH PDF",
                "target_label": target_label,
                "planned_count": len(writable_records),
                "count_label": "PDF 附件",
                "records": writable_records,
                "notice": (
                    "只会处理可重新解析到 RH paper 且本地 PDF "
                    "位于可信 RH PDF 根目录内的记录。"
                ),
                "confirm_label": "确认附加 PDF",
                "cancel_label": "取消",
                "list_label": "查看清单",
                "apply": apply_spec,
            },
            capability="rh.zotero.attach_pdf",
            target_source=target_source or "selected_items",
            target_record_count=len(target_refs),
            writable_count=len(writable_records),
            blocked_records=blocked_records,
            warnings=warnings,
            undo_supported=True,
        ),
    }
