"""Generate-Evaluate-Iterate loop controllers.

Implements the inner loop pattern from AI-Research-SKILLs and Anthropic's
harness design: generate -> evaluate -> iterate until quality threshold or max rounds.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from research_harness.storage.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision vocabulary (from AI-Research-SKILLs)
# ---------------------------------------------------------------------------

DIRECTION_DECISIONS = ("DEEPEN", "BROADEN", "PIVOT", "CONCLUDE")


@dataclass
class LoopIteration:
    """Record of one iteration in a generate-evaluate loop."""

    round: int
    score: float = 0.0
    passed: bool = False
    feedback: str = ""
    changes: list[str] = field(default_factory=list)


@dataclass
class LoopResult:
    """Final result of a generate-evaluate-iterate loop."""

    converged: bool
    final_score: float
    total_rounds: int
    iterations: list[LoopIteration] = field(default_factory=list)
    final_output: Any = None
    decision: str = ""  # DEEPEN|BROADEN|PIVOT|CONCLUDE


def build_revision_brief(
    review_result: Any, adversarial: dict[str, Any] | None = None
) -> str:
    """Structured revision brief from one review round.

    Groups failed deterministic checks (with offending items), the weakest
    scored dimensions (with reviewer comments), reviewer suggestions, and
    adversarial weaknesses (with their evidence quotes) so the reviser has to
    address each item instead of a flat suggestion string.
    """
    parts: list[str] = []

    def value(item: Any, key: str, default: Any = None) -> Any:
        return (
            item.get(key, default)
            if isinstance(item, Mapping)
            else getattr(item, key, default)
        )

    failed_checks = [
        check
        for check in (value(review_result, "deterministic_checks", []) or [])
        if not value(check, "passed", True)
    ]
    if failed_checks:
        lines = ["## Failed deterministic checks (fix every one)"]
        for check in failed_checks:
            found = ", ".join(
                str(item) for item in (value(check, "items_found", []) or [])[:5]
            )
            suffix = f" — offending items: {found}" if found else ""
            lines.append(
                f"- {value(check, 'check_name', '')}: {value(check, 'details', '')}{suffix}"
            )
        parts.append("\n".join(lines))

    dimensions = [
        dimension
        for dimension in (value(review_result, "dimensions", []) or [])
        if value(dimension, "score", 1.0) < 0.85
    ]
    dimensions.sort(key=lambda dimension: value(dimension, "score", 1.0))
    if dimensions:
        lines = ["## Weakest review dimensions (raise each)"]
        for dim in dimensions[:3]:
            score = value(dim, "score", 0.0)
            comment = value(dim, "comment", "") or "no comment provided"
            lines.append(
                f"- {value(dim, 'dimension', '')} (score {score:.2f}): {comment}"
            )
        parts.append("\n".join(lines))

    suggestions = [s for s in (value(review_result, "suggestions", []) or []) if s]
    if suggestions:
        lines = ["## Reviewer suggestions"]
        lines.extend(f"- {s}" for s in suggestions[:8])
        parts.append("\n".join(lines))

    weaknesses = (adversarial or {}).get("weaknesses") or []
    if weaknesses:
        lines = ["## Adversarial weaknesses (critical and major MUST be resolved)"]
        for weak in weaknesses[:8]:
            evidence = str(weak.get("evidence", ""))[:160]
            lines.append(
                f"- [{weak.get('severity', 'minor')}] {weak.get('category', 'general')}: "
                f"{weak.get('description', '')} (evidence: {evidence})"
            )
        parts.append("\n".join(lines))

    if not parts:
        return ""
    parts.append(
        "Address every item above explicitly; do not shorten or delete cited "
        "material just to satisfy a complaint."
    )
    return "\n\n".join(parts)


def run_section_loop(
    *,
    db: Database,
    section: str,
    topic_id: int,
    outline: str = "",
    max_words: int = 2000,
    max_rounds: int = 3,
    min_score: float = 0.7,
    evidence_ids: list[str] | None = None,
    paper_plan: dict[str, Any] | None = None,
    strict_evidence: bool | None = None,
    extra_instructions: str = "",
    paper_context: dict[str, Any] | None = None,
    adversarial: bool = False,
    writing_patterns: str = "",
) -> LoopResult:
    """Generate-evaluate-iterate loop for paper section writing.

    1. section_draft -> generates content
    2. section_review -> scores on 13 dimensions + deterministic checks
    3. adversarial_section_review (optional) -> skeptical pass; any critical
       weakness blocks convergence even when the cooperative score passes
    4. section_revise -> fixes issues from a structured revision brief
    5. Repeat until min_score reached (and no critical weaknesses) or
       max_rounds exhausted.
    """
    from . import llm_primitives

    iterations: list[LoopIteration] = []
    content = ""
    final_score = 0.0
    revision_brief = ""
    revise_evidence = ""

    for round_num in range(1, max_rounds + 1):
        logger.info("Section loop round %d/%d for '%s'", round_num, max_rounds, section)

        # Step 1: Draft (first round) or Revise (subsequent rounds)
        changes: list[str] = []
        if round_num == 1:
            draft_result = llm_primitives.section_draft(
                db=db,
                section=section,
                topic_id=topic_id,
                outline=outline,
                max_words=max_words,
                evidence_ids=evidence_ids,
                paper_plan=paper_plan,
                strict_evidence=strict_evidence,
                extra_instructions=extra_instructions,
                paper_context=paper_context,
                writing_patterns=writing_patterns,
            )
            content = draft_result.draft.content
        else:
            if not revise_evidence:
                # Revision sees the evidence list too, so it can ADD citations
                # instead of only rewording.
                try:
                    revise_evidence, _ = llm_primitives._build_numbered_evidence(
                        db, topic_id, task_type="section_draft", section=section
                    )
                except Exception:
                    logger.debug(
                        "revision evidence build failed for '%s'",
                        section,
                        exc_info=True,
                    )
            revise_result = llm_primitives.section_revise(
                db=db,
                section=section,
                content=content,
                review_feedback=revision_brief,
                target_words=max_words,
                topic_id=topic_id,
                paper_plan=paper_plan,
                paper_context=paper_context,
                evidence_text=revise_evidence,
            )
            content = revise_result.revised_content
            changes = revise_result.changes_made

        # Step 2: Cooperative review
        review_result = llm_primitives.section_review(
            db=db,
            section=section,
            content=content,
            target_words=max_words,
            paper_context=paper_context,
            topic_id=topic_id,
        )

        score = review_result.overall_score
        cooperative_pass = score >= min_score and not review_result.needs_revision
        final_score = score

        # Step 3: Adversarial review — only when the section would otherwise
        # converge, or on the last round (so the final output always carries
        # a skeptical assessment).
        adv_result: dict[str, Any] | None = None
        if adversarial and (cooperative_pass or round_num == max_rounds):
            try:
                adv_result = llm_primitives.adversarial_section_review(
                    db=db,
                    section=section,
                    content=content,
                    target_words=max_words,
                )
            except Exception as exc:
                logger.warning(
                    "adversarial review failed for '%s': %s — continuing without it",
                    section,
                    exc,
                )

        critical_count = int((adv_result or {}).get("critical_count", 0))
        passed = cooperative_pass and critical_count == 0

        revision_brief = build_revision_brief(review_result, adv_result)
        iteration = LoopIteration(
            round=round_num,
            score=score,
            passed=passed,
            feedback=revision_brief or "; ".join(review_result.suggestions[:3]),
            changes=changes,
        )
        iterations.append(iteration)

        logger.info(
            "Round %d: score=%.3f, passed=%s, critical=%d, suggestions=%d",
            round_num,
            score,
            passed,
            critical_count,
            len(review_result.suggestions),
        )

        if passed:
            return LoopResult(
                converged=True,
                final_score=score,
                total_rounds=round_num,
                iterations=iterations,
                final_output=content,
                decision="CONCLUDE",
            )

    # Did not converge
    decision = "DEEPEN" if final_score > 0.5 else "PIVOT"
    return LoopResult(
        converged=False,
        final_score=final_score,
        total_rounds=max_rounds,
        iterations=iterations,
        final_output=content,
        decision=decision,
    )


def run_experiment_loop(
    *,
    db: Database,
    topic_id: int,
    study_spec: str,
    max_iters: int = 5,
    target_metric: str = "",
    target_value: float | None = None,
) -> LoopResult:
    """Generate-evaluate-iterate loop for experiment code.

    1. code_generate -> produces experiment code
    2. code_validate -> checks syntax, security, imports
    3. experiment_run -> executes in sandbox
    4. Evaluate metrics -> decide continue or stop
    5. Feed metrics + feedback back to code_generate
    """
    from . import llm_primitives
    from research_harness.primitives.experiment_impls import (
        code_validate,
        experiment_run,
    )

    iterations: list[LoopIteration] = []
    code = ""
    metrics: dict[str, Any] = {}
    best_score = 0.0
    best_code = ""

    for iter_num in range(max_iters):
        logger.info("Experiment loop iteration %d/%d", iter_num + 1, max_iters)

        # Step 1: Generate code
        feedback = ""
        if iter_num > 0:
            feedback = _build_experiment_feedback(iterations[-1], metrics)

        gen_result = llm_primitives.code_generate(
            db=db,
            topic_id=topic_id,
            study_spec=study_spec,
            iteration=iter_num,
            previous_code=code,
            previous_metrics=metrics,
            feedback=feedback,
        )
        code = gen_result.files.get(gen_result.entry_point, "")
        if not code:
            iterations.append(
                LoopIteration(
                    round=iter_num + 1,
                    score=0.0,
                    passed=False,
                    feedback="Code generation produced empty output",
                )
            )
            continue

        # Step 2: Validate
        val_result = code_validate(code=code, auto_fix=True)
        if not val_result.ok:
            issues_str = "; ".join(i.message for i in val_result.issues[:3])
            iterations.append(
                LoopIteration(
                    round=iter_num + 1,
                    score=0.0,
                    passed=False,
                    feedback=f"Validation failed: {issues_str}",
                )
            )
            continue

        # Step 3: Run experiment
        try:
            run_result = experiment_run(
                code=code, timeout_sec=120.0, primary_metric=target_metric
            )
        except Exception as exc:
            iterations.append(
                LoopIteration(
                    round=iter_num + 1,
                    score=0.0,
                    passed=False,
                    feedback=f"Experiment execution failed: {exc}",
                )
            )
            continue

        if run_result.timed_out:
            iterations.append(
                LoopIteration(
                    round=iter_num + 1,
                    score=0.0,
                    passed=False,
                    feedback="Experiment timed out",
                )
            )
            continue

        metrics = run_result.metrics
        primary_value = run_result.primary_metric_value

        # Score this iteration
        score = 0.0
        passed = False
        if primary_value is not None:
            if target_value is not None:
                # Score relative to target
                score = (
                    min(1.0, primary_value / target_value) if target_value > 0 else 0.0
                )
                passed = primary_value >= target_value
            else:
                score = 0.5  # Has metrics but no target
                passed = run_result.returncode == 0

            if score > best_score:
                best_score = score
                best_code = code
        elif run_result.returncode == 0:
            score = 0.3
            passed = False

        iteration = LoopIteration(
            round=iter_num + 1,
            score=score,
            passed=passed,
            feedback=f"metrics={metrics}, returncode={run_result.returncode}",
        )
        iterations.append(iteration)

        logger.info("Iteration %d: score=%.3f, passed=%s", iter_num + 1, score, passed)

        if passed:
            return LoopResult(
                converged=True,
                final_score=score,
                total_rounds=iter_num + 1,
                iterations=iterations,
                final_output=best_code or code,
                decision="CONCLUDE",
            )

    # Did not converge
    decision = "DEEPEN" if best_score > 0.3 else "PIVOT"
    return LoopResult(
        converged=False,
        final_score=best_score,
        total_rounds=max_iters,
        iterations=iterations,
        final_output=best_code or code,
        decision=decision,
    )


def _build_experiment_feedback(
    last_iteration: LoopIteration, metrics: dict[str, Any]
) -> str:
    """Build feedback string from last iteration for code_generate."""
    parts = []
    if last_iteration.feedback:
        parts.append(f"Previous result: {last_iteration.feedback}")
    if not last_iteration.passed:
        parts.append("The experiment did not meet the target. Please improve.")
    if metrics:
        parts.append(f"Metrics from last run: {metrics}")
    return "\n".join(parts)
