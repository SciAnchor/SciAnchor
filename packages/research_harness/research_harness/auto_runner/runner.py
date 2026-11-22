"""Runner — top-level supervisor for autonomous research workflow.

The runner is a deterministic controller that:
1. Loads/creates checkpoint
2. Iterates through orchestrator stages
3. Delegates LLM work to claude-kimi sessions (via MCP)
4. Invokes codex at quality gates
5. Pauses at human checkpoints
6. Persists state after every stage
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from ..config import default_state_dir, load_runtime_config
from ..orchestrator.models import MIN_SEED_PAPER_COUNT
from ..orchestrator.service import OrchestratorService
from ..orchestrator.stages import STAGE_ORDER, next_stage
from ..storage.db import Database
from ..token_accounting import check_stage_budget
from . import checkpoint as ckpt
from .budget import BudgetLimits, BudgetMonitor
from .checkpoint import _utc_now
from .stage_executor import execute_stage
from .stage_policy import get_policy, max_retries, should_execute, should_pause_human

logger = logging.getLogger(__name__)


def _can_auto_approve(stage: str, gate_decision: str | None = None) -> bool:
    """Return whether auto-approval may advance a human checkpoint."""

    policy = get_policy(stage)
    if policy is None:
        return False
    if policy.approval_policy == "human_required" or policy.risk_level == "high":
        return False
    if gate_decision not in (None, "", "pass"):
        return False
    return True


_SKIP_WITHDRAWN_KEY = "pre_execute_skip_withdrawn_stages"


def _skip_withdrawn(checkpoint_data: dict[str, Any], stage: str) -> bool:
    """True when this run already re-ran ``stage`` after a withdrawn skip.

    One retry per stage: the first gate refusal may mean the stage never
    produced what the gate wants, but a second one is a real failure and must
    surface instead of looping.
    """
    withdrawn = checkpoint_data.get(_SKIP_WITHDRAWN_KEY)
    return isinstance(withdrawn, list) and stage in withdrawn


def _mark_skip_withdrawn(checkpoint_data: dict[str, Any], stage: str) -> None:
    withdrawn = checkpoint_data.get(_SKIP_WITHDRAWN_KEY)
    if not isinstance(withdrawn, list):
        withdrawn = []
        checkpoint_data[_SKIP_WITHDRAWN_KEY] = withdrawn
    if stage not in withdrawn:
        withdrawn.append(stage)


def _clear_stale_demo_policy(
    *,
    checkpoint_data: dict[str, Any],
    run_mode: str,
) -> bool:
    """Drop a leftover demo run policy once the orchestrator run is not demo.

    A demo smoke run leaves paper_production_run_policy.mode == "demo" in the
    checkpoint. Mode syncs only updated checkpoint_data["mode"], so a later
    formal resume inherited demo gate overrides and demo evidence boundaries
    from the stale policy.
    """
    if run_mode == "demo":
        return False
    cleared = False
    policy = checkpoint_data.get("paper_production_run_policy")
    if isinstance(policy, dict) and str(policy.get("mode") or "") == "demo":
        checkpoint_data.pop("paper_production_run_policy", None)
        cleared = True
    stage_context = checkpoint_data.get("stage_context")
    if isinstance(stage_context, dict):
        sc_policy = stage_context.get("paper_production_run_policy")
        if isinstance(sc_policy, dict) and str(sc_policy.get("mode") or "") == "demo":
            stage_context.pop("paper_production_run_policy", None)
            cleared = True
    if cleared:
        ckpt.record_event(
            checkpoint_data,
            stage=str(checkpoint_data.get("current_stage") or "init"),
            event="stale_demo_policy_cleared",
            detail=(
                "demo paper_production_run_policy dropped: orchestrator run "
                f"mode is {run_mode or 'unset'}"
            ),
        )
    return cleared


def _sync_checkpoint_with_orchestrator(
    *,
    checkpoint_data: dict[str, Any],
    svc: OrchestratorService,
    topic_id: int,
) -> bool:
    run = svc.get_run(topic_id)
    if run is None:
        return False
    changed = _clear_stale_demo_policy(
        checkpoint_data=checkpoint_data,
        run_mode=str(run.mode or ""),
    )
    db_stage = str(run.current_stage or "init")
    db_state = "blocked" if run.stage_status == "blocked" else "pending"
    db_mode = str(run.mode or checkpoint_data.get("mode") or "standard")
    ckpt_stage = str(checkpoint_data.get("current_stage") or "init")
    ckpt_state = str(checkpoint_data.get("stage_state") or "pending")
    ckpt_mode = str(checkpoint_data.get("mode") or "standard")
    blocked_state_changed = (
        run.stage_status == "blocked" and ckpt_state != "blocked"
    ) or (run.stage_status != "blocked" and ckpt_state == "blocked")
    stage_state_changed = ckpt_stage != db_stage or blocked_state_changed
    mode_changed = ckpt_mode != db_mode
    if not stage_state_changed and not mode_changed:
        return changed
    ckpt.record_event(
        checkpoint_data,
        stage=ckpt_stage,
        event="checkpoint_db_recovery",
        detail=(
            f"checkpoint stage/state/mode {ckpt_stage}/{ckpt_state}/{ckpt_mode} "
            f"realigned to orchestrator {db_stage}/{run.stage_status}/{db_mode}"
        ),
    )
    if stage_state_changed:
        checkpoint_data["current_stage"] = db_stage
        checkpoint_data["stage_state"] = db_state
        checkpoint_data["current_stage_attempt"] = 1
    if mode_changed:
        checkpoint_data["mode"] = db_mode
    return True


def _sync_topic_checkpoint_locked(
    topic_id: int,
    *,
    path: Path,
    resolved_db: Database,
) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        checkpoint_data = loaded if isinstance(loaded, dict) else None
    except (json.JSONDecodeError, OSError):
        checkpoint_data = None
    if checkpoint_data is None:
        return {
            "schema_version": "rh.paper_production_checkpoint_sync.v1",
            "status": "error",
            "topic_id": topic_id,
            "changed": False,
            "error": "checkpoint_not_found",
            "checkpoint_path": str(path),
        }
    if type(checkpoint_data.get("schema_version")) is not int or (
        checkpoint_data["schema_version"] != ckpt.SCHEMA_VERSION
    ):
        return {
            "schema_version": "rh.paper_production_checkpoint_sync.v1",
            "status": "error",
            "topic_id": topic_id,
            "changed": False,
            "error": "checkpoint_schema_mismatch",
            "checkpoint_path": str(path),
        }
    if type(checkpoint_data.get("topic_id")) is not int or (
        checkpoint_data["topic_id"] != topic_id
    ):
        return {
            "schema_version": "rh.paper_production_checkpoint_sync.v1",
            "status": "error",
            "topic_id": topic_id,
            "changed": False,
            "error": "checkpoint_topic_mismatch",
            "checkpoint_path": str(path),
        }

    service = OrchestratorService(resolved_db)
    if service.get_run(topic_id) is None:
        return {
            "schema_version": "rh.paper_production_checkpoint_sync.v1",
            "status": "error",
            "topic_id": topic_id,
            "changed": False,
            "error": "orchestrator_run_not_found",
            "checkpoint_path": str(path),
        }
    if str(checkpoint_data.get("stage_state") or "pending") == "running":
        return {
            "schema_version": "rh.paper_production_checkpoint_sync.v1",
            "status": "error",
            "topic_id": topic_id,
            "changed": False,
            "error": "checkpoint_running",
            "checkpoint_path": str(path),
        }

    before = {
        "stage": str(checkpoint_data.get("current_stage") or "init"),
        "state": str(checkpoint_data.get("stage_state") or "pending"),
        "mode": str(checkpoint_data.get("mode") or "standard"),
    }
    changed = _sync_checkpoint_with_orchestrator(
        checkpoint_data=checkpoint_data,
        svc=service,
        topic_id=topic_id,
    )
    if changed:
        ckpt.save_checkpoint(path, checkpoint_data, acquire_lock=False)
    after = {
        "stage": str(checkpoint_data.get("current_stage") or "init"),
        "state": str(checkpoint_data.get("stage_state") or "pending"),
        "mode": str(checkpoint_data.get("mode") or "standard"),
    }
    return {
        "schema_version": "rh.paper_production_checkpoint_sync.v1",
        "status": "synced" if changed else "unchanged",
        "topic_id": topic_id,
        "changed": changed,
        "before": before,
        "after": after,
        "checkpoint_path": str(path),
    }


def sync_topic_checkpoint(
    topic_id: int,
    *,
    base_dir: Path | None = None,
    db: Database | None = None,
) -> dict[str, Any]:
    """Reconcile a runner checkpoint with its DB run without executing work."""

    resolved_db = db or Database(load_runtime_config().db_path)
    state_dir = base_dir or default_state_dir(resolved_db.db_path)
    path = ckpt.checkpoint_path(state_dir, topic_id)
    with ckpt.checkpoint_lock(path):
        return _sync_topic_checkpoint_locked(
            topic_id,
            path=path,
            resolved_db=resolved_db,
        )


# Kept as aliases for backward compatibility; the definitions live in
# checkpoint.py so every consumer shares one schema-membership source.
_PAPER_PRODUCTION_POLICY_SCHEMAS = ckpt.PAPER_PRODUCTION_POLICY_SCHEMAS
_paper_production_policy = ckpt.paper_production_policy


def _paper_production_gate_block(
    *,
    db: Database,
    topic_id: int,
    stage: str,
    gate_decision: str,
    checkpoint_path: Path,
    checkpoint_data: dict[str, Any] | None = None,
    advance_result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if stage == "build" and gate_decision == "needs_coverage":
        result = dict(advance_result or {})
        gate_details = result.get("gate_details")
        if not isinstance(gate_details, dict):
            gate_details = OrchestratorService(db).check_gate_details(
                topic_id,
                stage=stage,
            )
        recovery_actions = list(
            result.get("recovery_actions") or gate_details.get("recovery_actions") or []
        )
        blockers = [
            str(reason.get("code"))
            for reason in gate_details.get("reasons", [])
            if isinstance(reason, dict) and reason.get("code")
        ]
        if not blockers:
            blockers = ["build_gate_needs_coverage"]
        summary = "Paper-production build gate blocked before analysis: " + ", ".join(
            blockers[:6]
        )
        return {
            "status": "blocked",
            "blocker_code": "paper_production_screening_gate",
            "current_stage": stage,
            "stages_completed": [stage],
            "summary": summary,
            "gate_decision": gate_decision,
            "gate_status": str(result.get("gate_status") or "needs_screening"),
            "stage_status": str(result.get("stage_status") or "blocked"),
            "gate_details": gate_details,
            "recovery_actions": recovery_actions,
            "paper_production_gate": {
                "schema_version": "rh.paper_production_runtime_gate.v1",
                "stage": stage,
                "next_stage": "PW02_EVIDENCE_ACQUISITION_AND_READING",
                "decision": "blocked",
                "blockers": blockers,
                "next_actions": recovery_actions,
            },
            "checkpoint_path": str(checkpoint_path),
        }

    if stage != "init" or gate_decision != "needs_approval":
        return None
    seed_count = _topic_seed_paper_count(db, topic_id)
    blockers: list[str] = []
    if seed_count < MIN_SEED_PAPER_COUNT:
        blockers.append("insufficient_seed_papers")
    if not blockers:
        blockers.append("init_gate_needs_approval")
    summary = "Paper-production evidence gate blocked before build: " + ", ".join(
        blockers
    )
    human_decision = None
    selected = ""
    if isinstance(checkpoint_data, dict):
        existing_decision = checkpoint_data.get("human_decision")
        if isinstance(existing_decision, dict):
            selected = str(existing_decision.get("selected") or "")
    if "insufficient_seed_papers" in blockers and selected != "broaden_search":
        human_decision = _paper_production_evidence_decision_request(
            topic_id=topic_id,
            stage=stage,
            checkpoint="paper_production_evidence_gate",
            reason_code="insufficient_seed_papers",
            seed_count=seed_count,
            minimum_seed_paper_count=MIN_SEED_PAPER_COUNT,
            checkpoint_path=checkpoint_path,
        )
    return {
        "status": "blocked",
        "blocker_code": "paper_production_evidence_gate",
        "current_stage": stage,
        "stages_completed": [stage],
        "summary": summary,
        "gate_decision": gate_decision,
        "human_decision": human_decision,
        "next_commands": _human_decision_next_commands(topic_id, human_decision),
        "paper_production_gate": {
            "schema_version": "rh.paper_production_runtime_gate.v1",
            "stage": stage,
            "next_stage": "PW02_EVIDENCE_ACQUISITION_AND_READING",
            "decision": "blocked",
            "blockers": blockers,
            "seed_paper_count": seed_count,
            "minimum_seed_paper_count": MIN_SEED_PAPER_COUNT,
            "next_actions": [
                "Add or ingest verified local seed papers, then rerun paper-production.",
                "Use non-local provider fanout only when real provider reads are acceptable.",
            ],
        },
        "checkpoint_path": str(checkpoint_path),
    }


def _paper_production_demo_gate_override(
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    gate_decision: str,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any] | None:
    policy = _paper_production_policy(checkpoint_data)
    if not policy:
        return None
    if policy.get("mode") != "demo":
        return None
    if policy.get("evidence_boundary") != "demo_limited_seed_pool":
        return None
    # The stale-policy leak: a demo policy left over from a smoke run must not
    # override gates for a formal resume. The checkpoint mode AND the
    # orchestrator run mode must both still be demo.
    if str(checkpoint_data.get("mode") or "") != "demo":
        return None
    run = svc.get_run(topic_id)
    if run is None or str(run.mode or "") != "demo":
        return None
    if gate_decision not in {"fail", "needs_approval", "warn"}:
        return None

    required_by_stage: dict[str, tuple[str, ...]] = {
        "build": (
            "literature_map",
            "paper_pool_snapshot",
            "citation_expansion_report",
            "acquisition_report",
        ),
        "analyze": (
            "claim_candidate_set",
            "evidence_pack",
            "baseline_matrix",
            "direction_proposal",
        ),
        "propose": ("direction_proposal", "study_spec"),
        "experiment": (
            "experiment_code",
            "experiment_result",
            "verified_registry",
        ),
    }
    required = required_by_stage.get(stage)
    if not required:
        return None

    missing = [
        artifact_type
        for artifact_type in required
        if svc.get_latest_artifact(topic_id, stage, artifact_type) is None
    ]
    if missing:
        return {
            "status": "blocked",
            "stage": stage,
            "gate_decision": gate_decision,
            "missing_artifacts": missing,
        }

    nxt = next_stage(stage)
    if nxt is None:
        return None
    transition = svc.transition_to(
        topic_id,
        nxt,
        actor="auto_runner",
        rationale=(
            "Paper-production demo gate override: evidence-limited artifacts "
            "are sufficient to continue to a not_submission_ready PDF smoke run."
        ),
    )
    if not transition.get("success"):
        return {
            "status": "blocked",
            "stage": stage,
            "gate_decision": gate_decision,
            "error": transition.get("error", "transition failed"),
        }
    ckpt.record_event(
        checkpoint_data,
        stage=stage,
        event="paper_production_demo_gate_override",
        detail=f"gate={gate_decision} -> {nxt}",
    )
    return {
        "status": "advanced",
        "stage": stage,
        "to_stage": nxt,
        "gate_decision": gate_decision,
        "required_artifacts": list(required),
    }


def _paper_production_evidence_decision_request(
    *,
    topic_id: int,
    stage: str,
    checkpoint: str,
    reason_code: str,
    seed_count: int,
    minimum_seed_paper_count: int,
    checkpoint_path: Path,
) -> dict[str, Any]:
    from .decision_helpers import build_decision_option, format_decision_prompt

    # Build v2 options with AI recommendations
    broaden_option = build_decision_option(
        action="broaden_search",
        label="Broaden evidence search",
        description=(
            "Allow RH to continue with expanded provider/search fanout and resume from the checkpoint."
        ),
        recommended=True,
        preference_score=0.85,
        expected_effect=(
            f"May find {minimum_seed_paper_count - seed_count}+ additional papers "
            "from semantic_scholar and pasa"
        ),
        default_action=True,
    )

    stop_option = build_decision_option(
        action="stop",
        label="Stop run",
        description="Keep the run stopped until seed papers are supplied manually.",
        recommended=False,
        preference_score=0.15,
        expected_effect="Workflow pauses until papers are added",
        default_action=False,
    )

    prompt = format_decision_prompt(
        situation=("Paper-production has fewer verified seed papers than required."),
        question="Choose whether RH may broaden evidence acquisition beyond the current local-only pool:",
        context={
            "seed_papers": seed_count,
            "required": minimum_seed_paper_count,
            "shortfall": minimum_seed_paper_count - seed_count,
        },
    )

    return {
        "schema_version": "rh.human_decision_request.v2",
        "requested": True,
        "request_id": f"human.topic.{topic_id}.{stage}.{reason_code}.{_utc_now()}",
        "stage": stage,
        "checkpoint": checkpoint,
        "reason_code": reason_code,
        "prompt": prompt,
        "options": [broaden_option, stop_option],
        "selected": "",
        "decision_status": "pending",
        "reasoning": "",
        "params": {
            "topic_id": topic_id,
            "seed_paper_count": seed_count,
            "minimum_seed_paper_count": minimum_seed_paper_count,
            "checkpoint_path": str(checkpoint_path),
        },
        "created_at": _utc_now(),
        "decided_at": "",
        "auto_selected": False,
        "auto_selection_reason": "",
    }


def _human_decision_next_commands(
    topic_id: int,
    human_decision: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(human_decision, dict) or not human_decision.get("requested"):
        return []
    return [
        f"rh paper-production status --topic {topic_id}",
        (
            f"rh paper-production decide --topic {topic_id} --action broaden_search "
            "--reasoning 'User approved expanded evidence acquisition.'"
        ),
        f"rh paper-production resume --topic {topic_id}",
    ]


def _pending_human_decision_response(
    *,
    topic_id: int,
    checkpoint_data: dict[str, Any],
    checkpoint_path: Path,
) -> dict[str, Any]:
    human_decision = checkpoint_data.get("human_decision")
    summary = str(
        checkpoint_data.get("stage_context", {}).get("summary_md")
        or "Workflow is waiting for a human decision."
    )
    return {
        "status": "paused",
        "topic_id": topic_id,
        "current_stage": checkpoint_data.get("current_stage", ""),
        "stage_state": checkpoint_data.get("stage_state", ""),
        "stages_completed": [],
        "summary": summary,
        "human_decision": human_decision,
        "next_commands": _human_decision_next_commands(topic_id, human_decision),
        "checkpoint_path": str(checkpoint_path),
    }


def _topic_seed_paper_count(db: Database, topic_id: int) -> int:
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT pt.paper_id) AS cnt
            FROM paper_topics pt
            WHERE pt.topic_id = ?
              AND pt.relevance != 'dismissed'
            """,
            (topic_id,),
        ).fetchone()
        return int(row["cnt"]) if row else 0
    finally:
        conn.close()


def run_topic(
    topic_id: int,
    *,
    direction: str = "",
    mode: str = "standard",
    session_command: list[str] | None = None,
    auto_approve: bool = False,
    base_dir: Path | None = None,
    dry_run: bool = False,
    db: Database | None = None,
) -> dict[str, Any]:
    """Run the full research workflow for a topic.

    This is the main entrypoint called by CLI (`rhub auto-runner start`)
    or by the /research-harness skill.

    Returns a dict with:
        status: "completed" | "paused" | "error" | "aborted"
        current_stage: where execution stopped
        stages_completed: list of completed stage names
        summary: human-readable summary
    """
    if db is None:
        config = load_runtime_config()
        db = Database(config.db_path)
        db.migrate()
    svc = OrchestratorService(db)

    if base_dir is None:
        base_dir = default_state_dir(db.db_path)

    cmd = session_command or ["claude-kimi"]
    ckpt_path = ckpt.checkpoint_path(base_dir, topic_id)

    # Load or create checkpoint
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)
    if checkpoint_data is None:
        # Resolve current stage from orchestrator if not provided
        run = svc.get_run(topic_id)
        if run is None:
            return {
                "status": "error",
                "current_stage": "",
                "stages_completed": [],
                "summary": f"No orchestrator run found for topic {topic_id}. "
                "Initialize with: rhub auto-runner start --init",
            }
        checkpoint_data = ckpt.new_checkpoint(
            topic_id,
            mode=mode,
            session_command=cmd,
        )
        # Sync initial stage from orchestrator run if it exists
        if run is not None and run.current_stage and run.current_stage != "init":
            checkpoint_data["current_stage"] = run.current_stage
            logger.info(
                "Resuming from orchestrator stage '%s' for topic %d",
                run.current_stage,
                topic_id,
            )
        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
        logger.info("Created new checkpoint for topic %d", topic_id)

    if _sync_checkpoint_with_orchestrator(
        checkpoint_data=checkpoint_data,
        svc=svc,
        topic_id=topic_id,
    ):
        ckpt.save_checkpoint(ckpt_path, checkpoint_data)

    # Initialize budget monitor
    budget_data = checkpoint_data.get("budget", {})
    policy_json = checkpoint_data.get("policy_json", "{}")
    budget_limits = BudgetLimits.from_policy_json(policy_json)
    budget_monitor = BudgetMonitor.from_checkpoint(budget_data, budget_limits)

    # Store direction in context if provided
    if direction:
        ctx = checkpoint_data.setdefault("stage_context", {})
        ctx["direction"] = direction

    stages_completed: list[str] = []
    current_stage = checkpoint_data.get("current_stage", "init")

    if dry_run:
        return _dry_run(current_stage, mode)

    human_decision = checkpoint_data.get("human_decision")
    if isinstance(human_decision, dict) and human_decision.get("requested"):
        return _pending_human_decision_response(
            topic_id=topic_id,
            checkpoint_data=checkpoint_data,
            checkpoint_path=ckpt_path,
        )

    # Main loop: iterate through stages
    while current_stage is not None:
        logger.info("━━━ Stage: %s ━━━", current_stage)
        ckpt.update_stage(checkpoint_data, stage=current_stage, state="running")
        ckpt.save_checkpoint(ckpt_path, checkpoint_data)

        # Pre-execution planner: should this stage even run?
        # (v2 Step 3.1 / ADR-001 Decision 2)
        exec_decision = should_execute(
            db=db,
            topic_id=topic_id,
            stage=current_stage,
            current_checkpoint_stage=checkpoint_data.get("current_stage"),
        )
        skip_withdrawn_now = False
        if not exec_decision.should_run:
            reason = exec_decision.reason
            notes = "; ".join(exec_decision.advisory_notes) or reason
            logger.info("Skipping stage %s: %s (%s)", current_stage, reason, notes)
            ckpt.record_event(
                checkpoint_data,
                stage=current_stage,
                event="pre_execute_skip",
                detail=f"{reason}: {notes[:180]}",
            )
            try:
                svc.record_decision(
                    topic_id=topic_id,
                    stage=current_stage,
                    checkpoint="pre_execute",
                    choice=f"skip_{reason}",
                    reasoning=notes[:500],
                    actor="auto_runner",
                    origin="auto",
                )
            except Exception as exc:
                logger.warning(
                    "decision_log record failed for skip: %s", exc, exc_info=True
                )
            stages_completed.append(current_stage)
            nxt = next_stage(current_stage)
            if nxt is None:
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                return {
                    "status": "completed",
                    "current_stage": current_stage,
                    "stages_completed": stages_completed,
                    "summary": (
                        f"Workflow completed (final stage {current_stage} "
                        f"skipped: {reason}). "
                        f"{len(stages_completed)} stages passed."
                    ),
                    "checkpoint_path": str(ckpt_path),
                }
            advance_result = svc.advance(topic_id, actor="auto_runner")
            if not advance_result.get("success"):
                gate_decision = str(advance_result.get("gate_decision") or "")
                override = _paper_production_demo_gate_override(
                    svc=svc,
                    topic_id=topic_id,
                    stage=current_stage,
                    gate_decision=gate_decision,
                    checkpoint_data=checkpoint_data,
                )
                if override is None or override.get("status") != "advanced":
                    # The skip said "already done"; the gate says otherwise.
                    # A stage gate can require artifacts the freshness planner
                    # does not track, so trusting the skip here strands the run
                    # in a state that can neither regenerate the missing
                    # artifact nor advance. Withdraw the skip and run the stage
                    # once; a second failure is a real error.
                    if reason != "resumed_past_stage" and not _skip_withdrawn(
                        checkpoint_data, current_stage
                    ):
                        stages_completed.pop()
                        _mark_skip_withdrawn(checkpoint_data, current_stage)
                        ckpt.record_event(
                            checkpoint_data,
                            stage=current_stage,
                            event="pre_execute_skip_withdrawn",
                            detail=(
                                f"gate refused to advance after {reason} skip: "
                                + str(advance_result.get("error", "advance failed"))[
                                    :160
                                ]
                            ),
                        )
                        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                        skip_withdrawn_now = True
                    else:
                        ckpt.update_stage(
                            checkpoint_data,
                            stage=current_stage,
                            state="error",
                            summary_md=(
                                "Pre-execution skip could not advance orchestrator: "
                                + str(advance_result.get("error", "advance failed"))
                            ),
                        )
                        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                        return {
                            "status": "error",
                            "current_stage": current_stage,
                            "stages_completed": stages_completed,
                            "summary": (
                                "Pre-execution skip could not advance orchestrator: "
                                + str(advance_result.get("error", "advance failed"))
                            ),
                            "checkpoint_path": str(ckpt_path),
                        }
            if not skip_withdrawn_now:
                current_stage = nxt
                checkpoint_data["current_stage"] = current_stage
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                continue

        # Per-stage token budget pre-check (v2 Step 3.1)
        budget_enforce = os.environ.get(
            "RESEARCH_HARNESS_STAGE_BUDGET_ENFORCE", "soft"
        ).lower()
        try:
            stage_budget = check_stage_budget(topic_id, current_stage)
            if stage_budget.warning:
                ckpt.record_event(
                    checkpoint_data,
                    stage=current_stage,
                    event="stage_budget_warning"
                    if stage_budget.ok
                    else "stage_budget_hard_cap",
                    detail=stage_budget.warning[:200],
                )
                try:
                    svc.record_decision(
                        topic_id=topic_id,
                        stage=current_stage,
                        checkpoint="pre_execute",
                        choice="budget_warn" if stage_budget.ok else "budget_exceeded",
                        reasoning=stage_budget.warning[:500],
                        actor="auto_runner",
                        origin="auto",
                    )
                except Exception as exc:
                    logger.debug("decision_log for budget failed: %s", exc)
            if not stage_budget.ok and budget_enforce == "hard":
                ckpt.update_stage(
                    checkpoint_data,
                    stage=current_stage,
                    state="needs_human",
                    summary_md=f"Stage budget exceeded: {stage_budget.warning}",
                )
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                return {
                    "status": "paused",
                    "current_stage": current_stage,
                    "stages_completed": stages_completed,
                    "summary": stage_budget.warning or "Stage budget exceeded",
                    "checkpoint_path": str(ckpt_path),
                }
        except Exception as exc:
            logger.warning(
                "check_stage_budget failed for topic=%d stage=%s: %s",
                topic_id,
                current_stage,
                exc,
            )

        # Execute stage
        result = execute_stage(
            db=db,
            svc=svc,
            topic_id=topic_id,
            stage=current_stage,
            mode=mode,
            checkpoint_data=checkpoint_data,
            base_dir=base_dir,
            budget_monitor=budget_monitor,
        )

        status = result.get("status", "error")

        # Budget check after each stage
        budget_result = budget_monitor.check()
        checkpoint_data["budget"] = budget_monitor.to_dict()
        if budget_result.action == "halt":
            ckpt.record_event(
                checkpoint_data,
                stage=current_stage,
                event="budget_halt",
                detail=budget_result.message,
            )
            ckpt.save_checkpoint(ckpt_path, checkpoint_data)
            return {
                "status": "paused",
                "current_stage": current_stage,
                "stages_completed": stages_completed,
                "summary": f"Budget exhausted: {budget_result.message}",
                "budget": budget_monitor.to_dict(),
            }

        if status == "complete":
            stages_completed.append(current_stage)
            ckpt.record_event(
                checkpoint_data,
                stage=current_stage,
                event="advance",
                detail="gate passed",
            )

            # Terminal stage: write is the last stage, no advance needed.
            # But still verify the gate passes (review issues, artifacts).
            if current_stage == "write":
                gate_decision = svc.check_gate(topic_id, stage="write")
                if gate_decision not in ("pass", None):
                    logger.warning("Write gate not passed: %s", gate_decision)
                    ckpt.update_stage(
                        checkpoint_data,
                        stage="write",
                        state="needs_human",
                        summary_md=f"Write gate: {gate_decision}",
                    )
                    ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                    if auto_approve and _can_auto_approve("write", str(gate_decision)):
                        logger.info("Auto-approving write gate (%s)", gate_decision)
                    else:
                        return {
                            "status": "paused",
                            "current_stage": "write",
                            "stages_completed": stages_completed,
                            "summary": f"Write stage complete but gate returned: {gate_decision}",
                            "gate_decision": gate_decision,
                            "checkpoint_path": str(ckpt_path),
                        }

                ckpt.update_stage(checkpoint_data, stage="write", state="complete")
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                return {
                    "status": "completed",
                    "current_stage": "write",
                    "stages_completed": stages_completed,
                    "summary": f"Workflow completed. {len(stages_completed)} stages passed.",
                    "checkpoint_path": str(ckpt_path),
                }

            # Advance orchestrator — only move checkpoint if advance succeeds
            try:
                advance_result = svc.advance(topic_id, actor="auto_runner")
                if advance_result.get("loopback"):
                    loopback_to = str(advance_result.get("to_stage") or "build")
                    logger.warning("orchestrator_advance loopback to %s", loopback_to)
                    ckpt.record_event(
                        checkpoint_data,
                        stage=current_stage,
                        event="loopback",
                        detail=f"→ {loopback_to} (gate-triggered)",
                    )
                    current_stage = loopback_to
                    ckpt.update_stage(
                        checkpoint_data, stage=current_stage, state="pending"
                    )
                    checkpoint_data["current_stage_attempt"] = 1
                    ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                    continue
                if not advance_result.get("success"):
                    error_msg = advance_result.get("error", "advance failed")

                    # Stop-before or gate failure — pause for human
                    if advance_result.get("stop_before"):
                        ckpt.update_stage(
                            checkpoint_data,
                            stage=current_stage,
                            state="needs_human",
                            summary_md=f"Stop-before: {error_msg}",
                        )
                        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                        return {
                            "status": "paused",
                            "current_stage": current_stage,
                            "stages_completed": stages_completed,
                            "summary": error_msg,
                        }

                    gate_decision = str(advance_result.get("gate_decision") or "")
                    if _paper_production_policy(checkpoint_data):
                        override = _paper_production_demo_gate_override(
                            svc=svc,
                            topic_id=topic_id,
                            stage=current_stage,
                            gate_decision=gate_decision,
                            checkpoint_data=checkpoint_data,
                        )
                        if (
                            override is not None
                            and override.get("status") == "advanced"
                        ):
                            current_stage = str(override["to_stage"])
                            ckpt.update_stage(
                                checkpoint_data,
                                stage=current_stage,
                                state="pending",
                            )
                            ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                            continue
                        gate_block = _paper_production_gate_block(
                            db=db,
                            topic_id=topic_id,
                            stage=current_stage,
                            gate_decision=gate_decision,
                            checkpoint_path=ckpt_path,
                            checkpoint_data=checkpoint_data,
                            advance_result=advance_result,
                        )
                        if gate_block is not None:
                            ckpt.update_stage(
                                checkpoint_data,
                                stage=current_stage,
                                state="needs_human",
                                summary_md=str(gate_block["summary"]),
                            )
                            human_decision = gate_block.get("human_decision")
                            if isinstance(human_decision, dict) and human_decision.get(
                                "requested"
                            ):
                                human_decision = ckpt.set_human_decision_request(
                                    checkpoint_data,
                                    stage=str(human_decision["stage"]),
                                    checkpoint=str(human_decision["checkpoint"]),
                                    reason_code=str(human_decision["reason_code"]),
                                    prompt=str(human_decision["prompt"]),
                                    options=list(human_decision["options"]),
                                    params=dict(human_decision.get("params") or {}),
                                )
                                gate_block["human_decision"] = human_decision
                                gate_block["next_commands"] = (
                                    _human_decision_next_commands(
                                        topic_id,
                                        human_decision,
                                    )
                                )
                            ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                            return gate_block

                    # Other advance failure — don't move checkpoint, pause
                    logger.warning("orchestrator_advance blocked: %s", error_msg)
                    ckpt.update_stage(
                        checkpoint_data,
                        stage=current_stage,
                        state="error",
                        summary_md=f"Advance blocked: {error_msg}",
                    )
                    ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                    return {
                        "status": "error",
                        "current_stage": current_stage,
                        "stages_completed": stages_completed,
                        "summary": f"Orchestrator advance blocked: {error_msg}",
                    }
            except Exception as exc:
                logger.warning("orchestrator_advance failed: %s", exc)
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                return {
                    "status": "error",
                    "current_stage": current_stage,
                    "stages_completed": stages_completed,
                    "summary": f"Orchestrator advance exception: {exc}",
                }

            # Move to next stage
            current_stage = next_stage(current_stage)
            if current_stage:
                ckpt.update_stage(checkpoint_data, stage=current_stage, state="pending")
            ckpt.save_checkpoint(ckpt_path, checkpoint_data)
            continue

        if status == "needs_human":
            ckpt.update_stage(
                checkpoint_data,
                stage=current_stage,
                state="needs_human",
                summary_md=result.get("summary", ""),
            )
            ckpt.save_checkpoint(ckpt_path, checkpoint_data)

            if auto_approve:
                if not _can_auto_approve(current_stage, result.get("gate_decision")):
                    return {
                        "status": "paused",
                        "current_stage": current_stage,
                        "stages_completed": stages_completed,
                        "summary": result.get("summary", ""),
                        "gate_decision": result.get("gate_decision", ""),
                        "checkpoint_path": str(ckpt_path),
                    }
                # Auto-approve in demo mode — but still respect advance() result
                try:
                    advance_result = svc.advance(topic_id, actor="auto_runner")
                    if not advance_result.get("success"):
                        error_msg = advance_result.get("error", "advance failed")
                        logger.warning("Auto-approve advance blocked: %s", error_msg)
                        # Don't advance checkpoint — return error to prevent divergence
                        ckpt.update_stage(
                            checkpoint_data,
                            stage=current_stage,
                            state="error",
                            summary_md=f"Auto-approve blocked: {error_msg}",
                        )
                        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                        return {
                            "status": "error",
                            "current_stage": current_stage,
                            "stages_completed": stages_completed,
                            "summary": f"Auto-approve advance blocked: {error_msg}",
                        }
                except Exception as exc:
                    logger.warning("Auto-approve advance failed: %s", exc)
                    ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                    return {
                        "status": "error",
                        "current_stage": current_stage,
                        "stages_completed": stages_completed,
                        "summary": f"Auto-approve advance exception: {exc}",
                    }
                stages_completed.append(current_stage)
                current_stage = next_stage(current_stage)
                if current_stage:
                    ckpt.update_stage(
                        checkpoint_data, stage=current_stage, state="pending"
                    )
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                continue

            return {
                "status": "paused",
                "current_stage": current_stage,
                "stages_completed": stages_completed,
                "summary": result.get("summary", ""),
                "gate_decision": result.get("gate_decision", ""),
                "checkpoint_path": str(ckpt_path),
            }

        if status == "fallback_stage":
            from ..orchestrator.stages import STAGE_REGISTRY

            stage_meta = STAGE_REGISTRY.get(current_stage)
            if stage_meta and stage_meta.fallback_stage:
                fallback = stage_meta.fallback_stage
                logger.warning("Falling back from %s to %s", current_stage, fallback)
                ckpt.record_event(
                    checkpoint_data,
                    stage=current_stage,
                    event="fallback",
                    detail=f"→ {fallback}",
                )
                current_stage = fallback
                ckpt.update_stage(checkpoint_data, stage=current_stage, state="pending")
                checkpoint_data["current_stage_attempt"] = 1
                ckpt.clear_error(checkpoint_data)
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                continue

        if status in ("pause_human", "error"):
            ckpt.update_stage(
                checkpoint_data,
                stage=current_stage,
                state="error",
                summary_md=result.get("summary", ""),
            )
            ckpt.save_checkpoint(ckpt_path, checkpoint_data)
            return {
                "status": "paused" if status == "pause_human" else "error",
                "current_stage": current_stage,
                "stages_completed": stages_completed,
                "summary": result.get("summary", ""),
                "error": result.get("error", ""),
                "checkpoint_path": str(ckpt_path),
            }

        # Retry
        if status == "retry":
            budget_monitor.record_iteration()
            attempt = checkpoint_data.get("current_stage_attempt", 1) + 1
            checkpoint_data["current_stage_attempt"] = attempt
            limit = max_retries(current_stage)
            if attempt > limit + 1:
                logger.error(
                    "Retry limit exhausted for stage %s (attempt %d > %d)",
                    current_stage,
                    attempt,
                    limit + 1,
                )
                ckpt.update_stage(
                    checkpoint_data,
                    stage=current_stage,
                    state="error",
                    summary_md=f"Retry limit exhausted after {attempt - 1} attempts",
                )
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                return {
                    "status": "error",
                    "current_stage": current_stage,
                    "stages_completed": stages_completed,
                    "summary": f"Retry limit exhausted for {current_stage}",
                    "checkpoint_path": str(ckpt_path),
                }
            ckpt.record_event(
                checkpoint_data,
                stage=current_stage,
                event="retry",
                detail=f"attempt {attempt}",
            )
            ckpt.save_checkpoint(ckpt_path, checkpoint_data)
            continue

        # Unknown status
        logger.error("Unknown stage result status: %s", status)
        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
        return {
            "status": "error",
            "current_stage": current_stage,
            "stages_completed": stages_completed,
            "summary": f"Unknown status: {status}",
        }

    # Unreachable under current 6-stage model: write stage exits via terminal
    # branch above.  Guard defensively in case stage ordering changes.
    last = stages_completed[-1] if stages_completed else "unknown"
    ckpt.update_stage(checkpoint_data, stage=last, state="complete")
    ckpt.save_checkpoint(ckpt_path, checkpoint_data)
    return {
        "status": "completed",
        "current_stage": last,
        "stages_completed": stages_completed,
        "summary": f"Workflow completed. {len(stages_completed)} stages passed.",
        "checkpoint_path": str(ckpt_path),
    }


def decide_human_checkpoint(
    topic_id: int,
    *,
    choice: str,
    reasoning: str = "",
    params: dict[str, Any] | None = None,
    base_dir: Path | None = None,
    db: Database | None = None,
    actor: str = "cli",
) -> dict[str, Any]:
    """Record a human decision for a paused checkpoint."""
    if db is None:
        config = load_runtime_config()
        db = Database(config.db_path)
        db.migrate()
    if base_dir is None:
        base_dir = default_state_dir(db.db_path)

    ckpt_path = ckpt.checkpoint_path(base_dir, topic_id)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)
    if checkpoint_data is None:
        return {
            "schema_version": "rh.paper_production_decision.v1",
            "status": "error",
            "topic_id": topic_id,
            "choice": choice,
            "summary": f"No checkpoint found for topic {topic_id}",
            "checkpoint_path": str(ckpt_path),
        }

    try:
        decision = ckpt.record_human_decision(
            checkpoint_data,
            choice=choice,
            reasoning=reasoning,
            params=params,
            decision_status="stopped" if choice == "stop" else "accepted",
        )
    except ValueError as exc:
        return {
            "schema_version": "rh.paper_production_decision.v1",
            "status": "error",
            "topic_id": topic_id,
            "choice": choice,
            "summary": str(exc),
            "checkpoint_path": str(ckpt_path),
        }

    stage = str(decision.get("stage") or checkpoint_data.get("current_stage") or "")
    try:
        OrchestratorService(db).record_decision(
            topic_id=topic_id,
            stage=stage,
            checkpoint=str(decision.get("checkpoint") or "human_decision"),
            choice=choice,
            reasoning=reasoning,
            actor=actor,
            origin="human",
        )
    except Exception as exc:
        logger.warning("decision_log record failed for human decision: %s", exc)

    if choice == "broaden_search":
        policy = checkpoint_data.setdefault("paper_production_run_policy", {})
        if isinstance(policy, dict):
            policy["local_only"] = False
            policy.setdefault("external_actions", [])
        stage_context = checkpoint_data.setdefault("stage_context", {})
        stage_context["local_only"] = False
        evidence_plan = stage_context.get("paper_production_evidence_plan")
        if isinstance(evidence_plan, dict):
            search_parameters = evidence_plan.setdefault("search_parameters", {})
            if isinstance(search_parameters, dict):
                search_parameters["local_only"] = False
                search_parameters["provider_allowlist"] = [
                    "semantic_scholar",
                    "pasa",
                ]
                search_parameters["provider_denylist"] = []
            evidence_plan["provider_mode"] = "expanded_provider_search"
        runtime_context = stage_context.get("paper_production_runtime_context")
        if isinstance(runtime_context, dict):
            plan = runtime_context.get("evidence_acquisition_plan")
            if isinstance(plan, dict):
                plan["provider_mode"] = "expanded_provider_search"
        ckpt.update_stage(checkpoint_data, stage=stage or "init", state="pending")
        ckpt.record_event(
            checkpoint_data,
            stage=stage or "init",
            event="human_decision_applied",
            detail="broaden_search",
        )
        status = "accepted"
        next_commands = [f"rh paper-production resume --topic {topic_id}"]
        summary = (
            "Human decision recorded; paper-production can resume with expanded search."
        )
    elif choice == "stop":
        ckpt.update_stage(checkpoint_data, stage=stage or "init", state="blocked")
        ckpt.record_event(
            checkpoint_data,
            stage=stage or "init",
            event="human_decision_applied",
            detail="stop",
        )
        status = "stopped"
        next_commands = []
        summary = "Human decision recorded; paper-production remains stopped."
    else:
        status = "accepted"
        next_commands = [f"rh paper-production resume --topic {topic_id}"]
        summary = "Human decision recorded."

    ckpt.save_checkpoint(ckpt_path, checkpoint_data)
    return {
        "schema_version": "rh.paper_production_decision.v1",
        "status": status,
        "topic_id": topic_id,
        "choice": choice,
        "summary": summary,
        "human_decision": decision,
        "next_commands": next_commands,
        "checkpoint_path": str(ckpt_path),
    }


def resume_topic(
    topic_id: int,
    *,
    base_dir: Path | None = None,
    auto_approve: bool = False,
    db: Database | None = None,
) -> dict[str, Any]:
    """Resume a paused workflow from checkpoint."""
    if base_dir is None:
        base_dir = default_state_dir(db.db_path if db is not None else None)

    ckpt_path = ckpt.checkpoint_path(base_dir, topic_id)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)
    if checkpoint_data is None:
        return {
            "status": "error",
            "current_stage": "",
            "stages_completed": [],
            "summary": f"No checkpoint found for topic {topic_id}",
        }
    human_decision = checkpoint_data.get("human_decision")
    if isinstance(human_decision, dict) and human_decision.get("requested"):
        return _pending_human_decision_response(
            topic_id=topic_id,
            checkpoint_data=checkpoint_data,
            checkpoint_path=ckpt_path,
        )
    if isinstance(human_decision, dict) and human_decision.get("selected") == "stop":
        return {
            "status": "stopped",
            "topic_id": topic_id,
            "current_stage": checkpoint_data.get("current_stage", ""),
            "stages_completed": [],
            "summary": "Paper-production was stopped by human decision.",
            "human_decision": human_decision,
            "checkpoint_path": str(ckpt_path),
        }

    return run_topic(
        topic_id,
        mode=checkpoint_data.get("mode", "standard"),
        session_command=checkpoint_data.get("session_command"),
        auto_approve=auto_approve,
        base_dir=base_dir,
        db=db,
    )


def get_status(
    topic_id: int,
    *,
    base_dir: Path | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Get current workflow status without executing."""
    if base_dir is None:
        base_dir = default_state_dir(db_path)

    ckpt_path = ckpt.checkpoint_path(base_dir, topic_id)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)
    if checkpoint_data is None:
        return {"status": "not_started", "topic_id": topic_id}

    current = checkpoint_data.get("current_stage", "?")
    state = checkpoint_data.get("stage_state", "?")
    idx = STAGE_ORDER.index(current) + 1 if current in STAGE_ORDER else 0

    human_decision = checkpoint_data.get("human_decision")
    next_commands = _human_decision_next_commands(topic_id, human_decision)
    return {
        "status": state,
        "topic_id": topic_id,
        "current_stage": f"{idx}/{len(STAGE_ORDER)}: {current}",
        "stage_state": state,
        "mode": checkpoint_data.get("mode", "?"),
        "summary": checkpoint_data.get("stage_context", {}).get("summary_md", ""),
        "human_decision": human_decision,
        "next_commands": next_commands,
        "artifacts_recorded": sum(
            len(arts) for arts in checkpoint_data.get("artifacts", {}).values()
        ),
        "history_events": len(checkpoint_data.get("history", [])),
        "last_error": checkpoint_data.get("last_error", {}).get("message", ""),
        "checkpoint_path": str(ckpt_path),
    }


def _dry_run(current_stage: str, mode: str) -> dict[str, Any]:
    """Show what would happen without executing."""
    from .stage_policy import STAGE_POLICIES, should_invoke_codex

    plan = []
    stage = current_stage
    while stage:
        policy = STAGE_POLICIES.get(stage)
        if policy is None:
            break
        plan.append(
            {
                "stage": stage,
                "tools": list(policy.tools),
                "codex": should_invoke_codex(stage, mode),
                "human_pause": should_pause_human(stage, mode),
            }
        )
        stage = next_stage(stage)

    return {
        "status": "dry_run",
        "current_stage": current_stage,
        "stages_completed": [],
        "plan": plan,
        "summary": f"Dry run: {len(plan)} stages from {current_stage}",
    }
