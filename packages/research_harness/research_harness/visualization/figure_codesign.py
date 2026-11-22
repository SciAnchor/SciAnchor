"""UF05 figure and caption co-design.

Contracts and caption skeleton only. No rendering, no final caption from bytes.
"""

from __future__ import annotations

from typing import Any, Mapping

from .figure_package_contracts import (
    SCHEMA_CAPTION,
    SCHEMA_FIGURE_DESIGN,
    normalize_venue,
    validate_caption_contract,
    validate_figure_design_contract,
    validate_figure_opportunity,
)

_ROLE_PANELS = {
    "method_architecture": (
        ("A", "Named stages from input to output."),
        ("B", "Interfaces and information flow between stages."),
    ),
    "study_or_experiment_design": (
        ("A", "Protocol path from intake to endpoint."),
        ("B", "Inclusion, timing, and decision gates."),
    ),
    "quantitative_comparison": (
        ("A", "Primary metric comparison across named methods."),
        ("B", "Secondary metric or dataset confirmation."),
    ),
    "ablation_or_sensitivity": (
        ("A", "Component or setting change versus the measured outcome."),
        ("B", "Sensitivity around the selected operating point."),
    ),
    "qualitative_cases": (
        ("A", "Typical case with the intended reading."),
        ("B", "Failure or edge case with the same encoding."),
    ),
}

_ROLE_ENCODING = {
    "method_architecture": [
        {"encoding": "position", "meaning": "stage order", "values": ["left_to_right"]},
        {"encoding": "line", "meaning": "information flow", "values": ["solid_arrow"]},
    ],
    "study_or_experiment_design": [
        {
            "encoding": "position",
            "meaning": "protocol order",
            "values": ["top_to_bottom"],
        },
        {
            "encoding": "shape",
            "meaning": "decision versus process",
            "values": ["diamond", "box"],
        },
    ],
    "quantitative_comparison": [
        {
            "encoding": "position",
            "meaning": "method identity",
            "values": ["grouped_bars"],
        },
        {"encoding": "color", "meaning": "method family", "values": ["categorical"]},
    ],
    "ablation_or_sensitivity": [
        {"encoding": "position", "meaning": "setting value", "values": ["x_axis"]},
        {
            "encoding": "line",
            "meaning": "measured outcome",
            "values": ["connected_points"],
        },
    ],
    "qualitative_cases": [
        {"encoding": "position", "meaning": "case identity", "values": ["grid"]},
        {
            "encoding": "marker",
            "meaning": "outcome class",
            "values": ["typical", "failure"],
        },
    ],
}


def codesign_figure(
    *,
    opportunity: Mapping[str, Any],
    target_venue: str,
    figure_id: str = "fig:1",
    records: list[Mapping[str, Any]] | None = None,
    assets: list[Mapping[str, Any]] | None = None,
    references: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    opp = validate_figure_opportunity(opportunity)
    venue = normalize_venue(target_venue)
    role = str(opp["role"])
    boundary = str(opp["evidence_boundary"])
    claim = str(opp["claim"])
    forbidden = list(opp.get("must_not_imply") or [])
    available = [str(x) for x in list(opp.get("available_evidence") or [])]
    records = [r for r in (records or []) if isinstance(r, Mapping)]
    assets = [a for a in (assets or []) if isinstance(a, Mapping)]
    references = [r for r in (references or []) if isinstance(r, Mapping)]

    panels = _panels(role, available, records)
    route = _route(role, boundary, assets, opp)
    encodings = list(_ROLE_ENCODING[role])
    design = validate_figure_design_contract(
        {
            "schema_version": SCHEMA_FIGURE_DESIGN,
            "figure_id": figure_id,
            "role": role,
            "one_sentence_claim": claim,
            "evidence_boundary": boundary,
            "panel_map": panels,
            "visual_encoding": encodings,
            "layout": {
                "reading_order": "A then B" if len(panels) > 1 else "A",
                "hero_panel": panels[0]["panel_id"],
                "supporting_panels": [p["panel_id"] for p in panels[1:]],
            },
            "references": [
                {
                    "reference_id": r.get("reference_id"),
                    "transferable": r.get("transferable"),
                }
                for r in references
                if r.get("reference_id")
            ],
            "render_route": route,
            "target_venue": venue,
            "venue_recipe": {"profile": venue},
            "forbidden_inferences": forbidden,
        }
    )
    caption = _caption(
        figure_id, claim, boundary, panels, encodings, forbidden, records
    )
    return {
        "design_contract": design,
        "caption_contract": caption,
        "caption_skeleton": _skeleton(caption, boundary),
        "render_route": route,
    }


def _panels(
    role: str,
    available: list[str],
    records: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    specs = list(_ROLE_PANELS[role])
    # ponytail: the second panel confirms on a second metric or dataset. One
    # record set has nothing to confirm, so it is not drawn twice.
    # ISSUE-figure-package-not-wired-2026-09-30.
    facets = {
        k
        for r in records
        for k in r
        if k not in ("value", "dataset", "method", "metric")
    }
    if (
        role in {"quantitative_comparison", "ablation_or_sensitivity"}
        and len(facets) <= 1
    ):
        specs = specs[:1]
    if role == "method_architecture" and "method_description" not in available:
        specs = specs[:1]
    out = []
    for panel_id, purpose in specs:
        out.append(
            {
                "panel_id": panel_id,
                "purpose": purpose,
                "elements": available[:],
                "relations": [],
                "source_bindings": available[:],
                "allowed_claims": [purpose],
                "forbidden_inferences": [],
            }
        )
    return out


def _route(
    role: str,
    boundary: str,
    assets: list[Mapping[str, Any]],
    opp: Mapping[str, Any],
) -> str:
    decision = str(opp.get("existing_decision") or "")
    if decision == "keep" and assets:
        return "external_asset"
    if (
        role in {"quantitative_comparison", "ablation_or_sensitivity"}
        and boundary == "evidence_backed"
    ):
        return "deterministic"
    if role == "qualitative_cases" or boundary == "mixed":
        return "hybrid"
    return "generative"


def _caption(
    figure_id: str,
    claim: str,
    boundary: str,
    panels: list[Mapping[str, Any]],
    encodings: list[Mapping[str, Any]],
    forbidden: list[str],
    records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_CAPTION,
        "caption_id": f"cap:{figure_id}",
        "figure_id": figure_id,
        "one_sentence_claim": claim,
        "panel_descriptions": [
            {
                "panel_id": p["panel_id"],
                "description": p["purpose"],
                "required_terms": [],
                "source_bindings": list(p.get("source_bindings") or []),
            }
            for p in panels
        ],
        "visual_encoding": [
            {
                "visual_mark": str((e.get("values") or ["mark"])[0]),
                "meaning": e.get("meaning"),
                "source_binding": "design_contract",
            }
            for e in encodings
        ],
        "forbidden_claims": forbidden,
        "scope_limitations": [f"must_not_imply:{item}" for item in forbidden],
        "caption_status": "draft",
    }
    numeric = boundary == "evidence_backed" and bool(records)
    if numeric:
        payload["measurement_and_units"] = _measurement(records)
        payload["uncertainty_definition"] = "as recorded"
        payload["statistical_annotations"] = "only marks present in records"
        payload["population_or_dataset"] = str(
            records[0].get("dataset") or records[0].get("population") or "as recorded"
        )
    return validate_caption_contract(payload)


def _measurement(records: list[Mapping[str, Any]]) -> str:
    metrics = sorted({str(r.get("metric") or "") for r in records if r.get("metric")})
    units = sorted({str(r.get("unit") or "") for r in records if r.get("unit")})
    parts = []
    if metrics:
        parts.append("metrics=" + ",".join(metrics))
    if units:
        parts.append("units=" + ",".join(units))
    return "; ".join(parts) or "as recorded"


def _skeleton(caption: Mapping[str, Any], boundary: str) -> str:
    lines = [
        f"Figure. {caption['one_sentence_claim']}",
    ]
    for panel in caption["panel_descriptions"]:
        lines.append(f"({panel['panel_id']}) {panel['description']}")
    marks = caption.get("visual_encoding") or []
    if marks:
        encoded = "; ".join(
            f"{m.get('visual_mark')}: {m.get('meaning')}" for m in marks
        )
        lines.append(f"Visual encoding: {encoded}.")
    if boundary == "evidence_backed":
        if caption.get("population_or_dataset"):
            lines.append(f"Data/setting: {caption['population_or_dataset']}.")
        if caption.get("measurement_and_units"):
            lines.append(f"Measurement: {caption['measurement_and_units']}.")
        if caption.get("uncertainty_definition"):
            lines.append(
                f"Uncertainty/statistics: {caption['uncertainty_definition']}."
            )
    if caption.get("scope_limitations"):
        lines.append("Scope: " + "; ".join(caption["scope_limitations"]) + ".")
    return "\n".join(lines)
