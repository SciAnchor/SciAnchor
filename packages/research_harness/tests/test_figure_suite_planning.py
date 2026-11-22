"""S2: planned-inventory synthesis, logging requirements, reconcile diff.

All deterministic — the DB is a tiny in-memory fake mirroring the goal_pool /
project_artifacts shapes the synthesizer reads."""

from __future__ import annotations

import json

import pytest

from research_harness.visualization.figure_suite_planning import (
    derive_logging_requirements,
    reconcile,
    synthesize_planned_inventory,
)


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Row(dict):
    def __getitem__(self, k):
        return dict.get(self, k)


class _Conn:
    def __init__(self, goals, artifacts):
        self._goals = goals
        self._artifacts = artifacts

    def execute(self, sql, params=None):
        if "FROM goal_pool" in sql:
            return _Cur(self._goals)
        if "FROM project_artifacts" in sql:
            atype = params[1]
            return _Cur(
                [
                    _Row({"payload_json": json.dumps(p)})
                    for (t, p) in self._artifacts
                    if t == atype
                ]
            )
        return _Cur([])

    def close(self):
        pass


class _DB:
    def __init__(self, goals=None, artifacts=None):
        self._goals = [_Row(g) for g in (goals or [])]
        self._artifacts = artifacts or []

    def connect(self):
        return _Conn(self._goals, self._artifacts)


# --------------------------------------------------------------------------- #
# Inventory fallback chain                                                     #
# --------------------------------------------------------------------------- #


def test_inventory_explicit_records_observed():
    records = [
        {
            "figure_type": "benchmark",
            "dataset": "DS",
            "method": "Ours",
            "metric": "F1",
            "value": 0.8,
        }
    ]
    inv = synthesize_planned_inventory(records=records)
    assert inv["source"] == "explicit_records" and inv["mode"] == "observed"
    assert inv["record_count"] == 1


def test_inventory_explicit_matrix_planned():
    inv = synthesize_planned_inventory(
        matrix_json={
            "datasets": ["A", "B"],
            "methods": ["Base", "Ours"],
            "metric": "F1",
        }
    )
    assert inv["source"] == "explicit_matrix" and inv["mode"] == "planned"
    assert inv["record_count"] == 4  # 2 datasets x 2 methods
    assert "Ours" in inv["methods"]


def test_inventory_observed_artifact_marks_observed():
    art = (
        "experiment_result",
        {
            "rows": [
                {"dataset": "BEAT", "method": "Ours", "metric": "LVE", "value": 5.4}
            ]
        },
    )
    inv = synthesize_planned_inventory(db=_DB(artifacts=[art]), topic_id=1)
    assert inv["mode"] == "observed"


def test_inventory_goal_pool_baselines_planned():
    goals = [
        {
            "dataset": "ETTh1",
            "metric_name": "MSE",
            "baseline_metric": 0.4,
            "target_metric_delta": -0.05,
            "target_venue": "AAAI",
        },
        {
            "dataset": "ETTh2",
            "metric_name": "MSE",
            "baseline_metric": 0.3,
            "target_metric_delta": -0.04,
            "target_venue": "AAAI",
        },
    ]
    baseline_art = (
        "baseline_matrix",
        {"baselines": [{"method": "PatchTST"}, {"method": "DLinear"}]},
    )
    inv = synthesize_planned_inventory(
        db=_DB(goals=goals, artifacts=[baseline_art]), topic_id=1
    )
    assert inv["source"] == "goal_pool_baselines" and inv["mode"] == "planned"
    # 2 datasets x 3 methods (PatchTST, DLinear, Ours)
    assert inv["figure_types"]["benchmark"] == 6
    assert "Ours" in inv["methods"]


def test_inventory_refuses_when_empty():
    with pytest.raises(ValueError, match="no experiment inventory"):
        synthesize_planned_inventory(db=_DB(), topic_id=1)


def test_inventory_records_take_precedence_over_db():
    records = [
        {
            "figure_type": "benchmark",
            "dataset": "DS",
            "method": "Ours",
            "metric": "F1",
            "value": 0.8,
        }
    ]
    goals = [
        {
            "dataset": "X",
            "metric_name": "M",
            "baseline_metric": 1.0,
            "target_metric_delta": 0.1,
        }
    ]
    inv = synthesize_planned_inventory(records=records, db=_DB(goals=goals), topic_id=1)
    assert inv["source"] == "explicit_records"


# --------------------------------------------------------------------------- #
# Logging requirements                                                        #
# --------------------------------------------------------------------------- #


def test_derive_logging_requirements():
    spec = {
        "figures": [
            {
                "figure_id": "fig:main",
                "panels": [
                    {"panel_id": "a", "chart": "grouped_bar"},
                    {"panel_id": "b", "chart": "convergence"},
                ],
            },
            {
                "figure_id": "fig:km",
                "panels": [{"panel_id": "a", "chart": "kaplan_meier"}],
            },
            {
                "figure_id": "fig:arch",
                "panels": [
                    {"panel_id": "a", "chart": "image", "pipeline": "generative"}
                ],
            },
        ]
    }
    reqs = derive_logging_requirements(spec)
    by_chart = {r["chart"]: r for r in reqs}
    assert (
        "grouped_bar" in by_chart and "line" in by_chart and "km_survival" in by_chart
    )
    # generative/image panel contributes no logging requirement
    assert "image" not in by_chart
    assert "value" in by_chart["grouped_bar"]["required_fields"]
    assert "std" in by_chart["grouped_bar"]["optional_fields"]
    assert "time" in by_chart["km_survival"]["required_fields"]
    assert "n>=3" in by_chart["grouped_bar"]["granularity"]


def test_derive_logging_requirements_dedupes():
    spec = {
        "figures": [
            {
                "figure_id": "f",
                "panels": [
                    {"panel_id": "a", "chart": "grouped_bar"},
                    {"panel_id": "b", "chart": "benchmark_bar"},
                ],
            }
        ]
    }  # alias → same chart
    reqs = derive_logging_requirements(spec)
    assert len([r for r in reqs if r["chart"] == "grouped_bar"]) == 1


# --------------------------------------------------------------------------- #
# Reconcile                                                                   #
# --------------------------------------------------------------------------- #


def _bench(metric="F1"):
    return [
        {
            "figure_type": "benchmark",
            "dataset": d,
            "method": m,
            "metric": metric,
            "value": v,
        }
        for d, mv in {"DS": {"Base": 0.7, "Ours": 0.8}}.items()
        for m, v in mv.items()
    ]


def test_reconcile_all_satisfied():
    spec = {
        "figures": [
            {
                "figure_id": "fig:m",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "grouped_bar",
                        "record_filter": {"figure_type": "benchmark"},
                    }
                ],
            }
        ]
    }
    result = reconcile(spec, _bench())
    assert result["verdict"] == "complete"
    assert result["satisfied"] == ["fig:m/a"]
    assert result["unsatisfied"] == [] and result["prune"] == []


def test_reconcile_prunes_unfeedable_figure():
    spec = {
        "figures": [
            {
                "figure_id": "fig:ok",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "grouped_bar",
                        "record_filter": {"figure_type": "benchmark"},
                    }
                ],
            },
            {
                "figure_id": "fig:km",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "km_survival",
                        "record_filter": {"figure_type": "survival"},
                    }
                ],
            },
        ]
    }
    result = reconcile(spec, _bench())  # no survival records
    assert "fig:km" in result["prune"]
    assert any(u["panel"] == "fig:km/a" for u in result["unsatisfied"])
    assert result["verdict"] == "gaps_found"


def test_reconcile_flags_unfed_figure_types():
    records = _bench() + [
        {
            "figure_type": "ablation",
            "dataset": "DS",
            "variant": "Full",
            "metric": "F1",
            "value": 0.8,
        }
    ]
    spec = {
        "figures": [
            {
                "figure_id": "fig:m",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "grouped_bar",
                        "record_filter": {"figure_type": "benchmark"},
                    }
                ],
            }
        ]
    }
    result = reconcile(spec, records)
    assert "ablation" in result["unfed_figure_types"]
    assert result["verdict"] == "gaps_found"


def test_reconcile_asset_panel_without_asset_unsatisfied():
    spec = {
        "figures": [
            {"figure_id": "fig:map", "panels": [{"panel_id": "a", "chart": "image"}]}
        ]
    }
    result = reconcile(spec, _bench())
    assert any(u["reason"] == "missing_asset" for u in result["unsatisfied"])


def test_reconcile_generative_panel_not_record_fed():
    spec = {
        "figures": [
            {
                "figure_id": "fig:arch",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "method_overview",
                        "pipeline": "generative",
                    }
                ],
            }
        ]
    }
    result = reconcile(spec, _bench())
    assert "fig:arch/a" in result["satisfied"]
    assert result["prune"] == []
