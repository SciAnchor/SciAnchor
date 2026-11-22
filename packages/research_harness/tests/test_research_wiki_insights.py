from __future__ import annotations

from pathlib import Path

from research_harness.knowledge.research_wiki import (
    ResearchWikiExport,
    ResearchWikiPage,
)
from research_harness.storage.db import Database


def _source(
    *,
    paper_id: int | None = 1,
    source_type: str = "normalized_claims",
    source_id: str = "1",
    source_hash: str = "hash-1",
    section_anchor: str = "results",
    evidence_snippet: str = "evidence",
) -> dict[str, object]:
    return {
        "paper_id": paper_id,
        "source_type": source_type,
        "source_id": source_id,
        "source_hash": source_hash,
        "section_anchor": section_anchor,
        "evidence_snippet": evidence_snippet,
    }


def _page(
    relative_path: str,
    *,
    page_type: str,
    title: str,
    sources: list[dict[str, object]] | None = None,
    body: str = "# Page\n",
) -> ResearchWikiPage:
    return ResearchWikiPage(
        relative_path=relative_path,
        title=title,
        page_type=page_type,
        frontmatter={
            "schema_version": "research_wiki_page.v1",
            "topic_id": 1,
            "page_type": page_type,
            "title": title,
            "sources": sources or [],
        },
        body=body,
    )


def _seed_two_method_topic(conn) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'insight topic')")
    conn.execute(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
        VALUES (1, 'Insight Paper', '10.test/insight', '2501.04040', 's2_insight')
        """
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
    )
    conn.execute(
        """
        INSERT INTO normalized_claims
            (id, topic_id, paper_id, claim_text, method, dataset, metric, task,
             value, direction, confidence, source_section, evidence_spans_json)
        VALUES
            (1, 1, 1, 'Reranker improves recall', 'Reranker', 'ORB',
             'recall@20', 'paper retrieval', '+7', 'higher', 0.82, 'results',
             '[{"section":"results","text":"reranker recall"}]'),
            (2, 1, 1, 'Dense retriever improves recall', 'Dense Retriever', 'ORB',
             'recall@20', 'paper retrieval', '+5', 'higher', 0.78, 'results',
             '[{"section":"results","text":"dense retriever recall"}]')
        """
    )
    conn.commit()


def test_research_wiki_insights_require_evidence_anchors() -> None:
    from research_harness.knowledge.research_wiki_insights import (
        find_research_wiki_insights,
    )

    export = ResearchWikiExport(
        topic_id=1,
        vault_path=Path("/tmp/wiki"),
        pages=(
            _page(
                "findings/unsupported.md",
                page_type="finding",
                title="Unsupported finding",
            ),
            _page(
                "methodology/unsupported.md",
                page_type="methodology",
                title="Unsupported method",
            ),
        ),
        graph={
            "findings/unsupported.md": [],
            "methodology/unsupported.md": [],
        },
    )

    assert find_research_wiki_insights(export).insights == ()


def test_research_wiki_insights_rank_shared_source_anchor() -> None:
    from research_harness.knowledge.research_wiki_insights import (
        find_research_wiki_insights,
    )

    shared = _source(evidence_snippet="Reranker improves recall")
    export = ResearchWikiExport(
        topic_id=1,
        vault_path=Path("/tmp/wiki"),
        pages=(
            _page(
                "findings/reranker-improves-recall.md",
                page_type="finding",
                title="Reranker improves recall",
                sources=[shared],
            ),
            _page(
                "methodology/reranker.md",
                page_type="methodology",
                title="Reranker",
                sources=[shared],
            ),
            _page(
                "concepts/orb.md",
                page_type="concept",
                title="ORB",
                sources=[_source(source_id="2", source_hash="hash-2")],
            ),
        ),
        graph={
            "findings/reranker-improves-recall.md": ["concepts/orb.md"],
            "methodology/reranker.md": [],
            "concepts/orb.md": ["findings/reranker-improves-recall.md"],
        },
    )

    report = find_research_wiki_insights(export)

    assert [insight.insight_type for insight in report.insights][:1] == [
        "shared_source_anchor"
    ]
    first = report.insights[0]
    assert first.source_page == "findings/reranker-improves-recall.md"
    assert first.target_page == "methodology/reranker.md"
    assert first.score > 0
    assert [anchor.source_id for anchor in first.evidence] == ["1"]
    assert first.evidence[0].section_anchor == "results"


def test_research_wiki_insights_find_shared_context_between_methods(
    db: Database,
    conn,
    tmp_path,
) -> None:
    from research_harness.knowledge.research_wiki import materialize_research_wiki_vault
    from research_harness.knowledge.research_wiki_insights import (
        find_research_wiki_insights,
    )
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    _seed_two_method_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )

    report = find_research_wiki_insights(export)
    method_insights = [
        insight
        for insight in report.insights
        if insight.insight_type == "shared_evaluation_context"
    ]

    assert method_insights
    first = method_insights[0]
    assert first.source_page == "methodology/dense-retriever.md"
    assert first.target_page == "methodology/reranker.md"
    assert first.bridge_pages == (
        "concepts/orb.md",
        "concepts/paper-retrieval.md",
        "concepts/recall-20.md",
    )
    assert {anchor.source_id for anchor in first.evidence} == {"1", "2"}
    assert all(anchor.evidence_snippet for anchor in first.evidence)


def test_research_wiki_insights_are_deterministically_sorted() -> None:
    from research_harness.knowledge.research_wiki_insights import (
        find_research_wiki_insights,
    )

    source_a = _source(source_id="1", source_hash="hash-1")
    source_b = _source(source_id="2", source_hash="hash-2")
    export = ResearchWikiExport(
        topic_id=1,
        vault_path=Path("/tmp/wiki"),
        pages=(
            _page(
                "findings/b.md",
                page_type="finding",
                title="B",
                sources=[source_b],
            ),
            _page(
                "methodology/b.md",
                page_type="methodology",
                title="B method",
                sources=[source_b],
            ),
            _page(
                "findings/a.md",
                page_type="finding",
                title="A",
                sources=[source_a],
            ),
            _page(
                "methodology/a.md",
                page_type="methodology",
                title="A method",
                sources=[source_a],
            ),
        ),
        graph={
            "findings/a.md": [],
            "findings/b.md": [],
            "methodology/a.md": [],
            "methodology/b.md": [],
        },
    )

    report = find_research_wiki_insights(export)

    assert [
        (insight.score, insight.source_page, insight.target_page)
        for insight in report.insights
    ] == [
        (0.74, "findings/a.md", "methodology/a.md"),
        (0.74, "findings/b.md", "methodology/b.md"),
    ]


def test_research_wiki_insight_report_renders_dict_and_markdown() -> None:
    from research_harness.knowledge.research_wiki_insights import (
        ResearchWikiInsight,
        ResearchWikiInsightReport,
        render_research_wiki_insight_report_markdown,
        research_wiki_insight_report_to_dict,
    )

    report = ResearchWikiInsightReport(
        topic_id=1,
        insights=(
            ResearchWikiInsight(
                insight_type="shared_evaluation_context",
                source_page="methodology/dense-retriever.md",
                target_page="methodology/reranker.md",
                score=0.84,
                rationale="Two methods share evidence-bound concept context.",
                bridge_pages=("concepts/orb.md", "concepts/recall-20.md"),
                evidence=(
                    _anchor(
                        page_path="methodology/dense-retriever.md",
                        source_id="2",
                        evidence_snippet="dense retriever recall",
                    ),
                    _anchor(
                        page_path="methodology/reranker.md",
                        source_id="1",
                        evidence_snippet="reranker recall",
                    ),
                ),
            ),
        ),
    )

    rendered = research_wiki_insight_report_to_dict(report)

    assert rendered == {
        "topic_id": 1,
        "insight_count": 1,
        "insights": [
            {
                "rank": 1,
                "insight_type": "shared_evaluation_context",
                "score": 0.84,
                "source_page": "methodology/dense-retriever.md",
                "target_page": "methodology/reranker.md",
                "bridge_pages": ["concepts/orb.md", "concepts/recall-20.md"],
                "rationale": "Two methods share evidence-bound concept context.",
                "evidence": [
                    {
                        "page_path": "methodology/dense-retriever.md",
                        "paper_id": 1,
                        "source_type": "normalized_claims",
                        "source_id": "2",
                        "source_hash": "hash-1",
                        "section_anchor": "results",
                        "evidence_snippet": "dense retriever recall",
                    },
                    {
                        "page_path": "methodology/reranker.md",
                        "paper_id": 1,
                        "source_type": "normalized_claims",
                        "source_id": "1",
                        "source_hash": "hash-1",
                        "section_anchor": "results",
                        "evidence_snippet": "reranker recall",
                    },
                ],
            }
        ],
    }

    markdown = render_research_wiki_insight_report_markdown(report)

    assert markdown.startswith("# Research Wiki Insights\n\n")
    assert "- Topic id: 1\n" in markdown
    assert "- Insight count: 1\n" in markdown
    assert "## 1. shared_evaluation_context" in markdown
    assert "- Score: 0.84\n" in markdown
    assert (
        "- Page pair: `methodology/dense-retriever.md` -> `methodology/reranker.md`\n"
    ) in markdown
    assert "- Bridge pages: `concepts/orb.md`, `concepts/recall-20.md`\n" in markdown
    assert (
        "- `methodology/dense-retriever.md` "
        "normalized_claims:2#results "
        "(paper 1, hash hash-1): dense retriever recall"
    ) in markdown


def _anchor(
    *,
    page_path: str,
    source_id: str,
    evidence_snippet: str,
):
    from research_harness.knowledge.research_wiki_insights import (
        ResearchWikiEvidenceAnchor,
    )

    return ResearchWikiEvidenceAnchor(
        page_path=page_path,
        paper_id=1,
        source_type="normalized_claims",
        source_id=source_id,
        source_hash="hash-1",
        section_anchor="results",
        evidence_snippet=evidence_snippet,
    )
