from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal


BM25ScoringMode = Literal["term_frequency", "bm25"]

DEFAULT_BM25_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "are",
        "for",
        "in",
        "is",
        "of",
        "on",
        "or",
        "papers",
        "research",
        "the",
        "there",
        "to",
        "using",
        "with",
    }
)


@dataclass(frozen=True)
class BM25Document:
    """Minimal document shape for reusable lexical retrieval."""

    doc_id: str
    text: str


@dataclass(frozen=True)
class BM25SearchResult:
    """Ranked lexical retrieval result."""

    doc_id: str
    score: float


@dataclass(frozen=True)
class BM25Index:
    """In-memory lexical retrieval index with term-frequency and BM25 scoring."""

    postings: dict[str, dict[str, int]]
    doc_lengths: dict[str, int]
    doc_count: int
    avg_doc_length: float
    k1: float = 1.2
    b: float = 0.75

    @classmethod
    def from_documents(
        cls,
        documents: Iterable[BM25Document],
        *,
        stopwords: frozenset[str] = DEFAULT_BM25_STOPWORDS,
    ) -> "BM25Index":
        postings: dict[str, dict[str, int]] = {}
        doc_lengths: dict[str, int] = {}
        for document in documents:
            doc_id = document.doc_id.strip()
            if not doc_id:
                continue
            terms = tokenize_text(document.text, stopwords=stopwords)
            doc_lengths[doc_id] = len(terms)
            for term in terms:
                term_postings = postings.setdefault(term, {})
                term_postings[doc_id] = term_postings.get(doc_id, 0) + 1

        avg_doc_length = (
            sum(doc_lengths.values()) / len(doc_lengths) if doc_lengths else 1.0
        )
        return cls(
            postings=postings,
            doc_lengths=doc_lengths,
            doc_count=len(doc_lengths),
            avg_doc_length=avg_doc_length or 1.0,
        )

    def search(
        self,
        query: str,
        *,
        k: int = 20,
        scoring: BM25ScoringMode = "bm25",
        stopwords: frozenset[str] = DEFAULT_BM25_STOPWORDS,
    ) -> tuple[BM25SearchResult, ...]:
        scores: dict[str, float] = {}
        for term in dict.fromkeys(tokenize_text(query, stopwords=stopwords)):
            for doc_id, term_frequency in self.postings.get(term, {}).items():
                if scoring == "bm25":
                    score = self._bm25(term, doc_id, term_frequency)
                elif scoring == "term_frequency":
                    score = float(term_frequency)
                else:
                    raise ValueError(f"unsupported BM25 scoring mode: {scoring}")
                scores[doc_id] = scores.get(doc_id, 0.0) + score

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return tuple(
            BM25SearchResult(doc_id=doc_id, score=score) for doc_id, score in ranked[:k]
        )

    def _bm25(self, term: str, doc_id: str, term_frequency: int) -> float:
        document_frequency = len(self.postings.get(term, {}))
        if document_frequency <= 0:
            return 0.0
        idf = math.log(
            1 + (self.doc_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        doc_length = self.doc_lengths.get(doc_id, 0)
        denominator = term_frequency + self.k1 * (
            1 - self.b + self.b * (doc_length / self.avg_doc_length)
        )
        if denominator <= 0:
            return 0.0
        return idf * ((term_frequency * (self.k1 + 1)) / denominator)


def tokenize_text(
    text: str,
    *,
    stopwords: frozenset[str] = DEFAULT_BM25_STOPWORDS,
) -> tuple[str, ...]:
    """Tokenize text for RH lexical retrieval baselines."""

    return tuple(
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.lower())
        if token not in stopwords
    )
