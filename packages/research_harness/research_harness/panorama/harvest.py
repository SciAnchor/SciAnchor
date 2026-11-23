"""Academic harvest for the Domain Panorama KB (plan §4–§5).

Multi-source query harvest feeding capture-recapture coverage estimation.
Every source×query is persisted via :meth:`PanoramaStore.record_harvest_run`,
so the harvest ledger doubles as the raw capture data for Chao-style
estimators (see ``coverage.py``). Records are normalized to one shape::

    {"title", "abstract", "year", "venue", "ids": {arxiv?, doi?, openalex?,
     s2?}, "url"}

and deduplicated across sources by :func:`canonical_identity` (precedence:
arxiv > doi > openalex > s2 > title hash). Triage-passing records are
imported as ``paper`` entities under a total per-call ``import_budget``.

Network access goes through an injectable ``fetcher`` callable so tests can
run fully offline.
"""

from __future__ import annotations

from research_harness.acquisition.spc_bridge import SPCAcquisitionError

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from .store import PanoramaStore

Fetcher = Callable[[str], bytes]

USER_AGENT = "research-harness-panorama/0.1 (+https://github.com/scianchor/scianchor)"

# Env var names carrying provider credentials (read from the RH private.env).

DEFAULT_QUERIES: dict[str, list[str]] = {
    "automated-research": [
        "AI scientist",
        "research agent",
        "autonomous scientific discovery",
        "automated research pipeline",
        "LLM hypothesis generation",
        "research ideation",
        "automated peer review",
        "ML research agent benchmark",
        "agentic science",
        "automated experiment design",
        "literature review automation",
        "laboratory automation LLM",
        # 2026-08-17: merged in the expanded panorama query set (queries.json) so the
        # recurring --since sweep covers the same surface as the initial build.
        "scientific hypothesis generation",
        "automatic survey generation",
        "scientific claim verification",
        "novelty assessment scientific ideas",
        "self-driving laboratory",
        "agentic workflow science",
        "LLM agent machine learning experimentation",
        "academic paper writing automation",
        "scientific knowledge graph construction",
        "research workflow provenance",
        "automated falsification hypothesis validation",
        "autonomous experimentation",
        "scientific reasoning language model agent",
        "literature-based discovery",
        "end-to-end automation of research",
        "LLM scientific paper review quality",
        "data-driven discovery agent",
        "citation-grounded scientific synthesis",
    ],
}

DEFAULT_TRIAGE_KEYWORDS: list[str] = [
    "ai scientist",
    "research agent",
    "autonomous research",
    "automated research",
    "automated scientific",
    "autonomous scientific",
    "scientific discovery",
    "hypothesis generation",
    "research ideation",
    "idea generation",
    "automated peer review",
    "paper generation",
    "research assistant",
    "agentic",
]

_SUMMARY_MAX = 600
_ABSTRACT_ATTR_MAX = 1500
_ID_SCHEMES = ("arxiv", "doi", "openalex", "s2")
_ARXIV_VERSION_RE = re.compile(r"v\d+$")
_ARXIV_URL_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf)/([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?(?:$|[?#])",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")

_S2_MIN_INTERVAL = 1.1
_S2_MAX_RETRIES = 3
_last_s2_call = 0.0


# -- fetcher ----------------------------------------------------------------


def make_fetcher(extra_headers: dict[str, str] | None = None) -> Fetcher:
    """Build a fetcher closure with a polite UA plus optional extra headers.

    Used to bake per-source credentials (e.g. Semantic Scholar ``x-api-key``)
    into the request without changing the ``fetcher(url)`` call contract.
    """
    headers = {"User-Agent": USER_AGENT}
    if extra_headers:
        headers.update({k: v for k, v in extra_headers.items() if v})

    def _fetch(url: str, *, timeout: float = 30.0) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(3):
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(  # noqa: S310
                    request, timeout=timeout
                ) as resp:
                    return resp.read()
            except urllib.error.HTTPError:
                raise
            except Exception as exc:  # transient transport errors
                last_exc = exc
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
        raise last_exc if last_exc else RuntimeError(f"fetch failed: {url}")

    return _fetch


default_fetcher = make_fetcher()


def default_source_fetchers() -> dict[str, Fetcher]:
    """Per-source fetchers. Every source is queried keyless at its public rate
    limit (OpenAlex's polite pool via the mailto UA); no credentials are read."""
    return {}


# -- normalization helpers --------------------------------------------------


def _strip_arxiv_version(value: str) -> str:
    return _ARXIV_VERSION_RE.sub("", value.strip().lower())


def _arxiv_from_url(url: str | None) -> str:
    if not url or "arxiv.org" not in url.casefold():
        return ""
    match = _ARXIV_URL_RE.search(url)
    return _strip_arxiv_version(match.group(1)) if match else ""


def _norm_doi(value: str | None) -> str:
    doi = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi.strip("/") if doi else ""


def _openalex_work_id(value: str | None) -> str:
    work = (value or "").strip()
    return work.rsplit("/", 1)[-1] if work else ""


def _norm_scheme_value(scheme: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if scheme == "arxiv":
        return _strip_arxiv_version(text)
    if scheme == "doi":
        return _norm_doi(text)
    if scheme == "openalex":
        return _openalex_work_id(text)
    return text


def _title_hash(title: str) -> str:
    collapsed = "".join(ch for ch in (title or "").casefold() if ch.isalnum())
    return hashlib.sha1(collapsed.encode("utf-8")).hexdigest()[:16]


def _record_identities(record: dict[str, Any]) -> list[tuple[str, str]]:
    """All (identity, scheme) pairs for a record, in precedence order."""
    ids = record.get("ids") or {}
    out: list[tuple[str, str]] = []
    for scheme in _ID_SCHEMES:
        value = _norm_scheme_value(scheme, ids.get(scheme))
        if value:
            out.append((f"{scheme}:{value}", scheme))
    out.append((f"title:{_title_hash(str(record.get('title') or ''))}", "title"))
    return out


def canonical_identity(record: dict[str, Any]) -> tuple[str, str]:
    """Canonical (identity, scheme) with arxiv > doi > openalex > s2 > title."""
    return _record_identities(record)[0]


def _clean_text(text: Any) -> str:
    return _WS_RE.sub(" ", str(text or "")).strip()


def _make_record(
    *,
    title: str,
    abstract: str,
    year: int | None,
    venue: str,
    ids: dict[str, str],
    url: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "abstract": abstract,
        "year": year,
        "venue": venue,
        "ids": {k: v for k, v in ids.items() if v},
        "url": url,
    }


# -- source clients ---------------------------------------------------------


def _openalex_abstract(inverted: Any) -> str:
    if not isinstance(inverted, dict) or not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted.items():
        if not isinstance(indexes, list):
            continue
        positions.extend((i, str(word)) for i in indexes if isinstance(i, int))
    positions.sort()
    return " ".join(word for _, word in positions)


def search_openalex(
    query: str, limit: int, fetcher: Fetcher, *, since: str | None = None
) -> list[dict[str, Any]]:
    """Search the OpenAlex works API; returns normalized records."""
    url = (
        "https://api.openalex.org/works?search="
        f"{urllib.parse.quote(query)}&per-page={min(int(limit), 50)}"
    )
    if since:
        url += f"&filter=from_publication_date:{since}&sort=publication_date:desc"
    payload = json.loads(fetcher(url))
    records: list[dict[str, Any]] = []
    results = payload.get("results") if isinstance(payload, dict) else None
    for work in results if isinstance(results, list) else []:
        if not isinstance(work, dict):
            continue
        title = _clean_text(work.get("display_name") or work.get("title"))
        primary = work.get("primary_location")
        primary = primary if isinstance(primary, dict) else {}
        source_meta = primary.get("source")
        source_meta = source_meta if isinstance(source_meta, dict) else {}
        ids_obj = work.get("ids")
        ids_obj = ids_obj if isinstance(ids_obj, dict) else {}
        arxiv = _arxiv_from_url(primary.get("landing_page_url")) or _arxiv_from_url(
            primary.get("pdf_url")
        )
        if not arxiv:
            locations = work.get("locations")
            for loc in locations if isinstance(locations, list) else []:
                if not isinstance(loc, dict):
                    continue
                arxiv = _arxiv_from_url(loc.get("pdf_url")) or _arxiv_from_url(
                    loc.get("landing_page_url")
                )
                if arxiv:
                    break
        year = work.get("publication_year")
        records.append(
            _make_record(
                title=title,
                abstract=_openalex_abstract(work.get("abstract_inverted_index")),
                year=year if isinstance(year, int) else None,
                venue=_clean_text(source_meta.get("display_name")),
                ids={
                    "arxiv": arxiv,
                    "doi": _norm_doi(work.get("doi") or ids_obj.get("doi")),
                    "openalex": _openalex_work_id(
                        work.get("id") or ids_obj.get("openalex")
                    ),
                },
                url=str(primary.get("landing_page_url") or work.get("id") or ""),
            )
        )
    return records


def _s2_pace() -> None:
    global _last_s2_call
    wait = _S2_MIN_INTERVAL - (time.monotonic() - _last_s2_call)
    if wait > 0:
        time.sleep(wait)
    _last_s2_call = time.monotonic()


def search_s2(
    query: str, limit: int, fetcher: Fetcher, *, since: str | None = None
) -> list[dict[str, Any]]:
    """Search the Semantic Scholar graph API; retries on HTTP 429."""
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search?query="
        f"{urllib.parse.quote(query)}&limit={min(int(limit), 50)}"
        "&fields=title,abstract,externalIds,year,venue"
    )
    if since:
        url += f"&publicationDateOrYear={since}:"
    raw: bytes | None = None
    for attempt in range(_S2_MAX_RETRIES + 1):
        _s2_pace()
        try:
            raw = fetcher(url)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < _S2_MAX_RETRIES:
                time.sleep(_S2_MIN_INTERVAL * (2**attempt))
                continue
            raise
    payload = json.loads(raw if raw is not None else b"{}")
    records: list[dict[str, Any]] = []
    data = payload.get("data") if isinstance(payload, dict) else None
    for paper in data if isinstance(data, list) else []:
        if not isinstance(paper, dict):
            continue
        external = paper.get("externalIds")
        external = external if isinstance(external, dict) else {}
        paper_id = str(paper.get("paperId") or "").strip()
        year = paper.get("year")
        records.append(
            _make_record(
                title=_clean_text(paper.get("title")),
                abstract=str(paper.get("abstract") or "").strip(),
                year=year if isinstance(year, int) else None,
                venue=_clean_text(paper.get("venue")),
                ids={
                    "arxiv": _strip_arxiv_version(str(external.get("ArXiv") or "")),
                    "doi": _norm_doi(external.get("DOI")),
                    "s2": paper_id,
                },
                url=(
                    f"https://www.semanticscholar.org/paper/{paper_id}"
                    if paper_id
                    else ""
                ),
            )
        )
    return records


def search_arxiv(
    query: str, limit: int, fetcher: Fetcher, *, since: str | None = None
) -> list[dict[str, Any]]:
    """Search the arXiv Atom API; union multi-form queries (E2).

    ``since`` (recency mode) sorts by submission date so a recurring sweep
    sees the newest entries first; arXiv's API has no server-side date
    filter, so ordering is the recency contract here.
    """
    from research_harness.retrieval_hygiene import arxiv_query_forms

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    cap = min(int(limit), 50)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for form in arxiv_query_forms(query):
        encoded = urllib.parse.quote(form)
        url = (
            "https://export.arxiv.org/api/query?search_query="
            f"{encoded}&max_results={cap}"
        )
        if since:
            url += "&sortBy=submittedDate&sortOrder=descending"
        root = ET.fromstring(fetcher(url))  # noqa: S314 - trusted API, tests offline
        for entry in root.findall("atom:entry", ns):
            id_url = (entry.findtext("atom:id", "", ns) or "").strip()
            arxiv_id = _arxiv_from_url(id_url)
            key = arxiv_id or id_url
            if not key or key in seen:
                continue
            seen.add(key)
            published = entry.findtext("atom:published", "", ns) or ""
            year = int(published[:4]) if published[:4].isdigit() else None
            records.append(
                _make_record(
                    title=_clean_text(entry.findtext("atom:title", "", ns)),
                    abstract=_clean_text(entry.findtext("atom:summary", "", ns)),
                    year=year,
                    venue=_clean_text(entry.findtext("arxiv:journal_ref", "", ns)),
                    ids={
                        "arxiv": arxiv_id,
                        "doi": _norm_doi(entry.findtext("arxiv:doi", "", ns)),
                    },
                    url=id_url,
                )
            )
            if len(records) >= cap:
                return records
    return records


def search_managed(
    query: str, limit: int, fetcher: Fetcher, *, since: str | None = None
) -> list[dict[str, Any]]:
    from research_harness.paper_source_clients import build_provider_suite
    from research_harness.paper_sources import SearchAggregator, SearchQuery

    year = int(since[:4]) if since else None
    outcome = SearchAggregator(build_provider_suite()).search(
        SearchQuery(query=query, limit=limit, year_from=year),
        output_limit=limit,
    )
    if not outcome.results and outcome.provider_errors:
        raise RuntimeError("Managed scholarly harvest unavailable")
    return [
        _make_record(
            title=r.title,
            abstract=r.abstract,
            year=r.year,
            venue=r.venue,
            ids={"doi": r.doi, "arxiv": r.arxiv_id},
            url=r.url,
        )
        for r in outcome.results
    ]


SOURCE_CLIENTS: dict[str, Callable[[str, int, Fetcher], list[dict[str, Any]]]] = {
    "managed": search_managed,
    "openalex": search_openalex,
    "s2": search_s2,
    "arxiv": search_arxiv,
}


# -- triage / import core ---------------------------------------------------


def _triage(record: dict[str, Any], keywords: Sequence[str]) -> bool:
    haystack = f"{record.get('title') or ''} {record.get('abstract') or ''}".casefold()
    return any(k.casefold() in haystack for k in keywords if k)


def _known_identities(store: PanoramaStore, direction_id: int) -> dict[str, int]:
    """identity -> entity id, preloaded from existing entities' ext ids + name."""
    known: dict[str, int] = {}
    for entity in store.entities(direction_id):
        entity_id = int(entity["id"])
        ext_ids = entity.get("ext_ids") or {}
        for scheme in _ID_SCHEMES:
            value = _norm_scheme_value(scheme, ext_ids.get(scheme))
            if value:
                known.setdefault(f"{scheme}:{value}", entity_id)
        known.setdefault(f"title:{_title_hash(entity.get('name') or '')}", entity_id)
    return known


def _import_record(
    store: PanoramaStore,
    direction_id: int,
    record: dict[str, Any],
    source: str,
) -> int:
    abstract = str(record.get("abstract") or "").strip()
    attrs: dict[str, Any] = {}
    for key in ("year", "venue", "url"):
        if record.get(key):
            attrs[key] = record[key]
    if abstract:
        attrs["abstract"] = abstract[:_ABSTRACT_ATTR_MAX]
    ext_ids = {
        scheme: _norm_scheme_value(scheme, (record.get("ids") or {}).get(scheme))
        for scheme in _ID_SCHEMES
    }
    return store.upsert_entity(
        direction_id,
        "paper",
        str(record["title"]).strip(),
        summary=abstract[:_SUMMARY_MAX],
        attrs=attrs,
        ext_ids={k: v for k, v in ext_ids.items() if v},
        source=f"harvest:{source}",
    )


def _ingest_query(
    store: PanoramaStore,
    direction_id: int,
    source: str,
    query: str,
    records: Iterable[dict[str, Any]],
    *,
    keywords: Sequence[str],
    known: dict[str, int],
    seen: set[str],
    budget: dict[str, Any],
    round_no: int,
) -> dict[str, int]:
    """Triage, import (within budget), and log one source×query run."""
    hits: list[dict[str, Any]] = []
    hit_identities: set[str] = set()
    imported = 0
    for record in records:
        identities = _record_identities(record)
        identity, scheme = identities[0]
        relevant = _triage(record, keywords)
        entity_id: int | None = None
        for ident, _ in identities:
            if ident in known:
                entity_id = known[ident]
                break
        if entity_id is None and relevant and str(record.get("title") or "").strip():
            if budget["remaining"] > 0:
                entity_id = _import_record(store, direction_id, record, source)
                budget["remaining"] -= 1
                imported += 1
                for ident, _ in identities:
                    known.setdefault(ident, entity_id)
            else:
                budget["exhausted"] = True
        if identity not in hit_identities:
            hit_identities.add(identity)
            hits.append(
                {
                    "identity": identity,
                    "scheme": scheme,
                    "title": str(record.get("title") or ""),
                    "matched_entity_id": entity_id,
                    "relevance": 1.0 if relevant else 0.0,
                }
            )
    new_identities = hit_identities - seen
    seen.update(hit_identities)
    store.record_harvest_run(direction_id, source, query, hits, round_no=round_no)
    return {
        "results": len(hits),
        "new_identities": len(new_identities),
        "imported": imported,
    }


# -- public entry points ----------------------------------------------------


def harvest_academic(
    store: PanoramaStore,
    direction_id: int,
    *,
    direction_slug: str = "automated-research",
    sources: Sequence[str] = ("managed",),
    queries: Sequence[str] | None = None,
    per_query_limit: int = 25,
    since: str | None = None,
    round_no: int = 1,
    fetcher: Fetcher | None = None,
    source_fetchers: dict[str, Fetcher] | None = None,
    triage_keywords: Sequence[str] | None = None,
    import_budget: int = 150,
) -> dict[str, Any]:
    """Run the multi-source academic harvest for one direction.

    For each source×query: fetch, normalize, triage by keyword, import
    triage-passing records as ``paper`` entities within ``import_budget``
    (new entities only), and log the run + hits for capture-recapture.
    A failing source/query is recorded in that source's ``errors`` list and
    never aborts the harvest.
    """
    if fetcher is None and source_fetchers is None:
        # Historical CLI source names cannot reopen direct upstream traffic.
        sources = ("managed",)
    query_list = list(
        queries if queries is not None else DEFAULT_QUERIES.get(direction_slug, [])
    )
    keywords = list(
        triage_keywords if triage_keywords is not None else DEFAULT_TRIAGE_KEYWORDS
    )
    # Explicit fetcher (tests) overrides everything and applies to all sources.
    # Otherwise pick a per-source fetcher (credentialed where available) and
    # fall back to the anonymous default.
    if fetcher is not None:
        resolved_fetchers: dict[str, Fetcher] = {}
        base_fetch = fetcher
    else:
        resolved_fetchers = (
            source_fetchers
            if source_fetchers is not None
            else default_source_fetchers()
        )
        base_fetch = default_fetcher
    known = _known_identities(store, direction_id)
    seen = set(store.capture_matrix(direction_id))
    budget = {"remaining": max(int(import_budget), 0), "exhausted": False}

    per_source: dict[str, dict[str, Any]] = {}
    totals = {"queries": 0, "results": 0, "new_identities": 0, "imported": 0}
    for source in sources:
        stats: dict[str, Any] = {
            "queries": 0,
            "results": 0,
            "new_identities": 0,
            "imported": 0,
            "errors": [],
        }
        per_source[source] = stats
        client = SOURCE_CLIENTS.get(source)
        if client is None:
            err = f"unknown source: {source}"
            stats["errors"].append({"query": None, "error": err})
            # Persist the miss so coverage can distinguish "failed" from "empty".
            store.record_harvest_run(
                direction_id,
                source,
                "",
                [],
                round_no=round_no,
                attrs={"status": "failed", "error": err},
            )
            continue
        source_fetch = resolved_fetchers.get(source, base_fetch)
        for query in query_list:
            try:
                extra = {"since": since} if since else {}
                records = client(query, per_query_limit, source_fetch, **extra)
            except SPCAcquisitionError:
                raise
            except Exception as exc:
                err = str(exc)
                stats["errors"].append({"query": query, "error": err})
                store.record_harvest_run(
                    direction_id,
                    source,
                    query,
                    [],
                    round_no=round_no,
                    attrs={"status": "failed", "error": err},
                )
                continue
            run = _ingest_query(
                store,
                direction_id,
                source,
                query,
                records,
                keywords=keywords,
                known=known,
                seen=seen,
                budget=budget,
                round_no=round_no,
            )
            stats["queries"] += 1
            for key in ("results", "new_identities", "imported"):
                stats[key] += run[key]
        for key in ("queries", "results", "new_identities", "imported"):
            totals[key] += stats[key]
    return {
        "direction_id": direction_id,
        "round_no": round_no,
        "sources": per_source,
        "totals": totals,
        "budget_exhausted": bool(budget["exhausted"]),
    }


def record_external_source(
    store: PanoramaStore,
    direction_id: int,
    source: str,
    records: Sequence[dict[str, Any]],
    *,
    triage_keywords: Sequence[str] | None = None,
    import_budget: int = 500,
    round_no: int = 1,
    query: str = "snapshot",
) -> dict[str, Any]:
    """Ingest an offline, already-normalized record list as one harvest run.

    Same triage/import/log path as :func:`harvest_academic`; used for bulk
    snapshots (e.g. the PwC archive subset) where records were produced
    elsewhere but must still enter the capture-recapture ledger.
    """
    keywords = list(
        triage_keywords if triage_keywords is not None else DEFAULT_TRIAGE_KEYWORDS
    )
    known = _known_identities(store, direction_id)
    seen = set(store.capture_matrix(direction_id))
    budget = {"remaining": max(int(import_budget), 0), "exhausted": False}
    run = _ingest_query(
        store,
        direction_id,
        source,
        query,
        records,
        keywords=keywords,
        known=known,
        seen=seen,
        budget=budget,
        round_no=round_no,
    )
    return {
        "direction_id": direction_id,
        "source": source,
        "query": query,
        "round_no": round_no,
        **run,
        "budget_exhausted": bool(budget["exhausted"]),
    }
