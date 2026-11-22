"""Built-in primitive implementations — non-LLM operations only in Phase 1."""

from __future__ import annotations

from research_harness.acquisition.spc_bridge import SPCAcquisitionError

import dataclasses
import json
import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..core.paper_pool import PaperPool
from ..core.search_cache import cache_get, cache_put
from ..knowledge.topic_refresh import refresh_topic_knowledge_after_ingest
from paperindex.retrieval import BM25Document, BM25Index, tokenize_text
from ..acquisition.candidate_store import save_pdf_candidates
from ..paper_source_clients import build_provider_suite
from ..paper_sources import PaperRecord, PDFResolver, SearchAggregator
from ..paper_sources import SearchQuery as AggSearchQuery
from ..paper_sources import normalize_title
from ..storage.db import Database, write_transaction
from ..storage.models import Paper, PaperAnnotation
from .registry import (
    COLD_START_RUN_SPEC,
    EXPAND_CITATIONS_SPEC,
    PAPER_ACQUIRE_SPEC,
    PAPER_INGEST_SPEC,
    PAPER_SEARCH_SPEC,
    TOPIC_GET_CONTRIBUTIONS_SPEC,
    TOPIC_SET_CONTRIBUTIONS_SPEC,
    SELECT_SEEDS_SPEC,
    register_primitive,
)
from .types import (
    ExpandCandidatePaper,
    ExpandCitationsOutput,
    PaperAcquireOutput,
    PaperIngestOutput,
    PaperRef,
    PaperSearchOutput,
    TopicSetContributionsOutput,
    SeedPaper,
    SelectSeedsOutput,
    UnableToAcquireItem,
)
from ..venue_facts import (
    meets_tier_threshold,
    venue_tier_label,
    venue_tier_score,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _LocalBM25CacheEntry:
    revision: tuple[int, int]
    row_by_id: dict[str, sqlite3.Row]
    index: BM25Index


@dataclass(frozen=True)
class _ExternalProviderSearchResult:
    refs: list[PaperRef]
    providers_queried: tuple[str, ...] = ()
    provider_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurveyFirstRetrievalPolicy:
    """Internal policy record for survey-first retrieval guardrails."""

    schema_version: str = "survey_first_retrieval_policy.v1"
    status: str = "stable_internal"
    topic_paper_floor: int = 5
    facet_query_limit: int = 2
    recent_year_window: int = 1
    auto_ingest_policy: str = "disable_survey_first_when_auto_ingest_is_enabled"
    normal_topic_policy: str = "skip_survey_first_at_or_above_topic_paper_floor"
    no_survey_fallback: str = "run_original_query_without_seed_or_facet_fanout"
    guardrails: tuple[str, ...] = (
        "underfilled_topic_seed_first",
        "normal_topic_no_extra_seed_fanout",
        "auto_ingest_original_query_only",
        "no_survey_hits_fallback_to_original_query",
    )


_LOCAL_BM25_INDEX_CACHE: dict[tuple[Any, ...], _LocalBM25CacheEntry] = {}
LOCAL_BM25_TITLE_WEIGHT = 5
LOCAL_BM25_PHRASE_BONUS = 0.2
LOCAL_BM25_CANDIDATE_WINDOW = 100
SURVEY_FIRST_TOPIC_PAPER_FLOOR = 5
SURVEY_FIRST_FACET_QUERY_LIMIT = 2
SURVEY_FIRST_RECENT_YEAR_WINDOW = 1
SURVEY_FIRST_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "from",
        "in",
        "of",
        "on",
        "review",
        "survey",
        "systematic",
        "the",
        "towards",
        "toward",
        "with",
    }
)


def survey_first_retrieval_policy() -> SurveyFirstRetrievalPolicy:
    """Return the stable internal survey-first retrieval policy."""
    return SurveyFirstRetrievalPolicy(
        topic_paper_floor=SURVEY_FIRST_TOPIC_PAPER_FLOOR,
        facet_query_limit=SURVEY_FIRST_FACET_QUERY_LIMIT,
        recent_year_window=SURVEY_FIRST_RECENT_YEAR_WINDOW,
    )


# ---------------------------------------------------------------------------
# paper_search — multi-provider with venue tier ranking
# ---------------------------------------------------------------------------


@register_primitive(PAPER_SEARCH_SPEC)
def paper_search(
    *,
    db: Database,
    query: str,
    topic_id: int | None = None,
    max_results: int = 500,
    year_from: int | None = None,
    year_to: int | None = None,
    venue_filter: str = "",
    tier_filter: str = "",
    auto_ingest: bool = False,
    subject_categories: list[str] | tuple[str, ...] | None = None,
    per_provider_limit: int = 50,
    provider_allowlist: str | list[str] | tuple[str, ...] | set[str] | None = None,
    provider_denylist: str | list[str] | tuple[str, ...] | set[str] | None = None,
    local_only: bool = False,
    local_index_cache: bool = False,
    local_embed_rerank: bool | None = None,
    **_: Any,
) -> PaperSearchOutput:
    """Search papers across local pool + external providers with venue tier ranking."""

    current_year = datetime.now(timezone.utc).year

    # Phase 1: Local DB search
    # Opt-in embed rerank (W1). Default off so BM25 ranking contracts stay stable;
    # fake/hash embeddings would scramble order under tests and offline hosts.
    if local_embed_rerank is None:
        local_embed_rerank = False
    local_refs = _local_db_search(
        db=db,
        query=query,
        topic_id=topic_id,
        year_from=year_from,
        year_to=year_to,
        venue_filter=venue_filter,
        max_results=max_results * 3,
        use_index_cache=local_index_cache,
        use_embed_rerank=bool(local_embed_rerank),
    )

    providers_queried: list[str] = ["local"]
    provider_errors: list[str] = []
    external_refs: list[PaperRef] = []
    spc_empty: SPCAcquisitionError | None = None

    # Phase 2: External provider fan-out (with cache)

    if local_only:
        providers_queried.append("local_only")
    else:
        try:
            # SPC is the fallback below, not part of the fan-out.
            raw_providers = [p for p in build_provider_suite() if p.name != "spc"]
            providers = _filter_provider_suite(
                raw_providers,
                provider_allowlist=provider_allowlist,
                provider_denylist=provider_denylist,
            )
            excluded = _excluded_provider_names(
                raw_providers,
                provider_allowlist=provider_allowlist,
                provider_denylist=provider_denylist,
            )
            for provider_name in excluded:
                provider_errors.append(f"{provider_name}: excluded_by_search_policy")
            if providers:
                cats_key = (
                    tuple(sorted(subject_categories)) if subject_categories else ()
                )
                if query.strip() and _should_run_survey_first(
                    db=db,
                    topic_id=topic_id,
                    auto_ingest=auto_ingest,
                    year_to=year_to,
                    current_year=current_year,
                ):
                    survey_year_from = _survey_seed_year_from(
                        year_from=year_from,
                        year_to=year_to,
                        current_year=current_year,
                    )
                    if survey_year_from is not None:
                        survey_search = _external_provider_search(
                            db=db,
                            providers=providers,
                            query=_survey_seed_query(query),
                            year_from=survey_year_from,
                            year_to=year_to,
                            max_results=max_results,
                            per_provider_limit=per_provider_limit,
                            subject_categories=cats_key,
                        )
                        _extend_unique(
                            providers_queried,
                            survey_search.providers_queried,
                        )
                        provider_errors.extend(survey_search.provider_errors)
                        survey_refs = [
                            ref
                            for ref in survey_search.refs
                            if _is_recent_high_tier_survey(
                                ref,
                                current_year=current_year,
                            )
                        ]
                        external_refs.extend(survey_refs)
                        for facet_query in _survey_facet_queries(query, survey_refs):
                            facet_search = _external_provider_search(
                                db=db,
                                providers=providers,
                                query=facet_query,
                                year_from=year_from
                                if year_from is not None
                                else current_year - 5,
                                year_to=year_to,
                                max_results=max_results,
                                per_provider_limit=per_provider_limit,
                                subject_categories=cats_key,
                            )
                            _extend_unique(
                                providers_queried,
                                facet_search.providers_queried,
                            )
                            provider_errors.extend(facet_search.provider_errors)
                            external_refs.extend(facet_search.refs)
                base_search = _external_provider_search(
                    db=db,
                    providers=providers,
                    query=query,
                    year_from=year_from if year_from is not None else current_year - 5,
                    year_to=year_to,
                    max_results=max_results,
                    per_provider_limit=per_provider_limit,
                    subject_categories=cats_key,
                )
                _extend_unique(providers_queried, base_search.providers_queried)
                provider_errors.extend(base_search.provider_errors)
                external_refs.extend(base_search.refs)
        except SPCAcquisitionError:
            raise
        except Exception as exc:
            logger.warning("External provider fan-out failed: %s", exc)
            provider_errors.append(f"fan-out: {exc}")
    # Phase 2b: SPC fallback. The fan-out over the keyless public sources answers first;
    # SPC, when installed, searches only when the fan-out found nothing or failed, and stays
    # the PDF acquisition lane. Without SPC an empty fan-out is reported, never raised,
    # unless no source answered at all.
    if not local_only and not external_refs:
        from ..acquisition.spc_bridge import spc_search  # noqa: PLC0415

        try:
            spc_hits = spc_search(
                query,
                limit=min(max_results, 50),
                min_year=year_from,
                errors=provider_errors,
            )
        except SPCAcquisitionError as exc:
            # Zero hits is an answer. An SPC outage is fatal only when no fan-out source
            # answered either; otherwise it is one failed lane of an empty search.
            answered = (
                set(providers_queried)
                - {"local"}
                - {str(error).partition(":")[0].strip() for error in provider_errors}
            )
            if exc.code != "no_results" and not answered:
                raise
            if exc.code != "no_results":
                provider_errors.append(f"spc: {exc.code}")
            spc_empty, spc_hits = exc, []
        if spc_hits or spc_empty is not None:
            providers_queried.append("spc")
            external_refs = [
                PaperRef(
                    title=str(hit.get("title") or ""),
                    year=hit.get("year"),
                    venue=str(hit.get("venue") or ""),
                    doi=str(hit.get("doi") or ""),
                    arxiv_id=str(hit.get("arxiv_id") or ""),
                    citation_count=hit.get("citation_count"),
                    pmid=str(hit.get("pubmed_id") or ""),
                    pmcid=str(hit.get("pmc_id") or ""),
                    venue_tier=str(hit.get("ccf_rank") or ""),
                )
                for hit in spc_hits
                if str(hit.get("title") or "").strip()
            ]

    # SPC answered with zero hits: an empty, healthy search. Callers such as DEFINE widen
    # or skip on an empty answer; only a failed source is an outage.

    # Phase 3: Merge, dedup, filter, rank
    all_refs = _merge_and_dedup(local_refs, external_refs)
    total_before_filter = len(all_refs)

    # Enrich with venue tier info
    all_refs = [_enrich_venue_tier(ref) for ref in all_refs]

    # Apply filters
    if venue_filter:
        all_refs = [r for r in all_refs if venue_filter.lower() in r.venue.lower()]
    if tier_filter:
        all_refs = [r for r in all_refs if meets_tier_threshold(r.venue, tier_filter)]

    # Rank
    all_refs.sort(key=lambda r: _composite_rank(r, query, current_year), reverse=True)
    final = all_refs[:max_results]

    # Phase 4: Auto-ingest
    ingested_count = 0
    if auto_ingest and final:
        ingested_count = _auto_ingest_refs(db, final, topic_id)

    provider_label = "multi" if len(providers_queried) > 1 else "local"

    # Log to search_runs so MCP callers also get audit trail
    try:
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO search_runs (topic_id, query, provider, result_count, ingested_count) VALUES (?, ?, ?, ?, ?)",
                (topic_id, query, provider_label, len(final), ingested_count),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to log search_run: %s", exc)

    return PaperSearchOutput(
        papers=final,
        provider=provider_label,
        query_used=query,
        providers_queried=providers_queried,
        provider_errors=provider_errors,
        total_before_filter=total_before_filter,
        ingested_count=ingested_count,
        retrieval_backend=(
            (
                "local_bm25+embed_rerank_v0"
                if local_embed_rerank
                else "local_bm25_metadata_v0"
            )
            if local_only
            else (
                "local_bm25+embed_rerank_v0+provider_fanout_v0"
                if local_embed_rerank
                else "local_bm25_metadata_v0+provider_fanout_v0"
            )
        ),
    )


def _normalized_provider_filter(
    values: str | list[str] | tuple[str, ...] | set[str] | None,
) -> set[str]:
    if isinstance(values, str):
        items = re.split(r"[,;\\s]+", values)
    else:
        items = list(values or ())
    return {str(value).strip().lower() for value in items if str(value).strip()}


def _provider_name(provider: Any) -> str:
    return str(getattr(provider, "name", provider.__class__.__name__)).strip().lower()


def _filter_provider_suite(
    providers: list[Any],
    *,
    provider_allowlist: str | list[str] | tuple[str, ...] | set[str] | None,
    provider_denylist: str | list[str] | tuple[str, ...] | set[str] | None,
) -> list[Any]:
    allow = _normalized_provider_filter(provider_allowlist)
    deny = _normalized_provider_filter(provider_denylist)
    filtered: list[Any] = []
    for provider in providers:
        name = _provider_name(provider)
        if allow and name not in allow:
            continue
        if deny and name in deny:
            continue
        filtered.append(provider)
    return filtered


def _excluded_provider_names(
    providers: list[Any],
    *,
    provider_allowlist: str | list[str] | tuple[str, ...] | set[str] | None,
    provider_denylist: str | list[str] | tuple[str, ...] | set[str] | None,
) -> tuple[str, ...]:
    allow = _normalized_provider_filter(provider_allowlist)
    deny = _normalized_provider_filter(provider_denylist)
    excluded: list[str] = []
    for provider in providers:
        name = _provider_name(provider)
        if (allow and name not in allow) or (deny and name in deny):
            excluded.append(name)
    return tuple(dict.fromkeys(excluded))


def _external_provider_search(
    *,
    db: Database,
    providers: list[Any],
    query: str,
    year_from: int | None,
    year_to: int | None,
    max_results: int,
    per_provider_limit: int,
    subject_categories: tuple[str, ...],
) -> _ExternalProviderSearchResult:
    # "aggregated_full" (2026-08-10): the cache used to store the POST-cap
    # result set under a key that did not include the cap, so an early
    # narrow search (max_results=30) permanently truncated later wider
    # searches for the same query. The full merged set is cached now and
    # callers apply their own cap after ranking.
    cache_params = {
        "year_from": year_from,
        "year_to": year_to,
        "limit": per_provider_limit,
        "categories": subject_categories,
    }
    cached = cache_get(db, query, "aggregated_full", cache_params)
    if cached is not None:
        # relevance_score is a function of the query AND the scoring version;
        # a cached score is stale on both axes (a scoring fix would silently
        # never apply to cache hits). Recompute on every retrieval.
        # PaperRef is frozen — build replacements, never mutate.
        refs = [
            dataclasses.replace(ref, relevance_score=_ref_relevance(ref, query))
            for ref in (_dict_to_ref(rec_dict) for rec_dict in cached)
        ]
        return _ExternalProviderSearchResult(
            refs=refs,
            providers_queried=("cache",),
        )

    try:
        agg_query = AggSearchQuery(
            query=query,
            year_from=year_from,
            year_to=year_to,
            limit=per_provider_limit,
            per_provider_limit=per_provider_limit,
            subject_categories=subject_categories or None,
        )
        # No output_limit: pre-capping here applied the aggregator's own
        # ranking BEFORE _composite_rank ever saw the candidates, so the two
        # rankings fought and the cap filled with the aggregator's ordering.
        # The final cap is applied once, after _composite_rank.
        outcome = SearchAggregator(providers).search(agg_query)
        refs = [_record_to_ref(record, query) for record in outcome.results]
        # Never cache a partial fan-out. When a provider 429s or times out its
        # contribution is simply absent from `refs`, and the cache-hit path
        # above returns providers_queried=("cache",) with NO provider_errors —
        # so a set missing an entire provider would replay as complete coverage
        # for the whole TTL. Callers that decide novelty on "nothing found"
        # cannot tell that apart from "we never asked". Skipping the write
        # costs a re-fan-out; caching it silently corrupts every later verdict.
        if not outcome.provider_errors:
            cache_put(
                db,
                query,
                "aggregated_full",
                [_ref_to_dict(ref) for ref in refs],
                cache_params,
            )
        return _ExternalProviderSearchResult(
            refs=refs,
            providers_queried=tuple(
                getattr(provider, "name", provider.__class__.__name__)
                for provider in providers
            ),
            provider_errors=tuple(
                f"{err.provider}: {err.message}" for err in outcome.provider_errors
            ),
        )
    except Exception as exc:
        stale = cache_get(db, query, "aggregated_full", cache_params, allow_stale=True)
        refs = [_dict_to_ref(rec_dict) for rec_dict in stale] if stale else []
        providers = ("stale_cache",) if refs else ()
        return _ExternalProviderSearchResult(
            refs=refs,
            providers_queried=providers,
            provider_errors=(f"fan-out: {exc}",),
        )


def _extend_unique(target: list[str], values: tuple[str, ...]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _should_run_survey_first(
    *,
    db: Database,
    topic_id: int | None,
    auto_ingest: bool,
    year_to: int | None,
    current_year: int,
) -> bool:
    if topic_id is None or auto_ingest:
        return False
    if year_to is not None and year_to < current_year - SURVEY_FIRST_RECENT_YEAR_WINDOW:
        return False
    return _topic_paper_count(db, topic_id) < SURVEY_FIRST_TOPIC_PAPER_FLOOR


def _topic_paper_count(db: Database, topic_id: int) -> int:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM paper_topics WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        return int(row["n"] or 0) if row else 0
    except Exception as exc:
        logger.warning("Failed to inspect topic paper count for %s: %s", topic_id, exc)
        return SURVEY_FIRST_TOPIC_PAPER_FLOOR
    finally:
        conn.close()


def _survey_seed_year_from(
    *,
    year_from: int | None,
    year_to: int | None,
    current_year: int,
) -> int | None:
    recent_floor = current_year - SURVEY_FIRST_RECENT_YEAR_WINDOW
    if year_to is not None and year_to < recent_floor:
        return None
    return max(year_from, recent_floor) if year_from is not None else recent_floor


def _survey_seed_query(query: str) -> str:
    cleaned = " ".join(query.split())
    normalized = set(normalize_title(cleaned).split())
    if {"survey", "review"} & normalized:
        return cleaned
    return f"{cleaned} survey"


def _is_recent_high_tier_survey(ref: PaperRef, *, current_year: int) -> bool:
    if ref.year is None:
        return False
    if ref.year < current_year - SURVEY_FIRST_RECENT_YEAR_WINDOW:
        return False
    if ref.year > current_year:
        return False
    if not _has_survey_signal(ref):
        return False
    return meets_tier_threshold(ref.venue, "ccf_b") or meets_tier_threshold(
        ref.venue,
        "cas_q2",
    )


def _has_survey_signal(ref: PaperRef) -> bool:
    text = normalize_title(f"{ref.title} {ref.snippet}")
    tokens = set(text.split())
    return bool({"survey", "review", "overview"} & tokens) or (
        "systematic review" in text or "literature review" in text
    )


def _survey_facet_queries(query: str, survey_refs: list[PaperRef]) -> tuple[str, ...]:
    base_query = " ".join(query.split())
    base_tokens = set(normalize_title(base_query).split())
    queries: list[str] = []
    for ref in survey_refs:
        tokens = [
            token
            for token in normalize_title(f"{ref.title} {ref.snippet}").split()
            if token not in base_tokens
            and token not in SURVEY_FIRST_STOPWORDS
            and len(token) > 2
        ]
        facet_terms = list(dict.fromkeys(tokens))[:3]
        if not facet_terms:
            continue
        facet_query = " ".join([base_query, *facet_terms])
        if facet_query != base_query and facet_query not in queries:
            queries.append(facet_query)
        if len(queries) >= SURVEY_FIRST_FACET_QUERY_LIMIT:
            break
    return tuple(queries)


def _local_db_search(
    *,
    db: Database,
    query: str,
    topic_id: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    venue_filter: str = "",
    max_results: int = 60,
    use_index_cache: bool = False,
    use_embed_rerank: bool = False,
) -> list[PaperRef]:
    """Search the local SQLite paper pool with BM25, optional embed rerank."""
    conn = db.connect()
    try:
        sql = (
            "SELECT id, title, authors, affiliations, year, venue, doi, arxiv_id, "
            "s2_id, url, abstract, citation_count FROM papers"
        )
        clauses: list[str] = []
        params: list[Any] = []

        if topic_id is not None:
            clauses.append(
                "id IN (SELECT paper_id FROM paper_topics WHERE topic_id = ?)"
            )
            params.append(topic_id)
        if year_from is not None:
            clauses.append("year >= ?")
            params.append(year_from)
        if year_to is not None:
            clauses.append("year <= ?")
            params.append(year_to)
        if venue_filter:
            clauses.append("LOWER(COALESCE(venue, '')) LIKE ?")
            params.append(f"%{venue_filter.lower()}%")
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql += where_sql

        cache_entry = _local_bm25_cache_entry(
            conn=conn,
            db_path=str(db.db_path),
            where_sql=where_sql,
            params=params,
            topic_id=topic_id,
            year_from=year_from,
            year_to=year_to,
            venue_filter=venue_filter,
            use_index_cache=use_index_cache,
            full_sql=sql,
        )
        row_by_id = cache_entry.row_by_id
        index = cache_entry.index
        candidate_limit = max(max_results, LOCAL_BM25_CANDIDATE_WINDOW)
        scored_results = [
            (
                result.doc_id,
                result.score
                + _local_phrase_boost(
                    query,
                    _local_search_display_text(row_by_id[result.doc_id]),
                ),
            )
            for result in index.search(query, k=candidate_limit, scoring="bm25")
            if result.doc_id in row_by_id and result.score > 0
        ]
        if use_embed_rerank and row_by_id:
            from research_harness.retrieval import retrieve_then_rerank
            from research_harness.retrieval.rerank import DEFAULT_EMBED_ALL_MAX

            bm25_prior = {doc_id: float(score) for doc_id, score in scored_results}
            # Small filtered pools: embed every row so BM25 zeros cannot hide
            # semantic near-misses. Large pools: only rerank the BM25 shortlist.
            if len(row_by_id) <= DEFAULT_EMBED_ALL_MAX:
                documents = [
                    (
                        doc_id,
                        _local_search_display_text(row),
                        {"row_id": doc_id},
                    )
                    for doc_id, row in row_by_id.items()
                ]
            else:
                shortlist_ids = [
                    doc_id
                    for doc_id, _ in sorted(
                        scored_results, key=lambda item: (-item[1], item[0])
                    )[:candidate_limit]
                ]
                documents = [
                    (
                        doc_id,
                        _local_search_display_text(row_by_id[doc_id]),
                        {"row_id": doc_id},
                    )
                    for doc_id in shortlist_ids
                    if doc_id in row_by_id
                ]
            if documents:
                ranked = retrieve_then_rerank(
                    db,
                    query,
                    documents,
                    top_k=max_results,
                    shortlist_k=max(candidate_limit, max_results),
                    use_embeddings=True,
                    embed_weight=0.55,
                    prior_scores=bm25_prior,
                    prior_weight=0.25,
                    embed_all_max=DEFAULT_EMBED_ALL_MAX,
                )
                results = [
                    _local_row_to_ref(
                        row_by_id[hit.doc_id],
                        relevance_score=float(hit.score),
                    )
                    for hit in ranked
                    if hit.doc_id in row_by_id
                ]
                return results[:max_results]

        ranked_results = sorted(scored_results, key=lambda item: (-item[1], item[0]))
        results = [
            _local_row_to_ref(row_by_id[doc_id], relevance_score=score)
            for doc_id, score in ranked_results[:max_results]
        ]
        results.sort(key=lambda item: (-item.relevance_score, item.title))
        return results[:max_results]
    finally:
        conn.close()


def _local_bm25_cache_entry(
    *,
    conn: sqlite3.Connection,
    db_path: str,
    where_sql: str,
    params: list[Any],
    topic_id: int | None,
    year_from: int | None,
    year_to: int | None,
    venue_filter: str,
    use_index_cache: bool,
    full_sql: str,
) -> _LocalBM25CacheEntry:
    cache_key = (
        db_path,
        topic_id,
        year_from,
        year_to,
        venue_filter.lower(),
    )
    revision = (-1, -1)
    if use_index_cache:
        row = conn.execute(
            "SELECT COUNT(*) AS n, MAX(id) AS max_id FROM papers" + where_sql,
            params,
        ).fetchone()
        revision = (int(row["n"] or 0), int(row["max_id"] or 0)) if row else (0, 0)
        cached = _LOCAL_BM25_INDEX_CACHE.get(cache_key)
        if cached is not None and cached.revision == revision:
            return cached

    rows = conn.execute(full_sql, params).fetchall()
    row_by_id = {str(row["id"]): row for row in rows}
    index = BM25Index.from_documents(
        BM25Document(
            doc_id=str(row["id"]),
            text=_local_search_document_text(row),
        )
        for row in rows
    )
    entry = _LocalBM25CacheEntry(
        revision=revision if use_index_cache else (-1, -1),
        row_by_id=row_by_id,
        index=index,
    )
    if use_index_cache:
        _LOCAL_BM25_INDEX_CACHE[cache_key] = entry
    return entry


def _local_search_document_text(row: sqlite3.Row) -> str:
    title = str(row["title"] or "")
    abstract = str(row["abstract"] or "")
    identifiers = " ".join(
        str(row[key] or "") for key in ("doi", "arxiv_id", "s2_id") if row[key]
    )
    # Repeat title to preserve title-first behavior while letting abstracts and
    # identifiers contribute to local recall. Weight 5 is supported by LitSearch
    # full597 replay evidence from the RFB optimization loop.
    return " ".join((*([title] * LOCAL_BM25_TITLE_WEIGHT), abstract, identifiers))


def _local_search_display_text(row: sqlite3.Row) -> str:
    return f"{row['title'] or ''} {row['abstract'] or ''}".lower()


def _local_phrase_boost(query: str, text: str) -> float:
    total = 0.0
    for phrase in _query_phrases(query):
        if phrase in text:
            total += LOCAL_BM25_PHRASE_BONUS * len(phrase.split())
    return total


def _query_phrases(query: str) -> tuple[str, ...]:
    tokens = list(tokenize_text(query))
    phrases: list[str] = []
    for length in (4, 3, 2):
        for index in range(0, max(len(tokens) - length + 1, 0)):
            phrase = " ".join(tokens[index : index + length]).replace("_", " ")
            if len(phrase) >= 7:
                phrases.append(phrase)
    return tuple(dict.fromkeys(phrases))


def _local_row_to_ref(row: sqlite3.Row, *, relevance_score: float) -> PaperRef:
    abstract = str(row["abstract"] or "")
    return PaperRef(
        title=row["title"] or "",
        authors=_parse_authors(row["authors"]),
        affiliations=_parse_authors(row["affiliations"]) if row["affiliations"] else [],
        year=row["year"],
        venue=row["venue"] or "",
        doi=row["doi"] or "",
        arxiv_id=row["arxiv_id"] or "",
        s2_id=row["s2_id"] or "",
        url=row["url"] or "",
        relevance_score=round(relevance_score, 6),
        snippet=abstract[:300] if abstract else "",
        citation_count=row["citation_count"],
    )


def _ref_relevance(ref: PaperRef, query: str) -> float:
    """Query-token coverage over title + abstract head for a PaperRef.

    Title-only coverage scored branded-title papers (A-MEM, Mem0, RULER...)
    near zero on any natural-language query — the abstract carries the
    topical vocabulary. Lexical coverage remains a coarse instrument; the
    semantic rerank (IDX01) is the real successor.
    """
    from research_harness.paper_sources import normalize_title

    if not query.strip():
        return 0.0
    query_tokens = set(normalize_title(query).split())
    if not query_tokens:
        return 0.0
    haystack = set(normalize_title(ref.title).split())
    if ref.abstract:
        haystack |= set(normalize_title(ref.abstract[:500]).split())
    return round(len(query_tokens & haystack) / len(query_tokens), 6)


def _record_to_ref(record: PaperRecord, query: str) -> PaperRef:
    """Convert a PaperRecord from SearchAggregator to PaperRef."""
    from research_harness.paper_sources import query_token_coverage

    score = query_token_coverage(record, query)

    pdf_candidates = [
        {
            "url": candidate.url,
            "source_type": candidate.source_type,
            "provider": candidate.provider,
            "requires_browser": candidate.requires_browser,
            "confidence": candidate.confidence,
            "license_hint": candidate.license_hint,
        }
        for candidate in PDFResolver().plan(record)
    ]
    return PaperRef(
        title=record.title,
        authors=list(record.authors),
        affiliations=list(record.affiliations),
        year=record.year,
        venue=record.venue,
        doi=record.doi,
        arxiv_id=record.arxiv_id,
        s2_id=record.s2_id,
        url=record.url,
        relevance_score=score,
        snippet=record.abstract[:300] if record.abstract else "",
        citation_count=record.citation_count,
        pmid=record.pmid,
        pmcid=record.pmcid,
        openalex_id=record.openalex_id,
        abstract=record.abstract or "",
        pdf_candidates=pdf_candidates,
    )


def _ref_to_dict(ref: PaperRef) -> dict[str, Any]:
    """Serialize PaperRef to a JSON-safe dict for caching."""
    return {
        "title": ref.title,
        "authors": ref.authors,
        "affiliations": ref.affiliations,
        "year": ref.year,
        "venue": ref.venue,
        "doi": ref.doi,
        "arxiv_id": ref.arxiv_id,
        "s2_id": ref.s2_id,
        "url": ref.url,
        "relevance_score": ref.relevance_score,
        "snippet": ref.snippet,
        "venue_tier": ref.venue_tier,
        "citation_count": ref.citation_count,
        "pmid": ref.pmid,
        "pmcid": ref.pmcid,
        "openalex_id": ref.openalex_id,
        "abstract": ref.abstract,
        "pdf_candidates": ref.pdf_candidates,
    }


def _dict_to_ref(d: dict[str, Any]) -> PaperRef:
    """Deserialize a cached dict back to PaperRef."""
    pdf_candidates = d.get("pdf_candidates") or []
    if not isinstance(pdf_candidates, list):
        pdf_candidates = []
    return PaperRef(
        title=d.get("title", ""),
        authors=d.get("authors", []),
        affiliations=d.get("affiliations", []),
        year=d.get("year"),
        venue=d.get("venue", ""),
        doi=d.get("doi", ""),
        arxiv_id=d.get("arxiv_id", ""),
        s2_id=d.get("s2_id", ""),
        url=d.get("url", ""),
        relevance_score=d.get("relevance_score", 0.0),
        snippet=d.get("snippet", ""),
        venue_tier=d.get("venue_tier", ""),
        citation_count=d.get("citation_count"),
        pmid=d.get("pmid", ""),
        pmcid=d.get("pmcid", ""),
        openalex_id=d.get("openalex_id", ""),
        abstract=d.get("abstract", ""),
        pdf_candidates=[c for c in pdf_candidates if isinstance(c, dict)],
    )


def _ref_fingerprint(ref: PaperRef) -> str:
    """Generate a dedup fingerprint for a PaperRef."""
    for value in (ref.doi, ref.arxiv_id, ref.s2_id):
        cleaned = value.strip().lower()
        if cleaned:
            return cleaned
    return f"title:{normalize_title(ref.title)}:{ref.year or ''}"


def _merge_and_dedup(local: list[PaperRef], external: list[PaperRef]) -> list[PaperRef]:
    """Merge local and external results, deduplicating by fingerprint."""
    merged: dict[str, PaperRef] = {}
    # Local results first (they have pool membership)
    for ref in local:
        fp = _ref_fingerprint(ref)
        merged[fp] = ref
    # External results — prefer richer metadata when deduplicating
    for ref in external:
        fp = _ref_fingerprint(ref)
        existing = merged.get(fp)
        if existing is None:
            merged[fp] = ref
        else:
            merged[fp] = _pick_richer(existing, ref)
    return list(merged.values())


def _pick_richer(a: PaperRef, b: PaperRef) -> PaperRef:
    """Pick the PaperRef with richer metadata, merging missing fields."""

    # Prefer the one with more filled fields
    def _richness(r: PaperRef) -> int:
        count = 0
        if r.venue:
            count += 1
        if r.doi:
            count += 1
        if r.arxiv_id:
            count += 1
        if r.s2_id:
            count += 1
        if r.citation_count is not None:
            count += 1
        if r.snippet:
            count += 1
        if r.authors:
            count += 1
        return count

    base, other = (a, b) if _richness(a) >= _richness(b) else (b, a)
    # Merge missing fields from other into base
    merged_candidates = list(base.pdf_candidates)
    seen_urls = {c.get("url") for c in merged_candidates if isinstance(c, dict)}
    for candidate in other.pdf_candidates:
        if isinstance(candidate, dict) and candidate.get("url") not in seen_urls:
            merged_candidates.append(candidate)
            seen_urls.add(candidate.get("url"))
    return PaperRef(
        title=base.title or other.title,
        authors=base.authors or other.authors,
        affiliations=base.affiliations or other.affiliations,
        year=base.year or other.year,
        venue=base.venue or other.venue,
        doi=base.doi or other.doi,
        arxiv_id=base.arxiv_id or other.arxiv_id,
        s2_id=base.s2_id or other.s2_id,
        url=base.url or other.url,
        relevance_score=max(base.relevance_score, other.relevance_score),
        snippet=base.snippet or other.snippet,
        venue_tier=base.venue_tier or other.venue_tier,
        citation_count=base.citation_count
        if base.citation_count is not None
        else other.citation_count,
        pmid=base.pmid or other.pmid,
        pmcid=base.pmcid or other.pmcid,
        openalex_id=base.openalex_id or other.openalex_id,
        abstract=base.abstract or other.abstract,
        pdf_candidates=merged_candidates,
    )


def _enrich_venue_tier(ref: PaperRef) -> PaperRef:
    """Add venue tier label to a PaperRef."""
    label = venue_tier_label(ref.venue)
    if label == ref.venue_tier:
        return ref
    return dataclasses.replace(ref, venue_tier=label)


def _composite_rank(ref: PaperRef, query: str, current_year: int) -> float:
    """Weighted ranking score (higher is better). Relevance dominates.

    This was a lexicographic tuple (tier, recency, relevance, citation),
    which made venue tier an absolute gate: any tiered-venue paper outranked
    every arXiv preprint regardless of topical relevance, and the sort never
    reached the relevance component. Frontier literature is mostly preprints
    — against the MemoryAgentBench gold-reference set the tuple ranking
    recalled 1/87 references while providers returned the missing papers at
    rank 1 (anchor-replay stage 1, 2026-08-10). Venue tier and citations are
    soft priors, never gates.
    """
    # 1. Venue tier score (0.0 - 1.0)
    tier_score = venue_tier_score(ref.venue) / 100.0

    # 2. Recency score
    if ref.year is not None and ref.year >= current_year - 4:
        recency = 1.0
    elif ref.year is not None and ref.year >= current_year - 8:
        recency = 0.5
    else:
        recency = 0.2

    # 3. Title relevance (query-token coverage for external refs, BM25-derived
    #    for local rows; both roughly 0-1)
    relevance = ref.relevance_score

    # 4. Citation score (log-scaled, ~0.8 at 100k citations)
    citation = math.log1p(ref.citation_count or 0) / 15.0

    return relevance * 0.55 + tier_score * 0.2 + recency * 0.15 + citation * 0.1


def _best_ingest_url(ref: PaperRef) -> str:
    """Pick the best URL to persist on the papers row.

    Prefers a ranked public direct-PDF candidate over the provider landing
    page, so acquisition does not collapse to DOI/landing-page routes. Skips
    routes that need a browser or configured credentials (openalex_content).
    """
    for candidate in ref.pdf_candidates or []:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("requires_browser"):
            continue
        source_type = str(candidate.get("source_type") or "")
        if source_type in ("openalex_content", "doi_landing", "browser_session"):
            continue
        url = str(candidate.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            return url
    return ref.url


def _auto_ingest_refs(db: Database, refs: list[PaperRef], topic_id: int | None) -> int:
    """Auto-ingest PaperRefs into the local pool."""
    conn = db.connect()
    count = 0
    try:
        pool = PaperPool(conn)
        for ref in refs:
            source = ref.doi or ref.arxiv_id or ref.title
            if not source:
                continue
            paper = Paper(
                title=ref.title,
                doi=ref.doi,
                arxiv_id=ref.arxiv_id,
                s2_id=ref.s2_id,
                pmid=ref.pmid,
                pmcid=ref.pmcid,
                year=ref.year,
                venue=ref.venue,
                abstract=ref.abstract or "",
                url=_best_ingest_url(ref),
                authors=list(ref.authors),
                affiliations=list(ref.affiliations),
            )
            try:
                # Preserve search relevance using the existing pool bands; otherwise
                # strict acquisition sees no eligible papers after auto-ingestion.
                relevance = _normalize_relevance(f"{ref.relevance_score:.6f}")
                screened = relevance != "low"
                with write_transaction(conn):
                    # Let the pool resolve canonical identity and enrich metadata,
                    # without overwriting a topic's existing screening decision.
                    paper_id = pool.ingest(paper)
                    link = conn.execute(
                        "SELECT screening_status, evidence_role, manuscript_eligible "
                        "FROM paper_topics WHERE paper_id = ? AND topic_id = ?",
                        (paper_id, topic_id),
                    ).fetchone()
                    unscreened = link is None or (
                        link["screening_status"] == "candidate"
                        and link["evidence_role"] == "unreviewed"
                        and not link["manuscript_eligible"]
                    )
                    if topic_id is not None and unscreened:
                        pool.ingest(
                            paper,
                            topic_id=topic_id,
                            relevance=relevance,
                            screening_status="screened_in" if screened else "candidate",
                            evidence_role="unreviewed",
                            manuscript_eligible=screened,
                            screening_reason=(
                                f"auto_screened_relevance_score={ref.relevance_score:.3f}"
                            ),
                            candidate_source="paper_search",
                        )
                count += 1
            except Exception as exc:
                logger.debug(
                    "Ingest failed for ref '%s': %s",
                    ref.title[:60] if ref.title else "?",
                    exc,
                )
                continue
            if ref.pdf_candidates:
                try:
                    save_pdf_candidates(conn, paper_id, ref.pdf_candidates)
                except Exception as exc:
                    logger.debug(
                        "Failed to persist pdf candidates for paper %d: %s",
                        paper_id,
                        exc,
                    )
        return count
    finally:
        conn.close()


@register_primitive(SELECT_SEEDS_SPEC)
def select_seeds(
    *,
    db: Database,
    topic_id: int,
    top_n: int = 10,
    min_relevance: str = "medium",
    **_: Any,
) -> SelectSeedsOutput:
    """Rank and return top citation-expansion seeds from the paper pool."""
    _RELEVANCE_WEIGHT = {"high": 1.0, "medium": 0.5, "low": 0.1}
    _RELEVANCE_ORDER = {"high": 0, "medium": 1, "low": 2}
    min_order = _RELEVANCE_ORDER.get(min_relevance, 1)

    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.venue, p.year, p.citation_count,
                   p.s2_id, p.arxiv_id, p.doi, pt.relevance
            FROM papers p
            JOIN paper_topics pt ON p.id = pt.paper_id
            WHERE pt.topic_id = ? AND p.status != 'deleted'
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    total_pool = len(rows)
    candidates: list[SeedPaper] = []

    for row in rows:
        relevance = _normalize_relevance(row["relevance"] or "low")
        if _RELEVANCE_ORDER.get(relevance, 2) > min_order:
            continue

        venue = row["venue"] or ""
        tier = venue_tier_label(venue)
        tier_score = venue_tier_score(venue) / 100.0

        citations = row["citation_count"]
        citation_score = math.log1p(citations or 0) / math.log1p(10000)

        relevance_score = _RELEVANCE_WEIGHT.get(relevance, 0.1)

        composite = tier_score * 0.4 + citation_score * 0.3 + relevance_score * 0.3

        candidates.append(
            SeedPaper(
                paper_id=row["id"],
                title=row["title"] or "",
                venue=venue,
                venue_tier=tier,
                year=row["year"],
                citation_count=citations,
                relevance=relevance,
                seed_score=round(composite, 4),
                s2_id=row["s2_id"] or "",
                arxiv_id=row["arxiv_id"] or "",
                doi=row["doi"] or "",
            )
        )

    candidates.sort(key=lambda s: s.seed_score, reverse=True)
    return SelectSeedsOutput(
        seeds=candidates[:top_n],
        topic_id=topic_id,
        total_pool=total_pool,
    )


@register_primitive(EXPAND_CITATIONS_SPEC)
def expand_citations(
    *,
    db: Database,
    topic_id: int,
    seed_paper_ids: list[int] | None = None,
    forward_limit: int = 50,
    backward_limit: int = 50,
    **_: Any,
) -> ExpandCitationsOutput:
    """Expand paper pool through the production SPC citation graph."""
    from ..acquisition.spc_bridge import spc_graph

    # Resolve seeds: use provided IDs or fall back to auto-select top 5
    if seed_paper_ids:
        seeds = _load_seed_papers(db, topic_id, seed_paper_ids)
    else:
        seeds_out = select_seeds(
            db=db, topic_id=topic_id, top_n=5, min_relevance="medium"
        )
        seeds = list(seeds_out.seeds)

    if not seeds:
        return ExpandCitationsOutput(
            topic_id=topic_id,
            seeds_used=0,
            decision_guidance=(
                "No seeds found for this topic. Run paper_search + paper_ingest first, "
                "then retry expand_citations."
            ),
        )

    candidates: list[ExpandCandidatePaper] = []
    forward_count = 0
    backward_count = 0
    acquisition_errors: list[str] = []
    for seed in seeds:
        if not seed.doi:
            acquisition_errors.append(
                f"seed {seed.paper_id}: DOI unresolved; graph not checked"
            )
            continue
        for direction, relation, limit in (
            ("citations", "forward", forward_limit),
            ("references", "backward", backward_limit),
        ):
            try:
                hits = spc_graph(seed.doi, direction=direction, limit=limit)
                for hit in hits:
                    rec = PaperRecord(
                        title=str(hit["title"]),
                        authors=hit.get("authors") or [],
                        year=hit.get("year"),
                        venue=str(hit.get("venue") or ""),
                        doi=str(hit.get("doi") or ""),
                        arxiv_id=str(hit.get("arxiv_id") or ""),
                        abstract=str(hit.get("abstract") or ""),
                        provider="spc",
                        citation_count=hit.get("citation_count"),
                    )
                    candidates.append(
                        _record_to_expand_candidate(rec, seed.paper_id, relation)
                    )
                if relation == "forward":
                    forward_count += len(hits)
                else:
                    backward_count += len(hits)
            except SPCAcquisitionError:
                raise
            except Exception as exc:
                acquisition_errors.append(
                    f"seed {seed.paper_id} {direction}: {type(exc).__name__}"
                )
                logger.warning(
                    "SPC %s failed for seed %d: %s", direction, seed.paper_id, exc
                )

    # Dedup by fingerprint (same paper may appear from multiple seeds)
    seen: set[str] = set()
    deduped: list[ExpandCandidatePaper] = []
    for c in candidates:
        fp = (
            c.doi.strip().lower()
            or c.arxiv_id.strip().lower()
            or c.s2_id.strip().lower()
            or f"title:{c.title.lower()}"
        )
        if fp not in seen:
            seen.add(fp)
            deduped.append(c)

    # Sort by composite score: venue_tier × 0.4 + log_citation × 0.3 (no relevance known yet)
    deduped.sort(key=_candidate_rank, reverse=True)

    guidance = _build_expand_guidance(deduped, topic_id)
    if acquisition_errors:
        guidance += (
            " Acquisition incomplete; zero hits are not evidence of no citations: "
            + "; ".join(acquisition_errors)
        )

    return ExpandCitationsOutput(
        topic_id=topic_id,
        seeds_used=len(seeds),
        forward_count=forward_count,
        backward_count=backward_count,
        candidates=deduped,
        decision_guidance=guidance,
    )


def _load_seed_papers(
    db: Database, topic_id: int, paper_ids: list[int]
) -> list[SeedPaper]:
    """Load SeedPaper objects for the given paper IDs in a topic."""
    conn = db.connect()
    try:
        placeholders = ",".join("?" * len(paper_ids))
        rows = conn.execute(
            f"""
            SELECT p.id, p.title, p.venue, p.year, p.citation_count,
                   p.s2_id, p.arxiv_id, p.doi, pt.relevance
            FROM papers p
            JOIN paper_topics pt ON p.id = pt.paper_id
            WHERE pt.topic_id = ? AND p.id IN ({placeholders})
            """,
            [topic_id, *paper_ids],
        ).fetchall()
    finally:
        conn.close()

    result: list[SeedPaper] = []
    for row in rows:
        venue = row["venue"] or ""
        result.append(
            SeedPaper(
                paper_id=row["id"],
                title=row["title"] or "",
                venue=venue,
                venue_tier=venue_tier_label(venue),
                year=row["year"],
                citation_count=row["citation_count"],
                relevance=row["relevance"] or "low",
                seed_score=0.0,
                s2_id=row["s2_id"] or "",
                arxiv_id=row["arxiv_id"] or "",
                doi=row["doi"] or "",
            )
        )
    return result


def _record_to_expand_candidate(
    record: "PaperRecord", seed_paper_id: int, direction: str
) -> ExpandCandidatePaper:
    """Convert a PaperRecord from S2 citation graph to an ExpandCandidatePaper."""
    venue = record.venue or ""
    return ExpandCandidatePaper(
        title=record.title or "",
        doi=record.doi or "",
        arxiv_id=record.arxiv_id or "",
        s2_id=record.s2_id or "",
        year=record.year,
        venue=venue,
        venue_tier=venue_tier_label(venue),
        citation_count=record.citation_count,
        abstract=(record.abstract or "")[:300],
        direction=direction,
        seed_paper_id=seed_paper_id,
    )


def _candidate_rank(c: ExpandCandidatePaper) -> tuple[float, float]:
    """Sort key for expand candidates: venue tier + log citation."""
    tier = venue_tier_score(c.venue) / 100.0
    cite = math.log1p(c.citation_count or 0) / math.log1p(10000)
    return (tier * 0.4 + cite * 0.3, c.year or 0)


def _build_expand_guidance(
    candidates: list[ExpandCandidatePaper], topic_id: int
) -> str:
    """Build model guidance text based on candidate pool quality."""
    if not candidates:
        return (
            "No expansion candidates found. The seeds may lack S2 identifiers. "
            "Try enriching seeds via paper_ingest before retrying."
        )

    top_tier = [
        c for c in candidates if "CCF-A" in c.venue_tier or "Q1" in c.venue_tier
    ]
    high_cite = [c for c in candidates if (c.citation_count or 0) >= 50]

    parts = [
        f"Found {len(candidates)} unique candidates ({len(top_tier)} from top-tier venues, "
        f"{len(high_cite)} with ≥50 citations).",
        "Decision guidance:",
        "  • PRIORITIZE ingestion of papers with: top-tier venue (CCF-A*/A, CAS-Q1) "
        "AND citation_count ≥ 50 AND year ≥ 2019.",
        "  • For additional rounds: re-run expand_citations with the newly ingested papers "
        "as seed_paper_ids if the top-tier / high-citation pool is still sparse (<10 papers).",
        "  • SKIP candidates with: unknown venue, citation_count < 5, year < 2015 "
        "(unless they appear highly relevant to the topic).",
        f"  • Use paper_ingest for each selected candidate, then paper_search topic_id={topic_id} "
        "to confirm pool coverage before moving to analyze stage.",
    ]
    return "\n".join(parts)


def _normalize_relevance(value: str) -> str:
    """Normalize relevance to categorical label (high/medium/low).

    Handles float-like strings (e.g. "0.67") by mapping to buckets:
      >= 0.7 → "high", >= 0.4 → "medium", else → "low"
    """
    value = value.strip().lower()
    if value in ("high", "medium", "low"):
        return value
    # Also accept core/peripheral as aliases
    if value == "core":
        return "high"
    if value == "peripheral":
        return "low"
    # Try parsing as float
    try:
        score = float(value)
        if score >= 0.7:
            return "high"
        elif score >= 0.4:
            return "medium"
        else:
            return "low"
    except (ValueError, TypeError):
        return "medium"


@register_primitive(PAPER_INGEST_SPEC)
def paper_ingest(
    *,
    db: Database,
    source: str,
    topic_id: int | None = None,
    relevance: str = "medium",
    url: str = "",
    **_: Any,
) -> PaperIngestOutput:
    """Ingest a paper into the local pool without changing PaperPool semantics."""

    import time

    relevance = _normalize_relevance(relevance)
    if not url and source.strip().lower().startswith(("http://", "https://")):
        url = source.strip()

    conn = db.connect()
    try:
        pool = PaperPool(conn)
        existing = _find_existing_source(conn, source)
        paper = _paper_from_source(source, url=url)
        if existing is not None:
            _backfill_identifier_from_source(conn, existing, paper)
        paper_id = pool.ingest(paper, topic_id=topic_id, relevance=relevance)

        # Auto-enrich metadata from Semantic Scholar (with retry on incomplete)
        enriched_fields: dict[str, str] = {}
        for attempt in range(2):
            try:
                enriched_fields = pool.enrich_metadata(paper_id)
                if "error" in enriched_fields:
                    logger.debug(
                        "S2 enrichment note for paper %d: %s",
                        paper_id,
                        enriched_fields.pop("error"),
                    )
                time.sleep(1.05)  # S2 rate limit: 1 req/s
            except SPCAcquisitionError as exc:
                # Enrichment is best-effort: no match leaves the ingested row as is,
                # and a transient SPC failure gets the second attempt. Others stay fatal.
                if exc.code == "no_results":
                    break
                if attempt == 0 and (exc.retryable or exc.code == "TimeoutExpired"):
                    time.sleep(1.05)
                    continue
                raise
            except Exception as exc:
                logger.warning(
                    "S2 enrichment failed for paper %d (attempt %d): %s",
                    paper_id,
                    attempt + 1,
                    exc,
                )
                time.sleep(1.05)
                continue

            # Verify completeness — retry if title still empty
            stored = pool.get(paper_id)
            if stored is not None and stored.title and stored.title != source:
                break
            if attempt == 0:
                time.sleep(1.05)

        stored = pool.get(paper_id)
        title = stored.title if stored is not None else paper.title
        metadata_complete = bool(title and title != source)

        # URL-only ingest: if caller supplied a web URL and we have no
        # PDF, try to fetch the HTML body so downstream claim_extract /
        # paper_summarize have something to read. Historical bug: this
        # path silently landed papers as meta_only with no text, so
        # agents fell back to their parametric memory. See
        # tool-gaps.md [2026-04-27].
        html_ingest_result: dict[str, Any] = {}
        needs_html_fetch = (
            bool(url)
            and (url.startswith("http://") or url.startswith("https://"))
            and not (stored and stored.pdf_path)
        )
        if needs_html_fetch:
            try:
                from ..acquisition.html_ingest import fetch_html_as_markdown

                page = fetch_html_as_markdown(url)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "URL-only ingest fetch failed for paper %d (%s): %s",
                    paper_id,
                    url,
                    exc,
                )
                page = None
            if page is not None and page.ok:
                pool.upsert_annotation(
                    PaperAnnotation(
                        paper_id=paper_id,
                        section="summary",
                        content=page.markdown,
                        source=f"html_ingest:{url}",
                        confidence=0.9,
                        extractor_version="html_ingest.v1",
                    )
                )
                conn.execute(
                    "UPDATE papers SET status = ?, abstract = COALESCE(NULLIF(abstract, ''), ?) WHERE id = ?",
                    ("text_only", page.markdown[:2000], paper_id),
                )
                # Fill title if we didn't have one (pure URL ingest case)
                stored_title = (stored.title or "").strip() if stored else ""
                have_better_title = bool(page.title) and (
                    not stored_title or (stored_title == source and not paper.title)
                )
                if have_better_title:
                    conn.execute(
                        "UPDATE papers SET title = ? WHERE id = ?",
                        (page.title, paper_id),
                    )
                    title = page.title
                conn.commit()
                html_ingest_result = {
                    "fetched": True,
                    "chars": len(page.markdown),
                    "http_status": page.http_status,
                }
                metadata_complete = bool(title and title != source)
            else:
                reason = (
                    (page.error or "no body")
                    if page is not None
                    else "internal exception"
                )
                html_ingest_result = {
                    "fetched": False,
                    "reason": reason,
                }
                logger.info(
                    "URL-only ingest: %s did not yield HTML body (%s); paper %d left as meta_only",
                    url,
                    reason,
                    paper_id,
                )

        # Duplicate detection (by title similarity)
        dup_candidates: list[dict[str, object]] = []
        if title and existing is None:
            try:
                dup_candidates = _find_duplicate_candidates(
                    conn,
                    title,
                    exclude_id=paper_id,
                    topic_id=topic_id,
                )
            except Exception:
                logger.debug(
                    "Duplicate detection failed for paper %d", paper_id, exc_info=True
                )

        # Survey detection
        if title and topic_id is not None:
            try:
                _detect_survey_paper(conn, paper_id, title, topic_id=topic_id)
            except Exception:
                logger.debug(
                    "Survey detection failed for paper %d", paper_id, exc_info=True
                )

        knowledge_refresh = refresh_topic_knowledge_after_ingest(
            db,
            topic_id=topic_id,
            paper_id=paper_id,
        )

        return PaperIngestOutput(
            paper_id=paper_id,
            title=title,
            status="existing" if existing is not None else "new",
            merged_fields=["metadata_incomplete"] if not metadata_complete else [],
            enriched_fields=enriched_fields,
            duplicate_candidates=dup_candidates,
            html_ingest=html_ingest_result,
            knowledge_refresh=knowledge_refresh,
        )
    finally:
        conn.close()


def _normalize_title(title: str) -> str:
    """Normalize a title for fuzzy comparison: lowercase, strip punctuation/whitespace."""
    import re

    t = title.lower().strip()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _title_similarity(a: str, b: str) -> float:
    """Character-level overlap ratio between two normalized titles."""
    if not a or not b:
        return 0.0
    a_set = set(a.split())
    b_set = set(b.split())
    if not a_set or not b_set:
        return 0.0
    intersection = a_set & b_set
    return len(intersection) / max(len(a_set), len(b_set))


_DUPLICATE_THRESHOLD = 0.75

_SURVEY_KEYWORDS = (
    "survey",
    "review",
    "meta-analysis",
    "meta analysis",
    "systematic review",
    "literature review",
    "overview of",
    "a comprehensive",
    "tutorial",
)


def _find_duplicate_candidates(
    conn: sqlite3.Connection,
    title: str,
    exclude_id: int | None = None,
    topic_id: int | None = None,
) -> list[dict[str, object]]:
    """Find papers with similar titles. Returns list of {id, title, similarity}."""
    if not title or len(title) < 10:
        return []

    norm = _normalize_title(title)
    if not norm:
        return []

    # Query candidate papers (same topic if specified, otherwise all)
    if topic_id is not None:
        rows = conn.execute(
            """
            SELECT p.id, p.title FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ? AND p.title IS NOT NULL AND p.title != ''
            """,
            (topic_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title FROM papers WHERE title IS NOT NULL AND title != ''",
        ).fetchall()

    candidates = []
    for row in rows:
        if exclude_id is not None and int(row["id"]) == exclude_id:
            continue
        other_norm = _normalize_title(row["title"])
        sim = _title_similarity(norm, other_norm)
        if sim >= _DUPLICATE_THRESHOLD:
            candidates.append(
                {
                    "id": int(row["id"]),
                    "title": row["title"],
                    "similarity": round(sim, 3),
                }
            )

    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    return candidates[:5]


def _detect_survey_paper(
    conn: sqlite3.Connection,
    paper_id: int,
    title: str,
    topic_id: int | None = None,
) -> bool:
    """Flag paper as survey if title matches survey keywords. Returns True if flagged."""
    if not title:
        return False
    lower = title.lower()
    is_survey = any(kw in lower for kw in _SURVEY_KEYWORDS)
    if not is_survey:
        return False

    if topic_id is None:
        return is_survey

    # Check if already flagged
    existing = conn.execute(
        "SELECT 1 FROM topic_paper_notes WHERE paper_id = ? AND topic_id = ? AND note_type = 'survey_flag'",
        (paper_id, topic_id),
    ).fetchone()
    if existing:
        return True

    conn.execute(
        "INSERT INTO topic_paper_notes (paper_id, topic_id, note_type, content) VALUES (?, ?, 'survey_flag', 'Auto-detected survey paper')",
        (paper_id, topic_id),
    )
    conn.commit()
    return True


def _find_existing_source(conn: sqlite3.Connection, source: str) -> int | None:
    kind, value = _normalize_identifier_source(source)
    row = None
    if kind == "doi":
        row = conn.execute("SELECT id FROM papers WHERE doi = ?", (value,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM papers WHERE title IN (?, ?, ?) ORDER BY id LIMIT 1",
                (
                    source,
                    f"doi:{value}",
                    f"DOI:{value}",
                ),
            ).fetchone()
    elif kind == "arxiv_id":
        row = conn.execute(
            "SELECT id FROM papers WHERE arxiv_id = ?", (value,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM papers WHERE title IN (?, ?, ?) ORDER BY id LIMIT 1",
                (
                    source,
                    f"arxiv:{value}",
                    f"arXiv:{value}",
                ),
            ).fetchone()
    elif kind == "pmid":
        row = conn.execute("SELECT id FROM papers WHERE pmid = ?", (value,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM papers WHERE title IN (?, ?, ?) ORDER BY id LIMIT 1",
                (
                    source,
                    f"pmid:{value}",
                    f"PMID:{value}",
                ),
            ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM papers WHERE title = ?", (source,)
        ).fetchone()
    if row is None:
        return None
    return int(row["id"])


def _paper_from_source(source: str, url: str = "") -> Paper:
    kind, value = _normalize_identifier_source(source)
    if kind == "doi":
        return Paper(doi=value, url=url)
    if kind == "arxiv_id":
        return Paper(arxiv_id=value, url=url)
    if kind == "pmid":
        return Paper(pmid=value, url=url)
    # No identifier recovered: never store a filesystem path or a raw URL as the
    # title (BUG-003 — those became permanent, undedup-able titles). Derive a
    # provisional human title from a file basename; for URLs leave the title
    # empty and keep the URL so enrichment can fill metadata later.
    title, resolved_url = _provisional_title_from_source(source, url)
    return Paper(title=title, url=resolved_url)


def _extract_doi_from_text(text: str) -> str:
    """Recover a DOI from a URL or SPC-style filename; '' if none found."""
    # doi.org URL or doi:/doi= prefixes (real slashes preserved)
    m = re.search(r"(?:doi\.org/|doi[:=])\s*(10\.\d{4,}/\S+)", text, re.I)
    if m:
        return m.group(1).strip().rstrip("./")
    # SPC packs encode the DOI with underscores: doi_10.1057_s41599-025-06126-7
    m = re.search(r"doi_(10\.\d{4,})_([^/\\]+?)(?:\.(?:pdf|md|txt))?$", text, re.I)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    # bare 10.xxxx/yyyy embedded anywhere
    m = re.search(r"(10\.\d{4,}/[^\s/\\]+)", text)
    if m:
        return m.group(1).strip().rstrip(".")
    return ""


def _looks_like_local_path(raw: str) -> bool:
    lower = raw.lower()
    return (
        raw.startswith(("/", "./", "../", "~/"))
        or "\\" in raw
        or bool(re.match(r"^[a-zA-Z]:\\", raw))
        or lower.endswith((".pdf", ".md", ".txt", ".html", ".htm"))
    )


def _provisional_title_from_source(source: str, url: str) -> tuple[str, str]:
    """Title/url for an unidentified ingest source. Paths/URLs never become titles."""
    raw = str(source or "").strip()
    lower = raw.lower()
    if lower.startswith(("http://", "https://")):
        return "", (url or raw)
    if _looks_like_local_path(raw):
        base = re.split(r"[\\/]", raw)[-1]
        base = re.sub(r"\.(pdf|md|txt|html?)$", "", base, flags=re.I)
        if re.match(r"^doi_10\.", base, re.I):
            return "", url  # pure DOI filename: DOI already recovered upstream
        return re.sub(r"[._-]+", " ", base).strip(), url
    return raw, url


def _normalize_identifier_source(source: str) -> tuple[str | None, str]:
    raw = str(source or "").strip()
    lower = raw.lower()
    if lower.startswith("doi:"):
        return "doi", raw.split(":", 1)[1].strip()
    if lower.startswith("arxiv:"):
        return "arxiv_id", raw.split(":", 1)[1].strip()
    if lower.startswith("pmid:"):
        value = raw.split(":", 1)[1].strip()
        return "pmid", re.sub(r"\D+", "", value) if value else value
    if raw.startswith("10."):
        return "doi", raw
    # DOI embedded in a URL or SPC filename — recover it so dedup by DOI works
    # instead of inserting a duplicate row with a path/URL title (BUG-003).
    doi = _extract_doi_from_text(raw)
    if doi:
        return "doi", doi
    arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", lower)
    if arxiv_match:
        return "arxiv_id", arxiv_match.group(1)
    if "/" not in raw and len(raw) < 20:
        return "arxiv_id", raw.removeprefix("arXiv:").removeprefix("arxiv:")
    return None, raw


def _backfill_identifier_from_source(
    conn: sqlite3.Connection, paper_id: int, paper: Paper
) -> None:
    updates: list[tuple[str, str]] = []
    if paper.doi:
        dup = conn.execute(
            "SELECT id FROM papers WHERE doi = ? AND id != ?",
            (paper.doi, paper_id),
        ).fetchone()
        if dup is None:
            updates.append(("doi", paper.doi))
    if paper.arxiv_id:
        dup = conn.execute(
            "SELECT id FROM papers WHERE arxiv_id = ? AND id != ?",
            (paper.arxiv_id, paper_id),
        ).fetchone()
        if dup is None:
            updates.append(("arxiv_id", paper.arxiv_id))
    if paper.s2_id:
        dup = conn.execute(
            "SELECT id FROM papers WHERE s2_id = ? AND id != ?",
            (paper.s2_id, paper_id),
        ).fetchone()
        if dup is None:
            updates.append(("s2_id", paper.s2_id))
    if paper.pmid:
        dup = conn.execute(
            "SELECT id FROM papers WHERE pmid = ? AND id != ?",
            (paper.pmid, paper_id),
        ).fetchone()
        if dup is None:
            updates.append(("pmid", paper.pmid))
    if paper.pmcid:
        dup = conn.execute(
            "SELECT id FROM papers WHERE pmcid = ? AND id != ?",
            (paper.pmcid, paper_id),
        ).fetchone()
        if dup is None:
            updates.append(("pmcid", paper.pmcid))

    changed = False
    for field_name, value in updates:
        row = conn.execute(
            f"SELECT {field_name} FROM papers WHERE id = ?",
            (paper_id,),
        ).fetchone()
        current = str(row[field_name] or "").strip() if row is not None else ""
        if current:
            continue
        conn.execute(
            f"UPDATE papers SET {field_name} = ? WHERE id = ?",
            (value, paper_id),
        )
        changed = True
    if changed:
        conn.commit()


@register_primitive(PAPER_ACQUIRE_SPEC)
def paper_acquire(
    *,
    db: Database,
    topic_id: int,
    limit: int | None = None,
    include_candidates: bool = False,
    **_: Any,
) -> PaperAcquireOutput:
    """Download PDFs, enrich metadata, annotate, and produce unable-to-acquire list."""
    import time
    from pathlib import Path

    from ..acquisition.pipeline import acquire_papers

    # Step 1: Batch-enrich metadata for papers missing key fields
    conn = db.connect()
    enriched = 0
    try:
        pool = PaperPool(conn)
        all_papers = pool.list_papers(topic_id=topic_id)
        if limit is not None and limit > 0:
            all_papers = all_papers[: int(limit)]
        for paper in all_papers:
            if paper.id is None:
                continue
            row = conn.execute(
                "SELECT title, abstract, venue, citation_count FROM papers WHERE id = ?",
                (paper.id,),
            ).fetchone()
            if row is None:
                continue
            title_raw = (row["title"] or "").strip()
            venue_raw = (row["venue"] or "").strip().lower()
            venue_placeholder = venue_raw in (
                "",
                "arxiv",
                "arxiv.org",
                "arxiv preprint",
            )
            needs_enrichment = (
                not title_raw
                or not row["abstract"]
                or title_raw.startswith(("doi:", "s2:", "pdf:"))
                or venue_placeholder
                or row["citation_count"] is None
                or row["citation_count"] == 0
            )
            if not needs_enrichment:
                continue
            has_id = bool(paper.arxiv_id or paper.doi or paper.s2_id)
            if not has_id:
                continue
            try:
                result = pool.enrich_metadata(paper.id)
                if result and "error" not in result:
                    enriched += 1
                time.sleep(1.05)
            except SPCAcquisitionError:
                raise
            except Exception as exc:
                logger.debug("Enrichment failed for paper %d: %s", paper.id, exc)
    finally:
        conn.close()

    # Step 2: Run existing acquisition pipeline (download + annotate)
    db_path = db.path
    download_dir = Path(db_path).parent / "papers"
    artifacts_root = Path(db_path).parent / "artifacts"
    report = acquire_papers(
        db,
        topic_id,
        download_dir=download_dir,
        artifacts_root=artifacts_root,
        limit=limit,
        include_candidates=include_candidates,
    )

    # Step 3: Build priority-sorted unable-to-acquire list
    unable = _build_unable_to_acquire_list(db, topic_id)

    return PaperAcquireOutput(
        topic_id=topic_id,
        total=report.total_papers,
        downloaded=report.downloaded,
        annotated=report.annotated,
        enriched=enriched,
        failed=report.failed,
        needs_manual=report.needs_manual,
        unable_to_acquire=unable,
    )


def _build_unable_to_acquire_list(
    db: Database, topic_id: int
) -> list[UnableToAcquireItem]:
    """Build a priority-sorted list of papers still missing PDFs after acquisition."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.doi, p.arxiv_id, p.status,
                   pt.relevance
            FROM papers p
            JOIN paper_topics pt ON p.id = pt.paper_id
            WHERE pt.topic_id = ? AND (p.pdf_path IS NULL OR p.pdf_path = '')
              AND p.status != 'deleted'
              AND pt.screening_status = 'screened_in'
              AND pt.manuscript_eligible = 1
              AND COALESCE(pt.relevance, '') NOT LIKE 'dismissed%'
              AND COALESCE(pt.relevance, '') NOT LIKE 'excluded%'
            ORDER BY
                CASE pt.relevance WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                p.title
            """,
            (topic_id,),
        ).fetchall()

        items: list[UnableToAcquireItem] = []
        for r in rows:
            doi = r["doi"] or ""
            arxiv_id = r["arxiv_id"] or ""
            hint = ""
            reason = "no downloadable URL found"
            if arxiv_id:
                hint = f"https://arxiv.org/pdf/{arxiv_id.removeprefix('arxiv:')}.pdf"
                reason = "download attempted but failed"
            elif doi:
                hint = f"https://doi.org/{doi}"
                reason = "likely paywalled"
            items.append(
                UnableToAcquireItem(
                    paper_id=r["id"],
                    title=r["title"] or "",
                    relevance=r["relevance"] or "medium",
                    doi=doi,
                    arxiv_id=arxiv_id,
                    failure_reason=reason,
                    download_hint=hint,
                )
            )
        return items
    finally:
        conn.close()


def _parse_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        parsed = [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


# ---------------------------------------------------------------------------
# topic_set_contributions / topic_get_contributions — topic-level config
# ---------------------------------------------------------------------------
# Writing primitives (writing_architecture, outline_generate, figure_plan,
# competitive_learning) read this as a fallback, eliminating the need to pass
# the contributions string to every call.


@register_primitive(TOPIC_SET_CONTRIBUTIONS_SPEC)
def topic_set_contributions(
    *,
    db: Database,
    topic_id: int,
    contributions: str,
    **_: Any,
) -> TopicSetContributionsOutput:
    """Persist topic-level contributions. Overwrites any prior value."""
    text = (contributions or "").strip()
    conn = db.connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"topic_id={topic_id} not found")
        conn.execute(
            """UPDATE topics
               SET contributions = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (text, topic_id),
        )
        conn.commit()
    finally:
        conn.close()
    return TopicSetContributionsOutput(
        topic_id=topic_id, contributions=text, updated=True
    )


@register_primitive(TOPIC_GET_CONTRIBUTIONS_SPEC)
def topic_get_contributions(
    *,
    db: Database,
    topic_id: int,
    **_: Any,
) -> TopicSetContributionsOutput:
    """Read topic-level contributions. Returns empty string if unset."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT contributions FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError(f"topic_id={topic_id} not found")
    return TopicSetContributionsOutput(
        topic_id=topic_id,
        contributions=(row["contributions"] or "").strip(),
        updated=False,
    )


# ---------------------------------------------------------------------------
# Cold Start Protocol
# ---------------------------------------------------------------------------


@register_primitive(COLD_START_RUN_SPEC)
def cold_start_run(*, db, topic_id, gold_papers=None, **_):
    from ..evolution.topic.cold_start_protocol import ColdStartProtocol

    protocol = ColdStartProtocol(db=db, topic_id=topic_id, gold_papers=gold_papers)
    return protocol.check_all()
