"""下载终局的唯一归一化入口。

该模块不执行网络或文件 I/O，只把逐路由事实折叠为供 CLI、Seed Pack、
run report 和持久 job 共同消费的稳定终局语义。
"""

from __future__ import annotations

from typing import Any

from paperfetch.core.models import FulltextStatus


_NON_ACTIONABLE_FAILURES = {
    "missing_file",
    "cache_miss",
    "disabled_by_config",
}

_RESOURCE_NOT_DISCOVERED_FAILURE = "pdf_resource_not_discovered"
_NON_SPECIFIC_TERMINAL_FAILURES = {
    "all_routes_failed",
    "download_failed",
    "failed",
    "fallback_failed",
    "no_result",
}


def _actionable_failures(status: FulltextStatus) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for attempt in status.download_attempts:
        error_class = str(attempt.get("error_class") or "").strip()
        if not error_class or error_class in _NON_ACTIONABLE_FAILURES:
            continue
        if attempt.get("skipped"):
            continue
        failures.append(attempt)
    return failures


def finalize_download_outcome(status: FulltextStatus) -> FulltextStatus:
    """原地补齐稳定终局字段，并返回同一个状态对象。"""

    failures = _actionable_failures(status)
    terminal_failed = status.download_status == "failed"
    existing_failure_class = (
        status.last_failure_class
        or status.failure_taxonomy
        or status.primary_failure_class
    )
    status.primary_failure_class = (
        str(failures[0].get("error_class")) if terminal_failed and failures else None
    )
    status.last_failure_class = (
        str(failures[-1].get("error_class")) if terminal_failed and failures else None
    )
    status.attempted_route_summary = [
        {
            "route": attempt.get("route"),
            "error_class": attempt.get("error_class"),
            "status_code": attempt.get("status_code"),
            "decision_reason": attempt.get("decision_reason"),
            "duration_ms": attempt.get("duration_ms"),
            "skipped": bool(attempt.get("skipped")),
        }
        for attempt in status.download_attempts
    ]

    if not status.download_attempted:
        status.resource_outcome = "not_attempted"
    elif status.download_status == "downloaded":
        status.resource_outcome = "downloaded"
    else:
        discovered = bool(status.normalized_resources) or any(
            bool(candidate.get("url"))
            for candidate in status.candidate_pdf_urls
            if isinstance(candidate, dict)
        )
        status.resource_outcome = (
            "resource_discovered_but_transfer_failed"
            if discovered
            else "resource_not_discovered"
        )

    if terminal_failed and status.last_failure_class:
        status.failure_taxonomy = status.last_failure_class
    elif terminal_failed and status.resource_outcome == "resource_not_discovered":
        # A discovery miss has no transport attempt from which to derive an error.
        # Keep the terminal contract explicit so agents do not have to infer failure
        # from resource_outcome while the three canonical failure fields stay null.
        fallback = (
            existing_failure_class
            if existing_failure_class
            and existing_failure_class not in _NON_SPECIFIC_TERMINAL_FAILURES
            else _RESOURCE_NOT_DISCOVERED_FAILURE
        )
        status.primary_failure_class = fallback
        status.last_failure_class = fallback
        status.failure_taxonomy = fallback
    elif status.download_status == "downloaded":
        status.failure_taxonomy = None
    return status
