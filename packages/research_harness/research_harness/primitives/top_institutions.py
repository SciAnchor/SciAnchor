"""Top-tier institution gate for exemplar source prioritization (EAG).

Goal 4 of the EAG first-impression plan: exemplar papers are restricted to
CCF-A / CAS-Q1 venues and preferentially drawn from absolutely-top institutions
(Google, OpenAI, Stanford, Harvard, ...). This module is the institution half
of that gate; the venue half is ``venue_facts.venue_tier_score`` (score >= 85
means CCF-A or CAS-Q1).

The matcher is keyword-based: an affiliation string is normalized to lowercase
alphanumerics and matched against canonical institution keywords (with aliases
for common spellings). It is intentionally conservative — a paper only counts
as "top" when at least one author affiliation resolves to a listed institution.
"""

from __future__ import annotations

import re
from typing import Iterable

# Canonical institution name -> alias keywords that identify it. Matching is a
# substring test on the normalized affiliation string, so "Google Research,
# Mountain View" and "Stanford University" both resolve. Keep aliases lowercase.
_TOP_INSTITUTION_ALIASES: dict[str, tuple[str, ...]] = {
    # Industry labs (absolutely top tier).
    "google": ("google",),
    "openai": ("openai",),
    "deepmind": ("deepmind",),
    "anthropic": ("anthropic",),
    "meta": ("meta", "facebook ai research", "fair"),
    "microsoft": ("microsoft research", "microsoft"),
    "nvidia": ("nvidia",),
    # Top US universities.
    "stanford": ("stanford",),
    "harvard": ("harvard",),
    "mit": ("mit", "massachusetts institute of technology"),
    "berkeley": ("berkeley", "uc berkeley", "university of california, berkeley"),
    "cmu": ("carnegie mellon", "cmu"),
    "princeton": ("princeton",),
    "caltech": ("caltech", "california institute of technology"),
    "columbia": ("columbia",),
    "cornell": ("cornell",),
    "yale": ("yale",),
    # Top international universities / institutes.
    "oxford": ("oxford",),
    "cambridge": ("cambridge",),
    "eth_zurich": ("eth zurich", "eth zürich", "ethz"),
    "toronto": ("university of toronto", "vector institute"),
    "tsinghua": ("tsinghua",),
    "peking": ("peking",),
    # Top research institutes.
    "max_planck": ("max planck",),
    "allen_ai": (
        "allen institute for ai",
        "allen institute for artificial intelligence",
        "ai2",
    ),
    "cas": ("chinese academy of sciences",),
}

_NORM_RE = re.compile(r"[^a-z0-9]+")


def normalize_affiliation(affiliation: str) -> str:
    """Lowercase and strip punctuation so aliases can substring-match reliably."""
    return _NORM_RE.sub(" ", (affiliation or "").lower()).strip()


def top_institution_matches(affiliations: Iterable[str] | str | None) -> list[str]:
    """Return the canonical names of top institutions matched in ``affiliations``.

    Accepts a single string or an iterable of strings (the ``papers.affiliations``
    JSON list). Returns the matched canonical names, de-duplicated and in
    definition order; empty list when nothing matches.
    """
    if not affiliations:
        return []
    if isinstance(affiliations, str):
        values = [affiliations]
    else:
        values = list(affiliations)

    hits: list[str] = []
    for aff in values:
        norm = normalize_affiliation(aff)
        if not norm:
            continue
        for canonical, aliases in _TOP_INSTITUTION_ALIASES.items():
            if canonical in hits:
                continue
            if any(alias in norm for alias in aliases):
                hits.append(canonical)
    return hits


def has_top_institution(affiliations: Iterable[str] | str | None) -> bool:
    """True when at least one affiliation resolves to a top institution."""
    return bool(top_institution_matches(affiliations))
