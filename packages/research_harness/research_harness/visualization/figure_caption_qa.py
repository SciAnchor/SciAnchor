"""UF08 caption realization and bidirectional QA.

Deterministic. No VLM. Failures retain authority over advisory review.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .figure_package_contracts import (
    SCHEMA_VALIDATION_REPORT,
    validate_caption_contract,
    validate_figure_design_contract,
    validate_validation_report,
)

_OBS_RE = re.compile(
    r"\b(observed|showed|achieved|outperformed|was measured|were measured)\b",
    re.I,
)
_EXT_RE = re.compile(
    r"external validation|independently reproduced|independent cohort",
    re.I,
)
_SIG_RE = re.compile(r"\bp\s*[<=>]|significant|\*|†", re.I)
_N_RE = re.compile(r"\b(?:n|N)\s*=\s*(\d+)")
_PANEL_RE = re.compile(r"\(([A-Z])\)|(?:panel)\s+([A-Z])\b", re.I)
_ABBR_USE_RE = re.compile(r"\b([A-Z]{2,8})\s*\(([^)]+)\)")


def realize_caption(
    *,
    caption_contract: Mapping[str, Any],
    design_contract: Mapping[str, Any],
    records: list[Mapping[str, Any]] | None = None,
    render: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    caption = validate_caption_contract(caption_contract)
    design = validate_figure_design_contract(design_contract)
    records = [r for r in (records or []) if isinstance(r, Mapping)]
    render = dict(render or {})
    lines = [f"Figure. {caption['one_sentence_claim']}"]
    for panel in caption["panel_descriptions"]:
        lines.append(f"({panel['panel_id']}) {panel['description']}")
    marks = list(caption.get("visual_encoding") or [])
    if marks:
        encoded = "; ".join(
            f"{m.get('visual_mark')}: {m.get('meaning')}" for m in marks
        )
        lines.append(f"Visual encoding: {encoded}.")
    if caption.get("population_or_dataset"):
        lines.append(f"Data/setting: {caption['population_or_dataset']}.")
    if caption.get("measurement_and_units"):
        lines.append(f"Measurement: {caption['measurement_and_units']}.")
    if caption.get("uncertainty_definition"):
        lines.append(f"Uncertainty: {caption['uncertainty_definition']}.")
    n = _record_n(records, render)
    if n is not None:
        lines.append(f"n={n}.")
    if caption.get("scope_limitations"):
        lines.append("Scope: " + "; ".join(caption["scope_limitations"]) + ".")
    text = "\n".join(lines)
    updated = dict(caption)
    updated["caption_status"] = "draft"
    updated["realized_from"] = {
        "figure_id": design["figure_id"],
        "render_panels": _render_panels(design, render),
        "record_count": len(records),
    }
    return {
        "caption_text": text,
        "caption_contract": validate_caption_contract(updated),
    }


def check_figure_caption_evidence(
    *,
    caption_contract: Mapping[str, Any],
    caption_text: str,
    design_contract: Mapping[str, Any],
    records: list[Mapping[str, Any]] | None = None,
    render: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    caption = validate_caption_contract(caption_contract)
    design = validate_figure_design_contract(design_contract)
    records = [r for r in (records or []) if isinstance(r, Mapping)]
    render = dict(render or {})
    text = str(caption_text or "")
    findings_fc = _figure_to_caption(caption, design, render)
    findings_cf = _caption_to_figure(caption, design, render, text, records)
    findings_ec = _evidence_to_claim(caption, design, render, text, records)
    checks = [
        _check("figure_to_caption", findings_fc),
        _check("caption_to_figure", findings_cf),
        _check("evidence_to_claim", findings_ec),
    ]
    failed = [c for c in checks if c["verdict"] == "fail"]
    status = "fail" if failed else "pass"
    updated = dict(caption)
    updated["caption_status"] = "rejected" if status == "fail" else "validated"
    return {
        "caption_contract": validate_caption_contract(updated),
        "validation": validate_validation_report(
            {
                "schema_version": SCHEMA_VALIDATION_REPORT,
                "status": status,
                "checks": checks,
            }
        ),
    }


def _figure_to_caption(
    caption: Mapping[str, Any],
    design: Mapping[str, Any],
    render: Mapping[str, Any],
) -> list[str]:
    findings: list[str] = []
    described = {
        str(p.get("panel_id"))
        for p in caption.get("panel_descriptions") or []
        if str(p.get("description") or "").strip()
    }
    for panel_id in _render_panels(design, render):
        if panel_id not in described:
            findings.append(f"missing_panel_description:{panel_id}")
    caption_marks = {
        str(m.get("visual_mark") or "").strip().lower()
        for m in caption.get("visual_encoding") or []
        if m.get("visual_mark")
    }
    for mark in _render_marks(design, render):
        if mark not in caption_marks:
            findings.append(f"undefined_encoding:{mark}")
    return findings


def _caption_to_figure(
    caption: Mapping[str, Any],
    design: Mapping[str, Any],
    render: Mapping[str, Any],
    text: str,
    records: list[Mapping[str, Any]],
) -> list[str]:
    findings: list[str] = []
    panels = set(_render_panels(design, render))
    named = {
        str(p.get("panel_id"))
        for p in caption.get("panel_descriptions") or []
        if p.get("panel_id")
    }
    named.update(p for a, b in _PANEL_RE.findall(text) for p in (a, b) if p)
    for panel_id in sorted(named):
        if panel_id not in panels:
            findings.append(f"nonexistent_panel:{panel_id}")
    if _SIG_RE.search(text) and not _has_significance(records, render):
        findings.append("nonexistent_significance_mark")
    return findings


def _evidence_to_claim(
    caption: Mapping[str, Any],
    design: Mapping[str, Any],
    render: Mapping[str, Any],
    text: str,
    records: list[Mapping[str, Any]],
) -> list[str]:
    findings: list[str] = []
    units = _record_units(records, render)
    stated = str(
        caption.get("measurement_and_units") or render.get("units") or ""
    ).lower()
    if units and stated and not any(u in stated or u in text.lower() for u in units):
        findings.append("axis_unit_mismatch")
    expected_n = _record_n(records, render)
    mentioned = [int(m) for m in _N_RE.findall(text)]
    if expected_n is not None and mentioned and expected_n not in mentioned:
        findings.append(f"wrong_sample_size:{mentioned[0]}!={expected_n}")
    boundary = str(design.get("evidence_boundary") or "")
    if boundary in {"conceptual", "planned_protocol"} and _OBS_RE.search(text):
        findings.append("planned_observed_confusion")
    if _EXT_RE.search(text) and not _has_external(records, render):
        findings.append("external_validation_overclaim")
    findings.extend(_abbreviation_findings(caption, text, render))
    return findings


def _abbreviation_findings(
    caption: Mapping[str, Any],
    text: str,
    render: Mapping[str, Any],
) -> list[str]:
    catalog: dict[str, str] = {}
    for item in list(caption.get("abbreviations") or []) + list(
        render.get("abbreviations") or []
    ):
        if isinstance(item, Mapping) and item.get("term"):
            catalog[str(item["term"]).upper()] = (
                str(item.get("expansion") or "").strip().lower()
            )
    findings: list[str] = []
    for term, expansion in _ABBR_USE_RE.findall(text):
        expected = catalog.get(term.upper())
        if expected and expansion.strip().lower() != expected:
            findings.append(f"abbreviation_mismatch:{term}")
    return findings


def _render_panels(design: Mapping[str, Any], render: Mapping[str, Any]) -> list[str]:
    if render.get("panels"):
        return [
            str(p.get("panel_id") or p)
            for p in render["panels"]
            if str(p.get("panel_id") or p).strip()
        ]
    return [
        str(p.get("panel_id"))
        for p in design.get("panel_map") or []
        if p.get("panel_id")
    ]


def _render_marks(design: Mapping[str, Any], render: Mapping[str, Any]) -> list[str]:
    raw = list(render.get("encodings") or design.get("visual_encoding") or [])
    out: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            mark = str(item.get("visual_mark") or "")
            if not mark and item.get("values"):
                mark = str(list(item.get("values") or [""])[0])
            encoding = str(item.get("encoding") or "")
            if encoding in {"color", "marker"} and mark:
                out.append(mark.strip().lower())
            elif item.get("visual_mark") and mark:
                out.append(mark.strip().lower())
        elif str(item).strip():
            out.append(str(item).strip().lower())
    return out


def _record_units(
    records: list[Mapping[str, Any]], render: Mapping[str, Any]
) -> list[str]:
    units = [str(r.get("unit")).strip().lower() for r in records if r.get("unit")]
    if render.get("units"):
        units.append(str(render["units"]).strip().lower())
    return sorted({u for u in units if u})


def _record_n(
    records: list[Mapping[str, Any]], render: Mapping[str, Any]
) -> int | None:
    if render.get("sample_size") is not None:
        try:
            return int(render["sample_size"])
        except (TypeError, ValueError):
            return None
    for record in records:
        for key in ("sample_size", "n", "N"):
            if record.get(key) is not None:
                try:
                    return int(record[key])
                except (TypeError, ValueError):
                    continue
    return None


def _has_significance(
    records: list[Mapping[str, Any]], render: Mapping[str, Any]
) -> bool:
    if render.get("significance_marks"):
        return True
    return any(
        r.get("p_value") is not None or r.get("significance") or r.get("star")
        for r in records
    )


def _has_external(records: list[Mapping[str, Any]], render: Mapping[str, Any]) -> bool:
    if str(render.get("validation_kind") or "").lower() == "external":
        return True
    return any(
        str(r.get("validation") or r.get("validation_kind") or "").lower() == "external"
        for r in records
    )


def _check(check_id: str, findings: list[str]) -> dict[str, Any]:
    fail = bool(findings)
    return {
        "check_id": check_id,
        "execution_status": "completed",
        "verdict": "fail" if fail else "pass",
        "severity": "major" if fail else "info",
        "findings": findings,
        "evidence": [],
    }
