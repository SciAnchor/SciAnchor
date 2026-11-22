from __future__ import annotations

from research_harness.paper_sources import (
    PDFCandidate,
    PDFResolver,
    PaperRecord,
    SearchAggregator,
    SearchQuery,
    normalize_title,
)


class StubProvider:
    def __init__(self, name: str, records: list[PaperRecord]):
        self.name = name
        self._records = records

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        assert query.query
        return list(self._records)


def test_normalize_title_collapses_punctuation() -> None:
    assert (
        normalize_title("Attention Is All You Need!!!") == "attention is all you need"
    )


def test_search_aggregator_dedupes_and_prefers_stronger_metadata() -> None:
    google = StubProvider(
        "google_scholar",
        [
            PaperRecord(
                title="Attention Is All You Need",
                authors=["A. Vaswani"],
                year=2017,
                venue="NIPS",
                provider="google_scholar",
                citation_count=50000,
                pdf_candidates=[
                    PDFCandidate(
                        url="https://example.com/landing",
                        source_type="doi_landing",
                        provider="google_scholar",
                        confidence=0.4,
                    )
                ],
            )
        ],
    )
    openalex = StubProvider(
        "openalex",
        [
            PaperRecord(
                title="Attention Is All You Need",
                authors=["Ashish Vaswani", "Noam Shazeer"],
                year=2017,
                venue="NeurIPS",
                doi="10.5555/3295222.3295349",
                provider="openalex",
                citation_count=70000,
                pdf_candidates=[
                    PDFCandidate(
                        url="https://openalex.org/content/oa.pdf",
                        source_type="openalex_content",
                        provider="openalex",
                        confidence=0.95,
                    )
                ],
            )
        ],
    )

    outcome = SearchAggregator([google, openalex]).search(
        SearchQuery(query="attention", limit=10)
    )

    assert not outcome.provider_errors
    assert len(outcome.results) == 1
    result = outcome.results[0]
    assert result.doi == "10.5555/3295222.3295349"
    assert result.venue == "NeurIPS"
    assert result.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert {candidate.source_type for candidate in result.pdf_candidates} == {
        "doi_landing",
        "openalex_content",
    }


def test_search_aggregator_keeps_recall_results_ranked() -> None:
    google = StubProvider(
        "google_scholar",
        [
            PaperRecord(
                title="High Recall Result",
                provider="google_scholar",
                citation_count=100,
            )
        ],
    )
    dblp = StubProvider(
        "dblp",
        [
            PaperRecord(
                title="Lower Priority Result", provider="dblp", citation_count=1000
            )
        ],
    )

    outcome = SearchAggregator([dblp, google]).search(
        SearchQuery(query="result", limit=10)
    )

    assert not outcome.provider_errors
    # Contract changed 2026-08-10 (ad70e37): relevance dominates ranking at
    # every layer; with no relevance signal, citation count breaks the tie —
    # provider recall-priority no longer outranks a stronger record.
    assert [item.title for item in outcome.results] == [
        "Lower Priority Result",
        "High Recall Result",
    ]


def test_pdf_resolver_prefers_open_access_over_browser_and_landing() -> None:
    record = PaperRecord(
        title="Sample",
        doi="10.1000/test",
        arxiv_id="2401.12345",
        openreview_id="abc123",
        pdf_candidates=[
            PDFCandidate(
                url="https://publisher.example.com/view",
                source_type="doi_landing",
                provider="crossref",
                confidence=0.5,
            ),
            PDFCandidate(
                url="https://proxy.example.com/download",
                source_type="browser_session",
                provider="manual",
                requires_browser=True,
                confidence=0.8,
            ),
            PDFCandidate(
                url="https://openaccess.example.com/paper.pdf",
                source_type="open_access_pdf",
                provider="semantic_scholar",
                confidence=0.9,
            ),
        ],
    )

    plan = PDFResolver().plan(record)

    assert plan[0].source_type == "open_access_pdf"
    assert any(item.source_type == "arxiv_pdf" for item in plan)
    assert any(item.source_type == "openreview_pdf" for item in plan)
    assert plan[-1].source_type == "browser_session"


def test_search_aggregator_prefers_exact_title_match_over_extra_identifiers() -> None:
    semantic = StubProvider(
        "semantic_scholar",
        [
            PaperRecord(
                title="Attention is All you Need",
                provider="semantic_scholar",
                year=2017,
                arxiv_id="1706.03762",
                citation_count=1000,
            ),
            PaperRecord(
                title="Attention Is All You Need In Speech Separation",
                provider="semantic_scholar",
                year=2020,
                doi="10.1109/test",
                arxiv_id="2010.13154",
                citation_count=50,
                pdf_candidates=[
                    PDFCandidate(
                        url="https://example.com/speech.pdf",
                        source_type="open_access_pdf",
                        provider="semantic_scholar",
                        confidence=0.9,
                    )
                ],
            ),
        ],
    )

    outcome = SearchAggregator([semantic]).search(
        SearchQuery(query="attention is all you need", limit=10)
    )

    assert not outcome.provider_errors
    assert outcome.results[0].title == "Attention is All you Need"


def test_search_aggregator_keeps_partial_results_when_provider_fails() -> None:
    class FailingProvider:
        name = "openalex"

        def search(self, query: SearchQuery) -> list[PaperRecord]:
            del query
            raise RuntimeError("temporary upstream failure")

    semantic = StubProvider(
        "semantic_scholar",
        [
            PaperRecord(
                title="Attention is All you Need",
                provider="semantic_scholar",
                year=2017,
            )
        ],
    )

    outcome = SearchAggregator([FailingProvider(), semantic]).search(
        SearchQuery(query="attention", limit=10)
    )

    assert [item.title for item in outcome.results] == ["Attention is All you Need"]
    assert len(outcome.provider_errors) == 1
    assert outcome.provider_errors[0].provider == "openalex"
    assert outcome.provider_errors[0].error_type == "RuntimeError"


def test_search_aggregator_returns_partial_results_within_time_budget() -> None:
    import time as _time

    class SlowProvider:
        name = "slow_provider"

        def search(self, query: SearchQuery) -> list[PaperRecord]:
            _time.sleep(3.0)
            return [PaperRecord(title="Too late", provider=self.name)]

    fast = StubProvider(
        "arxiv",
        [PaperRecord(title="Fast result", provider="arxiv")],
    )

    started = _time.monotonic()
    outcome = SearchAggregator([fast, SlowProvider()]).search(
        SearchQuery(query="fast"), time_budget_sec=0.5
    )
    elapsed = _time.monotonic() - started

    assert elapsed < 2.5
    assert [record.title for record in outcome.results] == ["Fast result"]
    timeout_errors = [
        err
        for err in outcome.provider_errors
        if err.error_type == "SearchTimeBudgetExceeded"
    ]
    assert [err.provider for err in timeout_errors] == ["slow_provider"]


def test_normalize_arxiv_id_strips_version_and_prefixes() -> None:
    from research_harness.paper_sources import normalize_arxiv_id

    assert normalize_arxiv_id("2608.14036v1") == "2608.14036"
    assert normalize_arxiv_id("arXiv:2603.15401") == "2603.15401"
    assert normalize_arxiv_id("https://arxiv.org/abs/2401.12345v3") == "2401.12345"
    assert normalize_arxiv_id("math/0309136v2") == "math/0309136"
    # Unparseable input is kept, not dropped: losing an id we failed to parse
    # is worse than carrying it through.
    assert normalize_arxiv_id("not-an-id") == "not-an-id"
    assert normalize_arxiv_id("") == ""


def test_aggregator_unifies_versioned_and_unversioned_arxiv_ids() -> None:
    """Same paper, two providers, two arXiv id shapes -> one canonical record.

    Live defect (2026-08-25): the arXiv API reports "2608.14036v1" while
    Semantic Scholar reports "2608.14036", so the merged output carried
    whichever shape happened to win. Downstream matching on the bare id then
    silently missed the paper.
    """
    arxiv = StubProvider(
        "arxiv",
        [
            PaperRecord(
                title="Demystifying Agent Skills",
                year=2026,
                arxiv_id="2608.14036v1",
            )
        ],
    )
    s2 = StubProvider(
        "semantic_scholar",
        [
            PaperRecord(
                title="Demystifying Agent Skills",
                year=2026,
                arxiv_id="2608.14036",
                citation_count=3,
            )
        ],
    )
    outcome = SearchAggregator([arxiv, s2]).search(SearchQuery(query="agent skills"))
    assert len(outcome.results) == 1, "versioned/unversioned ids must not split"
    assert outcome.results[0].arxiv_id == "2608.14036v1", (
        "retain version evidence for PDF identity"
    )


def test_normalize_arxiv_id_keeps_multi_id_corruption_visible() -> None:
    """A field holding several ids is corrupt input, not a shape variant.

    Live incident (2026-08-26): a shell loop that failed to word-split passed
    the whole id list as one --arxiv-id. Canonicalizing would have kept the
    first id and dropped 25 others, turning obvious corruption into a
    plausible-looking wrong id that no quarantine check would catch.
    """
    from research_harness.paper_sources import normalize_arxiv_id

    corrupt = "2608.14036 2607.03048 2608.11338"
    assert normalize_arxiv_id(corrupt) == corrupt.lower()
    # A single id with incidental whitespace is still canonicalized.
    assert normalize_arxiv_id("arXiv: 2608.14036") == "2608.14036"
    # Repeats of the SAME id are a shape variant, not corruption.
    assert normalize_arxiv_id("2608.14036v1 2608.14036") == "2608.14036"
