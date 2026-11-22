"""Citation verifier — 4-layer cascade verification of bibliographic references.

Checks citations against: CrossRef → DataCite → OpenAlex → Semantic Scholar.
Uses Jaccard title similarity for matching:
  - >= 0.80 → verified
  - >= 0.50 → partial_match
  - <  0.50 → hallucinated (if all sources fail)

Integrates with circuit breaker for resilience and search cache (TTL=365d)
for efficiency.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any

logger = logging.getLogger(__name__)

# Jaccard similarity thresholds
VERIFIED_THRESHOLD = 0.80
PARTIAL_THRESHOLD = 0.50


@dataclass
class CitationInput:
    """A citation to verify."""

    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""


@dataclass
class CitationResult:
    """Result of verifying a single citation."""

    title: str
    status: str = "not_found"  # verified | partial_match | not_found | hallucinated
    confidence: float = 0.0
    matched_title: str = ""
    matched_doi: str = ""
    source: str = ""  # which API confirmed it
    upstream_sources: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)


def _tokenize(text: str) -> set[str]:
    """Tokenize a title for Jaccard similarity."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = set(text.split())
    # Remove common stop words
    stop_words = {
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "for",
        "and",
        "to",
        "with",
        "is",
        "by",
        "at",
        "from",
    }
    return tokens - stop_words


def jaccard_similarity(title_a: str, title_b: str) -> float:
    """Compute Jaccard similarity between two titles."""
    tokens_a = _tokenize(title_a)
    tokens_b = _tokenize(title_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _classify_match(similarity: float) -> str:
    """Classify a match based on Jaccard similarity."""
    if similarity >= VERIFIED_THRESHOLD:
        return "verified"
    if similarity >= PARTIAL_THRESHOLD:
        return "partial_match"
    return "not_found"


def _normalize_doi(value: str) -> str:
    """Normalize DOI URLs for case-insensitive comparison."""
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip().lower())
    return re.sub(r"^doi:\s*", "", normalized)


def _normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _surname(value: str) -> str:
    return _normalize_text(value.split(",", 1)[0]).split(" ")[-1] if value else ""


def _crossref_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """Map a Crossref work into the fields used by the additive audit."""
    date = next(
        (
            item.get(key)
            for key in ("published-print", "published-online", "published", "issued")
            if item.get(key)
        ),
        {},
    )
    parts = date.get("date-parts", [[]]) if isinstance(date, dict) else [[]]
    year = parts[0][0] if parts and parts[0] else None
    return {
        "title": " ".join(item.get("title", [])),
        "authors": [
            author.get("name")
            or " ".join(
                filter(None, (author.get("given", ""), author.get("family", "")))
            )
            for author in item.get("author", [])
            if isinstance(author, dict)
        ],
        "year": year,
        "venue": " ".join(item.get("container-title", [])),
        "doi": item.get("DOI", ""),
    }


def _openalex_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """Map an OpenAlex work into the fields used by the additive audit."""
    primary_location = item.get("primary_location") or {}
    authorships = item.get("authorships") or []
    if not isinstance(primary_location, dict) or not isinstance(authorships, list):
        raise ValueError("malformed OpenAlex audit response")
    source = primary_location.get("source") or {}
    if not isinstance(source, dict):
        raise ValueError("malformed OpenAlex audit response")
    return {
        "title": item.get("title", ""),
        "authors": [
            (authorship.get("author") or {}).get("display_name", "")
            for authorship in authorships
            if isinstance(authorship, dict)
        ],
        "year": item.get("publication_year"),
        "venue": source.get("display_name", ""),
        "doi": item.get("doi", ""),
    }


def _select_audit_item(
    items: list[dict[str, Any]],
    citation: CitationInput,
    metadata_fn: Any,
    matched_title: str = "",
) -> dict[str, Any] | None:
    if citation.doi:
        return metadata_fn(items[0]) if items else None

    best_item: dict[str, Any] | None = None
    best_similarity = 0.0
    for item in items[:3]:
        metadata = metadata_fn(item)
        if matched_title and metadata["title"] == matched_title:
            return (
                metadata
                if jaccard_similarity(citation.title, metadata["title"])
                >= VERIFIED_THRESHOLD
                else None
            )
        similarity = jaccard_similarity(citation.title, metadata["title"])
        if similarity > best_similarity:
            best_item = metadata
            best_similarity = similarity
    return (
        None
        if matched_title
        else best_item
        if best_similarity >= VERIFIED_THRESHOLD
        else None
    )


def _audit_crossref(
    citation: CitationInput, http_fn: Any = None, matched_title: str = ""
) -> dict[str, Any] | None:
    query = _normalize_doi(citation.doi) if citation.doi else citation.title
    try:
        if http_fn is None:
            import json
            import urllib.parse
            import urllib.request

            if citation.doi:
                url = f"https://api.crossref.org/works/{urllib.parse.quote(query, safe='')}"
            else:
                encoded = urllib.parse.quote(query)
                url = f"https://api.crossref.org/works?query.bibliographic={encoded}&rows=3"
            req = urllib.request.Request(
                url, headers={"User-Agent": "ResearchHarness/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        else:
            data = http_fn("crossref", query)

        if not isinstance(data, dict) or not isinstance(data.get("message", {}), dict):
            raise ValueError("malformed Crossref audit response")
        message = data.get("message", {})
        items = (
            [message]
            if citation.doi and message.get("title")
            else message.get("items", [])
        )
        return _select_audit_item(
            items, citation, _crossref_metadata, matched_title=matched_title
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning(
            "CrossRef audit payload failed for '%s': %s", citation.title[:50], exc
        )
        return None
    except Exception as exc:
        logger.debug(
            "CrossRef audit unavailable for '%s': %s", citation.title[:50], exc
        )
        return None


def _audit_openalex(
    citation: CitationInput, http_fn: Any = None, matched_title: str = ""
) -> dict[str, Any] | None:
    query = _normalize_doi(citation.doi) if citation.doi else citation.title
    try:
        if http_fn is None:
            import json
            import urllib.parse
            import urllib.request

            if citation.doi:
                url = f"https://api.openalex.org/works/doi:{urllib.parse.quote(query)}"
            else:
                encoded = urllib.parse.quote(query)
                url = f"https://api.openalex.org/works?filter=title.search:{encoded}&per_page=3"
            req = urllib.request.Request(
                url, headers={"User-Agent": "ResearchHarness/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        else:
            data = http_fn("openalex", query)

        if not isinstance(data, dict):
            raise ValueError("malformed OpenAlex audit response")
        if citation.doi:
            items = [data] if data.get("title") else []
        else:
            items = data.get("results", [])
            if not isinstance(items, list):
                raise ValueError("malformed OpenAlex audit response")
        return _select_audit_item(
            items, citation, _openalex_metadata, matched_title=matched_title
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning(
            "OpenAlex audit payload failed for '%s': %s", citation.title[:50], exc
        )
        return None
    except Exception as exc:
        logger.debug(
            "OpenAlex audit unavailable for '%s': %s", citation.title[:50], exc
        )
        return None


def _metadata_conflicts(
    citation: CitationInput, source: str, metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []

    def add(field: str, declared_value: Any, upstream_value: Any) -> None:
        conflicts.append(
            {
                "source": source,
                "field": field,
                "declared_value": declared_value,
                "upstream_value": upstream_value,
            }
        )

    if (
        citation.title
        and metadata["title"]
        and jaccard_similarity(citation.title, metadata["title"]) < VERIFIED_THRESHOLD
    ):
        add("title", citation.title, metadata["title"])
    if citation.authors and metadata["authors"]:
        declared = {_surname(author) for author in citation.authors} - {""}
        upstream = {_surname(author) for author in metadata["authors"]} - {""}
        if declared and upstream and not declared.issubset(upstream):
            add("authors", citation.authors, metadata["authors"])
    if citation.year is not None and metadata["year"] is not None:
        try:
            if abs(int(citation.year) - int(metadata["year"])) > 1:
                add("year", citation.year, metadata["year"])
        except (TypeError, ValueError):
            pass
    if (
        citation.venue
        and metadata["venue"]
        and _normalize_text(citation.venue) != _normalize_text(metadata["venue"])
    ):
        add("venue", citation.venue, metadata["venue"])
    if (
        citation.doi
        and metadata["doi"]
        and _normalize_doi(citation.doi) != _normalize_doi(metadata["doi"])
    ):
        add("doi", citation.doi, metadata["doi"])
    return conflicts


def _audit_upstream_metadata(
    citation: CitationInput,
    http_fn: Any = None,
    result: CitationResult | None = None,
    breaker_fn: Any = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    sources: list[str] = []
    conflicts: list[dict[str, Any]] = []
    for source, audit_fn in (
        ("crossref", _audit_crossref),
        ("openalex", _audit_openalex),
    ):
        matched_title = (
            result.matched_title
            if result is not None and result.source == source
            else ""
        )
        try:
            metadata = (
                breaker_fn(source, audit_fn, citation, http_fn, matched_title)
                if breaker_fn is not None
                else audit_fn(citation, http_fn, matched_title)
            )
        except Exception:
            metadata = None
        if metadata is not None:
            sources.append(source)
            conflicts.extend(_metadata_conflicts(citation, source, metadata))
    return sources, conflicts


def _with_upstream_audit(
    result: CitationResult,
    citation: CitationInput,
    http_fn: Any,
    breaker_fn: Any = None,
) -> CitationResult:
    sources, conflicts = _audit_upstream_metadata(citation, http_fn, result, breaker_fn)
    return replace(result, upstream_sources=sources, conflicts=conflicts)


def _fetch_title_payload(source: str, title: str) -> dict[str, Any]:
    """Fetch a title response shared by verification and metadata audit."""
    import json
    import urllib.parse
    import urllib.request

    encoded = urllib.parse.quote(title)
    if source == "crossref":
        url = f"https://api.crossref.org/works?query.bibliographic={encoded}&rows=3"
    elif source == "openalex":
        url = f"https://api.openalex.org/works?filter=title.search:{encoded}&per_page=3"
    else:
        raise ValueError(f"unsupported audit source: {source}")
    req = urllib.request.Request(url, headers={"User-Agent": "ResearchHarness/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _cached_audit_http(http_fn: Any = None) -> Any:
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    errors: dict[tuple[str, str], Exception] = {}

    def fetch(source: str, query: str) -> dict[str, Any]:
        key = (source, query)
        if key in errors:
            raise errors[key]
        if key not in cache:
            try:
                cache[key] = (
                    http_fn(source, query)
                    if http_fn is not None
                    else _fetch_title_payload(source, query)
                )
            except Exception as exc:
                errors[key] = exc
                raise
        return cache[key]

    return fetch


def _check_crossref(title: str, http_fn: Any = None) -> CitationResult | None:
    """Check a citation against CrossRef API."""
    try:
        if http_fn is None:
            import urllib.request
            import json

            encoded = urllib.parse.quote(title)
            url = f"https://api.crossref.org/works?query.bibliographic={encoded}&rows=3"
            req = urllib.request.Request(
                url, headers={"User-Agent": "ResearchHarness/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        else:
            data = http_fn("crossref", title)

        items = data.get("message", {}).get("items", [])
        for item in items[:3]:
            candidate_title = " ".join(item.get("title", []))
            if not candidate_title:
                continue
            sim = jaccard_similarity(title, candidate_title)
            status = _classify_match(sim)
            if status != "not_found":
                return CitationResult(
                    title=title,
                    status=status,
                    confidence=sim,
                    matched_title=candidate_title,
                    matched_doi=item.get("DOI", ""),
                    source="crossref",
                )
    except Exception as exc:
        logger.debug("CrossRef check failed for '%s': %s", title[:50], exc)
    return None


def _check_openalex(title: str, http_fn: Any = None) -> CitationResult | None:
    """Check a citation against OpenAlex API."""
    try:
        if http_fn is None:
            import urllib.request
            import json

            encoded = urllib.parse.quote(title)
            url = f"https://api.openalex.org/works?filter=title.search:{encoded}&per_page=3"
            req = urllib.request.Request(
                url, headers={"User-Agent": "ResearchHarness/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        else:
            data = http_fn("openalex", title)

        results = data.get("results", [])
        for item in results[:3]:
            candidate_title = item.get("title", "")
            if not candidate_title:
                continue
            sim = jaccard_similarity(title, candidate_title)
            status = _classify_match(sim)
            if status != "not_found":
                return CitationResult(
                    title=title,
                    status=status,
                    confidence=sim,
                    matched_title=candidate_title,
                    matched_doi=item.get("doi", "").replace("https://doi.org/", ""),
                    source="openalex",
                )
    except Exception as exc:
        logger.debug("OpenAlex check failed for '%s': %s", title[:50], exc)
    return None


def _check_semantic_scholar(title: str, http_fn: Any = None) -> CitationResult | None:
    """Check a citation against Semantic Scholar API."""
    try:
        if http_fn is None:
            import urllib.request
            import json

            encoded = urllib.parse.quote(title)
            url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={encoded}&limit=3&fields=title,externalIds"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        else:
            data = http_fn("semantic_scholar", title)

        papers = data.get("data", [])
        for paper in papers[:3]:
            candidate_title = paper.get("title", "")
            if not candidate_title:
                continue
            sim = jaccard_similarity(title, candidate_title)
            status = _classify_match(sim)
            if status != "not_found":
                ext_ids = paper.get("externalIds", {}) or {}
                return CitationResult(
                    title=title,
                    status=status,
                    confidence=sim,
                    matched_title=candidate_title,
                    matched_doi=ext_ids.get("DOI", ""),
                    source="semantic_scholar",
                )
    except Exception as exc:
        logger.debug("S2 check failed for '%s': %s", title[:50], exc)
    return None


def _check_datacite(title: str, http_fn: Any = None) -> CitationResult | None:
    """Check a citation against DataCite API."""
    try:
        if http_fn is None:
            import urllib.request
            import json

            encoded = urllib.parse.quote(title)
            url = f"https://api.datacite.org/dois?query={encoded}&page[size]=3"
            req = urllib.request.Request(
                url, headers={"User-Agent": "ResearchHarness/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        else:
            data = http_fn("datacite", title)

        items = data.get("data", [])
        for item in items[:3]:
            attrs = item.get("attributes", {})
            candidate_title = (
                " ".join(attrs.get("titles", [{}])[0].get("title", "").split())
                if attrs.get("titles")
                else ""
            )
            if not candidate_title:
                continue
            sim = jaccard_similarity(title, candidate_title)
            status = _classify_match(sim)
            if status != "not_found":
                return CitationResult(
                    title=title,
                    status=status,
                    confidence=sim,
                    matched_title=candidate_title,
                    matched_doi=attrs.get("doi", ""),
                    source="datacite",
                )
    except Exception as exc:
        logger.debug("DataCite check failed for '%s': %s", title[:50], exc)
    return None


# Cascade order: CrossRef (best coverage) → DataCite → OpenAlex → S2
_CASCADE = [
    ("crossref", _check_crossref),
    ("datacite", _check_datacite),
    ("openalex", _check_openalex),
    ("semantic_scholar", _check_semantic_scholar),
]


def verify_citation(
    citation: CitationInput,
    http_fn: Any = None,
    breaker_fn: Any = None,
) -> CitationResult:
    """Verify identity and metadata through managed scholarly acquisition."""
    from research_harness.paper_source_clients import build_provider_suite
    from research_harness.paper_sources import SearchAggregator, SearchQuery

    if http_fn is not None:
        return _verify_injected_citation(
            citation, http_fn=http_fn, breaker_fn=breaker_fn
        )
    records = (
        SearchAggregator(build_provider_suite())
        .search(
            SearchQuery(query=citation.doi or citation.title, limit=5),
            output_limit=5,
        )
        .results
    )
    best = CitationResult(title=citation.title)
    for record in records:
        score = jaccard_similarity(citation.title, record.title)
        if citation.doi and _normalize_doi(record.doi) != _normalize_doi(citation.doi):
            continue
        if score <= best.confidence:
            continue
        metadata = {
            "title": record.title,
            "authors": record.authors,
            "year": record.year,
            "venue": record.venue,
            "doi": record.doi,
        }
        conflicts = _metadata_conflicts(citation, record.provider, metadata)
        best = CitationResult(
            title=citation.title,
            status="partial_match" if conflicts else _classify_match(score),
            confidence=score,
            matched_title=record.title,
            matched_doi=record.doi,
            source=record.provider,
            upstream_sources=[record.provider],
            conflicts=conflicts,
        )
    # An unavailable source or absent hit is not proof that a citation was invented.
    return best


def _verify_injected_citation(
    citation: CitationInput,
    http_fn: Any = None,
    breaker_fn: Any = None,
) -> CitationResult:
    """Verify a single citation through the 4-layer cascade.

    Args:
        citation: The citation to verify.
        http_fn: Optional mock HTTP function for testing.
        breaker_fn: Optional circuit breaker wrapper.

    Returns:
        CitationResult with status and matched metadata.
    """
    # If DOI is provided, it's likely real — skip cascade
    if citation.doi:
        return _with_upstream_audit(
            CitationResult(
                title=citation.title,
                status="verified",
                confidence=1.0,
                matched_doi=citation.doi,
                source="doi_provided",
            ),
            citation,
            http_fn,
            breaker_fn,
        )

    best_result: CitationResult | None = None
    audit_http = _cached_audit_http(http_fn)

    for source_name, check_fn in _CASCADE:
        provider_http = (
            audit_http if source_name in {"crossref", "openalex"} else http_fn
        )
        try:
            if breaker_fn is not None:
                result = breaker_fn(
                    source_name, check_fn, citation.title, provider_http
                )
            else:
                result = check_fn(citation.title, provider_http)
        except Exception:
            continue

        if result is None:
            continue

        if result.status == "verified":
            return _with_upstream_audit(result, citation, audit_http, breaker_fn)

        # Keep the best partial match
        if best_result is None or result.confidence > best_result.confidence:
            best_result = result

    # If we got a partial match, return it
    if best_result is not None:
        return _with_upstream_audit(best_result, citation, audit_http, breaker_fn)

    # All sources failed → hallucinated
    return _with_upstream_audit(
        CitationResult(
            title=citation.title,
            status="hallucinated",
            confidence=0.0,
        ),
        citation,
        audit_http,
        breaker_fn,
    )


def verify_citations(
    citations: list[CitationInput],
    http_fn: Any = None,
    breaker_fn: Any = None,
) -> list[CitationResult]:
    """Verify a batch of citations."""
    return [
        verify_citation(c, http_fn=http_fn, breaker_fn=breaker_fn) for c in citations
    ]
