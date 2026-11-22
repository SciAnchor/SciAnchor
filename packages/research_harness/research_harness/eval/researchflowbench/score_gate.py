"""Score comparison gates for ResearchFlowBench optimization loops."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCORE_COMPARISON_GATE_SCHEMA_VERSION = "researchflowbench.score_comparison_gate.v0.1"
COUNT_METRICS = frozenset({"score_count", "blocked_score_count"})


def compare_score_reports(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    *,
    required_metrics: tuple[str, ...] = (),
    min_deltas: dict[str, float] | None = None,
    max_regression: float = 0.0,
) -> dict[str, Any]:
    """Compare two score reports and return a no-mutation gate decision."""

    baseline_metrics = _numeric_metrics(baseline_report)
    candidate_metrics = _numeric_metrics(candidate_report)
    metric_names = _metric_names(
        baseline_metrics,
        candidate_metrics,
        required_metrics=required_metrics,
    )
    thresholds = min_deltas or {}
    comparisons = [
        _metric_comparison(
            metric,
            baseline_metrics=baseline_metrics,
            candidate_metrics=candidate_metrics,
            required_min_delta=thresholds.get(metric, -max_regression),
        )
        for metric in metric_names
    ]
    blocked_delta = candidate_metrics.get(
        "blocked_score_count", 0.0
    ) - baseline_metrics.get("blocked_score_count", 0.0)
    blockers = [
        comparison["blocker"] for comparison in comparisons if comparison.get("blocker")
    ]
    if blocked_delta > 0:
        blockers.append("blocked_score_count_increased")

    status = "pass" if not blockers and comparisons else "fail"
    return {
        "schema_version": SCORE_COMPARISON_GATE_SCHEMA_VERSION,
        "status": status,
        "benchmark_id": str(
            candidate_report.get("benchmark_id")
            or baseline_report.get("benchmark_id")
            or ""
        ),
        "split": str(
            candidate_report.get("split") or baseline_report.get("split") or ""
        ),
        "baseline_id": str(
            baseline_report.get("runner_id") or baseline_report.get("baseline_id") or ""
        ),
        "candidate_id": str(
            candidate_report.get("runner_id")
            or candidate_report.get("baseline_id")
            or ""
        ),
        "metric_comparisons": comparisons,
        "blockers": blockers,
        "automatic_mutation_enabled": False,
        "mutation_performed": False,
        "policy": {
            "max_regression": max_regression,
            "min_deltas": dict(sorted(thresholds.items())),
            "required_metrics": list(required_metrics),
            "blocked_score_count_must_not_increase": True,
        },
    }


def compare_score_report_files(
    baseline_file: str | Path,
    candidate_file: str | Path,
    *,
    required_metrics: tuple[str, ...] = (),
    min_deltas: dict[str, float] | None = None,
    max_regression: float = 0.0,
) -> dict[str, Any]:
    baseline_path = Path(baseline_file)
    candidate_path = Path(candidate_file)
    baseline = _load_report(baseline_path)
    candidate = _load_report(candidate_path)
    gate = compare_score_reports(
        baseline,
        candidate,
        required_metrics=required_metrics,
        min_deltas=min_deltas,
        max_regression=max_regression,
    )
    gate["baseline_file"] = str(baseline_path)
    gate["candidate_file"] = str(candidate_path)
    return gate


def write_score_comparison_gate(
    report: dict[str, Any], output_path: str | Path
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def parse_metric_thresholds(items: tuple[str, ...]) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"metric threshold must be METRIC=VALUE: {item}")
        metric, raw_value = item.split("=", 1)
        metric = metric.strip()
        if not metric:
            raise ValueError(f"metric threshold is missing metric name: {item}")
        try:
            thresholds[metric] = float(raw_value)
        except ValueError as exc:
            raise ValueError(f"metric threshold value must be numeric: {item}") from exc
    return thresholds


def _numeric_metrics(report: dict[str, Any]) -> dict[str, float]:
    metrics = report.get("metrics")
    if isinstance(metrics, dict):
        return {
            str(key): float(value)
            for key, value in metrics.items()
            if isinstance(value, (int, float, bool))
        }
    return _aggregate_metrics_from_scores(report)


def _aggregate_metrics_from_scores(report: dict[str, Any]) -> dict[str, float]:
    scores = report.get("scores")
    if not isinstance(scores, list):
        return {}
    metric_names = tuple(
        dict.fromkeys(
            metric
            for score in scores
            if isinstance(score, dict)
            for metric, value in (score.get("metrics") or {}).items()
            if isinstance(metric, str) and isinstance(value, (int, float, bool))
        )
    )
    aggregates: dict[str, float] = {
        "score_count": float(len(scores)),
        "blocked_score_count": float(
            sum(
                1
                for score in scores
                if isinstance(score, dict)
                and str(score.get("evidence_state") or "").startswith("blocked")
            )
        ),
    }
    for metric in metric_names:
        values = [
            float((score.get("metrics") or {}).get(metric) or 0.0)
            for score in scores
            if isinstance(score, dict)
        ]
        aggregates[f"mean_{metric}"] = (
            round(sum(values) / len(values), 6) if values else 0.0
        )
    return aggregates


def _metric_names(
    baseline_metrics: dict[str, float],
    candidate_metrics: dict[str, float],
    *,
    required_metrics: tuple[str, ...],
) -> tuple[str, ...]:
    if required_metrics:
        return required_metrics
    return tuple(
        metric
        for metric in sorted(set(baseline_metrics) & set(candidate_metrics))
        if metric not in COUNT_METRICS
    )


def _metric_comparison(
    metric: str,
    *,
    baseline_metrics: dict[str, float],
    candidate_metrics: dict[str, float],
    required_min_delta: float,
) -> dict[str, Any]:
    missing = [
        label
        for label, metrics in (
            ("baseline", baseline_metrics),
            ("candidate", candidate_metrics),
        )
        if metric not in metrics
    ]
    if missing:
        return {
            "metric": metric,
            "passed": False,
            "blocker": f"metric_missing:{metric}:{','.join(missing)}",
        }

    baseline_value = baseline_metrics[metric]
    candidate_value = candidate_metrics[metric]
    delta = round(candidate_value - baseline_value, 6)
    passed = delta >= required_min_delta
    return {
        "metric": metric,
        "baseline": baseline_value,
        "candidate": candidate_value,
        "delta": delta,
        "required_min_delta": required_min_delta,
        "passed": passed,
        "blocker": "" if passed else f"metric_regression:{metric}",
    }


def _load_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"score report must be a JSON object: {path}")
    return data
