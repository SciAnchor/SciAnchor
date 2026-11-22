"""Acquisition diagnosis read model.

Aggregates the route audits RH already records — native downloads
(``pdf_route_audit``) and imported external history
(``external_route_audit``) — into one per-topic view: what failed, where,
how it clusters by publisher and DOI prefix, which routes are slow, and
which papers remain uncovered. Read-only; no schema or behavior changes.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import Any

from ..storage.db import Database

logger = logging.getLogger(__name__)

DIAGNOSIS_SCHEMA_VERSION = "rh.acquisition_diagnosis.v1"
SLOW_ATTEMPT_THRESHOLD_MS = 10_000
SLOWEST_LIMIT = 10


def _doi_prefix(doi: str | None) -> str:
    cleaned = (doi or "").strip().lower()
    if not cleaned:
        return "missing_doi"
    return cleaned.split("/", 1)[0] if "/" in cleaned else cleaned


def _latest_audits(conn: Any, paper_id: int) -> dict[str, dict[str, Any]]:
    """Latest audit payload per artifact type for one paper."""
    rows = conn.execute(
        "SELECT artifact_type, metadata FROM paper_artifacts"
        " WHERE paper_id = ? AND artifact_type IN"
        " ('pdf_route_audit', 'external_route_audit')"
        " ORDER BY id",
        (paper_id,),
    ).fetchall()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            latest[row["artifact_type"]] = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            continue
    return latest


def build_acquisition_diagnosis(
    db: Database,
    topic_id: int,
    *,
    slow_threshold_ms: int = SLOW_ATTEMPT_THRESHOLD_MS,
) -> dict[str, Any]:
    conn = db.connect()
    try:
        papers = conn.execute(
            """
            SELECT p.id, p.title, p.doi, p.venue, p.pdf_path
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
            ORDER BY p.id
            """,
            (topic_id,),
        ).fetchall()

        failure_taxonomy: Counter = Counter()
        failure_by_origin: dict[str, Counter] = {
            "native": Counter(),
            "external": Counter(),
        }
        route_success: Counter = Counter()
        route_failure: Counter = Counter()
        publisher_failures: dict[str, Counter] = defaultdict(Counter)
        doi_prefix_failures: dict[str, Counter] = defaultdict(Counter)
        slow_attempts: list[dict[str, Any]] = []
        uncovered: list[dict[str, Any]] = []

        for paper in papers:
            paper_id = int(paper["id"])
            has_pdf = bool((paper["pdf_path"] or "").strip())
            audits = _latest_audits(conn, paper_id)
            venue_key = (paper["venue"] or "").strip().lower() or _doi_prefix(
                paper["doi"]
            )

            latest_taxonomy: str | None = None
            for artifact_type, payload in audits.items():
                origin = (
                    "external" if artifact_type == "external_route_audit" else "native"
                )
                taxonomy = payload.get("failure_taxonomy")
                if taxonomy:
                    failure_taxonomy[taxonomy] += 1
                    failure_by_origin[origin][taxonomy] += 1
                    publisher_failures[venue_key][taxonomy] += 1
                    doi_prefix_failures[_doi_prefix(paper["doi"])][taxonomy] += 1
                    latest_taxonomy = taxonomy
                successful = payload.get("successful_route")
                if successful:
                    route_success[str(successful)] += 1
                for attempt in (
                    payload.get("attempts") or payload.get("download_attempts") or []
                ):
                    if not isinstance(attempt, dict):
                        continue
                    error_class = attempt.get("error_class")
                    if error_class and not attempt.get("skipped"):
                        route_failure[str(attempt.get("route") or "unknown")] += 1
                    duration = attempt.get("duration_ms")
                    if (
                        isinstance(duration, (int, float))
                        and duration >= slow_threshold_ms
                    ):
                        slow_attempts.append(
                            {
                                "paper_id": paper_id,
                                "route": attempt.get("route"),
                                "duration_ms": int(duration),
                                "error_class": error_class,
                                "origin": origin,
                            }
                        )

            if not has_pdf:
                uncovered.append(
                    {
                        "paper_id": paper_id,
                        "title": paper["title"],
                        "doi": paper["doi"],
                        "latest_failure_taxonomy": latest_taxonomy,
                        "attempted": bool(audits),
                    }
                )
    finally:
        conn.close()

    slow_attempts.sort(key=lambda item: item["duration_ms"], reverse=True)
    total = len(papers)
    covered = total - len(uncovered)
    return {
        "schema_version": DIAGNOSIS_SCHEMA_VERSION,
        "topic_id": topic_id,
        "totals": {
            "papers": total,
            "with_pdf": covered,
            "without_pdf": len(uncovered),
            "coverage_rate": round(covered / total, 3) if total else 0.0,
        },
        "failure_taxonomy": dict(failure_taxonomy),
        "failure_by_origin": {
            origin: dict(counts) for origin, counts in failure_by_origin.items()
        },
        "route_success": dict(route_success),
        "route_failure": dict(route_failure),
        "publisher_failure_summary": {
            key: dict(counts) for key, counts in sorted(publisher_failures.items())
        },
        "doi_prefix_failure_summary": {
            key: dict(counts) for key, counts in sorted(doi_prefix_failures.items())
        },
        "slowest_attempts": slow_attempts[:SLOWEST_LIMIT],
        "uncovered_papers": uncovered,
    }
