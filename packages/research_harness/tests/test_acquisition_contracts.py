from __future__ import annotations

import json

from research_harness.paper_sources import PaperRecord


def _search_brief() -> dict:
    return {
        "schema_version": "seed-paper-curator.search-brief.v1",
        "topic": "retrieval augmented generation",
        "domain": "ai",
        "research_question": "How should RAG systems retrieve evidence for long tasks?",
        "scope": {
            "include": ["retrieval", "long context"],
            "exclude": ["web search products"],
            "time_window": {"from": 2020, "to": 2026},
            "document_types": ["conference_paper", "journal_article"],
        },
        "concepts": {
            "target_system": ["RAG"],
            "research_task": ["evidence retrieval"],
            "method_families": ["hybrid retrieval"],
            "evidence_modalities": ["benchmarks"],
            "synonyms": ["retrieval-augmented generation"],
            "abbreviations": {"RAG": "retrieval augmented generation"},
        },
        "source_strategy": {
            "selected": [
                {"source": "openalex", "reason": "broad recall"},
                {"source": "semantic_scholar", "reason": "citation signals"},
            ],
            "skipped": [{"source": "closed_proxy", "reason": "not default in RH"}],
        },
        "query_families": {
            "core": ["retrieval augmented generation evidence"],
            "synonym_expansion": ["RAG long context retrieval"],
            "method_modality": ["hybrid retrieval benchmark"],
            "survey_review": ["RAG survey"],
            "benchmark_dataset": ["RAG benchmark dataset"],
            "venue_probe": ["NeurIPS RAG retrieval"],
        },
        "recall_plan": {
            "execution_strategy": "per_source_parallel",
            "per_query_limit": 50,
            "total_candidate_budget": 500,
            "dedup_point": "after_all_sources_complete",
            "metadata_search": True,
            "manual_seed_probe": True,
            "oa_enrichment": "top_seeds_only",
        },
        "quality_gate": {
            "ready_for_candidate_recall": True,
            "requires_user_confirmation": [],
            "known_risks": ["S2 rate limit"],
        },
        "manual_seeds": [
            {
                "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP",
                "doi": "10.5555/test",
                "year": 2020,
                "reason": "canonical seed",
                "source": "user_supplied",
            }
        ],
    }


def test_search_brief_contract_preserves_scope_fields() -> None:
    from research_harness.acquisition.brief import normalize_search_brief

    normalized = normalize_search_brief(_search_brief())

    assert normalized["schema_version"] == "rh.acquisition_search_brief.v1"
    assert normalized["source_schema"] == "seed-paper-curator.search-brief.v1"
    assert normalized["brief"]["scope"]["include"] == ["retrieval", "long context"]
    assert normalized["brief"]["scope"]["exclude"] == ["web search products"]
    assert normalized["brief"]["scope"]["time_window"] == {"from": 2020, "to": 2026}
    assert normalized["brief"]["scope"]["document_types"] == [
        "conference_paper",
        "journal_article",
    ]
    assert normalized["brief"]["source_strategy"]["selected"][0]["source"] == "openalex"
    assert normalized["brief"]["query_families"]["venue_probe"] == [
        "NeurIPS RAG retrieval"
    ]
    assert normalized["preserved_fields"] == [
        "topic",
        "domain",
        "research_question",
        "scope.include",
        "scope.exclude",
        "scope.time_window",
        "scope.document_types",
        "concepts.target_system",
        "concepts.research_task",
        "concepts.method_families",
        "concepts.evidence_modalities",
        "concepts.synonyms",
        "concepts.abbreviations",
        "source_strategy.selected",
        "source_strategy.skipped",
        "query_families",
        "recall_plan",
        "quality_gate",
        "manual_seeds",
    ]


def test_record_topic_acquisition_brief_uses_project_artifact(db) -> None:
    from research_harness.acquisition.brief import record_topic_acquisition_brief

    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'rag')")
        conn.commit()
    finally:
        conn.close()

    artifact_id = record_topic_acquisition_brief(db, 1, _search_brief())

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT topic_id, stage, artifact_type, payload_json, metadata_json "
            "FROM project_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    finally:
        conn.close()

    payload = json.loads(row["payload_json"])
    metadata = json.loads(row["metadata_json"])
    assert row["topic_id"] == 1
    assert row["stage"] == "acquisition"
    assert row["artifact_type"] == "acquisition_search_brief"
    assert payload["brief"]["quality_gate"]["ready_for_candidate_recall"] is True
    assert metadata["contract"] == "seed-paper-curator.search-brief.v1"
    assert "scope.include" in metadata["preserved_fields"]


def test_field_provenance_package_preserves_venue_ranking_contract() -> None:
    from research_harness.acquisition.metadata import paper_metadata_package_from_record

    record = PaperRecord(
        title="Venue Paper",
        venue="International Conference on Machine Learning",
        journal="",
        publisher="PMLR",
        document_type="conference_paper",
        provider="openalex",
        citation_count=42,
        reference_count=31,
        source_refs=[
            {
                "source": "openalex",
                "field": "venue",
                "value": "International Conference on Machine Learning",
                "query_or_endpoint": "/works/W1",
                "confidence": 0.92,
                "retrieved_at": "2026-07-01T00:00:00Z",
            },
            {
                "source": "ccf_directory",
                "field": "ccf_rank",
                "value": "A",
                "query_or_endpoint": "venue_ranks_cs_2024.json",
                "confidence": 0.88,
                "retrieved_at": "2026-07-01T00:00:00Z",
            },
        ],
        recorded_facts={
            "venue_metadata": {
                "ccf_rank": "A",
                "ccf_subject": "AI",
                "cas_zone": "1",
                "cas_top_journal": False,
                "venue_match_name": "ICML",
                "venue_metadata_source": "venue_ranks_cs_2024.json",
            }
        },
        selection_basis=["high recall seed"],
        curation_signals={"selection_bucket": "seed"},
    )

    package = paper_metadata_package_from_record(record)

    assert package["schema_version"] == "rh.paper_metadata_facts.v1"
    facts = package["recorded_facts"]
    assert facts["venue_metadata"]["ccf_rank"] == "A"
    assert facts["venue_metadata"]["venue_match_name"] == "ICML"
    assert facts["citation_count"] == 42
    assert facts["reference_count"] == 31
    assert package["source_refs"][1]["source"] == "ccf_directory"
    assert package["curation_signals"]["selection_basis"] == ["high recall seed"]
    assert package["curation_signals"]["quality_score"] is None


def test_search_aggregator_records_field_conflicts_instead_of_overwriting_silently() -> (
    None
):
    from research_harness.paper_sources import SearchAggregator, SearchQuery

    class Provider:
        def __init__(self, name: str, records: list[PaperRecord]) -> None:
            self.name = name
            self._records = records

        def search(self, query: SearchQuery) -> list[PaperRecord]:
            del query
            return list(self._records)

    low = Provider(
        "google_scholar",
        [
            PaperRecord(
                title="Conflict Paper",
                year=2024,
                venue="NIPS",
                provider="google_scholar",
                recorded_facts={"venue_metadata": {"ccf_rank": "B"}},
            )
        ],
    )
    high = Provider(
        "openalex",
        [
            PaperRecord(
                title="Conflict Paper",
                year=2024,
                venue="NeurIPS",
                provider="openalex",
                recorded_facts={"venue_metadata": {"ccf_rank": "A"}},
            )
        ],
    )

    record = (
        SearchAggregator([low, high]).search(SearchQuery(query="conflict")).results[0]
    )

    assert record.venue == "NeurIPS"
    assert record.recorded_facts["venue_metadata"]["ccf_rank"] == "A"
    assert record.field_conflicts == [
        {
            "field": "venue",
            "values": [
                {"source": "google_scholar", "value": "NIPS"},
                {"source": "openalex", "value": "NeurIPS"},
            ],
            "selected_source": "openalex",
        },
        {
            "field": "recorded_facts.venue_metadata",
            "values": [
                {"source": "google_scholar", "value": {"ccf_rank": "B"}},
                {"source": "openalex", "value": {"ccf_rank": "A"}},
            ],
            "selected_source": "openalex",
        },
    ]


def test_search_aggregator_keeps_non_conflicting_lower_priority_facts() -> None:
    from research_harness.paper_sources import merge_records

    high = PaperRecord(
        title="Fact Paper",
        year=2024,
        venue="NeurIPS",
        provider="openalex",
        recorded_facts={
            "venue_metadata": {"ccf_rank": "A"},
            "citation_count": 100,
        },
    )
    low = PaperRecord(
        title="Fact Paper",
        year=2024,
        venue="NIPS",
        provider="google_scholar",
        recorded_facts={
            "venue_metadata": {"ccf_rank": "B"},
            "reference_count": 31,
        },
    )

    record = merge_records(high, low)

    assert record.recorded_facts == {
        "venue_metadata": {"ccf_rank": "A"},
        "citation_count": 100,
        "reference_count": 31,
    }
    assert record.field_conflicts == [
        {
            "field": "venue",
            "values": [
                {"source": "openalex", "value": "NeurIPS"},
                {"source": "google_scholar", "value": "NIPS"},
            ],
            "selected_source": "openalex",
        },
        {
            "field": "recorded_facts.venue_metadata",
            "values": [
                {"source": "openalex", "value": {"ccf_rank": "A"}},
                {"source": "google_scholar", "value": {"ccf_rank": "B"}},
            ],
            "selected_source": "openalex",
        },
    ]


def test_process_results_records_route_audit_without_pdf_path_on_identity_mismatch(
    db, tmp_path
) -> None:
    from research_harness.acquisition import pipeline
    from research_harness.acquisition.downloader import DownloadResult
    from research_harness.acquisition.routes import PDFRouteAttempt, PDFRouteAudit

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (id, title, pdf_path, status) VALUES (1, 'Wrong PDF', '', 'meta_only')"
        )
        conn.commit()
    finally:
        conn.close()

    result = DownloadResult(
        paper_id=1,
        status="needs_manual",
        failure_reason="pdf identity verification failed",
        audit=PDFRouteAudit(
            paper_id=1,
            failure_taxonomy="identity_mismatch",
            attempts=[
                PDFRouteAttempt(
                    route="metadata_open_access",
                    url="https://example.org/wrong.pdf?token=secret",
                    host="example.org",
                    error_class="identity_mismatch",
                    error="no title/DOI/PMID signal in extracted PDF text",
                )
            ],
        ),
    )
    candidate = pipeline.PaperDownloadCandidate(
        paper_id=1,
        title="Wrong PDF",
        url="https://example.org/wrong.pdf?token=secret",
    )

    report = pipeline._process_results(
        db,
        [result],
        [candidate],
        artifacts_root=tmp_path,
    )

    conn = db.connect()
    try:
        paper = conn.execute(
            "SELECT pdf_path, status FROM papers WHERE id = 1"
        ).fetchone()
        event = conn.execute(
            "SELECT detail, provider FROM pipeline_events "
            "WHERE paper_id = 1 AND event_type = 'download_route_audit'"
        ).fetchone()
        artifact = conn.execute(
            "SELECT artifact_type, metadata FROM paper_artifacts "
            "WHERE paper_id = 1 AND artifact_type = 'pdf_route_audit'"
        ).fetchone()
    finally:
        conn.close()

    assert report.needs_manual == 1
    assert paper["pdf_path"] == ""
    assert paper["status"] == "meta_only"
    event_detail = json.loads(event["detail"])
    artifact_metadata = json.loads(artifact["metadata"])
    assert event["provider"] == "identity_mismatch"
    assert event_detail["failure_taxonomy"] == "identity_mismatch"
    assert artifact_metadata["attempts"][0]["url"] == (
        "https://example.org/wrong.pdf?token=REDACTED"
    )
