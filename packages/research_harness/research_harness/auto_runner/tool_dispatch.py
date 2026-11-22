"""Tool dispatch — maps stage policy tool names to executable functions.

Bridges the gap between stage_policy.StagePolicy.tools (string names)
and the actual execution layer (backends + orchestrator service).

Three categories:
  1. Primitive tools → executed via ExecutionBackend
  2. Orchestrator tools → executed via OrchestratorService methods
  3. Query tools → read-only operations (paper_list, review_issues, etc.)
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import checkpoint as ckpt
from ..execution.backend import PrimitiveResult
from ..experiment.coverage_gate import (
    ABLATION_CONTRACT_FIELDS,
    ABLATION_MEMORY_INPUT_FIELDS,
    ABLATION_MEMORY_RESULT_FIELD,
)
from ..execution.factory import create_backend
from ..orchestrator.service import OrchestratorService
from ..primitives.registry import PRIMITIVE_REGISTRY
from ..runtime import CapabilityManifest, RunSpec, RunTrace, RunVisibleInputs, TraceStep
from ..storage.db import Database

if TYPE_CHECKING:
    from .budget import BudgetMonitor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output normalization helpers
# ---------------------------------------------------------------------------


def _extract_section_text(output: dict[str, Any]) -> str:
    """Extract text content from section_draft output.

    Real SectionDraftOutput → {"draft": {"content": ..., "section": ...}}
    Fallback: output["text"] for simplified/mock outputs.
    """
    draft = output.get("draft")
    if isinstance(draft, dict):
        return draft.get("content", "")
    return output.get("text", output.get("content", ""))


def _extract_review_feedback(output: dict[str, Any]) -> str:
    """Extract review feedback from section_review output.

    Real SectionReviewOutput → {"suggestions": [...], "dimensions": [...]}
    """
    suggestions = output.get("suggestions", [])
    if suggestions:
        return "; ".join(str(s) for s in suggestions)
    dims = output.get("dimensions", [])
    if dims:
        return "; ".join(
            f"{d.get('dimension', '?')}: {d.get('comment', '')}"
            for d in dims
            if isinstance(d, dict)
        )
    return output.get("feedback", output.get("issues", ""))


def _extract_revise_text(output: dict[str, Any]) -> str:
    """Extract revised text from section_revise output.

    Real SectionReviseOutput → {"revised_content": ...}
    """
    return output.get("revised_content", output.get("text", output.get("content", "")))


def _slug_id(value: str, fallback: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    text = "-".join(part for part in text.split("-") if part)
    return text or fallback


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        return [
            str(key).strip()
            for key, item in value.items()
            if str(key).strip() and item is not None and item is not False
        ]
    if isinstance(value, (list, tuple, set, frozenset)):
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    return []


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _baseline_method_family(item: dict[str, Any]) -> str:
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    for key in ("method_family", "baseline_family", "family"):
        value = str(item.get(key) or metrics.get(key) or "").strip()
        if value:
            return value
    return ""


def _baseline_facets(item: dict[str, Any]) -> list[str]:
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    facets: list[str] = []
    for key in ("facets", "survey_facets", "covered_facets"):
        facets.extend(_as_string_list(item.get(key)))
        facets.extend(_as_string_list(metrics.get(key)))
    for key in ("facet", "survey_facet", "evaluation_facet"):
        value = str(item.get(key) or metrics.get(key) or "").strip()
        if value:
            facets.append(value)
    return _unique_strings(facets)


def _normalize_baseline_matrix_payload(
    baselines_out: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    raw_baselines = [
        item for item in baselines_out.get("baselines", []) if isinstance(item, dict)
    ]
    baselines: list[dict[str, Any]] = []
    for index, item in enumerate(raw_baselines):
        record = dict(item)
        name = str(record.get("name") or "").strip()
        fallback_id = f"baseline:{index + 1}"
        baseline_id = str(record.get("baseline_id") or record.get("id") or "").strip()
        record["baseline_id"] = baseline_id or _slug_id(name, fallback_id)
        paper_ids = record.get("source_paper_ids") or record.get("paper_ids")
        if paper_ids is not None:
            record["source_paper_ids"] = [
                int(item)
                for item in paper_ids
                if isinstance(item, int) or str(item).strip().isdigit()
            ]
        method_family = _baseline_method_family(record)
        if method_family:
            record["method_family"] = method_family
        facets = _baseline_facets(record)
        if facets:
            record["facets"] = facets
        baselines.append(record)

    coverage = (
        baselines_out.get("coverage")
        if isinstance(baselines_out.get("coverage"), dict)
        else {}
    )
    required_families = _unique_strings(
        _as_string_list(context.get("required_baseline_families"))
        or _as_string_list(coverage.get("required_families"))
        or _as_string_list(baselines_out.get("required_families"))
    )
    covered_families = _unique_strings(
        _as_string_list(coverage.get("covered_families"))
        or [
            family
            for family in (_baseline_method_family(item) for item in baselines)
            if family
        ]
    )
    required_facets = _unique_strings(
        _as_string_list(context.get("required_baseline_facets"))
        or _as_string_list(coverage.get("required_facets"))
        or _as_string_list(baselines_out.get("required_facets"))
    )
    covered_facets = _unique_strings(
        _as_string_list(coverage.get("covered_facets"))
        or [facet for item in baselines for facet in _baseline_facets(item) if facet]
    )

    payload: dict[str, Any] = {
        "baselines": baselines,
        "baseline_count": len(baselines),
        "coverage": {
            "required_families": required_families,
            "covered_families": covered_families,
            "missing_families": sorted(set(required_families) - set(covered_families)),
            "required_facets": required_facets,
            "covered_facets": covered_facets,
            "missing_facets": sorted(set(required_facets) - set(covered_facets)),
        },
        "focus": context.get("focus", ""),
    }
    novelty_decision = baselines_out.get("novelty_decision")
    if isinstance(novelty_decision, dict):
        payload["novelty_decision"] = dict(novelty_decision)
    trace = baselines_out.get("trace")
    if isinstance(trace, dict):
        payload["trace"] = dict(trace)
    return payload


def _paper_production_policy_from_context(context: dict[str, Any]) -> dict[str, Any]:
    # Single source of truth for schema membership (entry writes v2; a v1
    # literal here silently dropped the whole policy on live runs).
    policy = ckpt.paper_production_policy(
        {"paper_production_run_policy": context.get("paper_production_run_policy")}
    )
    return dict(policy)


def _is_demo_seed_pool_context(context: dict[str, Any]) -> bool:
    policy = _paper_production_policy_from_context(context)
    return (
        policy.get("mode") == "demo"
        and policy.get("evidence_boundary") == "demo_limited_seed_pool"
    )


def _fetch_topic_seed_papers(
    db: Database | None,
    *,
    topic_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if db is None:
        return []
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.year, p.venue, p.status, p.pdf_path, pt.relevance
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND pt.relevance != 'dismissed'
            ORDER BY
              CASE pt.relevance
                WHEN 'high' THEN 0
                WHEN 'medium' THEN 1
                ELSE 2
              END,
              p.year DESC,
              p.id
            LIMIT ?
            """,
            (topic_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _has_demo_seed_pool(
    db: Database | None,
    *,
    topic_id: int,
    minimum: int = 3,
) -> bool:
    return (
        len(_fetch_topic_seed_papers(db, topic_id=topic_id, limit=minimum)) >= minimum
    )


def _seed_pool_clusters(seed_papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not seed_papers:
        return []
    venues: dict[str, list[dict[str, Any]]] = {}
    for paper in seed_papers:
        venue = str(paper.get("venue") or "unknown venue").strip() or "unknown venue"
        venues.setdefault(venue, []).append(paper)
    return [
        {
            "cluster_id": f"venue:{_slug_id(venue, 'unknown')}",
            "label": venue,
            "paper_ids": [int(item["id"]) for item in papers if item.get("id")],
            "paper_count": len(papers),
        }
        for venue, papers in sorted(venues.items())
    ]


def _record_artifact_safe(
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    artifact_type: str,
    title: str,
    payload: dict[str, Any],
    recorded: list[tuple[str, int]],
    errors: list[str],
) -> None:
    try:
        art = svc.record_artifact(
            topic_id=topic_id,
            stage=stage,
            artifact_type=artifact_type,
            title=title,
            payload=payload,
        )
        art_id = art.id if hasattr(art, "id") else 0
        if art_id:
            recorded.append((artifact_type, art_id))
    except Exception as exc:
        errors.append(f"auto_artifact[{artifact_type}]: {exc}")


def _record_artifact_returning_id(
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    artifact_type: str,
    title: str,
    payload: dict[str, Any],
    recorded: list[tuple[str, int]],
    errors: list[str],
    dependency_artifact_ids: list[int] | None = None,
    dependency_type: str = "derived_from",
) -> int:
    try:
        art = svc.record_artifact(
            topic_id=topic_id,
            stage=stage,
            artifact_type=artifact_type,
            title=title,
            payload=payload,
            dependency_artifact_ids=dependency_artifact_ids,
            dependency_type=dependency_type,
        )
        art_id = art.id if hasattr(art, "id") else 0
        if art_id:
            recorded.append((artifact_type, art_id))
        return int(art_id or 0)
    except Exception as exc:
        errors.append(f"auto_artifact[{artifact_type}]: {exc}")
        return 0


def _record_demo_seed_pool_analyze_artifacts(
    *,
    svc: OrchestratorService,
    db: Database | None,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
    recorded: list[tuple[str, int]],
    errors: list[str],
) -> bool:
    if not _is_demo_seed_pool_context(context):
        return False
    seed_papers = _fetch_topic_seed_papers(db, topic_id=topic_id)
    if len(seed_papers) < 3:
        return False
    seed_payload = {
        "source": "existing_topic_seed_pool",
        "paper_count": len(seed_papers),
        "papers": seed_papers,
        "target_venue": context.get("target_venue", ""),
        "evidence_boundary": "demo_limited_seed_pool",
        "submission_readiness": "not_submission_ready",
        "claim_strength_limit": "evidence_limited_demo",
    }
    _record_artifact_safe(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="claim_candidate_set",
        title="Demo claim candidates from seed pool",
        payload={
            **seed_payload,
            "claims": [
                {
                    "claim_id": "demo_seed_pool_claim",
                    "text": "The local seed pool is sufficient only for bounded pipeline smoke testing, not submission-ready claims.",
                    "supporting_paper_ids": [
                        int(item["id"]) for item in seed_papers[:3]
                    ],
                    "certainty": "bounded_demo",
                }
            ],
        },
        recorded=recorded,
        errors=errors,
    )
    _record_artifact_safe(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="evidence_pack",
        title="Demo evidence pack from seed pool",
        payload={
            **seed_payload,
            "evidence_items": [
                {
                    "paper_id": int(item["id"]),
                    "title": item.get("title", ""),
                    "role": "seed_pool_context",
                }
                for item in seed_papers[:10]
            ],
            "blockers": [
                "full-text evidence extraction required before submission use",
                "claim-level source tracing required before manuscript promotion",
            ],
        },
        recorded=recorded,
        errors=errors,
    )
    required_families = ["agent", "evaluation", "retrieval", "system"]
    baseline_artifact_id = _record_artifact_returning_id(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="baseline_matrix",
        title="Demo baseline matrix from seed pool",
        payload={
            **seed_payload,
            "baselines": [
                {
                    "baseline_id": f"demo_{family}",
                    "method_family": family,
                    "source_paper_ids": [int(item["id"]) for item in seed_papers[:3]],
                    "relationship_to_proposal": "bounded_demo_context",
                }
                for family in required_families
            ],
            "coverage": {
                "required_families": required_families,
                "covered_families": required_families,
            },
        },
        recorded=recorded,
        errors=errors,
    )
    _record_artifact_safe(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="direction_proposal",
        title="Demo direction proposal from seed pool",
        payload={
            **seed_payload,
            "research_question": context.get("topic_description")
            or context.get("query", ""),
            "proposal_status": "bounded_demo_not_submission_ready",
            "trace": {
                "source_artifact_ids": [baseline_artifact_id]
                if baseline_artifact_id
                else []
            },
            "next_required_for_submission": [
                "run claim extraction on verified full text",
                "build baseline matrix",
                "record gap analysis with source traces",
            ],
        },
        recorded=recorded,
        errors=errors,
    )
    return True


def _record_demo_seed_pool_build_artifacts(
    *,
    svc: OrchestratorService,
    db: Database | None,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
    seed_boundary: str,
    recorded: list[tuple[str, int]],
    errors: list[str],
) -> bool:
    seed_papers = _fetch_topic_seed_papers(db, topic_id=topic_id)
    if seed_boundary != "demo_limited_seed_pool" or len(seed_papers) < 3:
        return False
    seed_payload = {
        "source": "existing_topic_seed_pool",
        "paper_count": len(seed_papers),
        "papers": seed_papers,
        "target_venue": context.get("target_venue", ""),
        "evidence_boundary": seed_boundary,
        "submission_readiness": "not_submission_ready",
        "claim_strength_limit": "evidence_limited_demo",
    }
    _record_artifact_safe(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="literature_map",
        title="Demo literature map from existing seed pool",
        payload={
            **seed_payload,
            "clusters": _seed_pool_clusters(seed_papers),
            "themes": [
                "seed-pool coverage only",
                "demo evidence for end-to-end smoke testing",
            ],
        },
        recorded=recorded,
        errors=errors,
    )
    _record_artifact_safe(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="paper_pool_snapshot",
        title="Demo paper pool snapshot",
        payload=seed_payload,
        recorded=recorded,
        errors=errors,
    )
    _record_artifact_safe(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="citation_expansion_report",
        title="Demo citation expansion boundary",
        payload={
            "status": "bounded_demo_not_expanded",
            "seed_paper_count": len(seed_papers),
            "evidence_boundary": seed_boundary,
            "submission_readiness": "not_submission_ready",
            "claim_strength_limit": "evidence_limited_demo",
            "next_required_for_submission": [
                "run citation expansion",
                "increase corpus coverage",
                "verify full-text acquisition",
            ],
        },
        recorded=recorded,
        errors=errors,
    )
    pdf_count = sum(1 for item in seed_papers if item.get("pdf_path"))
    _record_artifact_safe(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="acquisition_report",
        title="Demo acquisition boundary",
        payload={
            "status": "bounded_demo_seed_metadata",
            "seed_paper_count": len(seed_papers),
            "pdf_count": pdf_count,
            "evidence_boundary": seed_boundary,
            "submission_readiness": "not_submission_ready",
            "claim_strength_limit": "evidence_limited_demo",
            "next_required_for_submission": [
                "acquire full text",
                "annotate or summarize corpus",
                "record source trace for claims",
            ],
        },
        recorded=recorded,
        errors=errors,
    )
    return True


def _run_section_loops(
    *,
    db: Database,
    topic_id: int,
    context: dict[str, Any],
    results: list["ToolResult"],
    errors: list[str],
) -> None:
    """Run run_section_loop() for every section in sections_to_draft.

    ADR-001 Decision 1: this is the canonical write-stage loop. Populates
    context[_output_section_draft_{sec}], _output_section_review_{sec}, and
    _output_section_revise_{sec} so that existing downstream tools (citation
    verify, latex compile, etc.) continue to read their inputs as before.
    """
    from ..execution.loops import run_section_loop
    from ..execution.paper_context import build_paper_context

    sections = context.get("sections_to_draft", []) or []
    outline = context.get("outline", "")
    evidence_ids = context.get("evidence_ids", [])
    max_words = int(context.get("max_words", 2000))
    paper_plan = context.get("paper_plan")
    strict_evidence = context.get("strict_evidence")
    extra_instructions = str(context.get("extra_instructions") or "")
    max_rounds = int(context.get("section_loop_max_rounds", 3))
    min_score = float(context.get("section_loop_min_score", 0.75))
    adversarial = bool(context.get("section_loop_adversarial", True))

    # One shared paper context for the whole write run: later sections see
    # earlier ones (full text, budgeted at render time), so the paper stops
    # being drafted in isolation.
    paper_ctx = build_paper_context(
        db,
        topic_id,
        paper_plan=paper_plan if isinstance(paper_plan, dict) else None,
        outline=outline if isinstance(outline, str) else "",
    )

    # EAG style card: exemplar_plan_style artifact -> writing_patterns.
    # The channel existed downstream but had no producer.
    writing_patterns = str(context.get("writing_patterns") or "")
    if not writing_patterns:
        try:
            from research_harness.orchestrator import OrchestratorService

            _style_art = OrchestratorService(db).get_latest_artifact(
                topic_id, "write", "exemplar_plan_style"
            )
            _style_plan = (
                _style_art.payload.get("plan", {})
                if (_style_art and isinstance(_style_art.payload, dict))
                else {}
            )
            if _style_plan:
                writing_patterns = json.dumps(_style_plan, ensure_ascii=False)[:3000]
                context["writing_patterns"] = writing_patterns
        except Exception:
            logger.debug("exemplar style plan unavailable", exc_info=True)

    for sec in sections:
        try:
            loop = run_section_loop(
                db=db,
                section=sec,
                topic_id=topic_id,
                outline=outline,
                max_words=max_words,
                max_rounds=max_rounds,
                min_score=min_score,
                evidence_ids=evidence_ids,
                paper_plan=paper_plan if isinstance(paper_plan, dict) else None,
                strict_evidence=(
                    bool(strict_evidence) if strict_evidence is not None else None
                ),
                extra_instructions=extra_instructions,
                paper_context=paper_ctx.to_dict(),
                adversarial=adversarial,
                writing_patterns=writing_patterns,
            )
            content = loop.final_output if isinstance(loop.final_output, str) else ""
            if content.strip():
                # Full text; render_paper_context budgets what later sections see
                # (previous section's ending in full, earlier ones digested).
                paper_ctx.drafted[sec] = content
            normalized = {
                "text": content,
                "rounds": loop.total_rounds,
                "score": loop.final_score,
                "converged": loop.converged,
                "decision": loop.decision,
            }
            context.setdefault("_drafted_sections", []).append(sec)
            context[f"_output_section_draft_{sec}"] = {"text": content}
            # Last iteration feedback seeds the review slot for downstream tools.
            last_feedback = loop.iterations[-1].feedback if loop.iterations else ""
            context[f"_output_section_review_{sec}"] = {"feedback": last_feedback}
            context[f"_output_section_revise_{sec}"] = {"text": content}
            # Record on "section_draft" so dispatch summaries keep the tool name.
            results.append(
                ToolResult(
                    tool="section_draft",
                    success=True,
                    output=normalized,
                )
            )
        except Exception as exc:
            logger.warning("run_section_loop[%s] failed: %s", sec, exc)
            errors.append(f"run_section_loop[{sec}]: {exc}")
            results.append(
                ToolResult(
                    tool="section_draft",
                    success=False,
                    error=str(exc)[:500],
                )
            )


def _apply_consistency_repairs(
    *,
    db: Database,
    topic_id: int | None = None,
    context: dict[str, Any],
    results: list["ToolResult"],
    errors: list[str],
) -> None:
    """Turn consistency_check issues into one targeted section_revise round.

    Only high/critical issues trigger a repair; each affected section is
    revised once with the full issue list for that section as feedback, and
    the revised text replaces the drafted output so downstream tools (figure
    injection, latex compile) pick it up.
    """
    from ..execution import llm_primitives

    issues = (context.get("_output_consistency_check") or {}).get("issues") or []
    drafted = context.get("_drafted_sections", []) or []
    if not issues or not drafted:
        return

    actionable = [
        i
        for i in issues
        if isinstance(i, dict)
        and str(i.get("severity", "")).lower() in ("high", "critical")
    ]
    if not actionable:
        return

    # Map each issue to the drafted sections its location names; unmapped
    # issues go to every section mentioned in none (skipped rather than
    # broadcast, to keep the repair targeted).
    by_section: dict[str, list[dict[str, Any]]] = {}
    for issue in actionable:
        loc = str(issue.get("location", "")).lower()
        for sec in drafted:
            if sec.lower().replace("_", " ") in loc or sec.lower() in loc:
                by_section.setdefault(sec, []).append(issue)

    for sec, sec_issues in by_section.items():
        content = context.get(f"_output_section_draft_{sec}", {}).get("text", "")
        if not content:
            continue
        feedback_lines = [
            f"- [{i.get('severity')}] {i.get('issue_type', 'consistency')}: "
            f"{i.get('description', '')} "
            + (f"Suggestion: {i.get('suggestion')}" if i.get("suggestion") else "")
            for i in sec_issues
        ]
        feedback = (
            "Whole-manuscript consistency check found issues this section must "
            "fix (keep all citation markers and evidence intact):\n"
            + "\n".join(feedback_lines)
        )
        try:
            revise = llm_primitives.section_revise(
                db=db,
                section=sec,
                content=content,
                review_feedback=feedback,
                topic_id=context.get("topic_id") or topic_id,
                paper_context=context.get("paper_context"),
            )
            revised = getattr(revise, "revised_content", "") or ""
            if revised.strip():
                context[f"_output_section_draft_{sec}"] = {"text": revised}
                context[f"_output_section_revise_{sec}"] = {"text": revised}
                results.append(
                    ToolResult(
                        tool="section_revise",
                        success=True,
                        output={
                            "section": sec,
                            "source": "consistency_repair",
                            "issues_addressed": len(sec_issues),
                        },
                    )
                )
        except Exception as exc:
            logger.warning("consistency repair for '%s' failed: %s", sec, exc)
            errors.append(f"consistency_repair[{sec}]: {exc}")


@dataclass
class ToolResult:
    """Result of dispatching one tool."""

    tool: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def _to_dict(obj: Any) -> dict[str, Any]:
    """Convert a dataclass or primitive result to a serializable dict."""
    if isinstance(obj, dict):
        return obj
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return {"result": str(obj)}


def _run_runtime_gate(
    *,
    capability_manifest: CapabilityManifest | dict[str, Any] | None,
    run_spec: RunSpec | dict[str, Any] | None,
    tools: tuple[str, ...],
) -> dict[str, Any] | None:
    if capability_manifest is None and run_spec is None:
        return None
    if capability_manifest is None or run_spec is None:
        missing = "capability_manifest" if capability_manifest is None else "run_spec"
        return {
            "guardrail_results": [
                {
                    "name": "runtime_contract_present",
                    "scope": "input",
                    "passed": False,
                    "severity": "blocking",
                    "tripwire_triggered": True,
                    "checked_refs": [],
                    "diagnostics": [{"missing": missing}],
                }
            ]
        }

    capability = _coerce_capability_manifest(capability_manifest)
    spec = _coerce_run_spec(run_spec)
    return {
        "guardrail_results": [
            result.to_dict()
            for result in capability.validate_run_spec(spec, requested_tools=tools)
        ]
    }


def _coerce_capability_manifest(
    value: CapabilityManifest | dict[str, Any],
) -> CapabilityManifest:
    if isinstance(value, CapabilityManifest):
        return value
    data = dict(value)
    return CapabilityManifest(**data)


def _coerce_run_spec(value: RunSpec | dict[str, Any]) -> RunSpec:
    if isinstance(value, RunSpec):
        return value
    data = dict(value)
    visible_inputs = data.get("visible_inputs")
    if isinstance(visible_inputs, dict):
        data["visible_inputs"] = RunVisibleInputs(**visible_inputs)
    return RunSpec(**data)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_stage_run_trace(
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    tools: tuple[str, ...],
    results: list["ToolResult"],
    errors: list[str],
    runtime_gate: dict[str, Any] | None,
    auto_artifacts: list[tuple[str, int]],
) -> tuple[str, int] | None:
    """Persist a canonical runtime trace for a non-skill stage dispatch."""

    started_at = _utc_now()
    steps: list[TraceStep] = []
    step_index = 1

    if runtime_gate is not None:
        guardrails = runtime_gate.get("guardrail_results", [])
        guardrail_failed = any(not item.get("passed") for item in guardrails)
        steps.append(
            TraceStep(
                step_id=f"{stage}.guardrail.{step_index}",
                kind="guardrail",
                status="blocked" if guardrail_failed else "success",
                started_at=started_at,
                finished_at=started_at,
                metadata={
                    "stage": stage,
                    "guardrail_results": guardrails,
                },
            )
        )
        step_index += 1

    for result in results:
        ts = _utc_now()
        steps.append(
            TraceStep(
                step_id=f"{stage}.tool.{step_index}",
                kind="tool_call",
                status="success" if result.success else "failed",
                started_at=ts,
                finished_at=ts,
                output_ref=f"tool:{result.tool}",
                metadata={
                    "stage": stage,
                    "tool_name": result.tool,
                    "requested_tools": list(tools),
                    "error": result.error,
                },
            )
        )
        step_index += 1

    for artifact_type, artifact_id in auto_artifacts:
        ts = _utc_now()
        steps.append(
            TraceStep(
                step_id=f"{stage}.artifact.{step_index}",
                kind="artifact_write",
                status="success",
                started_at=ts,
                finished_at=ts,
                output_ref=f"artifact:{artifact_type}:{artifact_id}",
                metadata={
                    "stage": stage,
                    "artifact_type": artifact_type,
                    "artifact_id": artifact_id,
                },
            )
        )
        step_index += 1

    trace = RunTrace(
        run_id=f"auto_runner.stage.{topic_id}.{stage}.{started_at}",
        task_id=f"topic:{topic_id}",
        trial_id=f"topic:{topic_id}",
        status="failed" if errors else "success",
        started_at=started_at,
        finished_at=_utc_now(),
        inputs={
            "topic_id": topic_id,
            "stage": stage,
            "requested_tools": list(tools),
        },
        steps=tuple(steps),
        outputs={"artifact_ids": [artifact_id for _, artifact_id in auto_artifacts]},
        errors=tuple({"message": error} for error in errors),
    )
    artifact = svc.record_artifact(
        topic_id=topic_id,
        stage=stage,
        artifact_type="run_trace",
        title=f"Auto-runner {stage} trace",
        payload=trace.to_dict(),
    )
    artifact_id = artifact.id if hasattr(artifact, "id") else 0
    if not artifact_id:
        return None
    return ("run_trace", int(artifact_id))


# ---------------------------------------------------------------------------
# Primitive tools — dispatched via ExecutionBackend
# ---------------------------------------------------------------------------

_PRIMITIVE_TOOLS = frozenset(PRIMITIVE_REGISTRY.keys())

# Orchestrator tools — dispatched via OrchestratorService
_ORCHESTRATOR_TOOLS = frozenset(
    {
        "orchestrator_status",
        "orchestrator_record_artifact",
        "orchestrator_advance",
        "orchestrator_gate_check",
        "orchestrator_resume",
    }
)

# Service tools — methods on OrchestratorService
_SERVICE_TOOLS = frozenset(
    {
        "adversarial_run",
        "adversarial_resolve",
        "adversarial_status",
        "adversarial_review",
        "integrity_check",
        "review_add_issue",
        "review_bundle_create",
        "review_issues",
        "review_respond",
        "review_resolve",
        "review_status",
        "finalize_project",
    }
)

# Read-only query tools — thin wrappers
_QUERY_TOOLS = frozenset(
    {
        "paper_list",
        "paper_coverage_check",
        "paper_dismiss",
        "topic_list",
        "topic_show",
    }
)


def _suite_spec_from_context(context: dict[str, Any]) -> dict[str, Any]:
    suite_out = context.get("_output_figure_suite_plan") or {}
    if isinstance(suite_out, dict):
        spec = suite_out.get("spec")
        if isinstance(spec, dict):
            return spec
        if suite_out.get("figures") or suite_out.get("target_venue"):
            return suite_out
    return {}


def _missing_predraw_fields(context: dict[str, Any]) -> list[str]:
    """Nail 2: target_venue, venue_figure_grammar, figure_modules before pixels."""
    spec = _suite_spec_from_context(context)
    venue = str(
        spec.get("target_venue")
        or context.get("target_venue")
        or context.get("venue")
        or ""
    ).strip()
    grammar = spec.get("venue_figure_grammar") or spec.get("result_plot_policy")
    modules = spec.get("figure_modules")
    missing: list[str] = []
    if not venue:
        missing.append("target_venue")
    if not (isinstance(grammar, dict) and grammar):
        missing.append("venue_figure_grammar")
    if not (isinstance(modules, dict) and modules):
        missing.append("figure_modules")
    return missing


def _figure_generation_provider_ready() -> bool:
    """True when a real figure provider is configured for figure_generate."""
    if os.environ.get("RESEARCH_HARNESS_FIGURE_MODEL", "").strip():
        return True
    try:
        from research_harness.integrations.figure_image_provider import (
            figure_image_generation_ready,
        )

        return bool(figure_image_generation_ready())
    except Exception:  # noqa: BLE001 - provider probe must not break dispatch
        return False


def _context_bound_tool_skip_reason(tool_name: str, context: dict[str, Any]) -> str:
    """Return a skip reason for tools that require explicit upstream context."""

    if tool_name == "paper_dismiss" and not context.get("paper_id"):
        return "paper_dismiss requires paper_id in context"
    if tool_name == "figure_suite_render":
        suite_out = context.get("_output_figure_suite_plan") or {}
        spec = suite_out.get("spec") if isinstance(suite_out, dict) else None
        if not (isinstance(spec, dict) and spec.get("figures")):
            return "figure_suite_render requires figure_suite_plan spec in context"
        draw_gap = _missing_predraw_fields(context)
        if draw_gap:
            return (
                "figure_suite_render skipped: missing pre-draw fields "
                f"({', '.join(draw_gap)}); cannot draw"
            )
    if tool_name == "figure_generate":
        figure_plan_out = context.get("_output_figure_plan") or {}
        if not figure_plan_out.get("items"):
            return "figure_generate requires figure_plan items in context"
        draw_gap = _missing_predraw_fields(context)
        if draw_gap:
            return (
                "figure_generate skipped: missing pre-draw fields "
                f"({', '.join(draw_gap)}); cannot draw"
            )
        if not _figure_generation_provider_ready():
            # With no provider configured, the sanctioned degraded state is a
            # deterministic local figure plus an ILLUSTRATION_PENDING marker.
            # With a provider ready, the write gate blocks pending fallbacks,
            # so this tool must actually run.
            return (
                "figure_generate skipped: no figure provider configured "
                "(illustration backends and RESEARCH_HARNESS_FIGURE_MODEL unset)"
            )
    if tool_name == "evidence_link" and not (
        context.get("claim_id")
        and context.get("source_type")
        and context.get("source_id")
    ):
        return "evidence_link requires claim_id, source_type, and source_id in context"
    if tool_name in {
        "adversarial_run",
        "adversarial_resolve",
        "adversarial_review",
        "integrity_check",
        "review_add_issue",
        "review_respond",
    }:
        has_context_args = any(
            context.get(key)
            for key in (
                "issue_id",
                "adversarial_case",
                "adversarial_report",
                "review_issue",
                "artifact_id",
                "response",
            )
        )
        if not has_context_args:
            return f"{tool_name} requires LLM-constructed context arguments"
    return ""


_DEMO_SEED_POOL_EXPANSION_TOOLS = frozenset(
    {
        "paper_search",
        "paper_ingest",
        "paper_acquire",
        "select_seeds",
        "expand_citations",
    }
)


def _demo_seed_pool_expansion_skip_reason(
    tool_name: str,
    *,
    stage: str,
    context: dict[str, Any],
    db: Database | None = None,
    topic_id: int | None = None,
) -> str:
    """Return a skip reason for expansion tools in bounded demo runs.

    A paper-production demo run with an existing seed pool is intentionally
    bound to those papers. Later stages should analyze, propose, experiment, and
    write from that evidence boundary instead of reopening the literature-
    acquisition loop. Cold-start demo runs may still search until the seed pool
    exists.
    """

    if tool_name not in _DEMO_SEED_POOL_EXPANSION_TOOLS:
        return ""
    if not _is_demo_seed_pool_context(context):
        return ""
    if stage in {"init", "build"}:
        if topic_id is None or not _has_demo_seed_pool(db, topic_id=topic_id):
            return ""
        return (
            f"{tool_name} skipped: paper-production demo_limited_seed_pool "
            "reuses the existing seed pool instead of expanding literature"
        )
    return (
        f"{tool_name} skipped: paper-production demo_limited_seed_pool "
        "reuses the build-stage seed pool after build"
    )


def _build_demo_seed_pool_paper_plan(context: dict[str, Any]) -> dict[str, Any]:
    target_venue = str(
        context.get("target_venue") or context.get("venue") or ""
    ).strip()
    return {
        "schema_version": "rh.delivery.paper_plan.v1",
        "status": "pass",
        "submission_readiness": "not_submission_ready",
        "evidence_boundary": "demo_limited_seed_pool",
        "claim_strength_limit": "evidence_limited_demo",
        "automation_scope": "paper_production_demo_pdf_smoke",
        "target_venue": target_venue,
        "manuscript_logic_gate_report": {
            "schema_version": "rh.manuscript.logic_gate_report.v1",
            "status": "pass",
            "blockers": [],
            "scope": "demo_limited_seed_pool",
            "notes": [
                "Allows bounded demo drafting from existing seed-pool evidence.",
                "Does not represent submission-ready manuscript logic approval.",
            ],
        },
        "fine_logic_audit_report": {
            "schema_version": "rh.manuscript.fine_logic_audit_report.v1",
            "status": "pass",
            "blockers": [],
            "scope": "demo_limited_seed_pool",
            "notes": [
                "Allows bounded demo drafting from existing seed-pool evidence.",
                "Requires full fine-logic audit before submission readiness.",
            ],
        },
        "promotion_blockers": [
            "demo_limited_seed_pool",
            "full_paper_plan_not_promoted",
            "submission_readiness_not_claimed",
        ],
        "source_artifacts": {
            "direction_proposal": context.get("artifact_payload", {}),
            "study_spec": context.get("study_spec", ""),
        },
    }


def _ensure_demo_seed_pool_write_plan(context: dict[str, Any]) -> None:
    if context.get("paper_plan") is not None:
        return
    if not _is_demo_seed_pool_context(context):
        return
    context["paper_plan"] = _build_demo_seed_pool_paper_plan(context)
    context.setdefault("strict_evidence", False)
    context["paper_plan_ready"] = True


def _demo_seed_pool_section_text(section: str, context: dict[str, Any]) -> str:
    topic = str(
        context.get("title")
        or context.get("topic_description")
        or context.get("query")
        or "Research Harness demo topic"
    ).strip()
    target_venue = str(
        context.get("target_venue") or context.get("venue") or "target venue"
    ).strip()
    section_label = section.replace("_", " ").title()
    if section == "abstract":
        return (
            f"This bounded demo manuscript for {target_venue} verifies that "
            f"Research Harness can advance the topic '{topic}' through a local "
            "paper-production PDF closure. The evidence pool, experiment, and "
            "claims are intentionally limited to smoke-test artifacts and are "
            "not submission ready."
        )
    if section == "method":
        return (
            "The method treats the existing seed pool, proposal artifact, and "
            "deterministic smoke experiment as fixed inputs. RH records a paper "
            "plan, drafts bounded sections, assembles a final bundle, and emits "
            "a publication package without opening external actions."
        )
    if section == "experiment_summary":
        return (
            "The experiment stage reports execution_success for the deterministic "
            "demo smoke run. These metrics only verify orchestration, artifact "
            "recording, and result-to-manuscript wiring; they do not establish "
            "scientific validity."
        )
    if section == "limitations":
        return (
            "This PDF is an end-to-end readiness artifact. Submission requires "
            "full corpus acquisition, source-grounded analysis, real experiments, "
            "citation audit, venue compliance, and human scholarly review."
        )
    return (
        f"{section_label}: bounded demo content generated from the RH paper-"
        "production smoke context. This section is not submission ready."
    )


def _ensure_demo_seed_pool_write_sections(context: dict[str, Any]) -> bool:
    if not _is_demo_seed_pool_context(context):
        return False
    _ensure_demo_seed_pool_write_plan(context)
    sections = context.get("sections_to_draft") or [
        "abstract",
        "method",
        "experiment_summary",
        "limitations",
    ]
    normalized_sections = [str(section).strip() for section in sections if section]
    if not normalized_sections:
        normalized_sections = [
            "abstract",
            "method",
            "experiment_summary",
            "limitations",
        ]
    context["sections_to_draft"] = normalized_sections
    drafted = context.setdefault("_drafted_sections", [])
    for section in normalized_sections:
        if section not in drafted:
            drafted.append(section)
        key = f"_output_section_draft_{section}"
        context.setdefault(
            key, {"text": _demo_seed_pool_section_text(section, context)}
        )
        context.setdefault(
            f"_output_section_review_{section}",
            {"feedback": "Demo smoke section accepted for local PDF closure."},
        )
        context.setdefault(f"_output_section_revise_{section}", context[key])
    return True


def _write_demo_seed_pool_pdf(
    pdf_path: Path, *, title: str, sections: dict[str, str]
) -> str:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fitz  # type: ignore

        doc = fitz.open()
        page = doc.new_page()
        y = 72
        page.insert_text(
            (72, y), title[:160] or "Research Harness Demo Paper", fontsize=16
        )
        y += 34
        for name, text in sections.items():
            page.insert_text((72, y), name.replace("_", " ").title(), fontsize=12)
            y += 20
            for line in _wrap_plain_text(text, width=92):
                if y > 760:
                    page = doc.new_page()
                    y = 72
                page.insert_text((72, y), line, fontsize=10)
                y += 14
            y += 10
        doc.save(str(pdf_path))
        doc.close()
        return "pymupdf"
    except Exception:
        pdf_path.write_bytes(
            b"%PDF-1.4\n"
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
            b"4 0 obj << /Length 91 >> stream\n"
            b"BT /F1 14 Tf 72 720 Td (Research Harness demo PDF smoke artifact.) Tj ET\n"
            b"endstream endobj\n"
            b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
            b"trailer << /Root 1 0 R >>\n%%EOF\n"
        )
        return "minimal_pdf_fallback"


def _wrap_plain_text(text: str, *, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines or [""]


def _ensure_demo_seed_pool_pdf_closure(
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
    recorded: list[tuple[str, int]],
    errors: list[str],
) -> bool:
    if stage != "write" or not _is_demo_seed_pool_context(context):
        return False
    _ensure_demo_seed_pool_write_sections(context)
    drafted = context.get("_drafted_sections", [])
    sections = {
        str(section): str(
            context.get(f"_output_section_draft_{section}", {}).get("text", "")
        )
        for section in drafted
        if str(
            context.get(f"_output_section_draft_{section}", {}).get("text", "")
        ).strip()
    }
    if not sections:
        return False

    output_dir = Path(str(context.get("output_dir") or "paper-production"))
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    output_dir = output_dir / f"demo-write-topic-{topic_id}"
    title = str(
        context.get("title")
        or context.get("topic_description")
        or context.get("query")
        or "Research Harness Demo Paper"
    ).strip()
    tex_path = output_dir / "paper.tex"
    pdf_path = output_dir / "paper.pdf"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text(
        "\\documentclass{article}\n"
        "\\usepackage[margin=1in]{geometry}\n"
        "\\begin{document}\n"
        f"\\title{{{_latex_escape(title)}}}\n"
        "\\author{Research Harness}\n"
        "\\maketitle\n"
        + "\n".join(
            f"\\section{{{_latex_escape(name.replace('_', ' ').title())}}}\n"
            f"{_latex_escape(text)}\n"
            for name, text in sections.items()
        )
        + "\\end{document}\n",
        encoding="utf-8",
    )
    pdf_generator = _write_demo_seed_pool_pdf(pdf_path, title=title, sections=sections)

    final_payload = {
        "schema_version": "rh.paper_production.demo_final_bundle.v1",
        "status": "ready",
        "readiness_scope": "demo_pdf_smoke",
        "submission_ready": False,
        "submission_readiness": "not_submission_ready",
        "evidence_boundary": "demo_limited_seed_pool",
        "claim_strength_limit": "evidence_limited_demo",
        "output_dir": str(output_dir),
        "tex_path": str(tex_path),
        "compiled_pdf_path": str(pdf_path),
        "pdf_path": str(pdf_path),
        "pdf_generator": pdf_generator,
        "sections": list(sections),
        "section_count": len(sections),
        "target_venue": context.get("target_venue", context.get("venue", "")),
    }
    draft_pack_id = _latest_recorded_artifact_id(recorded, "draft_pack")
    final_bundle_id = _record_artifact_returning_id(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="final_bundle",
        title="Demo final PDF bundle",
        payload=final_payload,
        recorded=recorded,
        errors=errors,
    )
    process_summary_id = _record_artifact_returning_id(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="process_summary",
        title="Demo writing process summary",
        payload={
            "schema_version": "rh.paper_production.demo_process_summary.v1",
            "status": "complete",
            "readiness_scope": "demo_pdf_smoke",
            "sections_drafted": list(sections),
            "sections_count": len(sections),
            "final_pdf_path": str(pdf_path),
            "submission_ready": False,
            "submission_readiness": "not_submission_ready",
        },
        recorded=recorded,
        errors=errors,
        dependency_artifact_ids=[
            artifact_id
            for artifact_id in (draft_pack_id, final_bundle_id)
            if artifact_id
        ],
    )
    source_artifacts = [
        {
            "artifact_type": "draft_pack",
            "status": "present" if draft_pack_id else "missing",
            "artifact_id": draft_pack_id,
        },
        {
            "artifact_type": "final_bundle",
            "status": "present" if final_bundle_id else "missing",
            "artifact_id": final_bundle_id,
        },
    ]
    dependency_ids = [
        artifact_id
        for artifact_id in (draft_pack_id, final_bundle_id, process_summary_id)
        if artifact_id
    ]
    _record_artifact_returning_id(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        artifact_type="publication_pack",
        title="Demo publication pack",
        payload={
            "schema_version": "rh.paper_production.demo_publication_pack.v1",
            "status": "review_ready_demo",
            "readiness_scope": "demo_pdf_smoke",
            "ready_for_review": True,
            "submission_ready": False,
            "submission_readiness": "not_submission_ready",
            "missing_required": [],
            "qa_checks": [
                {
                    "check": "demo_pdf_exists",
                    "passed": pdf_path.exists(),
                    "severity": "blocking",
                    "message": str(pdf_path),
                },
                {
                    "check": "submission_scope",
                    "passed": True,
                    "severity": "informational",
                    "message": "Demo smoke pack is not submission ready.",
                },
            ],
            "outputs": {
                "manuscript_pdf_path": str(pdf_path),
                "latex_source_path": str(tex_path),
            },
            "source_artifacts": source_artifacts,
            "artifact_refs": {
                item[
                    "artifact_type"
                ]: f"project_artifacts:{item['artifact_id']}:{item['artifact_type']}"
                for item in source_artifacts
                if item["artifact_id"]
            },
        },
        recorded=recorded,
        errors=errors,
        dependency_artifact_ids=dependency_ids,
    )
    context["_output_latex_compile"] = dict(final_payload)
    context["_output_publication_run"] = {
        "status": "review_ready_demo",
        "submission_ready": False,
        "publication_pack_status": "demo_pdf_smoke",
    }
    return True


def _latest_recorded_artifact_id(
    recorded: list[tuple[str, int]],
    artifact_type: str,
) -> int:
    for recorded_type, artifact_id in reversed(recorded):
        if recorded_type == artifact_type:
            return int(artifact_id or 0)
    return 0


def _latex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def _demo_seed_pool_experiment_code(context: dict[str, Any]) -> dict[str, Any]:
    target_venue = str(
        context.get("target_venue") or context.get("venue") or ""
    ).strip()
    study_spec = context.get("study_spec")
    if isinstance(study_spec, str):
        study_spec_text = study_spec
    else:
        study_spec_text = json.dumps(
            study_spec or {},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    code = f'''"""Research Harness demo seed-pool smoke experiment.

This script verifies that the experiment stage can execute locally from the
bounded demo evidence pool. It intentionally reports smoke metrics only; these
numbers are not scientific results and must not be promoted to submission
claims.
"""

from __future__ import annotations

import hashlib


TOPIC = {str(context.get("direction") or context.get("query") or "")!r}
TARGET_VENUE = {target_venue!r}
STUDY_SPEC = {study_spec_text[:4000]!r}


def bounded_score(*parts: str) -> float:
    joined = "\\n".join(part for part in parts if part)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    raw = int(digest[:8], 16)
    return 0.5 + (raw % 4000) / 10000.0


def main() -> None:
    score = bounded_score(TOPIC, TARGET_VENUE, STUDY_SPEC)
    coverage = 1.0 if STUDY_SPEC.strip() else 0.5
    print("condition=demo_smoke execution_success: 1.0")
    print(f"condition=demo_smoke reproducibility_score: {{score:.4f}}")
    print(f"condition=demo_smoke study_spec_coverage: {{coverage:.4f}}")


if __name__ == "__main__":
    main()
'''
    return {
        "files": {"main.py": code},
        "entry_point": "main.py",
        "description": (
            "Deterministic local smoke experiment for a bounded demo seed-pool "
            "paper-production run; not a scientific result."
        ),
        "model_used": "deterministic-demo-smoke",
        "evidence_boundary": "demo_limited_seed_pool",
        "claim_strength_limit": "evidence_limited_demo",
        "submission_readiness": "not_submission_ready",
    }


def _ensure_demo_seed_pool_experiment_code(context: dict[str, Any]) -> bool:
    if not _is_demo_seed_pool_context(context):
        return False
    cg_out = context.get("_output_code_generate")
    if isinstance(cg_out, dict):
        files = cg_out.get("files")
        entry = str(cg_out.get("entry_point") or "main.py")
        if (
            isinstance(files, dict)
            and str(files.get(entry) or files.get("main.py") or "").strip()
        ):
            return False
        if str(cg_out.get("code") or "").strip():
            return False
    context["_output_code_generate"] = _demo_seed_pool_experiment_code(context)
    return True


def dispatch(
    tool_name: str,
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
) -> ToolResult:
    """Dispatch a single tool by name and return its result.

    *context* is the checkpoint's stage_context dict, used to build
    tool-specific parameters.
    """
    try:
        if tool_name in _PRIMITIVE_TOOLS:
            return _dispatch_primitive(
                tool_name, db=db, topic_id=topic_id, context=context
            )
        if tool_name in _ORCHESTRATOR_TOOLS:
            return _dispatch_orchestrator(
                tool_name,
                svc=svc,
                topic_id=topic_id,
                stage=stage,
                context=context,
            )
        if tool_name in _SERVICE_TOOLS:
            return _dispatch_service(
                tool_name,
                svc=svc,
                topic_id=topic_id,
                stage=stage,
                context=context,
            )
        if tool_name in _QUERY_TOOLS:
            return _dispatch_query(tool_name, db=db, topic_id=topic_id, context=context)
        logger.warning("Unknown tool '%s', skipping", tool_name)
        return ToolResult(
            tool=tool_name, success=False, error=f"Unknown tool: {tool_name}"
        )
    except Exception as exc:
        logger.warning("Tool '%s' failed: %s", tool_name, exc)
        return ToolResult(tool=tool_name, success=False, error=str(exc)[:500])


def _maybe_auto_figure_suite_plan(
    *, db: Database, svc: OrchestratorService, topic_id: int
) -> None:
    """Auto-produce a v1 whole-paper figure contract when the write stage begins.

    Mirrors the intro-arc auto-plan: if the topic has experiment goals/results
    but no active ``figure_suite_plan``, plan the figure suite (design, v1) so
    the figure contract + logging requirements exist before drafting references
    figures. Best-effort and silent on failure — never blocks the write run.
    Disable with ``RESEARCH_HARNESS_FIGURE_AUTOPLAN=0``. Only records when a
    non-empty spec was produced (i.e. exemplars + an LLM were available).
    """
    if os.environ.get("RESEARCH_HARNESS_FIGURE_AUTOPLAN", "1").strip() == "0":
        return
    try:
        existing = svc.get_latest_artifact(topic_id, "write", "figure_suite_plan")
        if existing is not None:
            return
        from ..primitives.result_figure_impls import figure_suite_plan
        from ..primitives.types import _to_jsonable

        # Ground on whatever the topic already has (goal_pool / experiment_result);
        # refuse-to-fabricate raises ValueError → skip quietly.
        out = figure_suite_plan(
            db=db,
            topic_id=topic_id,
            target_content="(auto write-stage figure contract)",
            source="matrix",
        )
        figures = out.spec.get("figures") if isinstance(out.spec, dict) else None
        if not figures:
            return
        svc.record_artifact(
            topic_id=topic_id,
            stage="write",
            artifact_type="figure_suite_plan",
            title=f"figure suite plan (auto {out.version_phase}, {out.paper_type})",
            payload=_to_jsonable(out),
            metadata={
                "version_phase": out.version_phase,
                "paper_type": out.paper_type,
                "style_profile": out.style_profile,
                "inventory_mode": out.inventory_mode,
                "auto": True,
            },
        )
        logger.info(
            "auto figure_suite_plan recorded for topic %s (%d figures, coverage=%s)",
            topic_id,
            len(figures),
            out.matrix_coverage.get("verdict"),
        )
    except ValueError:
        return  # no inventory to plan from — nothing to do yet
    except Exception as exc:  # noqa: BLE001 - best-effort, never blocks write
        logger.debug("auto figure_suite_plan skipped: %s", exc, exc_info=True)


def _maybe_auto_exemplar_intro_plan(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    context: dict[str, Any],
    results: list[ToolResult],
) -> None:
    """Default-run EAG for the introduction arc at the write stage.

    Ensures an ``exemplar_plan_intro_arc`` artifact exists before drafting:
    curate exemplars from the topic's paper pool, rank them structure-first,
    and record a form-only plan. ``section_draft`` then auto-consumes the
    plan as the introduction outline (EAG auto-trigger, ef2c47f). Best-effort
    and idempotent: an existing plan, an empty pool, or any error leaves
    drafting untouched. Disable with ``RESEARCH_HARNESS_EAG_AUTOPLAN=0``.
    """
    if os.environ.get("RESEARCH_HARNESS_EAG_AUTOPLAN", "1").strip() == "0":
        return
    try:
        existing = svc.get_latest_artifact(topic_id, "write", "exemplar_plan_intro_arc")
        if existing is not None:
            return

        from research_harness.primitives.exemplar_impls import (
            exemplar_curate,
            exemplar_plan,
            exemplar_retrieve,
        )

        curated = exemplar_curate(db=db, topic_id=topic_id, unit_type="intro_arc")
        units = list(getattr(curated, "units", None) or [])
        if not units:
            logger.info(
                "EAG auto-plan: no usable exemplars for topic %s; drafting "
                "proceeds without an exemplar intro arc",
                topic_id,
            )
            return

        target_content = (
            "\n".join(
                str(context.get(key) or "").strip()
                for key in ("title", "contributions", "outline")
                if str(context.get(key) or "").strip()
            )
            or "introduction for this research topic"
        )
        retrieved = exemplar_retrieve(
            db=db,
            topic_id=topic_id,
            unit_type="intro_arc",
            target_content=target_content,
            units=units,
        )
        ranked = list(getattr(retrieved, "ranked", None) or []) or units
        plan_out = exemplar_plan(
            db=db,
            topic_id=topic_id,
            unit_type="intro_arc",
            target_content=target_content,
            retrieved_units=ranked,
        )
        plan = getattr(plan_out, "plan", None)
        if not isinstance(plan, dict) or not plan:
            return

        artifact = svc.record_artifact(
            topic_id=topic_id,
            stage="write",
            artifact_type="exemplar_plan_intro_arc",
            title="exemplar plan: intro_arc (auto)",
            payload={
                "unit_type": "intro_arc",
                "plan": plan,
                "exemplar_ids": list(getattr(plan_out, "exemplar_ids", None) or []),
                "form_only": True,
                "origin": "eag_auto_plan",
            },
        )
        results.append(
            ToolResult(
                tool="exemplar_auto_plan",
                success=True,
                output={
                    "artifact_id": artifact.id,
                    "exemplar_count": len(units),
                    "unit_type": "intro_arc",
                },
            )
        )
    except Exception as exc:  # noqa: BLE001 - EAG must never block drafting
        logger.warning("EAG auto-plan failed for topic %s: %s", topic_id, exc)


def _auto_exemplar_unit_plan(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    context: dict[str, Any],
    results: list[ToolResult],
    unit_type: str,
) -> None:
    """Shared curate→retrieve→plan→record flow for one EAG unit type.

    Mirrors ``_maybe_auto_exemplar_intro_plan`` exactly (idempotent on an
    existing ``exemplar_plan_<unit>`` artifact; empty pool or empty plan is a
    silent no-op) so every unit's auto-plan behaves identically.
    """
    artifact_type = f"exemplar_plan_{unit_type}"
    existing = svc.get_latest_artifact(topic_id, "write", artifact_type)
    if existing is not None:
        return

    from research_harness.primitives.exemplar_impls import (
        exemplar_curate,
        exemplar_plan,
        exemplar_retrieve,
    )

    curated = exemplar_curate(db=db, topic_id=topic_id, unit_type=unit_type)
    units = list(getattr(curated, "units", None) or [])
    if not units:
        logger.info(
            "EAG auto-plan: no usable %s exemplars for topic %s; drafting "
            "proceeds without this contract",
            unit_type,
            topic_id,
        )
        return

    target_content = (
        "\n".join(
            str(context.get(key) or "").strip()
            for key in ("title", "contributions", "outline")
            if str(context.get(key) or "").strip()
        )
        or f"{unit_type} for this research topic"
    )
    retrieved = exemplar_retrieve(
        db=db,
        topic_id=topic_id,
        unit_type=unit_type,
        target_content=target_content,
        units=units,
    )
    ranked = list(getattr(retrieved, "ranked", None) or []) or units
    plan_out = exemplar_plan(
        db=db,
        topic_id=topic_id,
        unit_type=unit_type,
        target_content=target_content,
        retrieved_units=ranked,
    )
    plan = getattr(plan_out, "plan", None)
    if not isinstance(plan, dict) or not plan:
        return

    artifact = svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type=artifact_type,
        title=f"exemplar plan: {unit_type} (auto)",
        payload={
            "unit_type": unit_type,
            "plan": plan,
            "exemplar_ids": list(getattr(plan_out, "exemplar_ids", None) or []),
            "form_only": True,
            "origin": "eag_auto_plan",
        },
    )
    results.append(
        ToolResult(
            tool="exemplar_auto_plan",
            success=True,
            output={
                "artifact_id": artifact.id,
                "exemplar_count": len(units),
                "unit_type": unit_type,
            },
        )
    )


def _maybe_auto_exemplar_style_plan(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    context: dict[str, Any],
    results: list[ToolResult],
) -> None:
    """Produce the ``exemplar_plan_style`` card that feeds writing_patterns.

    Default ON since the venue-family + surface-prose exemplar overhaul: a
    section drafted with no style card imitates nothing, which is how prose
    drifted to generic-conference register. Disable with
    ``RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN=0``.
    """
    if os.environ.get("RESEARCH_HARNESS_EXEMPLAR_STYLE_AUTOPLAN", "1").strip() == "0":
        return
    try:
        _auto_exemplar_unit_plan(
            db=db,
            svc=svc,
            topic_id=topic_id,
            context=context,
            results=results,
            unit_type="style",
        )
    except Exception as exc:  # noqa: BLE001 - EAG must never block drafting
        logger.warning("EAG style auto-plan failed for topic %s: %s", topic_id, exc)


# L1 section arcs (EAG-Ladder batch 1). experiments/results and
# limitations/conclusion share contracts; see _ARC_PLAN_FOR_SECTION on the
# consumer side (llm_primitives.section_draft).
_SECTION_ARC_UNITS: tuple[str, ...] = (
    "related_work_arc",
    "method_arc",
    "experiment_arc",
    "discussion_arc",
)


def _maybe_auto_exemplar_section_arc_plans(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    context: dict[str, Any],
    results: list[ToolResult],
) -> None:
    """Produce the four L1 section-arc plans before drafting (default ON).

    The whole-paper top-level rhetorical system is imitated, not just the
    introduction (user mandate). ``RESEARCH_HARNESS_EAG_SECTION_ARCS=0``
    disables — the same switch gates ``section_draft`` consumption, so
    producer and consumer flip together. Per-unit isolation: one failing arc
    never blocks the others or drafting itself.
    """
    if os.environ.get("RESEARCH_HARNESS_EAG_SECTION_ARCS", "1").strip() == "0":
        return
    for unit_type in _SECTION_ARC_UNITS:
        try:
            _auto_exemplar_unit_plan(
                db=db,
                svc=svc,
                topic_id=topic_id,
                context=context,
                results=results,
                unit_type=unit_type,
            )
        except Exception as exc:  # noqa: BLE001 - EAG must never block drafting
            logger.warning(
                "EAG %s auto-plan failed for topic %s: %s",
                unit_type,
                topic_id,
                exc,
            )


def _maybe_auto_exemplar_paragraph_moves_plan(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    context: dict[str, Any],
    results: list[ToolResult],
) -> None:
    """Produce the L2 paragraph-craft contract before drafting (opt-in).

    Gated by ``RESEARCH_HARNESS_EAG_PARAGRAPH_MOVES=1`` — the same switch
    that lets ``section_draft`` inject the craft block, so producer and
    consumer turn on together.
    """
    if os.environ.get("RESEARCH_HARNESS_EAG_PARAGRAPH_MOVES", "0").strip() != "1":
        return
    try:
        _auto_exemplar_unit_plan(
            db=db,
            svc=svc,
            topic_id=topic_id,
            context=context,
            results=results,
            unit_type="paragraph_moves",
        )
    except Exception as exc:  # noqa: BLE001 - EAG must never block drafting
        logger.warning(
            "EAG paragraph_moves auto-plan failed for topic %s: %s", topic_id, exc
        )


def _maybe_auto_logic_tree(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    context: dict[str, Any],
    results: list[ToolResult],
) -> None:
    """Build + record the claim-logic tree before drafting (opt-in).

    Gated by ``RESEARCH_HARNESS_EAG_LOGIC_TREE=1`` (same switch as the
    section_draft obligations block). Idempotent on an existing active
    ``logic_tree`` artifact; empty trees are a silent no-op.
    """
    if os.environ.get("RESEARCH_HARNESS_EAG_LOGIC_TREE", "0").strip() != "1":
        return
    try:
        existing = svc.get_latest_artifact(topic_id, "write", "logic_tree")
        if existing is not None:
            return

        from research_harness.primitives.logic_impls import logic_tree_build
        from research_harness.primitives.types import _to_jsonable

        target_content = "\n".join(
            str(context.get(key) or "").strip()
            for key in ("title", "contributions", "outline")
            if str(context.get(key) or "").strip()
        )
        out = logic_tree_build(db=db, topic_id=topic_id, target_content=target_content)
        if not out.nodes:
            logger.info(
                "logic tree auto-build: no tree for topic %s; drafting "
                "proceeds without obligations",
                topic_id,
            )
            return
        artifact = svc.record_artifact(
            topic_id=topic_id,
            stage="write",
            artifact_type="logic_tree",
            title="claim-logic tree (auto)",
            payload=_to_jsonable(out),
        )
        results.append(
            ToolResult(
                tool="logic_tree_build",
                success=True,
                output={
                    "artifact_id": artifact.id,
                    "n_nodes": out.n_nodes,
                    "sections_covered": list(out.sections_covered),
                },
            )
        )
    except Exception as exc:  # noqa: BLE001 - never block drafting
        logger.warning("logic tree auto-build failed for topic %s: %s", topic_id, exc)


def dispatch_stage_tools(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    tools: tuple[str, ...],
    context: dict[str, Any],
    budget_monitor: "BudgetMonitor | None" = None,
    capability_manifest: CapabilityManifest | dict[str, Any] | None = None,
    run_spec: RunSpec | dict[str, Any] | None = None,
    execute_skill: bool = False,
) -> dict[str, Any]:
    """Execute all tools for a stage in order.

    Returns a summary dict with results, errors, and overall status.
    If budget_monitor is provided, syncs cost from provenance after each tool
    and halts early if budget is exhausted.
    """

    results: list[ToolResult] = []
    errors: list[str] = []
    capability_input = (
        capability_manifest
        or context.get("_capability_manifest")
        or context.get("capability_manifest")
    )
    spec_input = run_spec or context.get("_run_spec") or context.get("run_spec")
    gate_tools = tools
    if execute_skill and capability_input is not None:
        gate_tools = _coerce_capability_manifest(capability_input).allowed_tools

    runtime_gate = _run_runtime_gate(
        capability_manifest=capability_input,
        run_spec=spec_input,
        tools=gate_tools,
    )
    if runtime_gate is not None:
        gate_results = runtime_gate["guardrail_results"]
        failed = [item for item in gate_results if not item.get("passed")]
        if failed:
            failed_names = ", ".join(str(item.get("name")) for item in failed)
            error = f"runtime capability gate blocked: {failed_names}"
            result = ToolResult(
                tool="runtime_contract",
                success=False,
                error=error,
                output={"guardrail_results": gate_results},
            )
            errors.append(error)
            auto_artifacts: list[tuple[str, int]] = []
            try:
                trace_ref = _record_stage_run_trace(
                    svc=svc,
                    topic_id=topic_id,
                    stage=stage,
                    tools=tools,
                    results=[result],
                    errors=errors,
                    runtime_gate={
                        "passed": False,
                        "guardrail_results": gate_results,
                    },
                    auto_artifacts=[],
                )
                if trace_ref is not None:
                    auto_artifacts.append(trace_ref)
            except Exception as exc:
                logger.warning(
                    "Blocked stage run_trace recording failed: %s",
                    exc,
                    exc_info=True,
                )
                errors.append(f"run_trace: {exc}")
            return {
                "summary": f"Stage {stage}: runtime capability gate blocked",
                "tool_results": [
                    {
                        "tool": result.tool,
                        "success": result.success,
                        "error": result.error,
                        "output": result.output,
                    }
                ],
                "errors": errors,
                "auto_artifacts": auto_artifacts,
                "runtime_gate": {
                    "passed": False,
                    "guardrail_results": gate_results,
                },
            }

    # Sync budget at stage START only (not per-tool) to avoid N*2 SQL queries
    if budget_monitor is not None:
        budget_monitor.sync_from_provenance(db, topic_id=topic_id)

    if execute_skill:
        if capability_input is None or spec_input is None:
            error = "execute_skill requires capability_manifest and run_spec"
            return {
                "summary": f"Stage {stage}: skill execution blocked",
                "tool_results": [
                    {
                        "tool": "runtime_contract",
                        "success": False,
                        "error": error,
                        "output": {},
                    }
                ],
                "errors": [error],
                "auto_artifacts": [],
                "runtime_gate": {
                    "passed": False,
                    "guardrail_results": (
                        runtime_gate["guardrail_results"] if runtime_gate else []
                    ),
                },
            }

        from ..evaluator.runtime import run_evaluator

        capability = _coerce_capability_manifest(capability_input)
        evaluator_result = run_evaluator(
            capability.name,
            db=db,
            svc=svc,
            topic_id=topic_id,
            stage=stage,
            capability_manifest=capability,
            run_spec=spec_input,
            guardrail_results=(
                tuple(runtime_gate["guardrail_results"]) if runtime_gate else ()
            ),
        )
        result = ToolResult(
            tool=evaluator_result.skill_name,
            success=evaluator_result.success,
            output=evaluator_result.output,
            error=evaluator_result.error,
        )
        results.append(result)
        if not result.success:
            errors.append(f"{result.tool}: {result.error}")
        auto_artifacts = []
        artifact_type = result.output.get("artifact_type") if result.output else ""
        artifact_id = result.output.get("artifact_id") if result.output else 0
        if result.success and artifact_type and artifact_id:
            auto_artifacts.append((str(artifact_type), int(artifact_id)))
        trace_artifact_id = (
            result.output.get("run_trace_artifact_id") if result.output else 0
        )
        if result.success and trace_artifact_id:
            auto_artifacts.append(("run_trace", int(trace_artifact_id)))
        trace_grade_artifact_id = (
            result.output.get("runtime_trace_grade_artifact_id") if result.output else 0
        )
        if result.success and trace_grade_artifact_id:
            auto_artifacts.append(("runtime_trace_grade", int(trace_grade_artifact_id)))
        if budget_monitor is not None:
            budget_monitor.sync_from_provenance(db, topic_id=topic_id)
        summary: dict[str, Any] = {
            "summary": (
                f"Stage {stage}: skill {result.tool} "
                f"{'succeeded' if result.success else 'failed'}"
            ),
            "tool_results": [
                {
                    "tool": result.tool,
                    "success": result.success,
                    "error": result.error,
                    "output": result.output,
                }
            ],
            "errors": errors,
            "auto_artifacts": auto_artifacts,
            "runtime_gate": {
                "passed": True,
                "guardrail_results": (
                    runtime_gate["guardrail_results"] if runtime_gate else []
                ),
            },
        }
        if budget_monitor is not None:
            summary["budget"] = budget_monitor.to_dict()
        return summary

    # Whole-paper figure contract: plan the figure suite (v1) at write-stage
    # entry so the contract + logging requirements exist before drafting.
    if stage == "write" and not _is_demo_seed_pool_context(context):
        _maybe_auto_figure_suite_plan(db=db, svc=svc, topic_id=topic_id)

    # v2 Step 5 — ADR-001 Decision 1: when the write stage requests the
    # EAG default execution: make sure an exemplar-derived introduction arc
    # exists before any drafting, so section_draft's auto-consume trigger has
    # a plan to follow. Best-effort; drafting proceeds without it.
    if stage == "write" and not _is_demo_seed_pool_context(context):
        _maybe_auto_exemplar_intro_plan(
            db=db, svc=svc, topic_id=topic_id, context=context, results=results
        )
        # EAG-Ladder batch 1 (both opt-in until E1 A/B evidence): style card
        # for writing_patterns + the four L1 section-arc contracts.
        _maybe_auto_exemplar_style_plan(
            db=db, svc=svc, topic_id=topic_id, context=context, results=results
        )
        _maybe_auto_exemplar_section_arc_plans(
            db=db, svc=svc, topic_id=topic_id, context=context, results=results
        )
        # EAG-Ladder batch 2 (opt-in until E2): L2 paragraph craft + logic tree.
        _maybe_auto_exemplar_paragraph_moves_plan(
            db=db, svc=svc, topic_id=topic_id, context=context, results=results
        )
        _maybe_auto_logic_tree(
            db=db, svc=svc, topic_id=topic_id, context=context, results=results
        )

    # draft/review/revise triad, replace it with run_section_loop() (canonical
    # section loop). Default ON since the 2026-07 writing-quality upgrade; set
    # RESEARCH_HARNESS_SECTION_LOOP=0 to fall back to single-pass drafting.
    # We populate context with the per-section outputs so the legacy tool
    # names become no-ops.
    section_loop_enabled = (
        os.environ.get("RESEARCH_HARNESS_SECTION_LOOP", "1").strip() != "0"
    )
    section_loop_handled = False
    if (
        section_loop_enabled
        and stage == "write"
        and not _is_demo_seed_pool_context(context)
        and context.get("sections_to_draft")
        and "section_draft" in tools
    ):
        _ensure_demo_seed_pool_write_plan(context)
        try:
            _run_section_loops(
                db=db,
                topic_id=topic_id,
                context=context,
                results=results,
                errors=errors,
            )
            section_loop_handled = True
        except Exception as exc:
            logger.warning("run_section_loop integration failed: %s", exc)
            errors.append(f"run_section_loop: {exc}")

    for tool_name in tools:
        if stage == "write" and tool_name == "section_draft":
            _ensure_demo_seed_pool_write_plan(context)
        if (
            stage == "write"
            and _is_demo_seed_pool_context(context)
            and (
                context.get("paper_production_closure_mode")
                == "deterministic_pdf_smoke"
                or context.get("sections_to_draft")
            )
            and tool_name not in ("orchestrator_gate_check", "orchestrator_status")
        ):
            _ensure_demo_seed_pool_write_sections(context)
            results.append(
                ToolResult(
                    tool=tool_name,
                    success=True,
                    output={
                        "status": "skipped",
                        "reason": (
                            f"{tool_name} skipped: paper-production "
                            "demo_limited_seed_pool uses deterministic local "
                            "PDF closure"
                        ),
                        "evidence_boundary": "demo_limited_seed_pool",
                        "closure_mode": "deterministic_pdf_smoke",
                    },
                )
            )
            continue
        if (
            stage == "experiment"
            and tool_name == "code_generate"
            and _ensure_demo_seed_pool_experiment_code(context)
        ):
            results.append(
                ToolResult(
                    tool=tool_name,
                    success=True,
                    output={
                        "status": "skipped",
                        "reason": (
                            "code_generate skipped: paper-production "
                            "demo_limited_seed_pool uses deterministic local "
                            "smoke experiment code"
                        ),
                        "evidence_boundary": "demo_limited_seed_pool",
                    },
                )
            )
            continue
        if (
            stage == "experiment"
            and tool_name in {"code_validate", "experiment_run"}
            and not context.get("_output_code_generate")
        ):
            _ensure_demo_seed_pool_experiment_code(context)
        # When the canonical loop already drafted/reviewed/revised, skip the
        # individual tool names — their outputs are already in context.
        if section_loop_handled and tool_name in (
            "section_draft",
            "section_review",
            "section_revise",
        ):
            continue
        # Skip gate/status checks that happen elsewhere
        if tool_name in ("orchestrator_gate_check", "orchestrator_status"):
            continue

        demo_skip_reason = _demo_seed_pool_expansion_skip_reason(
            tool_name,
            stage=stage,
            context=context,
            db=db,
            topic_id=topic_id,
        )
        if demo_skip_reason:
            results.append(
                ToolResult(
                    tool=tool_name,
                    success=True,
                    output={
                        "status": "skipped",
                        "reason": demo_skip_reason,
                        "evidence_boundary": "demo_limited_seed_pool",
                    },
                )
            )
            continue

        skip_reason = _context_bound_tool_skip_reason(tool_name, context)
        if skip_reason:
            results.append(
                ToolResult(
                    tool=tool_name,
                    success=False,
                    output={"status": "skipped", "reason": skip_reason},
                    error=skip_reason,
                )
            )
            continue

        # Multi-section expansion: call section_draft once per section
        if tool_name == "section_draft" and context.get("sections_to_draft"):
            for sec in context["sections_to_draft"]:
                context["section"] = sec
                result = dispatch(
                    tool_name,
                    db=db,
                    svc=svc,
                    topic_id=topic_id,
                    stage=stage,
                    context=context,
                )
                results.append(result)
                if result.success and result.output:
                    context.setdefault("_drafted_sections", []).append(sec)
                    # Normalize output: real SectionDraftOutput → {"draft": {"content": ...}}
                    text = _extract_section_text(result.output)
                    context[f"_output_{tool_name}_{sec}"] = {"text": text}
                if not result.success:
                    errors.append(f"{tool_name}[{sec}]: {result.error}")
                    logger.warning(
                        "Tool %s[%s] failed in stage %s: %s",
                        tool_name,
                        sec,
                        stage,
                        result.error,
                    )
            continue

        # Multi-section expansion: review each drafted section
        if tool_name == "section_review" and context.get("_drafted_sections"):
            for sec in context["_drafted_sections"]:
                context["section"] = sec
                result = dispatch(
                    tool_name,
                    db=db,
                    svc=svc,
                    topic_id=topic_id,
                    stage=stage,
                    context=context,
                )
                results.append(result)
                if result.success and result.output:
                    # Normalize: SectionReviewOutput → {"feedback": ..., "issues": ...}
                    feedback = _extract_review_feedback(result.output)
                    context[f"_output_section_review_{sec}"] = {"feedback": feedback}
                if not result.success:
                    errors.append(f"{tool_name}[{sec}]: {result.error}")
            continue

        # Multi-section expansion: revise each section using its review
        if tool_name == "section_revise" and context.get("_drafted_sections"):
            for sec in context["_drafted_sections"]:
                context["section"] = sec
                review_out = context.get(f"_output_section_review_{sec}", {})
                context["_output_section_review"] = review_out
                result = dispatch(
                    tool_name,
                    db=db,
                    svc=svc,
                    topic_id=topic_id,
                    stage=stage,
                    context=context,
                )
                results.append(result)
                if result.success and result.output:
                    # Normalize: SectionReviseOutput → {"text": revised_content}
                    text = _extract_revise_text(result.output)
                    normalized = {"text": text}
                    context[f"_output_section_revise_{sec}"] = normalized
                    context[f"_output_section_draft_{sec}"] = normalized
                if not result.success:
                    errors.append(f"{tool_name}[{sec}]: {result.error}")
            continue
        # direction_proposal and study_spec artifacts via one tool entry
        if (
            tool_name == "orchestrator_record_artifact"
            and stage == "propose"
            and context.get("study_spec")
        ):
            # First: record the primary artifact (direction_proposal)
            result = dispatch(
                tool_name,
                db=db,
                svc=svc,
                topic_id=topic_id,
                stage=stage,
                context=context,
            )
            results.append(result)
            if not result.success:
                errors.append(f"{tool_name}[primary]: {result.error}")

            # Second: record study_spec artifact
            saved = (
                context.get("artifact_type"),
                context.get("artifact_title"),
                context.get("artifact_payload"),
            )
            try:
                context["artifact_type"] = "study_spec"
                context["artifact_title"] = "Study design specification"
                context["artifact_payload"] = {"methodology": context["study_spec"]}
                result2 = dispatch(
                    tool_name,
                    db=db,
                    svc=svc,
                    topic_id=topic_id,
                    stage=stage,
                    context=context,
                )
                results.append(result2)
                if not result2.success:
                    errors.append(f"{tool_name}[study_spec]: {result2.error}")
            finally:
                (
                    context["artifact_type"],
                    context["artifact_title"],
                    context["artifact_payload"],
                ) = saved
            continue

        result = dispatch(
            tool_name,
            db=db,
            svc=svc,
            topic_id=topic_id,
            stage=stage,
            context=context,
        )
        results.append(result)

        # Feed tool output back into context for downstream tools
        if result.success and result.output:
            context[f"_output_{tool_name}"] = result.output

        # Whole-manuscript consistency issues feed a targeted repair round
        # instead of dying in an artifact nobody reads.
        if (
            result.success
            and stage == "write"
            and tool_name == "consistency_check"
            and result.output.get("issues")
        ):
            try:
                _apply_consistency_repairs(
                    db=db,
                    topic_id=topic_id,
                    context=context,
                    results=results,
                    errors=errors,
                )
            except Exception as exc:
                logger.warning("consistency repair pass failed: %s", exc)
                errors.append(f"consistency_repair: {exc}")

        if not result.success:
            errors.append(f"{tool_name}: {result.error}")
            logger.warning(
                "Tool %s failed in stage %s: %s", tool_name, stage, result.error
            )
            if stage == "experiment" and tool_name == "code_generate":
                if _ensure_demo_seed_pool_experiment_code(context):
                    results.append(
                        ToolResult(
                            tool=tool_name,
                            success=True,
                            output=context["_output_code_generate"],
                        )
                    )
                    continue
            if tool_name in _PRIMITIVE_TOOLS and PRIMITIVE_REGISTRY.get(tool_name):
                continue
            if tool_name.startswith("orchestrator_record"):
                continue

    # Post-tool artifact recording: ensure all gate-required artifacts exist.
    auto_artifacts = _record_auto_artifacts(
        db=db,
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        context=context,
        results=results,
        errors=errors,
    )

    try:
        trace_ref = _record_stage_run_trace(
            svc=svc,
            topic_id=topic_id,
            stage=stage,
            tools=tools,
            results=results,
            errors=errors,
            runtime_gate=runtime_gate,
            auto_artifacts=auto_artifacts,
        )
        if trace_ref is not None:
            auto_artifacts.append(trace_ref)
    except Exception as exc:
        logger.warning("Stage run_trace recording failed: %s", exc, exc_info=True)
        errors.append(f"run_trace: {exc}")

    # Sync budget at stage END and check limits
    if budget_monitor is not None:
        budget_monitor.sync_from_provenance(db, topic_id=topic_id)
        budget_check = budget_monitor.check()
        if budget_check.action == "halt":
            errors.append(f"Budget halted: {budget_check.message}")
            logger.warning(
                "Budget halted during stage %s: %s", stage, budget_check.message
            )

    succeeded = [r for r in results if r.success]
    summary: dict[str, Any] = {
        "summary": f"Stage {stage}: {len(succeeded)}/{len(results)} tools succeeded",
        "tool_results": [
            {"tool": r.tool, "success": r.success, "error": r.error, "output": r.output}
            for r in results
        ],
        "errors": errors,
        "auto_artifacts": auto_artifacts,
    }
    if runtime_gate is not None:
        summary["runtime_gate"] = {
            "passed": True,
            "guardrail_results": runtime_gate["guardrail_results"],
        }
    if budget_monitor is not None:
        summary["budget"] = budget_monitor.to_dict()
    return summary


# ---------------------------------------------------------------------------
# Automated adversarial review
# ---------------------------------------------------------------------------


def _run_automated_adversarial(proposal: dict[str, Any]) -> dict[str, Any]:
    """Run LLM-based adversarial evaluation of a research proposal.

    Returns a dict with verdict ("approved"/"revise"), issues list, and summary.
    Fails closed on LLM or provider failure so proposal gates cannot pass merely
    because review was unavailable.
    """
    try:
        from ..execution.llm_primitives import _client_chat, _get_client, _parse_json

        direction = proposal.get("direction", proposal.get("research_question", ""))
        motivation = proposal.get("motivation", "")

        prompt = f"""You are a critical adversarial reviewer evaluating a research direction proposal.

Direction: {direction}
Motivation: {motivation}
Full proposal: {json.dumps(proposal, ensure_ascii=False, default=str)[:2000]}

Evaluate on: novelty, feasibility, evidence coverage, scope discipline.
Return JSON:
{{
  "verdict": "approved" or "revise",
  "issues": [{{
    "category": "novelty|feasibility|evidence|scope",
    "severity": "critical|major|minor",
    "description": "..."
  }}],
  "summary": "one-line overall assessment"
}}

Only return "revise" if there are critical issues. Return ONLY JSON."""

        client = _get_client(tier="medium", task_name="stage_planner")
        raw = _client_chat(client, prompt)
        result = _parse_json(raw, primitive="adversarial_review")
        if result.get("verdict") in ("approved", "revise"):
            return result
        return {
            "verdict": "revise",
            "issues": [
                {
                    "category": "review_unavailable",
                    "severity": "critical",
                    "description": "Automated adversarial review returned an invalid verdict.",
                }
            ],
            "summary": "Automated adversarial review returned an invalid verdict.",
        }
    except Exception as exc:
        logger.warning("Automated adversarial review failed: %s", exc)
        return {
            "verdict": "revise",
            "issues": [
                {
                    "category": "review_unavailable",
                    "severity": "critical",
                    "description": f"Automated adversarial review failed: {str(exc)[:200]}",
                }
            ],
            "summary": f"Automated adversarial review failed: {str(exc)[:100]}",
        }


# ---------------------------------------------------------------------------
# Auto-artifact recording
# ---------------------------------------------------------------------------


def _record_auto_artifacts(
    *,
    db: Database | None = None,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
    results: list[ToolResult],
    errors: list[str],
) -> list[tuple[str, int]]:
    """Record gate-required artifacts from tool outputs.

    After all tools in a stage execute, this ensures the artifacts
    required by the orchestrator gate are written to the DB. Without this,
    advance() blocks with "Missing required artifact" errors.

    Returns list of (artifact_type, artifact_id) tuples for checkpoint tracking.
    """
    recorded: list[tuple[str, int]] = []
    succeeded_tools = {r.tool for r in results if r.success}

    if stage == "init":
        already_recorded = {
            r.output.get("artifact_type") if isinstance(r.output, dict) else None
            for r in results
            if r.success and r.tool == "orchestrator_record_artifact"
        }
        if "topic_brief" not in already_recorded:
            topic_desc = context.get("topic_description", context.get("query", ""))
            topic_contract = (
                context.get("topic_venue_contract")
                if isinstance(context.get("topic_venue_contract"), dict)
                else {}
            )
            non_goals = _as_string_list(topic_contract.get("non_goals"))
            if not non_goals:
                non_goals = [
                    "Do not claim a finished paper before evidence, experiment, PDF, and publication-pack gates pass.",
                    "Do not run credentialed external actions from the local auto-runner.",
                ]
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="topic_brief",
                    title="Topic brief",
                    payload={
                        "description": topic_desc,
                        "scope": topic_desc or context.get("direction", ""),
                        "scope_boundaries": non_goals,
                        "exclusion_criteria": non_goals,
                        "target_venue": context.get("target_venue", ""),
                        "search_queries": context.get("additional_queries", []),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("topic_brief", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[topic_brief]: {exc}")

    elif stage == "build":
        ps_out = context.get("_output_paper_search", {})
        expand_out = context.get("_output_expand_citations", {})
        acquire_out = context.get("_output_paper_acquire", {})
        policy = _paper_production_policy_from_context(context)
        seed_boundary = str(
            policy.get("evidence_boundary") or "strict_evidence_pool"
        ).strip()

        if ps_out and "paper_search" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="literature_map",
                    title="Literature map from search",
                    payload={
                        "papers_found": ps_out.get(
                            "ingested_count", len(ps_out.get("papers", []))
                        ),
                        "query": ps_out.get("query_used", ""),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("literature_map", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[literature_map]: {exc}")

            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="paper_pool_snapshot",
                    title="Paper pool snapshot",
                    payload={
                        "total_papers": ps_out.get("ingested_count", 0),
                        "provider": ps_out.get("provider", ""),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("paper_pool_snapshot", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[paper_pool_snapshot]: {exc}")

        if expand_out or "expand_citations" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="citation_expansion_report",
                    title="Citation expansion report",
                    payload=expand_out if expand_out else {"status": "completed"},
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("citation_expansion_report", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[citation_expansion_report]: {exc}")

        if acquire_out or "paper_acquire" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="acquisition_report",
                    title="Paper acquisition report",
                    payload=acquire_out if acquire_out else {"status": "completed"},
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("acquisition_report", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[acquisition_report]: {exc}")
        if policy and seed_boundary == "demo_limited_seed_pool":
            _record_demo_seed_pool_build_artifacts(
                svc=svc,
                db=db,
                topic_id=topic_id,
                stage=stage,
                context=context,
                seed_boundary=seed_boundary,
                recorded=recorded,
                errors=errors,
            )

    elif stage == "analyze":
        claims_out = context.get("_output_claim_extract", {})
        gaps_out = context.get("_output_gap_detect", {})
        baselines_out = context.get("_output_baseline_identify", {})

        if claims_out and "claim_extract" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="claim_candidate_set",
                    title="Extracted claims",
                    payload={
                        "claims_count": len(claims_out.get("claims", [])),
                        "papers_processed": claims_out.get("papers_processed", 0),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("claim_candidate_set", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[claim_candidate_set]: {exc}")

        if (gaps_out or baselines_out) and (
            "gap_detect" in succeeded_tools or "baseline_identify" in succeeded_tools
        ):
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="evidence_pack",
                    title="Evidence pack (gaps + baselines)",
                    payload={
                        "gaps_count": len(gaps_out.get("gaps", [])),
                        "papers_analyzed": gaps_out.get("papers_analyzed", 0),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("evidence_pack", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[evidence_pack]: {exc}")

        baseline_matrix_artifact_id = 0
        if baselines_out and "baseline_identify" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="baseline_matrix",
                    title="Baseline matrix",
                    payload=_normalize_baseline_matrix_payload(
                        baselines_out,
                        context,
                    ),
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    baseline_matrix_artifact_id = int(art_id)
                    recorded.append(("baseline_matrix", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[baseline_matrix]: {exc}")

        if gaps_out and "gap_detect" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="direction_proposal",
                    title="Research direction from gap analysis",
                    payload={
                        "gaps": gaps_out.get("gaps", [])[:5],
                        "research_question": context.get(
                            "focus", "What are the key gaps?"
                        ),
                    },
                    dependency_artifact_ids=(
                        [baseline_matrix_artifact_id]
                        if baseline_matrix_artifact_id
                        else None
                    ),
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("direction_proposal", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[direction_proposal]: {exc}")

        recorded_types = {artifact_type for artifact_type, _ in recorded}
        if (
            not {"claim_candidate_set", "evidence_pack", "direction_proposal"}
            <= recorded_types
        ):
            _record_demo_seed_pool_analyze_artifacts(
                svc=svc,
                db=db,
                topic_id=topic_id,
                stage=stage,
                context=context,
                recorded=recorded,
                errors=errors,
            )

    elif stage == "propose":
        if "adversarial_run" not in succeeded_tools:
            proposal = context.get("artifact_payload", {})
            outcome = _run_automated_adversarial(proposal)
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="adversarial_resolution",
                    title=f"Automated adversarial review ({outcome['verdict']})",
                    payload={
                        "outcome": outcome["verdict"],
                        "issues": outcome.get("issues", []),
                        "summary": outcome.get("summary", ""),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("adversarial_resolution", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[adversarial_resolution]: {exc}")

    elif stage == "experiment":
        cg_out = context.get("_output_code_generate", {})
        er_out = context.get("_output_experiment_run", {})
        vr_out = context.get("_output_verified_registry_build", {})

        if cg_out and (
            "code_generate" in succeeded_tools or _is_demo_seed_pool_context(context)
        ):
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="experiment_code",
                    title="Generated experiment code",
                    payload={
                        "files": list(cg_out.get("files", {}).keys()),
                        "entry_point": cg_out.get("entry_point", "main.py"),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("experiment_code", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[experiment_code]: {exc}")

        if er_out and "experiment_run" in succeeded_tools:
            try:
                contract_opted_in = any(
                    key in context for key in ABLATION_CONTRACT_FIELDS
                ) or bool(er_out.get("canonical_components"))
                ablation_contract = (
                    {
                        key: er_out[key] if key in er_out else context[key]
                        for key in ABLATION_CONTRACT_FIELDS
                        if key in er_out or key in context
                    }
                    if contract_opted_in
                    else {}
                )
                memory_opted_in = bool(
                    er_out.get("component_provenance")
                    or er_out.get(ABLATION_MEMORY_RESULT_FIELD)
                    or any(key in context for key in ABLATION_MEMORY_INPUT_FIELDS)
                )
                ablation_memory = (
                    {
                        key: er_out[key]
                        for key in (
                            *ABLATION_MEMORY_INPUT_FIELDS,
                            ABLATION_MEMORY_RESULT_FIELD,
                        )
                        if key in er_out
                    }
                    if memory_opted_in
                    else {}
                )
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="experiment_result",
                    title="Experiment results",
                    payload={
                        "metrics": er_out.get("metrics", {}),
                        **ablation_contract,
                        **ablation_memory,
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("experiment_result", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[experiment_result]: {exc}")

            # P0-2: Insert experiment_runs row with kept=1 to satisfy experiment_gate
            try:
                svc.record_experiment_run(
                    topic_id,
                    # The real sha256 comes from the sandbox run (er_out);
                    # falling back to the entry-point *filename* here wrote
                    # "main.py" into the hash column and destroyed run identity.
                    code_hash=er_out.get("code_hash", "")
                    or cg_out.get("entry_point", "main.py"),
                    primary_metric_name=er_out.get(
                        "primary_metric_name", context.get("primary_metric", "")
                    ),
                    primary_metric_value=er_out.get("primary_metric_value", 0.0),
                    metrics=er_out.get("metrics", {}),
                )
            except Exception as exc:
                errors.append(f"auto_artifact[experiment_runs]: {exc}")

        if vr_out and "verified_registry_build" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="verified_registry",
                    title="Verified number registry",
                    payload={"whitelist_size": vr_out.get("whitelist_size", 0)},
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("verified_registry", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[verified_registry]: {exc}")

    elif stage == "write":
        writing_arch_out = context.get("_output_writing_architecture", {})
        figure_plan_out = context.get("_output_figure_plan", {})
        drafted = context.get("_drafted_sections", [])
        sections_map: dict[str, str] = {}
        paper_plan = context.get("paper_plan")

        if (
            isinstance(paper_plan, dict)
            and paper_plan.get("automation_scope") == "paper_production_demo_pdf_smoke"
        ):
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="PAPER_PLAN",
                    title="Demo paper plan for bounded PDF smoke run",
                    payload=paper_plan,
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("PAPER_PLAN", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[PAPER_PLAN]: {exc}")

        if writing_arch_out and "writing_architecture" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="writing_architecture",
                    title="Writing architecture",
                    payload=writing_arch_out,
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("writing_architecture", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[writing_architecture]: {exc}")

        if figure_plan_out and "figure_plan" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="figure_plan",
                    title="Paper figure and table plan",
                    payload=figure_plan_out,
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("figure_plan", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[figure_plan]: {exc}")

        suite_plan_out = context.get("_output_figure_suite_plan", {})
        if suite_plan_out and "figure_suite_plan" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="figure_suite_plan",
                    title="Whole-paper figure suite plan",
                    payload=suite_plan_out,
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("figure_suite_plan", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[figure_suite_plan]: {exc}")

        suite_render_out = context.get("_output_figure_suite_render", {})
        if suite_render_out and "figure_suite_render" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="figure_suite_render",
                    title="Rendered figure suite",
                    payload=suite_render_out,
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("figure_suite_render", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[figure_suite_render]: {exc}")

        figure_assets_out = context.get("_output_figure_generate", {})
        if figure_assets_out and "figure_generate" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="figure_asset_pack",
                    title="Generated figure assets",
                    payload=figure_assets_out,
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("figure_asset_pack", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[figure_asset_pack]: {exc}")

        if drafted:
            for sec in drafted:
                text = context.get(f"_output_section_draft_{sec}", {}).get("text", "")
                if text:
                    sections_map[sec] = text
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="draft_pack",
                    title="Paper draft sections",
                    payload={
                        "sections": sections_map,
                        "section_names": list(sections_map.keys()),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("draft_pack", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[draft_pack]: {exc}")

        if _ensure_demo_seed_pool_pdf_closure(
            svc=svc,
            topic_id=topic_id,
            stage=stage,
            context=context,
            recorded=recorded,
            errors=errors,
        ):
            return recorded

        latex_out = context.get("_output_latex_compile", {})
        if latex_out and "latex_compile" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="final_bundle",
                    title="Final LaTeX bundle",
                    payload={
                        "output_dir": latex_out.get("output_dir", ""),
                        "pdf_path": latex_out.get("pdf_path", ""),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("final_bundle", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[final_bundle]: {exc}")
        elif drafted:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="final_bundle",
                    title="Draft bundle (pre-compilation)",
                    payload={"sections": list(sections_map.keys()), "status": "draft"},
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("final_bundle", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[final_bundle]: {exc}")

        if drafted:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="process_summary",
                    title="Writing process summary",
                    payload={
                        "sections_drafted": drafted,
                        "sections_count": len(drafted),
                        "tools_succeeded": list(succeeded_tools),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("process_summary", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[process_summary]: {exc}")

            try:
                from ..primitives.writing_impls import publication_run

                run = publication_run(
                    db=db or svc._db,
                    topic_id=topic_id,
                    target_profile=str(
                        context.get("target_profile", "high-impact-general")
                    ),
                    record_artifact=True,
                )
                pack_id = getattr(run, "publication_pack_artifact_id", 0)
                if pack_id:
                    recorded.append(("publication_pack", pack_id))
                run_id = getattr(run, "publication_run_artifact_id", 0)
                if run_id:
                    recorded.append(("publication_run", run_id))
            except Exception as exc:
                errors.append(f"auto_artifact[publication_run]: {exc}")

    return recorded


# ---------------------------------------------------------------------------
# Internal dispatchers
# ---------------------------------------------------------------------------


def _dispatch_primitive(
    name: str,
    *,
    db: Database,
    topic_id: int,
    context: dict[str, Any],
) -> ToolResult:
    """Execute a research primitive via the execution backend.

    Uses 'research_harness' backend which handles both LLM and non-LLM
    primitives (routes LLM calls through the configured provider).
    """
    backend = create_backend("research_harness", db=db)
    params = _build_primitive_params(name, topic_id=topic_id, context=context)
    params["db"] = db

    result: PrimitiveResult = backend.execute(name, **params)

    if not result.success:
        return ToolResult(
            tool=name, success=False, error=result.error or "Unknown error"
        )

    output = _to_dict(result.output)
    return ToolResult(tool=name, success=True, output=output)


def _dispatch_orchestrator(
    name: str,
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
) -> ToolResult:
    """Execute an orchestrator operation."""
    if name == "orchestrator_status":
        output = svc.get_status(topic_id)
        return ToolResult(tool=name, success=True, output=output)

    if name == "orchestrator_record_artifact":
        artifact_type = context.get("artifact_type", "")
        title = context.get("artifact_title", "")
        payload = context.get("artifact_payload", {})
        if not artifact_type:
            return ToolResult(
                tool=name,
                success=True,
                output={
                    "skipped": True,
                    "reason": "artifact_type_not_in_context; auto artifact recorder handles gate artifacts",
                },
            )
        artifact = svc.record_artifact(
            topic_id=topic_id,
            stage=stage,
            artifact_type=artifact_type,
            title=title,
            payload=payload,
        )
        artifact_id = artifact.id if hasattr(artifact, "id") else 0
        return ToolResult(
            tool=name,
            success=True,
            output={
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
            },
        )

    if name == "orchestrator_advance":
        result = svc.advance(topic_id)
        return ToolResult(tool=name, success=True, output=result)

    if name == "orchestrator_gate_check":
        details = svc.check_gate_details(topic_id, stage=stage)
        output = {"decision": details.get("gate_decision")}
        if stage == "build":
            output.update(details)
        return ToolResult(tool=name, success=True, output=output)

    if name == "orchestrator_resume":
        result = svc.resume_run(topic_id)
        return ToolResult(tool=name, success=True, output=result)

    return ToolResult(
        tool=name, success=False, error=f"Unhandled orchestrator tool: {name}"
    )


def _dispatch_service(
    name: str,
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
) -> ToolResult:
    """Execute a service-level operation (adversarial, review, finalize).

    Wires through to real OrchestratorService methods where possible.
    Tools that require LLM-constructed arguments (e.g. adversarial proposals)
    raise an explicit error so the caller knows to delegate to the MCP layer.
    """
    if name == "adversarial_status":
        result = svc.check_adversarial_status(topic_id)
        return ToolResult(tool=name, success=True, output=result)

    if name == "review_issues":
        result = svc.list_review_issues(
            topic_id,
            stage=context.get("review_stage"),
            status=context.get("review_status"),
            blocking_only=context.get("blocking_only", False),
        )
        return ToolResult(tool=name, success=True, output=result)

    if name == "review_status":
        result = svc.get_review_status(topic_id)
        return ToolResult(tool=name, success=True, output=result)

    if name == "review_resolve":
        issue_id = context.get("issue_id")
        status = context.get("resolve_status", "resolved")
        if not issue_id:
            return ToolResult(tool=name, success=False, error="No issue_id in context")
        result = svc.resolve_review_issue(issue_id, status)
        return ToolResult(tool=name, success=True, output=result)

    if name == "review_bundle_create":
        result = svc.create_review_bundle(
            topic_id,
            integrity_artifact_id=context.get("integrity_artifact_id"),
            scholarly_artifact_id=context.get("scholarly_artifact_id"),
        )
        return ToolResult(tool=name, success=True, output=result)

    if name == "finalize_project":
        result = svc.finalize_project(topic_id)
        return ToolResult(tool=name, success=True, output=result)

    # Tools requiring LLM-driven parameter construction
    if name in (
        "adversarial_run",
        "adversarial_resolve",
        "adversarial_review",
        "integrity_check",
        "review_add_issue",
        "review_respond",
    ):
        return ToolResult(
            tool=name,
            success=False,
            error=f"Service tool '{name}' requires LLM-constructed arguments; "
            f"delegate to MCP layer or provide arguments in context",
        )

    return ToolResult(tool=name, success=False, error=f"Unhandled service tool: {name}")


def _dispatch_query(
    name: str,
    *,
    db: Database,
    topic_id: int,
    context: dict[str, Any],
) -> ToolResult:
    """Execute a read-only query tool."""
    if name == "paper_list":
        conn = db.connect()
        try:
            rows = conn.execute(
                """SELECT p.id, p.title, p.year, p.venue, pt.relevance
                   FROM papers p JOIN paper_topics pt ON p.id = pt.paper_id
                   WHERE pt.topic_id = ? ORDER BY p.id""",
                (topic_id,),
            ).fetchall()
            papers = [dict(r) for r in rows]
            return ToolResult(
                tool=name, success=True, output={"count": len(papers), "papers": papers}
            )
        finally:
            conn.close()

    if name == "paper_coverage_check":
        backend = create_backend("research_harness", db=db)
        result = backend.execute("paper_coverage_check", topic_id=topic_id, db=db)
        if result.success:
            return ToolResult(tool=name, success=True, output=_to_dict(result.output))
        return ToolResult(
            tool=name, success=False, error=result.error or "coverage_check failed"
        )

    if name == "paper_dismiss":
        paper_id = context.get("paper_id")
        reason = context.get("reason", "")
        if not paper_id:
            return ToolResult(tool=name, success=False, error="No paper_id in context")
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE paper_topics SET relevance = 'dismissed' WHERE paper_id = ? AND topic_id = ?",
                (paper_id, topic_id),
            )
            conn.execute(
                # note_type must be 'user_dismissed' — every consumer
                # (acquisition pipeline, compiled_summary, llm_primitives,
                # analysis_impls) filters on that exact value. 'dismissed' here
                # would write a note no reader ever matches.
                """INSERT OR REPLACE INTO topic_paper_notes (paper_id, topic_id, note_type, content)
                   VALUES (?, ?, 'user_dismissed', ?)""",
                (paper_id, topic_id, reason),
            )
            conn.commit()
            return ToolResult(
                tool=name,
                success=True,
                output={"paper_id": paper_id, "dismissed": True},
            )
        except Exception as exc:
            conn.rollback()
            return ToolResult(
                tool=name, success=False, error=f"paper_dismiss failed: {exc}"
            )
        finally:
            conn.close()

    return ToolResult(
        tool=name, success=False, error=f"Query tool '{name}' not implemented"
    )


# ---------------------------------------------------------------------------
# Parameter builders
# ---------------------------------------------------------------------------


def _as_prose(value: Any) -> str:
    """Render a context value as the prose the writing primitives expect.

    The planner naturally produces contributions as a list of statements while
    every writing primitive takes a single string and calls ``.strip()`` on
    it. Passing the list straight through raised
    ``'list' object has no attribute 'strip'`` and took out the architecture,
    outline, figure-plan and compile steps of the write stage together.
    Numbering the items keeps the ordering the planner chose.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
    if value is None:
        return ""
    return str(value)


def _build_primitive_params(
    name: str,
    *,
    topic_id: int,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build parameters for a primitive from checkpoint context."""
    params: dict[str, Any] = {"topic_id": topic_id}

    if name == "paper_search":
        evidence_plan = context.get("paper_production_evidence_plan")
        search_params = (
            evidence_plan.get("search_parameters", {})
            if isinstance(evidence_plan, dict)
            and isinstance(evidence_plan.get("search_parameters"), dict)
            else {}
        )
        query = search_params.get(
            "query",
            context.get("query", context.get("topic_description", "")),
        )
        params["query"] = query
        params["auto_ingest"] = search_params.get(
            "auto_ingest",
            context.get("auto_ingest", True),
        )
        params["max_results"] = search_params.get(
            "max_results",
            context.get("max_results", 500),
        )
        for key in (
            "local_only",
            "per_provider_limit",
            "provider_allowlist",
            "provider_denylist",
            "tier_filter",
            "venue_filter",
        ):
            if key in search_params:
                params[key] = search_params[key]
            elif key in context:
                params[key] = context[key]

    elif name == "paper_ingest":
        params["source"] = context.get("ingest_source", "")

    elif name == "select_seeds":
        params["top_n"] = context.get("seed_top_n", 10)

    elif name == "expand_citations":
        params["forward_limit"] = context.get("forward_limit", 50)
        params["backward_limit"] = context.get("backward_limit", 50)

    elif name == "paper_acquire":
        if context.get("paper_acquire_limit") is not None:
            params["limit"] = int(context["paper_acquire_limit"])

    elif name in ("claim_extract", "gap_detect", "baseline_identify"):
        params["focus"] = context.get("focus", "")
        if name == "claim_extract":
            params["paper_ids"] = context.get("paper_ids", [])
        if name == "baseline_identify":
            # The baseline-coverage invariant compares the route's required
            # families against the families this call emits. The primitive
            # takes no family parameter, so without naming them in `focus` the
            # generator cannot know the vocabulary and the gate is
            # unsatisfiable by construction.
            families = _as_string_list(context.get("required_baseline_families"))
            if families:
                requirement = (
                    "Tag every baseline with a method_family drawn from this "
                    f"required coverage vocabulary: {', '.join(families)}. "
                    "Every listed family must appear on at least one baseline; "
                    "keep a descriptive sub-family in the baseline name."
                )
                params["focus"] = (
                    f"{params['focus']}\n\n{requirement}"
                    if params["focus"]
                    else requirement
                )

    elif name == "section_draft":
        params["section"] = context.get("section", "")
        params["outline"] = _as_prose(context.get("outline", ""))
        params["evidence_ids"] = context.get("evidence_ids", [])
        if context.get("paper_plan") is not None:
            params["paper_plan"] = context["paper_plan"]
        if context.get("strict_evidence") is not None:
            params["strict_evidence"] = bool(context["strict_evidence"])
        if context.get("extra_instructions"):
            params["extra_instructions"] = str(context["extra_instructions"])
        if context.get("max_words"):
            params["max_words"] = int(context["max_words"])
        if context.get("citation_quota") is not None:
            params["citation_quota"] = int(context["citation_quota"])
        if isinstance(context.get("paper_context"), dict):
            params["paper_context"] = context["paper_context"]

    elif name == "consistency_check":
        # The whole-manuscript pass must see the drafted prose, not just the
        # section-name list. Drafted texts live in _output_section_draft_{sec};
        # nothing else populates context["sections"] in the write pipeline.
        drafted_names = context.get("_drafted_sections", []) or []
        section_texts: list[str] = []
        for sec in drafted_names:
            text = context.get(f"_output_section_draft_{sec}", {}).get("text", "")
            if text:
                section_texts.append(f"## {sec}\n{text}")
        params["sections"] = section_texts or context.get("sections", [])
        if context.get("paper_plan") is not None:
            params["paper_plan"] = context["paper_plan"]

    elif name == "writing_architecture":
        params["contributions"] = _as_prose(context.get("contributions", ""))
        params["writing_patterns"] = _as_prose(context.get("writing_patterns", ""))
        params["outline"] = _as_prose(context.get("outline", ""))

    elif name == "figure_plan":
        params["contributions"] = _as_prose(context.get("contributions", ""))
        params["outline"] = _as_prose(context.get("outline", ""))
        params["target_venue"] = context.get("target_venue", context.get("venue", ""))

    elif name == "figure_suite_plan":
        params["target_content"] = _as_prose(
            context.get("contributions") or context.get("target_content") or ""
        )
        params["source"] = context.get("figure_suite_source", "matrix")
        if context.get("target_venue") or context.get("venue"):
            params["target_venue"] = context.get(
                "target_venue", context.get("venue", "")
            )

    elif name == "figure_suite_render":
        suite_out = context.get("_output_figure_suite_plan") or {}
        params["spec"] = (
            suite_out.get("spec")
            if isinstance(suite_out.get("spec"), dict)
            else suite_out
        )
        er_out = context.get("_output_experiment_run") or {}
        params["records"] = (
            context.get("figure_suite_records")
            or er_out.get("records")
            or er_out.get("observed_experiment_logs")
            or []
        )
        params["output_dir"] = str(
            context.get("figure_output_dir")
            or (Path(str(context.get("output_dir") or ".")) / "figures")
        )

    elif name == "figure_generate":
        figure_plan_out = context.get("_output_figure_plan", {})
        params["items"] = figure_plan_out.get("items", [])
        params["output_dir"] = str(
            context.get("figure_output_dir")
            or (Path(str(context.get("output_dir") or ".")) / "figures")
        )
        # The contract-driven illustration route (Grok / GPT Image / Gemini)
        # is the primary architecture-figure provider; an explicit
        # RESEARCH_HARNESS_FIGURE_MODEL still wins inside the primitive.
        if not os.environ.get("RESEARCH_HARNESS_FIGURE_MODEL", "").strip():
            params["model"] = "illustration"

    elif name == "competitive_learning":
        params["venue"] = context.get("venue", "")
        params["contributions"] = _as_prose(context.get("contributions", ""))

    elif name == "cold_start_run":
        params["gold_papers"] = context.get("gold_papers", [])

    elif name == "code_generate":
        params["study_spec"] = context.get("study_spec", "")

    elif name == "code_validate":
        cg_out = context.get("_output_code_generate", {})
        files = cg_out.get("files", {})
        entry = cg_out.get("entry_point", "main.py")
        params["code"] = files.get(entry, "") or cg_out.get("code", "")

    elif name == "experiment_run":
        cg_out = context.get("_output_code_generate", {})
        files = cg_out.get("files", {})
        entry = cg_out.get("entry_point", "main.py")
        if files:
            params["files"] = dict(files)
            params["entry_point"] = entry
        params["code"] = files.get(entry, "") or cg_out.get("code", "")
        params["primary_metric"] = context.get("primary_metric", "")
        for key in (*ABLATION_CONTRACT_FIELDS, *ABLATION_MEMORY_INPUT_FIELDS):
            if key in context:
                params[key] = context[key]
        if context.get("experiment_env_vars"):
            params["env_vars"] = dict(context["experiment_env_vars"])

    elif name == "verified_registry_build":
        er_out = context.get("_output_experiment_run", {})
        params["metrics"] = er_out.get("metrics", {})
        params["primary_metric_name"] = er_out.get(
            "primary_metric_name", context.get("primary_metric", "")
        )

    elif name == "verified_registry_check":
        er_out = context.get("_output_experiment_run", {})
        metrics = er_out.get("metrics", {})
        params["numbers"] = list(metrics.values()) if metrics else []

    elif name == "outline_generate":
        params["template"] = context.get("template", context.get("venue", "neurips"))
        params["contributions"] = _as_prose(context.get("contributions", ""))

    elif name == "section_review":
        drafted = context.get("_drafted_sections", [])
        sec = context.get("section", drafted[-1] if drafted else "")
        content = context.get(f"_output_section_draft_{sec}", {}).get("text", "")
        params["section"] = sec
        params["content"] = content
        # The abstract's word band is capped at the venue's own limit (section_review target_venue).
        params["target_venue"] = str(
            context.get("target_venue") or context.get("venue") or ""
        )

    elif name == "section_revise":
        drafted = context.get("_drafted_sections", [])
        sec = context.get("section", drafted[-1] if drafted else "")
        draft_out = context.get(f"_output_section_draft_{sec}", {})
        review_out = context.get("_output_section_review", {})
        params["section"] = sec
        params["content"] = draft_out.get("text", "")
        params["review_feedback"] = review_out.get(
            "feedback", review_out.get("issues", "")
        )

    elif name == "paper_verify_numbers":
        all_text_parts = []
        for sec in context.get("_drafted_sections", []):
            text = context.get(f"_output_section_draft_{sec}", {}).get("text", "")
            if text:
                # The verifier judges each part under its heading; a draft carries its section
                # only as a key, so the heading is written back in front of it.
                heading = (
                    ""
                    if text.lstrip().startswith("\\section")
                    else f"\\section{{{sec}}}\n"
                )
                all_text_parts.append(heading + text)
        params["text"] = "\n\n".join(all_text_parts)

    elif name == "citation_verify":
        citations: list[dict[str, Any]] = []
        for sec in context.get("_drafted_sections", []):
            sec_cites = context.get(f"_output_section_draft_{sec}", {}).get(
                "citations", []
            )
            if isinstance(sec_cites, list):
                citations.extend(sec_cites)
        params["citations"] = citations

    elif name == "evidence_trace":
        pass  # topic_id is sufficient

    elif name == "latex_compile":
        sections_map: dict[str, str] = {}
        for sec in context.get("_drafted_sections", []):
            text = context.get(f"_output_section_draft_{sec}", {}).get("text", "")
            if text:
                sections_map[sec] = text
        venue_overlay = (
            context.get("venue_overlay")
            if isinstance(context.get("venue_overlay"), dict)
            else {}
        )
        template = (
            str(venue_overlay.get("format_family") or "").strip()
            or str(context.get("template") or "").strip()
            or str(context.get("venue") or "arxiv").strip().lower()
        )
        params["sections"] = sections_map
        params["output_dir"] = context.get("output_dir", "")
        params["template"] = template
        params["title"] = str(
            context.get("title")
            or _as_prose(context.get("contributions", "")).split("\n")[0][:200]
        )
        params["abstract"] = str(context.get("abstract") or "")
        if context.get("authors"):
            params["authors"] = list(context["authors"])
        if context.get("bibliography_entries"):
            params["bibliography_entries"] = list(context["bibliography_entries"])

    elif name in ("publication_pack_backfill", "publication_run"):
        closure_plan = context.get("paper_production_closure_plan")
        closure_components = (
            closure_plan.get("publication_components", [])
            if isinstance(closure_plan, dict)
            and isinstance(closure_plan.get("publication_components"), list)
            else []
        )
        params["target_profile"] = context.get(
            "target_profile", context.get("venue", "high-impact-general")
        )
        if closure_components:
            params["components"] = list(closure_components)
        elif context.get("publication_components"):
            params["components"] = list(context["publication_components"])
        params["record_artifact"] = bool(context.get("record_artifact", True))

    # Pass through topic_id when available in context
    if "topic_id" in context:
        params.setdefault("topic_id", context["topic_id"])

    return params
