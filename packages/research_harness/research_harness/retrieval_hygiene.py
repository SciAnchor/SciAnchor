"""Retrieval evidence hygiene (E2/E3/E6–E8).

Index APIs lie in different ways: arXiv expands stems, Crossref ignores quotes,
DBLP does prefix match. Anything that enters a novelty argument must be able to
report API total vs local literal matches.
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
_WS_RE = re.compile(r"\s+")


#: What an index will accept as a query. A claim stated as a sentence still
#: searches; a claim stated as a paragraph is rejected (OpenReview answers 400)
#: or throttled, and in a novelty check one such rejection is enough to withdraw
#: the verdict — so an unsearchable capture round costs the whole answer.
QUERY_CHAR_BUDGET = 240


def normalize_query_text(query: str) -> str:
    return _WS_RE.sub(" ", (query or "").strip())


def is_query_shaped(text: str) -> bool:
    """Whether this text can be handed to an index as it stands."""
    return 0 < len(normalize_query_text(text)) <= QUERY_CHAR_BUDGET


def query_tokens(query: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_query_text(query))


def arxiv_query_forms(query: str) -> list[str]:
    """arXiv ``search_query`` forms to union (E2).

    Multi-word phrases collapse under a single ``all:"A B"`` when token order or
    field boundaries differ. Emit both the quoted phrase and an AND of tokens,
    on ``all`` and ``abs``, then dedupe.
    """
    q = normalize_query_text(query)
    if not q:
        return []
    forms = [f'all:"{q}"', f"all:{q}"]
    tokens = query_tokens(q)
    if len(tokens) >= 2:
        and_all = " AND ".join(f"all:{t}" for t in tokens)
        and_abs = " AND ".join(f"abs:{t}" for t in tokens)
        forms.extend(
            [
                f'abs:"{q}"',
                and_all,
                and_abs,
            ]
        )
    out: list[str] = []
    seen: set[str] = set()
    for form in forms:
        if form not in seen:
            seen.add(form)
            out.append(form)
    return out


def _word_boundary_pattern(phrase: str) -> re.Pattern[str] | None:
    tokens = query_tokens(phrase)
    if not tokens:
        return None
    body = r"\s+".join(re.escape(t) for t in tokens)
    return re.compile(rf"\b{body}\b", re.IGNORECASE)


def _token_stem_prefix(token: str) -> str:
    """Crude stem prefix so routing↔route / outlines↔outline share a head."""
    t = token.casefold()
    if len(t) <= 4:
        return t
    # Drop a short inflectional tail when present.
    for suffix in ("ings", "ing", "ies", "ied", "ed", "es", "s"):
        if t.endswith(suffix) and len(t) - len(suffix) >= 4:
            return t[: len(t) - len(suffix)]
    return t


def _stem_conjunct_pattern(phrase: str) -> list[re.Pattern[str]]:
    """One pattern per token; all must match (E8 stem-conjunction)."""
    patterns: list[re.Pattern[str]] = []
    for token in query_tokens(phrase):
        stem = _token_stem_prefix(token)
        patterns.append(re.compile(rf"\b{re.escape(stem)}\w*\b", re.IGNORECASE))
    return patterns


def literal_match_report(
    texts: list[str],
    phrase: str,
    *,
    api_total: int | None = None,
) -> dict[str, Any]:
    """Local literal audit for one phrase over retrieved rows (E3/E6/E7/E8).

    Reports:
    - ``phrase_hits``: contiguous word-boundary phrase matches
    - ``stem_conjunct_hits``: every token's stem appears somewhere in the text
    - ``api_total`` / ratios when provided

    When ``phrase_hits == 0`` and ``stem_conjunct_hits > 0``, callers must not
    treat the cell as empty (E8) — human review required.
    """
    phrase_re = _word_boundary_pattern(phrase)
    stem_res = _stem_conjunct_pattern(phrase)
    phrase_hits = 0
    stem_hits = 0
    for raw in texts:
        text = raw or ""
        if phrase_re is not None and phrase_re.search(text):
            phrase_hits += 1
        if stem_res and all(p.search(text) for p in stem_res):
            stem_hits += 1
    n = len(texts)
    api = int(api_total) if api_total is not None else None
    phrase_ratio = (phrase_hits / api) if api and api > 0 else None
    stem_ratio = (stem_hits / api) if api and api > 0 else None
    usable_as_denominator = True
    notes: list[str] = []
    if api is not None and api > 0 and phrase_ratio is not None and phrase_ratio < 0.5:
        usable_as_denominator = False
        notes.append(
            f"literal/api={phrase_ratio:.3f} < 0.5; do not use api_total as a "
            "novelty denominator"
        )
    if phrase_hits == 0 and stem_hits > 0:
        usable_as_denominator = False
        notes.append(
            "phrase_hits=0 but stem_conjunct_hits>0; require human review, "
            "do not record as empty"
        )
    return {
        "phrase": normalize_query_text(phrase),
        "rows_scanned": n,
        "api_total": api,
        "phrase_hits": phrase_hits,
        "stem_conjunct_hits": stem_hits,
        "phrase_ratio": phrase_ratio,
        "stem_ratio": stem_ratio,
        "usable_as_denominator": usable_as_denominator,
        "notes": notes,
    }


def audit_retrieved_rows(
    rows: list[dict[str, Any]],
    phrase: str,
    *,
    api_total: int | None = None,
    title_key: str = "title",
    abstract_key: str = "abstract",
) -> dict[str, Any]:
    """Convenience wrapper: audit title+abstract fields on retrieved rows.

    Never pass an index ``total-results`` as the sole hit count (E3). Prefer
    ``api_total=None`` unless you also report the local literal ratios.
    """
    texts: list[str] = []
    with_abstract = 0
    for row in rows:
        title = str(row.get(title_key) or "")
        abstract = str(row.get(abstract_key) or "")
        if abstract.strip():
            with_abstract += 1
        texts.append(f"{title}\n{abstract}".strip())
    report = literal_match_report(texts, phrase, api_total=api_total)
    n = len(rows)
    abstract_coverage = (with_abstract / n) if n else 0.0
    report["rows_with_abstract"] = with_abstract
    report["abstract_coverage"] = abstract_coverage
    if abstract_coverage < 0.5 and n:
        report["usable_as_denominator"] = False
        report["notes"] = list(report["notes"]) + [
            f"abstract_coverage={abstract_coverage:.2f} < 0.5; Crossref-style "
            "counts are lower bounds only (E3)"
        ]
    return report


# E10: only verbatim extraction may feed quantitative evidence claims.
ADMISSIBLE_NUMERIC_EVIDENCE_METHODS = frozenset({"grep", "pdf_text", "html_text"})


def is_admissible_numeric_evidence(method: str) -> bool:
    """True iff ``method`` is allowed for numeric claims in novelty evidence."""
    return str(method or "").strip().lower() in ADMISSIBLE_NUMERIC_EVIDENCE_METHODS


# E4: coarse domain → primary index route. Wrong primary index under-samples
# by orders of magnitude and fabricates "community moved on" trends.
_DOMAIN_ROUTES: tuple[
    tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        "human_factors",
        (
            "human factors",
            "ergonomics",
            "function allocation",
            "fitts",
            "maba-maba",
            "automation transparency",
            "levels of automation",
        ),
        ("crossref", "pubmed"),
        ("dblp", "openalex", "arxiv"),
    ),
    (
        "clinical_evidence",
        (
            "pubmed",
            "cerqual",
            "conqual",
            "cochrane",
            "clinical trial",
            "systematic review",
        ),
        ("pubmed", "crossref"),
        ("openalex", "semantic_scholar"),
    ),
    (
        "softeng_hci",
        ("software engineering", "hci", "human-computer", "acm dl", "chi ", "uist"),
        ("crossref", "dblp"),
        ("openalex", "arxiv"),
    ),
    (
        "ml_agents",
        (
            "llm",
            "language model",
            "transformer",
            "reinforcement",
            "agent",
            "sycophancy",
            "retrieval-augmented",
            "benchmark",
        ),
        ("arxiv", "semantic_scholar", "openalex"),
        ("crossref", "dblp"),
    ),
)


def recommend_index_route(text: str) -> dict[str, Any]:
    """Pick a primary index family from free text (E4)."""
    blob = normalize_query_text(text).casefold()
    for domain, keywords, primary, secondary in _DOMAIN_ROUTES:
        if any(k in blob for k in keywords):
            return {
                "domain": domain,
                "primary_indexes": list(primary),
                "secondary_indexes": list(secondary),
                "matched": True,
            }
    return {
        "domain": "unknown",
        "primary_indexes": ["arxiv", "openalex", "semantic_scholar", "crossref"],
        "secondary_indexes": ["dblp", "pubmed"],
        "matched": False,
    }


def uncovered_index_note(
    text: str, providers_queried: list[str] | tuple[str, ...] = ()
) -> str:
    """Coverage caveat when primary indexes for the domain were not queried (E4)."""
    route = recommend_index_route(text)
    if not route["matched"]:
        return ""
    queried = {str(p).strip().casefold() for p in providers_queried if str(p).strip()}
    # local / multi are not indexes
    queried -= {"local", "multi", "local_only", "cache", "stale_cache"}
    aliases = {
        "s2": "semantic_scholar",
        "semantic scholar": "semantic_scholar",
        "semanticscholar": "semantic_scholar",
    }
    normalized = {aliases.get(p, p) for p in queried}
    missing = [idx for idx in route["primary_indexes"] if idx not in normalized]
    if not missing:
        return ""
    return (
        f" Domain-index route={route['domain']}: primary index(es) not covered this "
        f"run: {', '.join(missing)}. Trend or emptiness claims on the wrong primary "
        "index are invalid (E4)."
    )


def synonym_family_zero_hits(
    family_hit_counts: dict[str, int],
) -> dict[str, Any]:
    """Flag lexicon collapse before treating zeros as open space (E5).

    ``family_hit_counts`` maps synonym/family label → retrieved hit count.
    Any zero-hit family is a suspect lexicon, not proof of vacancy.
    """
    zeros = [name for name, n in family_hit_counts.items() if int(n or 0) <= 0]
    nonzero = [name for name, n in family_hit_counts.items() if int(n or 0) > 0]
    suspect = bool(zeros)
    note = ""
    if zeros:
        note = (
            f" Synonym-family zero-hit(s): {', '.join(zeros)}. Suspect lexicon/"
            "morphology/index collapse before recording vacancy (E5)."
        )
        if nonzero:
            note += f" Non-zero families: {', '.join(nonzero)}."
    return {
        "zero_families": zeros,
        "nonzero_families": nonzero,
        "suspect_lexicon": suspect,
        "note": note,
    }


def filter_numeric_evidence_methods(
    items: list[dict[str, Any]],
    *,
    method_key: str = "method",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split evidence rows into admissible vs rejected for numeric claims (E10)."""
    ok: list[dict[str, Any]] = []
    bad: list[dict[str, Any]] = []
    for item in items:
        method = str(item.get(method_key) or "")
        if is_admissible_numeric_evidence(method):
            ok.append(item)
        else:
            bad.append(item)
    return ok, bad


# Provider names actually present in paper_source_clients.build_provider_suite.
# Derived from the suite's source table so a domain allowlist can never name a
# source the suite does not build (which would filter every source out).
def _known_search_providers() -> frozenset[str]:
    from research_harness.paper_source_clients import KEYLESS_SOURCES

    return frozenset({"papervault", *(name for name, _reason in KEYLESS_SOURCES)})


def provider_allowlist_for_text(text: str) -> list[str] | None:
    """E4: when domain matches, return concrete provider allowlist for paper_search.

    Returns None when domain is unknown so the default full suite is kept.
    """
    route = recommend_index_route(text)
    if not route["matched"]:
        return None
    ordered: list[str] = []
    for name in list(route["primary_indexes"]) + list(route["secondary_indexes"]):
        key = str(name).strip().casefold()
        if key == "s2":
            key = "semantic_scholar"
        if key in _known_search_providers() and key not in ordered:
            ordered.append(key)
    return ordered or None


# E5: small static cross-domain lexicon for known collapses (backlog cases).
# Values are alternate query phrasings, not full thesauri.
_SYNONYM_EXPAND: dict[str, tuple[str, ...]] = {
    "ask for help": (
        "expert calls",
        "query budget",
        "intervention budget",
        "escalation rate",
        "context switches",
    ),
    "function allocation": (
        "task allocation automation",
        "MABA-MABA",
        "levels of automation",
    ),
    "paper outline": ("paper outlining", "outline generation paper"),
    "sycophancy": ("sycophantic", "agreeableness bias", "preference sycophancy"),
}


def expand_synonym_queries(queries: list[str], *, max_extra: int = 6) -> list[str]:
    """Append lexicon alternates for known phrases appearing in queries (E5)."""
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        text = normalize_query_text(q)
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        out.append(text)
    extras: list[str] = []
    blob = " | ".join(out).casefold()
    for seed, alts in _SYNONYM_EXPAND.items():
        if seed not in blob and not any(seed in q.casefold() for q in out):
            continue
        for alt in alts:
            key = alt.casefold()
            if key in seen:
                continue
            seen.add(key)
            extras.append(alt)
            if len(extras) >= max_extra:
                break
        if len(extras) >= max_extra:
            break
    return out + extras


def sanitize_numeric_evidence_items(
    items: list[dict[str, Any]],
    *,
    method_key: str = "method",
    value_keys: tuple[str, ...] = ("value", "n", "count", "sample_size", "total"),
) -> dict[str, Any]:
    """Drop numeric claims that lack an admissible extraction method (E10).

    Rows without any numeric value_keys pass through untouched. Rows that carry
    a numeric field must use grep/pdf_text/html_text or they are rejected.
    """
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        has_numeric = any(
            item.get(k) is not None and str(item.get(k)).strip() != ""
            for k in value_keys
        )
        if not has_numeric:
            kept.append(item)
            continue
        if is_admissible_numeric_evidence(str(item.get(method_key) or "")):
            kept.append(item)
        else:
            rejected.append(item)
    note = ""
    if rejected:
        note = (
            f" Rejected {len(rejected)} numeric evidence row(s) lacking admissible "
            "method (grep/pdf_text/html_text); WebFetch/summary numbers are not "
            "evidence (E10)."
        )
    return {"kept": kept, "rejected": rejected, "note": note}
