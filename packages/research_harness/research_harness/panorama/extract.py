"""LLM claim-extraction batch for the Domain Panorama KB (plan §3).

Turns ``paper`` entities (title + abstract) into contribution-level ``claim``
entities, each with a 4-tuple evidence anchor whose ``quote`` is a verbatim
snippet of the abstract, and occupies territory-map cells
(problem × mechanism × evidence facet) so novelty mining can query the map.

The LLM is injected as a plain ``callable(prompt) -> str``. When none is
given, a default is built lazily from llm_router (mirroring
``primitives/cs_classify.py``) — the import happens only when a paper
actually needs extraction, so tests never touch env or network.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from .store import PanoramaStore

MIN_ABSTRACT_CHARS = 200

EVIDENCE_FACETS = (
    "benchmark-eval",
    "human-study",
    "theoretical",
    "case-study",
    "none",
)

_TAG_MAX_CHARS = 40

_EXT_ID_PREFERENCE = ("arxiv", "doi", "openalex", "s2", "semantic_scholar", "url")

DEFAULT_PROMPT_TEMPLATE = """You are building a research-domain knowledge base. \
Given the title and abstract of one paper, extract its contribution-level claims.

Output ONLY a JSON array (no markdown fences, no commentary) of at most \
{max_claims} objects. Each object has exactly these keys:

  "claim": one self-contained, contribution-level claim sentence stating what
           the paper contributes or shows.
  "problem": short problem-facet tag, lowercase kebab-case, 2-4 words.
  "mechanism": short mechanism tag, lowercase kebab-case.
  "evidence_facet": one of "benchmark-eval" | "human-study" | "theoretical" |
                    "case-study" | "none".
  "quote": a verbatim snippet copied character-for-character from the abstract
           below that supports the claim. No paraphrase, no ellipsis, no added
           or reordered words.
  "confidence": a number between 0 and 1.

Tagging rules — tags build one shared territory map across MANY papers, so
they must be GENERIC and REUSABLE, never paper-specific:
- problem examples: "paper-generation", "idea-generation", "rigor-audit",
  "benchmark-construction".
- mechanism examples: "llm-agent-loop", "tree-search", "multi-agent-debate",
  "retrieval-grounding", "fine-tuning".
- Reuse an existing generic tag whenever one fits; never derive tags from the
  paper's own system, model, or dataset names.
- Lowercase kebab-case only.

Known problem tags already in this map (REUSE one when it fits; mint a new
tag ONLY when none fits): {known_problem_tags}

Known mechanism tags already in this map (same rule): {known_mechanism_tags}

Title: {title}

Abstract: {abstract}
"""

# ponytail: prompt-size cap; switch to frequency-ranked retrieval per paper
# if a direction ever exceeds this many distinct tags per axis.
_KNOWN_TAGS_MAX = 100


def _known_tags(store: PanoramaStore, direction_id: int) -> tuple[set[str], set[str]]:
    problems: set[str] = set()
    mechanisms: set[str] = set()
    for cell in store.cells(direction_id):
        if cell.get("problem"):
            problems.add(str(cell["problem"]))
        if cell.get("mechanism"):
            mechanisms.add(str(cell["mechanism"]))
    return problems, mechanisms


def _format_tags(tags: set[str]) -> str:
    if not tags:
        return "(none yet — this is the first extraction batch)"
    return ", ".join(sorted(tags)[:_KNOWN_TAGS_MAX])


def _default_llm() -> tuple[Callable[[str], str], str]:
    """Build the default llm_router-backed completion callable.

    Imported lazily (mirrors ``primitives/cs_classify.py``:
    ``LLMClient(resolve_llm_config())`` + a single ``chat`` call per prompt)
    so that callers injecting a fake ``llm`` never need llm_router env,
    config, or network.
    """
    from llm_router.client import LLMClient, resolve_llm_config

    config = resolve_llm_config()
    client = LLMClient(config)
    model_name = config.model or config.provider

    def _call(prompt: str) -> str:
        return client.chat(prompt)

    return _call, model_name


def _first_json_array(raw: str) -> list[Any] | None:
    """Extract and decode the first JSON array substring of ``raw``."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    decoder = json.JSONDecoder()
    index = text.find("[")
    while index != -1:
        try:
            value, _ = decoder.raw_decode(text, index)
        except ValueError:
            value = None
        if isinstance(value, list):
            return value
        index = text.find("[", index + 1)
    return None


def _normalize_tag(value: Any) -> str:
    """Lowercase kebab-case: spaces/underscores → dashes, strip, cap 40."""
    if not isinstance(value, str):
        return ""
    tag = value.strip().lower()
    tag = re.sub(r"[\s_]+", "-", tag)
    tag = re.sub(r"-{2,}", "-", tag).strip("-")
    if len(tag) > _TAG_MAX_CHARS:
        tag = tag[:_TAG_MAX_CHARS].rstrip("-")
    return tag


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def _quote_in_abstract(quote: str, abstract: str) -> bool:
    normalized = _squash(quote)
    return bool(normalized) and normalized in _squash(abstract)


def _coerce_confidence(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, confidence))


def _paper_abstract(paper: dict[str, Any]) -> str:
    attrs = paper.get("attrs") or {}
    abstract = attrs.get("abstract")
    if not isinstance(abstract, str) or not abstract.strip():
        abstract = str(paper.get("summary") or "")
    return abstract.strip()


def _source_ref(paper: dict[str, Any]) -> str:
    pool_paper_id = paper.get("pool_paper_id")
    if pool_paper_id:
        return f"pool:paper:{pool_paper_id}"
    ext_ids = paper.get("ext_ids") or {}
    for scheme in _EXT_ID_PREFERENCE:
        if ext_ids.get(scheme):
            return f"{scheme}:{ext_ids[scheme]}"
    for scheme in sorted(ext_ids):
        if ext_ids[scheme]:
            return f"{scheme}:{ext_ids[scheme]}"
    return f"entity:{paper['id']}"


def _has_live_claims_edge(store: PanoramaStore, paper_id: int) -> bool:
    return any(
        edge["rel"] == "claims" and edge["src_id"] == paper_id
        for edge in store.edges_for(paper_id)
    )


def _strength_for(occupants: int) -> str:
    if occupants >= 3:
        return "strong"
    if occupants == 2:
        return "moderate"
    return "weak"


def extract_claims(
    store: PanoramaStore,
    direction_id: int,
    *,
    llm: Callable[[str], str] | None = None,
    limit: int | None = None,
    only_missing: bool = True,
    max_claims_per_paper: int = 3,
) -> dict[str, Any]:
    """Extract contribution-level claims for a direction's papers.

    Candidates are ``paper`` entities with a usable abstract
    (``attrs["abstract"]`` or ``summary``, at least ``MIN_ABSTRACT_CHARS``
    chars). With ``only_missing`` (default), papers that already have a live
    outgoing ``claims`` edge are skipped, so reruns are idempotent and make
    zero LLM calls for already-extracted papers. ``limit`` caps the number of
    LLM calls in this batch, making large extractions resumable.
    """
    llm_call = llm
    if llm is not None:
        model_name = str(getattr(llm, "model", "") or "") or "custom"
    else:
        model_name = ""

    papers_seen = 0
    papers_extracted = 0
    papers_skipped = 0
    claims_written = 0
    dropped_bad_quote = 0
    attempted = 0
    errors: list[dict[str, Any]] = []
    touched: dict[int, tuple[str, str, str]] = {}
    known_problems, known_mechanisms = _known_tags(store, direction_id)

    for paper in store.entities(direction_id, "paper"):
        papers_seen += 1
        paper_id = int(paper["id"])
        abstract = _paper_abstract(paper)
        if len(abstract) < MIN_ABSTRACT_CHARS:
            papers_skipped += 1
            continue
        if only_missing and _has_live_claims_edge(store, paper_id):
            papers_skipped += 1
            continue
        if limit is not None and attempted >= limit:
            papers_seen -= 1
            break
        if llm_call is None:
            llm_call, model_name = _default_llm()
        prompt = DEFAULT_PROMPT_TEMPLATE.format(
            max_claims=max_claims_per_paper,
            known_problem_tags=_format_tags(known_problems),
            known_mechanism_tags=_format_tags(known_mechanisms),
            title=paper["name"],
            abstract=abstract,
        )
        attempted += 1
        try:
            raw = llm_call(prompt)
        except Exception as exc:  # one bad call must not sink the batch
            errors.append({"paper_id": paper_id, "error": f"llm_error: {exc}"})
            continue
        parsed = _first_json_array(raw)
        if parsed is None:
            errors.append({"paper_id": paper_id, "error": "parse_error"})
            continue
        papers_extracted += 1
        source_ref = _source_ref(paper)
        for item in parsed[:max_claims_per_paper]:
            if not isinstance(item, dict):
                continue
            claim_text = str(item.get("claim") or "").strip()
            problem = _normalize_tag(item.get("problem"))
            mechanism = _normalize_tag(item.get("mechanism"))
            if not claim_text or not problem or not mechanism:
                continue
            facet = _normalize_tag(item.get("evidence_facet"))
            if facet not in EVIDENCE_FACETS:
                facet = "none"
            quote = str(item.get("quote") or "")
            if not _quote_in_abstract(quote, abstract):
                dropped_bad_quote += 1
                continue
            confidence = _coerce_confidence(item.get("confidence"))
            claim_id = store.upsert_entity(
                direction_id,
                "claim",
                claim_text[:120],
                summary=claim_text,
                source="extract",
                extractor_model=model_name,
                confidence=confidence,
            )
            store.add_edge(
                direction_id, paper_id, claim_id, "claims", confidence=confidence
            )
            store.add_anchor(
                "entity",
                claim_id,
                keywords=f"{problem} {mechanism}",
                summary=claim_text,
                quote=quote,
                source_ref=source_ref,
            )
            cell_id = store.upsert_cell(direction_id, problem, mechanism, facet)
            store.occupy_cell(cell_id, claim_id)
            touched[cell_id] = (problem, mechanism, facet)
            known_problems.add(problem)
            known_mechanisms.add(mechanism)
            claims_written += 1

    for cell_id, (problem, mechanism, facet) in touched.items():
        occupants = len(store.cell_occupants(cell_id))
        store.upsert_cell(
            direction_id,
            problem,
            mechanism,
            facet,
            evidence_strength=_strength_for(occupants),
            status="occupied",
        )

    store.set_meta(
        f"extract:last_run:{direction_id}",
        datetime.now(timezone.utc).isoformat(),
    )
    return {
        "papers_seen": papers_seen,
        "papers_extracted": papers_extracted,
        "papers_skipped": papers_skipped,
        "claims_written": claims_written,
        "cells_touched": len(touched),
        "dropped_bad_quote": dropped_bad_quote,
        "errors": errors,
    }
