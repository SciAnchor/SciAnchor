"""Convenient local entry helpers for paper-production runs."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from research_harness.config import default_state_dir
from research_harness.orchestrator.service import OrchestratorService
from research_harness.storage.db import Database

from . import checkpoint as ckpt
from .interaction_mode import resolve_interaction_mode
from .paper_production_context import build_paper_production_runtime_context


SCHEMA_VERSION = "rh.paper_production_entry.v1"
PAPER_PLAN_SCHEMA_VERSION = "rh.paper_plan.v1"
PAPER_PRODUCTION_CROSSWALK_SCHEMA_VERSION = "rh.paper_production_stage_crosswalk.v1"
EXECUTION_PREVIEW_SCHEMA_VERSION = "rh.paper_production_execution_preview.v1"
EXECUTION_CHAIN_PREVIEW_SCHEMA_VERSION = (
    "rh.paper_production_execution_chain_preview.v1"
)
CONTROL_ARTIFACT_PREVIEW_SCHEMA_VERSION = (
    "rh.paper_production_control_artifact_preview.v1"
)
RUN_SCHEMA_VERSION = "rh.paper_production_run.v1"
SYNC_STATUSES = (
    "RH_SYNCED",
    "RH_SYNC_PENDING",
    "RH_PENDING_TOPIC_ID",
    "RH_BLOCKED_BY_GATE",
    "RH_STALE",
)

PAPER_PRODUCTION_STAGE_CROSSWALK: tuple[dict[str, Any], ...] = (
    {
        "pw_stage": "PW01_TOPIC_AND_VENUE_CONTRACT",
        "orchestrator_stage": "init",
        "required_artifacts": (
            "PAPER_PLAN",
            "PAPER_PROFILE",
            "TARGET_VENUE_PROFILE",
        ),
        "skills": ("research-init", "research-harness", "rh-paper-production"),
        "required_gates": ("topic_scope_profile_gate",),
        "repair_action": "revise PAPER_PLAN, topic scope, or venue profile",
    },
    {
        "pw_stage": "PW02_EVIDENCE_ACQUISITION_AND_READING",
        "orchestrator_stage": "build",
        "required_artifacts": (
            "PAPER_POOL",
            "LITERATURE_MAP",
            "SEARCH_PROVENANCE",
            "CITATION_TRACE_REPORT",
        ),
        "skills": ("literature-search", "literature-mapping", "citation-trace"),
        "required_gates": ("coverage_gate", "provenance_gate"),
        "repair_action": "expand literature search, ingest papers, or trace citations",
    },
    {
        "pw_stage": "PW03_GAP_BASELINE_NOVELTY_VALIDATION",
        "orchestrator_stage": "analyze",
        "required_artifacts": (
            "EVIDENCE_PACK",
            "CLAIM_CANDIDATE_SET",
            "LIMITATION_REGISTER",
        ),
        "skills": ("claim-extraction", "evidence-gating"),
        "required_gates": ("evidence_admissibility_gate",),
        "repair_action": "repair unsupported claims or add admissible evidence",
    },
    {
        "pw_stage": "PW04_EXPERIMENT_AND_RESULT_TO_CLAIM",
        "orchestrator_stage": "experiment",
        "required_artifacts": (
            "EXPERIMENT_SPEC",
            "EXPERIMENT_RESULT",
            "RESULT_TO_CLAIM_ANALYSIS_PROFILE",
        ),
        "skills": ("evidence-gating", "manuscript-math-formalization"),
        "required_gates": ("reproducibility_gate", "result_to_claim_gate"),
        "repair_action": "rerun experiments or repair result-to-claim support",
    },
    {
        "pw_stage": "PW05_PAPER_PLAN_AND_LOGIC_GATES",
        "orchestrator_stage": "write",
        "required_artifacts": (
            "PAPER_PLAN",
            "LOGIC_GATE_REPORT",
            "CONTRIBUTION_MAP",
        ),
        "skills": ("manuscript-logic-gate", "paper-writing"),
        "required_gates": ("manuscript_logic_gate",),
        "repair_action": "revise paper plan, contribution map, or manuscript logic",
    },
    {
        "pw_stage": "PW06_SECTION_DRAFTING_AND_REVISION",
        "orchestrator_stage": "write",
        "required_artifacts": ("MANUSCRIPT_DRAFT", "SECTION_REVISION_TRACE"),
        "skills": ("paper-writing", "paper-verify"),
        "required_gates": ("section_logic_gate",),
        "repair_action": "revise drafted sections against the argument tree",
    },
    {
        "pw_stage": "PW07_FIGURE_TABLE_SOURCE_AND_CITATION_INTEGRITY",
        "orchestrator_stage": "write",
        "required_artifacts": (
            "FIGURE_SPEC",
            "FIGURE_ASSET",
            "SKELETON_SOURCE_INTEGRITY_PROFILE",
        ),
        "skills": ("rh-paper-figure-generator", "figure-quality", "provenance-review"),
        "required_gates": ("figure_quality_gate", "provenance_gate"),
        "repair_action": "repair figures, tables, citations, or source integrity",
    },
    {
        "pw_stage": "PW08_LATEX_FINAL_BUNDLE_AND_PDF",
        "orchestrator_stage": "write",
        "required_artifacts": ("LATEX_SOURCE", "FINAL_BUNDLE"),
        "skills": ("paper-writing", "final-bundle-quality"),
        "required_gates": ("final_bundle_gate",),
        "repair_action": "repair LaTeX source or final bundle generation",
    },
    {
        "pw_stage": "PW09_PRESUBMISSION_AUDIT_AND_PUBLICATION_PACK",
        "orchestrator_stage": "write",
        "required_artifacts": ("PUBLICATION_PACK", "PRESUBMISSION_AUDIT_REPORT"),
        "skills": ("publication-pack", "final-bundle-quality"),
        "required_gates": ("publication_readiness_gate",),
        "repair_action": "repair publication pack or presubmission audit blockers",
    },
    {
        "pw_stage": "PW10_REBUTTAL_CAMERA_READY_AND_REPLAY",
        "orchestrator_stage": "write",
        "required_artifacts": ("REBUTTAL_PACK", "CAMERA_READY_BUNDLE", "REPLAY_REPORT"),
        "skills": ("paper-verify", "publication-pack", "rh-self-evolution"),
        "required_gates": ("camera_ready_gate", "replay_gate"),
        "repair_action": "repair rebuttal, camera-ready bundle, or replay evidence",
    },
)


def plan_paper_production_entry(
    *,
    topic: str,
    target_venue: str,
    mode: str = "standard",
    local_only: bool = False,
) -> dict[str, Any]:
    """Return the public entry payload without mutating local state."""

    topic_text = _clean_text(topic)
    venue_text = _clean_text(target_venue)
    runtime_context = build_paper_production_runtime_context(
        topic=topic_text,
        target_venue=venue_text,
        local_only=local_only,
    )
    return _entry_payload(
        action="planned",
        topic_payload={
            "id": None,
            "name": topic_text,
            "description": topic_text,
            "target_venue": venue_text,
            "created": False,
        },
        run_payload={
            "id": None,
            "current_stage": "init",
            "stage_status": "not_created",
        },
        checkpoint_payload={"path": "", "exists": False},
        runtime_context=runtime_context.to_dict(),
        stage_context=runtime_context.to_stage_context(),
        execution_payload={
            "will_execute": False,
            "reason": "plan is side-effect-free",
        },
        next_commands=[
            (
                "rh paper-production start --topic "
                f"{shlex.quote(topic_text)} --target-venue {shlex.quote(venue_text)}"
            )
        ],
        mode=mode,
    )


def prepare_paper_production_entry(
    *,
    db: Database,
    topic: str,
    target_venue: str,
    mode: str = "standard",
    interaction_mode: str | None = None,
    base_dir: Path | None = None,
    execute: bool = False,
    local_only: bool = False,
    paper_mode: str = "main",
) -> dict[str, Any]:
    """Create or reuse local topic/run/checkpoint state for paper production.

    ``execute`` is accepted to keep the entry contract future-compatible. PP04
    deliberately does not run the auto-runner or external providers.

    ``paper_mode`` is the WRITING mode (``main``) and is orthogonal to ``mode``
    (the run mode: explore|standard|strict|demo). It lands in the run policy so
    the runner, gates, and export path can see it.
    """

    del execute
    topic_text = _clean_text(topic)
    venue_text = _clean_text(target_venue)
    # Resolve an existing topic by id / name / description before creating one.
    # Callers pass heterogeneous values: MCP passes a numeric topic_id, the CLI
    # passes raw --topic text, service handlers pass names. _ensure_topic matches
    # on name only, so without this an id ("16") or a free-text description would
    # spawn a duplicate topic (BUG-001 / I-4A).
    topic_payload = _find_topic(db, topic_text)
    if topic_payload is None:
        topic_payload = _ensure_topic(db, topic=topic_text, target_venue=venue_text)
    elif venue_text and str(topic_payload.get("target_venue") or "") != venue_text:
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE topics SET target_venue = ? WHERE id = ?",
                (venue_text, int(topic_payload["id"])),
            )
            conn.commit()
        finally:
            conn.close()
        topic_payload["target_venue"] = venue_text

    svc = OrchestratorService(db)
    run = svc.resume_run(int(topic_payload["id"]), mode=mode)
    runtime_context = build_paper_production_runtime_context(
        topic=str(topic_payload["description"] or topic_payload["name"]),
        target_venue=str(topic_payload["target_venue"]),
        local_only=local_only,
    )
    paper_plan_artifact = _record_initial_paper_plan(
        svc=svc,
        topic_id=int(topic_payload["id"]),
        run_id=run.id,
        topic=topic_text,
        target_venue=venue_text,
        mode=mode,
        runtime_context=runtime_context.to_dict(),
        stage_context=runtime_context.to_stage_context(),
        local_only=local_only,
    )
    status = svc.get_status(int(topic_payload["id"]))
    state_dir = _resolve_base_dir(base_dir, db_path=db.db_path)
    checkpoint_path = ckpt.checkpoint_path(state_dir, int(topic_payload["id"]))
    checkpoint_data = ckpt.load_checkpoint(checkpoint_path)
    if checkpoint_data is None:
        checkpoint_data = ckpt.new_checkpoint(int(topic_payload["id"]), mode=mode)
    checkpoint_data["mode"] = mode
    checkpoint_data["current_stage"] = run.current_stage
    checkpoint_data["stage_state"] = "pending"

    # Resolve unified interaction mode
    interaction_mode = resolve_interaction_mode(
        mode=mode, interaction_mode=interaction_mode
    )

    if paper_mode != "main":
        raise ValueError(f"unsupported paper_mode: {paper_mode!r}; expected 'main'")
    writing_mode = "main"
    if mode == "demo":
        evidence_boundary = "demo_limited_seed_pool"
    else:
        evidence_boundary = "strict_evidence_pool"
    checkpoint_data["paper_production_run_policy"] = {
        "schema_version": "rh.paper_production_run_policy.v2",
        "interaction_mode": interaction_mode,
        "autonomous_completion": interaction_mode == "autonomous",
        "stop_on_gate_failure": True,
        "mode": mode,  # Keep for backward compatibility
        "paper_mode": paper_mode,
        "writing_mode": writing_mode,
        "evidence_boundary": evidence_boundary,
        "local_only": local_only,
        # BUG-015: a durable per-topic compute constraint (e.g. remote_only)
        # travels with the run policy so the runner/agents honor it instead of
        # relying on chat/file prose.
        "compute_location": str(topic_payload.get("compute_location") or ""),
        "external_actions": [],
    }
    checkpoint_data["stage_context"].update(runtime_context.to_stage_context())
    checkpoint_data["stage_context"]["paper_production_run_policy"] = dict(
        checkpoint_data["paper_production_run_policy"]
    )
    checkpoint_data["stage_context"]["paper_production_runtime_context"] = (
        runtime_context.to_dict()
    )
    ckpt.record_event(
        checkpoint_data,
        stage=run.current_stage,
        event="paper_production_entry_prepared",
        detail="topic and target venue context prepared for local runner",
    )
    ckpt.save_checkpoint(checkpoint_path, checkpoint_data)

    return _entry_payload(
        action="prepared",
        topic_payload=topic_payload,
        run_payload={
            "id": run.id,
            "current_stage": run.current_stage,
            "stage_status": run.stage_status,
            "active_paper_plan_artifact_id": paper_plan_artifact.id,
            "gate_status": status.get("gate", {}).get("decision", "not_evaluated"),
            "sync_status": "RH_SYNCED",
        },
        checkpoint_payload={
            "path": str(checkpoint_path),
            "exists": checkpoint_path.exists(),
        },
        runtime_context=runtime_context.to_dict(),
        stage_context=runtime_context.to_stage_context(),
        execution_payload={
            "will_execute": False,
            "reason": "start prepares local DB/run/checkpoint only",
        },
        next_commands=[
            f"rh auto-runner start --topic-id {topic_payload['id']} --mode {mode}"
        ],
        mode=mode,
    )


PREFLIGHT_SCHEMA_VERSION = "rh.paper_production_preflight.v1"


def preflight_paper_production_topic(
    *,
    db: Database,
    topic: str | int,
    base_dir: Path | None = None,
    workspace_dir: Path | None = None,
    duplicate_workspace_dir: Path | None = None,
) -> dict[str, Any]:
    """Inspect local paper-production state without executing pipeline stages."""

    topic_payload = _find_topic(db, topic)
    state_dir = _resolve_base_dir(base_dir, db_path=db.db_path)
    workspace = Path(workspace_dir).expanduser() if workspace_dir is not None else None
    duplicate_workspace = (
        Path(duplicate_workspace_dir).expanduser()
        if duplicate_workspace_dir is not None
        else None
    )
    blockers: list[str] = []
    warnings: list[str] = []

    if workspace is not None and not workspace.exists():
        blockers.append("missing_workspace")
    if duplicate_workspace is not None and duplicate_workspace.exists():
        warnings.append("duplicate_workspace_ambiguity")

    checkpoint_payload: dict[str, Any] = {
        "path": "",
        "exists": False,
        "parseable": False,
        "current_stage": None,
        "stage_state": None,
    }
    status_payload: dict[str, Any] = {}
    classification = "missing_topic"

    if topic_payload is None:
        blockers.append("missing_topic")
    else:
        topic_id = int(topic_payload["id"])
        checkpoint_path = ckpt.checkpoint_path(state_dir, topic_id)
        checkpoint_payload.update(
            {
                "path": str(checkpoint_path),
                "exists": checkpoint_path.exists(),
            }
        )
        checkpoint_data = ckpt.load_checkpoint(checkpoint_path)
        if not checkpoint_path.exists():
            blockers.append("missing_checkpoint")
        if checkpoint_path.exists() and checkpoint_data is None:
            blockers.append("malformed_checkpoint")
        if checkpoint_data is not None:
            checkpoint_payload.update(
                {
                    "parseable": True,
                    "current_stage": checkpoint_data.get("current_stage"),
                    "stage_state": checkpoint_data.get("stage_state"),
                    "mode": checkpoint_data.get("mode"),
                }
            )

        svc = OrchestratorService(db)
        run = svc.get_run(topic_id)
        if run is None:
            blockers.append("missing_orchestrator_run")
            classification = "missing_orchestrator_run"
        else:
            status_payload = svc.get_status(topic_id)
            run_payload = status_payload.get("run", {})
            if (
                checkpoint_data is not None
                and checkpoint_data.get("current_stage")
                and run_payload.get("current_stage")
                and checkpoint_data.get("current_stage")
                != run_payload.get("current_stage")
            ):
                blockers.append("db_checkpoint_mismatch")
            if (
                checkpoint_data is not None
                and checkpoint_data.get("mode")
                and run_payload.get("mode")
                and checkpoint_data.get("mode") != run_payload.get("mode")
            ):
                blockers.append("db_checkpoint_mismatch")
                warnings.append("checkpoint_run_mode_mismatch")
            stage_payload = status_payload.get("stage", {})
            gate_payload = status_payload.get("gate", {})
            missing = stage_payload.get("missing_artifacts") or []
            reasons = gate_payload.get("reasons") or []
            if missing:
                blockers.append("missing_required_artifacts")
            if gate_payload and not gate_payload.get("can_advance", False):
                blockers.append("gate_blocked")
            if "db_checkpoint_mismatch" in blockers:
                classification = "db_checkpoint_mismatch"
            elif "malformed_checkpoint" in blockers:
                classification = "malformed_checkpoint"
            elif "missing_workspace" in blockers:
                classification = "missing_workspace"
            elif missing:
                classification = "missing_required_artifacts"
            elif reasons or "gate_blocked" in blockers:
                classification = "gate_blocked"
            else:
                classification = "ready_for_single_stage_dry_run"

    workspace_artifacts = _workspace_artifact_probe(workspace)
    if workspace_artifacts.get("topic_brief") and status_payload:
        missing_artifacts = (
            status_payload.get("stage", {}).get("missing_artifacts", [])
            if isinstance(status_payload.get("stage"), dict)
            else []
        )
        if "topic_brief" in missing_artifacts:
            warnings.append("workspace_topic_brief_not_synced_to_db")

    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "topic": topic_payload,
        "workspace": {
            "path": str(workspace) if workspace is not None else "",
            "exists": bool(workspace and workspace.exists()),
            "duplicate_path": str(duplicate_workspace)
            if duplicate_workspace is not None
            else "",
            "duplicate_exists": bool(
                duplicate_workspace is not None and duplicate_workspace.exists()
            ),
            "artifacts": workspace_artifacts,
        },
        "state": {
            "base_dir": str(state_dir),
            "db_path": str(getattr(db, "db_path", "")),
        },
        "checkpoint": checkpoint_payload,
        "orchestrator": status_payload,
        "classification": classification,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "external_actions": [],
    }


def run_paper_production_entry(
    *,
    db: Database,
    topic: str,
    target_venue: str,
    mode: str = "standard",
    base_dir: Path | None = None,
    dry_run: bool = True,
    auto_approve: bool = False,
    local_only: bool = False,
) -> dict[str, Any]:
    """Prepare local paper-production state and invoke the real auto-runner."""

    prepared = prepare_paper_production_entry(
        db=db,
        topic=topic,
        target_venue=target_venue,
        mode=mode,
        base_dir=base_dir,
        local_only=local_only,
    )
    topic_payload = prepared.get("topic", {})
    topic_id = int(topic_payload.get("id", 0)) if isinstance(topic_payload, dict) else 0
    if not topic_id:
        return {
            "schema_version": RUN_SCHEMA_VERSION,
            "action": "blocked",
            "prepared": prepared,
            "runner": {},
            "blockers": ["missing_topic_id"],
            "external_actions": [],
        }

    from .runner import run_topic

    runner_result = run_topic(
        topic_id,
        direction=str(topic_payload.get("description") or topic)
        if isinstance(topic_payload, dict)
        else topic,
        mode=mode,
        auto_approve=auto_approve,
        base_dir=base_dir,
        dry_run=dry_run,
        db=db,
    )
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "action": "dry_run" if dry_run else "run",
        "prepared": prepared,
        "runner": runner_result,
        "blockers": [],
        "external_actions": [],
    }


def preview_paper_production_execution(
    *,
    db: Database,
    topic_id: int,
    base_dir: Path,
    mode: str = "demo",
    stage: str = "init",
) -> dict[str, Any]:
    """Run a local fake-tool execution preview from a prepared checkpoint."""

    checkpoint_path = ckpt.checkpoint_path(base_dir, topic_id)
    checkpoint_data = ckpt.load_checkpoint(checkpoint_path)
    if checkpoint_data is None:
        return {
            "schema_version": EXECUTION_PREVIEW_SCHEMA_VERSION,
            "status": "blocked",
            "stage": stage,
            "topic_id": topic_id,
            "checkpoint": {"path": str(checkpoint_path), "exists": False},
            "blockers": ["missing_checkpoint"],
            "external_actions": [],
        }

    svc = OrchestratorService(db)
    run = svc.resume_run(topic_id, mode=mode)

    def fake_tool_executor(**kwargs: Any) -> dict[str, Any]:
        tool_preview = _fake_tool_preview(
            stage=str(kwargs.get("stage") or stage or run.current_stage),
            checkpoint_data=kwargs["checkpoint_data"],
        )
        return {
            "summary": "Paper-production execution preview completed with fake tools.",
            "tool_results": [tool_preview],
            "errors": [],
            "preview_tool_result": tool_preview,
        }

    from .stage_executor import execute_stage

    stage_result = execute_stage(
        db=db,
        svc=svc,
        topic_id=topic_id,
        stage=stage or run.current_stage,
        mode=mode,
        checkpoint_data=checkpoint_data,
        base_dir=base_dir,
        tool_executor=fake_tool_executor,
    )
    ckpt.save_checkpoint(checkpoint_path, checkpoint_data)
    trace_summary = _trace_summary(checkpoint_data)
    tool_results = stage_result.get("tool_results", [])
    if not isinstance(tool_results, list):
        tool_results = []
    preview_tool_result = _preview_tool_result_from_checkpoint(checkpoint_data)

    return {
        "schema_version": EXECUTION_PREVIEW_SCHEMA_VERSION,
        "status": stage_result.get("status", "unknown"),
        "stage": stage or run.current_stage,
        "topic_id": topic_id,
        "checkpoint": {
            "path": str(checkpoint_path),
            "exists": checkpoint_path.exists(),
        },
        "stage_result": stage_result,
        "tool_preview": preview_tool_result,
        "trace_summary": trace_summary,
        "blockers": [],
        "external_actions": [],
    }


def preview_paper_production_execution_chain(
    *,
    db: Database,
    topic_id: int,
    base_dir: Path,
    mode: str = "demo",
    stages: tuple[str, ...] = ("init", "build"),
) -> dict[str, Any]:
    """Run a local fake-tool preview across multiple paper-production stages."""

    checkpoint_path = ckpt.checkpoint_path(base_dir, topic_id)
    checkpoint_data = ckpt.load_checkpoint(checkpoint_path)
    if checkpoint_data is None:
        return {
            "schema_version": EXECUTION_CHAIN_PREVIEW_SCHEMA_VERSION,
            "status": "blocked",
            "topic_id": topic_id,
            "stages": list(stages),
            "checkpoint": {"path": str(checkpoint_path), "exists": False},
            "stage_results": [],
            "tool_previews": [],
            "control_artifacts": [],
            "trace_summary": {"event_count": 0, "events": [], "step_count": 0},
            "blockers": ["missing_checkpoint"],
            "external_actions": [],
        }

    svc = OrchestratorService(db)
    svc.resume_run(topic_id, mode=mode)

    stage_results: list[dict[str, Any]] = []
    tool_previews: list[dict[str, Any]] = []
    control_artifacts: list[dict[str, Any]] = []

    from .stage_executor import execute_stage

    for stage in stages:

        def fake_tool_executor(**kwargs: Any) -> dict[str, Any]:
            current_stage = str(kwargs.get("stage") or stage)
            tool_preview = _fake_tool_preview(
                stage=current_stage,
                checkpoint_data=kwargs["checkpoint_data"],
            )
            control_artifact = _control_artifact_preview(
                stage=current_stage,
                checkpoint_data=kwargs["checkpoint_data"],
            )
            if control_artifact:
                _append_control_artifact_preview(
                    kwargs["checkpoint_data"],
                    control_artifact,
                )
                tool_preview.update(
                    {
                        "control_artifact_type": control_artifact["artifact_type"],
                        "next_control_action": "evidence_acquisition_fake_ready",
                    }
                )
            return {
                "summary": (
                    "Paper-production execution chain preview completed fake "
                    f"{current_stage} tools."
                ),
                "tool_results": [tool_preview],
                "errors": [],
                "preview_tool_result": tool_preview,
                "control_artifact_preview": control_artifact,
            }

        stage_result = execute_stage(
            db=db,
            svc=svc,
            topic_id=topic_id,
            stage=stage,
            mode=mode,
            checkpoint_data=checkpoint_data,
            base_dir=base_dir,
            tool_executor=fake_tool_executor,
        )
        stage_results.append(stage_result)
        tool_previews.append(
            _fake_tool_preview(stage=stage, checkpoint_data=checkpoint_data)
        )
        control_artifact = _control_artifact_preview(
            stage=stage,
            checkpoint_data=checkpoint_data,
        )
        if control_artifact and control_artifact not in control_artifacts:
            control_artifacts.append(control_artifact)
        ckpt.record_event(
            checkpoint_data,
            stage=stage,
            event="paper_production_chain_stage_complete",
            detail=f"fake stage preview status={stage_result.get('status', 'unknown')}",
        )
        if stage_result.get("status") != "complete":
            ckpt.save_checkpoint(checkpoint_path, checkpoint_data)
            return {
                "schema_version": EXECUTION_CHAIN_PREVIEW_SCHEMA_VERSION,
                "status": "blocked",
                "topic_id": topic_id,
                "stages": list(stages),
                "checkpoint": _checkpoint_preview_summary(
                    checkpoint_path,
                    checkpoint_data,
                ),
                "stage_results": stage_results,
                "tool_previews": tool_previews,
                "control_artifacts": control_artifacts,
                "trace_summary": _trace_summary(checkpoint_data),
                "blockers": [f"stage_{stage_result.get('stage', stage)}_not_complete"],
                "external_actions": [],
            }

    checkpoint_control_artifacts = _checkpoint_control_artifacts(checkpoint_data)
    if checkpoint_control_artifacts:
        control_artifacts = checkpoint_control_artifacts
    ckpt.record_event(
        checkpoint_data,
        stage=stages[-1] if stages else "",
        event="paper_production_chain_preview_complete",
        detail=f"stages={','.join(stages)}",
    )
    ckpt.save_checkpoint(checkpoint_path, checkpoint_data)
    return {
        "schema_version": EXECUTION_CHAIN_PREVIEW_SCHEMA_VERSION,
        "status": "complete",
        "topic_id": topic_id,
        "stages": list(stages),
        "checkpoint": _checkpoint_preview_summary(checkpoint_path, checkpoint_data),
        "stage_results": stage_results,
        "tool_previews": tool_previews,
        "control_artifacts": control_artifacts,
        "trace_summary": _trace_summary(checkpoint_data),
        "blockers": [],
        "external_actions": [],
    }


def _entry_payload(
    *,
    action: str,
    topic_payload: dict[str, Any],
    run_payload: dict[str, Any],
    checkpoint_payload: dict[str, Any],
    runtime_context: dict[str, Any],
    stage_context: dict[str, Any],
    execution_payload: dict[str, Any],
    next_commands: list[str],
    mode: str,
) -> dict[str, Any]:
    rh_state = _rh_state(
        topic_payload=topic_payload,
        run_payload=run_payload,
        next_commands=next_commands,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "action": action,
        "mode": mode,
        "topic": topic_payload,
        "run": run_payload,
        "checkpoint": checkpoint_payload,
        "runtime_context": runtime_context,
        "stage_context": stage_context,
        "execution": execution_payload,
        "rh_state": rh_state,
        "next_commands": next_commands,
        "external_actions": [],
    }


def _rh_state(
    *,
    topic_payload: dict[str, Any],
    run_payload: dict[str, Any],
    next_commands: list[str],
) -> dict[str, Any]:
    artifact_id = run_payload.get("active_paper_plan_artifact_id")
    sync_status = str(run_payload.get("sync_status") or "RH_SYNC_PENDING")
    if not topic_payload.get("id"):
        sync_status = "RH_PENDING_TOPIC_ID"
    artifact_ids = [artifact_id] if isinstance(artifact_id, int) else []
    return {
        "topic_id": topic_payload.get("id"),
        "run_id": run_payload.get("id"),
        "stage": run_payload.get("current_stage"),
        "artifact_ids": artifact_ids,
        "gate_result_ids": [],
        "sync_status": sync_status,
        "next_action": next_commands[0] if next_commands else "",
    }


def _record_initial_paper_plan(
    *,
    svc: OrchestratorService,
    topic_id: int,
    run_id: int,
    topic: str,
    target_venue: str,
    mode: str,
    runtime_context: dict[str, Any],
    stage_context: dict[str, Any],
    local_only: bool,
):
    payload = _paper_plan_payload(
        topic_id=topic_id,
        run_id=run_id,
        topic=topic,
        target_venue=target_venue,
        mode=mode,
        runtime_context=runtime_context,
        stage_context=stage_context,
        local_only=local_only,
    )
    return svc.record_artifact(
        topic_id=topic_id,
        stage="init",
        artifact_type="paper_plan",
        title="Durable paper-production intake plan",
        payload=payload,
        metadata={
            "schema_version": PAPER_PLAN_SCHEMA_VERSION,
            "sync_status": "RH_SYNCED",
            "created_from": "paper_production_intake",
        },
    )


def _paper_plan_payload(
    *,
    topic_id: int | None,
    run_id: int | None,
    topic: str,
    target_venue: str,
    mode: str,
    runtime_context: dict[str, Any],
    stage_context: dict[str, Any],
    local_only: bool,
) -> dict[str, Any]:
    paper_profile = runtime_context.get("paper_profile", {})
    required_artifacts = sorted(
        {
            artifact
            for stage in PAPER_PRODUCTION_STAGE_CROSSWALK
            for artifact in stage["required_artifacts"]
        }
    )
    return {
        "schema_version": PAPER_PLAN_SCHEMA_VERSION,
        "topic_id": topic_id,
        "run_id": run_id,
        "raw_user_task": topic,
        "normalized_research_question": topic,
        "target_venue": target_venue,
        "domain_profile": {
            "discipline": paper_profile.get("discipline", ""),
            "research_type": paper_profile.get("research_type", ""),
            "study_design": paper_profile.get("study_design", ""),
            "domain_skill": paper_profile.get("domain_skill", ""),
        },
        "intended_outputs": [
            "PAPER_PLAN",
            "MANUSCRIPT_DRAFT",
            "PUBLICATION_PACK",
            "FINAL_BUNDLE",
        ],
        "stage_crosswalk": _stage_crosswalk_payload(),
        "required_artifacts": required_artifacts,
        "current_stage": "init",
        "validation_policy": {
            "human_eval_default": False,
            "default_methods": [
                "deterministic_gates",
                "artifact_grounded_replay",
                "synthetic_fixtures",
                "rubric_gates",
            ],
        },
        "provenance_policy": {
            "chat_only_progress_allowed": False,
            "evidence_bearing_artifacts_require_provenance": True,
            "sync_statuses": list(SYNC_STATUSES),
        },
        "sync_status": "RH_SYNCED" if topic_id and run_id else "RH_SYNC_PENDING",
        "dependency_artifact_ids": [],
        "stale_dependency_status": "fresh",
        "mode": mode,
        "local_only": local_only,
        "runtime_context_schema_version": runtime_context.get("schema_version", ""),
        "readiness_report": stage_context.get("paper_production_readiness_report", {}),
    }


def _stage_crosswalk_payload() -> list[dict[str, Any]]:
    return [
        {
            "schema_version": PAPER_PRODUCTION_CROSSWALK_SCHEMA_VERSION,
            "pw_stage": str(stage["pw_stage"]),
            "orchestrator_stage": str(stage["orchestrator_stage"]),
            "required_artifacts": list(stage["required_artifacts"]),
            "skills": list(stage["skills"]),
            "required_gates": list(stage["required_gates"]),
            "repair_action": str(stage["repair_action"]),
        }
        for stage in PAPER_PRODUCTION_STAGE_CROSSWALK
    ]


def _preview_tool_result_from_checkpoint(
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    return _fake_tool_preview(
        stage="", checkpoint_data=checkpoint_data, include_stage=False
    )


def _fake_tool_preview(
    *,
    stage: str,
    checkpoint_data: dict[str, Any],
    include_stage: bool = True,
) -> dict[str, Any]:
    context = checkpoint_data.get("stage_context", {})
    runtime_context = {}
    if isinstance(context, dict):
        raw_runtime_context = context.get("paper_production_runtime_context", {})
        if isinstance(raw_runtime_context, dict):
            runtime_context = raw_runtime_context
    preview = {
        "tool": "paper_production_preview",
        "success": True,
        "target_venue": context.get("target_venue", "")
        if isinstance(context, dict)
        else "",
        "paper_production_context_status": runtime_context.get("status", ""),
    }
    if include_stage:
        preview["stage"] = stage
    control_artifact = _control_artifact_preview(
        stage=stage,
        checkpoint_data=checkpoint_data,
    )
    if control_artifact:
        preview.update(
            {
                "control_artifact_type": control_artifact["artifact_type"],
                "next_control_action": "evidence_acquisition_fake_ready",
            }
        )
    return preview


def _control_artifact_preview(
    *,
    stage: str,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any] | None:
    if stage != "build":
        return None
    context = checkpoint_data.get("stage_context", {})
    if not isinstance(context, dict):
        context = {}
    return {
        "schema_version": CONTROL_ARTIFACT_PREVIEW_SCHEMA_VERSION,
        "stage": "build",
        "artifact_type": "evidence_acquisition_control_preview",
        "status": "fake_ready",
        "target_venue": str(context.get("target_venue") or ""),
        "external_actions": [],
    }


def _append_control_artifact_preview(
    checkpoint_data: dict[str, Any],
    control_artifact: dict[str, Any],
) -> None:
    context = checkpoint_data.setdefault("stage_context", {})
    if not isinstance(context, dict):
        checkpoint_data["stage_context"] = {}
        context = checkpoint_data["stage_context"]
    artifacts = context.setdefault("paper_production_control_artifacts", [])
    if not isinstance(artifacts, list):
        artifacts = []
        context["paper_production_control_artifacts"] = artifacts
    if control_artifact not in artifacts:
        artifacts.append(control_artifact)


def _checkpoint_control_artifacts(
    checkpoint_data: dict[str, Any],
) -> list[dict[str, Any]]:
    context = checkpoint_data.get("stage_context", {})
    if not isinstance(context, dict):
        return []
    artifacts = context.get("paper_production_control_artifacts", [])
    if not isinstance(artifacts, list):
        return []
    return [dict(item) for item in artifacts if isinstance(item, dict)]


def _checkpoint_preview_summary(
    checkpoint_path: Path,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    context = checkpoint_data.get("stage_context", {})
    runtime_context = {}
    if isinstance(context, dict):
        raw_runtime_context = context.get("paper_production_runtime_context", {})
        if isinstance(raw_runtime_context, dict):
            runtime_context = raw_runtime_context
    return {
        "path": str(checkpoint_path),
        "exists": checkpoint_path.exists(),
        "current_stage": checkpoint_data.get("current_stage", ""),
        "stage_state": checkpoint_data.get("stage_state", ""),
        "paper_production_context_status": runtime_context.get("status", ""),
    }


def _trace_summary(checkpoint_data: dict[str, Any]) -> dict[str, Any]:
    history = checkpoint_data.get("history", [])
    events: list[str] = []
    if isinstance(history, list):
        events = [
            str(item.get("event"))
            for item in history
            if isinstance(item, dict) and item.get("event")
        ]
    run_trace = checkpoint_data.get("run_trace", {})
    steps = run_trace.get("steps", []) if isinstance(run_trace, dict) else []
    return {
        "event_count": len(events),
        "events": events,
        "step_count": len(steps) if isinstance(steps, list) else 0,
        "run_trace_status": run_trace.get("status", "")
        if isinstance(run_trace, dict)
        else "",
    }


def _workspace_artifact_probe(workspace: Path | None) -> dict[str, str]:
    if workspace is None or not workspace.exists():
        return {}
    candidates = {
        "topic_brief": (
            "00-brief/topic-brief.md",
            "00-task-framing/topic-brief-v0.md",
        ),
        "paper_pool": ("01-literature/paper-pool.md",),
        "literature_map": ("02-synthesis/literature-map.md",),
        "deep_read_synthesis": ("02-synthesis/deep-read-synthesis.md",),
        "dataset_survey": ("03-data/dataset-survey.md",),
        "experiment_design": ("04-experiments/experiment-design.md",),
        "figure_plan": ("05-figures/figure-plan.md",),
        "draft_pack": (
            "06-writing/draft-pack.md",
            "06-draft/draft-pack.md",
        ),
        "quality_report": ("06-writing/quality-report.md",),
        "authorship_statement": ("07-authorship/authorship-statement.md",),
    }
    found: dict[str, str] = {}
    for key, relative_paths in candidates.items():
        for relative in relative_paths:
            path = workspace / relative
            if path.exists():
                found[key] = str(path)
                break
    return found


def _find_topic(db: Database, topic: str | int) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        if isinstance(topic, int) or str(topic).isdigit():
            row = conn.execute(
                "SELECT id, name, description, target_venue, status, compute_location "
                "FROM topics WHERE id = ?",
                (int(topic),),
            ).fetchone()
        else:
            topic_text = _clean_text(str(topic))
            row = conn.execute(
                """
                SELECT id, name, description, target_venue, status, compute_location
                FROM topics
                WHERE name = ? OR description = ?
                ORDER BY id LIMIT 1
                """,
                (topic_text, topic_text),
            ).fetchone()
        if row is None:
            return None
        keys = row.keys()
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "description": str(row["description"] or row["name"]),
            "target_venue": str(row["target_venue"] or ""),
            "status": str(row["status"] or "active"),
            "compute_location": str(
                (row["compute_location"] if "compute_location" in keys else "") or ""
            ),
            "created": False,
        }
    finally:
        conn.close()


def _ensure_topic(
    db: Database,
    *,
    topic: str,
    target_venue: str,
) -> dict[str, Any]:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id, name, description, target_venue FROM topics WHERE name = ?",
            (topic,),
        ).fetchone()
        if row is not None:
            topic_id = int(row["id"])
            if target_venue and row["target_venue"] != target_venue:
                conn.execute(
                    "UPDATE topics SET target_venue = ? WHERE id = ?",
                    (target_venue, topic_id),
                )
                conn.commit()
            return {
                "id": topic_id,
                "name": str(row["name"]),
                "description": str(row["description"] or row["name"]),
                "target_venue": target_venue or str(row["target_venue"] or ""),
                "created": False,
            }

        cur = conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            (topic, topic, target_venue),
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT OR IGNORE INTO projects
                (topic_id, name, description, target_venue)
            VALUES (?, ?, ?, ?)
            """,
            (topic_id, "paper-production", topic, target_venue),
        )
        conn.commit()
        return {
            "id": topic_id,
            "name": topic,
            "description": topic,
            "target_venue": target_venue,
            "created": True,
        }
    finally:
        conn.close()


def _resolve_base_dir(base_dir: Path | None, db_path: Path | None = None) -> Path:
    if base_dir is not None:
        return base_dir
    return default_state_dir(db_path)


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").split())
