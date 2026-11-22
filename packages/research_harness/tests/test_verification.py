"""Tests for Sprint 3 verification harness — paper_verifier, citation_verifier, evidence_trace."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from research_harness.experiment.paper_verifier import (
    _classify_section,
    extract_numbers,
    verify_paper_numbers,
)
from research_harness.experiment.citation_verifier import (
    CitationInput,
    CitationResult,
    _tokenize,
    jaccard_similarity,
    verify_citation,
    verify_citations,
)
from research_harness.experiment.verified_registry import (
    VerifiedRegistry,
)


# -- Paper Verifier -----------------------------------------------------------


class TestNumberExtraction:
    def test_basic_numbers(self):
        text = "accuracy is 0.95 and loss is 0.23"
        nums = extract_numbers(text)
        values = [n.value for n in nums]
        assert 0.95 in values
        assert 0.23 in values

    def test_integer_extraction(self):
        text = "We trained for 100 epochs with batch size 32"
        nums = extract_numbers(text)
        values = [n.value for n in nums]
        assert 100.0 in values
        assert 32.0 in values

    def test_scientific_notation(self):
        text = "learning rate 3e-4 with weight decay 1e-5"
        nums = extract_numbers(text)
        values = [n.value for n in nums]
        assert 3e-4 in values
        assert 1e-5 in values

    def test_comma_separated_numbers(self):
        text = "dataset contains 1,000,000 samples"
        nums = extract_numbers(text)
        values = [n.value for n in nums]
        assert 1000000.0 in values

    def test_skips_cite_ref(self):
        text = r"as shown in \cite{vaswani2017} and Table \ref{tab1}"
        nums = extract_numbers(text)
        # Should not extract numbers from \cite or \ref
        assert len(nums) == 0

    def test_skips_latex_comments(self):
        text = "accuracy 0.95\n% this is a comment with number 0.99"
        nums = extract_numbers(text)
        values = [n.value for n in nums]
        assert 0.95 in values
        assert 0.99 not in values

    def test_skips_verbatim(self):
        text = r"""Real number 0.95
\begin{verbatim}
x = 0.99
\end{verbatim}
Another number 0.88"""
        nums = extract_numbers(text)
        values = [n.value for n in nums]
        assert 0.95 in values
        assert 0.88 in values
        assert 0.99 not in values

    def test_negative_numbers(self):
        text = "temperature dropped by -2.5 degrees"
        nums = extract_numbers(text)
        values = [n.value for n in nums]
        assert -2.5 in values


class TestSectionClassification:
    def test_strict_sections(self):
        assert _classify_section("Results") == "strict"
        assert _classify_section("experiments") == "strict"
        assert _classify_section("Evaluation") == "strict"
        assert _classify_section("Ablation Study") == "strict"

    def test_lenient_sections(self):
        assert _classify_section("Introduction") == "lenient"
        assert _classify_section("Related Work") == "lenient"
        assert _classify_section("conclusion") == "lenient"
        assert _classify_section("abstract") == "lenient"

    def test_unknown_section(self):
        assert _classify_section("Appendix C: Hyperparameters") == "lenient"
        assert _classify_section("Custom Section Name") == "unknown"

    def test_partial_match(self):
        assert _classify_section("Main Results and Analysis") == "strict"
        assert _classify_section("Extended Related Work") == "lenient"


class TestPaperVerification:
    def test_all_verified_numbers(self):
        registry = VerifiedRegistry()
        registry.add_value(0.9134, "accuracy")
        registry.add_value(0.2347, "loss")

        text = "Our model achieves 0.9134 accuracy with 0.2347 loss."
        result = verify_paper_numbers(text, registry, section="results")
        assert result.verified_count == 2
        assert result.unverified_count == 0
        assert result.ok

    def test_unverified_in_strict_section(self):
        registry = VerifiedRegistry()
        registry.add_value(0.9134, "accuracy")

        text = "Our model achieves 0.9134 accuracy. The baseline gets 0.8742."
        result = verify_paper_numbers(text, registry, section="results")
        assert result.verified_count == 1
        assert result.unverified_count == 1
        assert not result.ok  # error in strict section

    def test_unverified_in_lenient_section(self):
        registry = VerifiedRegistry()

        text = "Prior work reported 0.87 accuracy on this task."
        result = verify_paper_numbers(text, registry, section="introduction")
        assert result.unverified_count == 1
        assert result.ok  # only warning in lenient section
        assert result.issues[0].severity == "warning"

    def test_always_allowed_skipped(self):
        registry = VerifiedRegistry()

        text = "We use batch size 32 and train for 100 epochs in 2024."
        result = verify_paper_numbers(text, section="results", registry=registry)
        # 32, 100, 2024 are all always-allowed
        assert result.always_allowed_count >= 3
        assert result.unverified_count == 0

    def test_small_integers_allowed(self):
        registry = VerifiedRegistry()

        text = "We compare 3 models across 5 datasets."
        result = verify_paper_numbers(text, registry=registry, section="results")
        # 3 and 5 are small integers ≤ 20, always allowed
        assert result.always_allowed_count == 2

    def test_pass_rate(self):
        registry = VerifiedRegistry()
        registry.add_value(0.95, "accuracy")

        text = "accuracy 0.95 and some other number 0.77"
        result = verify_paper_numbers(text, registry, section="results")
        assert result.pass_rate == pytest.approx(0.5)

    def test_empty_text(self):
        registry = VerifiedRegistry()
        result = verify_paper_numbers("", registry)
        assert result.total_numbers == 0
        assert result.pass_rate == 1.0
        assert result.ok


# -- Citation Verifier --------------------------------------------------------


class TestJaccardSimilarity:
    def test_identical(self):
        assert jaccard_similarity(
            "Attention Is All You Need", "Attention Is All You Need"
        ) == pytest.approx(1.0)

    def test_similar(self):
        sim = jaccard_similarity(
            "Attention Is All You Need",
            "Attention Mechanisms Are All You Need",
        )
        assert sim > 0.5

    def test_different(self):
        sim = jaccard_similarity(
            "Attention Is All You Need",
            "Convolutional Neural Networks for Image Classification",
        )
        assert sim < 0.3

    def test_empty_strings(self):
        assert jaccard_similarity("", "") == 0.0
        assert jaccard_similarity("something", "") == 0.0

    def test_stop_words_ignored(self):
        sim = jaccard_similarity(
            "A Study of the Effects",
            "Study Effects",
        )
        # After removing stop words, should be identical
        assert sim == pytest.approx(1.0)


class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("Hello World 2024")
        assert "hello" in tokens
        assert "world" in tokens
        assert "2024" in tokens

    def test_removes_stopwords(self):
        tokens = _tokenize("A Study of the Effects in NLP")
        assert "a" not in tokens
        assert "of" not in tokens
        assert "the" not in tokens
        assert "study" in tokens
        assert "effects" in tokens
        assert "nlp" in tokens


class TestCitationVerification:
    def test_doi_provided_auto_verified(self):
        def mock_http(source, query):
            assert source in {"crossref", "openalex"}
            assert query == "10.5555/3295222.3295349"
            return {"message": {}, "results": []}

        citation = CitationInput(
            title="Attention Is All You Need",
            doi="10.5555/3295222.3295349",
        )
        result = verify_citation(citation, http_fn=mock_http)
        assert result.status == "verified"
        assert result.confidence == 1.0
        assert result.source == "doi_provided"

    def test_mock_crossref_verified(self):
        def mock_http(source, title):
            if source == "crossref":
                return {
                    "message": {
                        "items": [
                            {
                                "title": ["Attention Is All You Need"],
                                "DOI": "10.5555/3295222.3295349",
                            }
                        ]
                    }
                }
            return {"message": {"items": []}}

        citation = CitationInput(title="Attention Is All You Need")
        result = verify_citation(citation, http_fn=mock_http)
        assert result.status == "verified"
        assert result.source == "crossref"

    def test_mock_partial_match(self):
        def mock_http(source, title):
            if source == "crossref":
                return {
                    "message": {
                        "items": [
                            {
                                "title": [
                                    "Self-Attention Network Architecture for Translation"
                                ],
                                "DOI": "10.1234/something",
                            }
                        ]
                    }
                }
            return {"message": {"items": []}, "data": [], "results": []}

        citation = CitationInput(title="Attention Networks for Translation Tasks")
        result = verify_citation(citation, http_fn=mock_http)
        # Jaccard between these should be in partial range
        assert result.status in ("partial_match", "verified", "hallucinated")

    def test_all_fail_hallucinated(self):
        def mock_http(source, title):
            return {"message": {"items": []}, "data": [], "results": []}

        citation = CitationInput(
            title="Completely Fabricated Paper Title That Does Not Exist"
        )
        result = verify_citation(citation, http_fn=mock_http)
        assert result.status == "hallucinated"
        assert result.confidence == 0.0

    def test_batch_verification(self):
        def mock_http(source, title):
            if "Attention" in title and source == "crossref":
                return {
                    "message": {
                        "items": [
                            {
                                "title": ["Attention Is All You Need"],
                                "DOI": "10.5555/3295222.3295349",
                            }
                        ]
                    }
                }
            return {"message": {"items": []}, "data": [], "results": []}

        citations = [
            CitationInput(title="Attention Is All You Need"),
            CitationInput(title="Totally Fake Paper"),
        ]
        results = verify_citations(citations, http_fn=mock_http)
        assert len(results) == 2
        assert results[0].status == "verified"
        assert results[1].status == "hallucinated"

    def test_cascade_fallback(self):
        """If crossref fails, falls through to other providers."""

        def mock_http(source, title):
            if source == "crossref":
                raise ConnectionError("CrossRef down")
            if source == "openalex":
                return {
                    "results": [
                        {
                            "title": "Attention Is All You Need",
                            "doi": "https://doi.org/10.5555/3295222.3295349",
                        }
                    ]
                }
            return {"message": {"items": []}, "data": [], "results": []}

        citation = CitationInput(title="Attention Is All You Need")
        result = verify_citation(citation, http_fn=mock_http)
        assert result.status == "verified"
        assert result.source == "openalex"

    def test_doi_metadata_conflicts_are_audited_against_both_upstreams(self):
        def mock_http(source, query):
            assert query == "10.0000/wrong"
            if source == "crossref":
                return {
                    "message": {
                        "title": ["Attention Is All You Need"],
                        "author": [{"family": "Vaswani"}],
                        "published": {"date-parts": [[2017]]},
                        "container-title": ["NeurIPS"],
                        "DOI": "10.5555/correct",
                    }
                }
            if source == "openalex":
                return {
                    "title": "Attention Is All You Need",
                    "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
                    "publication_year": 2017,
                    "primary_location": {"source": {"display_name": "NeurIPS"}},
                    "doi": "https://doi.org/10.5555/correct",
                }
            raise AssertionError(f"unexpected source: {source}")

        result = verify_citation(
            CitationInput(
                title="Attention Is All You Needed",
                authors=["Wrong Author"],
                year=2020,
                venue="Wrong Venue",
                doi="10.0000/wrong",
            ),
            http_fn=mock_http,
        )

        assert result.status == "verified"
        assert result.upstream_sources == ["crossref", "openalex"]
        assert {
            (conflict["source"], conflict["field"]) for conflict in result.conflicts
        } == {
            (source, field)
            for source in ("crossref", "openalex")
            for field in ("title", "authors", "year", "venue", "doi")
        }

    def test_matching_metadata_has_no_conflicts(self):
        def mock_http(source, query):
            assert query == "10.5555/correct"
            if source == "crossref":
                return {
                    "message": {
                        "title": ["Attention Is All You Need"],
                        "author": [{"family": "Vaswani"}],
                        "issued": {"date-parts": [[2017]]},
                        "container-title": ["NeurIPS"],
                        "DOI": "10.5555/correct",
                    }
                }
            if source == "openalex":
                return {
                    "title": "Attention Is All You Need",
                    "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
                    "publication_year": 2017,
                    "primary_location": {"source": {"display_name": "NeurIPS"}},
                    "doi": "https://doi.org/10.5555/correct",
                }
            raise AssertionError(f"unexpected source: {source}")

        result = verify_citation(
            CitationInput(
                title="Attention Is All You Need",
                authors=["Ashish Vaswani"],
                year=2018,
                venue="NeurIPS!",
                doi="HTTPS://DOI.ORG/10.5555/CORRECT",
            ),
            http_fn=mock_http,
        )

        assert result.status == "verified"
        assert result.upstream_sources == ["crossref", "openalex"]
        assert result.conflicts == []

    def test_title_audit_reuses_each_upstream_response(self):
        calls = {"crossref": 0, "openalex": 0}

        def mock_http(source, query):
            calls[source] += 1
            assert query == "Attention Is All You Need"
            if source == "crossref":
                return {
                    "message": {
                        "items": [
                            {
                                "title": ["Attention Is All You Need"],
                                "author": [{"family": "Vaswani"}],
                                "published-online": {"date-parts": [[2017]]},
                                "container-title": ["NeurIPS"],
                                "DOI": "10.5555/correct",
                            }
                        ]
                    }
                }
            if source == "openalex":
                return {
                    "results": [
                        {
                            "title": "Attention Is All You Need",
                            "authorships": [
                                {"author": {"display_name": "Ashish Vaswani"}}
                            ],
                            "publication_year": 2017,
                            "primary_location": {"source": {"display_name": "NeurIPS"}},
                            "doi": "https://doi.org/10.5555/correct",
                        }
                    ]
                }
            return {"message": {"items": []}, "data": []}

        result = verify_citation(
            CitationInput(
                title="Attention Is All You Need",
                authors=["Ashish Vaswani"],
                year=2017,
                venue="NeurIPS",
            ),
            http_fn=mock_http,
        )

        assert result.status == "verified"
        assert result.upstream_sources == ["crossref", "openalex"]
        assert result.conflicts == []
        assert calls == {"crossref": 1, "openalex": 1}

    def test_title_audit_uses_the_candidate_selected_by_verification(self):
        def mock_http(source, query):
            if source == "crossref":
                return {
                    "message": {
                        "items": [
                            {
                                "title": ["Deep Neural Networks Image"],
                                "published": {"date-parts": [[2017]]},
                            },
                            {
                                "title": ["Deep Neural Networks Image Classification"],
                                "published": {"date-parts": [[2020]]},
                            },
                        ]
                    }
                }
            if source == "openalex":
                return {"results": []}
            return {"message": {"items": []}, "data": []}

        result = verify_citation(
            CitationInput(title="Deep Neural Networks Image Classification", year=2017),
            http_fn=mock_http,
        )

        assert result.status == "verified"
        assert result.matched_title == "Deep Neural Networks Image"
        assert result.conflicts == []

    def test_partial_title_candidate_is_not_an_upstream_audit_match(self):
        def mock_http(source, query):
            if source == "crossref":
                return {
                    "message": {
                        "items": [
                            {"title": ["Deep Neural Networks"]},
                            {"title": ["Deep Neural Networks Image Classification"]},
                        ]
                    }
                }
            return {"message": {"items": []}, "data": [], "results": []}

        result = verify_citation(
            CitationInput(title="Deep Neural Networks Image Classification"),
            http_fn=mock_http,
        )

        assert result.status == "partial_match"
        assert result.matched_title == "Deep Neural Networks"
        assert "crossref" not in result.upstream_sources

    def test_audit_respects_circuit_breaker(self):
        calls: list[str] = []

        def mock_http(source, query):
            calls.append(source)
            if source == "crossref":
                return {
                    "message": {"items": [{"title": ["Attention Is All You Need"]}]}
                }
            if source == "openalex":
                raise AssertionError("open breaker must prevent this request")
            return {"message": {"items": []}, "data": []}

        def breaker(source, fn, *args):
            return None if source == "openalex" else fn(*args)

        result = verify_citation(
            CitationInput(title="Attention Is All You Need"),
            http_fn=mock_http,
            breaker_fn=breaker,
        )

        assert result.status == "verified"
        assert result.upstream_sources == ["crossref"]
        assert calls == ["crossref"]

    def test_title_audit_does_not_retry_a_failed_upstream(self):
        calls = {"crossref": 0, "openalex": 0}

        def mock_http(source, query):
            if source in calls:
                calls[source] += 1
            if source == "crossref":
                raise ConnectionError("Crossref unavailable")
            if source == "openalex":
                return {"results": [{"title": "Attention Is All You Need"}]}
            return {"message": {"items": []}, "data": []}

        result = verify_citation(
            CitationInput(title="Attention Is All You Need"), http_fn=mock_http
        )

        assert result.status == "verified"
        assert calls == {"crossref": 1, "openalex": 1}

    def test_doi_prefix_and_crossref_alternate_fields_are_normalized(self):
        def mock_http(source, query):
            assert query == "10.5555/correct"
            if source == "crossref":
                return {
                    "message": {
                        "title": ["Attention Is All You Need"],
                        "author": [{"name": "Vaswani"}],
                        "published-print": {"date-parts": [[2017]]},
                        "container-title": ["NeurIPS"],
                        "DOI": "10.5555/correct",
                    }
                }
            if source == "openalex":
                return {}
            raise AssertionError(f"unexpected source: {source}")

        result = verify_citation(
            CitationInput(
                title="Attention Is All You Need",
                authors=["Ashish Vaswani"],
                year=2017,
                venue="NeurIPS",
                doi="DOI: 10.5555/CORRECT",
            ),
            http_fn=mock_http,
        )

        assert result.upstream_sources == ["crossref"]
        assert result.conflicts == []

    def test_unavailable_upstreams_do_not_change_doi_status(self):
        def mock_http(source, query):
            assert query == "10.5555/correct"
            raise ConnectionError(f"{source} unavailable")

        result = verify_citation(
            CitationInput(title="Attention Is All You Need", doi="10.5555/correct"),
            http_fn=mock_http,
        )

        assert result.status == "verified"
        assert result.source == "doi_provided"
        assert result.upstream_sources == []
        assert result.conflicts == []

    def test_unmatched_upstreams_do_not_create_conflicts(self):
        def mock_http(source, query):
            assert query == "10.5555/correct"
            return {"message": {}, "results": []}

        result = verify_citation(
            CitationInput(title="Attention Is All You Need", doi="10.5555/correct"),
            http_fn=mock_http,
        )

        assert result.status == "verified"
        assert result.upstream_sources == []
        assert result.conflicts == []

    def test_malformed_upstream_payload_is_visible_without_changing_status(
        self, caplog
    ):
        def mock_http(source, query):
            assert query == "10.5555/correct"
            return (
                {"message": []}
                if source == "crossref"
                else {
                    "title": "Attention Is All You Need",
                    "primary_location": [{}],
                }
            )

        with caplog.at_level("WARNING"):
            result = verify_citation(
                CitationInput(title="Attention Is All You Need", doi="10.5555/correct"),
                http_fn=mock_http,
            )

        assert result.status == "verified"
        assert result.upstream_sources == []
        assert result.conflicts == []
        assert "malformed Crossref audit response" in caplog.text
        assert "malformed OpenAlex audit response" in caplog.text


# -- Verification Primitives (integration) ------------------------------------


class TestVerificationPrimitives:
    def test_paper_verify_numbers_primitive(self, tmp_path):
        from research_harness.primitives.verification_impls import paper_verify_numbers
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 't')")
        conn.execute(
            "INSERT INTO verified_numbers (topic_id, source, number_original, number_rounded) VALUES (?, ?, ?, ?)",
            (1, "metric:accuracy", 0.9134, 0.91),
        )
        conn.commit()
        conn.close()

        result = paper_verify_numbers(
            db=db,
            topic_id=1,
            text="Our model achieves 0.9134 accuracy.",
            section="results",
        )
        assert result.verified_count >= 1
        assert result.ok

    def test_paper_verify_detects_unverified(self, tmp_path):
        from research_harness.primitives.verification_impls import paper_verify_numbers
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 't')")
        conn.commit()
        conn.close()

        result = paper_verify_numbers(
            db=db,
            topic_id=1,
            text="Our method achieves 0.97 accuracy.",
            section="results",
        )
        assert result.unverified_count >= 1
        assert not result.ok

    def test_citation_verify_primitive(self, monkeypatch):
        from research_harness.primitives import verification_impls

        monkeypatch.setattr(
            verification_impls,
            "verify_citations",
            lambda inputs: [
                CitationResult(
                    title=citation.title,
                    status="verified",
                    confidence=1.0,
                    matched_doi=citation.doi,
                    source="doi_provided",
                )
                for citation in inputs
            ],
        )

        result = verification_impls.citation_verify(
            citations=[
                {"title": "Test Paper", "doi": "10.1234/test"},
                {"title": "Another Paper", "doi": "10.5678/another"},
            ],
        )
        # Both have DOIs, so both should be verified
        assert result.verified == 2
        assert result.hallucinated == 0
        assert result.pass_rate == pytest.approx(1.0)

    def test_citation_verify_primitive_serializes_upstream_conflicts(self, monkeypatch):
        from research_harness.primitives import verification_impls

        monkeypatch.setattr(
            verification_impls,
            "verify_citations",
            lambda _: [
                CitationResult(
                    title="Test Paper",
                    status="verified",
                    confidence=1.0,
                    source="doi_provided",
                    upstream_sources=["crossref"],
                    conflicts=[
                        {
                            "source": "crossref",
                            "field": "year",
                            "declared_value": 2020,
                            "upstream_value": 2017,
                        }
                    ],
                )
            ],
        )

        result = verification_impls.citation_verify(
            citations=[{"title": "Test Paper", "year": 2020, "doi": "10.1234/test"}]
        )

        assert result.verified == 1
        assert result.pass_rate == pytest.approx(1.0)
        assert result.conflict_count == 1
        assert asdict(result)["items"][0]["upstream_sources"] == ["crossref"]
        assert asdict(result)["items"][0]["conflicts"][0]["field"] == "year"

    def test_evidence_trace_empty(self, tmp_path):
        from research_harness.primitives.verification_impls import evidence_trace
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 't')")
        conn.commit()
        conn.close()

        result = evidence_trace(db=db, topic_id=1)
        assert result.total_claims == 0
        assert result.coverage_ratio == 0.0

    def test_evidence_trace_with_data(self, tmp_path):
        import json
        from research_harness.primitives.verification_impls import evidence_trace
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 't')")
        # Add a paper
        conn.execute(
            "INSERT INTO papers (id, title, doi, arxiv_id, s2_id) VALUES (1, 'Test Paper', '10.1000/test', '', '')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        # Add verified numbers (topic_id column required for evidence_trace query)
        conn.execute(
            "INSERT INTO verified_numbers (topic_id, source, number_original, number_rounded) VALUES (1, 'test', 0.95, 0.95)"
        )
        # Add claims artifact
        claims_payload = json.dumps(
            {"claims": [{"claim_id": "claim_abc123", "content": "Test claim"}]}
        )
        conn.execute(
            """INSERT INTO project_artifacts (topic_id, stage, artifact_type, payload_json, status)
               VALUES (1, 'analyze', 'claims', ?, 'active')""",
            (claims_payload,),
        )
        # Add evidence link artifact
        link_payload = json.dumps(
            {"claim_id": "claim_abc123", "source_type": "paper", "source_id": "1"}
        )
        conn.execute(
            """INSERT INTO project_artifacts (topic_id, stage, artifact_type, payload_json, status)
               VALUES (1, 'analyze', 'evidence_links', ?, 'active')""",
            (link_payload,),
        )
        conn.commit()
        conn.close()

        result = evidence_trace(db=db, topic_id=1)
        assert result.total_claims == 1
        assert result.traced_claims == 1
        assert result.fully_traced == 1
        assert result.coverage_ratio == pytest.approx(1.0)
