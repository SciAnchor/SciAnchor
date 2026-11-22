"""Stage executor — runs one orchestrator stage through MCP tools.

The executor is called by the supervisor (runner.py) for each stage.
It uses OrchestratorService for DB operations and the MCP tools layer
for research primitives.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..knowledge.research_wiki_preflight import (
    action_name_for_workflow_stage,
    run_research_wiki_preflight,
)
from ..orchestrator.service import OrchestratorService
from ..storage.db import Database
from . import checkpoint as ckpt
from .codex_bridge import (
    load_handoff_response,
    run_codex_review,
    save_handoff_request,
    save_handoff_response,
)
from .interaction_mode import resolve_interaction_mode, should_pause_for_decision
from .stage_policy import (
    decide_recovery,
    get_policy,
    should_invoke_codex,
    should_pause_human,
)

if TYPE_CHECKING:
    from .budget import BudgetMonitor

logger = logging.getLogger(__name__)

# Tools that require LLM-constructed arguments and always return success=False
# from tool_dispatch. These are excluded from "all tools failed" detection.
_DEFERRED_TOOLS = frozenset(
    {
        "adversarial_run",
        "adversarial_resolve",
        "adversarial_review",
        "integrity_check",
        "review_add_issue",
        "review_respond",
    }
)

_STAGE_CONTEXT_CARRY_FORWARD_KEYS = frozenset(
    {
        "direction",
        "topic_id",
        "target_venue",
        "venue",
        "target_profile",
        "topic_venue_contract",
        "venue_overlay",
        "paper_profile",
        "domain_method_search_profile",
        "paper_plan_requirements",
        "paper_production_state_machine",
        "paper_production_completion_condition",
        "paper_production_readiness_report",
        "paper_production_next_stage",
        "paper_production_next_action",
        "paper_production_evidence_plan",
        "max_results",
        "auto_ingest",
        "local_only",
        "per_provider_limit",
        "provider_allowlist",
        "provider_denylist",
        "tier_filter",
        "venue_filter",
        "required_baseline_families",
        "experiment_grounding_profile",
        "result_to_claim_analysis_profile",
        "paper_plan_gate_profile",
        "paper_production_closure_plan",
        "sections_to_draft",
        "template",
        "publication_components",
        "record_artifact",
        "citation_quota",
        "output_dir",
        "paper_plan_ready",
        "strict_evidence",
        "next_actions",
        "paper_production_context_status",
        "paper_production_context_blockers",
        "paper_production_runtime_context",
        "paper_production_run_policy",
        "research_wiki_preflight",
        "human_feedback_context",
    }
)


def _apply_human_feedback_context(checkpoint_data: dict[str, Any], stage: str) -> None:
    """Re-assert human feedback directives AFTER the planner runs.

    plan_stage() output is merged with stage_context.update(planned), which
    can clobber sections_to_draft/extra_instructions; feedback directives must
    win, so they are applied post-planner.
    """
    context = checkpoint_data.get("stage_context")
    if not isinstance(context, dict):
        return
    feedback_context = context.get("human_feedback_context")
    if not isinstance(feedback_context, dict):
        return
    instructions = str(feedback_context.get("instructions") or "").strip()
    if instructions:
        existing = str(context.get("extra_instructions") or "").strip()
        if instructions not in existing:
            context["extra_instructions"] = (
                f"{existing}\n\n{instructions}" if existing else instructions
            )
    sections_scope = feedback_context.get("sections_scope")
    if stage == "write" and isinstance(sections_scope, list) and sections_scope:
        context["sections_to_draft"] = [str(item) for item in sections_scope]
    ckpt.record_event(
        checkpoint_data,
        stage=stage,
        event="human_feedback_context_applied",
        detail=(
            f"items={len(feedback_context.get('feedback_items') or [])} "
            f"sections={list(sections_scope or [])[:4]}"
        ),
    )


def execute_stage(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    mode: str,
    checkpoint_data: dict[str, Any],
    base_dir: Path,
    budget_monitor: "BudgetMonitor | None" = None,
    tool_executor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one stage's tools and return the outcome.

    The executor runs tools and (optionally) codex review. It does NOT
    check the orchestrator gate — that responsibility belongs to runner.py
    via advance(), which is the single source of truth for stage transitions.

    Returns a dict with:
        status: "complete" | "needs_human" | "error" | "retry" | "fallback_stage" | "pause_human"
        stage: current stage name
        summary: one-line result
        error: error details if failed
    """
    policy = get_policy(stage)
    if policy is None:
        return {"status": "error", "stage": stage, "summary": f"Unknown stage: {stage}"}

    ckpt.update_stage(checkpoint_data, stage=stage, state="running")
    ckpt.record_event(
        checkpoint_data, stage=stage, event="stage_start", detail=policy.description
    )

    # Reset stage_context to prevent stale key leakage between stages.
    # Preserve only cross-stage keys that are explicitly carried forward.
    checkpoint_data["stage_context"] = _carried_forward_stage_context(
        checkpoint_data.get("stage_context", {})
    )
    _record_research_wiki_preflight(
        db=db,
        topic_id=topic_id,
        stage=stage,
        checkpoint_data=checkpoint_data,
    )

    # LLM Planner: enrich stage_context before tool execution
    from .llm_planner import plan_stage

    try:
        planned = plan_stage(
            db=db,
            svc=svc,
            topic_id=topic_id,
            stage=stage,
            checkpoint_data=checkpoint_data,
        )
        if planned:
            checkpoint_data["stage_context"].update(planned)
            ckpt.record_event(
                checkpoint_data,
                stage=stage,
                event="planner_ok",
                detail=f"keys={sorted(planned.keys())[:8]}",
            )
    except Exception as exc:
        logger.warning("LLM planner failed for stage %s: %s", stage, exc, exc_info=True)
        ckpt.record_event(
            checkpoint_data, stage=stage, event="planner_error", detail=str(exc)[:200]
        )

    _apply_human_feedback_context(checkpoint_data, stage)

    # Execute stage tools via orchestrator service
    try:
        executor = tool_executor or _execute_stage_tools
        result = executor(
            db=db,
            svc=svc,
            topic_id=topic_id,
            stage=stage,
            checkpoint_data=checkpoint_data,
            budget_monitor=budget_monitor,
        )
    except Exception as exc:
        error_msg = str(exc)
        ckpt.record_error(checkpoint_data, kind="exception", message=error_msg)
        ckpt.record_event(
            checkpoint_data, stage=stage, event="tool_error", detail=error_msg[:200]
        )

        retry_count = checkpoint_data.get("last_error", {}).get("retry_count", 0)
        recovery = decide_recovery(stage, "exception", retry_count)
        return {
            "status": recovery,
            "stage": stage,
            "summary": f"Stage failed: {error_msg[:200]}",
            "error": error_msg,
        }

    # Record tool errors in checkpoint for visibility
    tool_errors = result.get("errors", [])
    if tool_errors:
        ckpt.record_event(
            checkpoint_data,
            stage=stage,
            event="tool_errors",
            detail=f"{len(tool_errors)} tool(s) failed: {'; '.join(tool_errors[:3])}"[
                :200
            ],
        )

    # Track artifact IDs from orchestrator_record_artifact results
    for tr in result.get("tool_results", []):
        if tr.get("success") and tr.get("tool") == "orchestrator_record_artifact":
            output = tr.get("output", {})
            art_type = output.get("artifact_type", "")
            art_id = output.get("artifact_id", 0)
            if art_type and art_id:
                ckpt.record_artifact(
                    checkpoint_data,
                    stage=stage,
                    artifact_type=art_type,
                    artifact_id=art_id,
                )

    # Track auto-recorded artifacts (gate-required artifacts from _record_auto_artifacts)
    for art_type, art_id in result.get("auto_artifacts", []):
        if art_type and art_id:
            ckpt.record_artifact(
                checkpoint_data, stage=stage, artifact_type=art_type, artifact_id=art_id
            )

    # If ALL tools failed, trigger recovery
    tool_results = result.get("tool_results", [])
    # Exclude deferred tools (LLM-constructed args) from "all failed" detection
    non_deferred = [tr for tr in tool_results if tr.get("tool") not in _DEFERRED_TOOLS]
    all_real_failed = non_deferred and all(not tr.get("success") for tr in non_deferred)
    has_auto_artifacts = bool(result.get("auto_artifacts"))

    if all_real_failed and not has_auto_artifacts:
        error_msg = (
            f"All {len(non_deferred)} tools failed: {'; '.join(tool_errors[:3])}"
        )
        ckpt.record_error(checkpoint_data, kind="all_tools_failed", message=error_msg)
        retry_count = checkpoint_data.get("last_error", {}).get("retry_count", 0)
        recovery = decide_recovery(stage, "all_tools_failed", retry_count)
        return {
            "status": recovery,
            "stage": stage,
            "summary": error_msg[:200],
            "error": error_msg,
        }

    # Run codex review AFTER tools (so it reviews current stage output)
    if should_invoke_codex(stage, mode):
        codex_result = _maybe_run_codex(
            stage=stage,
            mode=mode,
            topic_id=topic_id,
            db=db,
            svc=svc,
            checkpoint_data=checkpoint_data,
            base_dir=base_dir,
            policy=policy,
        )
        if codex_result is not None:
            return codex_result

    # Tools executed successfully — check human checkpoint, then report complete.
    # Gate checking is handled by runner.py via advance().
    if stage == "write" and _paper_production_autonomous_completion_enabled(
        checkpoint_data
    ):
        completion_gate = _evaluate_paper_production_completion_gate(
            svc=svc,
            topic_id=topic_id,
        )
        if completion_gate["status"] != "pass":
            summary = "Paper-production completion gate blocked: " + ", ".join(
                completion_gate["blockers"]
            )
            ckpt.update_stage(
                checkpoint_data,
                stage=stage,
                state="error",
                summary_md=summary,
            )
            ckpt.record_event(
                checkpoint_data,
                stage=stage,
                event="paper_production_completion_gate_blocked",
                detail=summary[:200],
            )
            return {
                "status": "error",
                "stage": stage,
                "summary": summary[:200],
                "error": summary,
                "paper_production_completion_gate": completion_gate,
            }

    # Use unified interaction mode for post-execution approval
    run_policy = checkpoint_data.get("paper_production_run_policy", {})
    interaction_mode = run_policy.get("interaction_mode")
    if not interaction_mode:
        autonomy = "autonomous" if mode in ("demo", "autonomous") else "supervised"
        interaction_mode = resolve_interaction_mode(mode=mode, autonomy=autonomy)

    policy = get_policy(stage)
    decision_required = policy and policy.human_checkpoint in ("always", "conditional")

    # Check if should pause after stage completion
    should_pause = should_pause_for_decision(
        interaction_mode=interaction_mode,
        decision_required=decision_required or False,
        risk_level=policy.risk_level if policy else "low",
    )

    # Legacy fallback for backward compatibility
    if not should_pause:
        autonomy = "autonomous" if mode in ("demo", "autonomous") else "supervised"
        should_pause = should_pause_human(stage, mode, autonomy=autonomy)

    if should_pause and not _paper_production_autonomous_completion_enabled(
        checkpoint_data
    ):
        ckpt.update_stage(
            checkpoint_data,
            stage=stage,
            state="needs_human",
            summary_md=result.get("summary", ""),
        )
        # A needs_human pause MUST carry a decision to answer. Without it the user
        # sees "awaiting your decision" with no options and no callable action,
        # and paper_production_decide has nothing to record (BUG-009). Create the
        # approval decision in the same checkpoint update so state and decision
        # are always born together.
        existing_decision = checkpoint_data.get("human_decision")
        if not (
            isinstance(existing_decision, dict) and existing_decision.get("requested")
        ):
            ckpt.set_human_decision_request(
                checkpoint_data,
                stage=stage,
                checkpoint=f"{stage}_stage_approval",
                reason_code="stage_approval_required",
                prompt=(
                    f"Stage '{stage}' finished and is awaiting your approval "
                    f"(mode: {interaction_mode}). Approve to continue, or stop "
                    "to make manual changes first."
                ),
                options=[
                    {
                        "action": "approve",
                        "recommended": True,
                        "description": "Approve this stage and continue.",
                    },
                    {
                        "action": "stop",
                        "default_action": True,
                        "description": "Stop and intervene manually first.",
                    },
                ],
            )
        return {
            "status": "needs_human",
            "stage": stage,
            "summary": result.get(
                "summary",
                f"Stage {stage} complete, awaiting approval (mode: {interaction_mode})",
            ),
        }

    ckpt.update_stage(
        checkpoint_data,
        stage=stage,
        state="complete",
        summary_md=result.get("summary", ""),
    )
    ckpt.clear_error(checkpoint_data)
    ckpt.record_event(checkpoint_data, stage=stage, event="stage_complete")
    return {
        "status": "complete",
        "stage": stage,
        "summary": result.get("summary", f"Stage {stage} complete"),
    }


def _carried_forward_stage_context(context: dict[str, Any]) -> dict[str, Any]:
    """Carry only durable cross-stage context into a new stage execution."""

    return {
        key: context[key] for key in _STAGE_CONTEXT_CARRY_FORWARD_KEYS if key in context
    }


def _paper_production_autonomous_completion_enabled(
    checkpoint_data: dict[str, Any],
) -> bool:
    # Schema membership must come from the shared frozenset: the entry writes
    # v2 while this predicate compared against a v1 literal, which silently
    # disabled the completion gate (and every blocker behind it, including
    # final_bundle_finality_blocked) on all live runs.
    policy = ckpt.paper_production_policy(checkpoint_data)
    return policy.get("autonomous_completion") is True


def _evaluate_paper_production_completion_gate(
    *,
    svc: OrchestratorService,
    topic_id: int,
) -> dict[str, Any]:
    """Fail closed unless paper-production has a PDF bundle and publication pack."""

    blockers: list[str] = []
    final_bundle = svc.get_latest_artifact(topic_id, "write", "final_bundle")
    publication_pack = svc.get_latest_artifact(topic_id, "write", "publication_pack")
    process_summary = svc.get_latest_artifact(topic_id, "write", "process_summary")

    final_payload = _artifact_payload(final_bundle)
    if final_bundle is None:
        blockers.append("missing_final_bundle")
    elif str(final_payload.get("status", "")).lower() == "draft":
        blockers.append("final_bundle_is_draft")
    elif not _final_bundle_has_pdf(final_payload):
        blockers.append("final_bundle_missing_pdf")
    blockers.extend(_final_bundle_finality_blockers(final_payload))

    if publication_pack is None:
        blockers.append("missing_publication_pack")
    if process_summary is None:
        blockers.append("missing_process_summary")

    return {
        "schema_version": "rh.paper_production_completion_gate.v1",
        "status": "blocked" if blockers else "pass",
        "required_artifacts": [
            "final_bundle_pdf",
            "publication_pack",
            "process_summary",
        ],
        "blockers": blockers,
    }


def _artifact_payload(artifact: Any) -> dict[str, Any]:
    if artifact is None:
        return {}
    payload = getattr(artifact, "payload", None)
    if isinstance(payload, dict):
        return payload
    payload_json = getattr(artifact, "payload_json", None)
    if isinstance(payload_json, str) and payload_json:
        try:
            parsed = json.loads(payload_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _final_bundle_finality_blockers(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    evidence = payload.get("reference_pool_evidence")
    if isinstance(evidence, dict) and evidence.get("passed") is False:
        if not _final_bundle_has_interim_boundary(payload):
            blockers.append("final_bundle_reference_pool_below_final_threshold")
    if str(payload.get("finality_status") or "") == "blocked":
        blockers.append("final_bundle_finality_blocked")
    return blockers


def _final_bundle_has_interim_boundary(payload: dict[str, Any]) -> bool:
    boundary = payload.get("interim_boundary")
    return (
        payload.get("is_interim") is True
        and str(payload.get("finality_status") or "") == "interim_ready"
        and isinstance(boundary, dict)
        and bool(str(boundary.get("statement") or "").strip())
    )


def _final_bundle_has_pdf(payload: dict[str, Any]) -> bool:
    def valid_pdf(value: Any) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        path = Path(value)
        return path.exists() and path.is_file() and path.stat().st_size > 0

    for key in ("pdf_path", "compiled_pdf_path"):
        if valid_pdf(payload.get(key)):
            return True
    outputs = payload.get("outputs")
    if isinstance(outputs, dict):
        for key in ("pdf_path", "compiled_pdf_path"):
            if valid_pdf(outputs.get(key)):
                return True
    return False


def _record_research_wiki_preflight(
    *,
    db: Database,
    topic_id: int,
    stage: str,
    checkpoint_data: dict[str, Any],
) -> None:
    """Run Research Wiki context preflight for stages that require it."""

    if _reuse_demo_research_wiki_preflight(
        topic_id=topic_id,
        stage=stage,
        checkpoint_data=checkpoint_data,
    ):
        return

    try:
        query = str(checkpoint_data.get("stage_context", {}).get("direction") or "")
        summary = run_research_wiki_preflight(
            db=db,
            topic_id=topic_id,
            stage=stage,
            query=query,
        )
    except Exception as exc:
        ckpt.record_event(
            checkpoint_data,
            stage=stage,
            event="research_wiki_preflight_error",
            detail=str(exc)[:200],
        )
        checkpoint_data.setdefault("stage_context", {})["research_wiki_preflight"] = {
            "schema_version": "research_wiki_preflight.v1",
            "topic_id": topic_id,
            "stage": stage,
            "paper_wiki_status": "unavailable",
            "status_reason": "preflight_error",
            "fallback_allowed": True,
            "fallback_must_be_declared": True,
            "must_not_silent_markdown_fallback": True,
            "unavailable_reasons": [str(exc)[:200]],
        }
        return

    if summary is None:
        return

    checkpoint_data.setdefault("stage_context", {})["research_wiki_preflight"] = summary
    warning_codes = ",".join(summary.get("warning_codes") or [])
    detail = (
        f"paper_wiki_status={summary.get('paper_wiki_status')} "
        f"reason={summary.get('status_reason')} "
        f"action={summary.get('action_name')} "
        f"warnings={warning_codes or '-'}"
    )
    ckpt.record_event(
        checkpoint_data,
        stage=stage,
        event="research_wiki_preflight",
        detail=detail[:200],
    )


def _reuse_demo_research_wiki_preflight(
    *,
    topic_id: int,
    stage: str,
    checkpoint_data: dict[str, Any],
) -> bool:
    """Reuse loaded wiki preflight in demo seed-pool stages after analyze.

    Demo paper-production runs operate on a bounded seed pool. Once analyze has
    loaded the Research Wiki context, later stages should consume that compact
    summary instead of rebuilding the wiki pack on every stage transition.
    """

    if stage not in {"propose", "experiment", "write"}:
        return False
    if not _paper_production_demo_seed_pool_enabled(checkpoint_data):
        return False

    context = checkpoint_data.setdefault("stage_context", {})
    existing = context.get("research_wiki_preflight")
    if not _is_loaded_research_wiki_preflight(existing, topic_id=topic_id):
        return False

    source_stage = str(
        existing.get("reused_from_stage") or existing.get("stage") or "unknown"
    )
    source_action = str(
        existing.get("reused_from_action_name")
        or existing.get("action_name")
        or action_name_for_workflow_stage(source_stage)
    )
    action_name = action_name_for_workflow_stage(stage)
    reused = {
        **existing,
        "topic_id": topic_id,
        "stage": stage,
        "action_name": action_name,
        "status_reason": f"reused_from_{source_stage}_preflight",
        "reused": True,
        "reused_from_stage": source_stage,
        "reused_from_action_name": source_action,
    }
    context["research_wiki_preflight"] = reused

    warning_codes = ",".join(reused.get("warning_codes") or [])
    ckpt.record_event(
        checkpoint_data,
        stage=stage,
        event="research_wiki_preflight_reused",
        detail=(
            f"paper_wiki_status={reused.get('paper_wiki_status')} "
            f"from_stage={source_stage} to_stage={stage} "
            f"action={action_name} warnings={warning_codes or '-'}"
        )[:200],
    )
    return True


def _paper_production_demo_seed_pool_enabled(
    checkpoint_data: dict[str, Any],
) -> bool:
    # v2 policies carry the same demo fields; comparing against a v1 literal
    # left the demo evidence boundary unenforced on live (v2) demo runs.
    policy = ckpt.paper_production_policy(checkpoint_data)
    return (
        policy.get("mode") == "demo"
        and policy.get("evidence_boundary") == "demo_limited_seed_pool"
    )


def _is_loaded_research_wiki_preflight(
    value: Any,
    *,
    topic_id: int,
) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        value.get("schema_version") == "research_wiki_preflight.v1"
        and value.get("paper_wiki_status") == "loaded"
        and int(value.get("topic_id") or 0) == topic_id
    )


def _execute_stage_tools(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    checkpoint_data: dict[str, Any],
    budget_monitor: "BudgetMonitor | None" = None,
) -> dict[str, Any]:
    """Execute the tools for a stage via tool_dispatch.

    Iterates through the stage policy's tool list, dispatching each
    through the appropriate backend (primitive, orchestrator, or service).
    Each tool call is recorded in provenance via the execution backend.
    """
    from .tool_dispatch import dispatch_stage_tools

    policy = get_policy(stage)
    if policy is None:
        return {"summary": f"Stage {stage}: no policy found", "errors": []}

    context = checkpoint_data.get("stage_context", {})
    runtime_contract = _materialize_runtime_contract(
        checkpoint_data=checkpoint_data,
        topic_id=topic_id,
    )
    return dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        tools=policy.tools,
        context=context,
        budget_monitor=budget_monitor,
        capability_manifest=runtime_contract.get("capability_manifest"),
        run_spec=runtime_contract.get("run_spec"),
        execute_skill=bool(runtime_contract.get("execute_skill")),
    )


def _materialize_runtime_contract(
    *,
    checkpoint_data: dict[str, Any],
    topic_id: int,
) -> dict[str, Any]:
    contract = checkpoint_data.get("runtime_contract")
    if not isinstance(contract, dict):
        return {}
    if contract.get("capability_manifest") and contract.get("run_spec"):
        return contract
    skill_name = str(contract.get("skill_name") or "")
    if not skill_name:
        return contract

    from ..skill import build_skill_runtime_contract, find_repo_root

    repo_root = (
        Path(str(contract["skills_root"])).expanduser().resolve()
        if contract.get("skills_root")
        else find_repo_root()
    )
    materialized = build_skill_runtime_contract(
        repo_root,
        skill_name,
        topic_id=topic_id,
        artifact_refs=tuple(str(ref) for ref in contract.get("artifact_refs", ())),
        objective=str(contract.get("objective") or ""),
        literal_inputs=dict(contract.get("literal_inputs") or {}),
        user_brief=dict(contract.get("user_brief") or {}),
        run_id=str(contract.get("run_id") or ""),
        task_type=str(contract.get("task_type") or "evaluation"),
        project_id=contract.get("project_id"),
    )
    checkpoint_data["runtime_contract"] = {
        **contract,
        **materialized,
        "execute_skill": bool(contract.get("execute_skill", True)),
        "skills_root": str(repo_root),
    }
    return checkpoint_data["runtime_contract"]


def _maybe_run_codex(
    *,
    stage: str,
    mode: str,
    topic_id: int,
    db: Database,
    svc: OrchestratorService,
    checkpoint_data: dict[str, Any],
    base_dir: Path,
    policy: Any,
) -> dict[str, Any] | None:
    """Run codex review if needed. Returns outcome dict or None to continue."""
    handoff = checkpoint_data.get("codex_handoff", {})

    # Already have a verdict for THIS stage from a previous run
    if handoff.get("verdict") and handoff.get("stage") == stage:
        return None  # Continue with existing verdict

    h_dir = ckpt.handoff_dir(base_dir, topic_id, stage)

    # Check for existing response from a previous interrupted run
    existing = load_handoff_response(h_dir)
    if existing and existing.get("success"):
        ckpt.clear_codex_handoff(checkpoint_data, verdict=existing.get("verdict", ""))
        ckpt.record_event(
            checkpoint_data,
            stage=stage,
            event="codex_complete",
            detail=f"verdict={existing.get('verdict', '?')}",
        )
        return None  # Continue

    # Find the artifact to review — handles both V2 and legacy stage names
    stage_artifacts = checkpoint_data.get("artifacts", {}).get(stage, {})
    artifact_path = ""

    # V2 propose = legacy adversarial_optimization + study_design
    if stage in ("adversarial_optimization", "propose"):
        # Look for direction_proposal in propose or research_direction stages
        for search_stage in (stage, "research_direction", "analyze"):
            proposal = checkpoint_data.get("artifacts", {}).get(search_stage, {})
            artifact_id = proposal.get("direction_proposal", {}).get("artifact_id")
            if artifact_id:
                artifact_path = f"artifact:{artifact_id}"
                break

    elif stage == "study_design":
        spec = stage_artifacts.get("study_spec", {})
        artifact_id = spec.get("artifact_id")
        if artifact_id:
            artifact_path = f"artifact:{artifact_id}"

    elif stage == "write":
        # For write stage, review draft_pack if available
        draft = stage_artifacts.get("draft_pack", {})
        artifact_id = draft.get("artifact_id")
        if artifact_id:
            artifact_path = f"artifact:{artifact_id}"

    elif stage == "experiment":
        # For experiment stage, review experiment_result if available
        expr = stage_artifacts.get("experiment_result", {})
        artifact_id = expr.get("artifact_id")
        if artifact_id:
            artifact_path = f"artifact:{artifact_id}"

    if not artifact_path:
        # No artifact to review yet — let the stage continue
        return None

    # Save handoff request. Codex runs outside RH's DB context, so an internal
    # reference such as ``artifact:26`` is not enough; include the artifact
    # payload in the evidence summary as the model-visible review target.
    evidence = _build_codex_evidence_summary(
        db=db,
        topic_id=topic_id,
        stage=stage,
        artifact_path=artifact_path,
        checkpoint_data=checkpoint_data,
    )
    save_handoff_request(
        h_dir,
        stage=stage,
        artifact_path=artifact_path,
        focus=policy.codex_focus,
        evidence_summary=evidence,
    )

    # Run codex
    ckpt.record_event(checkpoint_data, stage=stage, event="codex_start")
    review = run_codex_review(
        artifact_path=Path(artifact_path),
        stage=stage,
        focus=policy.codex_focus,
        evidence_summary=evidence,
        cwd=base_dir.parent if base_dir.exists() else None,
    )
    save_handoff_response(h_dir, review)

    if not review.get("success"):
        # Codex failed — policy says required stages must pause
        if policy.codex == "required":
            ckpt.record_event(
                checkpoint_data,
                stage=stage,
                event="codex_error",
                detail=review.get("error", "unknown"),
            )
            return {
                "status": "pause_human",
                "stage": stage,
                "summary": f"Codex review failed: {review.get('error', 'unknown')[:200]}",
                "error": review.get("error", ""),
            }
        # Optional/recommended — continue without codex
        ckpt.record_event(
            checkpoint_data,
            stage=stage,
            event="codex_skipped",
            detail="codex failed, continuing without review",
        )
        return None

    verdict = review.get("verdict", "")
    ckpt.clear_codex_handoff(checkpoint_data, verdict=verdict)
    ckpt.record_event(
        checkpoint_data,
        stage=stage,
        event="codex_complete",
        detail=f"verdict={verdict}, issues={len(review.get('issues', []))}",
    )

    # "revise" verdict from a required codex gate should block advancement
    if verdict == "revise" and policy.codex == "required":
        issues = review.get("issues", [])
        if _paper_production_autonomous_completion_enabled(checkpoint_data):
            revision = _apply_paper_production_codex_revision(
                db=db,
                svc=svc,
                topic_id=topic_id,
                stage=stage,
                artifact_path=artifact_path,
                review=review,
                checkpoint_data=checkpoint_data,
            )
            if revision.get("success"):
                ckpt.record_event(
                    checkpoint_data,
                    stage=stage,
                    event="codex_revision_applied",
                    detail=(
                        f"verdict=revise issues={len(issues)} "
                        f"artifact={revision.get('artifact_id')}"
                    )[:200],
                )
                return None
        return {
            "status": "needs_human",
            "stage": stage,
            "summary": f"Codex requires revision: {len(issues)} issue(s) flagged",
            "codex_issues": issues,
        }

    # "reject" verdict always blocks
    if verdict == "reject":
        return {
            "status": "pause_human",
            "stage": stage,
            "summary": f"Codex rejected: {len(review.get('issues', []))} issue(s)",
            "codex_issues": review.get("issues", []),
        }

    return None


def _apply_paper_production_codex_revision(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    artifact_path: str,
    review: dict[str, Any],
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    """Record a bounded automatic revision for paper-production smoke runs."""

    artifact = _artifact_from_ref(db=db, artifact_path=artifact_path)
    if artifact is None or getattr(artifact, "topic_id", None) != topic_id:
        return {"success": False, "error": "missing_reviewed_artifact"}

    artifact_type = str(getattr(artifact, "artifact_type", "") or "")
    if artifact_type != "direction_proposal":
        return {"success": False, "error": f"unsupported_artifact:{artifact_type}"}

    original_payload = _artifact_payload(artifact)
    issues = [issue for issue in review.get("issues", []) if isinstance(issue, dict)]
    revision_plan = [_codex_issue_revision_action(issue) for issue in issues]
    revised_payload = _build_revised_direction_proposal_payload(
        original_payload,
        review=review,
        revision_plan=revision_plan,
        original_artifact_id=int(getattr(artifact, "id", 0) or 0),
    )
    revision_record = svc.record_artifact(
        topic_id=topic_id,
        stage=stage,
        artifact_type="codex_revision",
        title="Codex-required revision applied automatically",
        payload={
            "schema_version": "rh.paper_production_codex_revision.v1",
            "reviewed_artifact_id": int(getattr(artifact, "id", 0) or 0),
            "superseded_artifact_id": int(getattr(artifact, "id", 0) or 0),
            "review_verdict": str(review.get("verdict") or ""),
            "review_scores": dict(review.get("scores") or {}),
            "review_notes": str(review.get("notes") or ""),
            "issue_count": len(issues),
            "issues": issues,
            "revision_plan": revision_plan,
            "automation_scope": "paper_production_demo_quality_repair",
            "submission_readiness": "not_submission_ready",
        },
        parent_artifact_id=int(getattr(artifact, "id", 0) or 0),
        dependency_artifact_ids=[int(getattr(artifact, "id", 0) or 0)],
        dependency_type="derived_from",
    )
    revised = svc.record_artifact(
        topic_id=topic_id,
        stage=stage,
        artifact_type="direction_proposal",
        title=str(getattr(artifact, "title", "") or "Revised direction proposal"),
        payload=revised_payload,
        parent_artifact_id=int(getattr(artifact, "id", 0) or 0),
        dependency_artifact_ids=[
            int(getattr(artifact, "id", 0) or 0),
            int(getattr(revision_record, "id", 0) or 0),
        ],
        dependency_type="derived_from",
    )

    revised_id = int(getattr(revised, "id", 0) or 0)
    revision_id = int(getattr(revision_record, "id", 0) or 0)
    if revised_id:
        ckpt.record_artifact(
            checkpoint_data,
            stage=stage,
            artifact_type="direction_proposal",
            artifact_id=revised_id,
        )
    if revision_id:
        ckpt.record_artifact(
            checkpoint_data,
            stage=stage,
            artifact_type="codex_revision",
            artifact_id=revision_id,
        )
    context = checkpoint_data.setdefault("stage_context", {})
    context["codex_revision"] = {
        "schema_version": "rh.paper_production_codex_revision.v1",
        "artifact_id": revised_id,
        "revision_artifact_id": revision_id,
        "issue_count": len(issues),
        "revision_plan": revision_plan,
    }
    return {
        "success": bool(revised_id and revision_id),
        "artifact_id": revised_id,
        "revision_artifact_id": revision_id,
        "issue_count": len(issues),
    }


def _codex_issue_revision_action(issue: dict[str, Any]) -> dict[str, Any]:
    category = str(issue.get("category") or "general").strip() or "general"
    target = str(issue.get("target") or "").strip()
    severity = str(issue.get("severity") or "").strip()
    reasoning = str(issue.get("reasoning") or "").strip()
    suggested_fix = str(issue.get("suggested_fix") or "").strip()
    return {
        "category": category,
        "target": target,
        "severity": severity,
        "reasoning": reasoning,
        "action": suggested_fix or reasoning or f"Address {category}.",
    }


def _build_revised_direction_proposal_payload(
    original_payload: dict[str, Any],
    *,
    review: dict[str, Any],
    revision_plan: list[dict[str, Any]],
    original_artifact_id: int,
) -> dict[str, Any]:
    payload = dict(original_payload)
    payload["revision_plan"] = revision_plan
    payload["codex_revision"] = {
        "schema_version": "rh.paper_production_codex_revision.v1",
        "verdict": str(review.get("verdict") or ""),
        "scores": dict(review.get("scores") or {}),
        "notes": str(review.get("notes") or ""),
        "issue_count": len(revision_plan),
        "source_artifact_id": original_artifact_id,
    }
    payload["method_validity_guard"] = (
        "The proposal must define required model states, parameters, branch "
        "switches, reconstructible diagnostics, non-reconstructible cases, and "
        "explicit failure conditions before claims are treated as submission-ready."
    )
    payload["falsifiability_guard"] = (
        "Diagnostic reconstruction claims require measurable acceptance criteria, "
        "including component-level tolerance checks, branch-selection checks, and "
        "water-balance residual thresholds."
    )
    payload["scope_guard"] = (
        "The demo run remains bounded to evidence-limited paper-production smoke "
        "testing and is not submission-ready without full corpus and experiment "
        "validation."
    )
    payload["submission_readiness"] = "not_submission_ready"
    payload["quality_gate_status"] = "codex_revision_applied"
    return payload


def _build_codex_evidence_summary(
    *,
    db: Database,
    topic_id: int,
    stage: str,
    artifact_path: str,
    checkpoint_data: dict[str, Any],
) -> str:
    context = checkpoint_data.get("stage_context", {})
    parts: list[str] = []
    summary_md = context.get("summary_md")
    if isinstance(summary_md, str) and summary_md.strip():
        parts.append("Stage summary:\n" + summary_md.strip())

    artifact = _artifact_from_ref(db=db, artifact_path=artifact_path)
    if artifact is not None:
        parts.append(_format_artifact_for_codex(artifact, label="Primary artifact"))

    for related in _related_stage_artifacts_for_codex(
        db=db,
        topic_id=topic_id,
        stage=stage,
        checkpoint_data=checkpoint_data,
        primary_ref=artifact_path,
    ):
        parts.append(_format_artifact_for_codex(related, label="Related artifact"))

    return "\n\n".join(parts)[:12000]


def _artifact_from_ref(*, db: Database, artifact_path: str) -> Any | None:
    if not artifact_path.startswith("artifact:"):
        return None
    raw_id = artifact_path.split(":", 1)[1].strip()
    if not raw_id.isdigit():
        return None
    from ..orchestrator.artifacts import ArtifactManager

    return ArtifactManager(db).get(int(raw_id))


def _related_stage_artifacts_for_codex(
    *,
    db: Database,
    topic_id: int,
    stage: str,
    checkpoint_data: dict[str, Any],
    primary_ref: str,
) -> list[Any]:
    primary_id = _artifact_id_from_ref(primary_ref)
    artifact_ids: list[int] = []
    for search_stage in (stage, "analyze", "research_direction", "study_design"):
        stage_artifacts = checkpoint_data.get("artifacts", {}).get(search_stage, {})
        if not isinstance(stage_artifacts, dict):
            continue
        for artifact_record in stage_artifacts.values():
            if not isinstance(artifact_record, dict):
                continue
            artifact_id = artifact_record.get("artifact_id")
            if isinstance(artifact_id, int) and artifact_id != primary_id:
                artifact_ids.append(artifact_id)

    if not artifact_ids:
        return []

    from ..orchestrator.artifacts import ArtifactManager

    manager = ArtifactManager(db)
    seen: set[int] = set()
    artifacts: list[Any] = []
    for artifact_id in artifact_ids:
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        artifact = manager.get(artifact_id)
        if artifact is not None and artifact.topic_id == topic_id:
            artifacts.append(artifact)
    return artifacts[:6]


def _artifact_id_from_ref(artifact_path: str) -> int | None:
    if not artifact_path.startswith("artifact:"):
        return None
    raw_id = artifact_path.split(":", 1)[1].strip()
    return int(raw_id) if raw_id.isdigit() else None


def _format_artifact_for_codex(artifact: Any, *, label: str) -> str:
    payload = getattr(artifact, "payload", None)
    if not isinstance(payload, dict):
        payload = {}
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if len(payload_text) > 6000:
        payload_text = payload_text[:6000] + "\n... [truncated]"
    return (
        f"{label}:\n"
        f"- id: {getattr(artifact, 'id', '')}\n"
        f"- stage: {getattr(artifact, 'stage', '')}\n"
        f"- artifact_type: {getattr(artifact, 'artifact_type', '')}\n"
        f"- title: {getattr(artifact, 'title', '')}\n"
        f"- payload:\n{payload_text}"
    )
