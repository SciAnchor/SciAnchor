"""Private dependency-free search over in-memory Research Wiki pages."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .research_wiki import ResearchWikiExport, ResearchWikiPage
from .research_wiki_insights import ResearchWikiEvidenceAnchor


_TERM_RE = re.compile(r"[a-z0-9]+")
_PAGE_TYPE_BOOSTS = {
    "finding": 14.0,
    "methodology": 8.0,
    "source_section": 6.0,
    "source": 3.0,
    "thesis": 2.0,
    "concept": 0.0,
}
_STALE_OR_DEGRADED_STATUSES = {"stale", "degraded", "needs_attention"}


@dataclass(frozen=True)
class ResearchWikiSearchHit:
    page_path: str
    title: str
    page_type: str
    score: float
    matched_terms: tuple[str, ...]
    evidence: tuple[ResearchWikiEvidenceAnchor, ...]


@dataclass(frozen=True)
class ResearchWikiSearchResult:
    topic_id: int
    query: str
    terms: tuple[str, ...]
    hits: tuple[ResearchWikiSearchHit, ...]

    @property
    def term_count(self) -> int:
        return len(self.terms)


def search_research_wiki_pages(
    export: ResearchWikiExport,
    query: str,
    *,
    max_results: int = 10,
) -> ResearchWikiSearchResult:
    """Return ranked keyword hits over in-memory Research Wiki pages."""

    terms = _query_terms(query)
    if not terms or max_results <= 0:
        return ResearchWikiSearchResult(
            topic_id=export.topic_id,
            query=query,
            terms=terms,
            hits=(),
        )

    query_phrase = _search_text(query)
    hits = [
        hit
        for page in export.pages
        if (hit := _page_hit(page, terms, query_phrase=query_phrase)) is not None
    ]
    ranked = sorted(
        hits,
        key=lambda hit: (
            -hit.score,
            -len(hit.matched_terms),
            hit.page_path,
        ),
    )
    return ResearchWikiSearchResult(
        topic_id=export.topic_id,
        query=query,
        terms=terms,
        hits=tuple(ranked[: int(max_results)]),
    )


def _page_hit(
    page: ResearchWikiPage,
    terms: tuple[str, ...],
    *,
    query_phrase: str,
) -> ResearchWikiSearchHit | None:
    title_text = _search_text(page.title)
    path_text = _search_text(page.relative_path)
    body_text = _search_text(page.body)
    source_text = _search_text(
        " ".join(
            str(source.get("evidence_snippet") or "")
            for source in _source_dicts(page.frontmatter.get("sources"))
        )
    )
    evidence = _page_evidence(page)

    matched_terms: list[str] = []
    score = 0.0
    for term in terms:
        title_hits = _term_hits(title_text, term)
        path_hits = _term_hits(path_text, term)
        body_hits = min(_term_hits(body_text, term), 6)
        source_hits = _term_hits(source_text, term)
        total_hits = title_hits + path_hits + body_hits + source_hits
        if total_hits == 0:
            continue
        matched_terms.append(term)
        score += (
            title_hits * 8.0 + source_hits * 3.0 + body_hits * 2.0 + path_hits * 1.0
        )

    if not matched_terms:
        return None
    score += _title_match_boost(title_text, terms, query_phrase)
    score += _page_type_boost(page.page_type)
    score += _exact_phrase_boost(
        query_phrase=query_phrase,
        title_text=title_text,
        body_text=body_text,
        source_text=source_text,
        path_text=path_text,
    )
    score += _evidence_boost(evidence, query_phrase=query_phrase)
    score += _source_diversity_boost(evidence)
    score -= _stale_or_degraded_penalty(page)
    return ResearchWikiSearchHit(
        page_path=page.relative_path,
        title=page.title,
        page_type=page.page_type,
        score=round(score, 3),
        matched_terms=tuple(matched_terms),
        evidence=evidence,
    )


def _title_match_boost(
    title_text: str,
    terms: tuple[str, ...],
    query_phrase: str,
) -> float:
    title_terms = set(title_text.split())
    score = 0.0
    if terms and all(term in title_terms for term in terms):
        score += 12.0
    if query_phrase and _contains_phrase(title_text, query_phrase):
        score += 18.0
    return score


def _page_type_boost(page_type: str) -> float:
    return _PAGE_TYPE_BOOSTS.get(page_type, 1.0)


def _exact_phrase_boost(
    *,
    query_phrase: str,
    title_text: str,
    body_text: str,
    source_text: str,
    path_text: str,
) -> float:
    if not query_phrase:
        return 0.0
    score = 0.0
    if _contains_phrase(title_text, query_phrase):
        score += 20.0
    if _contains_phrase(source_text, query_phrase):
        score += 16.0
    if _contains_phrase(body_text, query_phrase):
        score += 10.0
    if _contains_phrase(path_text, query_phrase):
        score += 4.0
    return score


def _evidence_boost(
    evidence: tuple[ResearchWikiEvidenceAnchor, ...],
    *,
    query_phrase: str,
) -> float:
    score = min(len(evidence), 4) * 4.0
    if query_phrase:
        score += sum(
            6.0
            for anchor in evidence[:4]
            if _contains_phrase(_search_text(anchor.evidence_snippet), query_phrase)
        )
    return score


def _source_diversity_boost(evidence: tuple[ResearchWikiEvidenceAnchor, ...]) -> float:
    source_types = {anchor.source_type for anchor in evidence if anchor.source_type}
    source_ids = {anchor.source_id for anchor in evidence if anchor.source_id}
    paper_ids = {anchor.paper_id for anchor in evidence if anchor.paper_id is not None}
    return (
        min(len(source_types), 3) * 2.0
        + min(len(source_ids), 4)
        + min(len(paper_ids), 4)
    )


def _stale_or_degraded_penalty(page: ResearchWikiPage) -> float:
    metadata = page.frontmatter
    status = str(
        metadata.get("status") or metadata.get("readiness_status") or ""
    ).lower()
    if (
        status in _STALE_OR_DEGRADED_STATUSES
        or bool(metadata.get("stale"))
        or bool(metadata.get("degraded"))
    ):
        return 70.0
    return 0.0


def _page_evidence(page: ResearchWikiPage) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    anchors: list[ResearchWikiEvidenceAnchor] = []
    for source in _source_dicts(page.frontmatter.get("sources")):
        source_type = str(source.get("source_type") or "")
        source_id = str(source.get("source_id") or "")
        source_hash = str(source.get("source_hash") or "")
        evidence_snippet = str(source.get("evidence_snippet") or "")
        if not source_type or not source_id or not source_hash or not evidence_snippet:
            continue
        paper_id = source.get("paper_id")
        anchors.append(
            ResearchWikiEvidenceAnchor(
                page_path=page.relative_path,
                paper_id=int(paper_id) if isinstance(paper_id, int) else None,
                source_type=source_type,
                source_id=source_id,
                source_hash=source_hash,
                section_anchor=str(source.get("section_anchor") or ""),
                evidence_snippet=evidence_snippet,
            )
        )
    return tuple(
        sorted(
            anchors,
            key=lambda anchor: (
                anchor.source_type,
                anchor.source_id,
                anchor.source_hash,
                anchor.section_anchor,
                anchor.evidence_snippet,
            ),
        )
    )


def _source_dicts(raw_sources: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_sources, list):
        return []
    return [source for source in raw_sources if isinstance(source, dict)]


def _query_terms(query: str) -> tuple[str, ...]:
    terms = _TERM_RE.findall(query.lower())
    return tuple(dict.fromkeys(terms))


def _search_text(value: Any) -> str:
    return " ".join(_TERM_RE.findall(str(value or "").lower()))


def _term_hits(text: str, term: str) -> int:
    return sum(1 for token in text.split() if token == term)


def _contains_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    return f" {phrase} " in f" {text} "
