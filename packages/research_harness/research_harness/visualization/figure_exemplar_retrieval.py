"""UF04 figure–caption exemplar retrieval.

Deterministic filter-then-rank over in-memory units. Structure over topic.
No embeddings, vector store, LLM, corpus acquisition, or source-pixel leak.
"""

from __future__ import annotations

from typing import Any, Mapping

from .figure_package_contracts import (
    SCHEMA_REFERENCE_RECORD,
    validate_figure_opportunity,
    validate_reference_record,
)

WEIGHTS = {
    "figure_role": 0.35,
    "information_topology": 0.25,
    "evidence_grammar": 0.15,
    "venue_profile": 0.15,
    "quality_recency_source": 0.10,
}

USER_VISIBLE_RIGHTS = frozenset({"display_allowed", "redistributable"})
ELIGIBLE_RIGHTS = frozenset(
    {"internal_retrieval", "display_allowed", "redistributable"}
)

_TOPOLOGY_DEFAULT = {
    "method_architecture": "pipeline_stages",
    "study_or_experiment_design": "protocol_flow",
    "quantitative_comparison": "grouped_comparison",
    "ablation_or_sensitivity": "factor_sweep",
    "qualitative_cases": "case_grid",
}


def retrieve_figure_exemplars(
    *,
    opportunity: Mapping[str, Any],
    units: list[Mapping[str, Any]],
    target_venue: str = "",
    topic: str = "",
    top_k: int = 3,
) -> dict[str, Any]:
    opp = validate_figure_opportunity(opportunity)
    query = {
        "role": str(opp["role"]),
        "evidence_grammar": str(opp.get("evidence_boundary") or ""),
        "venue_profile": str(target_venue or opp.get("target_venue") or ""),
        "information_topology": str(
            opp.get("information_topology") or _TOPOLOGY_DEFAULT.get(opp["role"], "")
        ),
        "topic": str(topic or opp.get("topic") or ""),
        "reader_question": str(opp.get("reader_question") or ""),
    }
    ranked: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for raw in units:
        if not isinstance(raw, Mapping):
            continue
        unit = dict(raw)
        rights = str(unit.get("rights_status") or "unknown")
        if rights not in ELIGIBLE_RIGHTS:
            excluded.append(
                {
                    "reference_id": str(
                        unit.get("reference_id") or unit.get("figure_id") or ""
                    ),
                    "reason": f"rights_status={rights}",
                }
            )
            continue
        dims, total = _score(query, unit)
        record = _to_record(unit, query, dims, total, rights)
        scored.append((-total, record["reference_id"], record))
    scored.sort()
    seen_papers: set[str] = set()
    diverse: list[dict[str, Any]] = []
    remainder: list[dict[str, Any]] = []
    for _neg, _rid, record in scored:
        paper = str(record.get("paper_id") or record["reference_id"])
        if paper in seen_papers:
            remainder.append(record)
            continue
        seen_papers.add(paper)
        diverse.append(record)
    ordered = diverse + remainder
    for record in ordered[: max(0, int(top_k))]:
        ranked.append(validate_reference_record(record))
    return {
        "query": query,
        "ranked": ranked,
        "excluded": excluded,
        "weights": dict(WEIGHTS),
    }


def _match(query_val: str, unit_val: str) -> float:
    if not query_val:
        return 0.5
    if not unit_val:
        return 0.0
    return 1.0 if query_val == unit_val else 0.0


def _score(
    query: Mapping[str, str], unit: Mapping[str, Any]
) -> tuple[dict[str, float], float]:
    dims = {
        "figure_role": _match(
            query["role"], str(unit.get("figure_role") or unit.get("role") or "")
        ),
        "information_topology": _match(
            query["information_topology"], str(unit.get("information_topology") or "")
        ),
        "evidence_grammar": _match(
            query["evidence_grammar"], str(unit.get("evidence_grammar") or "")
        ),
        "venue_profile": _match(
            query["venue_profile"],
            str(unit.get("venue_profile") or unit.get("venue") or ""),
        ),
    }
    quality = float(unit.get("quality") or 0.0)
    if quality > 1.0:
        quality = quality / 10.0
    quality = max(0.0, min(1.0, quality))
    recency = 1.0 if int(unit.get("publication_year") or 0) >= 2023 else 0.5
    source = 1.0 if str(unit.get("verification_status") or "") == "verified" else 0.5
    dims["quality_recency_source"] = (quality + recency + source) / 3.0
    total = sum(WEIGHTS[k] * dims[k] for k in WEIGHTS)
    unit_topic = str(unit.get("topic") or "")
    if query["topic"] and unit_topic and query["topic"] == unit_topic:
        total += 0.02
    return dims, total


def _to_record(
    unit: Mapping[str, Any],
    query: Mapping[str, str],
    dims: Mapping[str, float],
    total: float,
    rights: str,
) -> dict[str, Any]:
    transferable = [
        k for k, v in dims.items() if v >= 1.0 and k != "quality_recency_source"
    ]
    if not transferable:
        transferable = ["layout_form"]
    record: dict[str, Any] = {
        "schema_version": SCHEMA_REFERENCE_RECORD,
        "reference_id": str(unit.get("reference_id") or unit.get("figure_id") or "ref"),
        "paper_id": str(unit.get("paper_id") or ""),
        "figure_id": str(unit.get("figure_id") or ""),
        "panel_ids": list(unit.get("panel_ids") or []),
        "match_dimensions": {
            "figure_role": str(unit.get("figure_role") or unit.get("role") or ""),
            "information_topology": str(unit.get("information_topology") or ""),
            "evidence_grammar": str(unit.get("evidence_grammar") or ""),
            "venue_profile": str(unit.get("venue_profile") or unit.get("venue") or ""),
        },
        "source_bindings": {},
        "rights_status": rights,
        "selection_score": round(total, 6),
        "selection_reasons": [f"{k}={dims[k]:g}*{WEIGHTS[k]:g}" for k in WEIGHTS]
        + [f"total={total:.6f}"],
        "transferable": transferable,
        "not_transferable": ["source_claims", "source_numbers", "source_topic_content"],
    }
    if rights in USER_VISIBLE_RIGHTS:
        if unit.get("caption"):
            record["caption"] = unit["caption"]
        if unit.get("image_path"):
            record["image_path"] = unit["image_path"]
    return record
