"""Tests for `rh exemplar figures` — the result-figure suite CLI.

The offline path (--spec) needs no LLM: it renders a given suite spec from
records. The exemplar design phase (curate→retrieve→plan) is covered by
test_exemplar_primitives.py with mocked LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from research_harness.cli import main


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    records = [
        {
            "figure_type": "benchmark",
            "dataset": dataset,
            "method": method,
            "metric": "F1",
            "value": value,
        }
        for dataset, values in {
            "DS-A": {"Baseline": 0.71, "Ours": 0.81},
            "DS-B": {"Baseline": 0.66, "Ours": 0.78},
        }.items()
        for method, value in values.items()
    ] + [
        {
            "figure_type": "ablation",
            "dataset": dataset,
            "variant": variant,
            "metric": "F1",
            "value": value,
        }
        for dataset, values in {
            "DS-A": {"Full": 0.81, "- X": 0.77},
            "DS-B": {"Full": 0.78, "- X": 0.74},
        }.items()
        for variant, value in values.items()
    ]
    spec = {
        "plan": {
            "style_profile": "nature_family",
            "figures": [
                {
                    "figure_id": "fig:main",
                    "title": "Main results",
                    "composition": "1x2",
                    "panels": [
                        {"panel_id": "a", "chart": "grouped_bar"},
                        {"panel_id": "b", "chart": "heatmap"},
                    ],
                }
            ],
        }
    }
    records_file = tmp_path / "records.json"
    records_file.write_text(json.dumps({"records": records}), encoding="utf-8")
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")
    return records_file, spec_file


def test_figures_renders_offline_from_spec(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("RH_EAG_FIGURE_VISION", raising=False)
    records_file, spec_file = _write_inputs(tmp_path)
    out_dir = tmp_path / "figs"

    result = runner.invoke(
        main,
        [
            "exemplar",
            "figures",
            "--topic",
            "1",
            "--records",
            str(records_file),
            "--spec",
            str(spec_file),
            "--output-dir",
            str(out_dir),
            "--suite-id",
            "clitest",
            "--no-record",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "exemplar design skipped" in result.output
    assert "status=rendered style_profile=nature_family figures=1" in result.output
    assert "critique[pass_deterministic_only]" in result.output
    rendered = list(out_dir.glob("clitest_fig_main.png"))
    assert rendered and rendered[0].stat().st_size > 1000


def test_figures_records_suite_artifact(
    runner: CliRunner, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("RH_EAG_FIGURE_VISION", raising=False)
    records_file, spec_file = _write_inputs(tmp_path)
    out_dir = tmp_path / "figs"

    init = runner.invoke(main, ["topic", "init", "figures-cli-test"])
    assert init.exit_code == 0, init.output

    result = runner.invoke(
        main,
        [
            "exemplar",
            "figures",
            "--topic",
            "1",
            "--records",
            str(records_file),
            "--spec",
            str(spec_file),
            "--output-dir",
            str(out_dir),
            "--no-critique",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "recorded figure_suite #" in result.output


def test_figures_requires_output_dir_unless_plan_only(
    runner: CliRunner, tmp_path: Path
) -> None:
    records_file, spec_file = _write_inputs(tmp_path)
    result = runner.invoke(
        main,
        [
            "exemplar",
            "figures",
            "--topic",
            "1",
            "--records",
            str(records_file),
            "--spec",
            str(spec_file),
        ],
    )
    assert result.exit_code != 0
    assert "--output-dir" in result.output


def test_figures_rejects_empty_records(runner: CliRunner, tmp_path: Path) -> None:
    records_file = tmp_path / "empty.json"
    records_file.write_text("[]", encoding="utf-8")
    _, spec_file = _write_inputs(tmp_path)
    result = runner.invoke(
        main,
        [
            "exemplar",
            "figures",
            "--topic",
            "1",
            "--records",
            str(records_file),
            "--spec",
            str(spec_file),
            "--output-dir",
            str(tmp_path / "figs"),
        ],
    )
    assert result.exit_code != 0
    assert "no records" in result.output
