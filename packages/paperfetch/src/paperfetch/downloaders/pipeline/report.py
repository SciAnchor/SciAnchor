# -*- coding: utf-8 -*-
"""从统一下载事件生成机器审计报告。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.pipeline.outcome import finalize_download_outcome
from paperfetch.downloaders.pdf_common import redact_url
from paperfetch.downloaders.pipeline.events import (
    build_paper_download_events,
    event_dicts,
)


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1)))
    )
    return int(ordered[index])


def _timing(values: list[int]) -> dict[str, int]:
    return {
        "count": len(values),
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "max_ms": max(values) if values else 0,
    }


def build_download_run_report(
    papers: list[PaperRecord],
    total_candidates: int = 0,
    preflight: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """生成 schema v3；版本只描述数据格式，不表示并存的下载实现。"""
    discovery_results: Counter[str] = Counter()
    transfer_results: Counter[str] = Counter()
    transfer_error_classes: Counter[str] = Counter()
    verification_results: Counter[str] = Counter()
    verification_statuses: Counter[str] = Counter()
    proxy_modes: Counter[str] = Counter()
    skip_reasons: Counter[str] = Counter()
    discovery_durations: list[int] = []
    deduplication_durations: list[int] = []
    transfer_durations: list[int] = []
    phase1_transfer_durations: list[int] = []
    verification_durations: list[int] = []
    normalized_count = 0
    duplicate_count = 0
    all_events: list[dict[str, Any]] = []
    paper_reports: list[dict[str, Any]] = []

    for paper in papers:
        status = paper.fulltext_status
        finalize_download_outcome(status)
        events = build_paper_download_events(paper)
        serialized_events = event_dicts(events)
        all_events.extend(serialized_events)
        for event in events:
            duration = int(event.elapsed_ms or 0)
            if event.phase == "discovery":
                discovery_results[event.outcome] += 1
                discovery_durations.append(duration)
                if event.outcome == "skipped":
                    skip_reasons[event.error_class or event.source or "unknown"] += 1
            elif event.phase == "transfer":
                transfer_results[event.outcome] += 1
                if event.error_class:
                    transfer_error_classes[event.error_class] += 1
                transfer_durations.append(duration)
                if event.route in {
                    "public_http",
                    "public_browser",
                    "elsevier_api",
                    "publisher_api_springer",
                }:
                    phase1_transfer_durations.append(duration)
                diagnostics = event.diagnostics
                proxy = diagnostics.get("proxy_mode") or diagnostics.get("proxy_policy")
                if proxy:
                    proxy_modes[str(proxy)] += 1
                if event.outcome == "skipped":
                    skip_reasons[event.error_class or event.route or "unknown"] += 1
            elif event.phase == "verification":
                verification_results[event.outcome] += 1
                verification_statuses[
                    paper.fulltext_status.identity_status or "not_checked"
                ] += 1
                verification_durations.append(duration)
        for item in status.discovery_events:
            if item.get("source") == "normalization":
                duplicate_count += int(item.get("duplicate_count") or 0)
                if isinstance(item.get("duration_ms"), (int, float)):
                    deduplication_durations.append(int(item["duration_ms"]))
        normalized_count += len(status.normalized_resources)
        paper_reports.append(
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "doi": paper.doi,
                "arxiv_id": paper.arxiv_id,
                "publisher_key": events[-1].publisher_key,
                "events": serialized_events,
                "discovery_events": [
                    event
                    for event in serialized_events
                    if event["phase"] == "discovery"
                ],
                "normalized_resources": status.normalized_resources,
                "transfer_attempts": [
                    event for event in serialized_events if event["phase"] == "transfer"
                ],
                "verification": next(
                    event
                    for event in serialized_events
                    if event["phase"] == "verification"
                ),
                "final_result": {
                    "download_status": status.download_status,
                    "successful_route": status.successful_route,
                    "resolved_pdf_url": redact_url(status.resolved_pdf_url),
                    "local_path": status.local_path,
                    "failure_taxonomy": status.failure_taxonomy,
                    "primary_failure_class": status.primary_failure_class,
                    "last_failure_class": status.last_failure_class,
                    "attempted_route_summary": status.attempted_route_summary,
                    "resource_outcome": status.resource_outcome,
                    "oa_declaration_status": status.oa_declaration_status,
                    "oa_transport_status": status.oa_transport_status,
                    "cache_hit": status.cache_hit,
                    "identity_verified": status.identity_verified,
                    "identity_status": status.identity_status,
                    "identity_confidence": status.identity_confidence,
                },
            }
        )

    papers_entered = sum(
        1 for paper in papers if paper.fulltext_status.download_attempted
    )
    downloaded = sum(
        1 for paper in papers if paper.fulltext_status.download_status == "downloaded"
    )
    identity_verified = sum(
        1 for paper in papers if paper.fulltext_status.identity_verified
    )
    physically_verified = sum(1 for paper in papers if paper.fulltext_status.magic_pdf)
    transfer_attempts = transfer_results.get("success", 0) + transfer_results.get(
        "failed", 0
    )
    transfer_successes = transfer_results.get("success", 0)
    return {
        "report_version": "paperfetch.run-report.v3",
        "schema_purpose": "data_format_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {"total_candidates": total_candidates, "total_top_seeds": len(papers)},
        "preflight": preflight or {},
        "events": all_events,
        "metrics": {
            "discovery": {
                "results": dict(discovery_results),
                "timing": _timing(discovery_durations),
                "resource_success_rate": round(
                    discovery_results.get("success", 0)
                    / sum(discovery_results.values()),
                    4,
                )
                if discovery_results
                else 0.0,
            },
            "deduplication": {
                "normalized_resources": normalized_count,
                "duplicate_resources": duplicate_count,
                "duplicate_transfer_count": 0,
                "timing": _timing(deduplication_durations),
                "deduplication_rate": round(
                    duplicate_count / (normalized_count + duplicate_count), 4
                )
                if normalized_count + duplicate_count
                else 0.0,
            },
            "transfer": {
                "results": dict(transfer_results),
                "error_classes": dict(transfer_error_classes),
                "timing": _timing(transfer_durations),
                "phase1_timing": _timing(phase1_transfer_durations),
                "actual_proxy_modes": dict(proxy_modes),
                "skip_reasons": dict(skip_reasons),
                "attempt_success_rate": round(transfer_successes / transfer_attempts, 4)
                if transfer_attempts
                else 0.0,
            },
            "verification": {
                "results": dict(verification_results),
                "statuses": dict(verification_statuses),
                "identity_verified": identity_verified,
                "paper_success_rate": round(identity_verified / papers_entered, 4)
                if papers_entered
                else 0.0,
                "timing": _timing(verification_durations),
            },
        },
        "summary": {
            "papers_entered": papers_entered,
            "pdf_downloaded": downloaded,
            "pdf_identity_verified": identity_verified,
            "pdf_verified": physically_verified,
            "cache_hit": sum(1 for paper in papers if paper.fulltext_status.cache_hit),
            "paper_download_success_rate": round(downloaded / papers_entered, 4)
            if papers_entered
            else 0.0,
            "pdf_verification_pass_rate": round(physically_verified / downloaded, 4)
            if downloaded
            else 0.0,
            "pdf_identity_verification_pass_rate": round(
                identity_verified / downloaded, 4
            )
            if downloaded
            else 0.0,
            "mineru_parsed": sum(
                1 for paper in papers if paper.fulltext_status.mineru_status == "parsed"
            ),
        },
        "papers": paper_reports,
    }
