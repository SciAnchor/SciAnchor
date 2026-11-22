"""UF03 context intake and transparent top-one opportunity ranking.

Contracts only. No generation, provider, parser, or corpus.
Existing-figure decisions are rule-based on declared diagnostic fields.
"""

from __future__ import annotations

from typing import Any, Mapping

from .figure_package_contracts import (
    FIGURE_ROLES,
    SCHEMA_CONTEXT_ASSESSMENT,
    SCHEMA_FIGURE_OPPORTUNITY,
    VENUE_IPM,
    VENUE_NPJ,
    validate_context_assessment,
    validate_figure_opportunity,
    validate_figure_task,
)

DECISIONS = ("keep", "improve", "redraw", "request_information")

_VENUE_FIT = {
    VENUE_NPJ: {
        "study_or_experiment_design": 2,
        "method_architecture": 2,
        "qualitative_cases": 1,
        "quantitative_comparison": 1,
        "ablation_or_sensitivity": 0,
    },
    VENUE_IPM: {
        "quantitative_comparison": 2,
        "ablation_or_sensitivity": 2,
        "method_architecture": 1,
        "qualitative_cases": 1,
        "study_or_experiment_design": 0,
    },
}

_REDRAW_DEFECTS = frozenset(
    {"claim_exceeds_evidence", "numeric_not_from_records", "scientific_mismatch"}
)
_IMPROVE_DEFECTS = frozenset(
    {"missing_caption", "unlabeled_axes", "missing_body_reference", "weak_encoding"}
)


def assess_intake(task: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a FigureTask into assessment, inventory, ranked opportunities."""
    task_obj = validate_figure_task(task)
    context = (
        task.get("paper_context")
        if isinstance(task.get("paper_context"), Mapping)
        else {}
    )
    assets = list(task.get("existing_assets") or [])
    source_data = list(task.get("source_data") or [])

    inventory = [_inventory_asset(item) for item in assets if isinstance(item, Mapping)]
    signals = _signals(context, source_data)
    opportunities = _opportunities(task_obj, signals, inventory)
    assessment = _assessment(task_obj, signals, inventory, opportunities)
    selected = _select(task_obj, assessment, inventory, opportunities)

    return {
        "task": task_obj,
        "assessment": assessment,
        "existing_figure_inventory": inventory,
        "opportunities": opportunities,
        "selected_opportunity": selected,
    }


def _signals(context: Mapping[str, Any], source_data: list[Any]) -> dict[str, Any]:
    claims = [c for c in list(context.get("claims") or []) if isinstance(c, Mapping)]
    records = [r for r in list(context.get("records") or []) if isinstance(r, Mapping)]
    records.extend(r for r in source_data if isinstance(r, Mapping))
    tables = [t for t in list(context.get("tables") or []) if isinstance(t, Mapping)]
    method_elements = [m for m in list(context.get("method_elements") or []) if m]
    ablation = [
        r for r in list(context.get("ablation_records") or []) if isinstance(r, Mapping)
    ]
    cases = [c for c in list(context.get("cases") or []) if isinstance(c, Mapping)]
    sections = (
        context.get("sections") if isinstance(context.get("sections"), Mapping) else {}
    )
    methods_text = str(
        sections.get("methods") or context.get("method_text") or ""
    ).strip()
    results_text = str(
        sections.get("results") or context.get("result_text") or ""
    ).strip()
    protocol = str(context.get("protocol") or sections.get("protocol") or "").strip()
    return {
        "claims": claims,
        "records": records,
        "tables": tables,
        "method_elements": method_elements,
        "ablation": ablation,
        "cases": cases,
        "methods_text": methods_text,
        "results_text": results_text,
        "protocol": protocol,
        "title": str(context.get("title") or "").strip(),
        "abstract": str(context.get("abstract") or "").strip(),
    }


def _inventory_asset(asset: Mapping[str, Any]) -> dict[str, Any]:
    defects = [str(d) for d in list(asset.get("defects") or []) if str(d).strip()]
    caption = str(asset.get("caption") or "").strip()
    refs = list(asset.get("body_references") or [])
    fidelity = str(asset.get("scientific_fidelity") or "").strip().lower()
    quality = str(asset.get("communicative_quality") or "").strip().lower()
    has_bytes = bool(
        asset.get("sha256") or asset.get("path") or asset.get("bytes_present")
    )

    if fidelity == "fail" or any(d in _REDRAW_DEFECTS for d in defects):
        decision = "redraw"
    elif not has_bytes and not caption:
        decision = "request_information"
        defects = list(dict.fromkeys([*defects, "missing_asset_and_caption"]))
    elif (
        quality == "fail"
        or any(d in _IMPROVE_DEFECTS for d in defects)
        or not caption
        or not refs
    ):
        decision = "improve"
        if not caption and "missing_caption" not in defects:
            defects.append("missing_caption")
        if not refs and "missing_body_reference" not in defects:
            defects.append("missing_body_reference")
    else:
        decision = "keep"

    reasons = (
        list(defects) if defects else [f"scientific_fidelity={fidelity or 'pass'}"]
    )
    return {
        "asset_id": str(asset.get("asset_id") or asset.get("figure_id") or "asset"),
        "figure_id": str(asset.get("figure_id") or asset.get("asset_id") or "fig"),
        "role": asset.get("role") if asset.get("role") in FIGURE_ROLES else None,
        "decision": decision,
        "reasons": reasons,
        "defects": defects,
        "caption_present": bool(caption),
        "body_references": [str(r) for r in refs],
    }


def _role_evidence(
    role: str, signals: Mapping[str, Any]
) -> tuple[list[str], list[str], str]:
    """Return (available, missing, evidence_boundary)."""
    available: list[str] = []
    missing: list[str] = []
    if role == "method_architecture":
        if signals["method_elements"] or signals["methods_text"]:
            available.append("method_description")
        else:
            missing.append("method_description")
        return available, missing, "conceptual"
    if role == "study_or_experiment_design":
        if signals["protocol"] or _has_kind(signals["claims"], "protocol"):
            available.append("protocol")
        else:
            missing.append("protocol")
        return available, missing, "planned_protocol" if available else "conceptual"
    if role == "quantitative_comparison":
        if signals["records"]:
            available.append("comparison_records")
        else:
            missing.append("comparison_records")
        return available, missing, "evidence_backed" if available else "conceptual"
    if role == "ablation_or_sensitivity":
        if signals["ablation"]:
            available.append("ablation_records")
        else:
            missing.append("ablation_records")
        return available, missing, "evidence_backed" if available else "conceptual"
    if signals["cases"]:
        available.append("cases")
    else:
        missing.append("cases")
    return available, missing, "mixed" if available else "conceptual"


def _has_kind(claims: list[Mapping[str, Any]], kind: str) -> bool:
    return any(str(c.get("kind") or "") == kind for c in claims)


def _claim_for_role(role: str, signals: Mapping[str, Any]) -> str:
    for claim in signals["claims"]:
        text = str(claim.get("text") or "").strip()
        if text and (
            not claim.get("kind")
            or str(claim.get("kind")) in {role, "result", "method"}
        ):
            return text
    defaults = {
        "method_architecture": "The method maps inputs through named stages to a scored output.",
        "study_or_experiment_design": "The study follows a planned protocol from intake to endpoint.",
        "quantitative_comparison": "Named methods are compared on shared metrics.",
        "ablation_or_sensitivity": "Component or hyperparameter changes alter the measured outcome.",
        "qualitative_cases": "Selected cases illustrate typical and failure behavior.",
    }
    return defaults[role]


def _reader_question(role: str) -> str:
    return {
        "method_architecture": "How does the method transform inputs into outputs?",
        "study_or_experiment_design": "How is the study or experiment designed end to end?",
        "quantitative_comparison": "How do the methods compare on the reported metrics?",
        "ablation_or_sensitivity": "Which components or settings change the outcome?",
        "qualitative_cases": "What do representative cases show?",
    }[role]


def _score(
    *,
    role: str,
    venue: str,
    available: list[str],
    missing: list[str],
    covered_roles: set[str],
    table_covers_comparison: bool,
) -> dict[str, Any]:
    reader_value = 3 if available and not missing else 2 if available else 1
    evidence_completeness = 3 if available and not missing else 2 if available else 0
    venue_fit = int(_VENUE_FIT.get(venue, {}).get(role, 0))
    execution_feasibility = 2 if available and not missing else 1 if available else 0
    redundancy = 0
    if role in covered_roles:
        redundancy += 2
    if role == "quantitative_comparison" and table_covers_comparison:
        redundancy += 1
    total = (
        reader_value
        + evidence_completeness
        + venue_fit
        + execution_feasibility
        - redundancy
    )
    return {
        "reader_value": reader_value,
        "evidence_completeness": evidence_completeness,
        "venue_fit": venue_fit,
        "execution_feasibility": execution_feasibility,
        "redundancy_penalty": redundancy,
        "total": total,
    }


def _priority(total: int) -> str:
    if total >= 8:
        return "high"
    if total >= 5:
        return "medium"
    return "low"


def _opportunities(
    task: Mapping[str, Any],
    signals: Mapping[str, Any],
    inventory: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    venue = str(task["target_venue"])
    covered = {
        str(item["role"])
        for item in inventory
        if item.get("decision") == "keep" and item.get("role")
    }
    table_covers = bool(signals["tables"]) and bool(signals["records"])
    out: list[dict[str, Any]] = []
    for role in FIGURE_ROLES:
        available, missing, boundary = _role_evidence(role, signals)
        inventory_hit = any(item.get("role") == role for item in inventory)
        if not available and not inventory_hit:
            continue
        score = _score(
            role=role,
            venue=venue,
            available=available,
            missing=missing,
            covered_roles=covered,
            table_covers_comparison=table_covers,
        )
        reasons = [
            f"reader_value={score['reader_value']}",
            f"evidence_completeness={score['evidence_completeness']}",
            f"venue_fit={score['venue_fit']}",
            f"execution_feasibility={score['execution_feasibility']}",
            f"redundancy_penalty={score['redundancy_penalty']}",
            f"total={score['total']}",
        ]
        payload = {
            "schema_version": SCHEMA_FIGURE_OPPORTUNITY,
            "opportunity_id": f"opp:{role}",
            "role": role,
            "reader_question": _reader_question(role),
            "claim": _claim_for_role(role, signals),
            "evidence_boundary": boundary,
            "required_elements": list(available) + list(missing),
            "available_evidence": available,
            "missing_information": missing,
            "must_not_imply": _must_not_imply(boundary, venue),
            "priority": _priority(score["total"]),
            "priority_reasons": reasons,
            "score": score,
        }
        out.append(validate_figure_opportunity(payload))
    out.sort(
        key=lambda item: (
            -int(item["score"]["total"]),
            item["role"],
            item["opportunity_id"],
        )
    )
    return out


def _must_not_imply(boundary: str, venue: str) -> list[str]:
    banned = (
        ["observed_result"] if boundary in {"conceptual", "planned_protocol"} else []
    )
    if venue == VENUE_NPJ:
        banned.extend(["clinical_deployment", "clinical_utility"])
    if boundary != "evidence_backed":
        banned.append("statistical_significance")
    return list(dict.fromkeys(banned))


def _assessment(
    task: Mapping[str, Any],
    signals: Mapping[str, Any],
    inventory: list[Mapping[str, Any]],
    opportunities: list[Mapping[str, Any]],
) -> dict[str, Any]:
    context_type = str(task["context_type"])
    missing: list[str] = []
    if context_type == "existing_figure" and not inventory:
        missing.append("existing_figure_asset")
    usable_claims = [
        str(c.get("text") or c.get("claim_id") or "claim") for c in signals["claims"]
    ]
    usable_records = [
        str(r.get("record_id") or r.get("metric") or "record")
        for r in signals["records"]
    ]
    usable_assets = [str(item["asset_id"]) for item in inventory]
    feasible = [
        o for o in opportunities if int(o["score"]["execution_feasibility"]) > 0
    ]
    asked = str(task.get("requested_action") or "create")

    if missing or (asked == "create" and not feasible and not inventory):
        if not missing:
            missing.append("decisive_evidence_for_requested_figure")
        status = "insufficient"
        allowed = "none"
        question = _question(missing, context_type)
    elif context_type == "partial_context" or any(
        o.get("missing_information") for o in feasible
    ):
        status = "partially_sufficient"
        allowed = _allowed_scope(feasible, context_type)
        question = None
        if not feasible and inventory:
            status = "partially_sufficient"
            allowed = "existing_figure_diagnosis"
    elif (
        context_type == "existing_figure"
        and all(i["decision"] == "keep" for i in inventory)
        and asked == "diagnose"
    ):
        status = "sufficient"
        allowed = "existing_figure_keep"
        question = None
    else:
        status = "sufficient"
        allowed = "top_one_figure_package"
        question = None

    if any(i["decision"] == "request_information" for i in inventory) and not feasible:
        status = "insufficient"
        missing = list(dict.fromkeys([*missing, "figure_asset_or_caption"]))
        allowed = "none"
        question = _question(missing, context_type)

    payload = {
        "schema_version": SCHEMA_CONTEXT_ASSESSMENT,
        "status": status,
        "usable_claims": usable_claims,
        "usable_records": usable_records,
        "usable_assets": usable_assets,
        "missing_decisive_information": missing,
        "allowed_scope": allowed,
        "question": question,
    }
    return validate_context_assessment(payload)


def _allowed_scope(feasible: list[Mapping[str, Any]], context_type: str) -> str:
    if not feasible:
        return "none"
    role = str(feasible[0]["role"])
    if context_type == "partial_context":
        return f"partial:{role}"
    return f"top_one:{role}"


def _question(missing: list[str], context_type: str) -> str:
    if "existing_figure_asset" in missing:
        return "Supply the existing figure asset, caption, and body references."
    if "comparison_records" in missing:
        return "Supply the comparison records (methods, metrics, values, units)."
    if "method_description" in missing:
        return "Supply the method stages or architecture description."
    if "figure_asset_or_caption" in missing:
        return "Supply the figure bytes or a caption that identifies the figure."
    if context_type == "partial_context":
        return (
            "Supply the missing fact that determines the figure's scientific meaning."
        )
    return "Supply method, results records, or an existing figure to rank a figure opportunity."


def _select(
    task: Mapping[str, Any],
    assessment: Mapping[str, Any],
    inventory: list[Mapping[str, Any]],
    opportunities: list[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if assessment["status"] == "insufficient":
        return None
    action = str(task["requested_action"])
    if action in {"diagnose", "improve"} and inventory:
        order = {"redraw": 0, "request_information": 1, "improve": 2, "keep": 3}
        item = sorted(inventory, key=lambda row: order[str(row["decision"])])[0]
        if action == "improve" and item["decision"] == "keep":
            pass
        else:
            role = item.get("role") or (
                opportunities[0]["role"] if opportunities else "method_architecture"
            )
            match = next((o for o in opportunities if o["role"] == role), None)
            if match is None:
                match = validate_figure_opportunity(
                    {
                        "schema_version": SCHEMA_FIGURE_OPPORTUNITY,
                        "opportunity_id": f"opp:existing:{item['figure_id']}",
                        "role": role if role in FIGURE_ROLES else "method_architecture",
                        "reader_question": _reader_question(
                            role if role in FIGURE_ROLES else "method_architecture"
                        ),
                        "claim": f"Existing figure {item['figure_id']} requires {item['decision']}.",
                        "evidence_boundary": "mixed",
                        "priority": "high"
                        if item["decision"] in {"redraw", "improve"}
                        else "medium",
                        "existing_decision": item["decision"],
                    }
                )
            else:
                match = dict(match)
                match["existing_decision"] = item["decision"]
            return match
    feasible = [
        o for o in opportunities if int(o["score"]["execution_feasibility"]) > 0
    ]
    if not feasible:
        return None
    chosen = dict(feasible[0])
    keep_roles = {
        str(i["role"])
        for i in inventory
        if i.get("decision") == "keep" and i.get("role")
    }
    if chosen["role"] in keep_roles and inventory:
        chosen["existing_decision"] = "keep"
    return chosen
