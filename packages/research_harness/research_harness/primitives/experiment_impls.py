"""Experiment primitive implementations — non-LLM operations.

code_validate, experiment_run, verified_registry_build, verified_registry_check.
(code_generate is LLM-powered, implemented in execution/llm_primitives.py)
"""

from __future__ import annotations

import logging
import math
from typing import Any

from ..experiment.sandbox import run_experiment
from ..experiment.validator import auto_fix_unbound_locals, validate_code
from ..experiment.verified_registry import (
    ALWAYS_ALLOWED,
    build_registry_from_metrics,
)
from ..storage.db import Database
from .registry import (
    CODE_VALIDATE_SPEC,
    EXPERIMENT_RUN_SPEC,
    VERIFIED_REGISTRY_BUILD_SPEC,
    VERIFIED_REGISTRY_CHECK_SPEC,
    register_primitive,
)
from .types import (
    CodeValidationIssue,
    CodeValidationOutput,
    ExperimentRunOutput,
    VerifiedRegistryCheckOutput,
    VerifiedRegistryOutput,
)

logger = logging.getLogger(__name__)


def _project_id_for_topic(db: Database, topic_id: int) -> int | None:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id FROM projects WHERE topic_id = ? ORDER BY id LIMIT 1",
            (topic_id,),
        ).fetchone()
        return int(row["id"]) if row is not None else None
    finally:
        conn.close()


@register_primitive(CODE_VALIDATE_SPEC)
def code_validate(
    *,
    code: str,
    auto_fix: bool = True,
    mode: str = "strict",
    **_: Any,
) -> CodeValidationOutput:
    """Validate experiment code: syntax, security, imports.

    mode="agent" is refused: confined experiments have no network.
    """
    auto_fixed = 0
    if auto_fix:
        code, n = auto_fix_unbound_locals(code)
        auto_fixed = n

    result = validate_code(code, mode=mode)
    issues = [
        CodeValidationIssue(
            severity=i.severity,
            category=i.category,
            message=i.message,
            line=i.line,
        )
        for i in result.issues
    ]
    return CodeValidationOutput(
        ok=result.ok,
        issues=issues,
        summary=result.summary(),
        auto_fixed=auto_fixed,
    )


@register_primitive(EXPERIMENT_RUN_SPEC)
def experiment_run(
    *,
    code: str = "",
    files: dict[str, str] | None = None,
    entry_point: str = "main.py",
    env_vars: dict[str, str] | None = None,
    timeout_sec: float = 300.0,
    primary_metric: str = "",
    canonical_components: list[str] | None = None,
    ablation_components: list[str] | None = None,
    repeats: int = 0,
    variance_estimates: list[float] | None = None,
    acceptance_criteria: list[str] | None = None,
    evidence_kind: str = "",
    component_provenance: list[dict[str, Any]] | None = None,
    metric_direction: str = "maximize",
    **_: Any,
) -> ExperimentRunOutput:
    """Run experiment in local sandbox.

    Supports both single-file (``code``) and multi-file (``files``) inputs.
    ``env_vars`` are overlaid on the child's minimal environment; credential-named
    variables are refused, since the confined child has no network.
    """
    result = run_experiment(
        code=code or None,
        files=files,
        entry_point=entry_point,
        timeout_sec=timeout_sec,
        extra_env=env_vars,
    )

    primary_value = None
    if primary_metric and result.metrics:
        # Look for the primary metric in results
        for key, val in result.metrics.items():
            if key == primary_metric or key.endswith(f"/{primary_metric}"):
                primary_value = val
                break

    provenance = list(component_provenance or [])
    outcomes = (
        _derive_ablation_outcomes(
            metrics=result.metrics,
            primary_metric=primary_metric,
            canonical_components=list(canonical_components or []),
            ablation_components=list(ablation_components or []),
            repeats=repeats,
            variance_estimates=list(variance_estimates or []),
            acceptance_criteria=list(acceptance_criteria or []),
            evidence_kind=evidence_kind,
            component_provenance=provenance,
            metric_direction=metric_direction,
        )
        if result.returncode == 0 and not result.timed_out and not result.divergence
        else []
    )
    return ExperimentRunOutput(
        metrics=result.metrics,
        primary_metric_value=primary_value,
        primary_metric_name=primary_metric,
        elapsed_sec=result.elapsed_sec,
        returncode=result.returncode,
        timed_out=result.timed_out,
        divergence=result.divergence,
        code_hash=result.code_hash,
        stdout_tail=result.stdout[-1000:] if result.stdout else "",
        stderr_tail=result.stderr[-500:] if result.stderr else "",
        canonical_components=list(canonical_components or []),
        ablation_components=list(ablation_components or []),
        repeats=repeats,
        variance_estimates=list(variance_estimates or []),
        acceptance_criteria=list(acceptance_criteria or []),
        evidence_kind=evidence_kind,
        component_provenance=provenance,
        metric_direction=metric_direction,
        ablation_outcomes=outcomes,
    )


def _derive_ablation_outcomes(
    *,
    metrics: dict[str, float],
    primary_metric: str,
    canonical_components: list[str],
    ablation_components: list[str],
    repeats: int,
    variance_estimates: list[float],
    acceptance_criteria: list[str],
    evidence_kind: str,
    component_provenance: list[dict[str, Any]],
    metric_direction: str,
) -> list[dict[str, Any]]:
    """Derive provenance-bound removal outcomes from observed sandbox metrics."""
    from research_harness.experiment.coverage_gate import (
        _valid_component_provenance,
        evaluate_ablation_contract,
    )

    gate = evaluate_ablation_contract(
        canonical_components=tuple(canonical_components),
        ablation_components=tuple(ablation_components),
        repeats=repeats,
        acceptance_criteria=tuple(acceptance_criteria),
        variance_estimates=tuple(variance_estimates),
        evidence_kind=evidence_kind,
    )
    if (
        gate["verdict"] != "pass"
        or not gate["has_comparable_variance"]
        or not primary_metric
        or metric_direction not in {"maximize", "minimize"}
        or not _valid_component_provenance(component_provenance, canonical_components)
    ):
        return []
    full = metrics.get(f"full/{primary_metric}")
    if not isinstance(full, (int, float)) or not math.isfinite(full):
        return []

    outcomes = []
    for index, (component, variance, provenance) in enumerate(
        zip(
            canonical_components,
            variance_estimates,
            component_provenance,
            strict=True,
        ),
        1,
    ):
        without = metrics.get(f"without_{index}/{primary_metric}")
        if not isinstance(without, (int, float)) or not math.isfinite(without):
            return []
        signed_effect = (
            without - full if metric_direction == "maximize" else full - without
        )
        noise_bound = math.sqrt(variance)
        if math.isclose(abs(signed_effect), noise_bound):
            removal_effect = "inconclusive"
        elif signed_effect > noise_bound:
            removal_effect = "helped"
        elif signed_effect < -noise_bound:
            removal_effect = "hurt"
        else:
            removal_effect = "inconclusive"
        outcomes.append(
            {
                "component_family": component,
                "removal_effect": removal_effect,
                "provenance_tag": provenance["provenance_tag"],
                "source_paper_id": provenance.get("source_paper_id"),
                "evidence": (
                    f"observed {primary_metric}: full={full}, "
                    f"without_{index}={without}, direction={metric_direction}, "
                    f"noise_bound={noise_bound}"
                ),
            }
        )
    return outcomes


@register_primitive(VERIFIED_REGISTRY_BUILD_SPEC)
def verified_registry_build(
    *,
    db: Database,
    topic_id: int,
    metrics: dict[str, float],
    primary_metric_name: str = "",
    **_: Any,
) -> VerifiedRegistryOutput:
    """Build verified number registry from experiment metrics and persist to DB."""
    registry = build_registry_from_metrics(metrics, primary_metric_name)

    # Persist to DB
    conn = db.connect()
    try:
        project_id = _project_id_for_topic(db, topic_id)
        # Clear previous entries for this topic (use topic_id in both columns for compat)
        conn.execute("DELETE FROM verified_numbers WHERE topic_id = ?", (topic_id,))
        for number, source in registry.values.items():
            # Compute variants
            rounded = round(number, 2)
            pct = number * 100.0 if 0.0 < abs(number) <= 1.0 else None
            inv = number / 100.0 if abs(number) > 1.0 else None
            conn.execute(
                """INSERT INTO verified_numbers
                   (project_id, topic_id, source, number_original, number_rounded, number_percentage, number_inverse)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, topic_id, source[:200], number, rounded, pct, inv),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed to persist verified numbers: %s", exc)
    finally:
        conn.close()

    return VerifiedRegistryOutput(
        whitelist_size=registry.size,
        condition_names=sorted(registry.condition_names),
        primary_metric=registry.primary_metric,
        primary_metric_name=primary_metric_name,
    )


@register_primitive(VERIFIED_REGISTRY_CHECK_SPEC)
def verified_registry_check(
    *,
    db: Database,
    topic_id: int,
    numbers: list[float],
    tolerance: float = 0.01,
    **_: Any,
) -> VerifiedRegistryCheckOutput:
    """Check numbers against the verified registry whitelist."""
    # Load registry from DB
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT number_original, source FROM verified_numbers WHERE topic_id = ?",
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    # Build in-memory registry
    registry = build_registry_from_metrics({})
    for row in rows:
        registry.add_value(row["number_original"], row["source"])

    verified: list[float] = []
    unverified: list[float] = []
    always_allowed: list[float] = []

    for n in numbers:
        if n in ALWAYS_ALLOWED:
            always_allowed.append(n)
        elif registry.is_verified(n, tolerance):
            verified.append(n)
        else:
            unverified.append(n)

    total = len(numbers)
    pass_rate = (len(verified) + len(always_allowed)) / total if total > 0 else 1.0

    return VerifiedRegistryCheckOutput(
        verified=verified,
        unverified=unverified,
        always_allowed=always_allowed,
        pass_rate=pass_rate,
        total_checked=total,
    )
