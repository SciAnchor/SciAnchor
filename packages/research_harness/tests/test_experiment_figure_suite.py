from __future__ import annotations

from pathlib import Path

from research_harness.visualization.experiment_figures import (
    render_experiment_figure_suite,
)


def _records() -> list[dict[str, object]]:
    benchmark = [
        {
            "figure_type": "benchmark",
            "dataset": dataset,
            "method": method,
            "metric": "LVE",
            "value": value,
            "higher_is_better": False,
        }
        for dataset, values in {
            "BEAT": {"FaceFormer": 6.8, "CodeTalker": 6.1, "ESDiff": 5.4},
            "Multiface": {"FaceFormer": 7.3, "CodeTalker": 6.7, "ESDiff": 5.8},
            "VOCASET": {"FaceFormer": 5.6, "CodeTalker": 5.2, "ESDiff": 4.7},
        }.items()
        for method, value in values.items()
    ]
    ablation = [
        {
            "figure_type": "ablation",
            "dataset": dataset,
            "variant": variant,
            "metric": "LVE",
            "value": value,
            "higher_is_better": False,
        }
        for dataset, values in {
            "BEAT": {
                "Full": 5.4,
                "- emotion prior": 5.9,
                "- semantic disentangle": 6.2,
            },
            "Multiface": {
                "Full": 5.8,
                "- emotion prior": 6.3,
                "- semantic disentangle": 6.6,
            },
        }.items()
        for variant, value in values.items()
    ]
    radar = [
        {
            "figure_type": "radar",
            "method": method,
            "metric": metric,
            "value": value,
            "higher_is_better": higher,
        }
        for method, metrics in {
            "FaceFormer": {
                "Lip Sync": (0.74, True),
                "Emotion Match": (0.68, True),
                "Motion Smooth": (0.71, True),
                "Runtime": (42.0, False),
            },
            "CodeTalker": {
                "Lip Sync": (0.78, True),
                "Emotion Match": (0.72, True),
                "Motion Smooth": (0.76, True),
                "Runtime": (38.0, False),
            },
            "ESDiff": {
                "Lip Sync": (0.83, True),
                "Emotion Match": (0.81, True),
                "Motion Smooth": (0.84, True),
                "Runtime": (35.0, False),
            },
        }.items()
        for metric, (value, higher) in metrics.items()
    ]
    pareto = [
        {
            "figure_type": "pareto",
            "method": method,
            "x": latency,
            "y": quality,
            "x_label": "Latency (ms)",
            "y_label": "Emotion match",
        }
        for method, latency, quality in [
            ("FaceFormer", 42, 0.68),
            ("CodeTalker", 38, 0.72),
            ("ESDiff", 35, 0.81),
        ]
    ]
    sensitivity = [
        {
            "figure_type": "sensitivity",
            "method": "ESDiff",
            "parameter": "guidance scale",
            "setting": setting,
            "metric": "Emotion match",
            "value": value,
            "higher_is_better": True,
        }
        for setting, value in [(0.4, 0.73), (0.8, 0.79), (1.2, 0.81), (1.6, 0.78)]
    ]
    return benchmark + ablation + radar + pareto + sensitivity


def test_experiment_figure_suite_renders_multiple_publication_figures(
    tmp_path: Path,
) -> None:
    suite = render_experiment_figure_suite(
        records=_records(),
        output_dir=tmp_path,
        suite_id="esdiff",
        formats=("png",),
        claim_boundary="reported_baselines_only",
    )

    figure_ids = {figure.figure_id for figure in suite.figures}
    assert suite.status == "rendered"
    assert figure_ids == {
        "esdiff_benchmark_grouped_bar",
        "esdiff_ablation_heatmap",
        "esdiff_metric_radar",
        "esdiff_pareto_scatter",
        "esdiff_sensitivity_line",
    }
    assert suite.provenance["backend"] == "seaborn_matplotlib"
    assert suite.provenance["claim_boundary"] == "reported_baselines_only"
    assert suite.provenance["figure_count"] == 5
    assert suite.provenance["record_count"] == len(_records())

    for figure in suite.figures:
        assert figure.status == "rendered"
        assert figure.paths["png"].endswith(".png")
        assert Path(figure.paths["png"]).exists()
        assert Path(figure.paths["png"]).stat().st_size > 1000
        assert figure.provenance["claim_boundary"] == "reported_baselines_only"
        assert figure.provenance["backend"] == "seaborn_matplotlib"


def test_experiment_figure_suite_returns_empty_status_for_missing_records(
    tmp_path: Path,
) -> None:
    suite = render_experiment_figure_suite(records=[], output_dir=tmp_path)

    assert suite.status == "empty"
    assert suite.figures == []
    assert suite.provenance["limitations"] == ["no_experiment_records"]
