"""Exemplar-Anchored Generation (EAG) — the modality-agnostic engine that
generalizes the reference-driven figure-generation pattern to research artifacts.

"Stand on the shoulders of giants": retrieve high-quality published exemplars →
transfer FORM (structure/style) NOT CONTENT → plan by analogy → critique. Four
primitives (curate, retrieve, plan, critique) reuse RH's LLM/DB helpers; the
critique gate is deterministic n-gram overlap (anti-plagiarism, no LLM).

Maps to Anthropic's agent patterns: routing (retrieve), prompt-chaining
(curate→retrieve→plan), evaluator-optimizer (plan/section_draft ↔ critique).
"""

from __future__ import annotations

import collections
import json
import os
import re
import urllib.request
from typing import Any

from ..venue_facts import get_venue_tier, venue_tier_score
from .top_institutions import top_institution_matches
from .registry import (
    EXEMPLAR_CRITIQUE_SPEC,
    EXEMPLAR_CURATE_SPEC,
    EXEMPLAR_GENERATE_SPEC,
    EXEMPLAR_PLAN_SPEC,
    EXEMPLAR_RETRIEVE_SPEC,
    register_primitive,
)
from .types import (
    ExemplarCritiqueOutput,
    ExemplarCurateOutput,
    ExemplarGenerateOutput,
    ExemplarPlanOutput,
    ExemplarRetrieveOutput,
    ExemplarUnit,
)

# --------------------------------------------------------------------------- #
# LLM helpers (reuse RH's shared client; lazy import to avoid import cycles)   #
# --------------------------------------------------------------------------- #


_ROUTER_OK: bool | None = None  # process-level cache: None=unknown, False=router down


class _LLM:
    """Lightweight LLM handle. Prefers RH's native tier router; transparently
    falls back to a direct OpenAI-compatible endpoint (OPENAI_BASE_URL)
    when the router is unavailable/unauthenticated."""

    def __init__(self, model: str | None, tier: str, task: str):
        self.model = model or os.environ.get("RH_EAG_MODEL", "gpt-6-astra")
        self.tier = (
            tier if tier in ("light", "medium", "heavy", "writing") else "medium"
        )
        self.task = task


def _llm(model: str | None, tier: str, task: str) -> _LLM:
    return _LLM(model, tier, task)


def _direct_chat(model: str, prompt: str) -> str:
    base = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY", "")
    if not base or not key:
        raise RuntimeError(
            "EAG LLM unavailable: RH router failed and OPENAI_BASE_URL/OPENAI_API_KEY are unset."
        )
    payload = {
        "model": model,
        "temperature": 0.3,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        timeout = max(900, int(os.environ.get("LLM_HTTP_TIMEOUT_SECONDS") or 900))
    except (TypeError, ValueError):
        timeout = 900
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.load(r)
    usage = body.get("usage") if isinstance(body, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    _book(model, usage.get("prompt_tokens"), usage.get("completion_tokens"))
    return body["choices"][0]["message"]["content"]


# Every paid call this process made for EAG, as its provider reported it. The CLI prints the report
# (``rh-usage: {...}`` on stderr) so a caller that pays for these commands can account for them.
# ponytail: a bounded buffer, so a long-lived MCP server does not grow it without end; one CLI command
# never makes this many calls.
_CALLS: collections.deque[dict[str, Any]] = collections.deque(maxlen=4096)


def _book(model: str, prompt_tokens: Any, completion_tokens: Any) -> None:
    from research_harness.pricing.models import PRICES, cost_usd

    tokens = [
        t if type(t) is int and t >= 0 else None
        for t in (prompt_tokens, completion_tokens)
    ]
    if tokens == [None, None]:
        _CALLS.append(
            {
                "model": model,
                "prompt_tokens": None,
                "completion_tokens": None,
                "cost_usd": None,
                "price_basis": None,
            }
        )
        return
    prompt, completion = (t or 0 for t in tokens)
    _CALLS.append(
        {
            "model": model,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cost_usd": cost_usd(model, prompt, completion),
            # "table": RH's own price list; "estimate": litellm or RH's default price for a model it
            # does not list.
            "price_basis": "table" if model in PRICES else "estimate",
        }
    )


def usage_report() -> dict[str, Any]:
    """The calls so far and their total; ``cost_usd`` is None when any call's usage is unknown."""
    calls = list(_CALLS)
    known = all(call["cost_usd"] is not None for call in calls)
    return {
        "schema_version": "rh.eag_usage.v1",
        "calls": calls,
        "cost_usd": round(sum(call["cost_usd"] for call in calls), 6)
        if known
        else None,
    }


def _chat(handle: _LLM, prompt: str) -> str:
    global _ROUTER_OK
    if _ROUTER_OK is not False and os.environ.get("RH_EAG_LLM") != "openai_direct":
        try:
            from research_harness.execution.llm_primitives import (
                _client_chat,
                _get_client,
            )

            from llm_router.client import get_last_usage

            c = _get_client(handle.model, tier=handle.tier, task_name=handle.task)
            txt = _client_chat(c, prompt)
            _ROUTER_OK = True
            handle.model = getattr(c, "model", handle.model)
            usage = get_last_usage()
        except Exception:
            _ROUTER_OK = False  # pin to direct for the rest of the process
        else:
            # Booked outside the try: an accounting error must never read as a router failure and buy
            # the same prompt again on the direct path.
            _book(
                handle.model,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
            return txt
    return _direct_chat(handle.model, prompt)


def _json(raw: str, primitive: str) -> dict[str, Any]:
    from research_harness.execution.llm_primitives import _parse_json

    parsed = _parse_json(raw, primitive=primitive)
    return parsed if isinstance(parsed, dict) else {}


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _is_idx(i: Any, n: int) -> bool:
    try:
        return 0 <= int(i) < n
    except (TypeError, ValueError):
        return False


def _tier(venue: str | None) -> str:
    """Coarse exemplar-source grade: CCF-A/CAS-Q1-grade venues are 'A'."""
    v = (venue or "").strip()
    if not v:
        return "?"
    return "A" if venue_tier_score(v) >= 85 else "B"


# --------------------------------------------------------------------------- #
# Exemplar family: prose exemplars come from Nature/Science-family journals    #
# or top CCF-A venues, chosen by the TARGET venue's family — a Nature-journal  #
# paper must not anchor its introduction on CS-conference rhetoric and vice    #
# versa. Figure units keep the plain tier gate (visual form transfers across). #
# --------------------------------------------------------------------------- #

_NATURE_SCIENCE_RE = re.compile(
    r"(?ix)"
    r"\bnature\b"  # Nature + Nature <X> + Nature Communications
    r"|^\s*npj\b"
    r"|\bscientific\s+reports\b"
    r"|\bcommunications\s+(biology|medicine|engineering|physics|chemistry|"
    r"earth|materials|psychology)\b"
    r"|\bhumanities\s+and\s+social\s+sciences\s+communications\b"
    r"|^\s*science\s*$|\bscience\s+(advances|robotics|translational|immunology)\b"
    r"|\bproceedings\s+of\s+the\s+national\s+academy\b|^\s*pnas\b"
)

# The grade a borrowed exemplar holds whatever grade the topic's own papers are held to.
# CAS-Q1 / CCF-A on the venue_tier_score scale, the standing `exemplar_curate` default.
_EXEMPLAR_TIER_FLOOR = 85

_NATURE_MEDICAL_RE = re.compile(
    r"(?i)^\s*npj\s+(digital\s+medicine|precision\s+oncology|breast\s+cancer|"
    r"vaccines|parkinson['’]?s\s+disease|primary\s+care\s+respiratory\s+medicine)\s*$"
    r"|\bnature\s+(medicine|biomedical\s+engineering)\b"
    r"|\blancet\b|\bcommunications\s+medicine\b|\bscience\s+(translational|immunology)\b"
)
_NATURE_HSSC_RE = re.compile(
    r"(?i)\bhumanities\s+and\s+social\s+sciences\s+communications\b|^hssc$"
    r"|\bnature\s+(human\s+behaviour|psychology)\b|\bcommunications\s+psychology\b"
)
_MOVE_UNITS = frozenset({"abstract_moves", "intro_moves", "discussion_moves"})
# Track A of dual-track EAG: the DOMAIN REGISTER (canonical terminology and
# phrasing conventions of the target field). Unlike every FORM unit, it is
# curated from SAME-DOMAIN published papers only (topic match dominates) and
# its canonical terms are meant to be reused verbatim, not paraphrased.
_REGISTER_UNIT = "domain_register"


class ExemplarPoolError(ValueError):
    """A writing contract cannot be derived from the available discipline pool."""

    code = "E-WRITE-EAG-POOL-EMPTY"

    def __init__(self, unit_type: str, family: str | None):
        super().__init__(
            f"{self.code}: {unit_type} has no usable {family or 'same-lane'} "
            "exemplars; curate matching-venue section evidence before WRITE"
        )


# Prose unit types subject to family selection + the surface-prose screen.
_PROSE_UNITS = _MOVE_UNITS | frozenset(
    {
        "skeleton",
        "intro_arc",
        "abstract",
        "related_work_arc",
        "method_arc",
        "experiment_arc",
        "discussion_arc",
        "paragraph_moves",
        "style",
    }
)

# Units whose FORM lives in a section's running prose: curation reads the
# paper's real section text (paperindex structure artifact) so the extracted
# arc/style is sentence-level faithful, not inferred from abstracts. Keys are
# matched against normalized section titles.
_SECTION_EVIDENCE_PATTERNS: dict[str, tuple[str, ...]] = {
    "intro_arc": ("introduction",),
    "intro_moves": ("introduction",),
    "discussion_moves": ("discussion", "conclusion"),
    "style": ("introduction",),
    "paragraph_moves": ("introduction",),
    "related_work_arc": ("related work", "background", "literature"),
    "method_arc": ("method", "methodology", "approach", "materials"),
    "experiment_arc": ("experiment", "result", "evaluation"),
    "discussion_arc": ("discussion", "conclusion", "limitation"),
}


def _venue_matches_family(venue: str | None, family: str | None) -> bool:
    """Does this source venue belong to the requested exemplar family?
    Legacy nature_science/any remain available only for unbound callers."""
    v = (venue or "").strip()
    if not v:
        return False
    medical = bool(_NATURE_MEDICAL_RE.search(v))
    hssc = bool(_NATURE_HSSC_RE.search(v))
    if family == "nature_medical":
        return medical
    if family == "nature_hssc":
        return hssc
    if family == "nature_stem":
        return bool(_NATURE_SCIENCE_RE.search(v)) and not (medical or hssc)
    if family == "nature_science":
        return bool(_NATURE_SCIENCE_RE.search(v)) or medical or hssc
    if family == "ccfa":
        return venue_tier_score(v) >= 90  # CCF-A (90) / CCF-A* (100)
    if family not in (None, "any"):
        return False
    return (
        bool(_NATURE_SCIENCE_RE.search(v))
        or medical
        or hssc
        or venue_tier_score(v) >= 90
    )


def _exemplar_family_for_target(target_venue: str | None) -> str:
    """Map the paper's TARGET venue to the exemplar family to imitate."""
    v = (target_venue or "").strip()
    if not v:
        return "any"  # union of Nature/Science family and top CCF-A
    for family in ("nature_medical", "nature_hssc", "nature_stem"):
        if _venue_matches_family(v, family):
            return family
    from .venue_tiers import CCFTier  # lazy: avoid widening module imports

    if get_venue_tier(v).ccf in (CCFTier.A_STAR, CCFTier.A, CCFTier.B, CCFTier.C):
        return "ccfa"
    # Unknown venue (most non-CS journals): Nature/Science-family journal
    # rhetoric is the safer prose anchor than CS-conference rhetoric.
    return "nature_science"


def _topic_domain_key(db, topic_id) -> str:
    """Domain overlay key from the topic's active paper plan; "" when the
    topic has no plan yet (callers must not default to stem here — an
    unplanned topic falls back to venue-family selection)."""
    if db is None or topic_id is None:
        return ""
    try:
        from research_harness._workflow.execution.llm_primitives import (
            _active_paper_plan,
        )
        from research_harness._workflow.execution.writing_rigor import (
            resolve_domain_key,
        )

        plan = _active_paper_plan(db, topic_id)
        if not plan:
            return ""
        return resolve_domain_key(plan)
    except Exception:
        return ""


def _topic_target_venue(db, topic_id) -> str:
    if db is None or topic_id is None:
        return ""
    try:
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT target_venue FROM topics WHERE id=?", (int(topic_id),)
            ).fetchone()
        finally:
            conn.close()
        return str((row["target_venue"] if row else "") or "")
    except Exception:
        return ""


def _pool_family(db, topic_id, unit_type, venue_profile=None, target_venue=None):
    if unit_type not in _PROSE_UNITS and unit_type != "figure_suite":
        return None
    profile = venue_profile or {}
    family = profile.get("exemplar_family") or profile.get("family")
    if family:
        if family not in {"nature_medical", "nature_hssc", "nature_stem", "ccfa"}:
            raise ExemplarPoolError(unit_type, str(family))
        return str(family)
    target = target_venue or profile.get("venue") or _topic_target_venue(db, topic_id)
    if target:
        return _exemplar_family_for_target(str(target))
    if unit_type in _MOVE_UNITS:
        raise ExemplarPoolError(unit_type, "unspecified target venue")
    return None


def _valid_moves(form):
    """Shape only: scientific/register quality still needs independent calibration."""
    if not isinstance(form, dict):
        return False
    import math

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    def band(value):
        return (
            isinstance(value, list)
            and len(value) == 2
            and all(type(n) in (int, float) and math.isfinite(n) for n in value)
            and 0 < value[0] <= value[1]
        )

    moves = form.get("moves")
    return (
        isinstance(moves, list)
        and bool(moves)
        and all(
            isinstance(m, dict)
            and text(m.get("move"))
            and text(m.get("sentence_action"))
            and band(m.get("word_range"))
            for m in moves
        )
        and band(form.get("length_band_words"))
        and isinstance(form.get("opening_forbidden_moves"), list)
        and all(text(value) for value in form["opening_forbidden_moves"])
    )


def _writing_pool(units, unit_type, family):
    pool = _coerce_units(units)
    if family is not None or unit_type in _MOVE_UNITS:
        pool = [
            u
            for u in pool
            if u.unit_type == unit_type
            and u.source_paper_id > 0
            and u.form
            and _venue_matches_family(u.venue, family)
            and (unit_type not in _MOVE_UNITS or _valid_moves(u.form))
        ]
        if not pool:
            raise ExemplarPoolError(unit_type, family)
    elif unit_type in _PROSE_UNITS and not pool:
        raise ExemplarPoolError(unit_type, family)
    return pool


def _register_clause(venue_profile, family):
    profile = venue_profile or {}
    if not profile and not family:
        return ""
    return (
        "\nBINDING VENUE PROFILE: "
        + json.dumps(profile, ensure_ascii=False)
        + f"\nExemplar family: {family}. Follow this discipline's register and section order; "
        "hssc_argument uses its evidence/argument moves, never an imposed IMRaD formula. "
        "This profile overrides generic section-order advice. Transfer form only; "
        "preserve the target's evidence, claims, uncertainty and citations.\n"
    )


# --------------------------------------------------------------------------- #
# Source text: topic papers + their deep-read notes (defensive)               #
# --------------------------------------------------------------------------- #


def _fetch_note(conn, paper_id: int) -> str:
    for sql in (
        "SELECT content FROM paper_annotations WHERE paper_id=? ORDER BY id DESC LIMIT 4",
        "SELECT note AS content FROM paper_annotations WHERE paper_id=? LIMIT 4",
    ):
        try:
            rows = conn.execute(sql, (paper_id,)).fetchall()
        except Exception:
            continue
        txt = "\n".join((r["content"] or "") for r in rows).strip()
        if txt:
            return txt[:4000]
    return ""


def _load_structure(db, paper_id: int):
    """StructureResult for a pool paper from its persisted paperindex artifact,
    or None."""
    if db is None or not paper_id:
        return None
    try:
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT path FROM paper_artifacts WHERE paper_id=? AND "
                "artifact_type='paperindex_structure' ORDER BY id DESC LIMIT 1",
                (int(paper_id),),
            ).fetchone()
        finally:
            conn.close()
        path = row["path"] if row else ""
        if path and not os.path.isabs(path):
            # stored relative to the pool's parent, not to whoever launched the CLI
            path = os.path.join(os.path.dirname(os.path.dirname(str(db.db_path))), path)
        if not path or not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        from paperindex.types import StructureResult

        return StructureResult.from_dict(data)
    except Exception:
        return None


def _node_text(node, pages: list[str]) -> str:
    txt = (getattr(node, "section_text", "") or "").strip()
    if not txt and pages:
        start = max(1, int(node.start_page or 1))
        end = max(start, int(node.end_page or start))
        txt = "\n".join(
            pages[i - 1] for i in range(start, min(end, len(pages)) + 1)
        ).strip()
    return txt


def _section_prose(
    db, paper_id: int, patterns: tuple[str, ...], max_chars: int = 9000
) -> str:
    """Real running prose of the section(s) whose normalized title matches any
    pattern. "" when the paper has no structure artifact or no matching node;
    prose curation then falls back to abstract+notes and the curate prompt is
    instructed to score such evidence down honestly.
    """
    sr = _load_structure(db, paper_id)
    if sr is None:
        return ""
    try:
        from paperindex.indexing.section_text import normalize_section_title
        from paperindex.utils import flatten_nodes

        pages = [str(p or "") for p in (sr.raw or {}).get("pages_text") or []]
        chunks: list[str] = []
        for node in flatten_nodes(sr.tree):
            title = normalize_section_title(node.title or "")
            if not any(p in title for p in patterns):
                continue
            txt = _node_text(node, pages)
            if txt:
                chunks.append(txt)
            if sum(len(c) for c in chunks) >= max_chars:
                break
        return "\n\n".join(chunks)[:max_chars]
    except Exception:
        return ""


def _structure_overview(db, paper_id: int, max_chars: int = 2500) -> str:
    """Ordered section tree (titles + page spans, appendix included) — the
    real evidence for skeleton curation."""
    sr = _load_structure(db, paper_id)
    if sr is None:
        return ""
    try:
        lines: list[str] = []

        def walk(nodes, depth: int) -> None:
            for n in nodes or []:
                title = (n.title or "").strip()
                if title:
                    lines.append(
                        f"{'  ' * depth}- {title} (pp.{n.start_page}-{n.end_page})"
                    )
                walk(getattr(n, "children", None), depth + 1)

        walk(sr.tree, 0)
        if not lines:
            return ""
        return ("SECTION TREE (with page spans):\n" + "\n".join(lines))[:max_chars]
    except Exception:
        return ""


def _intro_text(db, paper_id: int, max_chars: int = 9000) -> str:
    """Back-compat wrapper: the introduction's running prose."""
    return _section_prose(db, paper_id, ("introduction",), max_chars)


def _parse_affiliations(raw: str | None) -> list[str]:
    """Parse the ``papers.affiliations`` JSON array into a list of strings."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(parsed, list):
        return [str(x) for x in parsed if x]
    return []


def _build_source(conn, r) -> dict[str, Any]:
    """One paper row -> exemplar source dict (venue tier + top institutions)."""
    affiliations = _parse_affiliations(
        r["affiliations"] if "affiliations" in r.keys() else None
    )
    citation = r["citation_count"] if "citation_count" in r.keys() else 0
    return {
        "id": r["id"],
        "title": r["title"] or "",
        "venue": r["venue"] or "",
        "year": r["year"],
        "abstract": (r["abstract"] or "")[:2000],
        "note": _fetch_note(conn, r["id"]),
        "affiliations": affiliations,
        "top_institutions": top_institution_matches(affiliations),
        "tier_score": venue_tier_score(r["venue"] or ""),
        "citation_count": int(citation or 0),
    }


def _rank_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Top institution first, then venue tier, then citation count (goal 4)."""
    return sorted(
        sources,
        key=lambda s: (
            bool(s["top_institutions"]),
            s["tier_score"],
            s["citation_count"],
        ),
        reverse=True,
    )


def _source_admissible(
    source: dict[str, Any], min_tier_score: int, family: str | None
) -> bool:
    """Family gate when a family is requested; legacy tier gate otherwise."""
    if family is not None:
        return _venue_matches_family(source["venue"], family)
    return source["tier_score"] >= int(min_tier_score)


def _global_high_tier_fill(
    conn,
    existing: list[dict[str, Any]],
    limit: int,
    min_tier_score: int,
    family: str | None = None,
) -> list[dict[str, Any]]:
    """Fill a filtered pool that fell short of ``limit`` from the global corpus.

    EAG exemplars need only be style/structure referenceable, not topically
    related (goal 4: "不是一定要相关，只要行文的风格，结构可以参考就行"), so a
    topic poor in admissible papers can still anchor on high-grade papers from
    elsewhere rather than degrading to an empty pool.
    """
    if not limit:
        return existing
    need = int(limit) - len(existing)
    if need <= 0:
        return existing
    seen = {int(s["id"]) for s in existing}
    rows = conn.execute(
        "SELECT p.id,p.title,p.abstract,p.venue,p.year,p.affiliations,"
        "COALESCE(p.citation_count,0) AS citation_count "
        "FROM papers p ORDER BY citation_count DESC LIMIT 2000"
    ).fetchall()
    fresh: list[dict[str, Any]] = []
    for r in rows:
        if int(r["id"]) in seen:
            continue
        source = _build_source(conn, r)
        if _source_admissible(source, min_tier_score, family):
            fresh.append(source)
    return existing + _rank_sources(fresh)[:need]


def _fetch_sources(
    db,
    topic_id,
    paper_ids,
    limit,
    min_tier_score: int = 0,
    family: str | None = None,
    same_domain: bool = False,
) -> list[dict[str, Any]]:
    """Fetch exemplar source papers, ranked top-institutions first then tier.

    ``family`` (when given) replaces the tier gate with exemplar-family
    admission: "nature_science" | "ccfa" | "any" — prose exemplars come from
    the family matching the TARGET venue. Without a family, ``min_tier_score``
    (venue_tier_score scale) hard-filters sources below the requested venue
    grade (CCF-A* = 100, CCF-A = 90, CAS-Q1 = 85). When the topic itself is
    poor in admissible papers, the pool is filled from the global corpus
    (exemplars need only style/structure reference).
    """
    if db is None or (topic_id is None and not paper_ids):
        return []
    conn = db.connect()
    try:
        # Widen the window so the venue/institution filter still has room to
        # yield ``limit`` sources (a large share of the corpus has unknown venue).
        fetch_limit = int(limit) * 8 if limit else 0
        cols = "p.id,p.title,p.abstract,p.venue,p.year,p.affiliations"
        if paper_ids:
            ph = ",".join("?" * len(paper_ids))
            rows = conn.execute(
                f"SELECT {cols} FROM papers p WHERE p.id IN ({ph})",
                list(paper_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {cols},COALESCE(p.citation_count,0) AS citation_count "
                "FROM papers p JOIN paper_topics pt ON p.id=pt.paper_id "
                "WHERE pt.topic_id=? ORDER BY citation_count DESC LIMIT ?",
                (topic_id, int(fetch_limit)),
            ).fetchall()
        out = _rank_sources([_build_source(conn, r) for r in rows])
        # Explicit IDs override tier, never a bound discipline. No global substitution.
        if paper_ids:
            if family is not None:
                out = [s for s in out if _venue_matches_family(s["venue"], family)]
            return out[: int(limit)] if limit else out
        if family is not None or (min_tier_score and int(min_tier_score) > 0):
            out = [s for s in out if _source_admissible(s, min_tier_score, family)]
        # Relaxing the grade says what the topic's own papers must clear, not how good a
        # borrowed exemplar has to be — form is borrowed precisely because the topic has
        # none worth copying. Tying the fill to the relaxed grade left the relaxed retry
        # weaker than the strict pass it was retrying: A0093's fourteen own papers, a
        # retraction notice among them, were judged and all rejected with nothing to fall
        # back on, and the stage parked. The fill keeps the standing high bar.
        # The domain register must come from the field itself: borrowing a
        # high-grade paper from another domain would import foreign jargon.
        if len(out) < int(limit or 0) and not same_domain:
            out = _global_high_tier_fill(
                conn,
                out,
                limit,
                max(int(min_tier_score or 0), _EXEMPLAR_TIER_FLOOR),
                family,
            )
        return out[: int(limit)] if limit else out
    finally:
        conn.close()


def _figure_evidence(db, paper_id: int) -> str:
    """Figure-form evidence (PDF captions + optional VLM analyses) for one paper."""
    if db is None or not paper_id:
        return ""
    try:
        from research_harness.visualization.result_figure_refs import (
            figure_evidence_text,
        )

        return figure_evidence_text(db, paper_id)
    except Exception:
        return ""


def _architecture_evidence(db, paper_id: int) -> str:
    """Architecture-figure STYLE evidence (arch captions + optional VLM form)."""
    if db is None or not paper_id:
        return ""
    try:
        from research_harness.visualization.result_figure_refs import (
            architecture_evidence_text,
        )

        return architecture_evidence_text(db, paper_id)
    except Exception:
        return ""


def _coerce_units(units) -> list[ExemplarUnit]:
    out: list[ExemplarUnit] = []
    for u in units or []:
        if isinstance(u, ExemplarUnit):
            out.append(u)
        elif isinstance(u, dict):
            form = u.get("form")
            out.append(
                ExemplarUnit(
                    unit_type=str(u.get("unit_type", "")),
                    source_paper_id=int(u.get("source_paper_id", 0) or 0),
                    source_title=str(u.get("source_title", "")),
                    venue=str(u.get("venue", "")),
                    venue_tier=str(u.get("venue_tier", "")),
                    quality=_num(u.get("quality")),
                    form=form if isinstance(form, dict) else {},
                    summary=str(u.get("summary", "")),
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Deterministic anti-plagiarism gate (form-not-content)                       #
# --------------------------------------------------------------------------- #


def _ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    t = re.findall(r"\w+", (text or "").lower())
    return (
        {tuple(t[i : i + n]) for i in range(len(t) - n + 1)} if len(t) >= n else set()
    )


def _max_ngram_overlap(
    draft: str, exemplars: list[str], n: int = 8
) -> tuple[float, str]:
    d = _ngrams(draft, n)
    if not d:
        return 0.0, ""
    ex: set[tuple[str, ...]] = set()
    for e in exemplars:
        ex |= _ngrams(e, n)
    inter = d & ex
    if not inter:
        return 0.0, ""
    return len(inter) / len(d), " ".join(next(iter(inter)))


# --------------------------------------------------------------------------- #
# First-impression quality critique (goal 1)                                   #
# --------------------------------------------------------------------------- #
# The venue_prescription quality targets drive deterministic per-section checks
# inside the generate loop. Only dimensions decidable on a single section draft
# are enforced here (title/abstract word bands, paragraph development); the
# llm/vlm and full-document dimensions (figure_density, aesthetics, palette,
# layout, page_fill, main_appendix) are reported as *deferred* — the downstream
# discriminator enforces them on the compiled paper, not on a partial draft.

_DETERMINISTIC = "deterministic"
_QUALITY_BAND_DIMS = {"title", "abstract"}


def _coerce_quality_targets(quality_targets) -> list[dict[str, Any]]:
    """Accept a serialized venue prescription, a bare list, or a single target."""
    if quality_targets is None:
        return []
    if isinstance(quality_targets, dict):
        if isinstance(quality_targets.get("quality_targets"), (list, tuple)):
            quality_targets = quality_targets["quality_targets"]
        else:
            quality_targets = [quality_targets]
    if not isinstance(quality_targets, (list, tuple)):
        return []
    return [t for t in quality_targets if isinstance(t, dict)]


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def _sentences(paragraph: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", paragraph.strip()) if s.strip()]


def _quality_critique(
    draft: str, quality_targets, section: str | None = None
) -> dict[str, Any]:
    """Deterministic first-impression checks on one drafted section.

    Returns ``{"passed", "failures", "deferred", "checks"}``. ``failures`` are
    deterministic misses that should trigger a revision; ``deferred`` are
    dimensions the discriminator checks later (never a generator-side block).
    """
    targets = _coerce_quality_targets(quality_targets)
    sec = (section or "").strip().lower().replace(" ", "_")
    text = str(draft or "")
    wc = _word_count(text)
    failures: list[dict[str, Any]] = []
    deferred: list[str] = []
    checks: list[dict[str, Any]] = []
    for t in targets:
        dim = str(t.get("dimension", ""))
        mtype = str(t.get("metric_type", ""))
        target = t.get("target") if isinstance(t.get("target"), dict) else {}
        remediation = str(t.get("remediation", ""))
        if mtype != _DETERMINISTIC:
            deferred.append(dim)
            continue
        if dim in _QUALITY_BAND_DIMS:
            if sec != dim:  # title band applies to a title draft, etc.
                deferred.append(dim)
                continue
            band = target.get("band")
            if not isinstance(band, (list, tuple)) or len(band) != 2:
                deferred.append(dim)
                continue
            lo, hi = int(band[0]), int(band[1])
            ok = lo <= wc <= hi
            checks.append(
                {"dimension": dim, "passed": ok, "observed": wc, "target": target}
            )
            if not ok:
                failures.append(
                    {
                        "dimension": dim,
                        "observed": wc,
                        "target": target,
                        "remediation": remediation,
                    }
                )
        elif dim == "paragraph_length":
            if sec in {"abstract", "title"} or not text:
                deferred.append(dim)
                continue
            paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
            thin = [
                p.strip()[:80].replace("\n", " ") + "…"
                for p in paragraphs
                if len(_sentences(p)) <= 2 and len(p.split()) > 15
            ]
            ok = not thin
            checks.append(
                {
                    "dimension": dim,
                    "passed": ok,
                    "observed": {"thin_paragraphs": len(thin)},
                    "target": target,
                }
            )
            if not ok:
                failures.append(
                    {
                        "dimension": dim,
                        "observed": f"{len(thin)} thin paragraph(s)",
                        "target": target,
                        "remediation": remediation,
                    }
                )
        else:
            # figure_density, palette, layout, page_fill, main_appendix —
            # full-document / compiled-PDF concerns, not decidable per section.
            deferred.append(dim)
    return {
        "passed": not failures,
        "failures": failures,
        "deferred": deferred,
        "checks": checks,
    }


def _target_state_string(quality_targets) -> str:
    """Render the writing-quality contract as a compact directive for the drafter."""
    targets = _coerce_quality_targets(quality_targets)
    if not targets:
        return ""
    lines = []
    for t in targets:
        dim = str(t.get("dimension", "?"))
        mtype = str(t.get("metric_type", "?"))
        target = t.get("target") if isinstance(t.get("target"), dict) else {}
        if isinstance(target, dict) and "band" in target:
            spec = (
                f"{target['band'][0]}-{target['band'][1]} words"
                if dim in _QUALITY_BAND_DIMS
                else f"band {target['band']}"
            )
        elif isinstance(target, dict) and "value" in target:
            spec = f">= {target['value']}"
        else:
            spec = str(target)
        lines.append(f"- {dim}: {spec} ({mtype})")
    return "Writing-quality contract — meet every entry:\n" + "\n".join(lines) + "\n\n"


def _quality_revision_hint(qcrit: dict[str, Any]) -> str:
    """Turn deterministic quality failures into a concrete revision directive."""
    failures = qcrit.get("failures") or []
    if not failures:
        return ""
    parts = ["IMPORTANT: your draft fails the venue writing-quality contract:"]
    for f in failures:
        parts.append(
            f"- {f['dimension']}: observed {f.get('observed')} vs target {f.get('target')} — "
            f"{f.get('remediation', '')}"
        )
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------------- #
# Prompts (inline; form-only, strict JSON)                                     #
# --------------------------------------------------------------------------- #

# Chart vocabulary shared with the renderer's PANEL_CHARTS registry
# (research_harness.visualization.experiment_figures); a test guards the match.
RESULT_FIGURE_CHART_VOCABULARY = (
    "grouped_bar",
    "heatmap",
    "radar",
    "pareto_scatter",
    "sensitivity_line",
    "line",
    "scatter",
    "box",
    "violin",
    "bar",
    "forest",
    "hist",
    "stacked_bar",
    "km_survival",
    "volcano",
    "image",
    "qualitative_grid",
)
_CHART_VOCAB = "|".join(RESULT_FIGURE_CHART_VOCABULARY)

RESULT_FIGURE_STYLE_PROFILES = (
    "stem_conference",
    "nature_family",
    "social_humanities",
    "biomed_omics",
)
_STYLE_VOCAB = "|".join(RESULT_FIGURE_STYLE_PROFILES)

# Full-paper figure-contract roles (empirically derived from 152 A-venue papers)
# and their default execution pipeline. Deterministic roles render from records;
# generative roles route to figure_generate (illustration route); latex roles are
# prompt/code/transcript listings; external_asset roles wrap maps/micrographs.
FIGURE_SUITE_ROLES = (
    "framing",
    "method",
    "study_design",
    "data",
    "results",
    "results_sensitivity",
    "analysis",
    "qualitative",
    # finish_rulebook_v0.1 P0: case-trace exhibit seats (generative plates)
    "case_exhibit",
    "failure_gallery",
    "spatial_map",
    "theory",
    "survey_meta",
    "listing",
)
_ROLE_VOCAB = "|".join(FIGURE_SUITE_ROLES)
ROLE_PIPELINE = {
    "framing": "generative",
    "method": "generative",
    "study_design": "generative",
    "theory": "generative",
    "survey_meta": "generative",
    "case_exhibit": "generative",
    "failure_gallery": "generative",
    "data": "deterministic",
    "results": "deterministic",
    "results_sensitivity": "deterministic",
    "analysis": "deterministic",
    "qualitative": "deterministic",
    "spatial_map": "external_asset",
    "listing": "latex",
}
FIGURE_SUITE_PAPER_TYPES = ("empirical", "survey")
_PAPER_TYPE_VOCAB = "|".join(FIGURE_SUITE_PAPER_TYPES)

# unit_type aliases: result_figure_suite (S-series pilot name) → figure_suite
_UNIT_ALIASES = {"result_figure_suite": "figure_suite"}


def _canon_unit(unit_type: str) -> str:
    u = str(unit_type or "")
    return _UNIT_ALIASES.get(u, u)


def _appendix_plan_rule() -> str:
    """Finish-rulebook P0 clause injected into skeleton/figure_suite plans."""
    try:
        from research_harness._workflow.execution.finish_form_contract import (
            appendix_plan_prompt_clause,
        )

        return appendix_plan_prompt_clause()
    except Exception:
        return (
            "appendix_plan MUST use controlled tokens only: extended_methods|"
            "extended_tables|extra_figures|case_study_trace|failure_gallery|"
            "prompt_or_protocol_export|instrument_codebook|reporting_checklist|"
            "proofs|robustness_checks|implementation_details|hyperparams. "
            "Mechanism papers MUST include case_study_trace."
        )


def _normalize_plan_appendix(
    plan: dict[str, Any], target_content: str
) -> dict[str, Any]:
    """Normalize appendix_plan tokens; seat case_study_trace for mechanism papers."""
    if not isinstance(plan, dict):
        return plan
    try:
        from research_harness._workflow.execution.finish_form_contract import (
            enrich_appendix_plan_for_domain,
            infer_domain_family,
            looks_like_mechanism_paper,
        )
    except Exception:
        return plan
    raw = plan.get("appendix_plan") or plan.get("appendix_components") or []
    if not isinstance(raw, list):
        raw = [raw] if raw else []
    target = str(target_content or "")
    norm = enrich_appendix_plan_for_domain(
        raw,
        infer_domain_family(target),
        mechanism=looks_like_mechanism_paper(target),
        text=target,
    )
    plan = dict(plan)
    plan["appendix_plan"] = norm
    # Drop free-form twin key if present — controlled list is canonical.
    if "appendix_components" in plan and plan.get("appendix_components") != norm:
        plan["appendix_components"] = list(norm)
    return plan


_CURATE_PROMPTS = {
    "skeleton": (
        "You are curating a reference exemplar. From the paper below, extract its SECTION "
        "ARCHITECTURE as abstracted FORM only (never verbatim text).\n"
        "Paper: {title} ({venue}).\nText:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"sections":[{{"name":"...","role":"...",'
        '"approx_share":0.0,"key_moves":["..."]}}],"n_sections":0,'
        '"appendix_components":["tokens from controlled vocab: extended_methods|'
        "extended_tables|extra_figures|case_study_trace|failure_gallery|"
        "prompt_or_protocol_export|instrument_codebook|reporting_checklist|"
        'proofs|robustness_checks|implementation_details|hyperparams"]}},'
        '"quality":0,'
        '"summary":"..."}}. quality 0-10: high only if a clean, complete, transferable '
        "skeleton is recoverable; low if the text is too sparse. Prefer recording "
        "case_study_trace when the paper has an auditable walkthrough/vignette/qual "
        "exhibit. No verbatim sentences."
    ),
    "intro_arc": (
        "You are curating a reference exemplar. From the paper below, extract its INTRODUCTION "
        "ARC as a paragraph-by-paragraph, sentence-by-sentence rhetorical move map "
        "(abstracted FORM only, never the paper's wording).\n"
        "Paper: {title} ({venue}).\nText:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"paragraphs":[{{"role":"establish-importance|'
        'prior-work|gap|this-work|contributions|roadmap|mixed",'
        '"sentences":[{{"move":"context-claim|evidence-cite|trend|prior-approach|'
        "limitation|gap-signal|turn|proposal|mechanism|significance|contribution|"
        'result-preview|roadmap","gist":"the sentence\'s rhetorical job, not its '
        'wording"}}],"n_sentences":0}}],"n_paragraphs":0,"hook_type":"...",'
        '"transition_style":"how paragraphs hand off to each other"}},'
        '"quality":0,"summary":"..."}}. quality 0-10: high only when the text '
        "contains the paper's actual introduction prose AND a clear "
        "gap->contribution arc is recoverable at sentence level; score below 6 "
        "for abstract-only or notes-only evidence. No verbatim text."
    ),
    "abstract": (
        "You are curating a reference exemplar. Extract the ABSTRACT element order (FORM only).\n"
        "Paper: {title} ({venue}).\nText:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"elements":["problem","method","validation",'
        '"result","impact"],"n_sentences_est":0}},"quality":0,"summary":"..."}}.'
    ),
    # L1 section arcs (EAG-Ladder): move-map contracts per major section,
    # mirroring intro_arc. FORM only — the move vocabulary is per-section.
    "related_work_arc": (
        "You are curating a reference exemplar. From the paper below, extract its RELATED WORK "
        "ARC as an ordered move-map (abstracted FORM only, never the paper's wording or "
        "citations).\n"
        "Paper: {title} ({venue}).\nText:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"organization":"thematic|chronological|'
        'taxonomy|problem-driven|method-family","moves":[{{"move":"group-intro|'
        'strand-survey|strand-contrast|gap-bridge|positioning","gist":"abstract role, '
        'not wording"}}],"n_moves":0,"positioning_style":"contrast-per-strand|'
        'final-positioning-paragraph|inline-throughout"}},"quality":0,"summary":"..."}}. '
        "quality 0-10: high only for a clearly organized survey->positioning arc. No verbatim text."
    ),
    "method_arc": (
        "You are curating a reference exemplar. From the paper below, extract its METHOD "
        "SECTION ARC as an ordered move-map (abstracted FORM only, never the paper's "
        "method content, names, or equations).\n"
        "Paper: {title} ({venue}).\nText:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"exposition":"top-down-overview-first|'
        'bottom-up-components-first|problem-formulation-first|pipeline-walkthrough",'
        '"moves":[{{"move":"problem-setup|notation|overview|component|mechanism-intuition|'
        'formalization|complexity|design-rationale","gist":"abstract role, not content"}}],'
        '"n_moves":0,"intuition_balance":"formal-first|intuition-first|interleaved"}},'
        '"quality":0,"summary":"..."}}. quality 0-10: high only for a clean, '
        "transferable exposition structure. No verbatim text."
    ),
    "experiment_arc": (
        "You are curating a reference exemplar. From the paper below, extract its "
        "EXPERIMENTS/RESULTS ARC as an ordered move-map (abstracted FORM only, never the "
        "paper's datasets, numbers, or findings).\n"
        "Paper: {title} ({venue}).\nText:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"moves":[{{"move":"setup|datasets|baselines|'
        'metrics|main-results|ablation|sensitivity|analysis|qualitative|efficiency",'
        '"gist":"abstract role, not content"}}],"n_moves":0,"claim_binding":'
        '"each-block-answers-a-question|results-then-discussion|hypothesis-driven",'
        '"analysis_depth":"reporting-only|mechanistic-analysis|error-analysis-included"}},'
        '"quality":0,"summary":"..."}}. quality 0-10: high only when the experiment '
        "narrative structure is clearly recoverable. No verbatim text."
    ),
    "discussion_arc": (
        "You are curating a reference exemplar. From the paper below, extract its "
        "DISCUSSION/LIMITATIONS/CONCLUSION ARC as an ordered move-map (abstracted FORM "
        "only, never the paper's claims or wording).\n"
        "Paper: {title} ({venue}).\nText:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"moves":[{{"move":"result-synthesis|'
        "implication|comparison-to-prior|limitation|threat-to-validity|future-work|"
        'takeaway","gist":"abstract role, not wording"}}],"n_moves":0,'
        '"limitation_stance":"honest-specific|generic-brief|integrated-with-results"}},'
        '"quality":0,"summary":"..."}}. quality 0-10: high only for an honest, '
        "structured closing arc. No verbatim text."
    ),
    # L2 (EAG-Ladder): paragraph-level rhetorical craft, below the section arcs.
    "paragraph_moves": (
        "You are curating a reference exemplar. From the paper below, extract its "
        "PARAGRAPH-LEVEL CRAFT profile as abstracted FORM only — how paragraphs are "
        "internally organized — never the paper's wording, claims, or content.\n"
        "Paper: {title} ({venue}).\nText:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"archetypes":[{{"role":"claim-development|'
        'contrast|setup-payoff|evidence-synthesis|definition-then-use|problem-solution",'
        '"move_seq":["topic-claim","evidence","interpretation","link-forward"],'
        '"topic_sentence":"assertive-claim|question|transition-anchored|scope-setting"}}],'
        '"transition_style":"explicit-connectives|semantic-echo|enumerative|minimal",'
        '"sentences_per_para":"3-5|5-8|varied"}},"quality":0,"summary":"..."}}. '
        "quality 0-10: high only when paragraph discipline is clearly recoverable. "
        "No verbatim text."
    ),
    "style": (
        "You are curating a reference exemplar. Extract a STYLE profile of the paper's "
        "running prose (FORM only, never wording).\n"
        "Paper: {title} ({venue}).\nText:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"sentence_length":"short|medium|long|varied",'
        '"sentence_rhythm":"how long and short sentences alternate",'
        '"hedging":"low|medium|high","voice":"active|mixed|passive",'
        '"connective_density":"low|medium|high",'
        '"citation_integration":"narrative|parenthetical|mixed",'
        '"paragraph_openers":"how paragraphs typically open (form, not wording)",'
        '"tone":"..."}},"quality":0,"summary":"..."}}. quality 0-10: high only '
        "when the text contains the paper's actual running prose; score below 6 "
        "for abstract-only or notes-only evidence."
    ),
    "figure_suite": (
        "You are curating a reference exemplar for WHOLE-PAPER FIGURE design. From the "
        "figure/table captions and notes below, extract the paper's FIGURE SUITE as "
        "abstracted FORM only (per-figure role, chart archetypes, panel composition, "
        "narrative order, discipline style) — never the paper's data, numbers, or caption "
        "wording.\n"
        "Paper: {title} ({venue}).\nEvidence:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"paper_type":"' + _PAPER_TYPE_VOCAB + '",'
        '"figures":[{{"role":"'
        + _ROLE_VOCAB
        + '","charts":["'
        + _CHART_VOCAB
        + '"],"n_panels":0,"composition":"e.g. 1x2"}}],"narrative_order":["<role>"],'
        '"style_traits":{{"palette":"...","annotation_density":"low|medium|high",'
        '"panel_labels":"a|(a)|A|none","error_bars":true}},"n_figures":0,'
        '"tables":[{{"role":"main-results|ablation|dataset-stats|comparison|'
        'hyperparams|robustness","gist":"what angle this table shows, not its '
        'numbers"}}],"appendix_components":["e.g. extended-tables|extra-figures|'
        'proofs|implementation-details"]}},'
        '"quality":0,"summary":"..."}}. Role guide: framing=Fig1 problem/motivation; '
        "method=architecture/pipeline; study_design=protocol/CONSORT/flowchart; "
        "data=dataset stats/distribution; results=benchmark/ablation/curves; "
        "results_sensitivity=hyperparameter/scale sweeps; analysis=t-SNE/attention/SHAP/"
        "error/calibration; qualitative=case showcase/prediction-vs-truth; "
        "spatial_map=study-area/choropleth/GWR maps; theory=causal DAG/state diagram/proof; "
        "survey_meta=PRISMA/taxonomy/field-trend; listing=prompt/code/transcript. "
        "quality 0-10: high only if captions clearly reveal figure structure."
    ),
    "figure": (
        "You are curating a VISUAL STYLE exemplar from a published paper's ARCHITECTURE/"
        "METHOD figure. From the evidence below, extract its VISUAL FORM as abstracted "
        "style only (layout, palette, geometry, composition) — NEVER the paper's method, "
        "components, or labels.\n"
        "Paper: {title} ({venue}).\nEvidence:\n{text}\n\n"
        'Return ONLY JSON: {{"form":{{"layout_archetype":"left-to-right pipeline|'
        "layered stack|radial hub|cyclic loop|swimlane|matrix grid|hourglass|control-plane "
        'overlay|split comparison","palette_strategy":"restrained monochrome + accent|'
        'cool technical|warm editorial|grayscale + highlights|domain palette",'
        '"geometry_language":"rounded modules|sharp blocks|thin-line blueprint|layered '
        'slabs|node-link graph|annotated cards","depth_model":"flat|paper cutout|'
        'isometric|blueprint","composition":"one sentence on zones/flow, NOT the '
        'method","label_density":"low|medium|high"}},"quality":0,"summary":"one '
        'sentence on the visual style, NOT the content"}}. quality 0-10: high only if the '
        "evidence clearly reveals a well-composed architecture figure. Never name the "
        "paper's specific components."
    ),
}

# Surface-prose screen appended to every prose-unit curate prompt. The single
# selection target (user mandate): the exemplar's VISIBLE writing must be at
# Nature/Science/top-CCF-A level — experimental soundness is deliberately out
# of scope for exemplar admission.
_PROSE_SCREEN = (
    "\n\nAdditionally rate prose_quality 0-10 and include it in the JSON as "
    '"prose_quality". Judge ONLY the surface writing craft visible in the text '
    "— rhetorical control, sentence-to-sentence logical flow, precision, "
    "professional register, and how the study's narrative (including its "
    "experimental design and results exposition) is structured and argued — "
    "against the bar of Nature/Science/top-CCF-A prose. Deliberately IGNORE "
    "whether the reported numbers hold up or the experiments are actually "
    "sound: a flawed study written and argued superbly scores high; a solid "
    "study written poorly scores low."
)

_RETRIEVE_PROMPT = (
    "Select the best reference exemplars to guide the {unit_type} of a NEW paper.\n"
    "PRINCIPLE: structure/intent match DOMINATES topic match — a same-FORM exemplar from a "
    "different topic beats a same-TOPIC exemplar with a different form.\n"
    "Target paper content: {target}\nTarget intent: {intent}\n"
    "Candidate exemplars (index: form):\n{listing}\n\n"
    'Return ONLY JSON: {{"ranking":[indices best-first],"rationale":"one sentence"}}. '
    "At most {k} indices."
)

_PLAN_PROMPTS = {
    "intro_arc": (
        "Plan the INTRODUCTION of THIS paper by analogy to the exemplar arcs. Use ONLY their "
        "structural FORM (paragraph roles and sentence-level move sequences) — NEVER their "
        "wording, claims, or examples. Re-instantiate every move with THIS paper's own "
        "content.\n"
        "THIS paper (content/contributions): {target}\nExemplar forms: {forms}\n\n"
        'Return ONLY JSON: {{"plan":{{"paragraphs":[{{"role":"...","intent":"one sentence '
        'on this paragraph\'s job","sentences":[{{"move":"...","instruction":"what THIS '
        "paper's sentence should accomplish here, in your own words, grounded in the "
        'target content"}}]}}],"n_paragraphs":0,"hook_directive":"how the opening should '
        'hook, re-instantiated for THIS paper","transition_directive":"how consecutive '
        'paragraphs should hand off","notes":"..."}}}}. Copy no phrase from the exemplars.'
    ),
    "style": (
        "Distill a STYLE CARD for THIS paper from the exemplar style profiles below. "
        "Transfer FORM only — never any exemplar wording. The card guides every "
        "section's prose.\n"
        "THIS paper (content/venue intent): {target}\nExemplar forms: {forms}\n\n"
        'Return ONLY JSON: {{"plan":{{"sentence_length":"...","sentence_rhythm":"...",'
        '"voice":"...","hedging":"...","connective_density":"...",'
        '"citation_integration":"...","paragraph_openers":"...","register":"...",'
        '"dos":["concrete prose directives"],"donts":["concrete prose prohibitions"]}}}}.'
    ),
    "skeleton": (
        "Plan the SECTION ARCHITECTURE of THIS paper by analogy to the exemplar skeletons. Use "
        "ONLY the structural FORM (section roles/order) — never exemplar wording.\n"
        "SECTION-ORDER RULE: if THIS paper is a pure computer-science paper, "
        "order the main sections in the CCF-A conventional arc (introduction -> "
        "related work -> method -> experiments/results -> discussion/conclusion) "
        "REGARDLESS of the target venue, while still including every "
        "venue-mandated section/declaration (e.g. data availability, methods "
        "presence, abstract constraints). Otherwise follow the target-venue "
        "family's conventional order as shown by the exemplars.\n"
        "THIS paper (content/contributions): {target}\nExemplar forms: {forms}\n\n"
        'Return ONLY JSON: {{"plan":{{"sections":[{{"name":"...","role":"...",'
        '"approx_share":0.0,"key_moves":["..."]}}],'
        '"appendix_plan":["controlled tokens only — see appendix vocabulary rule"],'
        '"notes":"..."}}}}. ' + _appendix_plan_rule()
    ),
    "figure_suite": (
        "Design THIS paper's WHOLE-PAPER FIGURE SUITE by analogy to the exemplar suite "
        "forms below. Transfer FORM only (which figures, their roles, chart choices, "
        "multi-panel composition, narrative order, style) — never exemplar data or "
        "captions. For DETERMINISTIC figures (data/results/results_sensitivity/analysis/"
        "qualitative), plan ONLY panels the available experiment records can feed (see the "
        "record inventory in the target content); the renderer skips unfed panels and NEVER "
        "invents data. GENERATIVE figures (framing/method/study_design/theory/survey_meta/"
        "case_exhibit/failure_gallery) need no records — give title+purpose. LATEX figures "
        "(listing) are prompt/code blocks. EXTERNAL figures (spatial_map) wrap a supplied asset.\n"
        "CASE-EXHIBIT RULE: for mechanism/method/system/model/clinical-AI papers include at "
        "least one figure with role=case_exhibit (or failure_gallery) in main or appendix — "
        "an auditable walkthrough/vignette/error plate, not a metric wall.\n"
        "THIS paper (content + record inventory): {target}\nExemplar suite forms: {forms}\n\n"
        'Return ONLY JSON: {{"plan":{{"paper_type":"' + _PAPER_TYPE_VOCAB + '",'
        '"style_profile":"' + _STYLE_VOCAB + '","figures":[{{"figure_id":"fig:...",'
        '"role":"' + _ROLE_VOCAB + '","pipeline":"deterministic|generative|latex|'
        'external_asset","placement":"main|appendix","title":"...","purpose":'
        '"(generative only) what it must show","composition":"RxC","caption_skeleton":'
        '"(a) ...; (b) ...","panels":[{{"panel_id":"a","chart":"'
        + _CHART_VOCAB
        + '","message":"one sentence","record_filter":{{}},"x_label":"",'
        '"y_label":""}}]}}],"narrative_order":["fig:..."],'
        '"tables":[{{"table_id":"tab:...","role":"main-results|ablation|'
        'dataset-stats|comparison|hyperparams|robustness","placement":"main|appendix",'
        '"purpose":"what angle it shows","column_sketch":"e.g. method|dataset|'
        'metric1|metric2"}}],"appendix_plan":["controlled tokens only"],'
        '"notes":"..."}}}}. '
        + _appendix_plan_rule()
        + " Choose style_profile by the target venue's discipline (biomed_omics for "
        "survival/expression/omics papers); set pipeline from role; use record_filter "
        "(column=value equality) to bind each deterministic panel to its data; 2-4 panels "
        "per figure beats one chart per figure when the exemplars compose panels; put "
        "supplementary figures in placement=appendix. Mirror the exemplars' table "
        "suite (multiple complementary angles: main results + ablation + robustness "
        "when the exemplars do so) and their appendix composition — a first-glance-"
        "rich paper carries a full evidence surface, not one results table."
    ),
    "figure": (
        "Design a VISUAL STYLE ANCHOR for THIS paper's ARCHITECTURE/METHOD figure by "
        "analogy to the exemplar architecture-figure forms below. Transfer VISUAL FORM "
        "ONLY (layout archetype, palette, geometry, depth, composition) — NEVER the "
        "exemplars' method, components, or labels. THIS paper supplies its own method "
        "content; you only choose how it should LOOK, standing on the shoulders of "
        "well-composed published figures.\n"
        "THIS paper (method/contributions): {target}\nExemplar figure forms: {forms}\n\n"
        'Return ONLY JSON: {{"plan":{{"style_anchor":{{"layout_archetype":"...",'
        '"palette_strategy":"...","geometry_language":"...","depth_model":"...",'
        '"composition":"one sentence on zones and flow for THIS method",'
        '"typography_mood":"..."}},"rationale":"why this form suits THIS method '
        '(one sentence)","avoid":["generic AI decoration","..."]}}}}. Choose an '
        "archetype that fits THIS method's structure; do not copy an exemplar's specific "
        "modules or wording."
    ),
    "_generic": (
        "Plan THIS paper's artifact by structural analogy to the exemplar forms below; transfer "
        "FORM not CONTENT.\nTHIS paper: {target}\nExemplar forms: {forms}\n\n"
        'Return ONLY JSON: {{"plan":{{}}}}.'
    ),
}

# L1 section-arc plan prompts share one shape: re-instantiate the exemplar
# move sequence with THIS paper's content, one instruction per move.
_ARC_PLAN_TEMPLATE = (
    "Plan the {section_label} of THIS paper by analogy to the exemplar arcs. Use ONLY "
    "their structural FORM (organization + move sequence) — NEVER their wording, claims, "
    "citations, or data. Re-instantiate each move with THIS paper's own content.\n"
    "THIS paper (content/contributions): {{target}}\nExemplar forms: {{forms}}\n\n"
    'Return ONLY JSON: {{{{"plan":{{{{"moves":[{{{{"move":"...","instruction":"what '
    'THIS paper should say here, in your own words, grounded in the target content"}}}}],'
    '"n_paragraphs":0,"notes":"..."}}}}}}}}. Copy no phrase from the exemplars.'
)

_PLAN_PROMPTS.update(
    {
        "related_work_arc": _ARC_PLAN_TEMPLATE.format(
            section_label="RELATED WORK section"
        ),
        "method_arc": _ARC_PLAN_TEMPLATE.format(section_label="METHOD section"),
        "experiment_arc": _ARC_PLAN_TEMPLATE.format(
            section_label="EXPERIMENTS/RESULTS section"
        ),
        "discussion_arc": _ARC_PLAN_TEMPLATE.format(
            section_label="DISCUSSION/LIMITATIONS/CONCLUSION section"
        ),
        "paragraph_moves": (
            "Distill a PARAGRAPH CRAFT CONTRACT for THIS paper from the exemplar "
            "paragraph-craft forms below. Transfer FORM only (paragraph archetypes, "
            "internal move sequences, topic-sentence discipline, transition style) — never "
            "any exemplar wording or content. The contract guides EVERY section's "
            "paragraphs.\n"
            "THIS paper (content/contributions): {target}\nExemplar forms: {forms}\n\n"
            'Return ONLY JSON: {{"plan":{{"templates":[{{"role":"...","move_seq":'
            '["..."],"topic_sentence":"one directive sentence in your own words"}}],'
            '"transition_directive":"how consecutive paragraphs should link",'
            '"sentences_per_para":"...","notes":"..."}}}}. Copy no phrase from the '
            "exemplars."
        ),
    }
)


# New move contracts share the existing unit/form storage and drafting loop.
for _move_unit, _label in (
    ("abstract_moves", "ABSTRACT"),
    ("intro_moves", "INTRODUCTION"),
    ("discussion_moves", "DISCUSSION"),
):
    _CURATE_PROMPTS[_move_unit] = (
        f"Extract the {_label} rhetorical moves from the actual section below, in order. "
        "Record each sentence action, its observed word range, section length band, and "
        "opening actions incompatible with this venue register. No fixed formula, wording, "
        "claims or numbers from the source may be transferred.\n"
        "Paper: {title} ({venue}).\nSection evidence:\n{text}\n"
        'Return ONLY JSON: {{"form":{{"moves":[{{"move":"...","sentence_action":"...",'
        '"word_range":[1,2]}}],"length_band_words":[1,2],"opening_forbidden_moves":[]}},'
        '"quality":0,"prose_quality":0,"summary":"..."}}. Scores use 0-10.'
    )
    _PLAN_PROMPTS[_move_unit] = (
        f"Plan THIS paper's {_label} from the supplied same-discipline move contracts. "
        "Preserve element order, sentence actions, length bands and opening restrictions. "
        "Transfer FORM only, never source wording, claims or data; use only the target evidence.\n"
        "THIS paper: {target}\nExemplar forms: {forms}\n"
        'Return ONLY JSON: {{"plan":{{"moves":[{{"move":"...","sentence_action":"...",'
        '"instruction":"what this paper should say","word_range":[1,2]}}],'
        '"length_band_words":[1,2],"opening_forbidden_moves":[]}}}}.'
    )


# --------------------------------------------------------------------------- #
# Primitives                                                                   #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Track A — domain register (canonical terminology of the target field)        #
# --------------------------------------------------------------------------- #
# FORM units teach *how a paper argues* and are borrowed across topics. The
# register teaches *what the field calls things*: task, input and output names,
# metric names, standard terms, hedges and avoided claims. Expert readers judge
# an author by this vocabulary, so it is reused verbatim from published papers
# of the same field and never invented by the drafting model.

_REGISTER_FIELDS = (
    "task_names",
    "input_names",
    "output_names",
    "terms",
    "metric_names",
    "phrase_templates",
    "hedges",
    "avoid",
)

_CURATE_PROMPTS["domain_register"] = (
    "You are extracting the DOMAIN REGISTER of a published paper: the canonical, field-standard "
    "vocabulary an expert in this area would expect. Copy surface forms EXACTLY as the paper "
    "writes them (lowercase is fine). Include only expressions that are standard in the field, "
    "never this paper's own coinages, system names or dataset names.\n"
    "Paper: {title} ({venue})\nText:\n{text}\n\n"
    'Return ONLY JSON: {{"quality": 0-10 (how clearly the text exposes field-standard '
    'terminology), "form": {{"task_names": [], "input_names": [], "output_names": [], '
    '"terms": [], "metric_names": [], "phrase_templates": ["abstract templates with X/Y '
    'placeholders"], "hedges": [], "avoid": ["claims or phrasings the paper explicitly '
    'warns against"], "synonyms": {{"non-canonical phrasing": "canonical term"}}}}, '
    '"summary": "one sentence"}}'
)


def _norm_term(t: Any) -> str:
    return re.sub(r"\s+", " ", str(t or "").strip().lower()).strip(" .;:,")


def build_register_lexicon(units, min_support: int = 2) -> dict[str, Any]:
    """Aggregate per-paper domain_register units into one canonical lexicon.

    A term enters the lexicon when at least ``min_support`` distinct papers use it
    (capped by the number of papers, so a two-paper pack still yields terms).
    Synonym mappings keep the canonical target that the most papers agree on.
    """
    units = [u for u in _coerce_units(units) if u.unit_type in ("", _REGISTER_UNIT)]
    n_papers = len({u.source_paper_id or id(u) for u in units})
    need = max(1, min(int(min_support), n_papers or 1))
    fields: dict[str, list[dict[str, Any]]] = {}
    for f in _REGISTER_FIELDS:
        support: dict[str, set] = collections.defaultdict(set)
        surface: dict[str, str] = {}
        for u in units:
            for t in (u.form or {}).get(f) or []:
                k = _norm_term(t)
                if 1 < len(k) <= 120:
                    support[k].add(u.source_paper_id or id(u))
                    surface.setdefault(k, str(t).strip())
        kept = [
            {
                "term": surface[k],
                "support": len(v),
                "sources": sorted(x for x in v if isinstance(x, int)),
            }
            for k, v in support.items()
            if len(v) >= need
        ]
        fields[f] = sorted(kept, key=lambda d: (-d["support"], d["term"].lower()))
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for u in units:
        for bad, good in ((u.form or {}).get("synonyms") or {}).items():
            b, g = _norm_term(bad), _norm_term(good)
            if b and g and b != g:
                votes[b][g] += 1
    canonical = {
        d["term"].lower()
        for f in ("task_names", "input_names", "output_names", "terms", "metric_names")
        for d in fields[f]
    }
    synonyms = {}
    for b, c in votes.items():
        g, _cnt = c.most_common(1)[0]
        if b not in canonical:  # never flag a term the field itself uses canonically
            synonyms[b] = g
    whitelist = sorted(canonical, key=len, reverse=True)
    return {
        "n_papers": n_papers,
        "min_support": need,
        "fields": fields,
        "synonyms": synonyms,
        "whitelist": whitelist,
    }


def _lexicon_terms(lexicon: dict[str, Any] | None) -> list[str]:
    if not lexicon:
        return []
    terms = lexicon.get("whitelist")
    if terms is None:
        terms = [
            d["term"].lower()
            for f in (
                "task_names",
                "input_names",
                "output_names",
                "terms",
                "metric_names",
            )
            for d in (lexicon.get("fields") or {}).get(f, [])
        ]
    return sorted(
        {_norm_term(t) for t in terms if _norm_term(t)}, key=len, reverse=True
    )


def _lexicon_clause(lexicon: dict[str, Any] | None) -> str:
    """Prompt block binding the drafter to the field's canonical vocabulary."""
    if not lexicon or not lexicon.get("fields"):
        return ""
    F = lexicon["fields"]

    def top(f, k=15):
        return ", ".join(d["term"] for d in F.get(f, [])[:k]) or "-"

    syn = "; ".join(
        f"'{b}' -> '{g}'" for b, g in list((lexicon.get("synonyms") or {}).items())[:15]
    )
    return (
        "\nDOMAIN REGISTER (binding; drawn from published papers of this field). Use these "
        "canonical expressions verbatim for the concepts they name and do not coin new names "
        "for them. Task: "
        + top("task_names")
        + ". Inputs: "
        + top("input_names")
        + ". Outputs: "
        + top("output_names")
        + ". Standard terms: "
        + top("terms", 25)
        + ". Metrics: "
        + top("metric_names")
        + ". Hedges: "
        + top("hedges", 8)
        + ". Avoid: "
        + top("avoid", 8)
        + (". Replace non-canonical phrasings: " + syn if syn else "")
        + ".\n"
    )


def mask_register_terms(text: str, lexicon: dict[str, Any] | None) -> str:
    """Replace canonical terms with unique placeholders so n-grams containing them
    cannot count as verbatim reuse (standard vocabulary is not plagiarism)."""
    terms = _lexicon_terms(lexicon)
    if not terms or not text:
        return text or ""
    out, i = text, 0
    for t in terms:
        pat = re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I)

        def sub(_m):
            nonlocal i
            i += 1
            return f" regterm{i} "

        out = pat.sub(sub, out)
    return out


def register_violations(
    text: str, lexicon: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Deterministic check: non-canonical synonyms the field replaces with a standard term."""
    out = []
    low = (text or "").lower()
    for bad, good in ((lexicon or {}).get("synonyms") or {}).items():
        n = len(re.findall(r"(?<!\w)" + re.escape(bad) + r"(?!\w)", low))
        if n:
            out.append({"found": bad, "use": good, "count": n})
    return sorted(out, key=lambda d: -d["count"])


def register_terms_used(text: str, lexicon: dict[str, Any] | None) -> list[str]:
    low = (text or "").lower()
    return [
        t
        for t in _lexicon_terms(lexicon)
        if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", low)
    ]


@register_primitive(EXEMPLAR_CURATE_SPEC)
def exemplar_curate(
    *,
    db=None,
    topic_id=None,
    unit_type: str,
    paper_ids=None,
    min_quality: float = 7.0,
    max_papers: int = 8,
    min_tier_score: int = 85,
    min_prose_quality: float = 7.0,
    target_venue: str | None = None,
    venue_profile: dict[str, Any] | None = None,
    _model: str | None = None,
    **_: Any,
) -> ExemplarCurateOutput:
    """Build a quality-gated exemplar library slice for one ``unit_type``.

    Prose units select sources by EXEMPLAR FAMILY (Nature/Science-family
    journals vs top CCF-A, resolved from ``target_venue`` or the topic's
    target_venue) and additionally pass a surface-prose screen
    (``min_prose_quality``): the exemplar's visible writing must read at
    Nature/Science/top-CCF-A level, judged independently of experimental
    soundness. Figure units keep the plain ``min_tier_score`` venue-grade gate
    (default 85 = "CCF-A or CAS-Q1"). Pass ``min_tier_score=0`` to opt out of
    all source gating (e.g. tests, pilots).
    """
    unit_type = _canon_unit(unit_type)
    # unit_type "figure" = ARCHITECTURE/method figure VISUAL-STYLE exemplars (native
    # RH curation from the pool's schematic figures); "figure_suite" = quantitative
    # RESULT figures. Both transfer FORM not CONTENT.
    tmpl = _CURATE_PROMPTS.get(unit_type)
    if tmpl is None:
        return ExemplarCurateOutput(unit_type=unit_type)
    family = _pool_family(db, topic_id, unit_type, venue_profile, target_venue)
    if family is None and unit_type in _PROSE_UNITS and int(min_tier_score or 0) > 0:
        # Legacy unbound callers retain their broad pool; a venue binding wins.
        family = "ccfa" if _topic_domain_key(db, topic_id) == "stem" else "any"
    sources = _fetch_sources(
        db,
        topic_id,
        paper_ids,
        max_papers,
        min_tier_score,
        family,
        same_domain=(unit_type == _REGISTER_UNIT),
    )
    if not sources:
        if unit_type in _PROSE_UNITS or family is not None:
            raise ExemplarPoolError(unit_type, family)
        return ExemplarCurateOutput(unit_type=unit_type)
    client = _llm(_model, "medium", "exemplar_curate")
    kept: list[ExemplarUnit] = []
    rejected = 0
    for s in sources:
        text = (s["abstract"] + "\n\n" + s["note"]).strip()[:6000]
        if unit_type == _REGISTER_UNIT:
            # Terminology lives in the abstract and introduction prose.
            intro = _intro_text(db, int(s["id"] or 0), max_chars=7000)
            text = (
                (s["abstract"] or "")
                + "\n\n"
                + intro
                + "\n\n"
                + (s["note"] or "")[:1500]
            ).strip()[:9000]
        if unit_type in _SECTION_EVIDENCE_PATTERNS:
            # Sentence-level prose FORM needs the section's actual running
            # prose; abstract+notes evidence is scored down by the prompt.
            prose = _section_prose(
                db, int(s["id"] or 0), _SECTION_EVIDENCE_PATTERNS[unit_type]
            )
            if not prose and unit_type in _MOVE_UNITS:
                rejected += 1
                continue
            if prose:
                text = (
                    prose
                    if unit_type in _MOVE_UNITS
                    else prose + "\n\n" + (s["abstract"] or "")[:1000]
                ).strip()[:9000]
        elif unit_type == "abstract_moves":
            text = s["abstract"].strip()
        elif unit_type == "skeleton":
            # The real section tree (with appendix composition) reveals the
            # architecture far better than the abstract.
            overview = _structure_overview(db, int(s["id"] or 0))
            if overview:
                text = (overview + "\n\n" + text).strip()[:6000]
        if unit_type == "figure_suite":
            # captions (+ optional VLM figure analyses) reveal the suite FORM far
            # better than the abstract; fall back to abstract/notes when no PDF
            fig_ev = _figure_evidence(db, int(s["id"] or 0))
            if fig_ev:
                text = (fig_ev + "\n\n" + (s["abstract"] or "")[:1500]).strip()[:6000]
        elif unit_type == "figure":
            # architecture-figure captions (+ optional VLM visual-form analyses)
            # reveal the schematic style; fall back to abstract/notes when no PDF
            arch_ev = _architecture_evidence(db, int(s["id"] or 0))
            if arch_ev:
                text = (arch_ev + "\n\n" + (s["abstract"] or "")[:1500]).strip()[:6000]
        if len(text) < 120:
            rejected += 1
            continue
        prompt = tmpl.format(title=s["title"], venue=s["venue"] or "?", text=text)
        prompt += _register_clause(venue_profile, family)
        if unit_type in _PROSE_UNITS:
            prompt += _PROSE_SCREEN
        # A dead route (HTTP 503, timeout) is not a quality miss. Counting it as
        # rejected printed "kept=0 rejected=20" and parked WRITE as if every
        # candidate scored under the bar. Parse failures of a successful reply
        # still are.
        raw = _chat(client, prompt)
        try:
            j = _json(raw, "exemplar_curate")
        except Exception:
            rejected += 1
            continue
        q = _num(j.get("quality"))
        # Scale guard: models often return quality normalized to 0-1 despite
        # the 0-10 instruction (observed: every unit scored 0.92 and the >=7
        # gate rejected the whole corpus). A value in (0,1] is a confidence,
        # not a reject-grade 0-10 score — rescale it.
        if 0 < q <= 1:
            q *= 10
        form = j.get("form")
        if not isinstance(form, dict) or not form or q < float(min_quality):
            rejected += 1
            continue
        if unit_type in _MOVE_UNITS and not _valid_moves(form):
            rejected += 1
            continue
        # Surface-prose screen shares the min_tier_score=0 opt-out (tests,
        # pilots); in production a missing/low prose_quality is a hard reject.
        if unit_type in _PROSE_UNITS and (min_tier_score and int(min_tier_score) > 0):
            pq = (
                _num(j.get("prose_quality")) or q
            )  # a reply that scored quality but omitted prose_quality
            if 0 < pq <= 1:
                pq *= 10
            if pq < float(min_prose_quality):
                rejected += 1
                continue
            form["prose_quality"] = round(pq, 1)  # audit trail for retrieval/QA
        kept.append(
            ExemplarUnit(
                unit_type=unit_type,
                source_paper_id=int(s["id"] or 0),
                source_title=s["title"],
                venue=s["venue"] or "",
                venue_tier=_tier(s["venue"]),
                quality=q,
                form=form,
                summary=str(j.get("summary", ""))[:300],
            )
        )
    if not kept and (unit_type in _PROSE_UNITS or family is not None):
        raise ExemplarPoolError(unit_type, family)
    if kept and topic_id is not None and db is not None:
        try:
            from research_harness.retrieval import upsert_exemplar_units

            upsert_exemplar_units(db, topic_id=int(topic_id), units=kept)
        except Exception:
            pass
    return ExemplarCurateOutput(
        unit_type=unit_type,
        units=kept,
        candidates_seen=len(sources),
        kept=len(kept),
        rejected=rejected,
        model_used=getattr(client, "model", ""),
    )


@register_primitive(EXEMPLAR_RETRIEVE_SPEC)
def exemplar_retrieve(
    *,
    db=None,
    topic_id=None,
    unit_type: str,
    target_content: str,
    target_intent: str = "",
    units=None,
    top_k: int = 3,
    use_embed_rank: bool | None = None,
    venue_profile: dict[str, Any] | None = None,
    target_venue: str | None = None,
    _model: str | None = None,
    **_: Any,
) -> ExemplarRetrieveOutput:
    """Rank exemplars by structure > topic; return top-k (structure-first principle)."""
    unit_type = _canon_unit(unit_type)
    pool = _coerce_units(units)
    # An explicit empty pool is not permission to recover stale stored units.
    if units is None and db is not None and topic_id is not None:
        try:
            from research_harness.retrieval import load_exemplar_unit_rows

            rows = load_exemplar_unit_rows(
                db, topic_id=int(topic_id), unit_type=unit_type
            )
            pool = _coerce_units(rows)
        except Exception:
            pool = []
    family = _pool_family(db, topic_id, unit_type, venue_profile, target_venue)
    pool = _writing_pool(pool, unit_type, family)
    if not pool:
        return ExemplarRetrieveOutput(unit_type=unit_type)
    if len(pool) <= top_k:
        return ExemplarRetrieveOutput(
            unit_type=unit_type,
            ranked=sorted(pool, key=lambda u: -u.quality),
            rationale="all exemplars returned (count <= top_k)",
        )

    # Dense FORM shortlist before (or instead of) LLM rank when db available.
    query = f"{target_intent or ''} {target_content or ''}".strip()
    if use_embed_rank is None:
        use_embed_rank = db is not None
    if use_embed_rank and db is not None and query:
        try:
            from research_harness.retrieval import rank_exemplar_rows

            rowish = [
                {
                    "id": i,
                    "unit_type": u.unit_type,
                    "source_paper_id": u.source_paper_id,
                    "source_title": u.source_title,
                    "venue": u.venue,
                    "venue_tier": u.venue_tier,
                    "quality": u.quality,
                    "form": u.form,
                    "summary": u.summary,
                }
                for i, u in enumerate(pool)
            ]
            # Shortlist more than top_k so LLM (if used) still sees structure options.
            short_n = min(len(pool), max(top_k * 3, 8))
            ranked_rows = rank_exemplar_rows(
                db, query=query, rows=rowish, top_k=short_n, use_embeddings=True
            )
            short_pool = [
                pool[int(r["id"])]
                for r in ranked_rows
                if isinstance(r.get("id"), int) and 0 <= int(r["id"]) < len(pool)
            ]
            if short_pool:
                pool = short_pool
                if len(pool) <= top_k:
                    return ExemplarRetrieveOutput(
                        unit_type=unit_type,
                        ranked=pool[:top_k],
                        rationale="embed form rank (pool <= top_k after shortlist)",
                        model_used="",
                    )
        except Exception:
            pass

    order: list[int] = []
    rationale = "fallback: ranked by quality"
    model_used = ""
    try:
        client = _llm(_model, "light", "exemplar_retrieve")
        model_used = getattr(client, "model", "") or ""
        listing = "\n".join(
            f"[{i}] venue={u.venue or '?'} tier={u.venue_tier} quality={u.quality:g} "
            f"form={json.dumps(u.form)[:500]}"
            for i, u in enumerate(pool)
        )
        j = _json(
            _chat(
                client,
                _RETRIEVE_PROMPT.format(
                    unit_type=unit_type,
                    target=str(target_content)[:1800],
                    intent=str(target_intent)[:400],
                    listing=listing,
                    k=top_k,
                ),
            ),
            "exemplar_retrieve",
        )
        order = [int(i) for i in j.get("ranking", []) if _is_idx(i, len(pool))]
        rationale = str(j.get("rationale", rationale))[:400]
        if use_embed_rank:
            rationale = f"embed shortlist + {rationale}"[:400]
    except Exception:
        order = []
    ranked: list[ExemplarUnit] = []
    seen: set[int] = set()
    for i in order:
        if i not in seen:
            seen.add(i)
            ranked.append(pool[i])
    # When LLM gave nothing, keep embed shortlist order (already FORM-ranked).
    rest = (
        pool
        if (use_embed_rank and not order)
        else sorted(pool, key=lambda u: -u.quality)
    )
    if use_embed_rank and not order:
        rationale = "embed form rank (llm unavailable)"
    for u in rest:
        if len(ranked) >= top_k:
            break
        if u not in ranked:
            ranked.append(u)
    return ExemplarRetrieveOutput(
        unit_type=unit_type,
        ranked=ranked[:top_k],
        rationale=rationale,
        model_used=model_used,
    )


@register_primitive(EXEMPLAR_PLAN_SPEC)
def exemplar_plan(
    *,
    db=None,
    topic_id=None,
    unit_type: str,
    target_content: str,
    retrieved_units,
    venue_profile: dict[str, Any] | None = None,
    target_venue: str | None = None,
    register_lexicon: dict[str, Any] | None = None,
    _model: str | None = None,
    **_: Any,
) -> ExemplarPlanOutput:
    """Produce a FORM-only generation plan by structural analogy to exemplars."""
    unit_type = _canon_unit(unit_type)
    family = _pool_family(db, topic_id, unit_type, venue_profile, target_venue)
    pool = _writing_pool(retrieved_units, unit_type, family)
    tmpl = _PLAN_PROMPTS.get(unit_type, _PLAN_PROMPTS["_generic"])
    # Keep the target (including tail inventories) whole. Ranked extra examples
    # are optional; drop whole examples, never slice serialized JSON.
    target = str(target_content)

    def serialize(units):
        return json.dumps(
            [{"venue": u.venue, "form": u.form} for u in units], separators=(",", ":")
        )

    forms = serialize(pool)
    while len(target) + len(forms) > 24000 and len(pool) > 1:
        pool = pool[:-1]
        forms = serialize(pool)
    if len(target) + len(forms) > 24000:
        raise ValueError(
            "E-WRITE-EAG-PAYLOAD-LIMIT: complete target and one exemplar exceed 24000 characters"
        )
    client = _llm(_model, "writing", "exemplar_plan")
    plan: dict[str, Any] = {}
    plan_error, reply = "", ""
    try:
        reply = _chat(
            client,
            tmpl.format(target=target, forms=forms)
            + _register_clause(venue_profile, family)
            + _lexicon_clause(register_lexicon),
        )
        j = _json(reply, "exemplar_plan")
        plan = j.get("plan") if isinstance(j.get("plan"), dict) else j
        if not reply.strip():
            plan_error = "empty reply"
        elif not j:
            # _json yields {} for prose, a truncated fence, or a bare {}; say so, or the
            # refusal reads as if the model planned nothing.
            plan_error = f"reply parsed to no JSON object ({len(reply)} characters)"
    except Exception as exc:  # noqa: BLE001
        # A swallowed exception turns a paid call into an empty plan with no cause.
        # csmopen12's figure suite came back "planner returned no figures" after a
        # twenty-minute stage, and the reply and whatever went wrong reading it were
        # both already gone — the next run could only be a blind retry.
        plan, plan_error = {}, f"{type(exc).__name__}: {exc}"
    if unit_type in _MOVE_UNITS and not _valid_moves(plan):
        raise ValueError(
            f"E-WRITE-EAG-PLAN-INVALID: {unit_type}: {plan_error or 'missing move contract'}"
        )
    if plan and family:
        plan["exemplar_family"] = family
        plan["exemplar_ids"] = [u.source_paper_id for u in pool]
        plan["prose_register"] = (venue_profile or {}).get("prose_register", "")
    # What the model returned, before normalisation adds its own empty fields: an empty
    # appendix list made an empty plan truthy and dropped the reply from the refusal.
    planned = bool(plan)
    if isinstance(plan, dict) and unit_type in {"skeleton", "figure_suite"}:
        plan = _normalize_plan_appendix(plan, str(target_content or ""))
    return ExemplarPlanOutput(
        unit_type=unit_type,
        plan=plan or {},
        exemplar_ids=[u.source_paper_id for u in pool],
        form_only=True,
        model_used=getattr(client, "model", ""),
        plan_error=plan_error,
        plan_reply="" if planned else reply[:4000],
    )


@register_primitive(EXEMPLAR_CRITIQUE_SPEC)
def exemplar_critique(
    *,
    draft_text: str,
    exemplar_texts,
    max_overlap: float = 0.18,
    register_lexicon: dict[str, Any] | None = None,
    strict_register: bool = True,
    _model: str | None = None,
    **_: Any,
) -> ExemplarCritiqueOutput:
    """Form-not-content gate: deterministic n-gram overlap vs the source exemplars.

    With a ``register_lexicon`` (Track A), canonical domain terms are exempt from
    the overlap count — reusing the field's standard vocabulary is required, not
    plagiarism — and the draft is checked for non-canonical synonyms of those
    terms (``register.violations``); with ``strict_register`` a violation fails
    the gate so the revise loop restores the canonical wording.
    """
    draft = str(draft_text or "")
    masked = mask_register_terms(draft, register_lexicon)
    score, worst = _max_ngram_overlap(
        masked,
        [str(t) for t in (exemplar_texts or [])],
        n=8,
    )
    overlap_ok = score <= float(max_overlap)
    conformance: dict[str, Any] = {}
    violations: list[dict[str, Any]] = []
    if register_lexicon:
        violations = register_violations(draft, register_lexicon)
        conformance["register"] = {
            "violations": violations,
            "canonical_terms_used": register_terms_used(draft, register_lexicon),
        }
    passed = overlap_ok and not (strict_register and violations)
    notes = []
    notes.append(
        "within form-not-content bound"
        if overlap_ok
        else f"verbatim overlap {score:.2f} exceeds {max_overlap}"
    )
    if violations:
        notes.append(
            "non-canonical domain terms: "
            + "; ".join(f"'{v['found']}' -> '{v['use']}'" for v in violations[:6])
        )
    return ExemplarCritiqueOutput(
        passed=passed,
        overlap_score=round(score, 4),
        worst_ngram=worst,
        conformance=conformance,
        notes="; ".join(notes),
    )


_SECTION_FOR_UNIT = {
    "intro_arc": "introduction",
    "abstract": "abstract",
    "related_work_arc": "related_work",
    "method_arc": "method",
    "experiment_arc": "experiments",
    "discussion_arc": "conclusion",
    "abstract_moves": "abstract",
    "intro_moves": "introduction",
    "discussion_moves": "discussion",
}


def render_arc_plan(plan: dict[str, Any]) -> str:
    """Render an exemplar arc plan as a structure contract for section_draft.

    Handles the sentence-level shape (``paragraphs`` with per-sentence moves),
    the legacy flat ``moves`` shape, and skeleton ``sections``.
    """
    if not isinstance(plan, dict):
        return ""
    paras = plan.get("paragraphs")
    if isinstance(paras, list) and paras:
        lines: list[str] = []
        for i, p in enumerate(paras):
            if not isinstance(p, dict):
                continue
            head = f"Paragraph {i + 1} [{p.get('role', '')}]"
            intent = str(p.get("intent") or p.get("instruction") or "").strip()
            lines.append(f"{head}: {intent}" if intent else head)
            for k, sent in enumerate(p.get("sentences") or []):
                if isinstance(sent, dict):
                    lines.append(
                        f"  sentence {k + 1} [{sent.get('move', '')}]: "
                        f"{sent.get('instruction', sent.get('gist', ''))}"
                    )
        for key in ("hook_directive", "transition_directive", "notes"):
            v = str(plan.get(key) or "").strip()
            if v:
                lines.append(f"{key}: {v}")
        if lines:
            return "\n".join(lines)
    moves = plan.get("moves")
    if isinstance(moves, list) and moves:
        lines = [
            f"{i + 1}. [{m.get('move', '')}] {m.get('instruction', m.get('gist', ''))}"
            + (
                f"; action: {m['sentence_action']}; words: {m.get('word_range')}"
                if m.get("sentence_action")
                else ""
            )
            for i, m in enumerate(moves)
            if isinstance(m, dict)
        ]
        for key in (
            "length_band_words",
            "opening_forbidden_moves",
            "prose_register",
            "exemplar_family",
        ):
            if key in plan:
                lines.append(f"{key}: {plan[key]}")
        return "\n".join(lines)
    secs = plan.get("sections")
    if isinstance(secs, list) and secs:
        return "\n".join(
            f"{i + 1}. {s.get('name', '')} — {s.get('role', '')}"
            for i, s in enumerate(secs)
            if isinstance(s, dict)
        )
    return json.dumps(plan)[:1500]


# Back-compat alias (pre-sentence-level name).
_plan_to_outline = render_arc_plan


_DRAFT_PROMPT = (
    "Write the {unit_type} for THIS paper, FOLLOWING the plan below. Use ONLY your own words, "
    "grounded in the target content — never copy any phrasing from any exemplar.\n"
    "Target content: {target}\nPlan (form to follow): {plan}\n{target_state}{revision}\n"
    "Return the text only (no JSON, no preamble)."
)


@register_primitive(EXEMPLAR_GENERATE_SPEC)
def exemplar_generate(
    *,
    db=None,
    topic_id=None,
    unit_type: str,
    target_content: str,
    retrieved_units=None,
    plan=None,
    exemplar_texts=None,
    section: str | None = None,
    backend: str = "auto",
    max_rounds: int = 2,
    max_overlap: float = 0.18,
    quality_targets=None,
    venue_profile: dict[str, Any] | None = None,
    target_venue: str | None = None,
    register_lexicon: dict[str, Any] | None = None,
    _model: str | None = None,
    **_: Any,
) -> ExemplarGenerateOutput:
    """Evaluator-optimizer loop: plan → draft → critique → revise.

    Two critique axes drive revisions: (1) anti-plagiarism n-gram overlap vs the
    source exemplars, and (2) — when ``quality_targets`` is supplied (a serialized
    ``venue_prescription``) — deterministic first-impression checks (title/abstract
    word bands, paragraph development). The venue targets are also injected into
    the draft prompt so the writer sees the contract before drafting.

    Backend 'auto'/'section_draft' uses RH's evidence-grounded ``section_draft`` when a
    prose section + a drafting-ready topic (active PAPER_PLAN) are available; otherwise it
    transparently falls back to the self-contained drafter. The exemplar_plan is passed as
    section_draft's ``outline`` so the FORM is transferred while evidence stays this paper's.
    """
    unit_type = _canon_unit(unit_type)
    family = _pool_family(db, topic_id, unit_type, venue_profile, target_venue)
    if family is not None or unit_type in _MOVE_UNITS or not plan:
        retrieved_units = _writing_pool(retrieved_units, unit_type, family)
    if unit_type in _MOVE_UNITS and plan and not _valid_moves(plan):
        raise ValueError(f"E-WRITE-EAG-PLAN-INVALID: {unit_type}")
    if not isinstance(plan, dict) or not plan:
        plan = exemplar_plan(
            db=db,
            topic_id=topic_id,
            unit_type=unit_type,
            target_content=target_content,
            retrieved_units=retrieved_units or [],
            venue_profile=venue_profile,
            target_venue=target_venue,
            register_lexicon=register_lexicon,
            _model=_model,
        ).plan
    if not plan:
        raise ValueError(f"E-WRITE-EAG-PLAN-INVALID: {unit_type} returned no plan")
    ex_texts = [str(t) for t in (exemplar_texts or [])]
    sec = section or _SECTION_FOR_UNIT.get(unit_type)
    qt = _coerce_quality_targets(quality_targets)
    target_state = (
        _target_state_string(qt)
        + _register_clause(venue_profile, family)
        + _lexicon_clause(register_lexicon)
    )
    want_sd = (
        backend in ("auto", "section_draft")
        and bool(sec)
        and db is not None
        and topic_id is not None
    )
    outline = _plan_to_outline(plan)
    client = _llm(_model, "writing", "exemplar_generate")
    draft = ""
    crit: ExemplarCritiqueOutput | None = None
    qcrit: dict[str, Any] | None = None
    rounds = 0
    revision = ""
    used_backend = ""
    for r in range(max(1, int(max_rounds))):
        rounds = r + 1
        draft = ""
        if want_sd:
            try:
                from research_harness.execution.llm_primitives import section_draft

                sd = section_draft(
                    db=db,
                    section=sec,
                    topic_id=topic_id,
                    outline=outline,
                    extra_instructions=(
                        "Follow this exemplar-derived structure exactly; write ENTIRELY in your own "
                        "words; never reuse any exemplar wording, claims, or data, except the "
                        "canonical domain terms of the DOMAIN REGISTER, which must be used as given. "
                        + target_state
                        + revision
                    ),
                    _model=_model,
                )
                # section_draft returns SectionDraftOutput(draft=DraftText(...)).
                draft = ((sd.draft.content if sd and sd.draft else "") or "").strip()
                used_backend = "section_draft" if draft else ""
            except Exception:
                # A bound evidence-grounded draft may not turn into a self-contained one.
                if family is not None or unit_type in _MOVE_UNITS:
                    raise
                want_sd = False  # legacy unbound caller
        if not draft:
            try:
                draft = _chat(
                    client,
                    _DRAFT_PROMPT.format(
                        unit_type=unit_type,
                        target=str(target_content)[:3000],
                        plan=json.dumps(plan)[:2500],
                        target_state=target_state,
                        revision=revision,
                    ),
                ).strip()
            except Exception:
                draft = draft or ""
            used_backend = used_backend or "self"
        crit = exemplar_critique(
            draft_text=draft,
            exemplar_texts=ex_texts,
            max_overlap=max_overlap,
            register_lexicon=register_lexicon,
        )
        qcrit = _quality_critique(draft, qt, section=sec or unit_type)
        if crit.passed and qcrit["passed"]:
            break
        revision = ""
        reg_viol = (crit.conformance or {}).get("register", {}).get("violations") or []
        if crit.overlap_score > float(max_overlap):
            revision += (
                "IMPORTANT: your previous draft reused verbatim wording from an exemplar (n-gram "
                "overlap too high). Rewrite ENTIRELY in your own words, keeping the same plan/"
                "structure. Previous draft:\n" + draft[:1500]
            )
        if reg_viol:
            revision += (
                "\nIMPORTANT: replace these non-canonical terms with the field's canonical ones: "
                + "; ".join(f"'{v['found']}' -> '{v['use']}'" for v in reg_viol[:10])
                + ". Keep everything else.\n"
            )
        if not qcrit["passed"]:
            revision += _quality_revision_hint(qcrit)
    return ExemplarGenerateOutput(
        unit_type=unit_type,
        draft=draft,
        plan=plan,
        critique=(
            {
                "passed": crit.passed,
                "overlap_score": crit.overlap_score,
                "worst_ngram": crit.worst_ngram,
                "quality": {
                    "passed": qcrit["passed"] if qcrit else True,
                    "failures": qcrit["failures"] if qcrit else [],
                    "deferred": qcrit["deferred"] if qcrit else [],
                    "checks": qcrit["checks"] if qcrit else [],
                },
            }
            if crit
            else {}
        ),
        rounds=rounds,
        passed=(crit.passed if crit else True) and (qcrit["passed"] if qcrit else True),
        backend=used_backend,
        model_used=getattr(client, "model", ""),
    )


def architecture_style_reference(
    *,
    db=None,
    topic_id=None,
    target_content: str = "",
    top_k: int = 3,
    min_quality: float = 7.0,
    max_papers: int = 6,
    _model: str | None = None,
) -> dict[str, Any]:
    """Resolve a VISUAL STYLE ANCHOR for an architecture figure from the topic's
    schematic-figure exemplars: curate → retrieve (structure>topic) → plan a
    FORM-only style anchor. This is the RH-native ``reference_style_selection``
    step — it runs before the image provider so the generated architecture figure
    stands on the shoulders of well-composed published figures (transferring
    visual FORM, never the exemplars' method/components).

    Best-effort: returns ``{"executed": False, "reason": ...}`` when no exemplars
    or no LLM are available, so figure generation proceeds unanchored rather than
    failing.
    """
    if db is None or topic_id is None:
        return {"executed": False, "reason": "no_topic"}
    try:
        cur = exemplar_curate(
            db=db,
            topic_id=topic_id,
            unit_type="figure",
            min_quality=min_quality,
            max_papers=max_papers,
            _model=_model,
        )
        units = cur.units
        if not units:
            return {"executed": False, "reason": "no_architecture_exemplars"}
        ret = exemplar_retrieve(
            unit_type="figure",
            target_content=target_content or "",
            units=units,
            top_k=top_k,
            _model=_model,
        )
        pl = exemplar_plan(
            unit_type="figure",
            target_content=target_content or "",
            retrieved_units=ret.ranked,
            _model=_model,
        )
        plan = pl.plan if isinstance(pl.plan, dict) else {}
        anchor = plan.get("style_anchor")
        if not isinstance(anchor, dict) or not anchor:
            return {"executed": False, "reason": "no_style_anchor"}
        return {
            "executed": True,
            "style_anchor": anchor,
            "rationale": str(plan.get("rationale", ""))[:300],
            "avoid": [str(a) for a in (plan.get("avoid") or [])][:8],
            "reference_ids": list(pl.exemplar_ids),
            "candidates_seen": cur.candidates_seen,
            "model_used": pl.model_used or cur.model_used,
        }
    except Exception as exc:  # noqa: BLE001 - reference selection is best-effort
        return {"executed": False, "reason": f"error:{type(exc).__name__}"}
