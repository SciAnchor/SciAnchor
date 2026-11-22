from __future__ import annotations

from research_harness.knowledge.cross_topic_atlas import (
    CROSS_TOPIC_KNOWLEDGE_ATLAS_SCHEMA_VERSION,
    CrossTopicKnowledgeAtlas,
    CrossTopicKnowledgeLink,
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


def _context_pack(*pages: WikiContextPage) -> WikiContextPack:
    anchors = [anchor for page in pages for anchor in page.evidence_anchors]
    return WikiContextPack(
        schema_version=WIKI_CONTEXT_PACK_SCHEMA_VERSION,
        topic_id=2,
        query="evidence provenance drift",
        action_name="science_discovery",
        anchor_paper_id=None,
        pages=tuple(pages),
        warnings=(),
        degraded=False,
        source_diversity={
            "paper_count": len({anchor.paper_id for anchor in anchors}),
            "source_hash_count": len({anchor.source_hash for anchor in anchors}),
            "source_type_count": len({anchor.source_type for anchor in anchors}),
        },
        evidence_anchor_count=len(anchors),
        truncated=False,
        truncation={"omitted_anchor_count": 0, "omitted_page_count": 0},
    )


def _page(
    *,
    page_path: str,
    title: str,
    page_type: str,
    excerpt: str,
    anchors: tuple[ResearchWikiEvidenceAnchor, ...],
) -> WikiContextPage:
    return WikiContextPage(
        page_path=page_path,
        title=title,
        page_type=page_type,
        status="ready",
        score=0.91,
        matched_terms=("evidence", "provenance", "drift"),
        selection_reason="query_match",
        excerpt=excerpt,
        source_hashes=tuple(anchor.source_hash for anchor in anchors),
        evidence_anchors=anchors,
    )


def _atlas(*links: CrossTopicKnowledgeLink) -> CrossTopicKnowledgeAtlas:
    return CrossTopicKnowledgeAtlas(
        schema_version=CROSS_TOPIC_KNOWLEDGE_ATLAS_SCHEMA_VERSION,
        topic_ids=(1, 2),
        links=tuple(links),
        warnings=(),
    )


def _link(
    *,
    link_type: str = "method_transfers_to_gap",
    score: float = 0.86,
    source_label: str = "source-hash checkpoint ledger",
    target_label: str = "evidence provenance drift in long literature agent runs",
    warnings: tuple[str, ...] = (),
) -> CrossTopicKnowledgeLink:
    return CrossTopicKnowledgeLink(
        link_type=link_type,
        source_topic_id=1,
        target_topic_id=2,
        score=score,
        source_label=source_label,
        target_label=target_label,
        explanation=(
            "Method 'source-hash checkpoint ledger' from topic 1 may address "
            "gap 'evidence provenance drift in long literature agent runs' in "
            "topic 2. Shared abstraction(s): provenance_control."
        ),
        evidence_summary=(
            "topic 1 `methods/source-hash-checkpoint-ledger.md` "
            "topic_knowledge_snapshot:901: Ledger checkpoints bind hashes.",
            "topic 2 `gaps/evidence-provenance-drift.md` "
            "topic_knowledge_snapshot:902: Long agents lose provenance.",
        ),
        source_ids=("topic_knowledge_snapshot:901", "topic_knowledge_snapshot:902"),
        warnings=warnings,
        metadata={"shared_abstractions": ["provenance_control"]},
    )


def test_innovation_opportunity_report_builds_evidence_bound_storyline() -> None:
    from research_harness.knowledge.innovation_opportunity import (
        build_innovation_opportunity_report,
        innovation_opportunity_report_to_dict,
        render_innovation_opportunity_report_markdown,
    )

    context_pack = _context_pack(
        _page(
            page_path="findings/evidence-provenance-drift.md",
            title="Evidence provenance drift",
            page_type="finding",
            excerpt=(
                "Long literature agents lose evidence provenance across "
                "multi-step synthesis."
            ),
            anchors=(
                _anchor(),
                _anchor(
                    page_path="methodology/current-reranker.md",
                    source_id="claim-12",
                    source_hash="hash-12",
                    source_type="normalized_claims",
                    evidence_snippet="Current reranking keeps recall but loses source links.",
                ),
            ),
        )
    )
    atlas = _atlas(_link())

    report = build_innovation_opportunity_report(
        topic_id=2,
        context_pack=context_pack,
        atlas=atlas,
        query="evidence provenance drift",
        max_opportunities=1,
    )

    assert report.schema_version == "innovation_opportunity_report.v1"
    assert report.topic_id == 2
    assert report.query == "evidence provenance drift"
    assert report.opportunities

    opportunity = report.opportunities[0]
    assert opportunity.support_level == "evidence_bound"
    assert opportunity.anchor_observation == "Evidence provenance drift"
    assert (
        "Long literature agents lose evidence provenance"
        in opportunity.observed_problem
    )
    assert opportunity.abstract_challenge == "provenance_control"
    assert opportunity.cross_domain_analogies[0].source_topic_id == 1
    assert opportunity.cross_domain_analogies[0].transfer_mechanism == (
        "transfer provenance_control from source-hash checkpoint ledger "
        "to evidence provenance drift in long literature agent runs"
    )
    assert "not proof of novelty" in opportunity.novelty_risks[0]
    assert opportunity.testable_hypothesis.startswith("If provenance_control")
    assert opportunity.derivation == {
        "anchor_observation": "wiki_page_title",
        "observed_problem": "wiki_page_excerpt",
        "abstract_challenge": "cross_topic_shared_abstraction",
        "transfer_mechanism": "cross_topic_analogy",
        "proposed_storyline": "derived_advisory_synthesis",
        "testable_hypothesis": "derived_advisory_hypothesis",
    }
    assert [anchor.source_id for anchor in opportunity.evidence_anchors] == [
        "card-11",
        "claim-12",
    ]

    data = innovation_opportunity_report_to_dict(report)
    assert data["schema_version"] == "innovation_opportunity_report.v1"
    assert data["opportunities"][0]["support_level"] == "evidence_bound"
    assert data["opportunities"][0]["artifact_role"] == "advisory_compiled_view"
    assert data["opportunities"][0]["derivation"]["proposed_storyline"] == (
        "derived_advisory_synthesis"
    )
    assert data["opportunities"][0]["cross_domain_analogies"][0]["link_type"] == (
        "method_transfers_to_gap"
    )
    assert "vault_path" not in repr(data)

    markdown = render_innovation_opportunity_report_markdown(report)
    assert "# Innovation Opportunity Report" in markdown
    assert "Support: evidence_bound" in markdown
    assert "Novelty risks" in markdown


def test_innovation_opportunity_report_marks_unsupported_ideas_speculative() -> None:
    from research_harness.knowledge.innovation_opportunity import (
        build_innovation_opportunity_report,
    )

    context_pack = _context_pack(
        _page(
            page_path="concepts/agent-memory.md",
            title="Agent memory",
            page_type="concept",
            excerpt="Agent memory appears in notes without a specific gap.",
            anchors=(),
        )
    )

    report = build_innovation_opportunity_report(
        topic_id=2,
        context_pack=context_pack,
        atlas=_atlas(),
        query="agent memory",
        max_opportunities=1,
    )

    opportunity = report.opportunities[0]
    assert opportunity.support_level == "speculative"
    assert opportunity.cross_domain_analogies == ()
    assert opportunity.evidence_anchors == ()
    assert opportunity.derivation["observed_problem"] == "wiki_page_excerpt"
    assert opportunity.abstract_challenge == "under-specified_challenge"
    assert opportunity.derivation["abstract_challenge"] == (
        "default_unspecified_challenge"
    )
    assert "insufficient evidence anchors" in opportunity.novelty_risks


def test_innovation_opportunity_report_downshifts_weak_or_warned_analogies() -> None:
    from research_harness.knowledge.innovation_opportunity import (
        build_innovation_opportunity_report,
    )

    context_pack = _context_pack(
        _page(
            page_path="findings/graph-reranker-gap.md",
            title="Graph reranker validation gap",
            page_type="finding",
            excerpt="Graph reranker validation lacks transfer evidence.",
            anchors=(
                _anchor(
                    source_id="gap-21",
                    source_hash="hash-21",
                    evidence_snippet="Graph reranker validation lacks transfer evidence.",
                ),
            ),
        )
    )
    atlas = _atlas(
        _link(
            score=0.42,
            source_label="graph neural network reranker",
            target_label="graph neural network molecular validation gap",
            warnings=("incompatible_task_context",),
        )
    )

    report = build_innovation_opportunity_report(
        topic_id=2,
        context_pack=context_pack,
        atlas=atlas,
        query="graph reranker validation",
        max_opportunities=1,
    )

    opportunity = report.opportunities[0]
    assert opportunity.support_level == "weakly_supported"
    assert "incompatible_task_context" in opportunity.novelty_risks
    assert "not proof of novelty" in opportunity.novelty_risks[0]
