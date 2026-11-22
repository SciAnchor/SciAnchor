"""paper_search ranking: relevance must dominate venue tier.

Live defect (anchor-replay stage 1, 2026-08-10): `_composite_rank` returned a
LEXICOGRAPHIC tuple (tier, recency, relevance, citation), so any venue-tiered
paper outranked every arXiv preprint regardless of topical relevance — the
sort never reached the relevance component. Against the MemoryAgentBench
gold-reference set the merged top-40s recalled 1/87 references (1.15%) while
Semantic Scholar alone returned the missing papers at rank 1 for the same
query. Frontier literature is mostly preprints; venue tier may only be a
soft prior, never a lexicographic gate.
"""

from __future__ import annotations


def _ref(**kw):
    from research_harness.primitives.impls import PaperRef

    defaults = dict(
        title="t",
        authors=[],
        affiliations=[],
        year=2025,
        venue="",
        doi="",
        arxiv_id="",
        s2_id="",
        url="",
        relevance_score=0.0,
        snippet="",
        citation_count=0,
    )
    defaults.update(kw)
    return PaperRef(**defaults)


def test_relevant_preprint_outranks_irrelevant_tiered_paper():
    from research_harness.primitives.impls import _composite_rank

    query = "RULER real context size long-context language models"
    ruler = _ref(
        title="RULER: What's the Real Context Size of Your Long-Context Language Models?",
        venue="",  # arXiv preprint: no venue tier
        relevance_score=1.0,
        arxiv_id="2404.06654",
        year=2024,
    )
    walmart = _ref(
        title="Knowledge Distillation for E-commerce Search Relevance",
        venue="IEEE Transactions on Knowledge and Data Engineering",
        relevance_score=0.15,
        citation_count=40,
        year=2025,
    )
    assert _composite_rank(ruler, query, 2026) > _composite_rank(walmart, query, 2026)


def test_tier_still_breaks_ties_at_equal_relevance():
    from research_harness.primitives.impls import _composite_rank

    query = "agent memory evaluation"
    tiered = _ref(title="Agent Memory Evaluation", venue="NeurIPS", relevance_score=0.8)
    untiered = _ref(
        title="Agent Memory Evaluation (preprint)", venue="", relevance_score=0.8
    )
    assert _composite_rank(tiered, query, 2026) > _composite_rank(untiered, query, 2026)


def _record(**kw):
    from research_harness.paper_sources import PaperRecord

    defaults = dict(title="t", provider="test")
    defaults.update(kw)
    return PaperRecord(**defaults)


def test_aggregator_rank_relevance_beats_provider_priority():
    """Same defect one layer down: rank_record led with source_rank, so the
    merged-set cap filled with the top-priority provider's fuzzy tail."""
    from research_harness.paper_sources import rank_record

    query = "RULER real context size long-context language models"
    exact_hit = _record(
        title="RULER: What's the Real Context Size of Your Long-Context Language Models?",
        arxiv_id="2404.06654",
        source_rank=110,  # semantic_scholar
    )
    fuzzy = _record(
        title="Knowledge Distillation for E-commerce Search Relevance",
        openalex_id="W123",
        citation_count=40,
        source_rank=115,  # openalex outranks s2 in provider priority
    )
    assert rank_record(exact_hit, query) > rank_record(fuzzy, query)


def test_aggregator_rank_provider_breaks_ties():
    from research_harness.paper_sources import rank_record

    query = "agent memory"
    a = _record(title="Agent Memory", source_rank=115)
    b = _record(title="Agent Memory", source_rank=100)
    assert rank_record(a, query) > rank_record(b, query)


def test_partial_fanout_is_not_cached(tmp_path, monkeypatch):
    """A fan-out that lost a provider must not be stored as authoritative.

    Live defect (2026-08-25): `cache_put` ran unconditionally, so a run where
    Semantic Scholar 429'd cached a merged set missing that provider entirely.
    The cache-hit path returns providers_queried=("cache",) with no
    provider_errors, so for the whole TTL the gap was replayed as full
    coverage — a novelty verdict could not tell "nothing found" from "we never
    asked". Certification missed arXiv 2608.14036 this way.
    """
    from research_harness.primitives import impls
    from research_harness.storage.db import Database

    db = Database(tmp_path / "search.db")
    db.migrate()
    calls: list[int] = []

    class _Err:
        provider = "semantic_scholar"
        message = "HTTP 429"

    class _Outcome:
        def __init__(self, errors):
            self.results = []
            self.provider_errors = errors

    class _Agg:
        def __init__(self, _providers):
            pass

        def search(self, _query):
            calls.append(1)
            # First fan-out loses a provider; the retry is clean.
            return _Outcome([_Err()] if len(calls) == 1 else [])

    monkeypatch.setattr(impls, "SearchAggregator", _Agg)
    kwargs = dict(
        db=db,
        providers=[],
        query="agent skills",
        year_from=None,
        year_to=None,
        max_results=10,
        per_provider_limit=50,
        subject_categories=(),
    )
    impls._external_provider_search(**kwargs)
    impls._external_provider_search(**kwargs)
    assert len(calls) == 2, "partial fan-out was cached and replayed as complete"
