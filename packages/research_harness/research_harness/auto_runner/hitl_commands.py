"""Transport-neutral HITL paper-production commands.

These implement the nine public MCP tools (``topic_init`` and the
``paper_production_*`` family) as plain core functions so the service layer
can back them. Ported from the MCP-side executors; response dicts keep the
same envelope shape those executors returned, because
``_execute_service_backed_convenience`` hands ``ServiceResult.output`` back
to MCP clients verbatim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_harness.config import default_state_dir
from research_harness.storage.db import Database

from . import checkpoint as ckpt
from .interaction_mode import (
    default_action_for_decision,
    interaction_mode_description,
)

INTERACTION_MODES = ("autonomous", "checkpoint", "interactive")


def resolve_state_dir(
    base_dir: Path | None = None,
    *,
    db_path: Path | str | None = None,
) -> Path:
    """Resolve the state dir, preferring the tree adjacent to the effective DB."""
    if base_dir is not None:
        return base_dir
    return default_state_dir(db_path)


def _error(summary: str, next_actions: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": "error",
        "summary": summary,
        "output": {},
        "next_actions": next_actions or [],
    }


def topic_init(
    db: Database,
    *,
    name: str,
    description: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create (or reuse) a research topic by name and return its id."""
    topic_name = " ".join(str(name or "").split())
    if not topic_name:
        return _error("topic name must not be empty")
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id, description FROM topics WHERE name = ?",
            (topic_name,),
        ).fetchone()
        if row is not None:
            topic_id = int(row["id"])
            created = False
            stored_description = str(row["description"] or "")
        else:
            cur = conn.execute(
                "INSERT INTO topics (name, description) VALUES (?, ?)",
                (topic_name, description or topic_name),
            )
            topic_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT OR IGNORE INTO projects (topic_id, name, description)
                VALUES (?, ?, ?)
                """,
                (topic_id, "paper-production", description or topic_name),
            )
            conn.commit()
            created = True
            stored_description = description or topic_name
    finally:
        conn.close()

    output: dict[str, Any] = {
        "topic_id": topic_id,
        "name": topic_name,
        "description": stored_description,
        "created": created,
    }
    if tags:
        # topics has no tags column; echo them so callers see they were read.
        output["tags"] = list(tags)
        output["tags_persisted"] = False
    return {
        "status": "success",
        "summary": (
            f"{'Created' if created else 'Reusing existing'} topic "
            f"'{topic_name}' with ID {topic_id}"
        ),
        "output": output,
        "next_actions": [
            f"Add seed papers: paper_ingest(..., topic_id={topic_id})",
            (
                f"Start workflow: paper_production_start(topic_id={topic_id}, "
                "target_venue='...')"
            ),
        ],
    }


def paper_production_start(
    db: Database,
    *,
    topic_id: int,
    target_venue: str,
    interaction_mode: str = "checkpoint",
    paper_mode: str = "main",
    budget: float = 100.0,
    local_only: bool = False,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Prepare topic/run/checkpoint state for a paper-production workflow."""
    from .paper_production_entry import prepare_paper_production_entry

    if interaction_mode not in INTERACTION_MODES:
        return _error(
            f"invalid interaction_mode: {interaction_mode}; "
            f"expected one of {', '.join(INTERACTION_MODES)}"
        )
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT name, description FROM topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return _error(
            f"topic {topic_id} not found",
            next_actions=["Create it first: topic_init(name='...')"],
        )

    if paper_mode != "main":
        return _error(f"invalid paper_mode: {paper_mode}; expected 'main'")
    result = prepare_paper_production_entry(
        # Pass the topic_id (the row above already proved it exists). The entry
        # resolves id/name/description via _find_topic before creating, so a
        # numeric id round-trips to the same topic instead of the description
        # spawning a duplicate topic (BUG-001 / I-4A).
        db=db,
        topic=str(topic_id),
        target_venue=target_venue,
        # paper_mode is the WRITING mode; the entry's mode is the RUN mode
        # (explore|standard|strict|demo). They travel as separate parameters.
        mode="standard",
        paper_mode=paper_mode,
        interaction_mode=interaction_mode,
        base_dir=resolve_state_dir(base_dir, db_path=db.db_path),
        local_only=local_only,
    )

    return {
        "status": "success",
        "summary": (
            f"Started paper production for topic {topic_id} "
            f"(mode: {interaction_mode}, venue: {target_venue})"
        ),
        "output": {
            "topic_id": topic_id,
            "target_venue": target_venue,
            "interaction_mode": interaction_mode,
            "paper_mode": paper_mode,
            "budget": budget,
            "current_stage": (result.get("run") or {}).get("current_stage", "init"),
            "entry": result,
        },
        "next_actions": [
            "Check status: paper_production_status(topic_id=...)",
            "If decision pending: paper_production_decide(...)",
            "Continue workflow: paper_production_resume(topic_id=...)",
        ],
    }


def paper_production_pending_decisions(
    topic_id: int,
    *,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Get pending human decision requests for a paper-production workflow."""
    state_dir = resolve_state_dir(base_dir)
    ckpt_path = ckpt.checkpoint_path(state_dir, topic_id)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)

    if checkpoint_data is None:
        return {
            "schema_version": "rh.pending_decisions.v1",
            "status": "error",
            "topic_id": topic_id,
            "has_pending": False,
            "message": f"No checkpoint found for topic {topic_id}",
        }

    human_decision = checkpoint_data.get("human_decision")
    if not isinstance(human_decision, dict) or not human_decision.get("requested"):
        return {
            "schema_version": "rh.pending_decisions.v1",
            "status": "no_pending_decisions",
            "topic_id": topic_id,
            "has_pending": False,
            "current_stage": checkpoint_data.get("current_stage"),
        }

    prompt = human_decision.get("prompt", "")
    options = human_decision.get("options", [])
    reason_code = human_decision.get("reason_code", "")

    run_policy = checkpoint_data.get("paper_production_run_policy", {})
    interaction_mode = run_policy.get("interaction_mode", "checkpoint")

    recommended_action = None
    default_action = None
    for opt in options:
        if opt.get("recommended"):
            recommended_action = opt.get("action")
        if opt.get("default_action"):
            default_action = opt.get("action")

    auto_action = default_action_for_decision(interaction_mode, options)

    return {
        "schema_version": "rh.pending_decisions.v1",
        "status": "pending_decision",
        "topic_id": topic_id,
        "has_pending": True,
        "decision": {
            "request_id": human_decision.get("request_id"),
            "stage": human_decision.get("stage"),
            "checkpoint": human_decision.get("checkpoint"),
            "reason_code": reason_code,
            "prompt": prompt,
            "options": options,
            "recommended_action": recommended_action,
            "default_action": default_action,
            "auto_action_if_autonomous": auto_action,
            "interaction_mode": interaction_mode,
        },
        "next_commands": [
            (
                f"Use paper_production_decide(topic_id={topic_id}, "
                f"choice='{opt.get('action')}', reasoning='...')"
            )
            for opt in options[:3]
        ],
    }


def paper_production_decide(
    db: Database,
    *,
    topic_id: int,
    choice: str,
    reasoning: str = "",
    base_dir: Path | None = None,
    actor: str = "service",
) -> dict[str, Any]:
    """Record a human decision and unblock the paused workflow."""
    from .runner import decide_human_checkpoint

    result = decide_human_checkpoint(
        topic_id=topic_id,
        choice=choice,
        reasoning=reasoning,
        base_dir=resolve_state_dir(base_dir, db_path=db.db_path),
        db=db,
        actor=actor,
    )

    if result.get("status") == "accepted":
        result["next_steps"] = [
            f"Decision '{choice}' recorded successfully",
            f"Resume workflow with: paper_production_resume(topic_id={topic_id})",
            f"Or check status: paper_production_status(topic_id={topic_id})",
        ]
    return result


def paper_production_status(
    db: Database,
    *,
    topic_id: int,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Detailed workflow status: orchestrator state, decisions, mode."""
    from research_harness.orchestrator.service import OrchestratorService

    state_dir = resolve_state_dir(base_dir, db_path=db.db_path)
    orchestrator_status = OrchestratorService(db).get_status(topic_id)
    decisions = paper_production_pending_decisions(topic_id, base_dir=state_dir)
    ckpt_path = ckpt.checkpoint_path(state_dir, topic_id)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)
    if checkpoint_data:
        run_policy = checkpoint_data.get("paper_production_run_policy", {})
        mode = run_policy.get("interaction_mode", "checkpoint")
    else:
        mode = "unknown"

    return {
        "status": "success",
        "summary": f"Status for topic {topic_id}",
        "output": {
            "orchestrator": orchestrator_status,
            "pending_decisions": decisions,
            "interaction_mode": mode,
            "mode_description": interaction_mode_description(mode),
        },
        "next_actions": _status_next_actions(orchestrator_status, decisions),
    }


def _status_next_actions(
    orchestrator_status: dict[str, Any],
    pending_decisions: dict[str, Any],
) -> list[str]:
    if pending_decisions.get("has_pending"):
        return ["Make decision: paper_production_decide(...)"]

    gate_info = orchestrator_status.get("gate", {})
    run_info = orchestrator_status.get("run", {})
    if gate_info.get("can_advance"):
        return ["Continue workflow: paper_production_resume(...)"]
    if run_info.get("stage_status") == "complete":
        return ["Check missing artifacts in status output"]
    return ["Investigate blockers or wait for stage completion"]


def paper_production_resume(
    db: Database,
    *,
    topic_id: int,
    auto_approve: bool = False,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Resume a paused workflow, optionally auto-applying a pending decision."""
    from .runner import resume_topic

    state_dir = resolve_state_dir(base_dir)

    if auto_approve:
        decisions = paper_production_pending_decisions(topic_id, base_dir=state_dir)
        if decisions.get("has_pending"):
            decision = decisions.get("decision") or {}
            choice = decision.get("recommended_action") or decision.get(
                "default_action"
            )
            if choice:
                paper_production_decide(
                    db,
                    topic_id=topic_id,
                    choice=str(choice),
                    reasoning="Auto-applied via auto_approve",
                    base_dir=state_dir,
                    actor="auto_approve",
                )

    result = resume_topic(
        topic_id=topic_id,
        base_dir=state_dir,
        auto_approve=auto_approve,
        db=db,
    )

    return {
        "status": "success",
        "summary": f"Resumed workflow for topic {topic_id}",
        "output": result,
        "next_actions": [
            "Check progress: paper_production_status(topic_id=...)",
        ],
    }


def paper_production_mode(
    topic_id: int,
    *,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Get the current interaction mode for a topic's workflow."""
    state_dir = resolve_state_dir(base_dir)
    ckpt_path = ckpt.checkpoint_path(state_dir, topic_id)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)

    if not checkpoint_data:
        return _error("No checkpoint found")

    run_policy = checkpoint_data.get("paper_production_run_policy", {})
    mode = run_policy.get("interaction_mode", "checkpoint")

    return {
        "status": "success",
        "summary": f"Current mode: {mode}",
        "output": {
            "topic_id": topic_id,
            "interaction_mode": mode,
            "description": interaction_mode_description(mode),
            "can_auto_decide": mode == "autonomous",
        },
        "next_actions": [],
    }


def paper_production_set_mode(
    topic_id: int,
    *,
    mode: str,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Change the interaction mode for a running workflow."""
    if mode not in INTERACTION_MODES:
        return _error(
            f"invalid interaction mode: {mode}; "
            f"expected one of {', '.join(INTERACTION_MODES)}"
        )
    state_dir = resolve_state_dir(base_dir)
    ckpt_path = ckpt.checkpoint_path(state_dir, topic_id)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)

    if not checkpoint_data:
        return _error("No checkpoint found for topic")

    run_policy = checkpoint_data.setdefault("paper_production_run_policy", {})
    old_mode = run_policy.get("interaction_mode", "checkpoint")
    run_policy["interaction_mode"] = mode
    run_policy["autonomous_completion"] = mode == "autonomous"

    ckpt.record_event(
        checkpoint_data,
        stage=checkpoint_data.get("current_stage", "unknown"),
        event="interaction_mode_changed",
        detail=f"{old_mode} → {mode}",
    )
    ckpt.save_checkpoint(ckpt_path, checkpoint_data)

    return {
        "status": "success",
        "summary": f"Changed mode from {old_mode} to {mode}",
        "output": {
            "topic_id": topic_id,
            "old_mode": old_mode,
            "new_mode": mode,
            "description": interaction_mode_description(mode),
        },
        "next_actions": [
            "Resume with new mode: paper_production_resume(topic_id=...)",
        ],
    }


def paper_production_export(
    db: Database,
    *,
    topic_id: int,
    format: str = "both",
    include_artifacts: bool = True,
) -> dict[str, Any]:
    """Export generated paper paths from the recorded write-stage artifacts.

    Reads the active draft_pack/final_bundle artifacts instead of guessing a
    filesystem layout, so it works wherever the manuscript was written.
    """
    from research_harness.orchestrator.service import OrchestratorService

    svc = OrchestratorService(db)
    files: dict[str, Any] = {}

    draft = svc.get_latest_artifact(topic_id, "write", "draft_pack")
    bundle = svc.get_latest_artifact(topic_id, "write", "final_bundle")
    if format in ("latex", "both") and draft is not None and draft.path:
        files["latex"] = [draft.path]
    if format in ("pdf", "both") and bundle is not None and bundle.path:
        files["pdf"] = [bundle.path]

    artifacts: dict[str, Any] = {}
    if include_artifacts:
        for artifact_type in (
            "figure_plan",
            "process_summary",
            "publication_pack",
            "final_bundle_quality_report",
        ):
            artifact = svc.get_latest_artifact(topic_id, "write", artifact_type)
            if artifact is not None:
                artifacts[artifact_type] = {
                    "artifact_id": artifact.id,
                    "version": artifact.version,
                    "path": artifact.path,
                }

    if not files and not artifacts:
        return _error(
            "No generated paper found",
            next_actions=[
                "Complete workflow first: paper_production_resume(...)",
            ],
        )

    return {
        "status": "success",
        "summary": f"Exported paper for topic {topic_id}",
        "output": {
            "files": files,
            "artifacts": artifacts,
        },
        "next_actions": [
            "Review the recorded TeX/PDF paths",
        ],
    }
