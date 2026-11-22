"""Deterministic experiment and manuscript coverage checks.

The manuscript check works on existing drafted-section artifacts. The ablation
evidence check is pure and preserves the canonical component order declared by
an experiment-design brief.
"""

from __future__ import annotations

import json
import math
import re
from typing import TYPE_CHECKING, Any

from research_harness.storage.db import Database

if TYPE_CHECKING:
    from research_harness.knowledge.experiment_design import ExperimentDesignBrief

EXPERIMENT_CATEGORIES: tuple[str, ...] = (
    "baseline",
    "ablation",
    "sensitivity",
    "explainability",
)

_CATEGORY_RE: dict[str, re.Pattern[str]] = {
    "baseline": re.compile(
        r"\bbaselines?\b|\bstate[- ]of[- ]the[- ]art\b|\bsota\b|\bcompared? (?:with|to|against)\b",
        re.IGNORECASE,
    ),
    "ablation": re.compile(r"\bablations?\b|\bablat", re.IGNORECASE),
    "sensitivity": re.compile(
        r"\bsensitivity analys[ie]s\b|\bhyper-?parameter sensitivity\b|"
        r"\brobustness (?:to|analysis)\b",
        re.IGNORECASE,
    ),
    "explainability": re.compile(
        r"\bexplainabilit|\binterpretab|\bfeature importance\b|\bsaliency\b|\bshap\b|"
        r"\battention map",
        re.IGNORECASE,
    ),
}

# Section names that mean "experiments are being written" — the trigger for the
# coverage check.
_EXPERIMENT_SECTION_RE = re.compile(
    r"experiment|result|evaluation|method", re.IGNORECASE
)
_SECTION_ARTIFACT_TYPES = ("section_draft", "draft_pack", "final_bundle")
_QUANTITATIVE_CRITERION_RE = re.compile(r"(?<![\w.])(?:\d+(?:\.\d+)?|\.\d+)\s*%?")
ABLATION_CONTRACT_FIELDS = (
    "canonical_components",
    "ablation_components",
    "repeats",
    "variance_estimates",
    "acceptance_criteria",
    "evidence_kind",
)
ABLATION_MEMORY_INPUT_FIELDS = ("component_provenance", "metric_direction")
ABLATION_MEMORY_RESULT_FIELD = "ablation_outcomes"


def evaluate_ablation_evidence(
    brief: ExperimentDesignBrief,
    *,
    ablation_components: tuple[str, ...],
    variance_estimates: tuple[float, ...] = (),
    evidence_kind: str = "final",
) -> dict[str, Any]:
    """Check final ablation coverage and effect-size variance discipline."""

    return evaluate_ablation_contract(
        canonical_components=brief.canonical_components,
        ablation_components=ablation_components,
        repeats=brief.repeats,
        acceptance_criteria=brief.acceptance_criteria,
        variance_estimates=variance_estimates,
        evidence_kind=evidence_kind,
    )


def evaluate_ablation_contract(
    *,
    canonical_components: tuple[str, ...],
    ablation_components: tuple[str, ...],
    repeats: int,
    acceptance_criteria: tuple[str, ...],
    variance_estimates: tuple[float, ...] = (),
    evidence_kind: str = "final",
) -> dict[str, Any]:
    """Evaluate the additive contract carried by an experiment result."""

    canonical = canonical_components
    missing = [
        component for component in canonical if component not in ablation_components
    ]
    extra = [
        component for component in ablation_components if component not in canonical
    ]
    duplicate = [
        component
        for index, component in enumerate(ablation_components)
        if component in ablation_components[:index]
        and component not in ablation_components[index + 1 :]
    ]
    blockers: list[str] = []
    if not canonical:
        blockers.append("canonical_components_missing")
    if evidence_kind != "final":
        blockers.append("non_final_evidence")
    if duplicate:
        blockers.append("duplicate_ablation_components")
    if ablation_components != canonical:
        blockers.append("ablation_component_mismatch")

    effect_size_claims = [
        criterion
        for criterion in acceptance_criteria
        if _QUANTITATIVE_CRITERION_RE.search(criterion)
    ]
    valid_variances = all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
        for value in variance_estimates
    )
    has_comparable_variance = (
        repeats > 1 and len(variance_estimates) == len(canonical) and valid_variances
    )
    if blockers:
        verdict = "blocked"
    elif effect_size_claims and not has_comparable_variance:
        verdict = "unclear"
    else:
        verdict = "pass"

    return {
        "verdict": verdict,
        "canonical_components": list(canonical),
        "ablation_components": list(ablation_components),
        "missing_components": missing,
        "extra_components": extra,
        "duplicate_components": duplicate,
        "order_matches": ablation_components == canonical,
        "evidence_kind": evidence_kind,
        "effect_size_claims": effect_size_claims,
        "repeats": repeats,
        "variance_estimate_count": len(variance_estimates),
        "has_comparable_variance": has_comparable_variance,
        "blockers": blockers,
    }


def evaluate_ablation_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Evaluate a result payload when it opts into the additive contract."""

    if not any(
        key in payload
        for key in (
            *ABLATION_CONTRACT_FIELDS,
            *ABLATION_MEMORY_INPUT_FIELDS,
            ABLATION_MEMORY_RESULT_FIELD,
        )
    ):
        return None
    canonical = payload.get("canonical_components")
    ablations = payload.get("ablation_components")
    repeats = payload.get("repeats")
    variances = payload.get("variance_estimates")
    criteria = payload.get("acceptance_criteria")
    evidence_kind = payload.get("evidence_kind")
    valid = (
        isinstance(canonical, list)
        and all(isinstance(value, str) and value for value in canonical)
        and isinstance(ablations, list)
        and all(isinstance(value, str) and value for value in ablations)
        and type(repeats) is int
        and repeats >= 0
        and isinstance(variances, list)
        and all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
            for value in variances
        )
        and isinstance(criteria, list)
        and all(isinstance(value, str) for value in criteria)
        and isinstance(evidence_kind, str)
        and bool(evidence_kind)
    )
    if not valid:
        return {"verdict": "blocked", "blockers": ["invalid_contract"]}
    result = evaluate_ablation_contract(
        canonical_components=tuple(canonical),
        ablation_components=tuple(ablations),
        repeats=repeats,
        acceptance_criteria=tuple(criteria),
        variance_estimates=tuple(variances),
        evidence_kind=evidence_kind,
    )
    if not any(
        key in payload
        for key in (*ABLATION_MEMORY_INPUT_FIELDS, ABLATION_MEMORY_RESULT_FIELD)
    ):
        return result
    provenance = payload.get("component_provenance")
    outcomes = payload.get(ABLATION_MEMORY_RESULT_FIELD)
    valid_memory = (
        result["verdict"] == "pass"
        and payload.get("metric_direction") in {"maximize", "minimize"}
        and _valid_component_provenance(provenance, canonical)
        and _valid_ablation_outcomes(outcomes, provenance)
    )
    if not valid_memory:
        return {"verdict": "blocked", "blockers": ["invalid_ablation_memory"]}
    return {**result, "ablation_outcomes": outcomes}


def _valid_component_provenance(value: Any, canonical: list[str]) -> bool:
    if not isinstance(value, list) or len(value) != len(canonical):
        return False
    for component, item in zip(canonical, value, strict=True):
        if not isinstance(item, dict) or item.get("component_family") != component:
            return False
        tag = item.get("provenance_tag")
        paper_id = item.get("source_paper_id")
        if tag == "novel":
            if paper_id is not None:
                return False
        elif tag in {"borrowed", "modified"}:
            if type(paper_id) is not int or paper_id <= 0:
                return False
        else:
            return False
    return True


def _valid_ablation_outcomes(value: Any, provenance: Any) -> bool:
    if not isinstance(value, list) or not isinstance(provenance, list):
        return False
    if len(value) != len(provenance):
        return False
    for outcome, source in zip(value, provenance, strict=True):
        if not isinstance(outcome, dict) or not isinstance(source, dict):
            return False
        if (
            outcome.get("component_family") != source.get("component_family")
            or outcome.get("provenance_tag") != source.get("provenance_tag")
            or outcome.get("source_paper_id") != source.get("source_paper_id")
            or outcome.get("removal_effect") not in {"helped", "hurt", "inconclusive"}
            or not isinstance(outcome.get("evidence"), str)
            or not outcome["evidence"].startswith("observed ")
        ):
            return False
    return True


def detect_experiment_categories(text: str) -> set[str]:
    """Return which experiment categories are discussed in ``text``."""
    if not text:
        return set()
    return {name for name, rx in _CATEGORY_RE.items() if rx.search(text)}


def _section_texts(db: Database, topic_id: int) -> tuple[str, bool]:
    conn = db.connect()
    try:
        rows = conn.execute(
            f"""
            SELECT artifact_type, title, payload_json
            FROM project_artifacts
            WHERE topic_id = ? AND status = 'active'
              AND artifact_type IN ({",".join("?" * len(_SECTION_ARTIFACT_TYPES))})
            """,
            (topic_id, *_SECTION_ARTIFACT_TYPES),
        ).fetchall()
    finally:
        conn.close()

    texts: list[str] = []
    has_experiment_section = False
    for row in rows:
        payload_text = str(row["payload_json"] or "")
        title = str(row["title"] or "")
        texts.append(f"{title} {payload_text}")
        try:
            payload = json.loads(payload_text)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        section_name = (
            str((payload or {}).get("section") or "")
            if isinstance(payload, dict)
            else ""
        )
        if _EXPERIMENT_SECTION_RE.search(f"{title} {section_name}"):
            has_experiment_section = True
    return "\n".join(texts), has_experiment_section


def experiment_coverage_findings(db: Database, topic_id: int) -> list[dict[str, Any]]:
    """Warn for each experiment category the manuscript does not discuss.

    Returns [] until an experiments/results/method section exists, so a topic
    that has not started drafting experiments is not spammed.
    """
    combined_text, has_experiment_section = _section_texts(db, topic_id)
    if not has_experiment_section:
        return []
    present = detect_experiment_categories(combined_text)
    findings: list[dict[str, Any]] = []
    for category in EXPERIMENT_CATEGORIES:
        if category not in present:
            findings.append(
                {
                    "category": category,
                    "severity": "warning",
                    "message": (
                        f"manuscript discusses no {category} experiments; the "
                        "write gate cannot confirm the claims are supported "
                        "without it (BUG-016)"
                    ),
                }
            )
    return findings
