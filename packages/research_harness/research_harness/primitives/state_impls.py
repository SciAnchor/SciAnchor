"""Research state primitive implementations."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Any

from .registry import RESEARCH_STATE_UPDATE_SPEC, register_primitive
from .types import ResearchStateUpdateOutput


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _as_ref_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    raw_items = value if isinstance(value, (list, tuple)) else [value]
    refs: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            refs.append({str(key): val for key, val in item.items()})
        elif str(item).strip():
            refs.append({"ref": str(item).strip()})
    return refs


def _topic_exists(db: Any, topic_id: int) -> bool:
    conn = db.connect()
    try:
        row = conn.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


@register_primitive(RESEARCH_STATE_UPDATE_SPEC)
def research_state_update(
    *,
    db: Any,
    topic_id: int,
    stage: str,
    event_type: str = "progress",
    title: str = "",
    summary: str = "",
    failure_reasons: list[str] | tuple[str, ...] | str | None = None,
    fix_records: list[str] | tuple[str, ...] | str | None = None,
    contradictions: list[str] | tuple[str, ...] | str | None = None,
    review_feedback: list[str] | tuple[str, ...] | str | None = None,
    evidence_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    next_actions: list[str] | tuple[str, ...] | str | None = None,
    record_artifact: bool = True,
    **_: Any,
) -> ResearchStateUpdateOutput:
    """Persist reusable research-state feedback as a first-class artifact."""
    if not _topic_exists(db, topic_id):
        raise ValueError(f"Topic not found: {topic_id}")

    output = ResearchStateUpdateOutput(
        topic_id=topic_id,
        stage=stage,
        event_type=event_type or "progress",
        title=title or f"Research state update: {event_type or 'progress'}",
        summary=summary,
        failure_reasons=_as_text_list(failure_reasons),
        fix_records=_as_text_list(fix_records),
        contradictions=_as_text_list(contradictions),
        review_feedback=_as_text_list(review_feedback),
        evidence_refs=_as_ref_list(evidence_refs),
        next_actions=_as_text_list(next_actions),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    if not record_artifact:
        return output

    from ..orchestrator.artifacts import ArtifactManager

    conn = db.connect()
    try:
        previous_rows = conn.execute(
            """
            SELECT id FROM project_artifacts
            WHERE topic_id = ? AND stage = ? AND artifact_type = 'research_state_update'
            """,
            (topic_id, stage),
        ).fetchall()
        previous_ids = [int(row["id"]) for row in previous_rows]
    finally:
        conn.close()

    artifact = ArtifactManager(db).record(
        topic_id=topic_id,
        stage=stage,
        artifact_type="research_state_update",
        title=output.title,
        payload=asdict(output),
        metadata={
            "generated_by": "research_state_update",
            "event_type": output.event_type,
            "failure_count": len(output.failure_reasons),
            "fix_count": len(output.fix_records),
            "contradiction_count": len(output.contradictions),
            "review_feedback_count": len(output.review_feedback),
            "append_log": True,
        },
    )
    if artifact is None:
        return output

    output = replace(output, research_state_update_artifact_id=artifact.id)
    conn = db.connect()
    try:
        if previous_ids:
            placeholders = ",".join("?" * len(previous_ids))
            conn.execute(
                f"""
                UPDATE project_artifacts
                SET status = 'active', updated_at = datetime('now')
                WHERE id IN ({placeholders})
                """,
                previous_ids,
            )
        conn.execute(
            """
            UPDATE project_artifacts
            SET payload_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (json.dumps(asdict(output), ensure_ascii=False), artifact.id),
        )
        conn.commit()
    finally:
        conn.close()
    return output
