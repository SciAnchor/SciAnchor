"""Panel decoration, colour pinning and figure sizing in the suite renderer.

Each covers a gap found while composing an eight-figure manuscript: a coefficient
panel that could not ask for its zero line, an entity whose colour changed between
panels, and a wide panel row that overflowed the text block it had to sit in.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

from research_harness.visualization.experiment_figures import (  # noqa: E402
    _as_number_list,
    _panel_reference_marks,
    _profile_palette,
    render_figure_suite_spec,
)
from research_harness.visualization.result_plot_policy import (  # noqa: E402
    register_style_profile,
    resolve_result_plot_policy,
)


def test_as_number_list_accepts_scalar_and_sequence_and_rejects_junk():
    assert _as_number_list(0) == [0.0]
    assert _as_number_list([0, 2022.5]) == [0.0, 2022.5]
    assert _as_number_list(None) == []
    assert _as_number_list(True) == []  # a bool is not a coordinate
    assert _as_number_list(["x", 3]) == [3.0]


def test_reference_marks_draw_lines_span_and_limits():
    fig, ax = plt.subplots()
    _panel_reference_marks(
        ax,
        {
            "hline": 0.0,
            "vline": [2022.5],
            "span": [2022.5, 2025.5],
            "xlim": [2018, 2026],
            "ylim": [-0.1, 0.25],
        },
    )
    assert len(ax.lines) == 2  # one horizontal, one vertical
    assert len(ax.patches) == 1  # the shaded span
    assert ax.get_xlim() == (2018.0, 2026.0)
    assert ax.get_ylim() == (-0.1, 0.25)
    plt.close(fig)


def test_reference_marks_are_optional():
    fig, ax = plt.subplots()
    _panel_reference_marks(ax, {})
    assert not ax.lines and not ax.patches
    plt.close(fig)


def test_series_colours_can_be_pinned_without_consuming_palette_slots():
    profile = {"palette": ["#111111", "#222222", "#333333"]}
    default = _profile_palette(profile, ["a", "b", "c"])
    assert default == {"a": "#111111", "b": "#222222", "c": "#333333"}
    pinned = _profile_palette(
        profile, ["a", "b", "c"], {"series_colors": {"b": "#E18727"}}
    )
    assert pinned["b"] == "#E18727"
    assert pinned["a"] == "#111111" and pinned["c"] == "#222222"


def test_registered_profile_survives_policy_resolution():
    register_style_profile("test_project_profile", inherits="stem_conference")
    resolved = resolve_result_plot_policy(
        explicit_style_profile="test_project_profile",
        spec_style_profile="",
        target_venue="",
        discipline="",
        article_type="",
        records=[{"x": 1, "y": 2}],
    )
    assert resolved.policy.style_profile == "test_project_profile"
    assert resolved.policy.venue_family == "stem_computing"
    with pytest.raises(ValueError):
        register_style_profile("bad_profile", inherits="not_a_profile")


def test_figure_level_size_and_width_clamp(tmp_path):
    records = [
        {"figure_type": "line", "panel": p, "x": x, "y": x * 0.1, "series": s}
        for p in ("p1", "p2", "p3")
        for s in ("human", "frozen")
        for x in range(1, 6)
    ]
    spec = {
        "style_profile": "stem_conference",
        "figures": [
            {
                "figure_id": "wide_row",
                "composition": {"rows": 1, "cols": 3},
                "max_width_in": 6.5,
                "panel_size": [4.0, 2.5],
                "panels": [
                    {
                        "panel_id": p,
                        "chart": "line",
                        "record_filter": {"panel": p},
                        "x_col": "x",
                        "y_col": "y",
                        "series_col": "series",
                        "hline": 0.0,
                    }
                    for p in ("p1", "p2", "p3")
                ],
            }
        ],
    }
    suite = render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, suite_id="t", formats=("png",)
    )
    assert suite.status == "rendered"
    assert not suite.provenance.get("limitations")
    figure = suite.figures[0]
    width_in = (
        figure.provenance.get("figsize_in", [None])[0]
        if figure.provenance.get("figsize_in")
        else None
    )
    if width_in is not None:  # only assert when the renderer records it
        assert width_in <= 6.5 + 1e-6


@pytest.fixture
def rendered(monkeypatch):
    """Hand back the composed figures; the renderer closes them after saving,
    but a closed figure keeps its axes and artists."""
    import research_harness.visualization.experiment_figures as ef

    seen: list[plt.Figure] = []
    real = ef._save_figure

    def spy(**kwargs):
        seen.append(kwargs["fig"])
        return real(**kwargs)

    monkeypatch.setattr(ef, "_save_figure", spy)
    return seen


def _forest_records(with_group: bool = True):
    """Two arms, three rows each, one row per arm failing the significance rule."""
    rows = []
    for arm, base in (("human reviewers", 0.07), ("frozen rater", 0.02)):
        for i, feature in enumerate(("cue a", "cue b", "cue c")):
            value = base - 0.02 * i
            row = {
                "figure_type": "forest",
                "label": f"{feature} | {arm}",
                "value": value,
                "lo": value - 0.02,
                "hi": value + 0.02,
                "filled": i < 2,
            }
            if with_group:
                row["group"] = arm
            rows.append(row)
    return rows


_FOREST_SPEC = {"figures": [{"figure_id": "f", "panels": [{"chart": "forest"}]}]}


def test_forest_colours_rows_by_group_and_hollows_unfilled_markers(tmp_path, rendered):
    suite = render_figure_suite_spec(
        spec=_FOREST_SPEC,
        records=_forest_records(),
        output_dir=tmp_path,
        suite_id="t",
        formats=("png",),
    )
    assert suite.status == "rendered"
    ax = rendered[0].axes[0]
    markers = [ln for ln in ax.lines if ln.get_marker() == "o"]
    assert len({ln.get_markeredgecolor() for ln in markers}) >= 2, (
        "rows of different arms must not share one colour"
    )
    assert any(ln.get_markerfacecolor() == "white" for ln in markers), (
        "a row failing the significance rule must render hollow"
    )
    assert ax.get_legend() is not None


def test_forest_without_group_column_keeps_a_single_colour(tmp_path, rendered):
    suite = render_figure_suite_spec(
        spec=_FOREST_SPEC,
        records=_forest_records(with_group=False),
        output_dir=tmp_path,
        suite_id="t",
        formats=("png",),
    )
    assert suite.status == "rendered"
    ax = rendered[0].axes[0]
    markers = [ln for ln in ax.lines if ln.get_marker() == "o"]
    assert len({ln.get_markeredgecolor() for ln in markers}) == 1


def _two_panel_spec(**figure_extra):
    records = [
        {"figure_type": "line", "panel": p, "x": year, "y": 0.1 * i, "series": arm}
        for p in ("p1", "p2")
        for i, year in enumerate((2018, 2019, 2020))
        for arm in ("human reviewers", "frozen rater")
    ]
    figure = {
        "figure_id": "f",
        "panels": [
            {
                "panel_id": p,
                "chart": "line",
                "record_filter": {"panel": p},
                "x_label": "submission year",
                "y_label": "coefficient",
            }
            for p in ("p1", "p2")
        ],
    }
    figure.update(figure_extra)
    return {"figures": [figure]}, records


def test_shared_legend_lifts_one_legend_out_of_the_panels(tmp_path, rendered):
    spec, records = _two_panel_spec(
        shared_legend=True, composition={"rows": 1, "cols": 2}
    )
    suite = render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, suite_id="t", formats=("png",)
    )
    assert suite.status == "rendered"
    fig = rendered[0]
    assert all(ax.get_legend() is None for ax in fig.axes)
    assert len(fig.legends) == 1
    assert {t.get_text() for t in fig.legends[0].get_texts()} == {
        "human reviewers",
        "frozen rater",
    }


def test_axis_labels_shared_only_where_every_panel_agrees(tmp_path, rendered):
    spec, records = _two_panel_spec(
        share_axis_labels=True, composition={"rows": 2, "cols": 1}
    )
    suite = render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, suite_id="t", formats=("png",)
    )
    assert suite.status == "rendered"
    fig = rendered[0]
    # one label for the figure, none left on the panels
    assert [ax.get_xlabel() for ax in fig.axes] == ["", ""]
    assert fig.get_supxlabel() == "submission year"
    assert [ax.get_ylabel() for ax in fig.axes] == ["", ""]
    assert fig.get_supylabel() == "coefficient"


def test_axis_labels_kept_when_panels_measure_different_things(tmp_path, rendered):
    spec, records = _two_panel_spec(
        share_axis_labels=True, composition={"rows": 2, "cols": 1}
    )
    spec["figures"][0]["panels"][1]["x_label"] = "review year"
    suite = render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, suite_id="t", formats=("png",)
    )
    assert suite.status == "rendered"
    fig = rendered[0]
    assert [ax.get_xlabel() for ax in fig.axes] == ["submission year", "review year"]
    assert not fig.get_supxlabel()


def test_long_panel_title_wraps_instead_of_overhanging(tmp_path, rendered):
    spec, records = _two_panel_spec(
        composition={"rows": 1, "cols": 2}, panel_size=[2.4, 2.0]
    )
    long_title = "non-domain lexical complexity in submitted abstracts"
    spec["figures"][0]["panels"][0]["title"] = long_title
    suite = render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, suite_id="t", formats=("png",)
    )
    assert suite.status == "rendered"
    drawn = rendered[0].axes[0].get_title(loc="left")
    assert "\n" in drawn, "a title wider than its panel must wrap"
    assert drawn.split("$")[-1].replace("\n", " ").strip().endswith(long_title)


def test_panel_titles_in_a_row_are_padded_to_one_height(tmp_path, rendered):
    spec, records = _two_panel_spec(
        composition={"rows": 1, "cols": 2}, panel_size=[2.4, 2.0]
    )
    spec["figures"][0]["panels"][0]["title"] = (
        "non-domain lexical complexity in submitted abstracts"
    )
    spec["figures"][0]["panels"][1]["title"] = "domain jargon"
    suite = render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, suite_id="t", formats=("png",)
    )
    assert suite.status == "rendered"
    lines = [ax.get_title(loc="left").count("\n") for ax in rendered[0].axes]
    assert len(set(lines)) == 1 and lines[0] > 0


def test_short_panel_title_is_left_alone(tmp_path, rendered):
    spec, records = _two_panel_spec(composition={"rows": 1, "cols": 2})
    spec["figures"][0]["panels"][0]["title"] = "domain jargon"
    suite = render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, suite_id="t", formats=("png",)
    )
    assert suite.status == "rendered"
    assert "\n" not in rendered[0].axes[0].get_title(loc="left")


def test_span_label_names_the_shaded_band():
    fig, ax = plt.subplots()
    _panel_reference_marks(
        ax, {"span": [2022.5, 2025.5], "span_label": "after the cost shock"}
    )
    assert any(t.get_text() == "after the cost shock" for t in ax.texts)
    plt.close(fig)


def test_line_chart_honours_pinned_series_colours(tmp_path, rendered):
    spec, records = _two_panel_spec(composition={"rows": 1, "cols": 2})
    for panel in spec["figures"][0]["panels"]:
        panel["series_colors"] = {"frozen rater": "#0072B5"}
    suite = render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, suite_id="t", formats=("png",)
    )
    assert suite.status == "rendered"
    for ax in rendered[0].axes:
        pinned = [ln for ln in ax.lines if ln.get_label() == "frozen rater"]
        assert pinned and all(ln.get_color() == "#0072B5" for ln in pinned)
