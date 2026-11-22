"""Private method-improvement advisory helpers.

This module diagnoses weak or failed method attempts and proposes evidence-
grounded improvement directions. It produces advisory compiled views only: no
experiment execution, storage mutation, public transport behavior, or GPU
offload happens here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .cross_topic_atlas import (
    CrossTopicKnowledgeAtlas,
    CrossTopicKnowledgeLink,
    rank_cross_topic_serendipity_links,
)
from .experiment_design import ExperimentDesignBrief
from .research_wiki_insights import ResearchWikiEvidenceAnchor
from .wiki_context_pack import WikiContextPack


METHOD_IMPROVEMENT_REPORT_SCHEMA_VERSION = "method_improvement_report.v1"
_WORD_RE = re.compile(r"[a-z0-9]+")
_PROOF_WARNING = "cross-domain remedy is inspiration, not proof of correctness"


@dataclass(frozen=True)
class FailureDiagnosis:
    failure_pattern: str
    abstract_failure_pattern: str
    observed_failure: str
    likely_causes: tuple[str, ...]
    implicated_metrics: tuple[str, ...]
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...]
    field_provenance: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RemedyCandidate:
    link_type: str
    source_topic_id: int
    target_topic_id: int
    score: float
    source_label: str
    target_label: str
    shared_abstractions: tuple[str, ...]
    evidence_summary: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class MethodImprovementRecommendation:
    recommendation_id: str
    modification_type: str
    support_level: str
    recommended_change: str
    transfer_explanation: str
    validation_plan: tuple[str, ...]
    falsification_test: str
    risk_level: str
    complexity: str
    remedy_candidates: tuple[RemedyCandidate, ...]
    warnings: tuple[str, ...]
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...]
    field_provenance: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MethodImprovementReport:
    schema_version: str
    artifact_role: str
    topic_id: int
    opportunity_id: str
    method_name: str
    support_level: str
    failure_diagnoses: tuple[FailureDiagnosis, ...]
    recommendations: tuple[MethodImprovementRecommendation, ...]
    warnings: tuple[str, ...]
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...]
    field_provenance: dict[str, str] = field(default_factory=dict)


def build_method_improvement_report(
    *,
    brief: ExperimentDesignBrief,
    context_pack: WikiContextPack,
    atlas: CrossTopicKnowledgeAtlas | None = None,
    method_name: str = "",
    observed_failures: tuple[str, ...] = (),
    ablation_notes: tuple[str, ...] = (),
    review_feedback: tuple[str, ...] = (),
    max_recommendations: int = 3,
    max_remedies: int = 3,
) -> MethodImprovementReport:
    """Build a private ``method_improvement_report.v1``."""

    normalized_method = " ".join(str(method_name or brief.opportunity_id).split())
    observations = _observations(
        observed_failures=observed_failures,
        ablation_notes=ablation_notes,
        review_feedback=review_feedback,
    )
    diagnoses = _failure_diagnoses(
        brief=brief,
        observations=observations,
        context_pack=context_pack,
    )
    remedies = _ranked_remedies(
        atlas=atlas,
        brief=brief,
        observations=observations,
        max_results=max(1, int(max_recommendations) * max(1, int(max_remedies))),
    )
    recommendations = _recommendations(
        brief=brief,
        context_pack=context_pack,
        diagnoses=diagnoses,
        remedies=remedies,
        max_recommendations=max_recommendations,
        max_remedies=max_remedies,
    )
    warnings = _report_warnings(
        brief=brief,
        context_pack=context_pack,
        recommendations=recommendations,
    )

    return MethodImprovementReport(
        schema_version=METHOD_IMPROVEMENT_REPORT_SCHEMA_VERSION,
        artifact_role="advisory_compiled_view",
        topic_id=brief.topic_id,
        opportunity_id=brief.opportunity_id,
        method_name=normalized_method,
        support_level=_report_support_level(brief, recommendations, warnings),
        failure_diagnoses=diagnoses,
        recommendations=recommendations,
        warnings=warnings,
        evidence_anchors=_dedupe_anchors(
            (*brief.evidence_anchors, *context_pack_anchors(context_pack))
        ),
        field_provenance={
            "failure_diagnoses": "observed_failures_and_experiment_brief",
            "recommendations": "failure_diagnosis_context_pack_and_atlas",
            "support_level": "brief_context_and_recommendation_support",
        },
    )


def method_improvement_report_to_dict(
    report: MethodImprovementReport,
) -> dict[str, Any]:
    """Serialize a method-improvement report into deterministic plain data."""

    return {
        "schema_version": report.schema_version,
        "artifact_role": report.artifact_role,
        "topic_id": report.topic_id,
        "opportunity_id": report.opportunity_id,
        "method_name": report.method_name,
        "support_level": report.support_level,
        "warnings": list(report.warnings),
        "field_provenance": dict(report.field_provenance),
        "failure_diagnoses": [
            _diagnosis_to_dict(diagnosis) for diagnosis in report.failure_diagnoses
        ],
        "recommendations": [
            _recommendation_to_dict(recommendation)
            for recommendation in report.recommendations
        ],
        "evidence_anchors": [
            _evidence_anchor_to_dict(anchor) for anchor in report.evidence_anchors
        ],
    }


def render_method_improvement_report_markdown(
    report: MethodImprovementReport,
) -> str:
    """Render a concise deterministic Markdown report."""

    lines = [
        "# Method Improvement Report",
        "",
        f"- Topic id: {report.topic_id}",
        f"- Opportunity id: {report.opportunity_id}",
        f"- Method: {report.method_name}",
        f"- Support: {report.support_level}",
        "",
    ]
    if report.warnings:
        _append_section(lines, "Warnings", report.warnings)
    lines.append("## Failure diagnoses")
    lines.append("")
    for diagnosis in report.failure_diagnoses:
        lines.extend(
            [
                f"- {diagnosis.failure_pattern}: {diagnosis.observed_failure}",
                f"  - Abstract pattern: {diagnosis.abstract_failure_pattern}",
            ]
        )
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    for recommendation in report.recommendations:
        lines.extend(
            [
                f"### {recommendation.recommendation_id}",
                "",
                f"- Type: {recommendation.modification_type}",
                f"- Support: {recommendation.support_level}",
                f"- Change: {recommendation.recommended_change}",
                f"- Transfer: {recommendation.transfer_explanation}",
                f"- Falsification test: {recommendation.falsification_test}",
                "",
            ]
        )
        _append_section(lines, "Validation plan", recommendation.validation_plan)
    return "\n".join(lines).rstrip() + "\n"


def _observations(
    *,
    observed_failures: tuple[str, ...],
    ablation_notes: tuple[str, ...],
    review_feedback: tuple[str, ...],
) -> tuple[str, ...]:
    values = [*observed_failures, *ablation_notes, *review_feedback]
    return tuple(
        dict.fromkeys(" ".join(str(value).split()) for value in values if value)
    )


def _failure_diagnoses(
    *,
    brief: ExperimentDesignBrief,
    observations: tuple[str, ...],
    context_pack: WikiContextPack,
) -> tuple[FailureDiagnosis, ...]:
    source_observations = observations or tuple(brief.warnings) or (brief.hypothesis,)
    diagnoses = [
        _diagnose_one(brief=brief, observation=observation, context_pack=context_pack)
        for observation in source_observations
    ]
    return _dedupe_diagnoses(tuple(diagnoses))


def _diagnose_one(
    *,
    brief: ExperimentDesignBrief,
    observation: str,
    context_pack: WikiContextPack,
) -> FailureDiagnosis:
    terms = _terms(
        " ".join((observation, brief.abstract_challenge, " ".join(brief.metrics)))
    )
    pattern = _failure_pattern(terms, observation)
    abstract_pattern = _abstract_failure_pattern(pattern, brief.abstract_challenge)
    return FailureDiagnosis(
        failure_pattern=pattern,
        abstract_failure_pattern=abstract_pattern,
        observed_failure=observation,
        likely_causes=_likely_causes(pattern, brief),
        implicated_metrics=_implicated_metrics(brief.metrics, terms),
        evidence_anchors=_diagnosis_anchors(brief, context_pack),
        field_provenance={
            "failure_pattern": "observed_failure_keyword_mapping",
            "likely_causes": "failure_pattern_and_experiment_brief",
            "implicated_metrics": "experiment_brief_metrics",
        },
    )


def _dedupe_diagnoses(
    diagnoses: tuple[FailureDiagnosis, ...],
) -> tuple[FailureDiagnosis, ...]:
    by_key: dict[tuple[str, str, str], FailureDiagnosis] = {}
    for diagnosis in diagnoses:
        key = (
            diagnosis.failure_pattern,
            diagnosis.abstract_failure_pattern,
            diagnosis.observed_failure,
        )
        by_key.setdefault(key, diagnosis)
    return tuple(by_key.values())


def _failure_pattern(terms: set[str], observation: str) -> str:
    normalized = observation.lower()
    if {"source", "provenance", "anchor", "hash", "resolvability"} & terms:
        return "provenance_control_failure"
    if {"recall", "retrieval", "reranking", "tail"} & terms:
        return "retrieval_quality_failure"
    if "leakage" in normalized:
        return "evaluation_protocol_failure"
    if {"baseline", "metric", "manual", "validation"} & terms:
        return "evaluation_protocol_failure"
    if {"drift", "unstable", "perturbation"} & terms:
        return "robustness_failure"
    return "under_specified_failure"


def _abstract_failure_pattern(pattern: str, abstract_challenge: str) -> str:
    mapping = {
        "provenance_control_failure": "provenance_control",
        "retrieval_quality_failure": "evaluation_bridge",
        "evaluation_protocol_failure": "evaluation_bridge",
        "robustness_failure": "failure_mode",
    }
    return mapping.get(pattern, abstract_challenge or "under-specified_challenge")


def _likely_causes(
    pattern: str,
    brief: ExperimentDesignBrief,
) -> tuple[str, ...]:
    if pattern == "provenance_control_failure":
        return (
            "evidence anchors are not checked after synthesis steps",
            "source hashes are not enforced as a verifier boundary",
        )
    if pattern == "retrieval_quality_failure":
        return (
            "retrieval or reranking objective does not cover the failure slice",
            "hard negatives or tail queries are underrepresented",
        )
    if pattern == "evaluation_protocol_failure":
        causes = ["baseline, metric, or dataset evidence is incomplete"]
        if "missing_baselines" in brief.warnings:
            causes.append("baseline evidence is missing")
        return tuple(causes)
    if pattern == "robustness_failure":
        return ("method is sensitive to the stress-test perturbation",)
    return ("failure mode is under-specified by the available evidence",)


def _implicated_metrics(
    metrics: tuple[str, ...],
    terms: set[str],
) -> tuple[str, ...]:
    matched = [metric for metric in metrics if _terms(metric) & terms or not terms]
    return tuple(dict.fromkeys(matched or metrics))


def _diagnosis_anchors(
    brief: ExperimentDesignBrief,
    context_pack: WikiContextPack,
) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    return _dedupe_anchors(
        (*brief.evidence_anchors, *context_pack_anchors(context_pack))
    )


def _ranked_remedies(
    *,
    atlas: CrossTopicKnowledgeAtlas | None,
    brief: ExperimentDesignBrief,
    observations: tuple[str, ...],
    max_results: int,
) -> tuple[CrossTopicKnowledgeLink, ...]:
    if atlas is None:
        return ()
    query = " ".join(
        (
            brief.abstract_challenge,
            brief.hypothesis,
            " ".join(brief.metrics),
            " ".join(observations),
        )
    )
    ranked = rank_cross_topic_serendipity_links(
        atlas,
        query=query,
        max_results=max_results,
    )
    return tuple(
        link
        for link in ranked
        if brief.topic_id in {link.source_topic_id, link.target_topic_id}
    )


def _recommendations(
    *,
    brief: ExperimentDesignBrief,
    context_pack: WikiContextPack,
    diagnoses: tuple[FailureDiagnosis, ...],
    remedies: tuple[CrossTopicKnowledgeLink, ...],
    max_recommendations: int,
    max_remedies: int,
) -> tuple[MethodImprovementRecommendation, ...]:
    if _requires_evidence_first(brief, context_pack):
        return (_evidence_first_recommendation(brief=brief, diagnoses=diagnoses),)

    selected_diagnoses = diagnoses[: max(1, int(max_recommendations))]
    recommendations: list[MethodImprovementRecommendation] = []
    for index, diagnosis in enumerate(selected_diagnoses, start=1):
        matching_remedies = _matching_remedies(
            diagnosis=diagnosis,
            remedies=remedies,
            max_remedies=max(0, int(max_remedies)),
        )
        recommendations.append(
            _recommendation_for_diagnosis(
                index=index,
                brief=brief,
                context_pack=context_pack,
                diagnosis=diagnosis,
                remedies=matching_remedies,
            )
        )
    return tuple(recommendations)


def _requires_evidence_first(
    brief: ExperimentDesignBrief,
    context_pack: WikiContextPack,
) -> bool:
    return (
        brief.support_level == "speculative"
        or not brief.evidence_anchors
        or context_pack.evidence_anchor_count == 0
        or "missing_baselines" in brief.warnings
        and "weak_metrics" in brief.warnings
    )


def _evidence_first_recommendation(
    *,
    brief: ExperimentDesignBrief,
    diagnoses: tuple[FailureDiagnosis, ...],
) -> MethodImprovementRecommendation:
    validation_plan = (
        "define a paper-backed baseline before changing the method",
        "collect failure cases with resolvable evidence anchors",
        "rerun manual validation before proposing architecture changes",
    )
    return MethodImprovementRecommendation(
        recommendation_id="method-improvement-1",
        modification_type="evaluation_protocol_change",
        support_level="speculative",
        recommended_change=(
            "collect evidence, baselines, and failure cases before changing the method"
        ),
        transfer_explanation="insufficient evidence for cross-domain remedy transfer",
        validation_plan=validation_plan,
        falsification_test=(
            "Falsify this recommendation if a paper-backed baseline and resolvable "
            "failure anchors already exist."
        ),
        risk_level="medium",
        complexity="low",
        remedy_candidates=(),
        warnings=("insufficient_evidence_for_method_change",),
        evidence_anchors=_dedupe_anchors(
            tuple(
                anchor
                for diagnosis in diagnoses
                for anchor in diagnosis.evidence_anchors
            )
        ),
        field_provenance={
            "recommended_change": "unsupported_manual_review_fallback",
            "validation_plan": "brief_warnings_and_missing_evidence",
            "falsification_test": "derived_advisory_guardrail",
        },
    )


def _matching_remedies(
    *,
    diagnosis: FailureDiagnosis,
    remedies: tuple[CrossTopicKnowledgeLink, ...],
    max_remedies: int,
) -> tuple[CrossTopicKnowledgeLink, ...]:
    if max_remedies <= 0:
        return ()
    diagnosis_terms = _terms(
        " ".join(
            (
                diagnosis.failure_pattern,
                diagnosis.abstract_failure_pattern,
                diagnosis.observed_failure,
                " ".join(diagnosis.likely_causes),
            )
        )
    )
    ranked = sorted(
        remedies,
        key=lambda link: (
            -_link_overlap(link, diagnosis_terms),
            -link.score,
            link.link_type,
            link.source_label,
        ),
    )
    matched = [
        link
        for link in ranked
        if _link_overlap(link, diagnosis_terms) > 0 or _shared_abstractions(link)
    ]
    return tuple(matched[:max_remedies])


def _recommendation_for_diagnosis(
    *,
    index: int,
    brief: ExperimentDesignBrief,
    context_pack: WikiContextPack,
    diagnosis: FailureDiagnosis,
    remedies: tuple[CrossTopicKnowledgeLink, ...],
) -> MethodImprovementRecommendation:
    remedy_candidates = tuple(_remedy_candidate(link) for link in remedies)
    modification_type = _modification_type(diagnosis, remedies)
    support_level = _recommendation_support_level(brief, context_pack, remedies)
    warnings = _recommendation_warnings(remedies=remedies, support_level=support_level)
    recommended_change = _recommended_change(
        modification_type=modification_type,
        diagnosis=diagnosis,
        remedies=remedies,
    )
    return MethodImprovementRecommendation(
        recommendation_id=f"method-improvement-{index}",
        modification_type=modification_type,
        support_level=support_level,
        recommended_change=recommended_change,
        transfer_explanation=_transfer_explanation(diagnosis, remedies),
        validation_plan=_validation_plan(brief, diagnosis, modification_type),
        falsification_test=_falsification_test(brief, diagnosis, modification_type),
        risk_level=_risk_level(modification_type, support_level),
        complexity=_complexity(modification_type),
        remedy_candidates=remedy_candidates,
        warnings=warnings,
        evidence_anchors=_recommendation_anchors(
            diagnosis=diagnosis,
            context_pack=context_pack,
        ),
        field_provenance={
            "recommended_change": "evidence_context_and_cross_domain_link"
            if remedies
            else "failure_diagnosis_and_context_pack",
            "transfer_explanation": "cross_topic_atlas_link"
            if remedies
            else "in_domain_failure_pattern",
            "validation_plan": "experiment_brief_and_failure_diagnosis",
            "falsification_test": "derived_advisory_guardrail",
        },
    )


def _remedy_candidate(link: CrossTopicKnowledgeLink) -> RemedyCandidate:
    return RemedyCandidate(
        link_type=link.link_type,
        source_topic_id=link.source_topic_id,
        target_topic_id=link.target_topic_id,
        score=link.score,
        source_label=link.source_label,
        target_label=link.target_label,
        shared_abstractions=_shared_abstractions(link),
        evidence_summary=link.evidence_summary,
        warnings=link.warnings,
    )


def _modification_type(
    diagnosis: FailureDiagnosis,
    remedies: tuple[CrossTopicKnowledgeLink, ...],
) -> str:
    text = " ".join(
        (
            diagnosis.failure_pattern,
            diagnosis.abstract_failure_pattern,
            diagnosis.observed_failure,
            remedies[0].source_label if remedies else "",
            remedies[0].explanation if remedies else "",
        )
    ).lower()
    if {"verifier", "critic", "gate", "check"}.intersection(_terms(text)):
        return "verifier_or_critic_addition"
    if "retrieval" in text or "reranker" in text:
        return "retrieval_or_reranking_change"
    if "objective" in text or "loss" in text:
        return "algorithmic_objective_change"
    if "dataset" in text or "baseline" in text or "metric" in text:
        return "evaluation_protocol_change"
    if "architecture" in text or "decomposition" in text:
        return "architecture_decomposition"
    if diagnosis.failure_pattern == "provenance_control_failure":
        return "verifier_or_critic_addition"
    return "module_addition"


def _recommendation_support_level(
    brief: ExperimentDesignBrief,
    context_pack: WikiContextPack,
    remedies: tuple[CrossTopicKnowledgeLink, ...],
) -> str:
    has_evidence = (
        bool(brief.evidence_anchors) and context_pack.evidence_anchor_count > 0
    )
    strong_remedy = any(link.score >= 0.65 and not link.warnings for link in remedies)
    weak_remedy = bool(remedies)
    if brief.support_level == "evidence_bound" and has_evidence and strong_remedy:
        return "evidence_bound"
    if has_evidence or weak_remedy:
        return "weakly_supported"
    return "speculative"


def _recommendation_warnings(
    *,
    remedies: tuple[CrossTopicKnowledgeLink, ...],
    support_level: str,
) -> tuple[str, ...]:
    warnings = [_PROOF_WARNING]
    for link in remedies:
        warnings.extend(link.warnings)
        if link.score < 0.5:
            warnings.append("cross_domain_remedy_weak")
    if support_level != "evidence_bound":
        warnings.append("recommendation_not_evidence_bound")
    return tuple(dict.fromkeys(warnings))


def _recommended_change(
    *,
    modification_type: str,
    diagnosis: FailureDiagnosis,
    remedies: tuple[CrossTopicKnowledgeLink, ...],
) -> str:
    if remedies:
        source_label = remedies[0].source_label
        if modification_type == "verifier_or_critic_addition":
            return (
                f"add a verifier/critic module inspired by {source_label} for "
                f"{diagnosis.abstract_failure_pattern}"
            )
        if modification_type == "retrieval_or_reranking_change":
            return f"modify retrieval or reranking using {source_label}"
        if modification_type == "evaluation_protocol_change":
            return f"revise evaluation protocol using {source_label}"
        return f"adapt {source_label} for {diagnosis.abstract_failure_pattern}"
    if modification_type == "verifier_or_critic_addition":
        return "add an in-domain evidence verifier before synthesis output"
    if modification_type == "evaluation_protocol_change":
        return "revise baseline and metric coverage before method changes"
    return f"modify method to address {diagnosis.abstract_failure_pattern}"


def _transfer_explanation(
    diagnosis: FailureDiagnosis,
    remedies: tuple[CrossTopicKnowledgeLink, ...],
) -> str:
    if not remedies:
        return (
            f"in-domain context suggests the failure is {diagnosis.abstract_failure_pattern}; "
            "no cross-domain remedy was selected"
        )
    link = remedies[0]
    abstractions = _shared_abstractions(link)
    abstraction_text = ", ".join(abstractions) or diagnosis.abstract_failure_pattern
    return (
        f"{link.source_label} may transfer because both contexts share "
        f"{abstraction_text}; this is an analogy and must be validated."
    )


def _validation_plan(
    brief: ExperimentDesignBrief,
    diagnosis: FailureDiagnosis,
    modification_type: str,
) -> tuple[str, ...]:
    plan = [
        f"rerun the failing slice: {diagnosis.observed_failure}",
        *(f"measure {metric}" for metric in diagnosis.implicated_metrics[:2]),
    ]
    if brief.baselines:
        plan.append(f"compare against baseline: {brief.baselines[0]}")
    else:
        plan.append("add a paper-backed baseline before claiming improvement")
    if modification_type == "verifier_or_critic_addition":
        plan.append("ablate the verifier/critic module")
    elif modification_type == "retrieval_or_reranking_change":
        plan.append("test tail queries and hard negatives")
    else:
        plan.append("run the original ablation and one stress test")
    return tuple(dict.fromkeys(plan))


def _falsification_test(
    brief: ExperimentDesignBrief,
    diagnosis: FailureDiagnosis,
    modification_type: str,
) -> str:
    metric = (
        diagnosis.implicated_metrics[0]
        if diagnosis.implicated_metrics
        else "primary metric"
    )
    baseline = brief.baselines[0] if brief.baselines else "the selected baseline"
    return (
        f"Falsify the {modification_type} if {metric} does not improve over "
        f"{baseline} on {brief.target_data_slice}."
    )


def _risk_level(
    modification_type: str,
    support_level: str,
) -> str:
    if support_level == "speculative":
        return "high"
    if modification_type in {
        "architecture_decomposition",
        "algorithmic_objective_change",
    }:
        return "high"
    if support_level == "weakly_supported":
        return "medium"
    return "medium" if modification_type == "module_addition" else "low"


def _complexity(modification_type: str) -> str:
    if modification_type in {
        "architecture_decomposition",
        "algorithmic_objective_change",
    }:
        return "high"
    if modification_type in {
        "verifier_or_critic_addition",
        "retrieval_or_reranking_change",
    }:
        return "medium"
    return "low"


def _recommendation_anchors(
    *,
    diagnosis: FailureDiagnosis,
    context_pack: WikiContextPack,
) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    return _dedupe_anchors(
        (*diagnosis.evidence_anchors, *context_pack_anchors(context_pack))
    )


def _report_warnings(
    *,
    brief: ExperimentDesignBrief,
    context_pack: WikiContextPack,
    recommendations: tuple[MethodImprovementRecommendation, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if brief.support_level != "evidence_bound":
        warnings.append("weak_or_speculative_brief")
    if not brief.evidence_anchors:
        warnings.append("evidence_anchor_missing")
    if context_pack.degraded:
        warnings.append("context_pack_degraded")
    if context_pack.truncated:
        warnings.append("context_pack_truncated")
    warnings.extend(brief.warnings)
    for warning in context_pack.warnings:
        warnings.append(warning.code)
    for recommendation in recommendations:
        warnings.extend(recommendation.warnings)
        if recommendation.support_level != "evidence_bound":
            warnings.append("recommendation_not_evidence_bound")
        if any(
            link_warning
            for candidate in recommendation.remedy_candidates
            for link_warning in candidate.warnings
        ):
            warnings.append("cross_domain_remedy_weak_or_warned")
    return tuple(dict.fromkeys(warnings))


def _report_support_level(
    brief: ExperimentDesignBrief,
    recommendations: tuple[MethodImprovementRecommendation, ...],
    warnings: tuple[str, ...],
) -> str:
    if brief.support_level == "speculative" or "evidence_anchor_missing" in warnings:
        return "speculative"
    if recommendations and all(
        recommendation.support_level == "evidence_bound"
        for recommendation in recommendations
    ):
        return "evidence_bound"
    if recommendations:
        return "weakly_supported"
    return "speculative"


def context_pack_anchors(
    context_pack: WikiContextPack,
) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    return tuple(
        anchor for page in context_pack.pages for anchor in page.evidence_anchors
    )


def _shared_abstractions(link: CrossTopicKnowledgeLink) -> tuple[str, ...]:
    raw = link.metadata.get("shared_abstractions")
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw if str(item).strip())


def _link_overlap(
    link: CrossTopicKnowledgeLink,
    terms: set[str],
) -> int:
    text = " ".join(
        (
            link.link_type,
            link.source_label,
            link.target_label,
            link.explanation,
            " ".join(_shared_abstractions(link)),
        )
    )
    return len(terms & _terms(text))


def _diagnosis_to_dict(diagnosis: FailureDiagnosis) -> dict[str, Any]:
    return {
        "failure_pattern": diagnosis.failure_pattern,
        "abstract_failure_pattern": diagnosis.abstract_failure_pattern,
        "observed_failure": diagnosis.observed_failure,
        "likely_causes": list(diagnosis.likely_causes),
        "implicated_metrics": list(diagnosis.implicated_metrics),
        "field_provenance": dict(diagnosis.field_provenance),
        "evidence_anchors": [
            _evidence_anchor_to_dict(anchor) for anchor in diagnosis.evidence_anchors
        ],
    }


def _recommendation_to_dict(
    recommendation: MethodImprovementRecommendation,
) -> dict[str, Any]:
    return {
        "recommendation_id": recommendation.recommendation_id,
        "modification_type": recommendation.modification_type,
        "support_level": recommendation.support_level,
        "recommended_change": recommendation.recommended_change,
        "transfer_explanation": recommendation.transfer_explanation,
        "validation_plan": list(recommendation.validation_plan),
        "falsification_test": recommendation.falsification_test,
        "risk_level": recommendation.risk_level,
        "complexity": recommendation.complexity,
        "warnings": list(recommendation.warnings),
        "field_provenance": dict(recommendation.field_provenance),
        "remedy_candidates": [
            _remedy_candidate_to_dict(candidate)
            for candidate in recommendation.remedy_candidates
        ],
        "evidence_anchors": [
            _evidence_anchor_to_dict(anchor)
            for anchor in recommendation.evidence_anchors
        ],
    }


def _remedy_candidate_to_dict(candidate: RemedyCandidate) -> dict[str, Any]:
    return {
        "link_type": candidate.link_type,
        "source_topic_id": candidate.source_topic_id,
        "target_topic_id": candidate.target_topic_id,
        "score": candidate.score,
        "source_label": candidate.source_label,
        "target_label": candidate.target_label,
        "shared_abstractions": list(candidate.shared_abstractions),
        "evidence_summary": list(candidate.evidence_summary),
        "warnings": list(candidate.warnings),
    }


def _evidence_anchor_to_dict(
    anchor: ResearchWikiEvidenceAnchor,
) -> dict[str, Any]:
    return {
        "page_path": anchor.page_path,
        "paper_id": anchor.paper_id,
        "source_type": anchor.source_type,
        "source_id": anchor.source_id,
        "source_hash": anchor.source_hash,
        "section_anchor": anchor.section_anchor,
        "evidence_snippet": anchor.evidence_snippet,
    }


def _dedupe_anchors(
    anchors: tuple[ResearchWikiEvidenceAnchor, ...],
) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    by_key = {
        (
            anchor.page_path,
            anchor.paper_id,
            anchor.source_type,
            anchor.source_id,
            anchor.source_hash,
            anchor.section_anchor,
            anchor.evidence_snippet,
        ): anchor
        for anchor in anchors
    }
    return tuple(by_key[key] for key in sorted(by_key))


def _append_section(
    lines: list[str],
    title: str,
    values: tuple[str, ...],
) -> None:
    lines.extend([f"## {title}", ""])
    if values:
        lines.extend(f"- {value}" for value in values)
    else:
        lines.append("- none")
    lines.append("")


def _terms(value: str) -> set[str]:
    return set(_WORD_RE.findall(str(value or "").lower()))
