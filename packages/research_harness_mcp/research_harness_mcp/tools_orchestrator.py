"""MCP orchestrator tool definitions."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from mcp.types import Tool

from research_harness_mcp.tools_service_dispatch import (
    _execute_service_backed_convenience,
)

_ORCHESTRATOR_TOOLS: dict[str, Tool] = {
    "orchestrator_status": Tool(
        name="orchestrator_status",
        description="Show orchestrator status for a topic (current stage, gate, artifacts, issues)",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
            },
            "required": ["topic_id"],
        },
    ),
    "orchestrator_advance": Tool(
        name="orchestrator_advance",
        description="Advance the topic to the next orchestrator stage (checks gates and artifacts)",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "actor": {
                    "type": "string",
                    "description": "Actor name (default: system)",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "orchestrator_record_artifact": Tool(
        name="orchestrator_record_artifact",
        description="Record a new artifact for the current orchestrator stage",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "stage": {"type": "string", "description": "Stage name"},
                "artifact_type": {"type": "string", "description": "Artifact type"},
                "title": {"type": "string", "description": "Artifact title"},
                "payload": {
                    "type": "object",
                    "description": "Artifact payload as JSON object",
                },
                "dependency_artifact_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional upstream artifact IDs this artifact depends on",
                },
                "dependency_type": {
                    "type": "string",
                    "description": "Dependency edge type (default: consumed_by)",
                },
            },
            "required": ["topic_id", "stage", "artifact_type"],
        },
    ),
    "orchestrator_add_artifact_dependency": Tool(
        name="orchestrator_add_artifact_dependency",
        description="Declare that one artifact depends on another",
        inputSchema={
            "type": "object",
            "properties": {
                "from_artifact_id": {
                    "type": "integer",
                    "description": "Upstream artifact ID",
                },
                "to_artifact_id": {
                    "type": "integer",
                    "description": "Downstream artifact ID",
                },
                "dependency_type": {
                    "type": "string",
                    "description": "consumed_by or derived_from",
                },
            },
            "required": ["from_artifact_id", "to_artifact_id"],
        },
    ),
    "orchestrator_mark_artifact_stale": Tool(
        name="orchestrator_mark_artifact_stale",
        description="Mark an artifact stale and optionally propagate to dependents",
        inputSchema={
            "type": "object",
            "properties": {
                "artifact_id": {"type": "integer", "description": "Artifact ID"},
                "reason": {
                    "type": "string",
                    "description": "Why this artifact is stale",
                },
                "propagate": {
                    "type": "boolean",
                    "description": "Propagate stale state downstream",
                },
            },
            "required": ["artifact_id"],
        },
    ),
    "orchestrator_clear_artifact_stale": Tool(
        name="orchestrator_clear_artifact_stale",
        description="Clear stale state for an artifact after acknowledgement or refresh",
        inputSchema={
            "type": "object",
            "properties": {
                "artifact_id": {"type": "integer", "description": "Artifact ID"},
            },
            "required": ["artifact_id"],
        },
    ),
    "orchestrator_list_stale_artifacts": Tool(
        name="orchestrator_list_stale_artifacts",
        description="List active stale artifacts for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
            },
            "required": ["topic_id"],
        },
    ),
    "orchestrator_resume": Tool(
        name="orchestrator_resume",
        description=(
            "Resume (or create) an orchestrator run, automatically inferring the current "
            "stage from existing artifacts so topics that predate orchestrator tracking "
            "start at the right stage instead of always at topic_framing. "
            "Pass force_stage to override the inferred stage."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "mode": {
                    "type": "string",
                    "description": "Workflow mode (default: standard)",
                },
                "force_stage": {
                    "type": "string",
                    "description": "Override inferred stage (optional)",
                },
                "stop_before": {
                    "type": "string",
                    "description": (
                        "Hard stop: advance() will refuse to enter this stage. "
                        "E.g. 'experiment' to auto-run init→build→analyze→propose then stop. "
                        "Pass empty string to clear."
                    ),
                },
            },
            "required": ["topic_id"],
        },
    ),
    "orchestrator_gate_check": Tool(
        name="orchestrator_gate_check",
        description="Check the gate for the current or specified stage",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "stage": {
                    "type": "string",
                    "description": "Stage to check (defaults to current)",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "paper_commit_version": Tool(
        name="paper_commit_version",
        description=(
            "Commit one manuscript version atomically: hash the TeX/PDF files, "
            "record draft_pack + final_bundle (+ quality report) with lineage "
            "wired, and reject commits whose declared dependencies are missing "
            "or superseded."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "tex_path": {
                    "type": "string",
                    "description": "Manuscript TeX file recorded as draft_pack",
                },
                "pdf_path": {
                    "type": "string",
                    "description": "Compiled PDF recorded as final_bundle",
                },
                "stage": {
                    "type": "string",
                    "description": "Orchestrator stage (default: write)",
                },
                "title": {"type": "string", "description": "Artifact title"},
                "quality_report": {
                    "type": "object",
                    "description": "Recorded as final_bundle_quality_report",
                },
                "dependency_artifact_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": (
                        "Upstream artifact IDs; commit is rejected if any is not active"
                    ),
                },
                "notes": {"type": "string", "description": "Free-form change notes"},
                "force_reason": {
                    "type": "string",
                    "description": (
                        "Record an audited human override when gate findings "
                        "would otherwise block the commit"
                    ),
                },
            },
            "required": ["topic_id", "tex_path"],
        },
    ),
    "paper_task_intake": Tool(
        name="paper_task_intake",
        description=(
            "Create or resume a durable RH paper-production topic/run from a "
            "natural-language task, record the initial PAPER_PLAN artifact, and "
            "return RH_STATE so chat-only output is not treated as progress."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Natural-language task"},
                "target_venue": {
                    "type": "string",
                    "description": "Target venue or publication context",
                },
                "mode": {
                    "type": "string",
                    "enum": ["explore", "standard", "strict", "demo"],
                    "description": "Workflow mode (default: standard)",
                },
                "local_only": {
                    "type": "boolean",
                    "description": "Restrict evidence acquisition planning to local sources",
                },
            },
            "required": ["task", "target_venue"],
        },
    ),
    "integrity_check": Tool(
        name="integrity_check",
        description="Run 5-phase integrity verification (references, citation context, statistics, originality, claims)",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "phase": {
                                "type": "string",
                                "enum": [
                                    "references",
                                    "citation_context",
                                    "statistical_data",
                                    "originality",
                                    "claims",
                                ],
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "high", "medium", "low"],
                            },
                            "category": {"type": "string"},
                            "summary": {"type": "string"},
                            "details": {"type": "string"},
                        },
                        "required": ["phase", "severity", "summary"],
                    },
                    "description": "External findings from agent review",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "finalize": Tool(
        name="finalize",
        description="Create final submission bundle and process summary for a completed topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
            },
            "required": ["topic_id"],
        },
    ),
    "review_bundle_create": Tool(
        name="review_bundle_create",
        description="Create a review bundle linking integrity and scholarly review report artifacts",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "integrity_artifact_id": {
                    "type": "integer",
                    "description": "Integrity report artifact ID",
                },
                "scholarly_artifact_id": {
                    "type": "integer",
                    "description": "Scholarly report artifact ID",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "review_add_issue": Tool(
        name="review_add_issue",
        description="Add a review finding as an issue (critical/high auto-blocks gate)",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "review_type": {
                    "type": "string",
                    "enum": ["integrity", "scholarly"],
                    "description": "Review type",
                },
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "Issue severity",
                },
                "category": {
                    "type": "string",
                    "description": "Issue category (methodology, evidence, writing, etc.)",
                },
                "summary": {"type": "string", "description": "Issue summary"},
                "details": {"type": "string", "description": "Detailed description"},
                "recommended_action": {
                    "type": "string",
                    "description": "Recommended fix",
                },
                "review_artifact_id": {
                    "type": "integer",
                    "description": "Source review artifact ID",
                },
            },
            "required": [
                "topic_id",
                "review_type",
                "severity",
                "category",
                "summary",
            ],
        },
    ),
    "review_issues": Tool(
        name="review_issues",
        description="List review issues for a topic, optionally filtered by stage/status/blocking",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "stage": {"type": "string", "description": "Filter by stage"},
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "resolved", "wontfix"],
                    "description": "Filter by status",
                },
                "blocking_only": {
                    "type": "boolean",
                    "description": "Show only blocking issues",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "review_respond": Tool(
        name="review_respond",
        description="Record a response to a review issue (change/clarify/dispute/acknowledge)",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "issue_id": {
                    "type": "integer",
                    "description": "Issue ID to respond to",
                },
                "response_type": {
                    "type": "string",
                    "enum": ["change", "clarify", "dispute", "acknowledge"],
                    "description": "Response type",
                },
                "response_text": {"type": "string", "description": "Response text"},
                "artifact_id": {"type": "integer", "description": "Linked artifact ID"},
                "evidence": {
                    "type": "object",
                    "description": "Supporting evidence as JSON",
                },
            },
            "required": ["topic_id", "issue_id", "response_type", "response_text"],
        },
    ),
    "review_resolve": Tool(
        name="review_resolve",
        description="Mark a review issue as resolved or wontfix",
        inputSchema={
            "type": "object",
            "properties": {
                "issue_id": {"type": "integer", "description": "Issue ID to resolve"},
                "status": {
                    "type": "string",
                    "enum": ["resolved", "wontfix"],
                    "description": "Resolution status",
                },
            },
            "required": ["issue_id", "status"],
        },
    ),
    "review_status": Tool(
        name="review_status",
        description="Get review summary: issue counts, decision, cycle info, gate status",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
            },
            "required": ["topic_id"],
        },
    ),
    "adversarial_run": Tool(
        name="adversarial_run",
        description="Run an adversarial round: submit proposal with objections for challenge",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "artifact_id": {
                    "type": "integer",
                    "description": "Target artifact ID to review",
                },
                "proposal_snapshot": {
                    "type": "object",
                    "description": "Proposal snapshot as JSON",
                },
                "objections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string"},
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "major", "minor"],
                            },
                            "target": {"type": "string"},
                            "reasoning": {"type": "string"},
                            "suggested_fix": {"type": "string"},
                        },
                        "required": ["category", "severity", "target", "reasoning"],
                    },
                    "description": "List of objections",
                },
                "proposer_responses": {
                    "type": "array",
                    "description": "Proposer responses to objections",
                },
                "resolver_notes": {"type": "string", "description": "Resolver notes"},
            },
            "required": [
                "topic_id",
                "artifact_id",
                "proposal_snapshot",
                "objections",
            ],
        },
    ),
    "adversarial_resolve": Tool(
        name="adversarial_resolve",
        description="Resolve an adversarial round with scores and determine outcome",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "round_artifact_id": {
                    "type": "integer",
                    "description": "Round artifact ID to resolve",
                },
                "scores": {
                    "type": "object",
                    "description": 'Dimension scores as JSON (e.g. {"novelty": 4.5})',
                },
                "notes": {"type": "string", "description": "Resolution notes"},
            },
            "required": ["topic_id", "round_artifact_id"],
        },
    ),
    "adversarial_status": Tool(
        name="adversarial_status",
        description="Check adversarial optimization status for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
            },
            "required": ["topic_id"],
        },
    ),
    "adversarial_review": Tool(
        name="adversarial_review",
        description=(
            "Run an independent cross-model adversarial review on a topic artifact. "
            "Automatically dispatches to a DIFFERENT model than the current executor: "
            "Claude sessions → Codex/GPT review, Codex sessions → Anthropic Opus review. "
            "Returns structured verdict with issues/scores and auto-records as adversarial_round artifact."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "artifact_id": {
                    "type": "integer",
                    "description": "Artifact ID to review",
                },
                "focus": {
                    "type": "string",
                    "description": "Review focus (e.g. 'novelty and method soundness')",
                },
                "evidence_summary": {
                    "type": "string",
                    "description": "Optional evidence summary to provide reviewer context",
                },
            },
            "required": ["topic_id", "artifact_id"],
        },
    ),
    "experiment_handoff_prepare": Tool(
        name="experiment_handoff_prepare",
        description=(
            "Package a research_candidate into an experiment_brief artifact on "
            "the experiment stage. Pulls the candidate's pitch, red-ocean "
            "scores, opportunity_angle, evidence gap_ids/contradiction_ids, and "
            "related papers (baselines, datasets) from the DB and records a "
            "self-contained brief ready for experiment kickoff."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "candidate_id": {
                    "type": "integer",
                    "description": "research_candidates.id to package",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional freeform operator notes",
                },
            },
            "required": ["topic_id", "candidate_id"],
        },
    ),
    "experiment_handoff_submit": Tool(
        name="experiment_handoff_submit",
        description=(
            "Submit an experiment_brief to an external handoff target. Records "
            "an experiment_handoff artifact linked to the brief via "
            "consumed_by dependency, and marks the candidate as 'promoted'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "brief_artifact_id": {
                    "type": "integer",
                    "description": "experiment_brief artifact ID from _prepare",
                },
                "handoff_target": {
                    "type": "string",
                    "description": "Target system name (e.g. 'codex', 'manual', 'notion')",
                },
                "summary": {
                    "type": "string",
                    "description": "Submission summary (what was handed off and how)",
                },
            },
            "required": ["topic_id", "brief_artifact_id", "handoff_target"],
        },
    ),
    "workflow_entry": Tool(
        name="workflow_entry",
        description=(
            "Single-call workflow status + next-action suggestion for a topic. "
            "Returns current orchestrator stage, gate decision, count of "
            "verified gaps/red-ocean candidates, and a ranked next_actions "
            "list so agents can resume a topic without reading multiple tools."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
            },
            "required": ["topic_id"],
        },
    ),
    "claim_verify": Tool(
        name="claim_verify",
        description=(
            "Bounded pair-wise contradiction detection over normalized_claims "
            "for a topic. Deterministic prefilter by (task, dataset, metric); "
            "hard cap on pair checks (default 200). Flags figure/table/equation "
            "claims for human review. Persists contradictions to DB when "
            "persist=true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "pair_budget": {
                    "type": "integer",
                    "description": "Max pair checks (hard cap 200)",
                    "default": 200,
                },
                "persist": {
                    "type": "boolean",
                    "description": "Persist contradictions to DB",
                    "default": True,
                },
            },
            "required": ["topic_id"],
        },
    ),
    "adversarial_section_review": Tool(
        name="adversarial_section_review",
        description=(
            "Skeptical-reviewer persona produces structured weakness report for "
            "a drafted section. Every weakness must cite evidence; items "
            "without evidence are dropped. Auto-opens review_issues for "
            "severity=critical items."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "section": {
                    "type": "string",
                    "description": "Section name (e.g. 'introduction', 'results')",
                },
                "content": {
                    "type": "string",
                    "description": "Full section draft text to review",
                },
                "target_words": {
                    "type": "integer",
                    "description": "Word budget used during drafting",
                    "default": 0,
                },
                "auto_open_issues": {
                    "type": "boolean",
                    "description": "Auto-open review_issues for critical items",
                    "default": True,
                },
            },
            "required": ["topic_id", "section", "content"],
        },
    ),
}


def _execute_adversarial_review(
    svc: Any,
    db: Any,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Run cross-model adversarial review and persist as artifact."""
    from research_harness.auto_runner.codex_bridge import (
        codex_issues_to_objections,
        run_codex_review,
    )

    topic_id = arguments["topic_id"]
    artifact_id = arguments["artifact_id"]
    focus = arguments.get("focus", "")
    evidence_summary = arguments.get("evidence_summary", "")

    run = svc.get_run(topic_id)
    if run is None:
        return {"success": False, "error": "No orchestrator run found for this topic"}

    artifact = svc._artifact_manager.get(artifact_id)
    if artifact is None:
        return {"success": False, "error": f"Artifact {artifact_id} not found"}

    artifact_content = json.dumps(artifact.payload, ensure_ascii=False, indent=2)[:3000]
    if evidence_summary:
        full_evidence = f"{evidence_summary}\n\nArtifact content:\n{artifact_content}"
    else:
        full_evidence = f"Artifact content:\n{artifact_content}"

    review = run_codex_review(
        artifact_path=Path(artifact.path)
        if artifact.path
        else Path(f"artifact_{artifact_id}"),
        stage=run.current_stage,
        focus=focus or f"Review {artifact.artifact_type} artifact",
        evidence_summary=full_evidence,
    )

    if not review.get("success"):
        return {
            "success": False,
            "error": f"Adversarial review failed: {review.get('error', 'unknown')}",
            "backend": review.get("backend", "unknown"),
        }

    objections = codex_issues_to_objections(review.get("issues", []))
    proposal_snapshot = {
        "artifact_id": artifact_id,
        "artifact_type": artifact.artifact_type,
        "stage": artifact.stage,
        "title": artifact.title,
        "content_preview": artifact_content[:1000],
    }

    round_result = svc.run_adversarial_round(
        topic_id=topic_id,
        target_artifact_id=artifact_id,
        proposal_snapshot=proposal_snapshot,
        objections=[
            {
                "category": o.get("category", "general"),
                "severity": o.get("severity", "minor"),
                "target": o.get("target", ""),
                "reasoning": o.get("reasoning", ""),
                "suggested_fix": o.get("suggested_fix", ""),
            }
            for o in objections
        ],
    )

    scores = review.get("scores", {})
    if scores and round_result.get("success"):
        resolve_result = svc.resolve_adversarial_round(
            topic_id=topic_id,
            round_artifact_id=round_result["artifact_id"],
            scores=scores,
            notes=review.get("notes", ""),
        )
    else:
        resolve_result = {}

    return {
        "success": True,
        "verdict": review.get("verdict", ""),
        "issues_count": len(objections),
        "critical_count": sum(1 for o in objections if o.get("severity") == "critical"),
        "major_count": sum(1 for o in objections if o.get("severity") == "major"),
        "scores": scores,
        "notes": review.get("notes", ""),
        "round_artifact_id": round_result.get("artifact_id"),
        "resolution_artifact_id": resolve_result.get("artifact_id"),
        "backend": review.get("backend", "unknown"),
        "model": review.get("model", ""),
        "stage": run.current_stage,
    }


def _missing_orchestrator_executor(
    name: str,
) -> Callable[[Any, Any, dict[str, Any]], dict[str, Any]]:
    def _executor(_svc: Any, _db: Any, _arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": f"Missing orchestrator executor: {name}"}

    return _executor


def _execute_orchestrator(
    name: str,
    arguments: dict[str, Any],
    *,
    db_resolver: Callable[[], Any],
    service_factory: Callable[[Any], Any] | None = None,
    adversarial_review_executor: Callable[
        [Any, Any, dict[str, Any]], dict[str, Any]
    ] = _execute_adversarial_review,
    experiment_handoff_prepare_executor: Callable[
        [Any, Any, dict[str, Any]], dict[str, Any]
    ]
    | None = None,
    experiment_handoff_submit_executor: Callable[
        [Any, Any, dict[str, Any]], dict[str, Any]
    ]
    | None = None,
    workflow_entry_executor: Callable[[Any, Any, dict[str, Any]], dict[str, Any]]
    | None = None,
    claim_verify_executor: Callable[[Any, dict[str, Any]], dict[str, Any]]
    | None = None,
    adversarial_section_review_executor: Callable[
        [Any, Any, dict[str, Any]], dict[str, Any]
    ]
    | None = None,
) -> dict[str, Any]:
    """Execute an orchestrator tool with injectable runtime dependencies."""
    from research_harness.orchestrator import OrchestratorService
    from research_harness.orchestrator.stages import resolve_stage

    db = db_resolver()
    svc = (service_factory or OrchestratorService)(db)
    normalized_arguments = dict(arguments)

    if "stage" in normalized_arguments:
        normalized_arguments["stage"] = resolve_stage(normalized_arguments["stage"])
    if "force_stage" in normalized_arguments:
        normalized_arguments["force_stage"] = resolve_stage(
            normalized_arguments["force_stage"]
        )

    if name == "orchestrator_resume":
        stop_before = normalized_arguments.get("stop_before")
        if stop_before:
            stop_before = resolve_stage(stop_before)
        run = svc.resume_run(
            topic_id=normalized_arguments["topic_id"],
            mode=normalized_arguments.get("mode", "standard"),
            force_stage=normalized_arguments.get("force_stage"),
            stop_before=stop_before,
        )
        inferred = svc.infer_stage_from_artifacts(normalized_arguments["topic_id"])
        result = {
            "success": True,
            "run_id": run.id,
            "topic_id": run.topic_id,
            "current_stage": run.current_stage,
            "inferred_stage": inferred,
            "stage_status": run.stage_status,
        }
        if run.stop_before:
            result["stop_before"] = run.stop_before
        return result

    if name == "orchestrator_status":
        status = svc.get_status(normalized_arguments["topic_id"])
        status["db_path"] = str(db.db_path)
        return status

    if name == "orchestrator_advance":
        return svc.advance(
            normalized_arguments["topic_id"],
            actor=normalized_arguments.get("actor", "system"),
        )

    if name == "orchestrator_record_artifact":
        artifact = svc.record_artifact(
            topic_id=normalized_arguments["topic_id"],
            stage=normalized_arguments["stage"],
            artifact_type=normalized_arguments["artifact_type"],
            title=normalized_arguments.get("title", ""),
            payload=normalized_arguments.get("payload"),
            dependency_artifact_ids=normalized_arguments.get("dependency_artifact_ids"),
            dependency_type=normalized_arguments.get("dependency_type", "consumed_by"),
        )
        return {
            "success": True,
            "artifact_id": artifact.id,
            "version": artifact.version,
            "stage": artifact.stage,
            "type": artifact.artifact_type,
        }

    if name == "orchestrator_add_artifact_dependency":
        return svc.add_artifact_dependency(
            from_artifact_id=normalized_arguments["from_artifact_id"],
            to_artifact_id=normalized_arguments["to_artifact_id"],
            dependency_type=normalized_arguments.get("dependency_type", "consumed_by"),
        )

    if name == "orchestrator_mark_artifact_stale":
        return svc.mark_artifact_stale(
            artifact_id=normalized_arguments["artifact_id"],
            reason=normalized_arguments.get("reason", ""),
            propagate=normalized_arguments.get("propagate", True),
        )

    if name == "orchestrator_clear_artifact_stale":
        return svc.clear_artifact_stale(normalized_arguments["artifact_id"])

    if name == "orchestrator_list_stale_artifacts":
        artifacts = svc.list_stale_artifacts(normalized_arguments["topic_id"])
        return {
            "artifacts": [asdict(artifact) for artifact in artifacts],
            "count": len(artifacts),
        }

    if name == "orchestrator_gate_check":
        decision = svc.check_gate(
            normalized_arguments["topic_id"],
            stage=normalized_arguments.get("stage"),
        )
        return {"gate_decision": decision}

    if name == "paper_task_intake":
        return _execute_service_backed_convenience(
            name,
            normalized_arguments,
            db,
        )

    if name == "integrity_check":
        return svc.run_integrity_check(
            topic_id=normalized_arguments["topic_id"],
            findings=normalized_arguments.get("findings"),
        )

    if name == "finalize":
        return svc.finalize(topic_id=normalized_arguments["topic_id"])

    if name == "review_bundle_create":
        return svc.create_review_bundle(
            topic_id=normalized_arguments["topic_id"],
            integrity_artifact_id=normalized_arguments.get("integrity_artifact_id"),
            scholarly_artifact_id=normalized_arguments.get("scholarly_artifact_id"),
        )

    if name == "review_add_issue":
        return svc.add_review_issue(
            topic_id=normalized_arguments["topic_id"],
            review_type=normalized_arguments["review_type"],
            severity=normalized_arguments["severity"],
            category=normalized_arguments["category"],
            summary=normalized_arguments["summary"],
            details=normalized_arguments.get("details", ""),
            recommended_action=normalized_arguments.get("recommended_action", ""),
            review_artifact_id=normalized_arguments.get("review_artifact_id"),
        )

    if name == "review_issues":
        return {
            "issues": svc.list_review_issues(
                topic_id=normalized_arguments["topic_id"],
                stage=normalized_arguments.get("stage"),
                status=normalized_arguments.get("status"),
                blocking_only=normalized_arguments.get("blocking_only", False),
            )
        }

    if name == "review_respond":
        return svc.respond_to_issue(
            issue_id=normalized_arguments["issue_id"],
            topic_id=normalized_arguments["topic_id"],
            response_type=normalized_arguments["response_type"],
            response_text=normalized_arguments["response_text"],
            artifact_id=normalized_arguments.get("artifact_id"),
            evidence=normalized_arguments.get("evidence"),
        )

    if name == "review_resolve":
        return svc.resolve_review_issue(
            issue_id=normalized_arguments["issue_id"],
            resolution_status=normalized_arguments["status"],
        )

    if name == "review_status":
        return svc.get_review_status(normalized_arguments["topic_id"])

    if name == "adversarial_run":
        return svc.run_adversarial_round(
            topic_id=normalized_arguments["topic_id"],
            target_artifact_id=normalized_arguments["artifact_id"],
            proposal_snapshot=normalized_arguments["proposal_snapshot"],
            objections=normalized_arguments["objections"],
            proposer_responses=normalized_arguments.get("proposer_responses"),
            resolver_notes=normalized_arguments.get("resolver_notes", ""),
        )

    if name == "adversarial_resolve":
        return svc.resolve_adversarial_round(
            topic_id=normalized_arguments["topic_id"],
            round_artifact_id=normalized_arguments["round_artifact_id"],
            scores=normalized_arguments.get("scores", {}),
            notes=normalized_arguments.get("notes", ""),
        )

    if name == "adversarial_status":
        return svc.check_adversarial_status(normalized_arguments["topic_id"])

    if name == "adversarial_review":
        return adversarial_review_executor(svc, db, normalized_arguments)

    if name == "experiment_handoff_prepare":
        return (
            experiment_handoff_prepare_executor
            or _missing_orchestrator_executor("experiment_handoff_prepare")
        )(svc, db, normalized_arguments)

    if name == "experiment_handoff_submit":
        return (
            experiment_handoff_submit_executor
            or _missing_orchestrator_executor("experiment_handoff_submit")
        )(svc, db, normalized_arguments)

    if name == "workflow_entry":
        return (
            workflow_entry_executor or _missing_orchestrator_executor("workflow_entry")
        )(svc, db, normalized_arguments)

    if name == "claim_verify":
        if claim_verify_executor is None:
            return {"error": "Missing orchestrator executor: claim_verify"}
        return claim_verify_executor(db, normalized_arguments)

    if name == "adversarial_section_review":
        return (
            adversarial_section_review_executor
            or _missing_orchestrator_executor("adversarial_section_review")
        )(svc, db, normalized_arguments)

    return {"error": f"Unknown orchestrator tool: {name}"}
