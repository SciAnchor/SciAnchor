"""S1 render-layer expansion: error bars, CI band, categorical-x line, and the
new chart kinds (hist, stacked_bar, km_survival, volcano, image,
qualitative_grid) plus the biomed_omics style profile."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from research_harness.visualization.experiment_figures import (
    PANEL_CHARTS,
    STYLE_PROFILES,
    canonical_chart_kind,
    render_figure_suite_spec,
)


def _panel_meta(suite, figure_id, panel_id):
    figure = {f.figure_id: f for f in suite.figures}[figure_id]
    return {p["panel_id"]: p for p in figure.provenance["panels"]}[panel_id]


# --------------------------------------------------------------------------- #
# Error bars (multi-seed / std / lo-hi) on grouped bars                        #
# --------------------------------------------------------------------------- #


def test_grouped_bar_error_bars_from_repeated_seeds(tmp_path: Path) -> None:
    records = [
        {
            "figure_type": "benchmark",
            "dataset": "DS",
            "method": m,
            "metric": "F1",
            "value": v,
        }
        for m, vals in {"Ours": [0.80, 0.82, 0.81], "Base": [0.70, 0.72, 0.68]}.items()
        for v in vals
    ]
    spec = {
        "figures": [
            {
                "figure_id": "fig:m",
                "panels": [{"panel_id": "a", "chart": "grouped_bar"}],
            }
        ]
    }
    suite = render_figure_suite_spec(spec=spec, records=records, output_dir=tmp_path)
    assert suite.status == "rendered"
    assert _panel_meta(suite, "experiment_fig_m", "a")["error_bars"] is True


def test_grouped_bar_error_bars_from_explicit_std(tmp_path: Path) -> None:
    records = [
        {
            "figure_type": "benchmark",
            "dataset": "DS",
            "method": "Ours",
            "metric": "F1",
            "value": 0.81,
            "std": 0.01,
        },
        {
            "figure_type": "benchmark",
            "dataset": "DS",
            "method": "Base",
            "metric": "F1",
            "value": 0.70,
            "std": 0.02,
        },
    ]
    spec = {
        "figures": [
            {
                "figure_id": "fig:m",
                "panels": [{"panel_id": "a", "chart": "grouped_bar"}],
            }
        ]
    }
    suite = render_figure_suite_spec(spec=spec, records=records, output_dir=tmp_path)
    assert _panel_meta(suite, "experiment_fig_m", "a")["error_bars"] is True


def test_grouped_bar_no_error_bars_single_deterministic_value(tmp_path: Path) -> None:
    records = [
        {
            "figure_type": "benchmark",
            "dataset": "DS",
            "method": "Ours",
            "metric": "F1",
            "value": 0.81,
        },
        {
            "figure_type": "benchmark",
            "dataset": "DS",
            "method": "Base",
            "metric": "F1",
            "value": 0.70,
        },
    ]
    spec = {
        "figures": [
            {
                "figure_id": "fig:m",
                "panels": [{"panel_id": "a", "chart": "grouped_bar"}],
            }
        ]
    }
    suite = render_figure_suite_spec(spec=spec, records=records, output_dir=tmp_path)
    assert _panel_meta(suite, "experiment_fig_m", "a")["error_bars"] is False


# --------------------------------------------------------------------------- #
# Line: confidence band + categorical x                                        #
# --------------------------------------------------------------------------- #


def test_line_confidence_band(tmp_path: Path) -> None:
    records = [
        {
            "figure_type": "line",
            "series": "Ours",
            "x": t,
            "y": y,
            "lo": y - 0.05,
            "hi": y + 0.05,
        }
        for t, y in [(1, 0.6), (2, 0.72), (3, 0.79), (4, 0.81)]
    ]
    spec = {
        "figures": [
            {
                "figure_id": "fig:c",
                "panels": [{"panel_id": "a", "chart": "convergence"}],
            }
        ]
    }
    suite = render_figure_suite_spec(spec=spec, records=records, output_dir=tmp_path)
    assert _panel_meta(suite, "experiment_fig_c", "a")["confidence_band"] is True


def test_line_categorical_x_interaction(tmp_path: Path) -> None:
    records = [
        {"figure_type": "line", "series": s, "x": genre, "y": v}
        for s, points in {
            "Human": [("novel", 9.3), ("news", 8.1), ("essay", 7.5)],
            "MT": [("novel", 8.1), ("news", 7.0), ("essay", 6.6)],
        }.items()
        for genre, v in points
    ]
    spec = {
        "figures": [
            {
                "figure_id": "fig:i",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "line",
                        "x_label": "Genre",
                        "y_label": "MTLD",
                    }
                ],
            }
        ]
    }
    suite = render_figure_suite_spec(
        spec=spec,
        records=records,
        output_dir=tmp_path,
        style_profile="social_humanities",
    )
    assert suite.status == "rendered"
    assert _panel_meta(suite, "experiment_fig_i", "a")["confidence_band"] is False


# --------------------------------------------------------------------------- #
# New chart kinds                                                              #
# --------------------------------------------------------------------------- #


def test_hist_renders(tmp_path: Path) -> None:
    records = [
        {"figure_type": "hist", "value": v}
        for v in [1, 2, 2, 3, 3, 3, 4, 4, 5, 2, 3, 4, 3, 2]
    ]
    spec = {
        "figures": [
            {
                "figure_id": "fig:h",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "histogram",
                        "kde": True,
                        "x_label": "score",
                    }
                ],
            }
        ]
    }
    suite = render_figure_suite_spec(spec=spec, records=records, output_dir=tmp_path)
    assert suite.status == "rendered"
    assert _panel_meta(suite, "experiment_fig_h", "a")["chart"] == "hist"


def test_stacked_bar_composition(tmp_path: Path) -> None:
    records = [
        {"figure_type": "composition", "category": c, "segment": s, "value": v}
        for c, segs in {
            "2019": {"CN": 40, "West": 30, "FastFood": 30},
            "2021": {"CN": 35, "West": 35, "FastFood": 30},
        }.items()
        for s, v in segs.items()
    ]
    spec = {
        "figures": [
            {
                "figure_id": "fig:s",
                "panels": [
                    {"panel_id": "a", "chart": "stacked_bar", "y_label": "share"}
                ],
            }
        ]
    }
    suite = render_figure_suite_spec(spec=spec, records=records, output_dir=tmp_path)
    meta = _panel_meta(suite, "experiment_fig_s", "a")
    assert meta["segments"] == 3


def test_km_survival_with_groups_and_censoring(tmp_path: Path) -> None:
    records = []
    for grp, curve in {
        "High": [(0, 1.0, False), (5, 0.8, True), (10, 0.6, False), (15, 0.4, False)],
        "Low": [(0, 1.0, False), (5, 0.6, False), (10, 0.35, True), (15, 0.2, False)],
    }.items():
        for t, s, c in curve:
            records.append(
                {
                    "figure_type": "survival",
                    "group": grp,
                    "time": t,
                    "value": s,
                    "censored": c,
                }
            )
    spec = {
        "figures": [
            {
                "figure_id": "fig:km",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "kaplan_meier",
                        "title": "Overall survival",
                    }
                ],
            }
        ]
    }
    suite = render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, style_profile="biomed_omics"
    )
    assert suite.status == "rendered"
    assert _panel_meta(suite, "experiment_fig_km", "a")["groups"] == 2


def test_volcano_thresholds(tmp_path: Path) -> None:
    records = [
        {"figure_type": "volcano", "log2fc": fc, "neg_log10_p": p}
        for fc, p in [
            (2.5, 4.0),
            (-2.1, 3.5),
            (0.2, 0.5),
            (1.5, 2.0),
            (-0.3, 1.0),
            (3.0, 5.0),
            (-2.8, 4.2),
            (0.1, 0.2),
        ]
    ]
    spec = {
        "figures": [
            {
                "figure_id": "fig:v",
                "panels": [{"panel_id": "a", "chart": "volcano_plot"}],
            }
        ]
    }
    suite = render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, style_profile="biomed_omics"
    )
    meta = _panel_meta(suite, "experiment_fig_v", "a")
    assert meta["up"] == 3 and meta["down"] == 2


def _png(tmp_path: Path, name: str) -> Path:
    fig, ax = plt.subplots(figsize=(2, 2))
    ax.plot([0, 1], [0, 1])
    path = tmp_path / name
    fig.savefig(path)
    plt.close(fig)
    return path


def test_image_panel_from_asset(tmp_path: Path) -> None:
    asset = _png(tmp_path, "map.png")
    spec = {
        "figures": [
            {
                "figure_id": "fig:map",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "image",
                        "asset_path": str(asset),
                        "title": "Study area",
                    }
                ],
            }
        ]
    }
    # image panels bind by asset_path, not records
    suite = render_figure_suite_spec(
        spec=spec,
        records=[
            {
                "figure_type": "benchmark",
                "dataset": "d",
                "method": "m",
                "metric": "x",
                "value": 1.0,
            }
        ],
        output_dir=tmp_path,
    )
    assert suite.status == "rendered"
    assert _panel_meta(suite, "experiment_fig_map", "a")["asset_path"].endswith(
        "map.png"
    )


def test_image_panel_missing_asset_skipped(tmp_path: Path) -> None:
    spec = {
        "figures": [
            {
                "figure_id": "fig:map",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "image",
                        "asset_path": str(tmp_path / "nope.png"),
                    }
                ],
            }
        ]
    }
    suite = render_figure_suite_spec(
        spec=spec,
        records=[
            {
                "figure_type": "benchmark",
                "dataset": "d",
                "method": "m",
                "metric": "x",
                "value": 1.0,
            }
        ],
        output_dir=tmp_path,
    )
    assert suite.status == "empty"
    assert any(
        "no_matching_records" in n or "all_panels_skipped" in n
        for n in suite.provenance["limitations"]
    )


def test_qualitative_grid_from_spec_assets_skips_missing(tmp_path: Path) -> None:
    a1, a2 = _png(tmp_path, "c1.png"), _png(tmp_path, "c2.png")
    spec = {
        "figures": [
            {
                "figure_id": "fig:cases",
                "panels": [
                    {
                        "panel_id": "a",
                        "chart": "case_grid",
                        "cols": 2,
                        "assets": [
                            {"path": str(a1), "label": "good"},
                            {"path": str(a2), "label": "bad"},
                            {"path": str(tmp_path / "missing.png"), "label": "gone"},
                        ],
                    }
                ],
            }
        ]
    }
    suite = render_figure_suite_spec(
        spec=spec,
        records=[
            {
                "figure_type": "benchmark",
                "dataset": "d",
                "method": "m",
                "metric": "x",
                "value": 1.0,
            }
        ],
        output_dir=tmp_path,
    )
    meta = _panel_meta(suite, "experiment_fig_cases", "a")
    assert meta["cells"] == 2  # third asset missing, skipped


# --------------------------------------------------------------------------- #
# Registry / profile coverage                                                 #
# --------------------------------------------------------------------------- #


def test_new_charts_registered_and_aliased() -> None:
    for kind in (
        "hist",
        "stacked_bar",
        "km_survival",
        "volcano",
        "image",
        "qualitative_grid",
    ):
        assert kind in PANEL_CHARTS
    assert canonical_chart_kind("kaplan_meier") == "km_survival"
    assert canonical_chart_kind("volcano plot") == "volcano"
    assert canonical_chart_kind("case_grid") == "qualitative_grid"
    assert canonical_chart_kind("histogram") == "hist"
    assert canonical_chart_kind("composition_bar") == "stacked_bar"


def test_biomed_omics_profile_registered() -> None:
    assert "biomed_omics" in STYLE_PROFILES
    assert len(STYLE_PROFILES) == 4
