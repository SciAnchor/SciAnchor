"""MCP workflow and experiment handoff helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

_COMPETITION_DENSITY_THRESHOLD = 0.7


def _load_candidate(db: Any, candidate_id: int) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM research_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def _candidate_evidence(db: Any, candidate: dict[str, Any]) -> dict[str, Any]:
    """Dereference evidence IDs stored on the candidate into full rows."""
    out: dict[str, Any] = {"gaps": [], "contradictions": []}
    gap_ids = json.loads(candidate.get("evidence_gap_ids") or "[]")
    contra_ids = json.loads(candidate.get("evidence_contradiction_ids") or "[]")
    conn = db.connect()
    try:
        if gap_ids:
            ph = ",".join("?" * len(gap_ids))
            rows = conn.execute(
                f"SELECT id, description, severity, confidence, cross_verified "
                f"FROM gaps WHERE id IN ({ph})",
                gap_ids,
            ).fetchall()
            out["gaps"] = [dict(r) for r in rows]
        if contra_ids:
            ph = ",".join("?" * len(contra_ids))
            rows = conn.execute(
                f"SELECT id, conflict_reason, status FROM contradictions "
                f"WHERE id IN ({ph})",
                contra_ids,
            ).fetchall()
            out["contradictions"] = [dict(r) for r in rows]
    finally:
        conn.close()
    return out


def _competition_density_projection(
    area: float, task: float, method: float
) -> dict[str, Any]:
    """Render the canonical payload shape without importing the RH runtime."""
    dense_dimensions: tuple[str, ...] = ()
    if area >= _COMPETITION_DENSITY_THRESHOLD:
        dense_dimensions = dense_dimensions + ("area",)
    if task >= _COMPETITION_DENSITY_THRESHOLD:
        dense_dimensions = dense_dimensions + ("task",)
    if method >= _COMPETITION_DENSITY_THRESHOLD:
        dense_dimensions = dense_dimensions + ("method",)
    return {
        "area": area,
        "task": task,
        "method": method,
        "threshold": _COMPETITION_DENSITY_THRESHOLD,
        "dense_dimensions": list(dense_dimensions),
    }


def _execute_experiment_handoff_prepare(
    svc: Any,
    db: Any,
    arguments: dict[str, Any],
    *,
    candidate_loader: Callable[[Any, int], dict[str, Any] | None] = _load_candidate,
    evidence_loader: Callable[[Any, dict[str, Any]], dict[str, Any]] = (
        _candidate_evidence
    ),
) -> dict[str, Any]:
    topic_id = arguments["topic_id"]
    candidate_id = arguments["candidate_id"]
    notes = arguments.get("notes", "")

    candidate = candidate_loader(db, candidate_id)
    if candidate is None:
        return {
            "success": False,
            "error": f"research_candidates row not found: id={candidate_id}",
        }

    # Integrity: candidate scope should reference this topic (topic:N).
    expected_scope = f"topic:{topic_id}"
    if candidate.get("scope") != expected_scope:
        return {
            "success": False,
            "error": (
                f"Candidate {candidate_id} has scope={candidate.get('scope')!r}, "
                f"expected {expected_scope!r}"
            ),
        }

    evidence = evidence_loader(db, candidate)
    area_density = candidate.get("area_red_ocean", 0.0)
    task_density = candidate.get("task_red_ocean", 0.0)
    method_density = candidate.get("method_red_ocean", 0.0)

    payload: dict[str, Any] = {
        "candidate_id": candidate_id,
        "lineage_key": candidate.get("lineage_key", ""),
        "title": candidate.get("title", ""),
        "pitch": candidate.get("pitch", ""),
        "opportunity_angle": candidate.get("opportunity_angle", ""),
        "red_ocean": {
            "area": area_density,
            "task": task_density,
            "method": method_density,
        },
        "competition_density": _competition_density_projection(
            area_density,
            task_density,
            method_density,
        ),
        "llm_score": candidate.get("llm_score", 0.0),
        "evidence": evidence,
        "notes": notes,
    }

    try:
        artifact = svc.record_artifact(
            topic_id=topic_id,
            stage="experiment",
            artifact_type="experiment_brief",
            title=payload["title"] or f"candidate:{candidate_id}",
            payload=payload,
        )
    except Exception as exc:
        return {"success": False, "error": f"record_artifact failed: {exc}"}

    return {
        "success": True,
        "artifact_id": artifact.id,
        "version": artifact.version,
        "candidate_id": candidate_id,
        "stage": artifact.stage,
        "artifact_type": artifact.artifact_type,
    }


def _execute_experiment_handoff_submit(
    svc: Any, db: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    topic_id = arguments["topic_id"]
    brief_artifact_id = arguments["brief_artifact_id"]
    handoff_target = arguments["handoff_target"]
    summary = arguments.get("summary", "")

    brief = svc._artifact_manager.get(brief_artifact_id)
    if brief is None:
        return {
            "success": False,
            "error": f"experiment_brief not found: id={brief_artifact_id}",
        }
    if brief.artifact_type != "experiment_brief":
        return {
            "success": False,
            "error": (
                f"Artifact {brief_artifact_id} is not an experiment_brief "
                f"(type={brief.artifact_type})"
            ),
        }

    candidate_id = (brief.payload or {}).get("candidate_id")

    payload = {
        "brief_artifact_id": brief_artifact_id,
        "candidate_id": candidate_id,
        "handoff_target": handoff_target,
        "summary": summary,
    }

    try:
        handoff = svc.record_artifact(
            topic_id=topic_id,
            stage="experiment",
            artifact_type="experiment_handoff",
            title=f"handoff → {handoff_target}",
            payload=payload,
            dependency_artifact_ids=[brief_artifact_id],
            dependency_type="consumed_by",
        )
    except Exception as exc:
        return {"success": False, "error": f"record_artifact failed: {exc}"}

    # Flip candidate.status to 'promoted' so it no longer surfaces as a
    # live recommendation. Silently skip if the row is missing (handoff
    # artifact is the source of truth either way).
    if candidate_id:
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE research_candidates SET status = 'promoted' "
                "WHERE id = ? AND status != 'promoted'",
                (candidate_id,),
            )
            conn.commit()
        finally:
            conn.close()

    return {
        "success": True,
        "artifact_id": handoff.id,
        "version": handoff.version,
        "brief_artifact_id": brief_artifact_id,
        "candidate_id": candidate_id,
        "handoff_target": handoff_target,
    }


def _execute_workflow_entry(
    svc: Any, db: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Compact status + ranked next_actions for a topic.

    Reads orchestrator status (stage, gate), verified-gap counts, and
    live (status candidate/active) candidate counts so agents have a
    single call to decide what to do next.
    """
    topic_id = arguments["topic_id"]

    try:
        status = svc.get_status(topic_id)
    except Exception as exc:
        return {"success": False, "error": f"orchestrator_status failed: {exc}"}

    conn = db.connect()
    try:
        gaps_row = conn.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN cross_verified = 1 THEN 1 ELSE 0 END) AS verified "
            "FROM gaps WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        live_candidates = conn.execute(
            "SELECT COUNT(*) AS n FROM research_candidates "
            "WHERE scope = ? AND status IN ('candidate', 'active')",
            (f"topic:{topic_id}",),
        ).fetchone()
        promoted = conn.execute(
            "SELECT COUNT(*) AS n FROM research_candidates "
            "WHERE scope = ? AND status = 'promoted'",
            (f"topic:{topic_id}",),
        ).fetchone()
    finally:
        conn.close()

    gaps_total = int(gaps_row["total"] or 0) if gaps_row else 0
    gaps_verified = int(gaps_row["verified"] or 0) if gaps_row else 0
    live_n = int(live_candidates["n"] or 0) if live_candidates else 0
    promoted_n = int(promoted["n"] or 0) if promoted else 0

    run = status.get("run", {})
    gate = status.get("gate", {})
    stage = run.get("current_stage", "?")

    next_actions: list[str] = []
    if gaps_total == 0:
        next_actions.append("gap_detect — topic has no gaps yet")
    elif gaps_verified == 0 and gaps_total > 0:
        next_actions.append(
            f"gap_cross_verify — {gaps_total} unverified gaps on this topic"
        )
    if live_n == 0 and gaps_verified > 0:
        next_actions.append(
            "recommendations_generate — verified gaps ready, no live candidates"
        )
    if live_n > 0:
        next_actions.append(
            f"experiment_handoff_prepare — {live_n} live candidates "
            "ready for experiment brief"
        )
    if gate.get("can_advance"):
        next_actions.append(f"orchestrator_advance — gate passed for stage {stage}")

    return {
        "success": True,
        "topic_id": topic_id,
        "stage": stage,
        "gate_decision": gate.get("decision", ""),
        "can_advance": bool(gate.get("can_advance")),
        "gaps": {"total": gaps_total, "cross_verified": gaps_verified},
        "candidates": {"live": live_n, "promoted": promoted_n},
        "next_actions": next_actions,
    }
