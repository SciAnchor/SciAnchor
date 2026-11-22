"""Single venue-fact lookup service.

This is the one place RH resolves a venue string to CCF/CAS tier facts.
Lookup order:

1. Exact hit in the hardcoded registry (``primitives.venue_tiers``) — the
   offline baseline and the only source for *conferences* (journal_master
   is journals-only).
2. Exact hit in SPC's ``journal_master.db`` (22k journals with CCF/CAS/JCR
   facts), opened read-only via ``RESEARCH_HARNESS_JOURNAL_MASTER_DB``
   (PaperVault pattern: absent/broken DB silently degrades to offline).
3. Guarded substring fallback against the hardcoded registry only.

The schema is owned by SPC and treated as a frozen read contract:

    journal_records(normalized_name TEXT PRIMARY KEY,  -- lower, alnum only
                    original_name TEXT, facts_json TEXT)

``facts_json`` keys used here: ``ccf.rank`` ("A"/"B"/"C") and ``cas.zone``
(1-4). RH never writes to the file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from .primitives.venue_tiers import (
    _EMPTY_TIER,
    _TIER_THRESHOLDS,
    _VENUE_REGISTRY,
    CASQuartile,
    CCFTier,
    VenueTier,
    normalize_venue_name,
)

__all__ = [
    "JOURNAL_MASTER_DB_ENV",
    "CCFTier",
    "CASQuartile",
    "VenueTier",
    "normalize_venue_name",
    "get_venue_tier",
    "meets_tier_threshold",
    "venue_tier_score",
    "venue_tier_label",
    "venue_facts_status",
    "build_venue_facts_check",
]

logger = logging.getLogger(__name__)

JOURNAL_MASTER_DB_ENV = "RESEARCH_HARNESS_JOURNAL_MASTER_DB"

_SQUASH_RE = re.compile(r"[^a-z0-9]+")

_CCF_RANK_TO_TIER = {
    "A*": CCFTier.A_STAR,
    "A": CCFTier.A,
    "B": CCFTier.B,
    "C": CCFTier.C,
}
_CAS_ZONE_TO_QUARTILE = {
    1: CASQuartile.Q1,
    2: CASQuartile.Q2,
    3: CASQuartile.Q3,
    4: CASQuartile.Q4,
}

# Registry keys too ambiguous for substring matching: short abbreviations
# that collide inside unrelated names ("chi" in "machine"), plus
# generic-word journal titles that appear inside other journals' names
# ("science" in "journal of medical science"). Exact lookup still works.
_FALLBACK_AMBIGUOUS_KEYS = frozenset(
    {
        "nature",
        "science",
        "access",
        "supercomputing",
        "artificial intelligence",
        "artificial intelligence journal",
        "machine learning",
        "neural networks",
        "pattern recognition",
        "information sciences",
        "computational linguistics",
    }
)

# Generic query strings that would otherwise substring-match into a key.
_GENERIC_QUERIES = frozenset(
    {
        "conference",
        "journal",
        "proceedings",
        "workshop",
        "symposium",
        "transactions",
        "international",
        "international conference",
    }
)


def _journal_master_path() -> str:
    raw = os.environ.get(JOURNAL_MASTER_DB_ENV, "").strip()
    if not raw:
        return ""
    path = Path(raw).expanduser()
    return str(path) if path.is_file() else ""


@lru_cache(maxsize=4096)
def _db_tier(db_path: str, squashed_name: str) -> VenueTier | None:
    """Exact lookup in journal_master.db. None = no usable facts."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        try:
            row = conn.execute(
                "SELECT facts_json FROM journal_records WHERE normalized_name = ?",
                (squashed_name,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        logger.warning("journal_master query failed", exc_info=True)
        return None
    if not row or not row[0]:
        return None
    try:
        facts = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(facts, dict):
        return None

    ccf_facts = facts.get("ccf") or {}
    cas_facts = facts.get("cas") or {}
    rank = str(ccf_facts.get("rank") or "").upper().strip()
    ccf = _CCF_RANK_TO_TIER.get(rank, CCFTier.NONE)
    try:
        zone = int(cas_facts.get("zone"))
    except (TypeError, ValueError):
        zone = 0
    cas = _CAS_ZONE_TO_QUARTILE.get(zone, CASQuartile.NONE)
    if ccf is CCFTier.NONE and cas is CASQuartile.NONE:
        return None
    return VenueTier.create(ccf, cas)


def _fallback_tier(normalized: str) -> VenueTier | None:
    """Guarded substring fallback over the hardcoded registry."""
    if len(normalized) < 4 or normalized in _GENERIC_QUERIES:
        return None
    for key, tier in _VENUE_REGISTRY.items():
        if len(key) < 4 or key in _FALLBACK_AMBIGUOUS_KEYS:
            continue
        # Abbreviation/full name appearing as a whole word inside the query
        # ("aaai conference on artificial intelligence" -> "aaai"), or the
        # query being a fragment of a registered full name.
        if re.search(rf"\b{re.escape(key)}\b", normalized) or (
            len(normalized) >= 6 and normalized in key
        ):
            return tier
    return None


def get_venue_tier(venue: str) -> VenueTier:
    """Look up venue tier facts. Returns empty tier (score=0) for unknowns."""
    if not venue:
        return _EMPTY_TIER
    normalized = normalize_venue_name(venue)
    if not normalized:
        return _EMPTY_TIER

    tier = _VENUE_REGISTRY.get(normalized)
    if tier is not None:
        return tier

    db_path = _journal_master_path()
    if db_path:
        squashed = _SQUASH_RE.sub("", normalized)
        if squashed:
            db_tier = _db_tier(db_path, squashed)
            if db_tier is None and squashed.startswith("the"):
                # SPC normalizes "The Lancet" -> "lancet"
                db_tier = _db_tier(db_path, squashed[3:])
            if db_tier is not None:
                return db_tier

    return _fallback_tier(normalized) or _EMPTY_TIER


def _normalize_min_tier(min_tier: str) -> str:
    key = re.sub(r"[\s\-]+", "_", min_tier.strip().lower())
    return key.replace("*", "_star")


def meets_tier_threshold(venue: str, min_tier: str) -> bool:
    """Check if venue meets the minimum tier threshold.

    min_tier: one of ccf_a_star, ccf_a, ccf_b, ccf_c, cas_q1..cas_q4
    (common spellings like "CCF-A" / "CAS Q1" are normalized). Empty
    min_tier means no filtering; an *unknown* min_tier fails closed.
    """
    if not min_tier:
        return True
    threshold = _TIER_THRESHOLDS.get(_normalize_min_tier(min_tier))
    if threshold is None:
        logger.warning("unknown venue tier threshold %r; treating as not met", min_tier)
        return False
    return get_venue_tier(venue).score >= threshold


def venue_tier_score(venue: str) -> int:
    """Return numeric score 0-100 for ranking."""
    return get_venue_tier(venue).score


def venue_tier_label(venue: str) -> str:
    """Return human-readable tier label, e.g. 'CCF-A/CAS-Q1'."""
    return get_venue_tier(venue).label


def venue_facts_status() -> dict[str, object]:
    """Readiness snapshot of the optional journal_master.db facts source."""
    raw = os.environ.get(JOURNAL_MASTER_DB_ENV, "").strip()
    if not raw:
        return {
            "journal_master_db": None,
            "state": "not_configured",
            "journal_count": None,
        }
    if not Path(raw).expanduser().is_file():
        return {"journal_master_db": raw, "state": "missing", "journal_count": None}
    count: int | None = None
    try:
        conn = sqlite3.connect(
            f"file:{Path(raw).expanduser()}?mode=ro", uri=True, timeout=2.0
        )
        try:
            count = int(
                conn.execute("SELECT COUNT(*) FROM journal_records").fetchone()[0]
            )
        finally:
            conn.close()
    except sqlite3.Error:
        logger.warning("journal_master count failed", exc_info=True)
    return {"journal_master_db": raw, "state": "ready", "journal_count": count}


def build_venue_facts_check() -> dict[str, object]:
    """``rh doctor`` check entry; journal_master is optional so ``ok`` is always True."""
    status = venue_facts_status()
    check: dict[str, object] = {
        "check": "venue_facts",
        "journal_master_db": status["journal_master_db"] or "not configured",
        "state": status["state"],
        "ok": True,
        "note": (
            "optional journal CCF/CAS facts (SPC journal_master.db); "
            "hardcoded registry is the offline baseline"
        ),
    }
    if status["state"] == "ready":
        check["journal_count"] = status["journal_count"]
    if status["state"] == "not_configured":
        check["remediation"] = [
            f"set {JOURNAL_MASTER_DB_ENV} to SPC's journal_master.db "
            "for CCF/CAS tier facts on 22k journals"
        ]
    return check
