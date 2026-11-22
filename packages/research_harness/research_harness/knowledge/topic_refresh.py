"""Best-effort Topic Knowledge refresh helpers."""

from __future__ import annotations

import logging
from typing import Any

from research_harness.storage.db import Database

from .topic_layer import build_topic_knowledge_snapshot


LOGGER = logging.getLogger(__name__)


def refresh_topic_knowledge(
    db: Database,
    *,
    topic_id: int,
    paper_id: int | None = None,
) -> dict[str, Any]:
    """Refresh one topic knowledge snapshot and return a public-safe payload."""

    try:
        result = build_topic_knowledge_snapshot(db, topic_id=topic_id)
    except Exception:
        LOGGER.warning(
            "topic knowledge refresh failed topic_id=%s paper_id=%s",
            topic_id,
            paper_id,
            exc_info=True,
        )
        return _refresh_payload(
            status="failed",
            topic_id=topic_id,
            paper_id=paper_id,
            error="topic knowledge refresh failed",
        )

    return _refresh_payload(
        status="reused" if result.reused else "refreshed",
        topic_id=result.topic_id,
        paper_id=paper_id,
        artifact_id=result.artifact_id,
        snapshot_id=result.snapshot_id,
        source_hash=result.source_hash,
    )


def refresh_topic_knowledge_after_ingest(
    db: Database,
    *,
    topic_id: int | None,
    paper_id: int,
) -> dict[str, Any]:
    """Best-effort topic knowledge refresh for the paper ingest hot path."""

    if topic_id is None:
        return _refresh_payload(
            status="skipped",
            topic_id=None,
            paper_id=paper_id,
        )
    return refresh_topic_knowledge(db, topic_id=int(topic_id), paper_id=paper_id)


def refresh_all_topic_knowledge(db: Database) -> dict[str, Any]:
    """Refresh every known topic and summarize per-topic outcomes."""

    topic_ids = _topic_ids(db)
    results = [refresh_topic_knowledge(db, topic_id=topic_id) for topic_id in topic_ids]
    counts = {status: 0 for status in ("refreshed", "reused", "skipped", "failed")}
    for result in results:
        status = str(result.get("status") or "failed")
        counts[status] = counts.get(status, 0) + 1
    return {
        "topic_count": len(topic_ids),
        "counts": counts,
        "failed_topic_ids": [
            int(result["topic_id"])
            for result in results
            if result.get("status") == "failed" and result.get("topic_id") is not None
        ],
        "results": results,
    }


def topic_exists(db: Database, topic_id: int) -> bool:
    """Return whether a topic id exists without exposing storage details."""

    conn = db.connect()
    try:
        row = conn.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


def _topic_ids(db: Database) -> list[int]:
    conn = db.connect()
    try:
        rows = conn.execute("SELECT id FROM topics ORDER BY id").fetchall()
        return [int(row["id"]) for row in rows]
    finally:
        conn.close()


def _refresh_payload(
    *,
    status: str,
    topic_id: int | None,
    paper_id: int | None,
    artifact_id: int | None = None,
    snapshot_id: int | None = None,
    source_hash: str = "",
    error: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "topic_id": topic_id,
        "paper_id": paper_id,
        "artifact_id": artifact_id,
        "snapshot_id": snapshot_id,
        "source_hash": source_hash,
        "error": error,
    }
