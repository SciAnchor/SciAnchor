"""Retrieve-then-rerank over an in-memory candidate set.

Two modes:
- small corpora (N <= ``embed_all_max``): embed every candidate so pure lexical
  gates cannot drop semantic near-misses (D4 failure mode);
- large corpora: lexical shortlist first, then embed the shortlist.

Accuracy is carried by the embedding score when the provider succeeds; lexical
is the fallback and a blend term. No ANN / GPU path here.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..storage.db import Database

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "why",
        "with",
        "will",
        "can",
        "could",
        "should",
        "would",
    }
)

# When the candidate set is this small, skip the lexical gate and embed all.
DEFAULT_EMBED_ALL_MAX = 64


@dataclass(frozen=True)
class RankedHit:
    doc_id: str
    text: str
    score: float
    lexical_score: float = 0.0
    embed_score: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


def tokenize(text: str) -> set[str]:
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text or "")
        if t.lower() not in _STOPWORDS and len(t) > 1
    }


def lexical_score(query_tokens: set[str], doc_text: str) -> float:
    doc_tokens = tokenize(doc_text)
    if not query_tokens or not doc_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / max(len(query_tokens), 1)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def retrieve_then_rerank(
    db: Database,
    query: str,
    documents: Iterable[tuple[str, str] | tuple[str, str, dict[str, Any]]],
    *,
    top_k: int = 5,
    shortlist_k: int = 25,
    use_embeddings: bool = True,
    embed_weight: float = 0.6,
    embed_all_max: int = DEFAULT_EMBED_ALL_MAX,
    prior_scores: dict[str, float] | None = None,
    prior_weight: float = 0.0,
) -> list[RankedHit]:
    """Rank ``documents`` for ``query``.

    ``documents`` items are ``(doc_id, text)`` or ``(doc_id, text, meta)``.
    ``prior_scores`` (e.g. BM25) blend in when ``prior_weight > 0``; values are
    min-max normalized over the shortlist before blending.
    """
    query = (query or "").strip()
    if not query or top_k <= 0:
        return []

    docs: list[tuple[str, str, dict[str, Any]]] = []
    for item in documents:
        if len(item) == 2:
            doc_id, text = item  # type: ignore[misc]
            meta: dict[str, Any] = {}
        else:
            doc_id, text, meta = item  # type: ignore[misc]
            meta = dict(meta or {})
        docs.append((str(doc_id), str(text or ""), meta))
    if not docs:
        return []

    q_tokens = tokenize(query)
    lex_scored = [
        (lexical_score(q_tokens, text), doc_id, text, meta)
        for doc_id, text, meta in docs
    ]

    embed_all = use_embeddings and len(lex_scored) <= max(embed_all_max, 1)
    if embed_all:
        shortlist = lex_scored
    else:
        lex_scored.sort(key=lambda row: row[0], reverse=True)
        shortlist = lex_scored[: max(shortlist_k, 1)]

    embed_scores: dict[str, float] = {}
    if use_embeddings and shortlist:
        try:
            from ..embeddings import embed_texts

            texts = [query] + [text for _, _, text, _ in shortlist]
            emb = embed_texts(db, texts)
            if emb.degraded:
                # Substituted fake vectors are hash noise: cosine over them is
                # meaningless, not merely weaker. Blending them at embed_weight
                # would silently randomize the ranking, so drop the dense signal
                # and let lexical/prior carry full weight below.
                logger.warning(
                    "embedding provider degraded (%s); reranking on lexical"
                    " signal only",
                    "; ".join(emb.errors[:2]) or "unknown",
                )
            elif emb.vectors and len(emb.vectors) == 1 + len(shortlist):
                q_vec = emb.vectors[0]
                for (_, doc_id, _, _), vec in zip(shortlist, emb.vectors[1:]):
                    # Map cosine [-1,1] → [0,1] for stable blending.
                    embed_scores[doc_id] = max(
                        0.0, min(1.0, (_cosine(q_vec, vec) + 1.0) / 2.0)
                    )
        except Exception as exc:
            logger.debug("embedding rerank skipped: %s", exc)

    prior_norm: dict[str, float] = {}
    if prior_scores and prior_weight > 0:
        vals = [float(prior_scores.get(doc_id, 0.0)) for _, doc_id, _, _ in shortlist]
        lo = min(vals) if vals else 0.0
        hi = max(vals) if vals else 0.0
        span = (hi - lo) or 1.0
        for _, doc_id, _, _ in shortlist:
            prior_norm[doc_id] = (float(prior_scores.get(doc_id, 0.0)) - lo) / span

    hits: list[RankedHit] = []
    has_embed = bool(embed_scores)
    has_prior = bool(prior_norm)
    w_e = embed_weight if has_embed else 0.0
    w_p = prior_weight if has_prior else 0.0
    residual = max(0.0, 1.0 - w_e - w_p)
    if not has_embed and not has_prior:
        residual = 1.0

    for lex, doc_id, text, meta in shortlist:
        emb_s = embed_scores.get(doc_id, 0.0)
        prior_s = prior_norm.get(doc_id, 0.0)
        combined = residual * lex + w_e * emb_s + w_p * prior_s
        hits.append(
            RankedHit(
                doc_id=doc_id,
                text=text,
                score=round(combined, 4),
                lexical_score=round(lex, 4),
                embed_score=round(emb_s, 4),
                meta=meta,
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]
