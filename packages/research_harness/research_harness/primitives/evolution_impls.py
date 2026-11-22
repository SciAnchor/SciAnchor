"""Evolution primitive implementations.

lesson_extract (stub fallback — real LLM version in llm_primitives.py),
lesson_overlay, strategy_distill, strategy_inject, experiment_log, meta_reflect.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..evolution.topic.store import LessonStore
from .registry import (
    EXPERIMENT_LOG_SPEC,
    GOVERNANCE_GATE_SPEC,
    LESSON_EXTRACT_SPEC,
    LESSON_OVERLAY_SPEC,
    META_REFLECT_SPEC,
    STRATEGY_DISTILL_SPEC,
    STRATEGY_INJECT_SPEC,
    register_primitive,
)
from .types import (
    ExperimentLogOutput,
    GovernanceGateOutput,
    LessonExtractOutput,
    LessonItem,
    LessonOverlayOutput,
    MetaReflectOutput,
    StrategyDistillOutput,
    StrategyInjectOutput,
)
from research_harness.config import state_path

logger = logging.getLogger(__name__)


@register_primitive(LESSON_EXTRACT_SPEC)
def lesson_extract(
    *,
    stage: str,
    stage_summary: str,
    issues_encountered: list[str] | None = None,
    **_: Any,
) -> LessonExtractOutput:
    """Extract lessons from stage execution. Stub — real LLM call dispatched by harness.

    In stub mode, converts issues_encountered into lesson items directly.
    """
    lessons: list[LessonItem] = []
    issues = issues_encountered or []

    if issues:
        for issue in issues:
            lessons.append(
                LessonItem(
                    stage=stage,
                    content=issue,
                    lesson_type="failure",
                    tags=[stage],
                )
            )

    # Always add a summary observation
    if stage_summary:
        lessons.append(
            LessonItem(
                stage=stage,
                content=stage_summary,
                lesson_type="observation",
                tags=[stage],
            )
        )

    return LessonExtractOutput(
        lessons=lessons,
        stage=stage,
        model_used="stub",
    )


@register_primitive(LESSON_OVERLAY_SPEC)
def lesson_overlay(
    *,
    stage: str,
    store_path: str,
    top_k: int = 5,
    **_: Any,
) -> LessonOverlayOutput:
    """Build prompt overlay from stored lessons."""
    store = LessonStore(store_path)
    overlay = store.build_overlay(stage, top_k=top_k)
    count = store.count(stage)

    return LessonOverlayOutput(
        overlay_text=overlay,
        lesson_count=count,
        stage=stage,
    )


@register_primitive(STRATEGY_DISTILL_SPEC)
def strategy_distill(
    *,
    db: Any = None,
    stage: str,
    min_lessons: int = 3,
    topic_id: int | None = None,
    force: bool = False,
    **_: Any,
) -> StrategyDistillOutput:
    """Distill lessons into strategies. Real LLM call dispatched by harness."""
    if db is None:
        return StrategyDistillOutput(stage=stage)

    from ..evolution.topic.distiller import StrategyDistiller

    # Default strategies dir
    strategies_dir = (
        Path(db._path).parent / "strategies"
        if hasattr(db, "_path")
        else state_path("strategies")
    )

    distiller = StrategyDistiller(db, strategies_dir)
    result = distiller.distill_stage(
        stage,
        min_lessons=min_lessons,
        topic_id=topic_id,
        force=force,
    )

    return StrategyDistillOutput(
        stage=result.stage,
        strategies_created=result.strategies_created,
        strategies_updated=result.strategies_updated,
        strategies_skipped=result.strategies_skipped,
        quality_scores=result.quality_scores,
        model_used=result.model_used,
    )


@register_primitive(STRATEGY_INJECT_SPEC)
def strategy_inject(
    *,
    db: Any = None,
    stage: str,
    topic_id: int | None = None,
    max_strategies: int = 3,
    **_: Any,
) -> StrategyInjectOutput:
    """Get active strategy overlay for a stage."""
    if db is None:
        return StrategyInjectOutput(stage=stage)

    from ..evolution.topic.injector import StrategyInjector

    injector = StrategyInjector(db)
    overlay = injector.build_strategy_overlay(
        stage,
        topic_id=topic_id,
        max_strategies=max_strategies,
    )
    strategies = injector.get_active_strategies(
        stage,
        topic_id=topic_id,
        max_strategies=max_strategies,
    )

    return StrategyInjectOutput(
        overlay_text=overlay,
        strategy_count=len(strategies),
        stage=stage,
    )


@register_primitive(EXPERIMENT_LOG_SPEC)
def experiment_log(
    *,
    db: Any = None,
    topic_id: int,
    hypothesis: str,
    primary_metric_name: str = "",
    primary_metric_value: float | None = None,
    metrics: dict | None = None,
    outcome: str = "pending",
    notes: str = "",
    study_spec_artifact_id: int | None = None,
    result_artifact_id: int | None = None,
    **_: Any,
) -> ExperimentLogOutput:
    """Log an experiment result for dual-loop tracking."""
    if db is None:
        return ExperimentLogOutput(topic_id=topic_id)

    from ..evolution.topic.outer_loop import OuterLoop

    loop = OuterLoop(db)
    eid = loop.log_experiment(
        topic_id,
        hypothesis,
        primary_metric_name=primary_metric_name,
        primary_metric_value=primary_metric_value,
        metrics=metrics,
        outcome=outcome,
        notes=notes,
        study_spec_artifact_id=study_spec_artifact_id,
        result_artifact_id=result_artifact_id,
    )

    exp_num = loop.get_experiment_count(topic_id)
    return ExperimentLogOutput(
        experiment_id=eid,
        experiment_number=exp_num,
        topic_id=topic_id,
    )


@register_primitive(GOVERNANCE_GATE_SPEC)
def governance_gate(
    *,
    verdict: str = "",
    judge_confidence: float = 0.5,
    generator_model: str = "",
    judge_model: str = "",
    external_anchors: int = 0,
    contamination_rho: float = 0.7,
    alpha: float = 0.1,
    same_lineage: bool | None = None,
    **_: Any,
) -> GovernanceGateOutput:
    """Correlation-aware acceptance guard (the r(rho) decision rule). Deterministic.

    Motivation (grounded): a self-graded 'pass' has residual false-accept risk
    driven by the shared generator<->judge blind spot (contamination_rho). Using
    multiple *models* only PARTIALLY decorrelates — family effects and a shared
    perplexity/familiarity bias leave residual correlation — so cross-model still
    carries a reduced rho. Each independent external anchor is a fresh check that
    (conservatively) multiplies the residual risk by rho again; to bring residual
    under the error budget alpha one needs k+1 >= log(alpha)/log(rho) checks (the
    self-grade counts as one, contaminated, check). The gate therefore forces
    external ground truth at a rate that grows with measured contamination.

    NOTE: the rho^(k+1) risk model is a conservative single-parameter policy for
    routing verification effort, not a proven statistical bound.
    """
    import math

    rho = min(max(float(contamination_rho), 0.0), 0.999)
    conf = min(max(float(judge_confidence), 0.0), 1.0)
    anchors = max(int(external_anchors), 0)
    a = min(max(float(alpha), 1e-6), 0.999)

    gen = (generator_model or "").strip().lower()
    jud = (judge_model or "").strip().lower()

    def _family(m: str) -> str:
        for fam in (
            "gpt",
            "claude",
            "gemini",
            "llama",
            "qwen",
            "mistral",
            "deepseek",
            "gemma",
        ):
            if fam in m:
                return fam
        return m

    if same_lineage is True or (gen and jud and gen == jud):
        self_graded = True
        regime = "self_graded"
        effective_rho = rho
    elif gen and jud and _family(gen) == _family(jud):
        # different checkpoints, same family: correlated (family effect)
        self_graded = False
        regime = "cross_model"
        effective_rho = rho * 0.7
    elif gen and jud:
        # genuinely different models: partial decorrelation, but shared
        # perplexity/familiarity bias means residual correlation remains
        self_graded = False
        regime = "cross_model"
        effective_rho = rho * 0.5
    else:
        # generator/judge unknown -> assume worst case (self-graded)
        self_graded = True
        regime = "self_graded"
        effective_rho = rho

    v = (verdict or "").strip().lower()
    positive = v in (
        "",
        "open",
        "accept",
        "pass",
        "novel",
        "supported",
        "true",
        "yes",
    )

    if not positive:
        # Contamination inflates ACCEPTs of the model's own favored findings, not
        # REJECTs. Keeping a finding out is the safe direction: accept the verdict.
        return GovernanceGateOutput(
            action="accept_verdict",
            self_graded=self_graded,
            contamination_regime=regime,
            effective_rho=round(effective_rho, 4),
            residual_contamination_risk=0.0,
            trust_adjusted_confidence=round(conf, 3),
            meets_error_budget=True,
            required_external_verifications=0,
            external_anchors=anchors,
            alpha=round(a, 4),
            rationale=(
                "Negative verdict: contamination inflates self-favored ACCEPTs, "
                "not REJECTs, so this verdict is in the safe direction and needs "
                "no external anchor."
            ),
        )

    if effective_rho <= 0.0:
        residual = 0.0
        needed_total = 0
    else:
        residual = effective_rho ** (anchors + 1)
        needed_total = max(0, math.ceil(math.log(a) / math.log(effective_rho)) - 1)

    required_external = max(0, needed_total - anchors)
    meets = residual <= a
    trust_conf = round(conf * (1.0 - residual), 3)

    if required_external <= 0:
        action = "accept"
        rationale = (
            f"Positive verdict backed by {anchors} external anchor(s); residual "
            f"contamination risk {residual:.3f} <= budget {a:.3f}. Trustworthy."
        )
    elif anchors == 0 and self_graded:
        action = "abstain_pending_external"
        rationale = (
            f"Self-graded positive verdict with NO external anchor and "
            f"contamination rho={effective_rho:.2f}: self-governance cannot meet "
            f"budget {a:.3f}. Abstain until >= {required_external} independent "
            f"external verification(s) are injected (r(rho))."
        )
    else:
        action = "require_external"
        rationale = (
            f"Positive verdict with {anchors} anchor(s) but residual "
            f"{residual:.3f} > budget {a:.3f} at rho={effective_rho:.2f}. Require "
            f"{required_external} more independent external verification(s) (r(rho))."
        )

    return GovernanceGateOutput(
        action=action,
        self_graded=self_graded,
        contamination_regime=regime,
        effective_rho=round(effective_rho, 4),
        residual_contamination_risk=round(residual, 4),
        trust_adjusted_confidence=trust_conf,
        meets_error_budget=meets,
        required_external_verifications=required_external,
        external_anchors=anchors,
        alpha=round(a, 4),
        rationale=rationale,
    )


@register_primitive(META_REFLECT_SPEC)
def meta_reflect(
    *,
    db: Any = None,
    topic_id: int,
    force: bool = False,
    **_: Any,
) -> MetaReflectOutput:
    """Cross-experiment meta-reflection."""
    if db is None:
        return MetaReflectOutput()

    from ..evolution.topic.outer_loop import OuterLoop

    loop = OuterLoop(db)
    reflection = loop.reflect(topic_id, force=force)

    if reflection is None:
        return MetaReflectOutput(
            decision="",
            reasoning="Not enough experiments for reflection",
        )

    should_transition = reflection.decision in ("PIVOT", "CONCLUDE")
    target = ""
    if reflection.decision == "PIVOT":
        target = "propose"
    elif reflection.decision == "CONCLUDE":
        target = "write"

    return MetaReflectOutput(
        decision=reflection.decision,
        reasoning=reflection.reasoning,
        next_hypothesis=reflection.next_hypothesis,
        patterns_observed=reflection.patterns_observed,
        confidence=reflection.confidence,
        reflection_number=reflection.reflection_number,
        model_used=reflection.model_used,
        should_transition=should_transition,
        transition_target=target,
    )
