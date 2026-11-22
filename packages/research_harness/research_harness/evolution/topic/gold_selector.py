"""V2 Self-Evolution Phase 3: Gold paper selection for cold start.

Selects high-quality papers from the pool as gold standards for comparison.
Criteria: venue tier, citation count, recency, full-text availability.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ...venue_facts import venue_tier_score

logger = logging.getLogger(__name__)


def _venue_tier(venue: str) -> int:
    """Map venue facts back onto the original 3/2/0 gold-selection ladder:
    CCF-A-and-up flagships -> 3, CCF-B/CAS-Q2-grade -> 2, rest -> 0."""
    score = venue_tier_score(venue)
    if score >= 90:
        return 3
    if score >= 65:
        return 2
    return 0


class GoldSelector:
    def __init__(self, db: Any) -> None:
        self._db = db

    def select(
        self,
        topic_id: int,
        max_papers: int = 5,
        max_age_years: int = 5,
        min_citations: int = 0,
    ) -> list[dict[str, Any]]:
        current_year = datetime.now().year
        min_year = current_year - max_age_years

        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT p.id, p.title, p.venue, p.year, p.citation_count, p.arxiv_id, p.status
                   FROM papers p
                   JOIN paper_topics pt ON p.id = pt.paper_id
                   WHERE pt.topic_id = ?
                     AND p.status = 'full_text'
                     AND (p.year IS NULL OR p.year >= ?)
                     AND (p.citation_count IS NULL OR p.citation_count >= ?)
                   ORDER BY p.citation_count DESC NULLS LAST""",
                (topic_id, min_year, min_citations),
            ).fetchall()
        finally:
            conn.close()

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            venue = (row["venue"] or "").strip()
            venue_score = _venue_tier(venue) / 3.0
            cite_count = row["citation_count"] or 0
            cite_score = min(1.0, cite_count / 100.0)
            year = row["year"] or current_year
            recency_score = max(0.0, 1.0 - (current_year - year) / max_age_years)

            composite = venue_score * 0.4 + cite_score * 0.3 + recency_score * 0.3

            scored.append(
                (
                    composite,
                    {
                        "paper_id": row["id"],
                        "title": row["title"],
                        "venue": row["venue"] or "",
                        "year": row["year"],
                        "citation_count": cite_count,
                        "score": round(composite, 3),
                    },
                )
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:max_papers]]
