"""Deterministic layout controls measured from actual drawn axes."""

from copy import deepcopy
from pathlib import Path

import pytest

from research_harness.visualization import experiment_figures as renderer


def _render(tmp_path, monkeypatch, composition="2x2", overrides=None):
    panels = [
        {"panel_id": name, "chart": "bar", "record_filter": {"panel": name}}
        for name in ("a", "b", "c")
    ]
    for panel, extra in zip(panels, overrides or []):
        panel.update(extra)
    records = [
        {"panel": panel["panel_id"], "label": label, "value": value}
        for panel in panels
        for label, value in (("x", 1), ("y", 2))
    ]
    boxes = []
    original = renderer._save_figure

    def capture(**kwargs):
        fig = kwargs["fig"]
        fig.canvas.draw()
        axes = [*fig.axes, *(child for ax in fig.axes for child in ax.child_axes)]
        boxes.extend(ax.get_position().frozen() for ax in axes)
        return original(**kwargs)

    monkeypatch.setattr(renderer, "_save_figure", capture)
    spec = {
        "figures": [
            {"figure_id": "control", "composition": composition, "panels": panels}
        ]
    }
    before = deepcopy(spec)
    suite = renderer.render_figure_suite_spec(
        spec=spec, records=records, output_dir=tmp_path, formats=("pdf",)
    )
    assert spec == before
    assert Path(suite.figures[0].paths["pdf"]).is_file()
    return boxes


def test_asymmetric_mosaic_has_real_spanning_axes(tmp_path, monkeypatch):
    a, b, c = _render(tmp_path, monkeypatch, "AAB;CCB")
    assert a.width > b.width * 1.5
    assert b.height > a.height * 1.5
    assert a.y0 > c.y1
    assert b.x0 > a.x1


def test_explicit_row_and_column_spans(tmp_path, monkeypatch):
    a, b, c = _render(
        tmp_path,
        monkeypatch,
        "2x3",
        [
            {"layout_span": [1, 2]},
            {"layout_span": [2, 1]},
            {"layout_span": [1, 2]},
        ],
    )
    assert a.width > b.width * 1.5
    assert b.height > a.height * 1.5
    assert a.y0 > c.y1


def test_inset_is_parent_relative(tmp_path, monkeypatch):
    a, c, inset = _render(
        tmp_path,
        monkeypatch,
        "1x2",
        [
            {},
            {"inset": True, "inset_parent": "a", "inset_bounds": [0.5, 0.5, 0.4, 0.4]},
            {},
        ],
    )
    assert inset.x0 == pytest.approx(a.x0 + 0.5 * a.width)
    assert inset.y0 == pytest.approx(a.y0 + 0.5 * a.height)
    assert inset.width == pytest.approx(0.4 * a.width)
    assert inset.height == pytest.approx(0.4 * a.height)
    assert c.x0 > a.x1


@pytest.mark.parametrize(
    "composition,overrides",
    [
        ("AA;AB", []),  # One panel occupies a nonrectangular L.
        ("AB;C", []),
        ("AB;DD", []),
        ("2x2", [{"layout_span": [3, 1]}]),
        ("2x2", [{"grid_position": [0, 0]}, {"grid_position": [0, 0]}]),
        ("2x2", [{"grid_position": [2, 0]}]),
        ("2x2", [{"layout_span": [0, 1]}]),
        ("2x2", [{"inset": True}]),
        ("2x2", [{}, {"inset": True, "inset_parent": "absent"}]),
        ("2x2", [{}, {"inset": True, "inset_bounds": [0.8, 0.8, 0.4, 0.4]}]),
        ("2x2", [{}, {"panel_id": "a"}]),
        ("2x2", [{"inset": True}, {"inset": True}, {"inset": True}]),
        ("AAB;CCB", [{"layout_span": [1, 1]}]),
        ("AAB;CCB", [{"grid_position": [1, 0]}]),
        ("2x2", [{"grid_position": "bad"}]),
        ("2x2", [{}, {"inset": 1}]),
        ("2x2", [{}, {"inset_bounds": [0.1, 0.1, 0.3, 0.3]}]),
        ("2x2", [{}, {"inset": True, "layout_span": [2, 1]}]),
        ("2x2", [{}, {"inset": True, "inset_bounds": [0, 0, float("nan"), 0.4]}]),
        ("2x2", [{}, {"inset": True}, {"inset": True}]),
    ],
)
def test_invalid_layout_fails_before_export(
    tmp_path, monkeypatch, composition, overrides
):
    with pytest.raises(ValueError, match="layout|mosaic|inset|span"):
        _render(tmp_path, monkeypatch, composition, overrides)
    assert not list(tmp_path.glob("*.pdf"))


@pytest.mark.parametrize("composition", ["2x2", "2X2", {"rows": 2, "cols": 2}])
def test_ordinary_grid_still_renders(tmp_path, monkeypatch, composition):
    a, b, c = _render(tmp_path, monkeypatch, composition)
    assert a.width == pytest.approx(b.width)
    assert a.height == pytest.approx(c.height)
    assert b.x0 > a.x1 and a.y0 > c.y1


def test_mosaic_holes_and_default_inset(tmp_path, monkeypatch):
    a, c, inset = _render(tmp_path, monkeypatch, "A.;.C", [{}, {"inset": True}, {}])
    assert a.y0 > c.y1
    assert inset.x0 == pytest.approx(a.x0 + 0.55 * a.width)


def test_mosaic_span_confirmation_and_explicit_positions(tmp_path, monkeypatch):
    a, b, c = _render(
        tmp_path,
        monkeypatch,
        "AAB;CCB",
        [
            {"layout_span": [1, 2], "grid_position": [0, 0]},
            {"layout_span": [2, 1]},
            {"layout_span": [1, 2]},
        ],
    )
    assert b.height > a.height * 1.5


def test_single_row_mosaic(tmp_path, monkeypatch):
    a, b, c = _render(tmp_path, monkeypatch, "ABC")
    assert a.x1 < b.x0 < c.x0
