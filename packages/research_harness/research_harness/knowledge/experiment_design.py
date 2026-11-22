"""Private experiment-design brief helpers.

This module converts an evidence-grounded innovation opportunity into a
falsifiable validation plan. It deliberately stops at design guidance: no
experiment execution, hyperparameter orchestration, training script generation,
or storage/provenance mutation happens here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .innovation_opportunity import (
    InnovationOpportunity,
    InnovationOpportunityReport,
)
from .research_wiki_insights import ResearchWikiEvidenceAnchor


EXPERIMENT_DESIGN_BRIEF_SCHEMA_VERSION = "experiment_design_brief.v1"
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ExperimentDesignBrief:
    schema_version: str
    topic_id: int
    opportunity_id: str
    support_level: str
    abstract_challenge: str
    hypothesis: str
    target_task: str
    target_data_slice: str
    baselines: tuple[str, ...]
    metrics: tuple[str, ...]
    ablations: tuple[str, ...]
    failure_slices: tuple[str, ...]
    stress_tests: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...]
    field_provenance: dict[str, str] = field(default_factory=dict)
    canonical_components: tuple[str, ...] = ()
    repeats: int = 0


def build_experiment_design_brief_from_report(
    report: InnovationOpportunityReport,
    *,
    opportunity_id: str = "",
    target_task: str = "",
    repeats: int = 0,
) -> ExperimentDesignBrief:
    """Select an opportunity from a report and build a validation brief."""

    opportunity = _select_opportunity(report, opportunity_id)
    return build_experiment_design_brief(
        opportunity=opportunity,
        topic_id=report.topic_id,
        target_task=target_task,
        repeats=repeats,
    )


def build_experiment_design_brief(
    *,
    opportunity: InnovationOpportunity,
    topic_id: int,
    target_task: str = "",
    repeats: int = 0,
) -> ExperimentDesignBrief:
    """Build a private ``experiment_design_brief.v1``."""

    if type(repeats) is not int or repeats < 0:
        raise ValueError("repeats must be a non-negative integer")

    terms = _opportunity_terms(opportunity)
    inferred_task = target_task or _target_task(opportunity, terms)
    target_data_slice = _target_data_slice(opportunity, terms)
    baselines = _baselines(opportunity)
    metrics = _metrics(opportunity, terms)
    ablations = _ablations(opportunity)
    failure_slices = _failure_slices(opportunity, terms)
    stress_tests = _stress_tests(opportunity, terms)
    warnings = _warnings(
        opportunity=opportunity,
        target_data_slice=target_data_slice,
        baselines=baselines,
        metrics=metrics,
        repeats=repeats,
    )

    return ExperimentDesignBrief(
        schema_version=EXPERIMENT_DESIGN_BRIEF_SCHEMA_VERSION,
        topic_id=topic_id,
        opportunity_id=opportunity.opportunity_id,
        support_level=opportunity.support_level,
        abstract_challenge=opportunity.abstract_challenge,
        hypothesis=opportunity.testable_hypothesis,
        target_task=inferred_task,
        target_data_slice=target_data_slice,
        baselines=baselines,
        metrics=metrics,
        ablations=ablations,
        failure_slices=failure_slices,
        stress_tests=stress_tests,
        expected_outputs=_expected_outputs(opportunity, metrics),
        acceptance_criteria=_acceptance_criteria(opportunity, metrics),
        warnings=warnings,
        evidence_anchors=opportunity.evidence_anchors,
        canonical_components=ablations,
        repeats=repeats,
        field_provenance=_field_provenance(
            opportunity=opportunity,
            target_task=target_task,
            inferred_task=inferred_task,
            target_data_slice=target_data_slice,
            baselines=baselines,
            metrics=metrics,
            repeats=repeats,
        ),
    )


def experiment_design_brief_to_dict(
    brief: ExperimentDesignBrief,
) -> dict[str, Any]:
    """Serialize an experiment design brief into deterministic plain data."""

    return {
        "artifact_role": "advisory_compiled_view",
        "schema_version": brief.schema_version,
        "topic_id": brief.topic_id,
        "opportunity_id": brief.opportunity_id,
        "support_level": brief.support_level,
        "abstract_challenge": brief.abstract_challenge,
        "hypothesis": brief.hypothesis,
        "target_task": brief.target_task,
        "target_data_slice": brief.target_data_slice,
        "baselines": list(brief.baselines),
        "metrics": list(brief.metrics),
        "canonical_components": list(brief.canonical_components),
        "ablations": list(brief.ablations),
        "repeats": brief.repeats,
        "failure_slices": list(brief.failure_slices),
        "stress_tests": list(brief.stress_tests),
        "expected_outputs": list(brief.expected_outputs),
        "acceptance_criteria": list(brief.acceptance_criteria),
        "warnings": list(brief.warnings),
        "field_provenance": dict(brief.field_provenance),
        "evidence_anchors": [
            _evidence_anchor_to_dict(anchor) for anchor in brief.evidence_anchors
        ],
    }


def render_experiment_design_brief_markdown(
    brief: ExperimentDesignBrief,
) -> str:
    """Render a concise deterministic Markdown brief."""

    lines = [
        "# Experiment Design Brief",
        "",
        f"- Topic id: {brief.topic_id}",
        f"- Opportunity id: {brief.opportunity_id}",
        f"- Support: {brief.support_level}",
        f"- Hypothesis: {brief.hypothesis}",
        f"- Target task: {brief.target_task}",
        f"- Target data slice: {brief.target_data_slice}",
        f"- Repeats: {brief.repeats}",
        "",
    ]
    _append_section(lines, "Baselines", brief.baselines)
    _append_section(lines, "Metrics", brief.metrics)
    _append_section(lines, "Canonical components", brief.canonical_components)
    _append_section(lines, "Ablations", brief.ablations)
    _append_section(lines, "Failure slices", brief.failure_slices)
    _append_section(lines, "Stress tests", brief.stress_tests)
    _append_section(lines, "Expected outputs", brief.expected_outputs)
    _append_section(lines, "Acceptance criteria", brief.acceptance_criteria)
    if brief.warnings:
        _append_section(lines, "Warnings", brief.warnings)
    return "\n".join(lines).rstrip() + "\n"


def _select_opportunity(
    report: InnovationOpportunityReport,
    opportunity_id: str,
) -> InnovationOpportunity:
    if not report.opportunities:
        raise ValueError("innovation opportunity report has no opportunities")
    if not opportunity_id:
        return report.opportunities[0]
    for opportunity in report.opportunities:
        if opportunity.opportunity_id == opportunity_id:
            return opportunity
    raise ValueError(f"opportunity not found: {opportunity_id}")


def _opportunity_terms(opportunity: InnovationOpportunity) -> set[str]:
    text = " ".join(
        (
            opportunity.anchor_observation,
            opportunity.observed_problem,
            opportunity.abstract_challenge,
            opportunity.transfer_mechanism,
            opportunity.proposed_storyline,
            " ".join(opportunity.in_domain_context),
        )
    )
    return set(_WORD_RE.findall(text.lower()))


def _target_task(
    opportunity: InnovationOpportunity,
    terms: set[str],
) -> str:
    if opportunity.support_level == "speculative":
        return "manual validation required"
    if {"literature", "synthesis"} & terms:
        return "literature agent synthesis"
    if {"retrieval", "reranking", "recall"} & terms:
        return "paper retrieval and reranking"
    if {"agent", "memory"} <= terms:
        return "manual validation required"
    return "target task inferred from opportunity"


def _target_data_slice(
    opportunity: InnovationOpportunity,
    terms: set[str],
) -> str:
    if opportunity.support_level == "speculative" and not opportunity.evidence_anchors:
        return "unsupported data slice"
    if {"source", "provenance", "synthesis"} & terms:
        return "multi-step synthesis cases with source links"
    if {"recall", "retrieval", "reranking"} & terms:
        return "retrieval queries with judged relevance and failure cases"
    return "evidence-linked validation slice"


def _baselines(opportunity: InnovationOpportunity) -> tuple[str, ...]:
    if not opportunity.evidence_anchors and opportunity.support_level == "speculative":
        return ()

    baselines: list[str] = []
    context_text = _baseline_context_text(opportunity)
    normalized_context = context_text.lower()
    if "bm25" in normalized_context:
        baselines.append("BM25")
    if "current reranker" in normalized_context or "reranker baseline" in (
        normalized_context
    ):
        baselines.append("current reranker")
    if "current synthesis baseline" in normalized_context:
        baselines.append("current synthesis baseline")
    return tuple(dict.fromkeys(baselines))


def _baseline_context_text(opportunity: InnovationOpportunity) -> str:
    return " ".join(
        tuple(opportunity.in_domain_context)
        + tuple(anchor.evidence_snippet for anchor in opportunity.evidence_anchors)
    )


def _metrics(
    opportunity: InnovationOpportunity,
    terms: set[str],
) -> tuple[str, ...]:
    if opportunity.support_level == "speculative" and not opportunity.evidence_anchors:
        return ("human-verified success rate",)

    metrics: list[str] = []
    if {"source", "provenance", "checkpoint"} & terms:
        metrics.append("source-link retention")
        metrics.append("evidence-anchor resolvability")
    if {"recall", "retrieval", "reranking"} & terms:
        metrics.append("recall@k")
    if {"drift", "failure"} & terms:
        metrics.append("failure-rate reduction")
    if not metrics:
        metrics.append("task success rate")
    return tuple(dict.fromkeys(metrics))


def _ablations(opportunity: InnovationOpportunity) -> tuple[str, ...]:
    mechanism = opportunity.transfer_mechanism
    if "checkpoint ledger" in mechanism or "source-hash checkpoint" in mechanism:
        return (
            "remove source-hash checkpoint ledger",
            "replace source hashes with unverified source labels",
        )
    if opportunity.cross_domain_analogies:
        return (
            "remove transferred cross-domain mechanism",
            "use in-domain-only variant",
        )
    return ("remove proposed mechanism",)


def _failure_slices(
    opportunity: InnovationOpportunity,
    terms: set[str],
) -> tuple[str, ...]:
    slices: list[str] = []
    if {"long", "multi", "synthesis"} & terms:
        slices.append("long synthesis chains")
    if {"source", "provenance"} & terms:
        slices.append("ambiguous or conflicting source evidence")
    if {"recall", "retrieval", "reranker"} & terms:
        slices.append("tail queries and hard negatives")
    if not slices:
        slices.append("low-support examples")
    return tuple(dict.fromkeys(slices))


def _stress_tests(
    opportunity: InnovationOpportunity,
    terms: set[str],
) -> tuple[str, ...]:
    tests: list[str] = []
    if {"source", "provenance"} & terms:
        tests.append("source-order perturbation")
        tests.append("missing-source perturbation")
    if {"recall", "retrieval", "reranker"} & terms:
        tests.append("query distribution shift")
    if opportunity.support_level != "evidence_bound":
        tests.append("small evidence-pool sensitivity check")
    if not tests:
        tests.append("held-out validation slice")
    return tuple(dict.fromkeys(tests))


def _expected_outputs(
    opportunity: InnovationOpportunity,
    metrics: tuple[str, ...],
) -> tuple[str, ...]:
    if "source-link retention" in metrics:
        return (
            "table: baseline vs checkpointed provenance metrics",
            "figure: source-link retention by synthesis depth",
        )
    if "recall@k" in metrics:
        return (
            "table: baseline vs proposed method retrieval metrics",
            "figure: recall@k by query slice",
        )
    if opportunity.support_level == "speculative":
        return ("table: manual validation outcomes",)
    return ("table: baseline vs proposed validation metrics",)


def _acceptance_criteria(
    opportunity: InnovationOpportunity,
    metrics: tuple[str, ...],
) -> tuple[str, ...]:
    criteria: list[str] = []
    if "source-link retention" in metrics:
        criteria.append(
            "source-link retention improves without reducing answer correctness"
        )
    if "evidence-anchor resolvability" in metrics:
        criteria.append("evidence-anchor resolvability improves on held-out cases")
    if "recall@k" in metrics:
        criteria.append("recall@k improves against the selected baseline")
    if opportunity.support_level != "evidence_bound":
        criteria.append("manual review confirms the opportunity is not spurious")
    if not criteria:
        criteria.append("primary metric improves on the target data slice")
    return tuple(dict.fromkeys(criteria))


def _warnings(
    *,
    opportunity: InnovationOpportunity,
    target_data_slice: str,
    baselines: tuple[str, ...],
    metrics: tuple[str, ...],
    repeats: int,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if not baselines:
        warnings.append("missing_baselines")
    if not baselines and opportunity.evidence_anchors:
        warnings.append("baseline_evidence_missing")
    if metrics == ("human-verified success rate",):
        warnings.append("weak_metrics")
    if target_data_slice == "unsupported data slice":
        warnings.append("unsupported_dataset")
    if opportunity.support_level != "evidence_bound":
        warnings.append("weak_or_speculative_opportunity")
    if not opportunity.evidence_anchors:
        warnings.append("evidence_anchor_missing")
    if repeats == 0:
        warnings.append("missing_repeats")
    if "leakage" in " ".join(opportunity.novelty_risks).lower():
        warnings.append("evaluation_leakage_risk")
    return tuple(dict.fromkeys(warnings))


def _field_provenance(
    *,
    opportunity: InnovationOpportunity,
    target_task: str,
    inferred_task: str,
    target_data_slice: str,
    baselines: tuple[str, ...],
    metrics: tuple[str, ...],
    repeats: int,
) -> dict[str, str]:
    if target_task:
        task_source = "user_supplied"
    elif inferred_task == "manual validation required":
        task_source = "manual_validation_required"
    else:
        task_source = "heuristic_from_opportunity_terms"

    if target_data_slice == "unsupported data slice":
        data_slice_source = "unsupported_without_evidence"
    else:
        data_slice_source = "heuristic_from_opportunity_terms"

    if baselines:
        baseline_source = "evidence_anchored_from_in_domain_context"
    else:
        baseline_source = "none"

    if metrics == ("human-verified success rate",):
        metric_source = "manual_review_fallback"
    else:
        metric_source = "heuristic_from_opportunity_terms"

    return {
        "target_task": task_source,
        "target_data_slice": data_slice_source,
        "baselines": baseline_source,
        "metrics": metric_source,
        "canonical_components": "derived_from_ablations",
        "ablations": "derived_from_transfer_mechanism",
        "repeats": "user_supplied" if repeats else "default_missing",
        "failure_slices": "heuristic_from_opportunity_terms",
        "stress_tests": "heuristic_from_opportunity_terms",
        "expected_outputs": "derived_from_metrics",
        "acceptance_criteria": "derived_from_metrics",
    }


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
