"""Offline, credential-free aggregation for publisher download run reports."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "spc.publisher-route-analysis.v1"


def _percentile(values: Iterable[int], percentile: float) -> int:
    ordered = sorted(max(0, int(value)) for value in values)
    if not ordered:
        return 0
    index = min(
        len(ordered) - 1,
        max(0, round((percentile / 100) * (len(ordered) - 1))),
    )
    return ordered[index]


def _timing(values: Iterable[int]) -> dict[str, int]:
    resolved = [max(0, int(value)) for value in values]
    return {
        "count": len(resolved),
        "p50_ms": _percentile(resolved, 50),
        "p95_ms": _percentile(resolved, 95),
        "max_ms": max(resolved, default=0),
    }


def _counter(value: Counter[str]) -> dict[str, int]:
    return {key: int(value[key]) for key in sorted(value) if key}


def _nested_diagnostics(attempt: dict[str, Any]) -> dict[str, Any]:
    diagnostics = attempt.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return {}
    nested = diagnostics.get("diagnostics")
    return nested if isinstance(nested, dict) else diagnostics


def _run_report_paths(roots: Iterable[Path]) -> list[Path]:
    reports: list[Path] = []
    for raw_root in roots:
        root = raw_root.expanduser().resolve()
        if root.is_file():
            reports.append(root)
            continue
        reports.extend(sorted(root.glob("round_*/run_report.json")))
    return list(dict.fromkeys(reports))


def analyze_publisher_routes(roots: Iterable[str | Path]) -> dict[str, Any]:
    report_paths = _run_report_paths(Path(item) for item in roots)
    publishers: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "papers": 0,
            "succeeded": 0,
            "failed": 0,
            "final_errors": Counter(),
            "routes": defaultdict(
                lambda: {
                    "attempts": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "errors": Counter(),
                    "durations": [],
                }
            ),
            "discovery": defaultdict(
                lambda: {"outcomes": Counter(), "errors": Counter(), "durations": []}
            ),
            "verification": Counter(),
            "proxy_modes": Counter(),
            "client_kinds": Counter(),
            "challenge_modes": Counter(),
            "decision_reasons": Counter(),
        }
    )
    paper_count = 0
    attempt_count = 0

    for report_path in report_paths:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for paper in report.get("papers", []):
            if not isinstance(paper, dict):
                continue
            publisher = str(paper.get("publisher_key") or "unknown")
            stats = publishers[publisher]
            stats["papers"] += 1
            paper_count += 1
            final = (
                paper.get("final_result")
                if isinstance(paper.get("final_result"), dict)
                else {}
            )
            succeeded = bool(
                final.get("download_status") == "downloaded"
                and final.get("identity_verified")
            )
            stats["succeeded" if succeeded else "failed"] += 1
            if not succeeded:
                error_class = str(
                    final.get("failure_taxonomy")
                    or final.get("last_failure_class")
                    or final.get("primary_failure_class")
                    or "unclassified"
                )
                stats["final_errors"][error_class] += 1

            verification = paper.get("verification")
            if isinstance(verification, dict):
                status = str(verification.get("identity_status") or "not_checked")
                stats["verification"][status] += 1

            for event in paper.get("discovery_events", []):
                if not isinstance(event, dict):
                    continue
                source = str(event.get("source") or "unknown")
                discovery = stats["discovery"][source]
                discovery["outcomes"][str(event.get("outcome") or "unknown")] += 1
                if event.get("error_class"):
                    discovery["errors"][str(event["error_class"])] += 1
                discovery["durations"].append(int(event.get("elapsed_ms") or 0))

            for attempt in paper.get("transfer_attempts", []):
                if not isinstance(attempt, dict):
                    continue
                attempt_count += 1
                route = str(attempt.get("route") or "unknown")
                route_stats = stats["routes"][route]
                route_stats["attempts"] += 1
                success = attempt.get("outcome") == "success"
                route_stats["succeeded" if success else "failed"] += 1
                route_stats["durations"].append(int(attempt.get("elapsed_ms") or 0))
                if attempt.get("error_class"):
                    route_stats["errors"][str(attempt["error_class"])] += 1

                diagnostics = attempt.get("diagnostics")
                if isinstance(diagnostics, dict):
                    for key, counter_name in (
                        ("proxy_mode", "proxy_modes"),
                        ("client_kind", "client_kinds"),
                        ("decision_reason", "decision_reasons"),
                    ):
                        if diagnostics.get(key):
                            stats[counter_name][str(diagnostics[key])] += 1
                nested = _nested_diagnostics(attempt)
                if nested.get("challenge_mode"):
                    stats["challenge_modes"][str(nested["challenge_mode"])] += 1

    public_publishers: dict[str, Any] = {}
    for publisher in sorted(publishers):
        stats = publishers[publisher]
        routes = {
            route: {
                "attempts": value["attempts"],
                "succeeded": value["succeeded"],
                "failed": value["failed"],
                "errors": _counter(value["errors"]),
                "timing": _timing(value["durations"]),
            }
            for route, value in sorted(stats["routes"].items())
        }
        discovery = {
            source: {
                "outcomes": _counter(value["outcomes"]),
                "errors": _counter(value["errors"]),
                "timing": _timing(value["durations"]),
            }
            for source, value in sorted(stats["discovery"].items())
        }
        papers = int(stats["papers"])
        public_publishers[publisher] = {
            "papers": papers,
            "succeeded": int(stats["succeeded"]),
            "failed": int(stats["failed"]),
            "success_rate": round(stats["succeeded"] / papers, 4) if papers else 0.0,
            "final_errors": _counter(stats["final_errors"]),
            "routes": routes,
            "discovery": discovery,
            "verification": _counter(stats["verification"]),
            "proxy_modes": _counter(stats["proxy_modes"]),
            "client_kinds": _counter(stats["client_kinds"]),
            "challenge_modes": _counter(stats["challenge_modes"]),
            "decision_reasons": _counter(stats["decision_reasons"]),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "run_reports": len(report_paths),
        "papers": paper_count,
        "transfer_attempts": attempt_count,
        "publishers": public_publishers,
    }
