"""Tests for the spec-driven (exemplar-anchored) figure-suite renderer."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from matplotlib.collections import PathCollection

from research_harness.visualization import experiment_figures as figure_renderer
from research_harness.visualization.experiment_figures import (
    PANEL_CHARTS,
    STYLE_PROFILES,
    canonical_chart_kind,
    chart_field_requirements,
    render_figure_suite_spec,
    resolve_style_profile,
    summarize_records_for_plan,
)


def _benchmark_records() -> list[dict[str, object]]:
    return [
        {
            "figure_type": "benchmark",
            "dataset": dataset,
            "method": method,
            "metric": "F1",
            "value": value,
        }
        for dataset, values in {
            "DS-A": {"Baseline": 0.71, "Prior": 0.74, "Ours": 0.81},
            "DS-B": {"Baseline": 0.66, "Prior": 0.70, "Ours": 0.78},
        }.items()
        for method, value in values.items()
    ]


def _ablation_records() -> list[dict[str, object]]:
    return [
        {
            "figure_type": "ablation",
            "dataset": dataset,
            "variant": variant,
            "metric": "F1",
            "value": value,
        }
        for dataset, values in {
            "DS-A": {"Full": 0.81, "- module X": 0.77, "- module Y": 0.75},
            "DS-B": {"Full": 0.78, "- module X": 0.74, "- module Y": 0.71},
        }.items()
        for variant, value in values.items()
    ]


def _line_records() -> list[dict[str, object]]:
    return [
        {"figure_type": "line", "series": series, "x": step, "y": value}
        for series, points in {
            "Ours": [(1, 0.61), (2, 0.72), (3, 0.79), (4, 0.81)],
            "Baseline": [(1, 0.55), (2, 0.63), (3, 0.68), (4, 0.70)],
        }.items()
        for step, value in points
    ]


def _forest_records() -> list[dict[str, object]]:
    return [
        {"figure_type": "forest", "label": label, "value": value, "lo": lo, "hi": hi}
        for label, value, lo, hi in [
            ("Education", 0.42, 0.21, 0.63),
            ("Income", 0.18, -0.02, 0.38),
            ("Urban residence", -0.11, -0.29, 0.07),
        ]
    ]


def _box_records() -> list[dict[str, object]]:
    return [
        {"figure_type": "box", "group": group, "value": value}
        for group, values in {
            "Ours": [0.79, 0.81, 0.80, 0.82, 0.78],
            "Baseline": [0.69, 0.71, 0.70, 0.68, 0.72],
        }.items()
        for value in values
    ]


def _suite_spec() -> dict[str, object]:
    return {
        "style_profile": "stem_conference",
        "figures": [
            {
                "figure_id": "fig:main_results",
                "title": "Main results",
                "composition": "1x2",
                "caption_skeleton": "(a) benchmark; (b) ablation.",
                "panels": [
                    {"panel_id": "a", "chart": "grouped_bar", "y_label": "F1"},
                    {"panel_id": "b", "chart": "heatmap"},
                ],
            },
            {
                "figure_id": "fig:analysis",
                "composition": {"rows": 1, "cols": 3},
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "convergence",
                        "x_label": "Epoch",
                        "y_label": "F1",
                    },
                    {
                        "panel_id": "b",
                        "chart": "forest_plot",
                        "ref": 0.0,
                        "x_label": "Effect size",
                    },
                    {"panel_id": "c", "chart": "boxplot", "y_label": "F1"},
                ],
            },
        ],
    }


def _all_records() -> list[dict[str, object]]:
    return (
        _benchmark_records()
        + _ablation_records()
        + _line_records()
        + _forest_records()
        + _box_records()
    )


def test_spec_suite_renders_multi_panel_figures(tmp_path: Path) -> None:
    suite = render_figure_suite_spec(
        spec=_suite_spec(),
        records=_all_records(),
        output_dir=tmp_path,
        suite_id="demo",
        claim_boundary="observed_or_reported_results",
    )

    assert suite.status == "rendered"
    assert suite.provenance["figure_count"] == 2
    assert suite.provenance["style_profile"] == "stem_conference"
    assert suite.provenance["spec_fingerprint"]
    assert suite.provenance["limitations"] == []

    by_id = {figure.figure_id: figure for figure in suite.figures}
    main = by_id["demo_fig_main_results"]
    assert main.figure_type == "multi_panel"
    assert [p["chart"] for p in main.provenance["panels"]] == ["grouped_bar", "heatmap"]
    assert main.provenance["style_profile"] == "stem_conference"
    assert main.provenance["caption_skeleton"].startswith("(a)")
    assert main.provenance["panels"][0]["uncertainty"] == "none"

    analysis = by_id["demo_fig_analysis"]
    assert [p["chart"] for p in analysis.provenance["panels"]] == [
        "line",
        "forest",
        "box",
    ]
    assert analysis.provenance["panels"][1]["ci"] is True

    for figure in suite.figures:
        path = Path(figure.paths["png"])
        assert path.exists() and path.stat().st_size > 1000


def test_spec_suite_accepts_plan_wrapper_and_all_style_profiles(
    tmp_path: Path,
) -> None:
    for profile in STYLE_PROFILES:
        wrapped = {"plan": {**_suite_spec(), "style_profile": profile}}
        suite = render_figure_suite_spec(
            spec=wrapped,
            records=_all_records(),
            output_dir=tmp_path / profile,
            suite_id=profile,
        )
        assert suite.status == "rendered"
        assert suite.provenance["style_profile"] == profile


def test_spec_suite_style_profile_override_and_fallback(tmp_path: Path) -> None:
    suite = render_figure_suite_spec(
        spec=_suite_spec(),
        records=_all_records(),
        output_dir=tmp_path,
        style_profile="nonexistent_venue_style",
    )
    assert suite.status == "rendered"
    assert suite.provenance["style_profile"] == "stem_conference"
    assert any(
        note.startswith("unknown_style_profile:")
        for note in suite.provenance["limitations"]
    )


def test_spec_suite_routes_clinical_venue_and_records_policy_provenance(
    tmp_path: Path,
) -> None:
    spec = {
        **_suite_spec(),
        "style_profile": "",
        "target_venue": "Nature Medicine",
        "discipline": "clinical medicine",
    }
    suite = render_figure_suite_spec(
        spec=spec,
        records=_all_records(),
        output_dir=tmp_path,
    )

    assert suite.status == "rendered"
    assert suite.provenance["style_profile"] == "biomed_omics"
    policy = suite.provenance["result_plot_policy"]
    assert policy["policy_id"] == "biomed_clinical_v1"
    assert policy["venue_family"] == "biomedical_clinical"
    assert policy["selection_basis"] == "venue_discipline"
    assert "forest" in policy["recommended_charts"]
    assert all(
        figure.provenance["result_plot_policy"]["policy_id"] == "biomed_clinical_v1"
        for figure in suite.figures
    )


def test_explicit_style_profile_wins_over_spec_venue_routing(tmp_path: Path) -> None:
    spec = {
        **_suite_spec(),
        "style_profile": "social_humanities",
        "target_venue": "Nature Medicine",
        "discipline": "clinical medicine",
    }
    suite = render_figure_suite_spec(
        spec=spec,
        records=_all_records(),
        output_dir=tmp_path,
        style_profile="stem_conference",
    )

    policy = suite.provenance["result_plot_policy"]
    assert suite.provenance["style_profile"] == "stem_conference"
    assert policy["policy_id"] == "stem_computing_v1"
    assert policy["selection_basis"] == "explicit_style_profile"


def test_plan_wrapper_preserves_outer_metadata_and_paper_type(tmp_path: Path) -> None:
    suite = render_figure_suite_spec(
        spec={
            "target_venue": "Journal of Behavioral Evidence",
            "paper_type": "quantitative psychology study",
            "plan": _suite_spec(),
        },
        records=_all_records(),
        output_dir=tmp_path,
    )

    policy = suite.provenance["result_plot_policy"]
    assert suite.provenance["style_profile"] == "social_humanities"
    assert policy["policy_id"] == "social_behavioral_v1"
    assert "target_venue:journal of behavioral evidence" in policy["signals"]
    assert "article_type:quantitative psychology study" in policy["signals"]


def test_biomedical_grouped_bar_exposes_raw_replicates(tmp_path: Path) -> None:
    records = [
        {
            "figure_type": "benchmark",
            "dataset": "Cohort A",
            "method": method,
            "metric": "response",
            "replicate_id": replicate,
            "value": value,
        }
        for method, values in {
            "Control": [0.41, 0.46, 0.44],
            "Treatment": [0.62, 0.67, 0.64],
        }.items()
        for replicate, value in enumerate(values, start=1)
    ]
    suite = render_figure_suite_spec(
        spec={
            "target_venue": "Nature Medicine",
            "discipline": "clinical medicine",
            "figures": [
                {
                    "figure_id": "fig:response",
                    "panels": [{"panel_id": "a", "chart": "grouped_bar"}],
                }
            ],
        },
        records=records,
        output_dir=tmp_path,
    )

    panel = suite.figures[0].provenance["panels"][0]
    assert panel["raw_points"] == 6
    assert panel["replicate_visibility"] == "overlaid"
    assert panel["uncertainty"] == "sample_standard_deviation"
    assert panel["category_encoding"] == "color_and_hatch"


def test_grouped_bar_draws_hatches_and_raw_replicate_markers() -> None:
    records = [
        {
            "dataset": "Cohort A",
            "method": method,
            "metric": "response",
            "replicate_id": replicate,
            "value": value,
        }
        for method, values in {
            "Control": [0.41, 0.46, 0.44],
            "Treatment": [0.62, 0.67, 0.64],
        }.items()
        for replicate, value in enumerate(values, start=1)
    ]
    profile = {
        **STYLE_PROFILES["biomed_omics"],
        "result_plot_policy": {"policy_id": "biomed_clinical_v1"},
        "reveal_raw_points": True,
        "print_safe_hatches": True,
    }
    figure, axis = figure_renderer.plt.subplots()
    try:
        metadata = figure_renderer._draw_grouped_bar(
            axis, pd.DataFrame(records), {}, profile
        )
        assert metadata is not None
        assert len({patch.get_hatch() for patch in axis.patches}) == 2
        assert sum(isinstance(item, PathCollection) for item in axis.collections) == 2
    finally:
        figure_renderer.plt.close(figure)


def test_grouped_bar_caps_large_raw_replicate_overlays() -> None:
    records = [
        {
            "dataset": "Cohort A",
            "method": "Treatment",
            "metric": "response",
            "replicate_id": replicate,
            "value": 0.5 + replicate / 10_000,
        }
        for replicate in range(600)
    ]
    profile = {
        **STYLE_PROFILES["biomed_omics"],
        "result_plot_policy": {"policy_id": "biomed_clinical_v1"},
        "reveal_raw_points": True,
        "print_safe_hatches": True,
    }
    figure, axis = figure_renderer.plt.subplots()
    try:
        metadata = figure_renderer._draw_grouped_bar(
            axis, pd.DataFrame(records), {}, profile
        )
        assert metadata is not None
        assert metadata["raw_points"] == 500
        assert metadata["raw_points_available"] == 600
        assert metadata["replicate_visibility"] == "overlaid_sampled"
        plotted = sum(
            len(item.get_offsets())
            for item in axis.collections
            if isinstance(item, PathCollection)
        )
        assert plotted == 500
    finally:
        figure_renderer.plt.close(figure)


def _grouped_bar_replicate_profile() -> dict:
    return {
        **STYLE_PROFILES["stem_conference"],
        "result_plot_policy": {"policy_id": "stem_computing_v1"},
        "reveal_raw_points": False,
        "print_safe_hatches": True,
    }


def _grouped_bar_replicate_records(n_seeds: int) -> list[dict]:
    return [
        {
            "dataset": "Benchmark A",
            "method": "Model",
            "metric": "accuracy",
            "seed": seed,
            "value": 0.8 + seed / 100,
        }
        for seed in range(n_seeds)
    ]


@pytest.mark.parametrize("sample_count, expected_points", [(1, 0), (3, 3), (10, 0)])
def test_grouped_bar_small_samples_override_optional_overlay(
    sample_count, expected_points
) -> None:
    figure, axis = figure_renderer.plt.subplots()
    try:
        metadata = figure_renderer._draw_grouped_bar(
            axis,
            pd.DataFrame(_grouped_bar_replicate_records(sample_count)),
            {},
            _grouped_bar_replicate_profile(),
        )
        assert metadata is not None
        assert metadata["raw_points"] == expected_points
        assert metadata["raw_points_available"] == sample_count
        assert metadata["replicate_visibility"] == (
            "overlaid" if expected_points else "not_requested"
        )
        assert any(
            isinstance(item, PathCollection) for item in axis.collections
        ) == bool(expected_points)
    finally:
        figure_renderer.plt.close(figure)


def test_grouped_bar_reports_raw_replicates_as_not_requested() -> None:
    figure, axis = figure_renderer.plt.subplots()
    try:
        metadata = figure_renderer._draw_grouped_bar(
            axis,
            pd.DataFrame(_grouped_bar_replicate_records(12)),
            {},
            _grouped_bar_replicate_profile(),
        )
        assert metadata is not None
        assert metadata["raw_points"] == 0
        assert metadata["raw_points_available"] == 12
        assert metadata["replicate_visibility"] == "not_requested"
        assert not any(isinstance(item, PathCollection) for item in axis.collections)
    finally:
        figure_renderer.plt.close(figure)


def test_grouped_bar_overlays_replicates_when_the_cell_is_small() -> None:
    # A mean-only bar over a handful of seeds hides the distribution, so a small cell
    # overlays its replicates whatever the profile asked for.
    figure, axis = figure_renderer.plt.subplots()
    try:
        metadata = figure_renderer._draw_grouped_bar(
            axis,
            pd.DataFrame(_grouped_bar_replicate_records(3)),
            {},
            _grouped_bar_replicate_profile(),
        )
        assert metadata is not None
        assert metadata["raw_points"] == 3
        assert metadata["raw_points_available"] == 3
        assert metadata["replicate_visibility"] == "overlaid"
    finally:
        figure_renderer.plt.close(figure)


def test_spec_suite_skips_missing_panels_and_reflows(tmp_path: Path) -> None:
    spec = {
        "figures": [
            {
                "figure_id": "fig:partial",
                "panels": [
                    {"panel_id": "a", "chart": "grouped_bar"},
                    {"panel_id": "b", "chart": "radar"},  # no radar records
                    {"panel_id": "c", "chart": "made_up_chart"},
                ],
            },
            {
                "figure_id": "fig:empty",
                "panels": [{"panel_id": "a", "chart": "violin"}],
            },
        ]
    }
    suite = render_figure_suite_spec(
        spec=spec, records=_benchmark_records(), output_dir=tmp_path
    )

    assert suite.status == "rendered"
    assert suite.provenance["figure_count"] == 1
    figure = suite.figures[0]
    assert [p["chart"] for p in figure.provenance["panels"]] == ["grouped_bar"]
    limitations = suite.provenance["limitations"]
    assert "fig_partial/b: no_matching_records" in limitations
    assert any(
        note.startswith("fig_partial/c: unsupported_chart:") for note in limitations
    )
    assert "fig_empty/a: no_matching_records" in limitations
    assert "fig_empty: all_panels_skipped" in limitations


def test_spec_suite_record_filter_selection(tmp_path: Path) -> None:
    records = _benchmark_records() + [
        {
            "figure_type": "benchmark",
            "dataset": "DS-C",
            "method": "Ours",
            "metric": "Recall",
            "value": 0.9,
        }
    ]
    spec = {
        "figures": [
            {
                "figure_id": "fig:f1_only",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "grouped_bar",
                        "record_filter": {"metric": "F1"},
                    }
                ],
            }
        ]
    }
    suite = render_figure_suite_spec(spec=spec, records=records, output_dir=tmp_path)
    assert suite.status == "rendered"
    assert suite.figures[0].provenance["panels"][0]["records"] == len(
        _benchmark_records()
    )


def test_an_unanswerable_filter_says_which_half_the_records_failed(
    tmp_path: Path,
) -> None:
    """A four-figure suite reported no_matching_records on every panel against 884
    records, and only a hand query said why: the plan filtered on task/model/target
    and not one record carried any of them. A plan written against a vocabulary the
    evidence never used is a different repair from a value nothing happens to hold."""
    spec = {
        "figures": [
            {
                "figure_id": "fig:vocab",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "grouped_bar",
                        "record_filter": {"task": "ranking"},
                    },
                    {
                        "panel_id": "b",
                        "chart": "grouped_bar",
                        "record_filter": {"metric": "AUROC"},
                    },
                ],
            }
        ]
    }
    suite = render_figure_suite_spec(
        spec=spec, records=_benchmark_records(), output_dir=tmp_path
    )
    limitations = suite.provenance["limitations"]
    assert "fig_vocab/a: no_matching_records:records_carry_no_field:task" in limitations
    assert "fig_vocab/b: no_matching_records:no_row_matches:metric=AUROC" in limitations


def test_spec_suite_empty_inputs(tmp_path: Path) -> None:
    no_spec = render_figure_suite_spec(
        spec={}, records=_benchmark_records(), output_dir=tmp_path
    )
    assert no_spec.status == "empty"
    assert no_spec.provenance["limitations"] == ["no_figures_in_spec"]

    no_records = render_figure_suite_spec(
        spec=_suite_spec(), records=[], output_dir=tmp_path
    )
    assert no_records.status == "empty"
    assert (
        no_records.provenance["result_plot_policy"]["policy_id"] == "stem_computing_v1"
    )
    assert no_records.provenance["limitations"] == ["no_experiment_records"]


def test_chart_kind_canonicalization() -> None:
    assert canonical_chart_kind("Grouped_Bar") == "grouped_bar"
    assert canonical_chart_kind("pareto") == "pareto_scatter"
    assert canonical_chart_kind("training curve") == "line"
    assert canonical_chart_kind("coefficient plot") == "forest"
    assert canonical_chart_kind("hologram") is None
    for kind in PANEL_CHARTS:
        assert canonical_chart_kind(kind) == kind


def test_grouped_bar_contract_advertises_replicate_identifiers() -> None:
    optional = set(chart_field_requirements("grouped_bar")["optional"])
    assert {
        "replicate_id",
        "replicate",
        "seed",
        "run_id",
        "sample_id",
        "subject_id",
    } <= optional


def test_resolve_style_profile() -> None:
    assert resolve_style_profile("nature_family")[0] == "nature_family"
    assert resolve_style_profile("  Social_Humanities ")[0] == "social_humanities"
    assert resolve_style_profile("unknown")[0] == "stem_conference"
    assert resolve_style_profile(None)[0] == "stem_conference"


def test_summarize_records_for_plan() -> None:
    inventory = summarize_records_for_plan(_all_records())
    assert inventory["record_count"] == len(_all_records())
    assert inventory["figure_types"]["benchmark"] == len(_benchmark_records())
    assert "grouped_bar" in inventory["supported_charts"]
    assert "Ours" in inventory["methods"]
    assert summarize_records_for_plan([]) == {"record_count": 0}


def test_figure_suite_render_primitive(tmp_path: Path, monkeypatch) -> None:
    import json

    import pytest

    from research_harness.primitives.result_figure_impls import figure_suite_render
    from research_harness.primitives.types import _to_jsonable

    monkeypatch.delenv("RH_EAG_FIGURE_VISION", raising=False)
    out = figure_suite_render(
        spec=_suite_spec(),
        records=_all_records(),
        output_dir=str(tmp_path),
        suite_id="prim",
        claim_boundary="reported_baselines_only",
        critique=True,
    )
    assert out.status == "rendered"
    assert len(out.figures) == 2
    assert out.style_profile == "stem_conference"
    assert out.provenance["claim_boundary"] == "reported_baselines_only"
    assert len(out.critique) == 2
    assert all(r["verdict"] == "pass_deterministic_only" for r in out.critique)
    for figure in out.figures:
        assert Path(figure.paths["png"]).exists()
    json.dumps(_to_jsonable(out))  # artifact-recordable

    with pytest.raises(ValueError):
        figure_suite_render(spec=_suite_spec(), records=_all_records(), output_dir="  ")
