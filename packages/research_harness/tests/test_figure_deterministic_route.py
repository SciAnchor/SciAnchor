"""UF06: retain recorded nulls; block missing records; hash assets."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.visualization.figure_deterministic_route import (
    render_deterministic_package,
)
from research_harness.visualization.figure_package_contracts import (
    SCHEMA_FIGURE_DESIGN,
    FigureContractError,
    validate_validation_report,
)
from research_harness.visualization.result_plot_policy import empty_effect_reason


def _design(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_DESIGN,
        "figure_id": "fig:cmp",
        "role": "quantitative_comparison",
        "one_sentence_claim": "Named methods are compared on F1.",
        "evidence_boundary": "evidence_backed",
        "panel_map": [{"panel_id": "A", "purpose": "primary comparison"}],
        "render_route": "deterministic",
        "target_venue": "Information Processing & Management",
    }
    payload.update(overrides)
    return payload


def _records(
    values: tuple[float, float, float] = (0.71, 0.74, 0.81),
) -> list[dict[str, object]]:
    methods = ("Baseline", "Prior", "Ours")
    return [
        {
            "figure_type": "benchmark",
            "dataset": "DS-A",
            "method": method,
            "metric": "F1",
            "value": value,
            "unit": "score",
        }
        for method, value in zip(methods, values)
    ]


def test_true_null_effect_is_retained(tmp_path: Path) -> None:
    records = _records((0.5, 0.5, 0.5))
    assert empty_effect_reason("grouped_bar", records) == "empty_effect:bar_range"
    result = render_deterministic_package(
        design_contract=_design(),
        records=records,
        output_dir=tmp_path,
    )
    assert result["validation"]["status"] == "pass"
    assert result["assets"]
    assert Path(result["assets"][0]["path"]).is_file()
    assert result["assets"][0]["sha256"]
    assert result["provenance"]["null_effect_retained"] is True
    assert any(
        "retained_empty_effect" in n for n in result["provenance"]["limitations"]
    )


def test_missing_records_are_blocked(tmp_path: Path) -> None:
    result = render_deterministic_package(
        design_contract=_design(),
        records=[],
        output_dir=tmp_path,
    )
    assert result["validation"]["status"] == "fail"
    assert result["assets"] == []
    assert result["validation"]["checks"][0]["execution_status"] == "completed"
    assert result["validation"]["checks"][0]["verdict"] == "fail"


def test_unmatched_records_are_blocked(tmp_path: Path) -> None:
    result = render_deterministic_package(
        design_contract=_design(),
        records=[{"figure_type": "line", "series": "A", "x": 1, "y": 0.2}],
        output_dir=tmp_path,
    )
    assert result["validation"]["status"] == "fail"
    assert any(
        "no_matching_records" in str(c["findings"])
        for c in result["validation"]["checks"]
    )


def test_non_deterministic_route_is_not_run(tmp_path: Path) -> None:
    result = render_deterministic_package(
        design_contract=_design(render_route="generative"),
        records=_records(),
        output_dir=tmp_path,
    )
    assert result["validation"]["status"] == "not_run"
    check = result["validation"]["checks"][0]
    assert check["execution_status"] == "not_run"
    assert check["verdict"] is None


def test_not_run_cannot_pass() -> None:
    with pytest.raises(FigureContractError):
        validate_validation_report(
            {
                "schema_version": "rh.validation_report.v1",
                "status": "pass",
                "checks": [
                    {
                        "check_id": "deterministic_render",
                        "execution_status": "not_run",
                        "verdict": "pass",
                    }
                ],
            }
        )


def test_rendered_comparison_hashes_png(tmp_path: Path) -> None:
    result = render_deterministic_package(
        design_contract=_design(),
        records=_records(),
        output_dir=tmp_path,
    )
    assert result["validation"]["status"] == "pass"
    digest = result["assets"][0]["sha256"]
    assert len(digest) == 64
    assert Path(result["assets"][0]["path"]).read_bytes()
    second = render_deterministic_package(
        design_contract=_design(),
        records=_records(),
        output_dir=tmp_path / "b",
    )
    assert second["assets"][0]["sha256"] == digest
