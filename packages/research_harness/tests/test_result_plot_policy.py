"""Unit contract for deterministic result-plot policy resolution."""

from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from research_harness.visualization.result_plot_policy import (
    ResultPlotPolicy,
    ResultPlotPolicyResolution,
    empty_effect_reason,
    refuse_chart_kind,
    resolve_result_plot_policy,
)


def _assert_policy(
    resolution: ResultPlotPolicyResolution,
    *,
    policy_id: str,
    style_profile: str,
) -> None:
    assert isinstance(resolution, ResultPlotPolicyResolution)
    assert isinstance(resolution.policy, ResultPlotPolicy)
    assert resolution.policy.policy_id == policy_id
    assert resolution.policy.style_profile == style_profile


@pytest.mark.parametrize("target_venue", ["NeurIPS 2026", "CCF-A conference"])
def test_computing_venues_select_stem_policy(target_venue: str) -> None:
    resolution = resolve_result_plot_policy(target_venue=target_venue)

    _assert_policy(
        resolution,
        policy_id="stem_computing_v1",
        style_profile="stem_conference",
    )


def test_plain_nature_selects_multidisciplinary_policy() -> None:
    resolution = resolve_result_plot_policy(target_venue="Nature")

    _assert_policy(
        resolution,
        policy_id="nature_multidisciplinary_v1",
        style_profile="nature_family",
    )


@pytest.mark.parametrize(
    ("target_venue", "discipline"),
    [
        ("Nature Medicine", ""),
        ("", "clinical medicine"),
        ("", "biomedical science"),
    ],
)
def test_clinical_signals_select_biomedical_policy(
    target_venue: str,
    discipline: str,
) -> None:
    resolution = resolve_result_plot_policy(
        target_venue=target_venue,
        discipline=discipline,
    )

    _assert_policy(
        resolution,
        policy_id="biomed_clinical_v1",
        style_profile="biomed_omics",
    )


@pytest.mark.parametrize(
    "signals",
    [
        {"target_venue": "Nature Genetics"},
        {"discipline": "genomics"},
        {"records": ({"gene": "TP53", "log2fc": 1.8, "p_value": 0.002},)},
    ],
)
def test_omics_signals_select_omics_policy_and_recommend_volcano(
    signals: dict[str, object],
) -> None:
    resolution = resolve_result_plot_policy(**signals)

    _assert_policy(
        resolution,
        policy_id="biomed_omics_v1",
        style_profile="biomed_omics",
    )
    assert "volcano" in resolution.policy.recommended_charts


@pytest.mark.parametrize(
    ("target_venue", "discipline"),
    [("APA", ""), ("AEA", ""), ("", "economics")],
)
def test_social_science_signals_recommend_interval_forest_plot(
    target_venue: str,
    discipline: str,
) -> None:
    records = ({"term": "Treatment", "estimate": 0.24, "lo": 0.08, "hi": 0.40},)

    resolution = resolve_result_plot_policy(
        target_venue=target_venue,
        discipline=discipline,
        records=records,
    )

    _assert_policy(
        resolution,
        policy_id="social_behavioral_v1",
        style_profile="social_humanities",
    )
    assert "forest" in resolution.policy.recommended_charts


def test_clinical_time_to_event_records_recommend_survival_plot() -> None:
    records = (
        {"cohort": "Control", "time": 12.0, "event": 1},
        {"cohort": "Treatment", "time": 16.0, "event": 0},
    )

    resolution = resolve_result_plot_policy(
        target_venue="Nature Medicine",
        records=records,
    )

    assert "km_survival" in resolution.policy.recommended_charts


def test_plain_time_value_series_does_not_imply_survival_plot() -> None:
    records = (
        {"figure_type": "line", "time": 1, "value": 0.52},
        {"figure_type": "line", "time": 2, "value": 0.61},
    )

    resolution = resolve_result_plot_policy(
        explicit_style_profile="stem_conference",
        records=records,
    )

    assert "line" in resolution.policy.recommended_charts
    assert "km_survival" not in resolution.policy.recommended_charts


def test_record_chart_recommendations_preserve_first_seen_order() -> None:
    records = (
        {"figure_type": "sensitivity"},
        {"figure_type": "benchmark"},
        {"figure_type": "ablation"},
    )

    resolution = resolve_result_plot_policy(
        explicit_style_profile="stem_conference",
        records=records,
    )

    assert resolution.policy.recommended_charts[:3] == (
        "sensitivity_line",
        "grouped_bar",
        "heatmap",
    )


def test_explicit_style_profile_wins_over_all_inferred_signals() -> None:
    resolution = resolve_result_plot_policy(
        explicit_style_profile="social_humanities",
        spec_style_profile="nature_family",
        target_venue="Nature Medicine",
        discipline="clinical medicine",
        records=({"gene": "TP53", "log2fc": 2.1, "p_value": 0.001},),
    )

    _assert_policy(
        resolution,
        policy_id="social_behavioral_v1",
        style_profile="social_humanities",
    )
    assert resolution.selection_basis == "explicit_style_profile"


def test_valid_spec_profile_is_preserved_without_stronger_signal() -> None:
    resolution = resolve_result_plot_policy(spec_style_profile="nature_family")

    _assert_policy(
        resolution,
        policy_id="nature_multidisciplinary_v1",
        style_profile="nature_family",
    )
    assert resolution.selection_basis == "spec_style_profile"


def test_unknown_signals_have_stable_warned_fallback() -> None:
    kwargs = {
        "spec_style_profile": "unregistered_profile",
        "target_venue": "Journal of Unmapped Results",
        "discipline": "unmapped discipline",
        "article_type": "unmapped article",
    }

    first = resolve_result_plot_policy(**kwargs)
    second = resolve_result_plot_policy(**kwargs)

    assert first == second
    _assert_policy(
        first,
        policy_id="stem_computing_v1",
        style_profile="stem_conference",
    )
    assert first.selection_basis == "default"
    assert first.warnings


@pytest.mark.parametrize("target_venue", ["ACME Journal", "Apache Research"])
def test_venue_acronyms_require_complete_tokens(target_venue: str) -> None:
    resolution = resolve_result_plot_policy(target_venue=target_venue)

    _assert_policy(
        resolution,
        policy_id="stem_computing_v1",
        style_profile="stem_conference",
    )
    assert resolution.selection_basis == "default"
    assert "unrecognized_venue_or_discipline" in resolution.warnings


def test_resolution_does_not_mutate_nested_input_records() -> None:
    records = [
        {
            "gene": "TP53",
            "log2fc": 1.8,
            "p_value": 0.002,
            "metadata": {"replicates": ["r1", "r2", "r3"]},
        }
    ]
    before = copy.deepcopy(records)

    resolve_result_plot_policy(records=records)

    assert records == before


def test_policy_resolution_is_frozen_and_provenance_is_json_serializable() -> None:
    resolution = resolve_result_plot_policy(
        target_venue="Nature Medicine",
        records=({"time": 12.0, "event": 1},),
    )

    with pytest.raises(FrozenInstanceError):
        resolution.selection_basis = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        resolution.policy.policy_id = "changed"  # type: ignore[misc]

    provenance = resolution.as_provenance()
    assert provenance["policy_id"] == "biomed_clinical_v1"
    assert provenance["style_profile"] == "biomed_omics"
    assert provenance["selection_basis"] == resolution.selection_basis
    json.dumps(provenance)


def test_refuse_pie_and_dual_y() -> None:
    assert refuse_chart_kind("pie") == "refused_chart:pie"
    assert refuse_chart_kind("twinx") == "refused_chart:twinx"
    assert refuse_chart_kind("grouped_bar") is None


def test_empty_effect_skips_flat_bars_and_empty_volcano() -> None:
    assert (
        empty_effect_reason(
            "bar",
            ({"value": 0.5}, {"value": 0.5}, {"value": 0.5}),
        )
        == "empty_effect:bar_range"
    )
    assert (
        empty_effect_reason(
            "volcano",
            ({"log2fc": 0.2, "p_value": 0.4}, {"log2fc": -0.1, "p_value": 0.8}),
        )
        == "empty_effect:volcano_hits"
    )
    assert (
        empty_effect_reason(
            "bar",
            ({"value": 0.4}, {"value": 0.9}),
        )
        is None
    )
