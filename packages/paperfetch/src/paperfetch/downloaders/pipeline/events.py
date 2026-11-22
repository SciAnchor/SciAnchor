"""将下载状态转换为统一 SPC 事件。"""

from __future__ import annotations

from typing import Any, Iterable

from paperfetch.core.models import PaperRecord
from paperfetch.observability import SPCLogEvent, canonical_publisher_key


def _elapsed(item: dict[str, Any]) -> int:
    value = item.get("duration_ms", item.get("elapsed_ms", 0))
    return max(0, int(value or 0))


def build_paper_download_events(
    paper: PaperRecord, *, task_id: str | None = None
) -> list[SPCLogEvent]:
    """从一次下载的权威状态生成发现、传输、验证和终局事件。"""
    status = paper.fulltext_status
    common = {
        "task_id": task_id,
        "paper_id": paper.paper_id,
        "doi": paper.doi,
        "publisher_key": canonical_publisher_key(
            paper.publisher or paper.journal or paper.venue, paper.doi
        ),
    }
    events: list[SPCLogEvent] = []
    for item in status.discovery_events:
        result = str(item.get("result") or "miss")
        outcome = {
            "found": "success",
            "success": "success",
            "completed": "success",
            "planned_skip": "skipped",
            "cancelled": "skipped",
            "timeout": "degraded",
            "error": "degraded",
        }.get(result, "miss")
        events.append(
            SPCLogEvent(
                event_code="download.discovery.result",
                domain="download",
                phase="discovery",
                action="discover_resource",
                outcome=outcome,
                terminal=False,
                level="WARNING" if outcome == "degraded" else "INFO",
                source=str(item.get("source") or "unknown"),
                elapsed_ms=_elapsed(item),
                error_class=str(item.get("error_class") or item.get("reason") or "")
                or None,
                message="资源发现完成",
                diagnostics=item,
                **common,
            )
        )
    for item in status.download_attempts:
        skipped = bool(item.get("skipped"))
        error_class = str(item.get("error_class") or "") or None
        outcome = "skipped" if skipped else ("degraded" if error_class else "success")
        events.append(
            SPCLogEvent(
                event_code="download.transfer.result",
                domain="download",
                phase="transfer",
                action="transfer_pdf",
                outcome=outcome,
                terminal=False,
                level="WARNING" if outcome == "degraded" else "INFO",
                route=str(item.get("route") or "unknown"),
                source=str(item.get("source") or "") or None,
                elapsed_ms=_elapsed(item),
                error_class=error_class,
                message="传输尝试完成",
                diagnostics=item,
                **common,
            )
        )
    verification = dict(status.verification or {})
    verification_error = str(verification.get("error_class") or "") or None
    verification_outcome = (
        "success"
        if status.identity_verified
        else ("degraded" if verification_error else "skipped")
    )
    events.append(
        SPCLogEvent(
            event_code="download.verification.result",
            domain="download",
            phase="verification",
            action="verify_identity",
            outcome=verification_outcome,
            terminal=False,
            level="WARNING" if verification_outcome == "degraded" else "INFO",
            route=status.successful_route,
            elapsed_ms=_elapsed(verification),
            error_class=verification_error,
            message="PDF 身份验证完成",
            diagnostics=verification,
            **common,
        )
    )
    success = status.download_status == "downloaded" and status.identity_verified
    discovery_elapsed_ms = max(
        (_elapsed(item) for item in status.discovery_events), default=0
    )
    transfer_elapsed_ms = sum(_elapsed(item) for item in status.download_attempts)
    events.append(
        SPCLogEvent(
            event_code="download.paper.terminal",
            domain="download",
            phase="final",
            action="download_paper",
            outcome="success" if success else "failed",
            terminal=True,
            level="INFO" if success else "ERROR",
            route=status.successful_route,
            # 远程发现并发执行，取最大墙钟时间；验证耗时已包含在传输尝试中。
            elapsed_ms=discovery_elapsed_ms + transfer_elapsed_ms,
            error_class=None
            if success
            else (status.failure_taxonomy or "download_failed"),
            message="论文下载成功" if success else "论文下载失败",
            diagnostics={
                "download_status": status.download_status,
                "identity_verified": status.identity_verified,
                "identity_status": status.identity_status,
                "failure_taxonomy": status.failure_taxonomy,
            },
            **common,
        )
    )
    return events


def event_dicts(events: Iterable[SPCLogEvent]) -> list[dict[str, Any]]:
    return [event.to_dict() for event in events]
