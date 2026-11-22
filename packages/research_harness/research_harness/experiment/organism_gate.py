"""BUG-012: cross-species / cross-model validation evidence detection.

Works on existing paper text (title + abstract) — no new data pipeline needed.
Opt-in per topic: only fires when a topic declares ``expected_organism`` via
``rh topic update --expected-organism``. Papers whose text clearly indicates a
different organism than the declared one are flagged as support-only, so a
human-DVT topic no longer treats mouse vein-wall or CTEPH data as direct
validation evidence.
"""

from __future__ import annotations

import re
from typing import Any

from research_harness.storage.db import Database

# Curated biomedical organism markers. Word boundaries / multi-word phrases keep
# false positives down (e.g. "rat" won't match "generate", "human" is a whole
# word). This is a warning-level signal for human review, not a hard block.
_ORGANISM_TERMS: dict[str, tuple[str, ...]] = {
    "human": (r"\bhuman\b", r"\bpatients?\b", r"\bclinical\b", r"\bhomo sapiens\b"),
    "mouse": (r"\bmouse\b", r"\bmice\b", r"\bmurine\b", r"\bc57bl\b"),
    "rat": (r"\brat\b", r"\brats\b", r"\bsprague[- ]dawley\b"),
    "zebrafish": (r"\bzebrafish\b", r"\bdanio rerio\b"),
    "drosophila": (r"\bdrosophila\b", r"\bfruit fly\b"),
    "primate": (r"\bmacaque\b", r"\brhesus\b", r"\bnon-?human primate\b"),
    "c_elegans": (r"\bc\.?\s?elegans\b", r"\bcaenorhabditis\b"),
    "yeast": (r"\byeast\b", r"\bsaccharomyces\b"),
}
_ORGANISM_RE: dict[str, re.Pattern[str]] = {
    name: re.compile("|".join(pats), re.IGNORECASE)
    for name, pats in _ORGANISM_TERMS.items()
}


def detect_organisms(text: str) -> set[str]:
    """Return the set of organism markers found in ``text``."""
    if not text:
        return set()
    return {name for name, rx in _ORGANISM_RE.items() if rx.search(text)}


def cross_species_evidence_findings(
    db: Database, topic_id: int
) -> list[dict[str, Any]]:
    """Flag topic papers whose organism differs from the declared expectation.

    Returns an empty list when the topic declares no ``expected_organism`` (the
    check is opt-in), or when every paper matches / is organism-agnostic.
    """
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT expected_organism FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        expected = str((row["expected_organism"] if row else "") or "").strip().lower()
        if not expected:
            return []
        papers = conn.execute(
            """
            SELECT p.id, p.title, p.abstract
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND COALESCE(pt.relevance, '') NOT LIKE 'dismissed%'
              AND COALESCE(pt.relevance, '') NOT LIKE 'excluded%'
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    findings: list[dict[str, Any]] = []
    for paper in papers:
        text = f"{paper['title'] or ''} {paper['abstract'] or ''}"
        organisms = detect_organisms(text)
        # Only flag when the paper clearly indicates a different organism and
        # does NOT also mention the expected one (mixed papers are ambiguous).
        if organisms and expected not in organisms:
            findings.append(
                {
                    "paper_id": int(paper["id"]),
                    "expected_organism": expected,
                    "detected_organisms": sorted(organisms),
                    "severity": "warning",
                    "message": (
                        f"paper {paper['id']} evidence appears to be "
                        f"{'/'.join(sorted(organisms))}, not the topic's declared "
                        f"organism '{expected}'; treat as support evidence only, "
                        "not direct validation (BUG-012)"
                    ),
                }
            )
    return findings
