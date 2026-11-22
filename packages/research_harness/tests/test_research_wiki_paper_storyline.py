from __future__ import annotations

from research_harness.knowledge.experiment_design import ExperimentDesignBrief
from research_harness.knowledge.innovation_opportunity import (
    CrossDomainAnalogy,
    InnovationOpportunity,
    InnovationOpportunityReport,
)
from research_harness.knowledge.method_improvement import (
    FailureDiagnosis,
    MethodImprovementRecommendation,
    MethodImprovementReport,
    RemedyCandidate,
)
from research_harness.knowledge.research_wiki_insights import (
    ResearchWikiEvidenceAnchor,
)
from research_harness.knowledge.wiki_context_pack import (
    WIKI_CONTEXT_PACK_SCHEMA_VERSION,
    WikiContextPack,
    WikiContextPage,
)


def _anchor(
    *,
    page_path: str = "findings/evidence-provenance-drift.md",
    source_id: str = "card-11",
    source_hash: str = "hash-11",
    evidence_snippet: str = "Long literature agents lose evidence provenance.",
) -> ResearchWikiEvidenceAnchor:
    return ResearchWikiEvidenceAnchor(
        page_path=page_path,
        paper_id=11,
        source_type="paperindex_card",
        source_id=source_id,
        source_hash=source_hash,
        section_anchor="results",
        evidence_snippet=evidence_snippet,
    )


def _context_pack() -> WikiContextPack:
    anchors = (
        _anchor(),
        _anchor(
            page_path="methodology/evidence-anchor-verifier.md",
            source_id="claim-21",
            source_hash="hash-21",
            evidence_snippet="Verifier gates keep source hashes resolvable.",
        ),
    )
    return WikiContextPack(
        schema_version=WIKI_CONTEXT_PACK_SCHEMA_VERSION,
        topic_id=2,
        query="evidence provenance paper writing",
        action_name="paper_writing",
        anchor_paper_id=None,
        pages=(
            WikiContextPage(
                page_path="findings/evidence-provenance-drift.md",
                title="Evidence provenance drift",
                page_type="finding",
                status="ready",
                score=0.9,
                matched_terms=("evidence", "provenance"),
                selection_reason="query_match",
                excerpt="Long literature agents lose evidence provenance.",
                source_hashes=("hash-11",),
                evidence_anchors=(anchors[0],),
            ),
            WikiContextPage(
                page_path="methodology/evidence-anchor-verifier.md",
                title="Evidence anchor verifier",
                page_type="methodology",
                status="ready",
                score=0.88,
                matched_terms=("evidence", "verifier"),
                selection_reason="query_match",
                excerpt="Verifier gates keep source hashes resolvable.",
                source_hashes=("hash-21",),
                evidence_anchors=(anchors[1],),
            ),
        ),
        warnings=(),
        degraded=False,
        source_diversity={
            "paper_count": 1,
            "source_hash_count": 2,
            "source_type_count": 1,
        },
        evidence_anchor_count=2,
        truncated=False,
        truncation={"omitted_anchor_count": 0, "omitted_page_count": 0},
    )


def _opportunity(
    *,
    support_level: str = "evidence_bound",
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...] = (_anchor(),),
) -> InnovationOpportunity:
    return InnovationOpportunity(
        opportunity_id="topic-2-opportunity-1",
        support_level=support_level,
        anchor_observation="Evidence provenance drift",
        observed_problem="Long literature agents lose evidence provenance.",
        abstract_challenge="provenance_control",
        in_domain_context=("Long literature agents lose evidence provenance.",),
        cross_domain_analogies=(
            CrossDomainAnalogy(
                link_type="method_transfers_to_gap",
                source_topic_id=1,
                target_topic_id=2,
                score=0.86,
                source_label="source-hash verifier gate",
                target_label="evidence provenance drift",
                shared_abstractions=("provenance_control",),
                transfer_mechanism=(
                    "transfer provenance_control from source-hash verifier gate "
                    "to evidence provenance drift"
                ),
                evidence_summary=("Verifier gates preserve source hashes.",),
                warnings=(),
            ),
        ),
        transfer_mechanism=(
            "transfer provenance_control from source-hash verifier gate "
            "to evidence provenance drift"
        ),
        proposed_storyline=(
            "Evidence provenance drift motivates verifier-gated synthesis."
        ),
        testable_hypothesis=(
            "If source-hash verifier gates address provenance_control, "
            "source-link retention should improve."
        ),
        novelty_risks=("cross-domain analogy is inspiration, not proof of novelty",),
        evidence_anchors=evidence_anchors,
        derivation={
            "proposed_storyline": "derived_advisory_synthesis",
            "testable_hypothesis": "derived_advisory_hypothesis",
        },
    )


def _opportunity_report(
    opportunity: InnovationOpportunity,
) -> InnovationOpportunityReport:
    return InnovationOpportunityReport(
        schema_version="innovation_opportunity_report.v1",
        topic_id=2,
        query="evidence provenance drift",
        anchor_paper_id=None,
        opportunities=(opportunity,),
        warnings=(),
    )


def _brief(
    *,
    support_level: str = "evidence_bound",
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...] = (_anchor(),),
) -> ExperimentDesignBrief:
    return ExperimentDesignBrief(
        schema_version="experiment_design_brief.v1",
        topic_id=2,
        opportunity_id="topic-2-opportunity-1",
        support_level=support_level,
        abstract_challenge="provenance_control",
        hypothesis=(
            "If source-hash verifier gates address provenance_control, "
            "source-link retention should improve."
        ),
        target_task="literature agent synthesis",
        target_data_slice="multi-step synthesis cases with source links",
        baselines=("BM25",),
        metrics=("source-link retention", "evidence-anchor resolvability"),
        ablations=("ablate verifier gate",),
        failure_slices=("long synthesis chains",),
        stress_tests=("source-order perturbation",),
        expected_outputs=("table: verifier-gated vs baseline provenance metrics",),
        acceptance_criteria=(
            "source-link retention improves without reducing answer correctness",
        ),
        warnings=(),
        evidence_anchors=evidence_anchors,
        field_provenance={"metrics": "heuristic_from_opportunity_terms"},
    )


def _method_report(
    *,
    support_level: str = "evidence_bound",
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...] = (_anchor(),),
) -> MethodImprovementReport:
    recommendation = MethodImprovementRecommendation(
        recommendation_id="method-improvement-1",
        modification_type="verifier_or_critic_addition",
        support_level=support_level,
        recommended_change=(
            "add a verifier/critic module inspired by source-hash verifier gate"
        ),
        transfer_explanation=(
            "source-hash verifier gate may transfer because both contexts share "
            "provenance_control"
        ),
        validation_plan=("ablate the verifier/critic module",),
        falsification_test=(
            "Falsify if source-link retention does not improve over BM25."
        ),
        risk_level="low",
        complexity="medium",
        remedy_candidates=(
            RemedyCandidate(
                link_type="method_transfers_to_gap",
                source_topic_id=1,
                target_topic_id=2,
                score=0.84,
                source_label="source-hash verifier gate",
                target_label="evidence provenance drift",
                shared_abstractions=("provenance_control",),
                evidence_summary=("Verifier gates preserve source hashes.",),
                warnings=(),
            ),
        ),
        warnings=("cross-domain remedy is inspiration, not proof of correctness",),
        evidence_anchors=evidence_anchors,
        field_provenance={
            "recommended_change": "evidence_context_and_cross_domain_link"
        },
    )
    return MethodImprovementReport(
        schema_version="method_improvement_report.v1",
        artifact_role="advisory_compiled_view",
        topic_id=2,
        opportunity_id="topic-2-opportunity-1",
        method_name="verifier-gated synthesis",
        support_level=support_level,
        failure_diagnoses=(
            FailureDiagnosis(
                failure_pattern="provenance_control_failure",
                abstract_failure_pattern="provenance_control",
                observed_failure="source links became unresolved",
                likely_causes=("evidence anchors are not checked",),
                implicated_metrics=("source-link retention",),
                evidence_anchors=evidence_anchors,
            ),
        ),
        recommendations=(recommendation,),
        warnings=(),
        evidence_anchors=evidence_anchors,
        field_provenance={
            "recommendations": "failure_diagnosis_context_pack_and_atlas"
        },
    )


def test_paper_storyline_graph_links_claims_to_evidence() -> None:
    from research_harness.knowledge.paper_storyline import (
        build_paper_storyline_graph,
        paper_storyline_graph_to_dict,
        render_paper_storyline_graph_markdown,
    )

    graph = build_paper_storyline_graph(
        context_pack=_context_pack(),
        opportunity_report=_opportunity_report(_opportunity()),
        experiment_brief=_brief(),
        method_report=_method_report(),
    )

    assert graph.schema_version == "paper_storyline_graph.v1"
    assert graph.artifact_role == "advisory_compiled_view"
    assert graph.topic_id == 2
    assert graph.claim_integrity["unsupported_claim_count"] == 0
    assert graph.claim_integrity["speculative_claim_count"] == 0
    assert graph.nodes_by_role("contribution_claim")

    contribution = graph.nodes_by_role("contribution_claim")[0]
    assert contribution.claim_status == "evidence_bound"
    assert contribution.evidence_anchors
    assert contribution.field_provenance["claim_status"] == (
        "support_level_and_evidence_anchors"
    )

    data = paper_storyline_graph_to_dict(graph)
    assert data["artifact_role"] == "advisory_compiled_view"
    assert data["claim_integrity"]["evidence_bound_claim_count"] >= 1
    assert data["section_packs"][0]["section_name"] == "introduction"
    assert "vault_path" not in repr(data)

    markdown = render_paper_storyline_graph_markdown(graph)
    assert "# Paper Storyline Graph" in markdown
    assert "Contribution claims" in markdown


def test_paper_storyline_marks_speculative_or_unanchored_claims() -> None:
    from research_harness.knowledge.paper_storyline import (
        build_paper_storyline_graph,
    )

    graph = build_paper_storyline_graph(
        context_pack=_context_pack(),
        opportunity_report=_opportunity_report(
            _opportunity(support_level="speculative", evidence_anchors=())
        ),
        experiment_brief=_brief(support_level="speculative", evidence_anchors=()),
        method_report=_method_report(support_level="speculative", evidence_anchors=()),
    )

    contribution = graph.nodes_by_role("contribution_claim")[0]
    assert contribution.claim_status == "unsupported"
    assert contribution.evidence_anchors == ()
    assert "unsupported_claims_present" in graph.warnings
    assert graph.claim_integrity["unsupported_claim_count"] >= 1


def test_section_evidence_packs_are_section_specific_and_claim_safe() -> None:
    from research_harness.knowledge.paper_storyline import (
        build_paper_storyline_graph,
        build_section_evidence_packs,
        section_evidence_packs_to_dict,
    )

    graph = build_paper_storyline_graph(
        context_pack=_context_pack(),
        opportunity_report=_opportunity_report(_opportunity()),
        experiment_brief=_brief(),
        method_report=_method_report(),
    )

    packs = build_section_evidence_packs(
        graph,
        section_names=("abstract", "method", "limitations"),
    )

    assert [pack.section_name for pack in packs] == [
        "abstract",
        "method",
        "limitations",
    ]
    assert all(pack.artifact_role == "advisory_compiled_view" for pack in packs)
    assert packs[0].required_claim_statuses == (
        "evidence_bound",
        "weakly_supported",
    )
    assert packs[1].nodes
    assert packs[2].nodes
    assert any(node.node_role == "limitation" for node in packs[2].nodes)

    data = section_evidence_packs_to_dict(packs)
    assert data[0]["section_name"] == "abstract"
    assert data[0]["required_claim_statuses"] == [
        "evidence_bound",
        "weakly_supported",
    ]
