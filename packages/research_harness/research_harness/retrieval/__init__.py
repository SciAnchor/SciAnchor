"""Shared retrieve-then-rerank primitives (IDX01 slice).

Lexical shortlist is a cheap gate, not the ranker. Embeddings (when available)
carry the accuracy; see arXiv 2508.21038. This package does not own ANN
indexes or offline workers — only the online combine path over an
already-materialized candidate set.
"""

from __future__ import annotations

from .assets import (
    FigureHit,
    load_exemplar_unit_rows,
    rank_exemplar_rows,
    search_extracted_figures,
    upsert_exemplar_units,
)
from .rerank import RankedHit, retrieve_then_rerank

__all__ = [
    "FigureHit",
    "RankedHit",
    "load_exemplar_unit_rows",
    "rank_exemplar_rows",
    "retrieve_then_rerank",
    "search_extracted_figures",
    "upsert_exemplar_units",
]
