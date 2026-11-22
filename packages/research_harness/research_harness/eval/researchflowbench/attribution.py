"""Failure attribution for ResearchFlowBench score reports."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def attribute_score_report_failures(
    score_report: dict[str, Any],
    *,
    evidence_state: str = "",
) -> dict[str, Any]:
    """Group score outcomes by RH axis without changing optimization state."""

    scores = score_report.get("scores") if isinstance(score_report, dict) else []
    score_items = scores if isinstance(scores, list) else []
    axis_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    evidence_states: Counter[str] = Counter()
    for score in score_items:
        if not isinstance(score, dict):
            continue
        state = _score_evidence_state(score, default=evidence_state)
        evidence_states[state] += 1
        axes = score.get("rh_axis_ids")
        axis_ids = axes if isinstance(axes, list) else []
        for axis_id in axis_ids:
            if isinstance(axis_id, str) and axis_id:
                axis_records[axis_id].append(score)

    return {
        "schema_version": "researchflowbench.failure_attribution.v0.1",
        "benchmark_id": str(score_report.get("benchmark_id") or ""),
        "split": str(score_report.get("split") or ""),
        "score_count": len(score_items),
        "evidence_state": _report_evidence_state(evidence_states, evidence_state),
        "evidence_state_counts": dict(sorted(evidence_states.items())),
        "model_execution_performed": bool(
            score_report.get("model_execution_performed")
        ),
        "automatic_mutation_enabled": False,
        "axis_attribution": [
            _axis_summary(axis_id, records, evidence_state=evidence_state)
            for axis_id, records in sorted(axis_records.items())
        ],
        "blockers": _report_blockers(score_items),
    }


def attribute_score_report_file(
    score_file: str | Path,
    *,
    evidence_state: str = "",
) -> dict[str, Any]:
    """Load a score report JSON and return RH-axis attribution."""

    path = Path(score_file)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"score report must be a JSON object: {path}")
    report = attribute_score_report_failures(payload, evidence_state=evidence_state)
    report["source_file"] = str(path)
    return report


def write_failure_attribution_report(
    report: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Write an attribution report with deterministic formatting."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _axis_summary(
    axis_id: str,
    records: list[dict[str, Any]],
    *,
    evidence_state: str = "",
) -> dict[str, Any]:
    numeric_metrics = _numeric_metric_names(records)
    metric_means = {
        metric: _mean(
            float((record.get("metrics") or {}).get(metric) or 0.0)
            for record in records
        )
        for metric in numeric_metrics
    }
    failing_task_ids = [
        str(record.get("task_id") or "")
        for record in records
        if _is_failure(record, evidence_state=evidence_state)
    ]
    return {
        "rh_axis_id": axis_id,
        "score_count": len(records),
        "failure_count": len(failing_task_ids),
        "failure_rate": round(len(failing_task_ids) / len(records), 6)
        if records
        else 0.0,
        "metric_means": metric_means,
        "failing_task_ids": failing_task_ids,
        "evidence_state_counts": dict(
            sorted(
                Counter(
                    _score_evidence_state(record, default=evidence_state)
                    for record in records
                ).items()
            )
        ),
    }


def _numeric_metric_names(records: list[dict[str, Any]]) -> tuple[str, ...]:
    names: list[str] = []
    for record in records:
        metrics = record.get("metrics")
        if not isinstance(metrics, dict):
            continue
        for key, value in metrics.items():
            if isinstance(key, str) and isinstance(value, (int, float, bool)):
                names.append(key)
    return tuple(dict.fromkeys(names))


def _is_failure(record: dict[str, Any], *, evidence_state: str = "") -> bool:
    state = _score_evidence_state(record, default=evidence_state)
    if state.startswith("blocked"):
        return True
    metrics = record.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return True
    combined_score = metrics.get("combined_score")
    if isinstance(combined_score, (int, float, bool)):
        return float(combined_score) <= 0.0
    numeric_values = [
        float(value)
        for value in metrics.values()
        if isinstance(value, (int, float, bool))
    ]
    return bool(numeric_values) and max(numeric_values) <= 0.0


def _score_evidence_state(score: dict[str, Any], *, default: str) -> str:
    return str(score.get("evidence_state") or default or "unknown")


def _report_evidence_state(states: Counter[str], default: str) -> str:
    if not states:
        return default or "unknown"
    if len(states) == 1:
        return next(iter(states))
    if any(state.startswith("blocked") for state in states):
        return "blocked_mixed"
    if "real_data" in states:
        return "real_data_mixed"
    return "fixture_only_mixed"


def _report_blockers(scores: list[Any]) -> list[str]:
    blockers: list[str] = []
    for score in scores:
        if not isinstance(score, dict):
            continue
        score_blockers = score.get("blockers")
        if isinstance(score_blockers, list):
            blockers.extend(str(item) for item in score_blockers if item)
    return sorted(dict.fromkeys(blockers))


def _mean(values: Any) -> float:
    items = list(values)
    return round(sum(items) / len(items), 6) if items else 0.0
