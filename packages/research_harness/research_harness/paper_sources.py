from __future__ import annotations

from dataclasses import dataclass, field
import copy
import json
import math
import os
import re
from typing import Any, Iterable, Protocol


_TITLE_TOKEN_RE = re.compile(r"[^a-z0-9]+")

SEARCH_PROVIDER_PRIORITY: dict[str, int] = {
    "google_scholar": 120,
    # Local curated CS/AI top-venue corpus (see papervault_source.py):
    # trusted recall, but online sources still win metadata field merges.
    "papervault": 119,
    "sciverse": 118,
    "openalex": 115,
    "semantic_scholar": 110,
    "openreview": 105,
    "arxiv": 100,
    "pubmed": 98,
    "crossref": 95,
    "dblp": 90,
    "pasa": 50,
    "manual": 200,
}

METADATA_FIELD_PRIORITY: dict[str, int] = {
    "manual": 200,
    "openalex": 130,
    "crossref": 125,
    "sciverse": 122,
    "arxiv": 120,
    "openreview": 118,
    "semantic_scholar": 112,
    "pubmed": 110,
    "papervault": 108,
    "dblp": 105,
    "google_scholar": 95,
}

PDF_SOURCE_PRIORITY: dict[str, int] = {
    "manual_pdf": 220,
    "local_file": 210,
    "open_access_pdf": 190,
    "arxiv_pdf": 185,
    "openreview_pdf": 180,
    "publisher_pdf": 130,
    # content.openalex.org needs configured authorization (401 without an
    # API key) — never rank it above public OA/publisher links.
    "openalex_content": 100,
    "doi_landing": 80,
    "browser_session": 70,
}


@dataclass(frozen=True)
class SearchQuery:
    query: str
    topic: str = ""
    year_from: int | None = None
    year_to: int | None = None
    limit: int = 50
    subject_categories: tuple[str, ...] | None = None
    per_provider_limit: int = 50


@dataclass(frozen=True)
class PDFCandidate:
    url: str
    source_type: str
    provider: str
    requires_browser: bool = False
    confidence: float = 0.5
    license_hint: str = ""

    @property
    def priority(self) -> int:
        return PDF_SOURCE_PRIORITY.get(self.source_type, 0)


@dataclass
class ProviderError:
    provider: str
    error_type: str
    message: str


@dataclass
class SearchOutcome:
    results: list[PaperRecord]
    provider_errors: list[ProviderError] = field(default_factory=list)


@dataclass
class PaperRecord:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    journal: str = ""
    publisher: str = ""
    document_type: str = ""
    abstract: str = ""
    doi: str = ""
    arxiv_id: str = ""
    s2_id: str = ""
    openalex_id: str = ""
    openreview_id: str = ""
    pmid: str = ""
    pmcid: str = ""
    url: str = ""
    provider: str = ""
    citation_count: int | None = None
    reference_count: int | None = None
    pdf_candidates: list[PDFCandidate] = field(default_factory=list)
    concepts: list[dict] = field(default_factory=list)  # OpenAlex concept tags
    source_rank: int = 0
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    recall_hits: list[dict[str, Any]] = field(default_factory=list)
    institution_signals: dict[str, Any] | None = None
    fulltext_status: dict[str, Any] = field(default_factory=dict)
    recorded_facts: dict[str, Any] = field(default_factory=dict)
    available_files: dict[str, Any] = field(default_factory=dict)
    curation_signals: dict[str, Any] = field(default_factory=dict)
    merged_from: list[str] = field(default_factory=list)
    field_conflicts: list[dict[str, Any]] = field(default_factory=list)
    selection_rank: int | None = None
    selection_bucket: str | None = None
    selection_basis: list[str] = field(default_factory=list)
    requires_agent_review: list[str] = field(default_factory=list)

    def fingerprint(self) -> str:
        for value in (
            self.doi,
            normalize_arxiv_id(self.arxiv_id),
            self.openreview_id,
            self.s2_id,
            self.openalex_id,
            self.pmid,
            self.pmcid,
        ):
            cleaned = (value or "").strip().lower()
            if cleaned:
                return cleaned
        normalized_title = normalize_title(self.title)
        normalized_year = str(self.year or "")
        return f"title:{normalized_title}:{normalized_year}"


class SearchProvider(Protocol):
    name: str

    def search(self, query: SearchQuery) -> list[PaperRecord]: ...


def normalize_title(value: str) -> str:
    lowered = value.strip().lower()
    lowered = _TITLE_TOKEN_RE.sub(" ", lowered)
    return " ".join(lowered.split())


# Providers disagree on arXiv id shape: Semantic Scholar reports "2608.14036",
# the arXiv API reports "2608.14036v1", and some sources prefix "arXiv:" or ship
# a full abs/pdf URL. Left alone, the same paper gets two fingerprints and any
# downstream id match silently misses one of them.
_ARXIV_ID_RE = re.compile(
    r"(?:arxiv[:\s]*)?(?:abs/|pdf/)?"
    r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})"
    r"(?:v\d+)?",
    re.IGNORECASE,
)


def normalize_arxiv_id(value: str) -> str:
    """Canonical, version-stripped arXiv id.

    ``2608.14036v1`` / ``arXiv:2608.14036`` / ``https://arxiv.org/abs/2608.14036``
    all collapse to ``2608.14036``. Old-style ids (``math/0309136v2``) keep their
    archive prefix. Unrecognizable input is passed through lowercased rather than
    dropped — losing an id we merely failed to parse is worse than keeping it.
    """
    raw = str(value or "").strip()
    matches = _ARXIV_ID_RE.findall(raw)
    if len(set(matches)) > 1:
        # Several distinct ids in one field is corrupt input — a caller passed a
        # LIST where an id was expected (a shell loop that failed to word-split
        # does exactly this). Canonicalizing would keep the first and drop the
        # rest, turning obvious corruption into a plausible wrong id. Leave it
        # raw so the damage stays visible to the quarantine checks downstream.
        return raw.lower()
    if not matches:
        return raw.lower()
    return matches[0].lower()


def title_year_key(record: PaperRecord) -> str:
    return f"{normalize_title(record.title)}::{record.year or ''}"


def provider_priority(provider: str, table: dict[str, int]) -> int:
    return table.get(provider, 0)


def _default_search_time_budget() -> float:
    """Wall-clock budget for one multi-provider search, in seconds.

    Bounded so one slow/retrying provider (PASA SSL EOF loops, Crossref 429
    backoff) cannot stall the whole fan-out; set to 0 to disable the cap.
    """
    raw = os.environ.get("RESEARCH_HARNESS_SEARCH_TIME_BUDGET_SEC", "").strip()
    try:
        return float(raw) if raw else 210.0
    except ValueError:
        return 210.0


class SearchAggregator:
    def __init__(self, providers: Iterable[SearchProvider]):
        self.providers = list(providers)

    def search(
        self,
        query: SearchQuery,
        *,
        output_limit: int | None = None,
        time_budget_sec: float | None = None,
    ) -> SearchOutcome:
        """Search all providers and merge results.

        Each provider is queried with ``query.limit`` (per-provider cap).
        The merged output is capped at ``output_limit`` when provided, otherwise
        all unique merged results are returned so callers can apply their own cap.

        Providers that do not answer within ``time_budget_sec`` (default from
        RESEARCH_HARNESS_SEARCH_TIME_BUDGET_SEC, 210s) are reported as timeout
        provider errors and the partial merged results are returned. Their
        worker threads are abandoned, not interrupted — they finish in the
        background bounded by their own request timeouts.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from concurrent.futures import TimeoutError as FuturesTimeoutError

        merged: dict[str, PaperRecord] = {}
        title_index: dict[str, str] = {}
        provider_errors: list[ProviderError] = []

        if not self.providers:
            return SearchOutcome(results=[], provider_errors=[])

        if time_budget_sec is None:
            time_budget_sec = _default_search_time_budget()
        timeout = time_budget_sec if time_budget_sec and time_budget_sec > 0 else None

        def _query_one(
            provider: SearchProvider,
        ) -> tuple[SearchProvider, list[PaperRecord]]:
            return provider, provider.search(query)

        def _merge_provider_records(
            provider: SearchProvider, records: list[PaperRecord]
        ) -> None:
            for record in records:
                provider_name = record.provider or provider.name
                record.provider = provider_name
                # Fingerprints normalize IDs; retain the requested arXiv version.
                record.source_rank = provider_priority(
                    provider_name, SEARCH_PROVIDER_PRIORITY
                )
                key = record.fingerprint()
                title_key = title_year_key(record)
                existing_key = key if key in merged else title_index.get(title_key)
                if existing_key is not None:
                    merged_record = merge_records(merged[existing_key], record)
                    canonical_key = merged_record.fingerprint()
                    if canonical_key != existing_key:
                        del merged[existing_key]
                    merged[canonical_key] = merged_record
                    title_index[title_key] = canonical_key
                else:
                    merged[key] = clone_record(record)
                    title_index[title_key] = key

        # SPC is one optional lane among several. Its failure is reported like
        # any other provider's; it is raised only when no provider answered, so
        # an outage never turns into a silent empty result.
        answered = 0
        spc_failure: Exception | None = None
        executor = ThreadPoolExecutor(max_workers=len(self.providers))
        futures = {executor.submit(_query_one, p): p for p in self.providers}
        pending = set(futures)
        try:
            for future in as_completed(futures, timeout=timeout):
                pending.discard(future)
                provider = futures[future]
                try:
                    _, records = future.result()
                except Exception as exc:
                    if getattr(provider, "name", "") == "spc":
                        if getattr(exc, "code", "") == "no_results":
                            answered += 1  # an empty answer, not a failure
                            continue
                        spc_failure = exc
                    provider_errors.append(
                        ProviderError(
                            provider=getattr(
                                provider, "name", provider.__class__.__name__
                            ),
                            error_type=exc.__class__.__name__,
                            message=str(exc),
                        )
                    )
                    continue
                answered += 1
                _merge_provider_records(provider, records)
        except FuturesTimeoutError:
            for future in pending:
                future.cancel()
                provider = futures[future]
                if getattr(provider, "name", "") == "spc":
                    from .acquisition.spc_bridge import SPCAcquisitionError

                    spc_failure = SPCAcquisitionError(
                        "search",
                        {
                            "error": {
                                "code": "search_time_budget_exceeded",
                                "retryable": True,
                            }
                        },
                    )
                provider_errors.append(
                    ProviderError(
                        provider=getattr(provider, "name", provider.__class__.__name__),
                        error_type="SearchTimeBudgetExceeded",
                        message=(
                            f"provider did not finish within {time_budget_sec:.0f}s "
                            "search time budget; partial results returned"
                        ),
                    )
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if spc_failure is not None and not answered:
            raise spc_failure
        ranked = sorted(
            merged.values(),
            key=lambda record: rank_record(record, query.query),
            reverse=True,
        )
        cap = output_limit if output_limit is not None else len(ranked)
        return SearchOutcome(results=ranked[:cap], provider_errors=provider_errors)


class PDFResolver:
    def plan(self, record: PaperRecord) -> list[PDFCandidate]:
        merged: dict[tuple[str, str], PDFCandidate] = {}
        for candidate in record.pdf_candidates:
            key = (candidate.url.strip(), candidate.source_type)
            if not key[0]:
                continue
            current = merged.get(key)
            if current is None or rank_pdf_candidate(candidate) > rank_pdf_candidate(
                current
            ):
                merged[key] = candidate

        if record.arxiv_id:
            arxiv_url = (
                f"https://arxiv.org/pdf/{record.arxiv_id.removeprefix('arXiv:')}.pdf"
            )
            candidate = PDFCandidate(
                url=arxiv_url,
                source_type="arxiv_pdf",
                provider="arxiv",
                confidence=0.98,
            )
            key = (candidate.url, candidate.source_type)
            merged.setdefault(key, candidate)

        if record.openreview_id:
            openreview_url = f"https://openreview.net/pdf?id={record.openreview_id}"
            candidate = PDFCandidate(
                url=openreview_url,
                source_type="openreview_pdf",
                provider="openreview",
                confidence=0.9,
            )
            key = (candidate.url, candidate.source_type)
            merged.setdefault(key, candidate)

        if record.doi:
            doi_url = f"https://doi.org/{record.doi}"
            candidate = PDFCandidate(
                url=doi_url,
                source_type="doi_landing",
                provider="crossref",
                confidence=0.6,
            )
            key = (candidate.url, candidate.source_type)
            merged.setdefault(key, candidate)

        return sorted(merged.values(), key=rank_pdf_candidate, reverse=True)


def merge_records(base: PaperRecord, incoming: PaperRecord) -> PaperRecord:
    result = clone_record(base)
    result.pdf_candidates = list(base.pdf_candidates)
    result.field_conflicts = list(base.field_conflicts) + list(incoming.field_conflicts)
    result.source_rank = max(base.source_rank, incoming.source_rank)

    _merge_scalar(result, incoming, "title")
    _merge_scalar(result, incoming, "venue")
    _merge_scalar(result, incoming, "journal")
    _merge_scalar(result, incoming, "publisher")
    _merge_scalar(result, incoming, "document_type")
    _merge_scalar(result, incoming, "abstract")
    _merge_scalar(result, incoming, "doi")
    _merge_scalar(result, incoming, "arxiv_id")
    _merge_scalar(result, incoming, "s2_id")
    _merge_scalar(result, incoming, "openalex_id")
    _merge_scalar(result, incoming, "openreview_id")
    _merge_scalar(result, incoming, "pmid")
    _merge_scalar(result, incoming, "pmcid")
    _merge_scalar(result, incoming, "url")
    _merge_numeric(result, incoming, "year")
    _merge_numeric(result, incoming, "citation_count")
    _merge_numeric(result, incoming, "reference_count")
    _merge_recorded_facts(result, base, incoming)
    result.source_refs = _dedupe_dicts(base.source_refs + incoming.source_refs)
    result.recall_hits = _dedupe_dicts(base.recall_hits + incoming.recall_hits)
    result.merged_from = list(
        dict.fromkeys(
            source
            for source in (
                base.merged_from
                + incoming.merged_from
                + [base.provider, incoming.provider]
            )
            if source
        )
    )
    result.available_files = _merge_dicts(
        base.available_files, incoming.available_files
    )
    result.curation_signals = _merge_dicts(
        base.curation_signals, incoming.curation_signals
    )
    if incoming.institution_signals and not result.institution_signals:
        result.institution_signals = copy.deepcopy(incoming.institution_signals)
    result.requires_agent_review = list(
        dict.fromkeys(base.requires_agent_review + incoming.requires_agent_review)
    )
    result.selection_basis = list(
        dict.fromkeys(base.selection_basis + incoming.selection_basis)
    )
    result.selection_rank = (
        base.selection_rank
        if base.selection_rank is not None
        else incoming.selection_rank
    )
    result.selection_bucket = base.selection_bucket or incoming.selection_bucket

    if incoming.authors and (
        not result.authors
        or provider_priority(incoming.provider, METADATA_FIELD_PRIORITY)
        >= provider_priority(base.provider, METADATA_FIELD_PRIORITY)
    ):
        result.authors = list(dict.fromkeys(incoming.authors))

    if incoming.affiliations and (
        not result.affiliations
        or provider_priority(incoming.provider, METADATA_FIELD_PRIORITY)
        >= provider_priority(base.provider, METADATA_FIELD_PRIORITY)
    ):
        result.affiliations = list(dict.fromkeys(incoming.affiliations))

    existing_urls = {(item.url, item.source_type) for item in result.pdf_candidates}
    for candidate in incoming.pdf_candidates:
        key = (candidate.url, candidate.source_type)
        if candidate.url and key not in existing_urls:
            result.pdf_candidates.append(candidate)
            existing_urls.add(key)
    return result


def clone_record(record: PaperRecord) -> PaperRecord:
    return PaperRecord(
        title=record.title,
        authors=list(record.authors),
        affiliations=list(record.affiliations),
        year=record.year,
        venue=record.venue,
        journal=record.journal,
        publisher=record.publisher,
        document_type=record.document_type,
        abstract=record.abstract,
        doi=record.doi,
        arxiv_id=record.arxiv_id,
        s2_id=record.s2_id,
        openalex_id=record.openalex_id,
        openreview_id=record.openreview_id,
        pmid=record.pmid,
        pmcid=record.pmcid,
        url=record.url,
        provider=record.provider,
        citation_count=record.citation_count,
        reference_count=record.reference_count,
        pdf_candidates=list(record.pdf_candidates),
        concepts=list(record.concepts),
        source_rank=record.source_rank,
        source_refs=copy.deepcopy(record.source_refs),
        recall_hits=copy.deepcopy(record.recall_hits),
        institution_signals=copy.deepcopy(record.institution_signals),
        fulltext_status=copy.deepcopy(record.fulltext_status),
        recorded_facts=copy.deepcopy(record.recorded_facts),
        available_files=copy.deepcopy(record.available_files),
        curation_signals=copy.deepcopy(record.curation_signals),
        merged_from=list(record.merged_from),
        field_conflicts=copy.deepcopy(record.field_conflicts),
        selection_rank=record.selection_rank,
        selection_bucket=record.selection_bucket,
        selection_basis=list(record.selection_basis),
        requires_agent_review=list(record.requires_agent_review),
    )


def _merge_scalar(result: PaperRecord, incoming: PaperRecord, field_name: str) -> None:
    existing_value = getattr(result, field_name)
    incoming_value = getattr(incoming, field_name)
    if not incoming_value:
        return
    incoming_wins = provider_priority(
        incoming.provider, METADATA_FIELD_PRIORITY
    ) >= provider_priority(result.provider, METADATA_FIELD_PRIORITY)
    if existing_value and not _values_equal(existing_value, incoming_value):
        _append_field_conflict(
            result,
            field_name,
            existing_value,
            result.provider,
            incoming_value,
            incoming.provider,
            incoming.provider if incoming_wins else result.provider,
        )
    if not existing_value or incoming_wins:
        setattr(result, field_name, incoming_value)
        if field_name != "title":
            result.provider = incoming.provider


def _merge_numeric(result: PaperRecord, incoming: PaperRecord, field_name: str) -> None:
    incoming_value = getattr(incoming, field_name)
    if incoming_value is None:
        return
    existing_value = getattr(result, field_name)
    if existing_value is None or provider_priority(
        incoming.provider, METADATA_FIELD_PRIORITY
    ) >= provider_priority(result.provider, METADATA_FIELD_PRIORITY):
        setattr(result, field_name, incoming_value)


def _merge_recorded_facts(
    result: PaperRecord, base: PaperRecord, incoming: PaperRecord
) -> None:
    if not incoming.recorded_facts:
        return
    incoming_wins = provider_priority(
        incoming.provider, METADATA_FIELD_PRIORITY
    ) >= provider_priority(base.provider, METADATA_FIELD_PRIORITY)
    base_venue = (base.recorded_facts or {}).get("venue_metadata")
    incoming_venue = incoming.recorded_facts.get("venue_metadata")
    result.recorded_facts = _merge_fact_dicts(
        base.recorded_facts,
        incoming.recorded_facts,
        incoming_wins=incoming_wins,
    )
    if base_venue and incoming_venue and not _values_equal(base_venue, incoming_venue):
        _append_field_conflict(
            result,
            "recorded_facts.venue_metadata",
            base_venue,
            base.provider,
            incoming_venue,
            incoming.provider,
            incoming.provider if incoming_wins else base.provider,
        )


def _merge_dicts(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in incoming.items():
        if value not in (None, "", [], {}):
            merged[key] = copy.deepcopy(value)
    return merged


def _merge_fact_dicts(
    base: dict[str, Any], incoming: dict[str, Any], *, incoming_wins: bool
) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = copy.deepcopy(value)
        elif incoming_wins:
            merged[key] = copy.deepcopy(value)
    return merged


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        output.append(copy.deepcopy(item))
    return output


def _values_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, ensure_ascii=False, sort_keys=True) == json.dumps(
        right, ensure_ascii=False, sort_keys=True
    )


def _append_field_conflict(
    record: PaperRecord,
    field_name: str,
    existing_value: Any,
    existing_source: str,
    incoming_value: Any,
    incoming_source: str,
    selected_source: str,
) -> None:
    conflict = {
        "field": field_name,
        "values": [
            {"source": existing_source, "value": existing_value},
            {"source": incoming_source, "value": incoming_value},
        ],
        "selected_source": selected_source,
    }
    if conflict not in record.field_conflicts:
        record.field_conflicts.append(conflict)


def rank_record(record: PaperRecord, query_text: str = "") -> tuple[float, str]:
    """Merged-result ranking: query relevance dominates, provider is a prior.

    This was a lexicographic tuple led by ``source_rank``: every OpenAlex
    record outranked every Semantic Scholar record outranked every arXiv
    record regardless of topical match, so when the merged set was capped the
    cap filled with the highest-priority provider's fuzzy tail while exact
    hits from lower-priority providers were dropped (anchor-replay stage 1,
    2026-08-10: 1/87 gold-reference recall while S2 alone returned the
    missing papers at rank 1). Provider priority still merges metadata
    fields (METADATA_FIELD_PRIORITY) and breaks ranking ties, but it must
    never outrank relevance.
    """
    title_frac = query_token_coverage(record, query_text)
    pdf_bonus = (
        1 if record.pdf_candidates or record.arxiv_id or record.openreview_id else 0
    )
    id_bonus = sum(
        1
        for item in (
            record.doi,
            record.arxiv_id,
            record.s2_id,
            record.openalex_id,
            record.openreview_id,
            record.pmid,
            record.pmcid,
        )
        if item
    )
    citation_score = math.log1p(record.citation_count or 0) / 15.0
    composite = (
        title_frac
        + pdf_bonus * 0.05
        + id_bonus * 0.01
        + citation_score * 0.1
        + record.source_rank / 2000.0
    )
    return (round(composite, 6), normalize_title(record.title))


def query_title_match_score(record: PaperRecord, query_text: str) -> int:
    if not query_text.strip():
        return 0
    normalized_query = normalize_title(query_text)
    normalized_title = normalize_title(record.title)
    if normalized_title == normalized_query:
        return 3
    if normalized_query and normalized_query in normalized_title:
        return 2
    query_tokens = set(normalized_query.split())
    title_tokens = set(normalized_title.split())
    if query_tokens and query_tokens.issubset(title_tokens):
        return 1
    return 0


def query_token_coverage(record: PaperRecord, query_text: str) -> float:
    """Fraction of query tokens present in title+abstract head (0..1).

    ``query_title_match_score``'s 0-3 ladder scores most topical matches 0
    (exact/substring/subset only) — too coarse to rank a merged candidate
    set for a natural-language query.
    """
    if not query_text.strip():
        return 0.0
    query_tokens = set(normalize_title(query_text).split())
    if not query_tokens:
        return 0.0
    haystack = set(normalize_title(record.title).split())
    if record.abstract:
        haystack |= set(normalize_title(record.abstract[:500]).split())
    return len(query_tokens & haystack) / len(query_tokens)


def rank_pdf_candidate(candidate: PDFCandidate) -> tuple[int, float, int, str]:
    browser_penalty = 0 if not candidate.requires_browser else -1
    return (candidate.priority, candidate.confidence, browser_penalty, candidate.url)
