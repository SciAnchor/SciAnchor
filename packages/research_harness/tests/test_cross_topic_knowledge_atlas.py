from __future__ import annotations

import dataclasses
from pathlib import Path

from research_harness.knowledge.research_wiki import (
    ResearchWikiExport,
    ResearchWikiPage,
)
from research_harness.knowledge.topic_layer import TopicKnowledgeSnapshot


def test_cross_topic_atlas_discovers_method_transfer_to_gap() -> None:
    from research_harness.knowledge.cross_topic_atlas import (
        build_cross_topic_knowledge_atlas,
        rank_cross_topic_serendipity_links,
    )

    audit_topic = _snapshot(
        topic_id=1,
        artifact_id=901,
        covered={
            "methods": ["source-hash checkpoint ledger"],
            "claims": ["source-hash checkpoints reduce audit drift"],
            "datasets": ["audit ledgers"],
            "metrics": ["trace consistency"],
            "baselines": ["manual audit trail"],
            "tasks": ["financial audit automation"],
        },
    )
    literature_topic = _snapshot(
        topic_id=2,
        artifact_id=902,
        covered={
            "gaps": ["evidence provenance drift in long literature agent runs"],
            "tasks": ["literature agent orchestration"],
        },
        coverage={"gaps": 1, "semantic_atoms": 2},
    )

    atlas = build_cross_topic_knowledge_atlas(
        (audit_topic, literature_topic),
        wiki_exports=(
            _wiki(
                audit_topic,
                page_path="methods/source-hash-checkpoint-ledger.md",
                title="Source-hash checkpoint ledger",
                snippet="Ledger checkpoints bind source hashes to audit steps.",
            ),
            _wiki(
                literature_topic,
                page_path="gaps/evidence-provenance-drift.md",
                title="Evidence provenance drift",
                snippet="Long literature agents lose evidence provenance over time.",
            ),
        ),
    )
    ranked = rank_cross_topic_serendipity_links(atlas)

    assert ranked
    top = ranked[0]
    assert top.link_type == "method_transfers_to_gap"
    assert top.source_topic_id == 1
    assert top.target_topic_id == 2
    assert top.score >= 0.7
    assert "source-hash checkpoint ledger" in top.explanation
    assert "evidence provenance drift" in top.explanation
    assert top.evidence_summary
    assert top.source_ids


def test_cross_topic_atlas_finds_abstraction_match_for_budget_control() -> None:
    from research_harness.knowledge.cross_topic_atlas import (
        build_cross_topic_knowledge_atlas,
        rank_cross_topic_serendipity_links,
    )

    marketing_topic = _snapshot(
        topic_id=3,
        artifact_id=903,
        covered={
            "methods": ["budget pacing with spend caps"],
            "claims": ["budget pacing prevents front-loaded spend"],
            "tasks": ["ad campaign optimization"],
        },
    )
    agent_topic = _snapshot(
        topic_id=4,
        artifact_id=904,
        covered={
            "methods": ["token budget scheduling with context caps"],
            "claims": ["token budget scheduling prevents early context exhaustion"],
            "tasks": ["agent context management"],
        },
    )

    atlas = build_cross_topic_knowledge_atlas(
        (marketing_topic, agent_topic),
        wiki_exports=(
            _wiki(
                marketing_topic,
                page_path="methods/budget-pacing.md",
                title="Budget pacing",
                snippet="Pacing allocates spend across time under hard caps.",
            ),
            _wiki(
                agent_topic,
                page_path="methods/token-budget-scheduling.md",
                title="Token budget scheduling",
                snippet="Scheduling allocates context budget across agent phases.",
            ),
        ),
    )
    ranked = rank_cross_topic_serendipity_links(
        atlas, query="budget scheduling", max_results=5
    )

    abstraction_links = [
        link for link in ranked if link.link_type == "abstraction_match"
    ]
    assert abstraction_links
    link = abstraction_links[0]
    assert link.score >= 0.68
    assert "budget_control" in link.explanation
    assert {link.source_topic_id, link.target_topic_id} == {3, 4}


def test_cross_topic_atlas_downranks_incompatible_lexical_overlap() -> None:
    from research_harness.knowledge.cross_topic_atlas import (
        build_cross_topic_knowledge_atlas,
    )

    retrieval_topic = _snapshot(
        topic_id=5,
        artifact_id=905,
        covered={
            "methods": ["graph neural network reranker"],
            "claims": ["graph neural network reranker improves citation recall"],
            "tasks": ["paper retrieval"],
        },
    )
    wetlab_topic = _snapshot(
        topic_id=6,
        artifact_id=906,
        covered={
            "gaps": [
                "graph neural network molecular property prediction lacks wet-lab validation"
            ],
            "tasks": ["molecular property prediction"],
        },
    )

    atlas = build_cross_topic_knowledge_atlas((retrieval_topic, wetlab_topic))

    assert atlas.links
    assert max(link.score for link in atlas.links) < 0.45
    assert any("incompatible_task_context" in link.warnings for link in atlas.links)


def test_cross_topic_atlas_penalizes_stale_or_degraded_snapshots() -> None:
    from research_harness.knowledge.cross_topic_atlas import (
        build_cross_topic_knowledge_atlas,
    )

    source = _snapshot(
        topic_id=7,
        artifact_id=907,
        covered={
            "methods": ["audit checkpoint ledger"],
            "claims": ["checkpoint ledgers reduce drift"],
            "tasks": ["audit automation"],
        },
    )
    current_target = _snapshot(
        topic_id=8,
        artifact_id=908,
        covered={
            "gaps": ["agent evidence drift during long running automation"],
            "tasks": ["agent automation"],
        },
    )
    stale_target = dataclasses.replace(
        current_target,
        current_source_hash=f"{current_target.source_hash}-changed",
        is_current=False,
    )

    current_atlas = build_cross_topic_knowledge_atlas((source, current_target))
    stale_atlas = build_cross_topic_knowledge_atlas((source, stale_target))

    assert current_atlas.links
    assert stale_atlas.links
    assert stale_atlas.links[0].score < current_atlas.links[0].score
    assert "target_snapshot_stale" in stale_atlas.links[0].warnings


def test_cross_topic_atlas_returns_empty_for_zero_or_single_topic() -> None:
    from research_harness.knowledge.cross_topic_atlas import (
        build_cross_topic_knowledge_atlas,
        cross_topic_knowledge_atlas_to_dict,
        rank_cross_topic_serendipity_links,
    )

    snapshot = _snapshot(
        topic_id=9,
        artifact_id=909,
        covered={"methods": ["single topic method"]},
    )

    empty = build_cross_topic_knowledge_atlas(())
    single = build_cross_topic_knowledge_atlas((snapshot,))

    assert empty.links == ()
    assert empty.topic_ids == ()
    assert single.links == ()
    assert single.topic_ids == (9,)
    assert rank_cross_topic_serendipity_links(single) == ()
    assert cross_topic_knowledge_atlas_to_dict(single)["links"] == []


def _snapshot(
    *,
    topic_id: int,
    artifact_id: int,
    covered: dict[str, list[str]],
    coverage: dict[str, int] | None = None,
    is_current: bool = True,
) -> TopicKnowledgeSnapshot:
    merged_coverage = {
        "topic_papers": 1,
        "paper_cards": 1,
        "compiled_summaries": 1,
        "normalized_claims": len(covered.get("claims", [])),
        "gaps": len(covered.get("gaps", [])),
        "contradictions": len(covered.get("conflicts", [])),
        "semantic_atoms": sum(len(values) for values in covered.values()),
        **(coverage or {}),
    }
    source_hash = f"atlas-source-{artifact_id}"
    return TopicKnowledgeSnapshot(
        topic_id=topic_id,
        artifact_id=artifact_id,
        snapshot_id=artifact_id + 1000,
        source_hash=source_hash,
        current_source_hash=source_hash if is_current else f"{source_hash}-current",
        snapshot_version="topic_knowledge_snapshot.v1",
        payload={
            "schema_version": "topic_knowledge_snapshot.v1",
            "topic_id": topic_id,
            "source_hash": source_hash,
            "coverage": dict(merged_coverage),
            "covered": {key: list(values) for key, values in covered.items()},
            "weak_spots": {},
            "research_state": {
                "open_gaps": list(covered.get("gaps", [])),
                "high_confidence_claims": list(covered.get("claims", [])),
            },
            "next_actions": [],
        },
        source_manifest={"fixture": "cross_topic_knowledge_atlas"},
        coverage=dict(merged_coverage),
        is_current=is_current,
    )


def _wiki(
    snapshot: TopicKnowledgeSnapshot,
    *,
    page_path: str,
    title: str,
    snippet: str,
) -> ResearchWikiExport:
    page = ResearchWikiPage(
        relative_path=page_path,
        title=title,
        page_type="methodology" if page_path.startswith("methods/") else "finding",
        frontmatter={
            "schema_version": "research_wiki_page.v1",
            "topic_id": snapshot.topic_id,
            "title": title,
            "sources": [
                {
                    "source_type": "topic_knowledge_snapshot",
                    "source_id": str(snapshot.artifact_id),
                    "source_hash": snapshot.source_hash,
                    "section_anchor": "atlas",
                    "evidence_snippet": snippet,
                    "paper_id": snapshot.topic_id,
                }
            ],
        },
        body=f"# {title}\n\n{snippet}\n",
    )
    return ResearchWikiExport(
        topic_id=snapshot.topic_id,
        vault_path=Path("/tmp/research-harness-cross-topic-atlas"),
        pages=(page,),
        graph={page.relative_path: []},
    )
