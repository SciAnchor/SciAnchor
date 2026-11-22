from __future__ import annotations

import json
from pathlib import Path

from research_harness.knowledge.research_wiki import (
    ResearchWikiExport,
    ResearchWikiPage,
)
from research_harness.storage.db import Database


def _seed_topic(conn) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'wiki topic')")
    conn.execute(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
        VALUES (1, 'Wiki Paper', '10.test/wiki', '2501.02020', 's2_wiki')
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
             '[{"section":"results","text":"recall improves"}]')
        """
    )
    conn.execute(
        """
        INSERT INTO gaps
            (id, topic_id, description, gap_type, severity, related_paper_ids,
             focus, confidence, cross_verified, cross_check_runs)
        VALUES
            (1, 1, 'Cross-domain recall evidence is thin', 'evidence_gap',
             'medium', '[1]', '', 0.61, 0, 0)
        """
    )
    conn.commit()


def test_research_wiki_frontmatter_round_trips_structured_values() -> None:
    from research_harness.knowledge.research_wiki import (
        dump_frontmatter,
        parse_frontmatter,
    )

    metadata = {
        "schema_version": "research_wiki_page.v1",
        "topic_id": 1,
        "page_type": "finding",
        "title": "Reranker improves recall",
        "aliases": ["Reranker recall"],
        "sources": [
            {
                "paper_id": 1,
                "source_type": "normalized_claims",
                "source_id": "1",
                "source_hash": "abc",
                "section_anchor": "results",
                "evidence_snippet": "recall improves",
            }
        ],
    }

    markdown = dump_frontmatter(metadata, "# Reranker improves recall\n")
    parsed, body = parse_frontmatter(markdown)

    assert parsed == metadata
    assert body == "# Reranker improves recall\n"


def test_research_wiki_wikilink_parser_handles_aliases_and_anchors() -> None:
    from research_harness.knowledge.research_wiki import extract_wikilinks

    links = extract_wikilinks(
        "See [[sources/paper-1#results|results]] and [[concepts/orb]]."
    )

    assert [link.target for link in links] == [
        "sources/paper-1#results",
        "concepts/orb",
    ]
    assert links[0].label == "results"
    assert links[1].label == "orb"


def test_materialize_research_wiki_vault_writes_evidence_bound_pages(
    db: Database,
    conn,
    tmp_path,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.knowledge.research_wiki import (
        materialize_research_wiki_vault,
        parse_frontmatter,
    )

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)

    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )

    expected_paths = {
        "sources/paper-1.md",
        "sources/paper-1/results.md",
        "concepts/orb.md",
        "concepts/recall-20.md",
        "methodology/reranker.md",
        "findings/reranker-improves-recall.md",
        "thesis/topic-1.md",
    }
    assert expected_paths <= {page.relative_path for page in export.pages}

    finding_path = tmp_path / "wiki" / "findings/reranker-improves-recall.md"
    metadata, body = parse_frontmatter(finding_path.read_text(encoding="utf-8"))

    assert metadata["schema_version"] == "research_wiki_page.v1"
    assert metadata["page_type"] == "finding"
    assert metadata["topic_id"] == 1
    assert metadata["sources"] == [
        {
            "paper_id": 1,
            "source_type": "normalized_claims",
            "source_id": "1",
            "source_hash": metadata["sources"][0]["source_hash"],
            "section_anchor": "results",
            "evidence_snippet": "Reranker improves recall",
        }
    ]
    assert "[[sources/paper-1/results|results]]" in body
    assert "[[concepts/orb|ORB]]" in body
    assert "[[concepts/recall-20|recall@20]]" in body


def test_research_wiki_graph_combines_wikilinks_and_semantic_edges(
    db: Database,
    conn,
    tmp_path,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.knowledge.research_wiki import materialize_research_wiki_vault

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)

    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )

    assert export.graph["findings/reranker-improves-recall.md"] == [
        "concepts/orb.md",
        "concepts/paper-retrieval.md",
        "concepts/recall-20.md",
        "sources/paper-1/results.md",
    ]
    assert export.graph["concepts/orb.md"] == ["findings/reranker-improves-recall.md"]


def test_validate_research_wiki_export_accepts_materialized_vault(
    db: Database,
    conn,
    tmp_path,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.knowledge.research_wiki import (
        materialize_research_wiki_vault,
        validate_research_wiki_export,
    )

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )

    report = validate_research_wiki_export(export)

    assert report.valid is True
    assert report.issue_count == 0
    assert report.issues == ()
    assert report.counts_by_code == {}


def test_validate_research_wiki_export_reports_advisory_issues() -> None:
    from research_harness.knowledge.research_wiki import (
        render_research_wiki_validation_report_markdown,
        validate_research_wiki_export,
    )

    export = ResearchWikiExport(
        topic_id=1,
        vault_path=Path("/tmp/wiki"),
        pages=(
            ResearchWikiPage(
                relative_path="findings/bad.md",
                title="Bad",
                page_type="finding",
                frontmatter={
                    "schema_version": "wrong",
                    "topic_id": 2,
                    "page_type": "finding",
                    "title": "",
                    "sources": [],
                },
                body="# Bad\n\nSee [[missing/page]].\n",
            ),
            ResearchWikiPage(
                relative_path="findings/bad.md",
                title="Duplicate",
                page_type="finding",
                frontmatter={
                    "schema_version": "research_wiki_page.v1",
                    "topic_id": 1,
                    "page_type": "finding",
                    "title": "Duplicate",
                    "sources": [
                        {
                            "paper_id": 1,
                            "source_type": "normalized_claims",
                            "source_id": "1",
                            "source_hash": "hash-1",
                            "section_anchor": "results",
                            "evidence_snippet": "evidence",
                        }
                    ],
                },
                body="# Duplicate\n",
            ),
        ),
        graph={"findings/bad.md": []},
    )

    report = validate_research_wiki_export(export)

    assert report.valid is False
    assert report.counts_by_code == {
        "duplicate_page_path": 1,
        "frontmatter_schema": 3,
        "missing_evidence_anchor": 1,
        "unresolved_wikilink": 1,
    }
    assert {issue.severity for issue in report.issues} == {"error"}

    markdown = render_research_wiki_validation_report_markdown(report)

    assert markdown.startswith("# Research Wiki Validation\n\n")
    assert "- Valid: no\n" in markdown
    assert (
        "- `duplicate_page_path` (error) `findings/bad.md`: duplicate page path"
        in markdown
    )
    assert (
        "- `unresolved_wikilink` (error) `findings/bad.md`: "
        "unresolved wikilink `missing/page`"
    ) in markdown


def test_materialize_research_wiki_bundle_writes_local_files(
    db: Database,
    conn,
    tmp_path,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.knowledge.research_wiki import materialize_research_wiki_vault
    from research_harness.knowledge.research_wiki_bundle import (
        materialize_research_wiki_bundle,
    )

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )

    bundle = materialize_research_wiki_bundle(
        export,
        bundle_path=tmp_path / "bundle",
    )

    manifest_path = tmp_path / "bundle" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    finding = tmp_path / "bundle" / "vault" / "findings/reranker-improves-recall.md"

    assert bundle.topic_id == 1
    assert bundle.bundle_path == tmp_path / "bundle"
    assert bundle.manifest == manifest
    assert finding.read_text(encoding="utf-8") == next(
        page.markdown
        for page in export.pages
        if page.relative_path == "findings/reranker-improves-recall.md"
    )
    assert (
        (tmp_path / "bundle" / "insights.md")
        .read_text(encoding="utf-8")
        .startswith("# Research Wiki Insights\n")
    )
    assert "- Valid: yes\n" in (tmp_path / "bundle" / "validation.md").read_text(
        encoding="utf-8"
    )
    assert manifest["schema_version"] == "research_wiki_bundle.v1"
    assert manifest["topic_id"] == 1
    assert manifest["page_count"] == len(export.pages)
    assert manifest["validation"]["valid"] is True
    assert (
        "vault/findings/reranker-improves-recall.md" in manifest["files"]["vault_pages"]
    )
    assert bundle.written_relative_paths == tuple(
        sorted(
            [
                "insights.md",
                "manifest.json",
                "validation.md",
                *(f"vault/{page.relative_path}" for page in export.pages),
            ]
        )
    )


def test_materialize_research_wiki_bundle_rejects_unsafe_page_paths(tmp_path) -> None:
    from research_harness.knowledge.research_wiki_bundle import (
        materialize_research_wiki_bundle,
    )

    export = ResearchWikiExport(
        topic_id=1,
        vault_path=tmp_path / "wiki",
        pages=(
            ResearchWikiPage(
                relative_path="../escape.md",
                title="Escape",
                page_type="finding",
                frontmatter={
                    "schema_version": "research_wiki_page.v1",
                    "topic_id": 1,
                    "page_type": "finding",
                    "title": "Escape",
                    "sources": [],
                },
                body="# Escape\n",
            ),
        ),
        graph={},
    )

    try:
        materialize_research_wiki_bundle(export, bundle_path=tmp_path / "bundle")
    except ValueError as exc:
        assert "unsafe wiki page path" in str(exc)
    else:
        raise AssertionError("expected unsafe page path to be rejected")


def test_search_research_wiki_pages_ranks_hits_with_evidence(
    db: Database,
    conn,
    tmp_path,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.knowledge.research_wiki import materialize_research_wiki_vault
    from research_harness.knowledge.research_wiki_search import (
        search_research_wiki_pages,
    )

    _seed_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    export = materialize_research_wiki_vault(
        db,
        topic_id=1,
        vault_path=tmp_path / "wiki",
    )

    result = search_research_wiki_pages(export, "reranker recall", max_results=3)

    assert result.topic_id == 1
    assert result.query == "reranker recall"
    assert result.term_count == 2
    assert result.hits[0].page_path == "findings/reranker-recall-20-orb-7-higher.md"
    assert result.hits[0].matched_terms == ("reranker", "recall")
    assert result.hits[0].score > result.hits[1].score
    assert result.hits[0].evidence
    assert result.hits[0].evidence[0].source_type == "normalized_claims"
    assert result.hits[0].evidence[0].source_id == "1"
    assert all("reranker" in hit.matched_terms for hit in result.hits)


def test_search_research_wiki_pages_handles_empty_query() -> None:
    from research_harness.knowledge.research_wiki_search import (
        search_research_wiki_pages,
    )

    export = ResearchWikiExport(
        topic_id=1,
        vault_path=Path("/tmp/wiki"),
        pages=(
            ResearchWikiPage(
                relative_path="findings/a.md",
                title="A",
                page_type="finding",
                frontmatter={
                    "schema_version": "research_wiki_page.v1",
                    "topic_id": 1,
                    "page_type": "finding",
                    "title": "A",
                    "sources": [],
                },
                body="# A\n",
            ),
        ),
        graph={},
    )

    result = search_research_wiki_pages(export, "   ")

    assert result.topic_id == 1
    assert result.term_count == 0
    assert result.hits == ()


def test_search_research_wiki_pages_ranking_v2_prefers_fresh_evidence_bound_pages() -> (
    None
):
    from research_harness.knowledge.research_wiki_search import (
        search_research_wiki_pages,
    )

    def page(
        path: str,
        title: str,
        page_type: str,
        body: str,
        sources: list[dict],
        *,
        status: str = "ready",
    ) -> ResearchWikiPage:
        return ResearchWikiPage(
            relative_path=path,
            title=title,
            page_type=page_type,
            frontmatter={
                "schema_version": "research_wiki_page.v1",
                "topic_id": 1,
                "page_type": page_type,
                "title": title,
                "status": status,
                "sources": sources,
            },
            body=body,
        )

    export = ResearchWikiExport(
        topic_id=1,
        vault_path=Path("/tmp/wiki"),
        pages=(
            page(
                "sources/stale-term-heavy.md",
                "Hybrid retrieval recall archive",
                "source",
                ("# Hybrid retrieval recall archive\n\nhybrid retrieval recall " * 10),
                [
                    {
                        "paper_id": 1,
                        "source_type": "paper_card",
                        "source_id": "stale-paper",
                        "source_hash": "stale-hash",
                        "section_anchor": "results",
                        "evidence_snippet": "hybrid retrieval recall archive",
                    }
                ],
                status="stale",
            ),
            page(
                "concepts/hybrid-retrieval.md",
                "Hybrid retrieval",
                "concept",
                "# Hybrid retrieval\n\nHybrid retrieval recall appears in notes.\n",
                [],
            ),
            page(
                "findings/hybrid-retrieval-recall.md",
                "Hybrid retrieval recall finding",
                "finding",
                (
                    "# Hybrid retrieval recall finding\n\n"
                    "Hybrid retrieval recall improves on ORB with source support.\n"
                ),
                [
                    {
                        "paper_id": 2,
                        "source_type": "normalized_claims",
                        "source_id": "claim-2",
                        "source_hash": "claim-hash-2",
                        "section_anchor": "results",
                        "evidence_snippet": "Hybrid retrieval recall improves on ORB.",
                    },
                    {
                        "paper_id": 3,
                        "source_type": "paper_card",
                        "source_id": "paper-3",
                        "source_hash": "paper-hash-3",
                        "section_anchor": "summary",
                        "evidence_snippet": "Hybrid retrieval recall is replicated.",
                    },
                ],
            ),
        ),
        graph={},
    )

    result = search_research_wiki_pages(
        export,
        "hybrid retrieval recall",
        max_results=3,
    )

    assert [hit.page_path for hit in result.hits] == [
        "findings/hybrid-retrieval-recall.md",
        "sources/stale-term-heavy.md",
        "concepts/hybrid-retrieval.md",
    ]
    assert result.hits[0].score > result.hits[1].score
    assert result.hits[0].page_type == "finding"
    assert result.hits[0].matched_terms == ("hybrid", "retrieval", "recall")
    assert [anchor.source_id for anchor in result.hits[0].evidence] == [
        "claim-2",
        "paper-3",
    ]
