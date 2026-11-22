from __future__ import annotations

from pathlib import Path

from research_harness.knowledge.research_wiki import (
    ResearchWikiExport,
    ResearchWikiPage,
)


def _seed_db_topic(conn) -> None:
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
    conn.commit()


def _source(
    *,
    paper_id: int | None = 1,
    source_type: str = "paperindex_card",
    source_id: str = "card-1",
    source_hash: str = "hash-1",
    section_anchor: str = "results",
    evidence_snippet: str = "hybrid retrieval recall improves on tail queries",
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
    path: str,
    title: str,
    page_type: str,
    body: str,
    sources: list[dict[str, object]],
    *,
    status: str = "ready",
) -> ResearchWikiPage:
    return ResearchWikiPage(
        relative_path=path,
        title=title,
        page_type=page_type,
        frontmatter={
            "schema_version": "research_wiki_page.v1",
            "topic_id": 7,
            "page_type": page_type,
            "title": title,
            "status": status,
            "sources": sources,
        },
        body=body,
    )


def _export(*pages: ResearchWikiPage) -> ResearchWikiExport:
    return ResearchWikiExport(
        topic_id=7,
        vault_path=Path("/tmp/wiki"),
        pages=tuple(pages),
        graph={},
    )


def test_build_wiki_context_pack_ranks_pages_and_preserves_evidence() -> None:
    from research_harness.knowledge.wiki_context_pack import (
        build_wiki_context_pack,
        wiki_context_pack_to_dict,
    )

    export = _export(
        _page(
            "concepts/hybrid-retrieval.md",
            "Hybrid retrieval",
            "concept",
            "# Hybrid retrieval\n\nHybrid retrieval recall is discussed.",
            [],
        ),
        _page(
            "findings/hybrid-retrieval-recall.md",
            "Hybrid retrieval recall finding",
            "finding",
            (
                "# Hybrid retrieval recall finding\n\n"
                "Hybrid retrieval recall improves on tail queries and hard negatives."
            ),
            [
                _source(
                    source_type="normalized_claims",
                    source_id="claim-2",
                    source_hash="claim-hash-2",
                    evidence_snippet=(
                        "Hybrid retrieval recall improves on tail queries."
                    ),
                ),
                _source(
                    paper_id=2,
                    source_type="paperindex_card",
                    source_id="card-2",
                    source_hash="card-hash-2",
                    section_anchor="summary",
                    evidence_snippet="Paper card reports replicated recall gains.",
                ),
            ],
        ),
        _page(
            "sources/paper-1.md",
            "Hybrid Retrieval Paper",
            "source",
            "# Hybrid Retrieval Paper\n\nHybrid retrieval recall source notes.",
            [
                _source(
                    source_type="paperindex_card",
                    source_id="card-1",
                    source_hash="card-hash-1",
                    section_anchor="abstract",
                    evidence_snippet="Paper introduces hybrid retrieval recall.",
                )
            ],
        ),
    )

    pack = build_wiki_context_pack(
        export,
        query="hybrid retrieval recall",
        max_pages=2,
        max_anchors=2,
        excerpt_chars=96,
    )

    assert pack.schema_version == "wiki_context_pack.v1"
    assert pack.topic_id == 7
    assert pack.query == "hybrid retrieval recall"
    assert pack.pages[0].page_path == "findings/hybrid-retrieval-recall.md"
    assert pack.pages[0].page_type == "finding"
    assert pack.pages[0].matched_terms == ("hybrid", "retrieval", "recall")
    assert [anchor.source_type for anchor in pack.pages[0].evidence_anchors] == [
        "normalized_claims",
        "paperindex_card",
    ]
    assert pack.evidence_anchor_count == 2
    assert pack.source_diversity == {
        "paper_count": 2,
        "source_hash_count": 2,
        "source_type_count": 2,
    }
    assert pack.truncated is True
    assert pack.truncation == {
        "omitted_anchor_count": 1,
        "omitted_page_count": 1,
    }
    assert pack.warnings == ()
    assert pack.degraded is False

    data = wiki_context_pack_to_dict(pack)

    assert data["schema_version"] == "wiki_context_pack.v1"
    assert data["pages"][0]["evidence_anchors"][0] == {
        "page_path": "findings/hybrid-retrieval-recall.md",
        "paper_id": 1,
        "source_type": "normalized_claims",
        "source_id": "claim-2",
        "source_hash": "claim-hash-2",
        "section_anchor": "results",
        "evidence_snippet": "Hybrid retrieval recall improves on tail queries.",
    }
    assert "vault_path" not in data
    assert "/tmp/wiki" not in repr(data)


def test_build_wiki_context_pack_uses_action_page_type_hints() -> None:
    from research_harness.knowledge.wiki_context_pack import build_wiki_context_pack

    export = _export(
        _page(
            "concepts/reranking.md",
            "Reranking",
            "concept",
            "# Reranking\n\nGeneral reranking notes.",
            [],
        ),
        _page(
            "sources/paper-4/method.md",
            "Paper 4 method section",
            "source_section",
            "# Paper 4 method section\n\nSparse and dense reranking method details.",
            [
                _source(
                    paper_id=4,
                    source_type="paperindex_card",
                    source_id="card-4",
                    source_hash="card-hash-4",
                    section_anchor="method",
                    evidence_snippet="Sparse and dense reranking method details.",
                )
            ],
        ),
    )

    pack = build_wiki_context_pack(
        export,
        query="",
        action_name="paper_summarize",
        max_pages=2,
    )

    assert [page.page_path for page in pack.pages] == ["sources/paper-4/method.md"]
    assert pack.pages[0].selection_reason == "action_page_type"
    assert pack.pages[0].evidence_anchors[0].paper_id == 4


def test_build_wiki_context_pack_reports_validation_warnings_and_degraded() -> None:
    from research_harness.knowledge.wiki_context_pack import build_wiki_context_pack

    export = _export(
        ResearchWikiPage(
            relative_path="findings/broken.md",
            title="Broken finding",
            page_type="finding",
            frontmatter={
                "schema_version": "wrong",
                "topic_id": 7,
                "page_type": "finding",
                "title": "Broken finding",
                "status": "degraded",
                "sources": [
                    {
                        "source_type": "paperindex_card",
                        "source_id": "card-1",
                    }
                ],
            },
            body="# Broken finding\n\nHybrid recall points to [[missing/page]].",
        )
    )

    pack = build_wiki_context_pack(
        export,
        query="hybrid recall",
        max_pages=1,
        include_validation=True,
    )

    warning_codes = [warning.code for warning in pack.warnings]
    assert pack.degraded is True
    assert "frontmatter_schema" in warning_codes
    assert "missing_evidence_anchor" in warning_codes
    assert "unresolved_wikilink" in warning_codes
    assert pack.pages[0].status == "degraded"


def test_build_wiki_context_pack_handles_empty_query_without_public_paths() -> None:
    from research_harness.knowledge.wiki_context_pack import (
        build_wiki_context_pack,
        wiki_context_pack_to_dict,
    )

    export = _export(
        _page(
            "findings/alpha.md",
            "Alpha finding",
            "finding",
            "# Alpha finding\n\nEvidence-backed alpha finding.",
            [
                _source(
                    source_id="alpha",
                    source_hash="alpha-hash",
                    evidence_snippet="Evidence-backed alpha finding.",
                )
            ],
        )
    )

    pack = build_wiki_context_pack(export, query="   ", max_pages=1)
    data = wiki_context_pack_to_dict(pack)

    assert pack.query == ""
    assert pack.pages[0].selection_reason == "fallback"
    assert data["query"] == ""
    assert (
        data["pages"][0]["excerpt"] == "# Alpha finding Evidence-backed alpha finding."
    )
    assert "vault_path" not in data


def test_build_wiki_context_pack_warns_on_broad_fallback_selection() -> None:
    from research_harness.knowledge.wiki_context_pack import (
        build_wiki_context_pack,
        wiki_context_pack_to_dict,
    )

    export = _export(
        _page(
            "findings/alpha.md",
            "Alpha finding",
            "finding",
            "# Alpha finding\n\nEvidence-backed alpha finding.",
            [
                _source(
                    source_id="alpha",
                    source_hash="alpha-hash",
                    evidence_snippet="Evidence-backed alpha finding.",
                )
            ],
        ),
        _page(
            "methods/beta.md",
            "Beta method",
            "methodology",
            "# Beta method\n\nEvidence-backed beta method.",
            [
                _source(
                    source_id="beta",
                    source_hash="beta-hash",
                    evidence_snippet="Evidence-backed beta method.",
                )
            ],
        ),
    )

    pack = build_wiki_context_pack(export, query="", max_pages=2)

    assert [page.selection_reason for page in pack.pages] == [
        "fallback",
        "fallback",
    ]
    assert pack.degraded is False
    assert [warning.code for warning in pack.warnings] == ["broad_fallback_context"]

    data = wiki_context_pack_to_dict(pack)
    assert data["warnings"][0] == {
        "code": "broad_fallback_context",
        "severity": "warning",
        "page_path": "",
        "message": (
            "context pack selected pages without query, action, or anchor; "
            "treat as broad advisory context"
        ),
        "target": "",
    }


def test_build_wiki_context_pack_payload_from_db_loads_real_wiki_export(
    db,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.knowledge.wiki_context_pack import (
        build_wiki_context_pack_payload_from_db,
    )

    _seed_db_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)

    payload = build_wiki_context_pack_payload_from_db(
        db,
        topic_id=1,
        query="reranker recall",
        action_name="experiment_design",
    )

    assert payload["schema_version"] == "wiki_context_pack.v1"
    assert payload["paper_wiki_status"] == "loaded"
    assert payload["status_reason"] == "wiki_context_pack_loaded"
    assert payload["topic_id"] == 1
    assert payload["query"] == "reranker recall"
    assert payload["action_name"] == "experiment_design"
    assert payload["page_count"] > 0
    assert payload["evidence_anchor_count"] > 0
    assert payload["preflight"]["priority_evidence_layer"] == "research_wiki"
    assert payload["preflight"]["fallback_allowed"] is False
    assert "normalized_claims" in {
        anchor["source_type"]
        for page in payload["pages"]
        for anchor in page["evidence_anchors"]
    }
    assert "paper_wiki_status" in payload
    assert ".research-harness" not in repr(payload)


def test_build_wiki_context_pack_payload_from_db_reports_missing_snapshot(
    db,
    conn,
) -> None:
    from research_harness.knowledge.wiki_context_pack import (
        build_wiki_context_pack_payload_from_db,
    )

    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'missing wiki')")
    conn.commit()

    payload = build_wiki_context_pack_payload_from_db(
        db,
        topic_id=1,
        action_name="paper_writing",
    )

    assert payload == {
        "schema_version": "wiki_context_pack.v1",
        "topic_id": 1,
        "paper_wiki_status": "unavailable",
        "status_reason": "no_research_wiki_export",
        "unavailable_reasons": [
            "no current or stale Topic Knowledge snapshot; refresh Topic Knowledge from paper cards first"
        ],
        "warnings": [],
        "preflight": {
            "priority_evidence_layer": "",
            "fallback_allowed": True,
            "fallback_must_be_declared": True,
        },
        "pages": [],
    }


def test_build_wiki_context_pack_payload_from_db_warns_on_stale_snapshot(
    db,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.knowledge.wiki_context_pack import (
        build_wiki_context_pack_payload_from_db,
    )

    _seed_db_topic(conn)
    build_topic_knowledge_snapshot(db, topic_id=1)
    conn.execute(
        "UPDATE normalized_claims SET claim_text = 'Changed recall evidence' WHERE id = 1"
    )
    conn.commit()

    payload = build_wiki_context_pack_payload_from_db(
        db,
        topic_id=1,
        query="recall",
    )

    assert payload["paper_wiki_status"] == "loaded"
    assert payload["degraded"] is True
    assert "snapshot_stale" in [warning["code"] for warning in payload["warnings"]]
    assert payload["preflight"]["fallback_allowed"] is False
