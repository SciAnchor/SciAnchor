from __future__ import annotations

import pytest

from research_harness.knowledge.innovation_opportunity import (
    CrossDomainAnalogy,
    InnovationOpportunity,
    InnovationOpportunityReport,
)
from research_harness.knowledge.research_wiki_insights import (
    ResearchWikiEvidenceAnchor,
)


def _anchor(
    *,
    source_id: str = "card-11",
    source_type: str = "paperindex_card",
    source_hash: str = "hash-11",
    evidence_snippet: str = "Long literature agents lose evidence provenance.",
) -> ResearchWikiEvidenceAnchor:
    return ResearchWikiEvidenceAnchor(
        page_path="findings/evidence-provenance-drift.md",
        paper_id=11,
        source_type=source_type,
        source_id=source_id,
        source_hash=source_hash,
        section_anchor="results",
        evidence_snippet=evidence_snippet,
    )


def _opportunity(
    *,
    support_level: str = "evidence_bound",
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...] = (_anchor(),),
    in_domain_context: tuple[str, ...] = (
        "Long literature agents lose evidence provenance.",
        "Current reranking keeps recall but loses source links.",
        "BM25 baseline reports recall@20 on ORB.",
    ),
    novelty_risks: tuple[str, ...] = (
        "cross-domain analogy is inspiration, not proof of novelty",
    ),
) -> InnovationOpportunity:
    return InnovationOpportunity(
        opportunity_id="topic-2-opportunity-1",
        support_level=support_level,
        anchor_observation="Evidence provenance drift",
        observed_problem=(
            "Long literature agents lose evidence provenance across multi-step "
            "synthesis."
        ),
        abstract_challenge="provenance_control",
        in_domain_context=in_domain_context,
        cross_domain_analogies=(
            CrossDomainAnalogy(
                link_type="method_transfers_to_gap",
                source_topic_id=1,
                target_topic_id=2,
                score=0.86,
                source_label="source-hash checkpoint ledger",
                target_label="evidence provenance drift in long literature agent runs",
                shared_abstractions=("provenance_control",),
                transfer_mechanism=(
                    "transfer provenance_control from source-hash checkpoint "
                    "ledger to evidence provenance drift"
                ),
                evidence_summary=("Ledger checkpoints bind hashes.",),
                warnings=(),
            ),
        ),
        transfer_mechanism=(
            "transfer provenance_control from source-hash checkpoint ledger "
            "to evidence provenance drift"
        ),
        proposed_storyline=(
            "Evidence provenance drift exposes provenance_control; a checkpoint "
            "ledger may preserve source links through synthesis."
        ),
        testable_hypothesis=(
            "If provenance_control is addressed by source-hash checkpoints, "
            "then source-link loss should decrease."
        ),
        novelty_risks=novelty_risks,
        evidence_anchors=evidence_anchors,
    )


def _report(opportunity: InnovationOpportunity) -> InnovationOpportunityReport:
    return InnovationOpportunityReport(
        schema_version="innovation_opportunity_report.v1",
        topic_id=2,
        query="evidence provenance drift",
        anchor_paper_id=None,
        opportunities=(opportunity,),
        warnings=(),
    )


def test_experiment_design_brief_builds_falsifiable_validation_plan() -> None:
    from research_harness.knowledge.experiment_design import (
        build_experiment_design_brief,
        experiment_design_brief_to_dict,
        render_experiment_design_brief_markdown,
    )

    opportunity = _opportunity()
    brief = build_experiment_design_brief(
        opportunity=opportunity,
        topic_id=2,
        target_task="literature agent synthesis",
        repeats=3,
    )

    assert brief.schema_version == "experiment_design_brief.v1"
    assert brief.topic_id == 2
    assert brief.opportunity_id == "topic-2-opportunity-1"
    assert brief.hypothesis == opportunity.testable_hypothesis
    assert brief.target_task == "literature agent synthesis"
    assert brief.target_data_slice == "multi-step synthesis cases with source links"
    assert "BM25" in brief.baselines
    assert "source-link retention" in brief.metrics
    assert "remove source-hash checkpoint ledger" in brief.ablations
    assert brief.canonical_components == brief.ablations
    assert brief.repeats == 3
    assert "long synthesis chains" in brief.failure_slices
    assert "source-order perturbation" in brief.stress_tests
    assert "source-link retention improves" in brief.acceptance_criteria[0]
    assert brief.expected_outputs == (
        "table: baseline vs checkpointed provenance metrics",
        "figure: source-link retention by synthesis depth",
    )
    assert brief.field_provenance == {
        "target_task": "user_supplied",
        "target_data_slice": "heuristic_from_opportunity_terms",
        "baselines": "evidence_anchored_from_in_domain_context",
        "metrics": "heuristic_from_opportunity_terms",
        "canonical_components": "derived_from_ablations",
        "ablations": "derived_from_transfer_mechanism",
        "repeats": "user_supplied",
        "failure_slices": "heuristic_from_opportunity_terms",
        "stress_tests": "heuristic_from_opportunity_terms",
        "expected_outputs": "derived_from_metrics",
        "acceptance_criteria": "derived_from_metrics",
    }
    assert [anchor.source_id for anchor in brief.evidence_anchors] == ["card-11"]
    assert brief.warnings == ()

    data = experiment_design_brief_to_dict(brief)
    assert data["schema_version"] == "experiment_design_brief.v1"
    assert data["artifact_role"] == "advisory_compiled_view"
    assert data["field_provenance"]["target_task"] == "user_supplied"
    assert data["canonical_components"] == list(brief.ablations)
    assert data["repeats"] == 3
    assert data["evidence_anchors"][0]["source_hash"] == "hash-11"
    assert "training_script" not in repr(data)
    assert "hyperparameter" not in repr(data)

    markdown = render_experiment_design_brief_markdown(brief)
    assert "# Experiment Design Brief" in markdown
    assert "Acceptance criteria" in markdown
    assert "Canonical components" in markdown
    assert "Repeats: 3" in markdown
    assert "source-link retention improves" in markdown


def test_experiment_design_brief_flags_missing_baselines_and_weak_metrics() -> None:
    from research_harness.knowledge.experiment_design import (
        build_experiment_design_brief,
    )

    opportunity = _opportunity(
        support_level="speculative",
        evidence_anchors=(),
        in_domain_context=("Agent memory might help synthesis.",),
        novelty_risks=("insufficient evidence anchors",),
    )

    brief = build_experiment_design_brief(
        opportunity=opportunity,
        topic_id=2,
    )

    assert "missing_baselines" in brief.warnings
    assert "weak_metrics" in brief.warnings
    assert "unsupported_dataset" in brief.warnings
    assert "weak_or_speculative_opportunity" in brief.warnings
    assert "evidence_anchor_missing" in brief.warnings
    assert "missing_repeats" in brief.warnings
    assert brief.field_provenance["target_task"] == "manual_validation_required"
    assert brief.field_provenance["target_data_slice"] == "unsupported_without_evidence"
    assert brief.field_provenance["baselines"] == "none"
    assert brief.field_provenance["metrics"] == "manual_review_fallback"
    assert brief.target_task == "manual validation required"
    assert brief.target_data_slice == "unsupported data slice"
    assert brief.baselines == ()
    assert brief.metrics == ("human-verified success rate",)


def test_experiment_design_brief_can_select_from_report_by_opportunity_id() -> None:
    from research_harness.knowledge.experiment_design import (
        build_experiment_design_brief_from_report,
    )

    first = _opportunity()
    second = _opportunity(
        support_level="weakly_supported",
        evidence_anchors=(_anchor(source_id="gap-22", source_hash="hash-22"),),
    )
    second = InnovationOpportunity(
        **{
            **second.__dict__,
            "opportunity_id": "topic-2-opportunity-2",
            "anchor_observation": "Recall validation gap",
            "abstract_challenge": "evaluation_bridge",
            "testable_hypothesis": (
                "If evaluation_bridge is improved, recall drift should decrease."
            ),
        }
    )
    report = InnovationOpportunityReport(
        schema_version="innovation_opportunity_report.v1",
        topic_id=2,
        query="validation",
        anchor_paper_id=None,
        opportunities=(first, second),
        warnings=(),
    )

    brief = build_experiment_design_brief_from_report(
        report,
        opportunity_id="topic-2-opportunity-2",
    )

    assert brief.opportunity_id == "topic-2-opportunity-2"
    assert brief.abstract_challenge == "evaluation_bridge"
    assert "recall@k" in brief.metrics


def test_experiment_design_brief_does_not_invent_unsupported_baseline() -> None:
    from research_harness.knowledge.experiment_design import (
        build_experiment_design_brief,
    )

    opportunity = _opportunity(
        in_domain_context=(
            "Evidence anchors show provenance drift in synthesis.",
            "No paper card names a baseline method.",
        ),
    )

    brief = build_experiment_design_brief(
        opportunity=opportunity,
        topic_id=2,
    )

    assert "current best in-domain method" not in brief.baselines
    assert "current synthesis without source-hash checkpoints" not in brief.baselines
    assert brief.baselines == ()
    assert "missing_baselines" in brief.warnings
    assert "baseline_evidence_missing" in brief.warnings
    assert brief.field_provenance["baselines"] == "none"
    assert brief.evidence_anchors == opportunity.evidence_anchors


@pytest.mark.parametrize("repeats", [-1, 1.5, True])
def test_experiment_design_brief_rejects_invalid_repeats(repeats: object) -> None:
    from research_harness.knowledge.experiment_design import (
        build_experiment_design_brief,
    )

    with pytest.raises(ValueError, match="non-negative integer"):
        build_experiment_design_brief(
            opportunity=_opportunity(),
            topic_id=2,
            repeats=repeats,  # type: ignore[arg-type]
        )
