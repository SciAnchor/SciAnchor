"""选题检索与引文拓扑。只返回候选事实，不写入种子包。"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from paperfetch.core.metadata_signals import venue_metadata
from paperfetch.core.models import PaperRecord
from paperfetch.sources.openalex import OpenAlexSource
from paperfetch.sources.pubmed import PubMedSource
from paperfetch.sources.semantic_scholar import SemanticScholarSource
from paperfetch.utils.cleaner import MetadataCleanPipeline
from paperfetch.utils.client import create_metadata_client
from paperfetch.utils.normalizer import (
    normalize_arxiv_id,
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
)


@dataclass(frozen=True)
class SearchCandidate:
    title: str
    doi: str | None
    pubmed_id: str | None
    pmc_id: str | None
    arxiv_id: str | None
    year: int | None
    venue: str | None
    publisher: str | None
    citation_count: int | None
    sources: tuple[str, ...]
    ccf_rank: str | None
    cas_zone: int | None
    paper_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "title": self.title,
            "doi": self.doi,
            "pubmed_id": self.pubmed_id,
            "pmc_id": self.pmc_id,
            "arxiv_id": self.arxiv_id,
            "year": self.year,
            "venue": self.venue,
            "publisher": self.publisher,
            "citation_count": self.citation_count,
            "sources": list(self.sources),
            "ccf_rank": self.ccf_rank,
            "cas_zone": self.cas_zone,
            "paper_id": self.paper_id,
        }
        return {
            key: value for key, value in payload.items() if value not in (None, [], ())
        }


@dataclass(frozen=True)
class SearchPage:
    candidates: list[SearchCandidate]
    source_errors: dict[str, str]


def _clean_paper(paper: PaperRecord) -> PaperRecord:
    paper.doi = normalize_doi(paper.doi)
    paper.arxiv_id = normalize_arxiv_id(paper.arxiv_id)
    paper.pubmed_id = normalize_pmid(paper.pubmed_id)
    paper.pmc_id = normalize_pmcid(paper.pmc_id)
    paper.title = MetadataCleanPipeline.clean(paper.title) or paper.title
    paper.abstract = MetadataCleanPipeline.clean(paper.abstract)
    return paper


def _candidate_key(paper: PaperRecord) -> str:
    if paper.doi:
        return f"doi:{paper.doi.lower()}"
    if paper.arxiv_id:
        return f"arxiv:{paper.arxiv_id.lower()}"
    if paper.pubmed_id:
        return f"pmid:{paper.pubmed_id}"
    if paper.pmc_id:
        return f"pmcid:{paper.pmc_id}"
    title = (paper.title or "").strip().lower()
    return f"title:{title}:{paper.year or ''}"


def _to_candidate(paper: PaperRecord, sources: list[str]) -> SearchCandidate:
    signals = venue_metadata(paper)
    cas_zone = signals.get("cas_zone")
    return SearchCandidate(
        title=paper.title,
        doi=paper.doi,
        pubmed_id=paper.pubmed_id,
        pmc_id=paper.pmc_id,
        arxiv_id=paper.arxiv_id,
        year=paper.year,
        venue=paper.venue or paper.journal,
        publisher=paper.publisher,
        citation_count=paper.citation_count,
        sources=tuple(sorted(set(sources))),
        ccf_rank=signals.get("ccf_rank"),
        cas_zone=int(cas_zone) if cas_zone is not None else None,
        paper_id=paper.paper_id,
    )


def _passes_filters(
    candidate: SearchCandidate,
    *,
    min_year: int | None,
    ccf_ranks: list[str] | None,
    cas_zones: list[int] | None,
    min_citations: int,
) -> bool:
    if min_year is not None and (candidate.year is None or candidate.year < min_year):
        return False
    if min_citations and (candidate.citation_count or 0) < min_citations:
        return False
    if ccf_ranks and (candidate.ccf_rank or "").upper() not in {
        rank.upper() for rank in ccf_ranks
    }:
        return False
    if cas_zones and candidate.cas_zone not in cas_zones:
        return False
    return True


def _source_deadline_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("SPC_SEARCH_SOURCE_DEADLINE_SECONDS", "60")))
    except ValueError:
        return 60.0


async def _collect_source_hits(source, *, query: str, limit: int, min_year: int | None):
    # A rate-limited source waits out its cooldown without bound; the deadline keeps one
    # such source from holding the whole search, and the hits it already yielded stand.
    papers: list[PaperRecord] = []
    deadline = _source_deadline_seconds()
    try:
        async with asyncio.timeout(deadline):
            async for paper in source.search(
                query=query, limit=limit, year_from=min_year
            ):
                papers.append(_clean_paper(paper))
    except TimeoutError:
        return (
            source.source_name,
            papers,
            f"TimeoutError: no answer within {deadline:g}s",
        )
    except Exception as exc:
        return source.source_name, papers, _redact(f"{type(exc).__name__}: {exc}")
    return source.source_name, papers, None


def _redact(message: str) -> str:
    """HTTP errors quote the request URL, which carries the provider key as a query parameter."""
    return re.sub(
        r"(api_key|apikey|key)=[^&\s']+", r"\1=<redacted>", message, flags=re.IGNORECASE
    )


class PaperSearchEngine:
    """多源并发选题检索。"""

    async def search(
        self,
        *,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        ccf_ranks: list[str] | None = None,
        cas_zones: list[int] | None = None,
        min_citations: int = 0,
    ) -> SearchPage:
        client = create_metadata_client()
        semaphore = asyncio.Semaphore(5)
        sources = [
            OpenAlexSource(client, semaphore),
            SemanticScholarSource(client, semaphore),
            PubMedSource(client, semaphore),
        ]
        fetch_limit = max(limit * 3, limit)
        try:
            collected = await asyncio.gather(
                *(
                    _collect_source_hits(
                        source,
                        query=query,
                        limit=fetch_limit,
                        min_year=min_year,
                    )
                    for source in sources
                )
            )
        finally:
            await client.aclose()

        merged: dict[str, tuple[PaperRecord, list[str]]] = {}
        source_errors: dict[str, str] = {}
        for source_name, papers, error in collected:
            if error:
                source_errors[source_name] = error
            for paper in papers:
                key = _candidate_key(paper)
                existing = merged.get(key)
                if existing is None:
                    merged[key] = (paper, [source_name])
                elif source_name not in existing[1]:
                    existing[1].append(source_name)

        candidates = [
            _to_candidate(paper, source_names)
            for paper, source_names in merged.values()
        ]
        filtered = [
            candidate
            for candidate in candidates
            if _passes_filters(
                candidate,
                min_year=min_year,
                ccf_ranks=ccf_ranks,
                cas_zones=cas_zones,
                min_citations=min_citations,
            )
        ]
        filtered.sort(
            key=lambda item: (item.citation_count or 0, item.year or 0), reverse=True
        )
        return SearchPage(candidates=filtered[:limit], source_errors=source_errors)


class PaperGraphEngine:
    """从一篇 DOI 展开参考文献、施引或相似候选。"""

    async def explore(
        self,
        *,
        doi: str,
        direction: Literal["references", "citations", "similar"],
        limit: int = 15,
        min_year: int | None = None,
    ) -> SearchPage:
        client = create_metadata_client()
        semaphore = asyncio.Semaphore(1)
        sources = [
            OpenAlexSource(client, semaphore),
            SemanticScholarSource(client, semaphore),
        ]
        related: list[tuple[PaperRecord, str]] = []
        source_errors: dict[str, str] = {}
        seed_title: str | None = None
        try:
            for source in sources:
                try:
                    seed = await asyncio.wait_for(
                        source.lookup(doi, "doi"), _source_deadline_seconds()
                    )
                except Exception as exc:
                    source_errors[source.source_name] = _redact(
                        f"{type(exc).__name__}: {exc}"
                    )
                    continue
                if seed is None:
                    continue
                seed = _clean_paper(seed)
                seed_title = seed.title or seed_title
                try:
                    if direction == "references":
                        rows = await asyncio.wait_for(
                            source.get_references(seed), _source_deadline_seconds()
                        )
                    elif direction == "citations":
                        rows = await asyncio.wait_for(
                            source.get_citations(seed), _source_deadline_seconds()
                        )
                    else:
                        rows = []
                except Exception as exc:
                    source_errors[source.source_name] = _redact(
                        f"{type(exc).__name__}: {exc}"
                    )
                    rows = []
                if rows:
                    related.extend(
                        (_clean_paper(row), source.source_name) for row in rows
                    )
                    break
            if direction == "similar" and seed_title:
                searcher = OpenAlexSource(client, semaphore)
                try:
                    async for paper in searcher.search(
                        query=seed_title, limit=limit + 5
                    ):
                        cleaned = _clean_paper(paper)
                        if (
                            cleaned.doi
                            and normalize_doi(doi)
                            and cleaned.doi == normalize_doi(doi)
                        ):
                            continue
                        related.append((cleaned, searcher.source_name))
                except Exception as exc:
                    source_errors[searcher.source_name] = _redact(
                        f"{type(exc).__name__}: {exc}"
                    )
        finally:
            await client.aclose()

        merged: dict[str, tuple[PaperRecord, list[str]]] = {}
        for paper, source_name in related:
            key = _candidate_key(paper)
            existing = merged.get(key)
            if existing is None:
                merged[key] = (paper, [source_name])
            elif source_name not in existing[1]:
                existing[1].append(source_name)

        candidates = [
            _to_candidate(paper, source_names)
            for paper, source_names in merged.values()
        ]
        if min_year is not None:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.year is None or candidate.year >= min_year
            ]
        return SearchPage(candidates=candidates[:limit], source_errors=source_errors)
