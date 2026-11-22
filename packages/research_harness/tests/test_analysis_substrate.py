from __future__ import annotations

from pathlib import Path

from research_harness.knowledge.research_wiki import ResearchWikiExport
from research_harness.knowledge.research_wiki_insights import (
    ResearchWikiEvidenceAnchor,
)
from research_harness.knowledge.wiki_context_pack import (
    WIKI_CONTEXT_PACK_SCHEMA_VERSION,
    WikiContextPack,
    WikiContextPage,
)


def _anchor(page_path: str, paper_id: int, snippet: str) -> ResearchWikiEvidenceAnchor:
    return ResearchWikiEvidenceAnchor(
        page_path=page_path,
        paper_id=paper_id,
        source_type="paperindex_card",
        source_id=f"card-{paper_id}",
        source_hash=f"hash-{paper_id}",
        section_anchor="results",
        evidence_snippet=snippet,
    )


def _page(
    path: str,
    title: str,
    page_type: str,
    excerpt: str,
    *anchors: ResearchWikiEvidenceAnchor,
) -> WikiContextPage:
    return WikiContextPage(
        page_path=path,
        title=title,
        page_type=page_type,
        status="ready",
        score=0.9,
        matched_terms=tuple(title.lower().split()),
        selection_reason="query_match",
        excerpt=excerpt,
        source_hashes=tuple(anchor.source_hash for anchor in anchors),
        evidence_anchors=tuple(anchors),
    )


def _pack(*pages: WikiContextPage) -> WikiContextPack:
    anchors = tuple(anchor for page in pages for anchor in page.evidence_anchors)
    return WikiContextPack(
        schema_version=WIKI_CONTEXT_PACK_SCHEMA_VERSION,
        topic_id=7,
        query="retrieval robustness",
        action_name="science_discovery",
        anchor_paper_id=None,
        pages=tuple(pages),
        warnings=(),
        degraded=False,
        source_diversity={"paper_count": 2},
        evidence_anchor_count=len(anchors),
        truncated=False,
        truncation={"omitted_anchor_count": 0, "omitted_page_count": 0},
    )


def _export(graph: dict[str, list[str]]) -> ResearchWikiExport:
    return ResearchWikiExport(topic_id=7, vault_path=Path(), pages=(), graph=graph)


def test_analysis_substrate_keeps_survey_authority_and_evidence() -> None:
    from research_harness.knowledge.analysis_substrate import (
        build_analysis_substrate,
        analysis_substrate_to_dict,
    )

    survey = _page(
        "methodology/retrieval-robustness.md",
        "Retrieval robustness",
        "methodology",
        "The survey defines retrieval robustness as the main problem axis.",
        _anchor(
            "methodology/retrieval-robustness.md",
            1,
            "Surveys identify robustness and evaluation blind spots.",
        ),
    )
    capsule = _page(
        "findings/generation-speed.md",
        "Generation speed",
        "finding",
        "A single paper claims generation speed should replace the main axis.",
        _anchor(
            "findings/generation-speed.md",
            2,
            "Generation is faster with speculative decoding.",
        ),
    )
    pack = _pack(survey, capsule)

    substrate = build_analysis_substrate(
        context_pack=pack,
        wiki_export=_export(
            {
                survey.page_path: [capsule.page_path],
                capsule.page_path: [survey.page_path],
            }
        ),
        survey_paper_ids={1},
    )
    payload = analysis_substrate_to_dict(substrate)

    assert payload["schema_version"] == "analysis_substrate.v1"
    assert payload["authority_hierarchy"] == {
        "survey_pages": [survey.page_path],
        "supporting_capsule_pages": [capsule.page_path],
        "capsules_blocked_from_axis_redefinition": True,
    }
    assert payload["agenda"]["main_problem_axis"] == "Retrieval robustness"
    assert payload["agenda"]["survey_derived"] is True
    assert payload["agenda"]["evidence_anchors"][0]["source_id"] == "card-1"
    assert "Generation speed" not in payload["agenda"]["main_problem_axis"]
    assert payload["clusters"][0]["evidence_anchors"][0]["source_id"] == "card-1"
    assert payload["relation_graph"] == []


def test_analysis_substrate_allows_capsule_multi_assignment() -> None:
    from research_harness.knowledge.analysis_substrate import (
        analysis_substrate_to_dict,
        build_analysis_substrate,
    )

    first = _page(
        "methodology/retrieval.md",
        "Retrieval",
        "methodology",
        "Survey cluster for retrieval.",
        _anchor("methodology/retrieval.md", 1, "Retrieval survey evidence."),
    )
    second = _page(
        "methodology/evaluation.md",
        "Evaluation",
        "methodology",
        "Survey cluster for evaluation.",
        _anchor("methodology/evaluation.md", 1, "Evaluation survey evidence."),
    )
    capsule = _page(
        "findings/shared-paper.md",
        "Shared paper",
        "finding",
        "A capsule supporting both survey axes.",
        _anchor("findings/shared-paper.md", 2, "Shared supporting evidence."),
    )

    substrate = build_analysis_substrate(
        context_pack=_pack(first, second, capsule),
        wiki_export=_export(
            {
                first.page_path: [capsule.page_path],
                second.page_path: [capsule.page_path],
                capsule.page_path: [first.page_path, second.page_path],
            }
        ),
        survey_paper_ids={1},
    )

    memberships = [
        cluster.cluster_id
        for cluster in substrate.clusters
        if capsule.page_path in cluster.member_page_paths
    ]
    assert memberships == ["cluster-1", "cluster-2"]
    payload = analysis_substrate_to_dict(substrate)
    assert payload["relation_graph"][0]["relation_type"] in {
        "foundation",
        "extension",
        "alternative",
        "complementarity",
    }
    assert payload["relation_graph"][0]["evidence_anchors"]
    assert payload["comparison_tables"][0]["rows"][0]["evidence_anchors"]
    assert payload["guided_questions"][0]["evidence_anchors"]


def test_analysis_substrate_without_survey_fails_closed() -> None:
    from research_harness.knowledge.analysis_substrate import build_analysis_substrate

    capsule = _page(
        "findings/capsule-only.md",
        "Capsule-only agenda",
        "finding",
        "This must not become the topic agenda without survey authority.",
        _anchor("findings/capsule-only.md", 2, "A single-paper observation."),
    )
    substrate = build_analysis_substrate(
        context_pack=_pack(capsule),
        wiki_export=_export({capsule.page_path: []}),
        survey_paper_ids=set(),
    )

    assert substrate.agenda.main_problem_axis == ""
    assert substrate.agenda.survey_derived is False
    assert substrate.clusters == ()
    assert substrate.degraded is True
    assert "survey_authority_unavailable" in substrate.warnings


def test_analysis_substrate_does_not_promote_capsule_with_survey_citation() -> None:
    from research_harness.knowledge.analysis_substrate import build_analysis_substrate

    capsule = _page(
        "sources/paper-2.md",
        "Capsule claiming a new axis",
        "source",
        "A paper capsule cites a survey but cannot define its agenda.",
        _anchor("sources/paper-2.md", 1, "Survey citation."),
        _anchor("sources/paper-2.md", 2, "Capsule claim."),
    )
    substrate = build_analysis_substrate(
        context_pack=_pack(capsule),
        wiki_export=_export({capsule.page_path: []}),
        survey_paper_ids={1},
    )

    assert substrate.agenda.main_problem_axis == ""
    assert substrate.clusters == ()
    assert substrate.authority_hierarchy.survey_pages == ()
    assert substrate.authority_hierarchy.supporting_capsule_pages == (
        capsule.page_path,
    )
    assert substrate.degraded is True


def test_analysis_substrate_primitive_contract_and_db_facade(db, conn) -> None:
    from research_harness.primitives.registry import get_primitive_spec

    spec = get_primitive_spec("analysis_substrate_build")
    assert spec is not None
    assert spec.requires_llm is False
    assert spec.idempotent is True
    assert spec.input_schema["required"] == ["topic_id"]
    assert spec.input_schema["properties"]["max_clusters"]["maximum"] == 12
    assert spec.input_schema["properties"]["max_relations"]["maximum"] == 48

    gap_spec = get_primitive_spec("gap_detect")
    candidate_spec = get_primitive_spec("algorithm_candidate_generate")
    assert gap_spec is not None and candidate_spec is not None
    assert gap_spec.input_schema["required"] == ["topic_id"]
    assert candidate_spec.input_schema["required"] == ["topic_id", "brief"]
    assert gap_spec.input_schema["properties"]["analysis_substrate"] == {
        "type": "object"
    }
    assert candidate_spec.input_schema["properties"]["analysis_substrate"] == {
        "type": "object"
    }
    assert gap_spec.output_type == "GapDetectOutput"
    assert candidate_spec.output_type == "AlgorithmCandidateGenerateOutput"

    conn.execute("INSERT INTO topics (id, name) VALUES (7, 'substrate topic')")
    conn.commit()
    from research_harness.execution.harness import ResearchHarnessBackend

    result = ResearchHarnessBackend(db=db).execute(
        "analysis_substrate_build", topic_id=7
    )
    assert result.success is True
    assert result.output.schema_version == "analysis_substrate.v1"
    assert result.output.degraded is True


def test_analysis_substrate_facade_scopes_survey_authority_to_topic(
    db, conn, monkeypatch
) -> None:
    from research_harness.knowledge.research_wiki import ResearchWikiExport
    from research_harness.primitives.analysis_impls import analysis_substrate_build
    from research_harness.primitives.types import AnalysisSubstrateOutput

    conn.execute("INSERT INTO topics (id, name) VALUES (7, 'target')")
    conn.execute("INSERT INTO topics (id, name) VALUES (8, 'other')")
    conn.execute("INSERT INTO papers (id, title) VALUES (1, 'Survey')")
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 8, 'high')"
    )
    conn.execute(
        """INSERT INTO topic_paper_notes
           (paper_id, topic_id, note_type, content)
           VALUES (1, 8, 'survey_flag', 'survey')"""
    )
    conn.commit()

    survey_page = _page(
        "methodology/survey.md",
        "Survey axis",
        "methodology",
        "Survey-derived axis.",
        _anchor("methodology/survey.md", 1, "Survey evidence."),
    )
    monkeypatch.setattr(
        "research_harness.knowledge.research_wiki.build_research_wiki_export",
        lambda *_args, **_kwargs: ResearchWikiExport(
            topic_id=7, vault_path=Path(), pages=(), graph={survey_page.page_path: []}
        ),
    )
    monkeypatch.setattr(
        "research_harness.knowledge.wiki_context_pack.build_wiki_context_pack",
        lambda *_args, **_kwargs: _pack(survey_page),
    )

    result = analysis_substrate_build(db=db, topic_id=7)
    assert isinstance(result, AnalysisSubstrateOutput)
    assert result.degraded is True
    assert result.agenda.survey_derived is False
    assert "survey_authority_unavailable" in result.warnings


def test_analysis_substrate_facade_validates_limits(db) -> None:
    from research_harness.primitives.analysis_impls import analysis_substrate_build

    for kwargs in (
        {"topic_id": 0},
        {"topic_id": 1, "max_clusters": 13},
        {"topic_id": 1, "max_relations": 0},
        {"topic_id": 1, "anchor_paper_id": 0},
    ):
        try:
            analysis_substrate_build(db=db, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {kwargs}")
