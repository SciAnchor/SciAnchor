"""Feedback-reinforcement loop for finished topics (S3).

Records human feedback as reset-safe ``human_feedback_record`` artifacts, maps
open items to a revision plan (which artifacts to invalidate, which stage to
re-enter), applies the plan (scoped supersede + ``resume_run(force_stage=...)``
+ checkpoint context injection), and tracks items open -> addressed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_harness.orchestrator.models import STAGE_NAMES
from research_harness.storage.db import Database

from . import checkpoint as ckpt
from .checkpoint import _utc_now
from .hitl_commands import resolve_state_dir

FEEDBACK_SCHEMA_VERSION = "rh.topic_feedback.v1"
REVISION_PLAN_SCHEMA_VERSION = "rh.revision_plan.v1"
FEEDBACK_CONTEXT_SCHEMA_VERSION = "rh.human_feedback_context.v1"

# Not in ARTIFACT_STAGE_ALIASES, so feedback records never skew
# infer_stage_from_artifacts; human_feedback_record is reset-protected.
FEEDBACK_STAGE = "human_feedback"
FEEDBACK_ARTIFACT_TYPE = "human_feedback_record"
# `record-human-feedback` (self-evolution) writes the same artifact_type under a
# different stage. feedback_list unions it in so human feedback written there is
# not invisible to `rh feedback list` (BUG-006).
SELF_EVOLUTION_FEEDBACK_STAGE = "project_self_evolution"
REVISION_PLAN_ARTIFACT_TYPE = "revision_plan"

TARGET_KINDS = ("section", "claim", "evidence", "experiment")
FEEDBACK_STATUSES = ("open", "addressed", "dismissed")

_WRITE_INVALIDATE_TYPES = (
    "section_draft",
    "draft_pack",
    "final_bundle",
    "final_bundle_quality_report",
    "publication_pack",
    "publication_pack_trace",
    "consistency_resolution",
    "process_summary",
)
_KIND_REENTRY_STAGE = {
    "section": "write",
    "claim": "analyze",
    "evidence": "analyze",
    "experiment": "experiment",
}
_KIND_EXTRA_TYPES: dict[str, tuple[str, ...]] = {
    "claim": (
        "literature_map",
        "topic_knowledge_snapshot",
        "evidence_pack",
        "claim_candidate_set",
    ),
    "evidence": (
        "literature_map",
        "topic_knowledge_snapshot",
        "evidence_pack",
        "claim_candidate_set",
    ),
    "experiment": ("experiment_result", "verified_registry"),
}
_STAGES_FOR_REENTRY = {
    "write": ("write", "analysis"),
    "analyze": ("write", "analysis", "analyze"),
    "experiment": ("write", "analysis", "experiment"),
}


def _error(summary: str) -> dict[str, Any]:
    return {"status": "error", "summary": summary}


def _topic_id(db: Database, topic: str | int) -> int | None:
    from .paper_production_entry import _find_topic

    payload = _find_topic(db, topic)
    return int(payload["id"]) if payload else None


def _service(db: Database):
    from research_harness.orchestrator.service import OrchestratorService

    return OrchestratorService(db)


def _feedback_records(db: Database, topic_id: int) -> list[Any]:
    """S3 topic-revision feedback records (drives revision planning/apply)."""
    from research_harness._workflow.orchestrator.artifacts import ArtifactManager

    return ArtifactManager(db).list_by_topic(
        topic_id,
        stage=FEEDBACK_STAGE,
        artifact_type=FEEDBACK_ARTIFACT_TYPE,
        status="active",
    )


def _self_evolution_feedback_records(db: Database, topic_id: int) -> list[Any]:
    """human_feedback_record artifacts written by record-human-feedback (BUG-006).

    View-only: surfaced by feedback_list but intentionally NOT fed into the S3
    revision planner, which stays scoped to `rh feedback add` items.
    """
    from research_harness._workflow.orchestrator.artifacts import ArtifactManager

    return ArtifactManager(db).list_by_topic(
        topic_id,
        stage=SELF_EVOLUTION_FEEDBACK_STAGE,
        artifact_type=FEEDBACK_ARTIFACT_TYPE,
        status="active",
    )


def _item_view(artifact: Any) -> dict[str, Any]:
    payload = artifact.payload or {}
    return {
        "feedback_artifact_id": artifact.id,
        "target_kind": str(payload.get("target_kind") or ""),
        # self-evolution records carry the human note under different keys
        "target": str(payload.get("target") or payload.get("section") or ""),
        "note": str(payload.get("note") or payload.get("feedback_excerpt") or ""),
        "severity": str(payload.get("severity") or "minor"),
        "status": str(payload.get("status") or "open"),
        "created_at": str(payload.get("created_at") or artifact.created_at),
        "addressed_by_artifact_id": payload.get("addressed_by_artifact_id"),
    }


def feedback_add(
    db: Database,
    *,
    topic: str | int,
    target_kind: str,
    target: str,
    note: str,
    severity: str = "minor",
    actor: str = "human",
) -> dict[str, Any]:
    """Record one feedback item as a reset-safe artifact (items coexist)."""
    if target_kind not in TARGET_KINDS:
        return _error(
            f"invalid target_kind '{target_kind}'; expected one of {', '.join(TARGET_KINDS)}"
        )
    note_text = " ".join(str(note or "").split())
    if not note_text:
        return _error("note must not be empty")
    topic_id = _topic_id(db, topic)
    if topic_id is None:
        return _error(f"topic {topic!r} not found")

    payload = {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "topic_id": topic_id,
        "target_kind": target_kind,
        "target": " ".join(str(target or "").split()),
        "note": note_text,
        "severity": severity if severity in ("minor", "major") else "minor",
        "status": "open",
        "created_at": _utc_now(),
        "addressed_at": "",
        "addressed_by_artifact_id": None,
        "resolution_note": "",
        "actor": actor,
        "source": "rh feedback add",
    }
    artifact = _service(db).record_artifact(
        topic_id=topic_id,
        stage=FEEDBACK_STAGE,
        artifact_type=FEEDBACK_ARTIFACT_TYPE,
        title=f"feedback: {target_kind}:{payload['target']}"[:120],
        payload=payload,
        propagate_stale_from_previous=False,
        supersede_previous=False,
    )
    return {
        "status": "success",
        "summary": f"feedback recorded as artifact #{artifact.id}",
        "topic_id": topic_id,
        "feedback_artifact_id": artifact.id,
        "item": _item_view(artifact),
        "next_commands": [f"rh feedback plan --topic {topic_id}"],
    }


def feedback_list(
    db: Database,
    *,
    topic: str | int,
    status: str = "open",
) -> dict[str, Any]:
    """List feedback items, filtered by payload status (open|addressed|dismissed|all)."""
    topic_id = _topic_id(db, topic)
    if topic_id is None:
        return _error(f"topic {topic!r} not found")
    records = list(_feedback_records(db, topic_id))
    records += _self_evolution_feedback_records(db, topic_id)
    items = [_item_view(artifact) for artifact in records]
    if status != "all":
        items = [item for item in items if item["status"] == status]
    return {
        "status": "success",
        "topic_id": topic_id,
        "filter": status,
        "count": len(items),
        "items": items,
        "open_count": sum(1 for item in items if item["status"] == "open")
        if status == "all"
        else (len(items) if status == "open" else None),
    }


def build_revision_plan(
    db: Database,
    *,
    topic: str | int,
    record: bool = True,
) -> dict[str, Any]:
    """Map open feedback items to a re-entry stage + invalidation set."""
    topic_id = _topic_id(db, topic)
    if topic_id is None:
        return _error(f"topic {topic!r} not found")
    open_items = [
        _item_view(artifact)
        for artifact in _feedback_records(db, topic_id)
        if str((artifact.payload or {}).get("status") or "open") == "open"
    ]
    if not open_items:
        return _error(
            f"no open feedback for topic {topic_id}; add some with rh feedback add"
        )

    kinds = {item["target_kind"] for item in open_items}
    reentry_candidates = [
        _KIND_REENTRY_STAGE.get(kind, "write") for kind in sorted(kinds)
    ]
    reentry_stage = min(reentry_candidates, key=STAGE_NAMES.index)

    invalidate_types: set[str] = set(_WRITE_INVALIDATE_TYPES)
    for kind in kinds:
        invalidate_types.update(_KIND_EXTRA_TYPES.get(kind, ()))
    sections = [
        item["target"]
        for item in open_items
        if item["target_kind"] == "section" and item["target"]
    ]
    sections_scope = sections if kinds == {"section"} else []

    instruction_lines = [
        "Address the following human feedback explicitly in the revision:"
    ]
    for item in open_items:
        instruction_lines.append(
            f"- [{item['severity']}] {item['target_kind']}:{item['target'] or '(general)'} — {item['note']}"
        )
    plan_payload = {
        "schema_version": REVISION_PLAN_SCHEMA_VERSION,
        "topic_id": topic_id,
        "feedback_artifact_ids": [item["feedback_artifact_id"] for item in open_items],
        "reentry_stage": reentry_stage,
        "invalidate": {
            "stages": list(_STAGES_FOR_REENTRY[reentry_stage]),
            "types": sorted(invalidate_types),
            "sections": sections_scope,
        },
        "stage_context_injection": {
            "human_feedback_context": {
                "schema_version": FEEDBACK_CONTEXT_SCHEMA_VERSION,
                "feedback_items": open_items,
                "sections_scope": sections_scope,
                "instructions": "\n".join(instruction_lines),
            }
        },
        "created_at": _utc_now(),
    }

    plan_artifact_id: int | None = None
    if record:
        artifact = _service(db).record_artifact(
            topic_id=topic_id,
            stage=FEEDBACK_STAGE,
            artifact_type=REVISION_PLAN_ARTIFACT_TYPE,
            title=f"revision plan: reenter {reentry_stage} ({len(open_items)} items)",
            payload=plan_payload,
            propagate_stale_from_previous=False,
        )
        plan_artifact_id = artifact.id

    return {
        "status": "success",
        "summary": (
            f"revision plan: re-enter {reentry_stage}, invalidate "
            f"{len(plan_payload['invalidate']['types'])} artifact types"
            + (f", sections {sections_scope}" if sections_scope else "")
        ),
        "topic_id": topic_id,
        "plan_artifact_id": plan_artifact_id,
        "plan": plan_payload,
        "next_commands": [
            f"rh feedback apply --topic {topic_id} --dry-run",
            f"rh feedback apply --topic {topic_id}",
        ],
    }


def _load_plan(
    db: Database, topic_id: int, plan_artifact_id: int | None
) -> dict[str, Any] | None:
    from research_harness._workflow.orchestrator.artifacts import ArtifactManager

    manager = ArtifactManager(db)
    if plan_artifact_id is not None:
        artifact = manager.get(plan_artifact_id)
        if (
            artifact is None
            or artifact.topic_id != topic_id
            or artifact.artifact_type != REVISION_PLAN_ARTIFACT_TYPE
        ):
            return None
        return artifact.payload
    latest = manager.get_latest(topic_id, FEEDBACK_STAGE, REVISION_PLAN_ARTIFACT_TYPE)
    return latest.payload if latest is not None else None


def apply_revision_plan(
    db: Database,
    *,
    topic: str | int,
    plan_artifact_id: int | None = None,
    base_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply a revision plan: scoped supersede, force re-entry, inject context."""
    from research_harness._workflow.execution.artifact_reset import (
        supersede_manuscript_artifacts,
    )
    from research_harness._workflow.execution.compiled_summary import (
        invalidate_topic_summary,
    )

    topic_id = _topic_id(db, topic)
    if topic_id is None:
        return _error(f"topic {topic!r} not found")
    plan = _load_plan(db, topic_id, plan_artifact_id)
    if plan is None:
        built = build_revision_plan(db, topic=topic_id, record=not dry_run)
        if built.get("status") != "success":
            return built
        plan = built["plan"]
        plan_artifact_id = built.get("plan_artifact_id")

    invalidate = plan.get("invalidate") or {}
    reentry_stage = str(plan.get("reentry_stage") or "write")
    reset = supersede_manuscript_artifacts(
        db,
        topic_id=topic_id,
        stages=[str(stage) for stage in invalidate.get("stages") or []],
        types={str(item) for item in invalidate.get("types") or []},
        sections=[str(item) for item in invalidate.get("sections") or []] or None,
        dry_run=dry_run,
    )
    if dry_run:
        return {
            "status": "success",
            "summary": (
                f"dry-run: would supersede {len(reset['superseded'])} artifacts "
                f"and re-enter {reentry_stage}"
            ),
            "topic_id": topic_id,
            "dry_run": True,
            "reentry_stage": reentry_stage,
            "reset": reset,
            "plan_artifact_id": plan_artifact_id,
        }

    svc = _service(db)
    run = svc.get_run(topic_id)
    mode = str(run.mode) if run is not None else "standard"
    svc.resume_run(topic_id, mode=mode, force_stage=reentry_stage)

    state_dir = resolve_state_dir(base_dir, db_path=db.db_path)
    checkpoint_path = ckpt.checkpoint_path(state_dir, topic_id)
    checkpoint_data = ckpt.load_checkpoint(checkpoint_path)
    if checkpoint_data is None:
        checkpoint_data = ckpt.new_checkpoint(topic_id, mode=mode)
    ckpt.update_stage(checkpoint_data, stage=reentry_stage, state="pending")
    checkpoint_data["current_stage_attempt"] = 1
    stage_context = checkpoint_data.setdefault("stage_context", {})
    injection = (plan.get("stage_context_injection") or {}).get(
        "human_feedback_context"
    )
    if isinstance(injection, dict):
        stage_context["human_feedback_context"] = injection
    ckpt.record_event(
        checkpoint_data,
        stage=reentry_stage,
        event="feedback_reinforcement_applied",
        detail=(
            f"reenter {reentry_stage}; superseded {len(reset['superseded'])} artifacts; "
            f"feedback items {plan.get('feedback_artifact_ids')}"
        ),
    )
    ckpt.save_checkpoint(checkpoint_path, checkpoint_data)
    invalidate_topic_summary(db, topic_id)

    return {
        "status": "success",
        "summary": (
            f"re-entered {reentry_stage}; superseded {len(reset['superseded'])} "
            "artifacts; feedback context injected"
        ),
        "topic_id": topic_id,
        "dry_run": False,
        "reentry_stage": reentry_stage,
        "reset": reset,
        "plan_artifact_id": plan_artifact_id,
        "checkpoint_path": str(checkpoint_path),
        "next_commands": [f"rh paper-production resume --topic {topic_id}"],
    }


def feedback_address(
    db: Database,
    *,
    topic: str | int,
    feedback_artifact_id: int,
    addressed_by_artifact_id: int | None = None,
    note: str = "",
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Mark one feedback item addressed; clears checkpoint context at zero open."""
    from research_harness._workflow.orchestrator.artifacts import ArtifactManager

    topic_id = _topic_id(db, topic)
    if topic_id is None:
        return _error(f"topic {topic!r} not found")
    manager = ArtifactManager(db)
    artifact = manager.get(feedback_artifact_id)
    if (
        artifact is None
        or artifact.topic_id != topic_id
        or artifact.artifact_type != FEEDBACK_ARTIFACT_TYPE
    ):
        return _error(
            f"artifact {feedback_artifact_id} is not a feedback record of topic {topic_id}"
        )
    updated = manager.update_payload_fields(
        feedback_artifact_id,
        {
            "status": "addressed",
            "addressed_at": _utc_now(),
            "addressed_by_artifact_id": addressed_by_artifact_id,
            "resolution_note": " ".join(str(note or "").split()),
        },
    )

    open_left = [
        item
        for item in _feedback_records(db, topic_id)
        if str((item.payload or {}).get("status") or "open") == "open"
    ]
    context_cleared = False
    if not open_left:
        state_dir = resolve_state_dir(base_dir, db_path=db.db_path)
        checkpoint_path = ckpt.checkpoint_path(state_dir, topic_id)
        checkpoint_data = ckpt.load_checkpoint(checkpoint_path)
        if checkpoint_data is not None:
            stage_context = checkpoint_data.get("stage_context")
            if isinstance(stage_context, dict) and stage_context.pop(
                "human_feedback_context", None
            ):
                ckpt.record_event(
                    checkpoint_data,
                    stage=str(checkpoint_data.get("current_stage") or "write"),
                    event="human_feedback_context_cleared",
                    detail="all feedback items addressed",
                )
                ckpt.save_checkpoint(checkpoint_path, checkpoint_data)
                context_cleared = True

    return {
        "status": "success",
        "summary": f"feedback #{feedback_artifact_id} marked addressed",
        "topic_id": topic_id,
        "item": _item_view(updated) if updated is not None else None,
        "open_remaining": len(open_left),
        "feedback_context_cleared": context_cleared,
    }
