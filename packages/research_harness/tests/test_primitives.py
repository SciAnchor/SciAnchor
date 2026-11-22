from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from research_harness.paper_sources import PaperRecord, SearchQuery
from research_harness.primitives import (
    Baseline,
    Claim,
    ClaimExtractOutput,
    ConsistencyCheckOutput,
    DraftText,
    EvidenceLink,
    EvidenceLinkOutput,
    GapDetectOutput,
    PaperIngestOutput,
    PaperSearchOutput,
    PrimitiveCategory,
    PrimitiveResult,
    SectionDraftOutput,
    SummaryOutput,
    get_primitive_impl,
    list_by_category,
)
from research_harness.primitives.registry import PRIMITIVE_REGISTRY


def test_primitive_registry_has_all_specs() -> None:
    assert (
        len(PRIMITIVE_REGISTRY) == 103
    )  # +figure_package (UF09 public surface wrap of build_figure_package)
    for spec in PRIMITIVE_REGISTRY.values():
        assert spec.name
        assert spec.category
        assert spec.description
        assert spec.input_schema
        assert spec.output_type


def test_list_by_category() -> None:
    assert {spec.name for spec in list_by_category(PrimitiveCategory.RETRIEVAL)} == {
        "paper_search",
        "paper_ingest",
        "paper_acquire",
        "select_seeds",
        "expand_citations",
        "iterative_retrieval_loop",
        "method_layer_expansion",
        "cs_harvest",
        "exemplar_retrieve",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.EXTRACTION)} == {
        "claim_extract",
        "evidence_link",
        "baseline_identify",
        "lesson_extract",
        "experiment_log",
        "enrich_affiliations",
        "table_extract",
        "figure_interpret",
        "writing_pattern_extract",
        "experience_ingest",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.ANALYSIS)} == {
        "gap_detect",
        "analysis_substrate_build",
        "citation_frontier_sweep",
        "paper_coverage_check",
        "query_refine",
        "reading_prioritize",
        "method_taxonomy",
        "experiment_design_checklist",
        "evidence_matrix",
        "contradiction_detect",
        "dataset_index",
        "author_coverage",
        "metrics_aggregate",
        "meta_reflect",
        "competitive_learning",
        "direction_ranking",
        "topic_set_contributions",
        "topic_get_contributions",
        "design_gap_probe",
        "head_paper_rank",
        "cs_classify",
        "task_canonicalize",
        "compute_area_red_ocean",
        "compute_task_red_ocean",
        "compute_method_red_ocean",
        "candidate_seed",
        "candidate_upsert",
        "recommendations_generate",
        "gap_cross_verify",
        "exemplar_curate",
        "manuscript_review",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.GENERATION)} == {
        "section_draft",
        "code_generate",
        "outline_generate",
        "section_revise",
        "latex_compile",
        "rebuttal_format",
        "paper_finalize",
        "publication_pack_generate",
        "publication_pack_backfill",
        "publication_run",
        "algorithm_candidate_generate",
        "figure_generate",
        "exemplar_generate",
        "figure_suite_render",
        "figure_package",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.VERIFICATION)} == {
        "consistency_check",
        "code_validate",
        "experiment_run",
        "experiment_loop",
        "verified_registry_build",
        "verified_registry_check",
        "paper_verify_numbers",
        "citation_verify",
        "citation_sanitize",
        "evidence_trace",
        "gap_ground_verify",
        "governance_gate",
        "section_review",
        "originality_boundary_check",
        "venue_compliance_check",
        "exemplar_critique",
        "manuscript_polish",
    }
    assert {
        spec.name for spec in list_by_category(PrimitiveCategory.COMPREHENSION)
    } == {
        "paper_summarize",
        "deep_read",
        "get_deep_reading",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.SYNTHESIS)} == {
        "manuscript_unify",
        "lesson_overlay",
        "strategy_distill",
        "strategy_inject",
        "topic_export",
        "visualize_topic",
        "topic_framing",
        "writing_architecture",
        "writing_skill_aggregate",
        "figure_plan",
        "research_state_update",
        "design_brief_expand",
        "algorithm_design_refine",
        "algorithm_design_loop",
        "cold_start_run",
        "exemplar_plan",
        "figure_suite_plan",
        "logic_tree_build",
    }


def test_baseline_contract_carries_governance_fields() -> None:
    baseline = Baseline(
        name="Prior Agent Review",
        baseline_id="prior-agent-review",
        method_family="agent_review_workflow",
        facets=["human_eval"],
        relationship_to_proposal="close_prior",
        paper_ids=[1],
        source_paper_ids=[1],
    )

    assert baseline.baseline_id == "prior-agent-review"
    assert baseline.method_family == "agent_review_workflow"
    assert baseline.facets == ["human_eval"]
    assert baseline.relationship_to_proposal == "close_prior"
    assert baseline.source_paper_ids == [1]


def test_prompt_truncate_accepts_structured_values() -> None:
    from research_harness._workflow.execution.prompts import code_generate_prompt

    prompt = code_generate_prompt(
        study_spec={"objective": "local smoke", "metrics": ["execution_success"]},
        topic_summary=[{"paper": "seed"}],
    )

    assert '"objective": "local smoke"' in prompt
    assert '"paper": "seed"' in prompt


@pytest.mark.usefixtures("spc_no_results")
def test_paper_search_local(db) -> None:
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO papers (title, authors, year, venue, doi, arxiv_id, s2_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Attention Is All You Need",
                '["Vaswani"]',
                2017,
                "NeurIPS",
                "10.1000/attention",
                "1706.03762",
                "s2-attention",
            ),
        )
        conn.execute(
            """
            INSERT INTO papers (title, authors, year, venue, doi, arxiv_id, s2_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Attention for Vision Transformers",
                '["Dosovitskiy"]',
                2020,
                "ICLR",
                "10.1000/vit",
                "2010.11929",
                "s2-vit",
            ),
        )
        conn.execute(
            """
            INSERT INTO papers (title, authors, year, venue, doi, arxiv_id, s2_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Convolutional Networks",
                '["LeCun"]',
                1998,
                "IEEE",
                "10.1000/cnn",
                "9801001",
                "s2-cnn",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="attention")

    assert isinstance(result, PaperSearchOutput)
    assert result.query_used == "attention"
    titles = {paper.title for paper in result.papers}
    assert titles == {"Attention Is All You Need", "Attention for Vision Transformers"}
    assert len(result.papers) == 2
    # 2020 ICLR paper ranks above 2017 NeurIPS due to recency boost
    assert result.papers[0].year >= result.papers[1].year


@pytest.mark.usefixtures("spc_no_results")
def test_paper_search_with_topic_filter(db) -> None:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('topic-a')")
        topic_id = int(
            conn.execute("SELECT id FROM topics WHERE name = 'topic-a'").fetchone()[
                "id"
            ]
        )
        first = conn.execute(
            "INSERT INTO papers (title, authors, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?, ?)",
            (
                "Attention Is All You Need",
                '["A"]',
                "10.1000/topic-a",
                "topic-a-arxiv",
                "topic-s2-a",
            ),
        )
        conn.execute(
            "INSERT INTO papers (title, authors, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?, ?)",
            (
                "Attention and Memory",
                '["B"]',
                "10.1000/topic-b",
                "topic-b-arxiv",
                "topic-s2-b",
            ),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
            (int(first.lastrowid), topic_id, "high"),
        )
        conn.commit()
    finally:
        conn.close()

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="attention", topic_id=topic_id)

    assert [paper.title for paper in result.papers] == ["Attention Is All You Need"]


def test_paper_search_local_bm25_uses_abstract_for_recall(db) -> None:
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO papers (title, authors, year, venue, abstract, doi, arxiv_id, s2_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "A Survey of Scientific Discovery Systems",
                '["A"]',
                2024,
                "ACL",
                "Benchmarks dense retrieval and neural reranking for literature search.",
                "10.1000/scidiscovery",
                "2401.00001",
                "s2-scidiscovery",
            ),
        )
        conn.execute(
            """
            INSERT INTO papers (title, authors, year, venue, abstract, doi, arxiv_id, s2_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "A Vision Dataset Paper",
                '["B"]',
                2024,
                "CVPR",
                "Image classification and segmentation.",
                "10.1000/vision",
                "2401.00002",
                "s2-vision",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="dense retrieval reranking", local_only=True)

    assert [paper.title for paper in result.papers] == [
        "A Survey of Scientific Discovery Systems"
    ]
    assert result.papers[0].snippet.startswith("Benchmarks dense retrieval")
    assert result.papers[0].relevance_score > 0
    assert result.providers_queried == ["local", "local_only"]


def test_paper_search_falls_back_to_spc_when_the_fanout_is_empty(
    monkeypatch, db
) -> None:
    """The managed fan-out answers first; SPC fills the lane when it finds nothing.

    The order is pinned from the other side by test_managed_literature_routing
    (test_fanout_answers_first_and_spc_is_not_searched).
    """
    from research_harness.primitives.impls import paper_search

    monkeypatch.setattr(
        "research_harness.acquisition.spc_bridge.spc_search",
        lambda query, **_: [
            {"title": "From SPC", "doi": "10.1/spc", "year": 2024, "ccf_rank": "A"}
        ],
    )
    called = []
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda: called.append("fanout") or [],
    )
    result = paper_search(db=db, query="distributed control")
    assert any(paper.title == "From SPC" for paper in result.papers)
    assert result.providers_queried == ["local", "spc"]
    assert called == ["fanout"]


def test_local_search_document_text_applies_supported_title_weight(db) -> None:
    from research_harness.primitives.impls import (
        LOCAL_BM25_TITLE_WEIGHT,
        _local_search_document_text,
    )

    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO papers (title, abstract, doi, arxiv_id, s2_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Weighted Retrieval Title", "abstract evidence", "10.1000/w", "", "s2-w"),
        )
        row = conn.execute(
            "SELECT title, abstract, doi, arxiv_id, s2_id FROM papers LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    text = _local_search_document_text(row)

    assert text.count("Weighted Retrieval Title") == LOCAL_BM25_TITLE_WEIGHT
    assert "abstract evidence" in text
    assert "10.1000/w" in text
    assert "s2-w" in text


def test_local_phrase_boost_rewards_query_phrases() -> None:
    from research_harness.primitives.impls import (
        LOCAL_BM25_PHRASE_BONUS,
        _local_phrase_boost,
        _query_phrases,
    )

    query = "dense retrieval for literature search"

    assert "dense retrieval" in _query_phrases(query)
    assert (
        _local_phrase_boost(
            query,
            "this abstract studies dense retrieval for literature search",
        )
        >= LOCAL_BM25_PHRASE_BONUS * 2
    )
    assert _local_phrase_boost(query, "token overlap without adjacency") == 0.0


@pytest.mark.usefixtures("spc_no_results")
def test_paper_ingest_new(db) -> None:
    impl = get_primitive_impl("paper_ingest")
    assert impl is not None

    result = impl(db=db, source="10.1000/new-doi")

    assert isinstance(result, PaperIngestOutput)
    assert result.status == "new"
    assert result.paper_id > 0


@pytest.mark.usefixtures("spc_no_results")
def test_paper_ingest_duplicate(db) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?)",
            ("Known Paper", "10.1000/dup", "dup-arxiv", "dup-s2"),
        )
        conn.commit()
    finally:
        conn.close()

    impl = get_primitive_impl("paper_ingest")
    assert impl is not None
    result = impl(db=db, source="10.1000/dup")

    assert result.status == "existing"


def test_normalize_relevance() -> None:
    from research_harness.primitives.impls import _normalize_relevance

    # Categorical labels pass through
    assert _normalize_relevance("high") == "high"
    assert _normalize_relevance("medium") == "medium"
    assert _normalize_relevance("low") == "low"
    assert _normalize_relevance("HIGH") == "high"

    # Float-like strings map to buckets
    assert _normalize_relevance("0.9") == "high"
    assert _normalize_relevance("0.7") == "high"
    assert _normalize_relevance("0.5") == "medium"
    assert _normalize_relevance("0.4") == "medium"
    assert _normalize_relevance("0.3") == "low"
    assert _normalize_relevance("0.0") == "low"

    # Aliases
    assert _normalize_relevance("core") == "high"
    assert _normalize_relevance("peripheral") == "low"

    # Unknown strings default to medium
    assert _normalize_relevance("unknown") == "medium"
    assert _normalize_relevance("") == "medium"


@pytest.mark.usefixtures("spc_no_results")
def test_paper_ingest_normalizes_relevance(db) -> None:
    # Create a topic
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('test-topic')")
        conn.commit()
        topic_id = conn.execute(
            "SELECT id FROM topics WHERE name = 'test-topic'"
        ).fetchone()["id"]
    finally:
        conn.close()

    impl = get_primitive_impl("paper_ingest")
    assert impl is not None

    # Pass a float-like relevance
    result = impl(
        db=db, source="10.1000/float-rel", topic_id=topic_id, relevance="0.85"
    )
    assert result.paper_id > 0

    # Verify it was stored as "high" not "0.85"
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT relevance FROM paper_topics WHERE paper_id = ? AND topic_id = ?",
            (result.paper_id, topic_id),
        ).fetchone()
        assert row["relevance"] == "high"
    finally:
        conn.close()


def test_primitive_result_hashing() -> None:
    result = PrimitiveResult(
        primitive="paper_search",
        success=True,
        output=PaperSearchOutput(),
    )

    input_hash_1 = result.input_hash({"query": "transformer", "limit": 5})
    input_hash_2 = result.input_hash({"limit": 5, "query": "transformer"})
    output_hash_1 = result.output_hash()
    output_hash_2 = result.output_hash()

    assert input_hash_1 == input_hash_2
    assert output_hash_1 == output_hash_2


def test_claim_id_generation() -> None:
    claim = Claim(claim_id="", content="Transformers improve translation quality.")
    assert claim.claim_id.startswith("claim_")
    assert len(claim.claim_id) == 18


def test_frozen_dataclasses() -> None:
    outputs = [
        PaperSearchOutput(),
        PaperIngestOutput(paper_id=1, title="x", status="new"),
        SummaryOutput(paper_id=1, summary="x"),
        ClaimExtractOutput(),
        EvidenceLinkOutput(
            link=EvidenceLink(claim_id="c", source_type="paper", source_id="1")
        ),
        GapDetectOutput(),
        SectionDraftOutput(draft=DraftText(section="intro", content="hi")),
        ConsistencyCheckOutput(),
    ]

    for output in outputs:
        try:
            output.sentinel = 1  # type: ignore[attr-defined]
        except FrozenInstanceError:
            continue
        raise AssertionError(f"{type(output).__name__} is not frozen")


# ---------------------------------------------------------------------------
# Multi-provider search tests
# ---------------------------------------------------------------------------


class _StubProvider:
    name = "stub"

    def __init__(self, records: list[PaperRecord]):
        self._records = records

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        return self._records


class _QueryAwareStubProvider:
    name = "query-aware-stub"

    def __init__(self, responses: dict[str, list[PaperRecord]]):
        self._responses = responses
        self.calls: list[SearchQuery] = []

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        self.calls.append(query)
        return self._responses.get(query.query, [])


class _NamedStubProvider:
    def __init__(self, name: str, records: list[PaperRecord]):
        self.name = name
        self.records = records
        self.calls: list[SearchQuery] = []

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        self.calls.append(query)
        return self.records


def test_paper_search_with_external_providers(db, monkeypatch) -> None:
    """External provider results appear in output."""
    stub_records = [
        PaperRecord(
            title="External Paper on Transformers",
            authors=["Smith"],
            year=2024,
            venue="NeurIPS",
            doi="10.1000/ext-1",
            arxiv_id="2401.00001",
            provider="stub",
            citation_count=50,
            abstract="A study of transformers.",
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="transformers")

    assert isinstance(result, PaperSearchOutput)
    assert result.provider == "multi"
    assert "stub" in result.providers_queried
    assert len(result.papers) >= 1
    titles = [p.title for p in result.papers]
    assert "External Paper on Transformers" in titles


def test_paper_search_filters_provider_suite_by_allow_and_deny_lists(
    db,
    monkeypatch,
) -> None:
    """Paper-production can bound slow/rate-limited providers at the primitive seam."""

    arxiv = _NamedStubProvider(
        "arxiv",
        [
            PaperRecord(
                title="Allowed Provider Paper",
                year=2025,
                venue="arXiv",
                arxiv_id="2501.00001",
                provider="arxiv",
            )
        ],
    )
    semantic_scholar = _NamedStubProvider(
        "semantic_scholar",
        [
            PaperRecord(
                title="Denied Semantic Scholar Paper",
                year=2025,
                venue="ACL",
                s2_id="denied",
                provider="semantic_scholar",
            )
        ],
    )
    pasa = _NamedStubProvider(
        "pasa",
        [
            PaperRecord(
                title="Denied PASA Paper",
                year=2025,
                venue="preprint",
                provider="pasa",
            )
        ],
    )
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [arxiv, semantic_scholar, pasa],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(
        db=db,
        query="bounded provider paper search",
        provider_allowlist=["arxiv", "crossref", "openalex", "openreview", "pubmed"],
        provider_denylist=["semantic_scholar", "pasa"],
        per_provider_limit=7,
    )

    assert [call.per_provider_limit for call in arxiv.calls] == [7]
    assert semantic_scholar.calls == []
    assert pasa.calls == []
    assert "arxiv" in result.providers_queried
    assert "semantic_scholar" not in result.providers_queried
    assert "pasa" not in result.providers_queried
    assert [paper.title for paper in result.papers] == ["Allowed Provider Paper"]


def test_paper_search_provider_filters_accept_comma_strings(db, monkeypatch) -> None:
    """Transport adapters may pass provider filters as comma-separated strings."""

    arxiv = _NamedStubProvider(
        "arxiv",
        [
            PaperRecord(
                title="Allowed Provider Paper",
                year=2025,
                venue="arXiv",
                arxiv_id="2501.00001",
                provider="arxiv",
            )
        ],
    )
    pasa = _NamedStubProvider(
        "pasa",
        [
            PaperRecord(
                title="Denied PASA Paper",
                year=2025,
                venue="preprint",
                provider="pasa",
            )
        ],
    )
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [arxiv, pasa],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(
        db=db,
        query="bounded provider paper search",
        provider_allowlist="arxiv, openreview",
        provider_denylist="pasa",
    )

    assert arxiv.calls
    assert pasa.calls == []
    assert "arxiv" in result.providers_queried
    assert "pasa" not in result.providers_queried


def test_paper_search_tier_filter(db, monkeypatch) -> None:
    """tier_filter excludes papers below threshold."""
    stub_records = [
        PaperRecord(
            title="Top Venue Paper",
            year=2024,
            venue="NeurIPS",
            doi="10.1000/top",
            provider="stub",
        ),
        PaperRecord(
            title="Workshop Paper",
            year=2024,
            venue="Unknown Workshop",
            doi="10.1000/ws",
            provider="stub",
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="paper", tier_filter="ccf_b")

    titles = [p.title for p in result.papers]
    assert "Top Venue Paper" in titles
    assert "Workshop Paper" not in titles


def test_paper_search_auto_ingest(db, monkeypatch) -> None:
    """auto_ingest stores results in the paper pool."""
    stub_records = [
        PaperRecord(
            title="Auto Ingest Test Paper",
            year=2024,
            venue="CVPR",
            doi="10.1000/auto-ingest",
            provider="stub",
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="ingest test", auto_ingest=True)

    assert result.ingested_count >= 1

    # Verify paper exists in DB
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT title FROM papers WHERE doi = ?", ("10.1000/auto-ingest",)
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_paper_search_auto_ingest_preserves_acquisition_relevance(db, monkeypatch):
    """O1 regression: search relevance must survive ingestion and strict selection."""
    from research_harness.acquisition.pipeline import _build_candidates

    conn = db.connect()
    try:
        topic_id = conn.execute(
            "INSERT INTO topics (name) VALUES ('ingest-acquisition-regression')"
        ).lastrowid
        conn.commit()
    finally:
        conn.close()
    records = [
        PaperRecord(title=title, doi=f"10.1000/ingest-{band}", provider="stub")
        for band, title in (
            ("high", "Network Security Attack Detection"),
            ("medium", "Network Security"),
            ("low", "Network"),
        )
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(records)],
    )
    result = get_primitive_impl("paper_search")(
        db=db,
        query="network security attack detection",
        topic_id=topic_id,
        auto_ingest=True,
    )
    assert result.ingested_count == 3
    assert {ref.relevance_score for ref in result.papers} == {1.0, 0.5, 0.25}
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT p.doi, pt.relevance, pt.screening_status, "
            "pt.manuscript_eligible, pt.evidence_role FROM paper_topics pt "
            "JOIN papers p ON p.id = pt.paper_id WHERE pt.topic_id = ?",
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()
    assert {row["doi"]: tuple(row)[1:] for row in rows} == {
        "10.1000/ingest-high": ("high", "screened_in", 1, "unreviewed"),
        "10.1000/ingest-medium": ("medium", "screened_in", 1, "unreviewed"),
        "10.1000/ingest-low": ("low", "candidate", 0, "unreviewed"),
    }
    assert {paper.doi for paper in _build_candidates(db, topic_id)} == {
        "10.1000/ingest-high",
        "10.1000/ingest-medium",
    }
    assert len(_build_candidates(db, topic_id, include_candidates=True)) == 3


@pytest.mark.parametrize("status,eligible", [("screened_in", 1), ("screened_out", 0)])
def test_auto_ingest_preserves_curated_topic_decisions(db, status, eligible):
    from research_harness.primitives.impls import _auto_ingest_refs
    from research_harness.primitives import PaperRef

    conn = db.connect()
    try:
        topic_id = conn.execute(
            "INSERT INTO topics (name) VALUES ('curated')"
        ).lastrowid
        paper_id = conn.execute(
            "INSERT INTO papers (title, doi) VALUES ('Curated paper', '10.1000/curated')"
        ).lastrowid
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance, screening_status, "
            "evidence_role, manuscript_eligible, screening_reason, candidate_source) "
            "VALUES (?, ?, 'high', ?, 'core', ?, 'human-approved', 'manual')",
            (paper_id, topic_id, status, eligible),
        )
        conn.commit()
        before = tuple(conn.execute("SELECT * FROM paper_topics").fetchone())
        for score in (0.5, 0.25, 1.0):
            assert (
                _auto_ingest_refs(
                    db,
                    [
                        PaperRef(
                            title="Curated paper",
                            doi="10.1000/curated",
                            relevance_score=score,
                        )
                    ],
                    topic_id,
                )
                == 1
            )
            assert (
                tuple(conn.execute("SELECT * FROM paper_topics").fetchone()) == before
            )
    finally:
        conn.close()


def test_auto_ingest_promotes_unscreened_candidate_once(db):
    from research_harness.acquisition.pipeline import _build_candidates
    from research_harness.primitives.impls import _auto_ingest_refs
    from research_harness.primitives import PaperRef

    conn = db.connect()
    try:
        topic_id = conn.execute(
            "INSERT INTO topics (name) VALUES ('candidate')"
        ).lastrowid
        conn.commit()
    finally:
        conn.close()
    for score, expected_count in ((0.25, 0), (0.5, 1), (0.25, 1)):
        assert (
            _auto_ingest_refs(
                db,
                [
                    PaperRef(
                        title="Candidate paper",
                        doi="10.1000/candidate",
                        relevance_score=score,
                    )
                ],
                topic_id,
            )
            == 1
        )
        assert len(_build_candidates(db, topic_id)) == expected_count


def test_paper_search_recency_ranking(db, monkeypatch) -> None:
    """Recent papers rank above older ones with equal relevance."""
    stub_records = [
        PaperRecord(
            title="Recent Attention Model",
            year=2024,
            venue="CVPR",
            provider="stub",
        ),
        PaperRecord(
            title="Old Attention Model",
            year=2010,
            venue="CVPR",
            provider="stub",
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="attention model")

    assert len(result.papers) == 2
    assert result.papers[0].title == "Recent Attention Model"


def test_paper_search_dedup_across_sources(db, monkeypatch) -> None:
    """Same paper from local and external is deduplicated."""
    # Insert in local DB
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, authors, year, venue, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "Attention Is All You Need",
                '["Vaswani"]',
                2017,
                "NeurIPS",
                "10.1000/attention",
                "1706.03762",
                "",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Same paper from external with citation_count
    stub_records = [
        PaperRecord(
            title="Attention Is All You Need",
            year=2017,
            venue="NeurIPS",
            doi="10.1000/attention",
            arxiv_id="1706.03762",
            provider="stub",
            citation_count=100000,
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="attention")

    # Should be exactly 1 result (deduplicated)
    attention_papers = [
        p for p in result.papers if "Attention Is All You Need" in p.title
    ]
    assert len(attention_papers) == 1
    # Should have citation_count from external
    assert attention_papers[0].citation_count == 100000


def test_paper_search_venue_tier_enrichment(db, monkeypatch) -> None:
    """Results include venue_tier labels."""
    stub_records = [
        PaperRecord(
            title="A NeurIPS Paper",
            year=2024,
            venue="NeurIPS",
            provider="stub",
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="neurips paper")

    assert len(result.papers) >= 1
    paper = result.papers[0]
    assert "CCF-A*" in paper.venue_tier


def test_paper_search_underfilled_topic_runs_survey_seed_before_original_query(
    db, monkeypatch
) -> None:
    current_year = datetime.now(timezone.utc).year
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('survey-first')")
        topic_id = int(
            conn.execute(
                "SELECT id FROM topics WHERE name = 'survey-first'"
            ).fetchone()["id"]
        )
        conn.commit()
    finally:
        conn.close()

    provider = _QueryAwareStubProvider(
        {
            "agentic retrieval survey": [
                PaperRecord(
                    title="A Survey of Agentic Retrieval Graph RAG Evaluation",
                    year=current_year,
                    venue="NeurIPS",
                    doi="10.1000/survey-seed",
                    provider="stub",
                    abstract="Maps graph rag evaluation and benchmark facets.",
                )
            ],
            "agentic retrieval graph rag evaluation": [
                PaperRecord(
                    title="Graph RAG Evaluation Benchmark",
                    year=current_year,
                    venue="CVPR",
                    doi="10.1000/facet-hit",
                    provider="stub",
                )
            ],
            "agentic retrieval": [
                PaperRecord(
                    title="Agentic Retrieval System",
                    year=current_year,
                    venue="ICLR",
                    doi="10.1000/original-hit",
                    provider="stub",
                )
            ],
        }
    )
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [provider],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="agentic retrieval", topic_id=topic_id)

    calls = [call.query for call in provider.calls]
    assert calls[0] == "agentic retrieval survey"
    assert provider.calls[0].year_from == current_year - 1
    assert provider.calls[0].year_to is None
    assert "agentic retrieval graph rag evaluation" in calls
    assert "agentic retrieval" in calls
    titles = {paper.title for paper in result.papers}
    assert "A Survey of Agentic Retrieval Graph RAG Evaluation" in titles
    assert "Graph RAG Evaluation Benchmark" in titles
    assert "Agentic Retrieval System" in titles
    assert result.ingested_count == 0


def test_survey_first_retrieval_policy_component_documents_internal_guardrails():
    from research_harness.primitives.impls import survey_first_retrieval_policy

    policy = survey_first_retrieval_policy()

    assert policy.schema_version == "survey_first_retrieval_policy.v1"
    assert policy.status == "stable_internal"
    assert policy.topic_paper_floor == 5
    assert policy.facet_query_limit == 2
    assert policy.auto_ingest_policy == (
        "disable_survey_first_when_auto_ingest_is_enabled"
    )
    assert "underfilled_topic_seed_first" in policy.guardrails
    assert "normal_topic_no_extra_seed_fanout" in policy.guardrails
    assert "auto_ingest_original_query_only" in policy.guardrails
    assert "no_survey_hits_fallback_to_original_query" in policy.guardrails


def test_survey_first_policy_doc_records_stable_internal_guardrails():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    text = (
        repo_root / "docs" / "contracts" / "survey-first-retrieval-policy.md"
    ).read_text(encoding="utf-8")

    for required in (
        "survey_first_retrieval_policy.v1",
        "stable internal retrieval policy",
        "under-filled topics run survey seed first",
        "normal topics do not incur extra seed fanout",
        "auto_ingest never ingests survey or facet results",
        "no-survey fallback preserves original retrieval behavior",
    ):
        assert required in text


def test_paper_search_normal_topic_skips_survey_seed_fanout(db, monkeypatch) -> None:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('normal-survey-topic')")
        topic_id = int(
            conn.execute(
                "SELECT id FROM topics WHERE name = 'normal-survey-topic'"
            ).fetchone()["id"]
        )
        for index in range(5):
            row = conn.execute(
                """
                INSERT INTO papers (title, doi, arxiv_id, s2_id)
                VALUES (?, ?, ?, ?)
                """,
                (
                    f"Existing Topic Paper {index}",
                    f"10.1000/existing-{index}",
                    f"existing-{index}",
                    f"s2-existing-{index}",
                ),
            )
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, 'high')",
                (int(row.lastrowid), topic_id),
            )
        conn.commit()
    finally:
        conn.close()

    provider = _QueryAwareStubProvider(
        {
            "mature retrieval survey": [
                PaperRecord(
                    title="Mature Retrieval Survey",
                    year=datetime.now(timezone.utc).year,
                    venue="NeurIPS",
                    doi="10.1000/mature-survey",
                    provider="stub",
                )
            ],
            "mature retrieval": [
                PaperRecord(
                    title="Mature Retrieval System",
                    year=datetime.now(timezone.utc).year,
                    venue="ICLR",
                    doi="10.1000/mature-original",
                    provider="stub",
                )
            ],
        }
    )
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [provider],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="mature retrieval", topic_id=topic_id)

    assert [call.query for call in provider.calls] == ["mature retrieval"]
    assert [paper.title for paper in result.papers] == ["Mature Retrieval System"]


def test_paper_search_auto_ingest_never_ingests_survey_or_facet_results(
    db, monkeypatch
) -> None:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('auto-ingest-survey')")
        topic_id = int(
            conn.execute(
                "SELECT id FROM topics WHERE name = 'auto-ingest-survey'"
            ).fetchone()["id"]
        )
        conn.commit()
    finally:
        conn.close()

    current_year = datetime.now(timezone.utc).year
    provider = _QueryAwareStubProvider(
        {
            "auto ingest retrieval survey": [
                PaperRecord(
                    title="Auto Ingest Retrieval Survey",
                    year=current_year,
                    venue="NeurIPS",
                    doi="10.1000/auto-survey",
                    provider="stub",
                    abstract="Covers facet expansion.",
                )
            ],
            "auto ingest retrieval facet expansion": [
                PaperRecord(
                    title="Auto Ingest Retrieval Facet",
                    year=current_year,
                    venue="CVPR",
                    doi="10.1000/auto-facet",
                    provider="stub",
                )
            ],
            "auto ingest retrieval": [
                PaperRecord(
                    title="Auto Ingest Retrieval Original",
                    year=current_year,
                    venue="ICLR",
                    doi="10.1000/auto-original",
                    provider="stub",
                )
            ],
        }
    )
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [provider],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(
        db=db,
        query="auto ingest retrieval",
        topic_id=topic_id,
        auto_ingest=True,
    )

    assert [call.query for call in provider.calls] == ["auto ingest retrieval"]
    assert result.ingested_count == 1

    conn = db.connect()
    try:
        links = [
            dict(row)
            for row in conn.execute(
                """
                SELECT p.title, pt.relevance, pt.screening_status,
                       pt.evidence_role, pt.manuscript_eligible,
                       pt.screening_reason, pt.candidate_source
                FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                ORDER BY p.title
                """,
                (topic_id,),
            ).fetchall()
        ]
    finally:
        conn.close()

    assert [link["title"] for link in links] == ["Auto Ingest Retrieval Original"]
    assert links[0]["relevance"] == "high"
    assert links[0]["screening_status"] == "screened_in"
    assert links[0]["evidence_role"] == "unreviewed"
    assert links[0]["manuscript_eligible"] == 1
    assert links[0]["screening_reason"] == "auto_screened_relevance_score=1.000"
    assert links[0]["candidate_source"] == "paper_search"


def test_paper_search_survey_first_degrades_to_original_query_without_survey_hits(
    db, monkeypatch
) -> None:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('no-survey')")
        topic_id = int(
            conn.execute("SELECT id FROM topics WHERE name = 'no-survey'").fetchone()[
                "id"
            ]
        )
        conn.commit()
    finally:
        conn.close()

    provider = _QueryAwareStubProvider(
        {
            "cold start survey": [
                PaperRecord(
                    title="Cold Start Retrieval Workshop Note",
                    year=datetime.now(timezone.utc).year,
                    venue="Unknown Workshop",
                    doi="10.1000/workshop-note",
                    provider="stub",
                )
            ],
            "cold start": [
                PaperRecord(
                    title="Cold Start Retrieval",
                    year=datetime.now(timezone.utc).year,
                    venue="ICLR",
                    doi="10.1000/cold-start",
                    provider="stub",
                )
            ],
        }
    )
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [provider],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="cold start", topic_id=topic_id)

    assert [call.query for call in provider.calls] == [
        "cold start survey",
        "cold start",
    ]
    assert [paper.title for paper in result.papers] == ["Cold Start Retrieval"]


def test_paper_search_survey_seed_requires_recent_high_tier_survey(
    db, monkeypatch
) -> None:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('strict-survey')")
        topic_id = int(
            conn.execute(
                "SELECT id FROM topics WHERE name = 'strict-survey'"
            ).fetchone()["id"]
        )
        conn.commit()
    finally:
        conn.close()

    current_year = datetime.now(timezone.utc).year
    provider = _QueryAwareStubProvider(
        {
            "planning agent survey": [
                PaperRecord(
                    title="Planning Agent Survey Preprint",
                    year=current_year,
                    venue="arXiv",
                    doi="10.1000/preprint-survey",
                    provider="stub",
                ),
                PaperRecord(
                    title="Planning Agent Survey Workshop",
                    year=current_year,
                    venue="Unknown Workshop",
                    doi="10.1000/workshop-survey",
                    provider="stub",
                ),
                PaperRecord(
                    title="Planning Agent Survey at NeurIPS",
                    year=current_year - 3,
                    venue="NeurIPS",
                    doi="10.1000/old-survey",
                    provider="stub",
                ),
            ],
            "planning agent": [
                PaperRecord(
                    title="Planning Agent Retrieval",
                    year=current_year,
                    venue="NeurIPS",
                    doi="10.1000/planning-agent",
                    provider="stub",
                )
            ],
        }
    )
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [provider],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="planning agent", topic_id=topic_id)

    assert [call.query for call in provider.calls] == [
        "planning agent survey",
        "planning agent",
    ]
    assert [paper.title for paper in result.papers] == ["Planning Agent Retrieval"]


def test_paper_search_auto_ingest_persists_identifiers_and_candidates(
    db, monkeypatch
) -> None:
    """Auto-ingest keeps pmid/pmcid/abstract, picks a public PDF URL over the
    landing page, stores the candidate list, and does not double-encode authors."""
    import json as _json

    from research_harness.acquisition.candidate_store import load_pdf_candidates
    from research_harness.paper_sources import PDFCandidate

    stub_records = [
        PaperRecord(
            title="Rich Metadata Paper",
            authors=["A. Author", "B. Author"],
            year=2024,
            # A tiered venue forces the _enrich_venue_tier rebuild path, which
            # must carry pmid/pmcid/abstract/pdf_candidates through.
            venue="CVPR",
            doi="10.1186/s12870-023-04512-4",
            pmid="37940856",
            pmcid="PMC10634832",
            abstract="Nitrogen deposition alters dryland shrub root traits. " * 10,
            url="https://www.semanticscholar.org/paper/landing",
            provider="stub",
            pdf_candidates=[
                PDFCandidate(
                    url="https://content.openalex.org/works/W1.pdf",
                    source_type="openalex_content",
                    provider="openalex",
                    confidence=0.85,
                ),
                PDFCandidate(
                    url="https://oa.example.org/paper.pdf",
                    source_type="open_access_pdf",
                    provider="openalex",
                    confidence=0.95,
                ),
            ],
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="rich metadata", auto_ingest=True)

    assert result.ingested_count >= 1
    ref = next(p for p in result.papers if p.title == "Rich Metadata Paper")
    assert ref.pmid == "37940856"
    assert ref.pmcid == "PMC10634832"
    assert any(c["source_type"] == "open_access_pdf" for c in ref.pdf_candidates)

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM papers WHERE doi = ?", ("10.1186/s12870-023-04512-4",)
        ).fetchone()
        assert row is not None
        assert row["pmid"] == "37940856"
        assert row["pmcid"] == "PMC10634832"
        assert (row["abstract"] or "").startswith("Nitrogen deposition")
        # Public OA PDF beats the landing page and the auth-gated OpenAlex route.
        assert row["url"] == "https://oa.example.org/paper.pdf"
        # Authors stored as a plain JSON list, not a double-encoded string.
        assert _json.loads(row["authors"]) == ["A. Author", "B. Author"]

        stored = load_pdf_candidates(conn, int(row["id"]))
        stored_urls = [item["url"] for item in stored]
        assert "https://oa.example.org/paper.pdf" in stored_urls
        assert "https://content.openalex.org/works/W1.pdf" in stored_urls
    finally:
        conn.close()
