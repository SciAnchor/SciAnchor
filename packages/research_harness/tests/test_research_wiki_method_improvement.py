from __future__ import annotations

from research_harness.knowledge.cross_topic_atlas import (
    CROSS_TOPIC_KNOWLEDGE_ATLAS_SCHEMA_VERSION,
    CrossTopicKnowledgeAtlas,
    CrossTopicKnowledgeLink,
)
from research_harness.knowledge.experiment_design import ExperimentDesignBrief
from research_harness.knowledge.research_wiki_insights import (
    ResearchWikiEvidenceAnchor,
)
from research_harness.knowledge.wiki_context_pack import (
    WIKI_CONTEXT_PACK_SCHEMA_VERSION,
    WikiContextPack,
    WikiContextPackWarning,
    WikiContextPage,
)


def _anchor(
    *,
    page_path: str = "findings/evidence-provenance-drift.md",
    paper_id: int | None = 11,
    source_type: str = "paperindex_card",
    source_id: str = "card-11",
    source_hash: str = "hash-11",
    section_anchor: str = "results",
    evidence_snippet: str = "Long literature agents lose evidence provenance.",
) -> ResearchWikiEvidenceAnchor:
    return ResearchWikiEvidenceAnchor(
        page_path=page_path,
        paper_id=paper_id,
        source_type=source_type,
        source_id=source_id,
        source_hash=source_hash,
        section_anchor=section_anchor,
        evidence_snippet=evidence_snippet,
    )


def _brief(
    *,
    support_level: str = "evidence_bound",
    baselines: tuple[str, ...] = ("BM25",),
    metrics: tuple[str, ...] = (
        "source-link retention",
        "evidence-anchor resolvability",
    ),
    warnings: tuple[str, ...] = (),
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...] = (_anchor(),),
) -> ExperimentDesignBrief:
    return ExperimentDesignBrief(
        schema_version="experiment_design_brief.v1",
        topic_id=2,
        opportunity_id="topic-2-opportunity-1",
        support_level=support_level,
        abstract_challenge="provenance_control",
        hypothesis=(
            "If provenance_control is addressed by source-hash checkpoints, "
            "then source-link loss should decrease."
        ),
        target_task="literature agent synthesis",
        target_data_slice="multi-step synthesis cases with source links",
        baselines=baselines,
        metrics=metrics,
        ablations=("remove source-hash checkpoint ledger",),
        failure_slices=("long synthesis chains",),
        stress_tests=("source-order perturbation",),
        expected_outputs=("table: baseline vs checkpointed provenance metrics",),
        acceptance_criteria=(
            "source-link retention improves without reducing answer correctness",
        ),
        warnings=warnings,
        evidence_anchors=evidence_anchors,
        field_provenance={
            "target_task": "user_supplied",
            "baselines": "evidence_anchored_from_in_domain_context",
            "metrics": "heuristic_from_opportunity_terms",
        },
    )


def _context_pack(
    *,
    warnings: tuple[WikiContextPackWarning, ...] = (),
    anchors: tuple[ResearchWikiEvidenceAnchor, ...] = (
        _anchor(
            page_path="methodology/evidence-anchor-verifier.md",
            source_id="claim-21",
            source_hash="hash-21",
            source_type="normalized_claims",
            evidence_snippet=(
                "A verifier checks evidence anchors against source hashes and "
                "rejects unsupported synthesis."
            ),
        ),
    ),
) -> WikiContextPack:
    pages = (
        WikiContextPage(
            page_path="methodology/evidence-anchor-verifier.md",
            title="Evidence anchor verifier",
            page_type="methodology",
            status="ready",
            score=0.92,
            matched_terms=("evidence", "anchor", "verifier"),
            selection_reason="query_match",
            excerpt=(
                "A verifier checks evidence anchors against source hashes and "
                "rejects unsupported synthesis."
            ),
            source_hashes=tuple(anchor.source_hash for anchor in anchors),
            evidence_anchors=anchors,
        ),
    )
    return WikiContextPack(
        schema_version=WIKI_CONTEXT_PACK_SCHEMA_VERSION,
        topic_id=2,
        query="evidence provenance failure verifier",
        action_name="method_improvement",
        anchor_paper_id=None,
        pages=pages,
        warnings=warnings,
        degraded=bool(warnings),
        source_diversity={
            "paper_count": len({anchor.paper_id for anchor in anchors}),
            "source_hash_count": len({anchor.source_hash for anchor in anchors}),
            "source_type_count": len({anchor.source_type for anchor in anchors}),
        },
        evidence_anchor_count=len(anchors),
        truncated=False,
        truncation={"omitted_anchor_count": 0, "omitted_page_count": 0},
    )


def _atlas(
    *,
    warnings: tuple[str, ...] = (),
    score: float = 0.84,
) -> CrossTopicKnowledgeAtlas:
    return CrossTopicKnowledgeAtlas(
        schema_version=CROSS_TOPIC_KNOWLEDGE_ATLAS_SCHEMA_VERSION,
        topic_ids=(1, 2),
        links=(
            CrossTopicKnowledgeLink(
                link_type="method_transfers_to_gap",
                source_topic_id=1,
                target_topic_id=2,
                score=score,
                source_label="source-hash verifier gate",
                target_label="evidence provenance drift in long literature runs",
                explanation=(
                    "Verifier gates from audit workflows may transfer to "
                    "evidence provenance drift. Shared abstraction(s): "
                    "provenance_control."
                ),
                evidence_summary=(
                    "topic 1 `methods/source-hash-verifier.md` claim-21: verifier gate",
                    "topic 2 `findings/evidence-provenance-drift.md` card-11: drift",
                ),
                source_ids=("claim-21", "card-11"),
                warnings=warnings,
                metadata={"shared_abstractions": ["provenance_control"]},
            ),
        ),
        warnings=(),
    )


def test_method_improvement_report_recommends_evidence_backed_verifier() -> None:
    from research_harness.knowledge.method_improvement import (
        build_method_improvement_report,
        method_improvement_report_to_dict,
        render_method_improvement_report_markdown,
    )

    report = build_method_improvement_report(
        brief=_brief(),
        context_pack=_context_pack(),
        atlas=_atlas(),
        method_name="checkpointed literature synthesis",
        observed_failures=(
            "source-link retention fell below BM25 on long synthesis chains",
            "evidence anchors became unresolved after source-order perturbation",
        ),
        ablation_notes=(
            "Removing the checkpoint ledger worsened evidence-anchor resolvability.",
        ),
        review_feedback=(
            "Reviewer asks for a stricter verifier before claiming provenance control.",
        ),
    )

    assert report.schema_version == "method_improvement_report.v1"
    assert report.artifact_role == "advisory_compiled_view"
    assert report.support_level == "evidence_bound"
    assert report.failure_diagnoses[0].failure_pattern == ("provenance_control_failure")
    assert report.failure_diagnoses[0].abstract_failure_pattern == (
        "provenance_control"
    )

    recommendation = report.recommendations[0]
    assert recommendation.modification_type == "verifier_or_critic_addition"
    assert recommendation.support_level == "evidence_bound"
    assert "source-hash verifier gate" in recommendation.recommended_change
    assert "provenance_control" in recommendation.transfer_explanation
    assert "falsify" in recommendation.falsification_test.lower()
    assert recommendation.field_provenance["recommended_change"] == (
        "evidence_context_and_cross_domain_link"
    )
    assert [anchor.source_id for anchor in recommendation.evidence_anchors] == [
        "card-11",
        "claim-21",
    ]

    data = method_improvement_report_to_dict(report)
    assert data["artifact_role"] == "advisory_compiled_view"
    assert data["recommendations"][0]["remedy_candidates"][0]["score"] == 0.84
    assert data["field_provenance"]["failure_diagnoses"] == (
        "observed_failures_and_experiment_brief"
    )
    assert "vault_path" not in repr(data)

    markdown = render_method_improvement_report_markdown(report)
    assert "# Method Improvement Report" in markdown
    assert "verifier_or_critic_addition" in markdown
    assert "Validation plan" in markdown


def test_method_improvement_report_downshifts_warned_cross_domain_remedy() -> None:
    from research_harness.knowledge.method_improvement import (
        build_method_improvement_report,
    )

    report = build_method_improvement_report(
        brief=_brief(),
        context_pack=_context_pack(),
        atlas=_atlas(warnings=("incompatible_task_context",), score=0.42),
        observed_failures=("source-link retention still drifts.",),
    )

    recommendation = report.recommendations[0]
    assert recommendation.support_level == "weakly_supported"
    assert "incompatible_task_context" in recommendation.warnings
    assert "cross_domain_remedy_weak_or_warned" in report.warnings
    assert report.support_level == "weakly_supported"


def test_method_improvement_report_requires_more_evidence_when_unsupported() -> None:
    from research_harness.knowledge.method_improvement import (
        build_method_improvement_report,
    )

    report = build_method_improvement_report(
        brief=_brief(
            support_level="speculative",
            baselines=(),
            metrics=("human-verified success rate",),
            warnings=("missing_baselines", "weak_metrics"),
            evidence_anchors=(),
        ),
        context_pack=_context_pack(
            warnings=(
                WikiContextPackWarning(
                    code="broad_fallback_context",
                    severity="warning",
                    page_path="",
                    message="broad advisory context",
                ),
            ),
            anchors=(),
        ),
        atlas=None,
        observed_failures=("The method is not clearly better in manual review.",),
    )

    assert report.support_level == "speculative"
    assert "evidence_anchor_missing" in report.warnings
    assert "weak_or_speculative_brief" in report.warnings
    assert report.recommendations[0].modification_type == ("evaluation_protocol_change")
    assert report.recommendations[0].recommended_change == (
        "collect evidence, baselines, and failure cases before changing the method"
    )
    assert report.recommendations[0].evidence_anchors == ()
    assert report.recommendations[0].field_provenance["recommended_change"] == (
        "unsupported_manual_review_fallback"
    )
