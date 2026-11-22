"""Tag-vocabulary canonicalization for the territory map.

Method adopted from AutoSchemaKG's conceptualization stage (arXiv 2505.23628,
MIT): the LLM groups an
axis's raw tag stream into canonical categories instead of relying on each
extraction call to spell tags identically. Synonym tags fragment territory
cells, and fragmented cells read as false gaps — so this pass is a
correctness repair, not cosmetics.

Deterministic by construction: the LLM only *proposes* a variant→canonical
mapping over the existing vocabulary; validation drops anything outside it,
resolves chains, and the merge itself is plain SQL via
``PanoramaStore.merge_cell_into``. Dry-run by default.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from .extract import _default_llm, _strength_for
from .store import PanoramaStore

_AXES = ("problem", "mechanism")

PROMPT_TEMPLATE = """You maintain the tag vocabulary of a research territory \
map. Below are the "{axis}" tags currently in use, with how many map cells \
use each.

Merge ONLY true duplicates: spelling variants, singular/plural, word-order or \
synonym phrasings of the SAME concept (e.g. "llm-agent-loop" and \
"agent-loop"). Never merge two genuinely different concepts, and never merge \
a narrower concept into a broader one.

Output ONLY a JSON object (no fences, no commentary) mapping each duplicate \
tag to the canonical tag it should become. The canonical tag MUST be one of \
the listed tags — prefer the more frequent spelling. Omit tags that are \
already fine. Output {{}} if nothing should merge.

Tags ({axis}):
{tags}
"""


def _tag_counts(store: PanoramaStore, direction_id: int) -> dict[str, Counter]:
    counts: dict[str, Counter] = {axis: Counter() for axis in _AXES}
    for cell in store.cells(direction_id):
        for axis in _AXES:
            value = str(cell.get(axis) or "")
            if value:
                counts[axis][value] += 1
    return counts


def _parse_mapping(raw: str) -> dict[str, str] | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(k): str(v) for k, v in parsed.items()}


def _validate_mapping(
    proposed: dict[str, str], vocabulary: set[str]
) -> tuple[dict[str, str], list[str]]:
    """Keep only in-vocabulary, non-identity entries; resolve chains."""
    dropped: list[str] = []
    mapping: dict[str, str] = {}
    for variant, canonical in proposed.items():
        if (
            variant not in vocabulary
            or canonical not in vocabulary
            or variant == canonical
        ):
            dropped.append(variant)
            continue
        mapping[variant] = canonical
    resolved: dict[str, str] = {}
    for variant, canonical in mapping.items():
        seen = {variant}
        while canonical in mapping and canonical not in seen:
            seen.add(canonical)
            canonical = mapping[canonical]
        if canonical in seen and canonical != variant and canonical in mapping:
            dropped.append(variant)  # cycle — refuse the whole chain member
            continue
        if canonical == variant:
            dropped.append(variant)
            continue
        resolved[variant] = canonical
    return resolved, dropped


def canonicalize_tags(
    store: PanoramaStore,
    direction_id: int,
    *,
    llm: Callable[[str], str] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Propose (and optionally apply) synonym-tag merges for one direction."""
    counts = _tag_counts(store, direction_id)
    mappings: dict[str, dict[str, str]] = {}
    dropped: dict[str, list[str]] = {}
    errors: list[str] = []
    llm_call = llm

    for axis in _AXES:
        vocabulary = set(counts[axis])
        if len(vocabulary) < 2:
            mappings[axis] = {}
            continue
        if llm_call is None:
            llm_call, _ = _default_llm()
        tag_lines = "\n".join(
            f"- {tag} ({count} cells)" for tag, count in counts[axis].most_common()
        )
        try:
            raw = llm_call(PROMPT_TEMPLATE.format(axis=axis, tags=tag_lines))
        except Exception as exc:
            errors.append(f"{axis}: llm_error: {exc}")
            mappings[axis] = {}
            continue
        proposed = _parse_mapping(raw)
        if proposed is None:
            errors.append(f"{axis}: parse_error")
            mappings[axis] = {}
            continue
        mappings[axis], dropped[axis] = _validate_mapping(proposed, vocabulary)

    cells_merged = 0
    claims_moved = 0
    if apply and any(mappings.values()):
        retagged: set[int] = set()
        for cell in list(store.cells(direction_id)):
            problem = mappings["problem"].get(cell["problem"], cell["problem"])
            mechanism = mappings["mechanism"].get(cell["mechanism"], cell["mechanism"])
            if problem == cell["problem"] and mechanism == cell["mechanism"]:
                continue
            dst_id = store.upsert_cell(
                direction_id, problem, mechanism, cell.get("evidence_facet") or ""
            )
            claims_moved += store.merge_cell_into(int(cell["id"]), dst_id)
            cells_merged += 1
            retagged.add(dst_id)
        for dst_id in retagged:
            dst = next(c for c in store.cells(direction_id) if int(c["id"]) == dst_id)
            store.upsert_cell(
                direction_id,
                dst["problem"],
                dst["mechanism"],
                dst.get("evidence_facet") or "",
                evidence_strength=_strength_for(len(store.cell_occupants(dst_id))),
                status="occupied",
            )
        store.set_meta(
            f"canonicalize:last_run:{direction_id}",
            datetime.now(timezone.utc).isoformat(),
        )

    return {
        "proposed": mappings,
        "dropped": dropped,
        "applied": bool(apply),
        "cells_merged": cells_merged,
        "claims_moved": claims_moved,
        "errors": errors,
    }
