"""Stage snapshot + rollback logic.

Snapshots capture the state of a topic at a given stage (artifacts, claims,
rubric scores) as a JSON blob. On rollback, later-stage artifacts are marked
stale and the orchestrator is rewound.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

ROLLBACK_EVENT_SCHEMA_VERSION = "rollback_event/v1"


def create_snapshot(
    conn: sqlite3.Connection,
    topic_id: int,
    stage: str,
    run_id: int | None = None,
) -> int:
    artifacts = conn.execute(
        "SELECT id, stage, artifact_type, title, version, status FROM project_artifacts WHERE topic_id = ? AND (stale = 0 OR stale IS NULL)",
        (topic_id,),
    ).fetchall()

    claims = conn.execute(
        "SELECT c.id, c.text, c.claim_type FROM claims c WHERE c.topic_id = ?",
        (topic_id,),
    ).fetchall()

    rubric = conn.execute(
        "SELECT * FROM rubric_scores WHERE topic_id = ?",
        (topic_id,),
    ).fetchall()

    snapshot_data = {
        "artifacts": [dict(r) for r in artifacts],
        "claims": [dict(r) for r in claims],
        "rubric_scores": [dict(r) for r in rubric],
    }

    total_cost = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM token_ledger WHERE topic_id = ?",
        (topic_id,),
    ).fetchone()[0]

    cur = conn.execute(
        """
        INSERT INTO stage_snapshots (topic_id, stage, orchestrator_run_id, artifact_snapshot, token_cost_usd)
        VALUES (?, ?, ?, ?, ?)
        """,
        (topic_id, stage, run_id, json.dumps(snapshot_data), total_cost),
    )
    return cur.lastrowid  # type: ignore[return-value]


def rollback_to_stage(
    conn: sqlite3.Connection,
    topic_id: int,
    to_stage: str,
    reason: str,
    trigger: str = "user",
) -> dict[str, Any]:
    from .stages import STAGE_ORDER, stage_index

    to_idx = stage_index(to_stage)

    run = conn.execute(
        "SELECT id, current_stage FROM orchestrator_runs WHERE topic_id = ? ORDER BY id DESC LIMIT 1",
        (topic_id,),
    ).fetchone()
    if not run:
        return {"success": False, "error": "No orchestrator run found"}

    from_stage = run["current_stage"]

    snapshot = conn.execute(
        "SELECT id FROM stage_snapshots WHERE topic_id = ? AND stage = ? ORDER BY created_at DESC LIMIT 1",
        (topic_id, to_stage),
    ).fetchone()
    if not snapshot:
        return {"success": False, "error": f"No snapshot found for stage '{to_stage}'"}

    stale_reason = f"rollback to {to_stage} from {from_stage}: {reason}"
    affected_rows: list[dict[str, Any]] = []
    for stage in STAGE_ORDER:
        if stage_index(stage) > to_idx:
            rows = conn.execute(
                """
                SELECT id, stage, artifact_type, title
                FROM project_artifacts
                WHERE topic_id = ? AND stage = ? AND COALESCE(stale, 0) = 0
                ORDER BY id
                """,
                (topic_id, stage),
            ).fetchall()
            affected_rows.extend(dict(row) for row in rows)
            conn.execute(
                """
                UPDATE project_artifacts
                SET stale = 1,
                    stale_reason = ?,
                    updated_at = datetime('now')
                WHERE topic_id = ? AND stage = ?
                """,
                (stale_reason, topic_id, stage),
            )

    conn.execute(
        "UPDATE orchestrator_runs SET current_stage = ?, stage_status = 'in_progress', updated_at = datetime('now') WHERE topic_id = ?",
        (to_stage, topic_id),
    )

    rubric_snapshot = conn.execute(
        "SELECT artifact_snapshot FROM stage_snapshots WHERE id = ?",
        (snapshot["id"],),
    ).fetchone()

    cur = conn.execute(
        """
        INSERT INTO rollback_log (topic_id, from_stage, to_stage, to_snapshot_id, trigger, reason, rubric_snapshot)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            topic_id,
            from_stage,
            to_stage,
            snapshot["id"],
            trigger,
            reason,
            rubric_snapshot["artifact_snapshot"] if rubric_snapshot else None,
        ),
    )
    rollback_log_id = int(cur.lastrowid)

    rollback_event_id = _ensure_rollback_event(
        conn=conn,
        topic_id=topic_id,
        from_stage=str(from_stage),
        to_stage=to_stage,
        trigger=trigger,
        reason=reason,
        snapshot_id=int(snapshot["id"]),
        rollback_log_id=rollback_log_id,
        affected_rows=affected_rows,
    )

    conn.commit()

    return {
        "success": True,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "snapshot_id": snapshot["id"],
        "rollback_log_id": rollback_log_id,
        "rollback_event_artifact_id": rollback_event_id,
    }


def _ensure_rollback_event(
    *,
    conn: sqlite3.Connection,
    topic_id: int,
    from_stage: str,
    to_stage: str,
    trigger: str,
    reason: str,
    snapshot_id: int,
    rollback_log_id: int,
    affected_rows: list[dict[str, Any]],
) -> int | None:
    affected_ids = [int(row["id"]) for row in affected_rows]
    if not affected_ids:
        return None

    dedupe_key = _rollback_dedupe_key(
        topic_id=topic_id,
        from_stage=from_stage,
        to_stage=to_stage,
        trigger=trigger,
        reason=reason,
        snapshot_id=snapshot_id,
        affected_ids=affected_ids,
    )
    existing = _find_active_rollback_event(conn, topic_id, to_stage, dedupe_key)
    if existing is not None:
        return existing

    issue_id = _ensure_rollback_review_issue(
        conn=conn,
        topic_id=topic_id,
        stage=to_stage,
        dedupe_key=dedupe_key,
        from_stage=from_stage,
        to_stage=to_stage,
        trigger=trigger,
        reason=reason,
        affected_rows=affected_rows,
    )
    payload = {
        "object_type": "rollback_event",
        "schema_version": ROLLBACK_EVENT_SCHEMA_VERSION,
        "stage": to_stage,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "trigger": trigger,
        "reason": reason,
        "action": "rollback",
        "reason_codes": ["stage_rollback"],
        "dedupe_key": dedupe_key,
        "snapshot_id": snapshot_id,
        "rollback_log_id": rollback_log_id,
        "affected_artifact_ids": affected_ids,
        "affected_artifacts": affected_rows,
        "rollback_cone": {
            "trigger_stage": from_stage,
            "target_stage": to_stage,
            "affected_artifact_ids": affected_ids,
            "preserved_artifact_ids": [],
        },
        "review_issue_ids": [issue_id],
    }
    version = _next_artifact_version(conn, topic_id, to_stage, "rollback_event")
    project_id = _project_id_for_topic(conn, topic_id)
    cur = conn.execute(
        """
        INSERT INTO project_artifacts
          (project_id, topic_id, stage, artifact_type, status, version, title,
           payload_json, metadata_json)
        VALUES (?, ?, ?, 'rollback_event', 'active', ?, ?, ?, ?)
        """,
        (
            project_id,
            topic_id,
            to_stage,
            version,
            f"Rollback Event: {from_stage} -> {to_stage}",
            json.dumps(payload, sort_keys=True),
            json.dumps(
                {
                    "schema_version": ROLLBACK_EVENT_SCHEMA_VERSION,
                    "dedupe_key": dedupe_key,
                    "trigger": trigger,
                },
                sort_keys=True,
            ),
        ),
    )
    return int(cur.lastrowid)


def _ensure_rollback_review_issue(
    *,
    conn: sqlite3.Connection,
    topic_id: int,
    stage: str,
    dedupe_key: str,
    from_stage: str,
    to_stage: str,
    trigger: str,
    reason: str,
    affected_rows: list[dict[str, Any]],
) -> int:
    existing = conn.execute(
        """
        SELECT id
        FROM review_issues
        WHERE topic_id = ?
          AND stage = ?
          AND review_type = 'rollback_governance'
          AND category = 'rollback_event'
          AND affected_object_type = 'rollback_cone'
          AND affected_object_id = ?
          AND status = 'open'
        ORDER BY id LIMIT 1
        """,
        (topic_id, stage, dedupe_key),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])

    project_id = _project_id_for_topic(conn, topic_id)
    details = {
        "from_stage": from_stage,
        "to_stage": to_stage,
        "trigger": trigger,
        "reason": reason,
        "affected_artifacts": affected_rows,
    }
    cur = conn.execute(
        """
        INSERT INTO review_issues
          (project_id, topic_id, stage, review_type, severity, category,
           summary, details, blocking, recommended_action,
           affected_object_type, affected_object_id, status)
        VALUES (?, ?, ?, 'rollback_governance', 'high', 'rollback_event',
                ?, ?, 1, ?, 'rollback_cone', ?, 'open')
        """,
        (
            project_id,
            topic_id,
            stage,
            f"Rollback from {from_stage} to {to_stage} marked downstream artifacts stale",
            json.dumps(details, sort_keys=True),
            "Inspect affected artifacts and regenerate stale downstream outputs.",
            dedupe_key,
        ),
    )
    return int(cur.lastrowid)


def _project_id_for_topic(conn: sqlite3.Connection, topic_id: int) -> int | None:
    row = conn.execute(
        "SELECT id FROM projects WHERE topic_id = ? ORDER BY id LIMIT 1",
        (topic_id,),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _next_artifact_version(
    conn: sqlite3.Connection, topic_id: int, stage: str, artifact_type: str
) -> int:
    row = conn.execute(
        """
        SELECT MAX(version) AS version
        FROM project_artifacts
        WHERE topic_id = ? AND stage = ? AND artifact_type = ?
        """,
        (topic_id, stage, artifact_type),
    ).fetchone()
    return int(row["version"] or 0) + 1


def _find_active_rollback_event(
    conn: sqlite3.Connection,
    topic_id: int,
    stage: str,
    dedupe_key: str,
) -> int | None:
    rows = conn.execute(
        """
        SELECT id, payload_json
        FROM project_artifacts
        WHERE topic_id = ?
          AND stage = ?
          AND artifact_type = 'rollback_event'
          AND status = 'active'
        ORDER BY id
        """,
        (topic_id, stage),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if payload.get("dedupe_key") == dedupe_key:
            return int(row["id"])
    return None


def _rollback_dedupe_key(
    *,
    topic_id: int,
    from_stage: str,
    to_stage: str,
    trigger: str,
    reason: str,
    snapshot_id: int,
    affected_ids: list[int],
) -> str:
    raw = json.dumps(
        {
            "topic_id": topic_id,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "trigger": trigger,
            "reason": reason,
            "snapshot_id": snapshot_id,
            "affected_ids": affected_ids,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
