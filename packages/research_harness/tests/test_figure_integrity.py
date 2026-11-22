"""Regression tests for figure-file integrity checks.

Pins the two defects that shipped across a submission wave: matplotlib figures
saved without a tight bounding box (content drawn outside the page box, so a
legend or whole panel silently disappears) and ad-hoc hex palettes that ignore
``PALETTE_POOL``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from research_harness.visualization.experiment_figures import PALETTE_POOL  # noqa: E402
from research_harness.visualization.figure_integrity import (  # noqa: E402
    check_text_collisions,
    check_clipping,
    check_figure,
    check_figure_dir,
    check_grayscale_separability,
    check_palette,
    format_report,
    palette_rgb,
)

CORE = PALETTE_POOL["rh"]


@pytest.fixture(autouse=True)
def _clean_rcparams():
    # Style profiles call sns.set_theme, which mutates global rcParams. A
    # leaked coloured axes.edgecolor (stem_conference uses #243447) makes an
    # otherwise greyscale figure read as off-palette under random test order.
    matplotlib.rcdefaults()
    yield
    matplotlib.rcdefaults()


def _plot(path: Path, *, tight: bool, colors=None, outside=False) -> Path:
    colors = colors or CORE[:2]
    fig, ax = plt.subplots(figsize=(3, 2))
    for i, c in enumerate(colors):
        ax.plot([0, 1], [i, i + 1], color=c, linewidth=3)
    if outside:
        ax.legend(
            [f"s{i}" for i in range(len(colors))],
            loc="center left",
            bbox_to_anchor=(1.4, 0.5),
        )
    if tight:
        fig.savefig(path, bbox_inches="tight", pad_inches=0.08)
    else:
        fig.savefig(path)
    plt.close(fig)
    return path


class TestClipping:
    def test_content_outside_canvas_is_major(self, tmp_path):
        f = _plot(tmp_path / "clipped.pdf", tight=False, outside=True)
        findings = check_clipping(f)
        assert [x.check for x in findings] == ["clipped_content"]
        assert findings[0].severity == "major"

    def test_tight_bbox_figure_has_no_major(self, tmp_path):
        f = _plot(tmp_path / "clean.pdf", tight=True, outside=True)
        assert not [x for x in check_clipping(f) if x.severity == "major"]

    def test_zero_margin_save_is_minor_not_major(self, tmp_path):
        f = _plot(tmp_path / "edge.pdf", tight=False)
        findings = check_clipping(f)
        assert all(x.severity == "minor" for x in findings)

    def test_missing_file_abstains(self, tmp_path):
        assert check_clipping(tmp_path / "nope.pdf") == []

    def test_hatched_bar_under_nonzero_ylim_is_not_clipped(self, tmp_path):
        # Two ways a correct figure reports geometry far outside the page and
        # renders perfectly anyway: a bar rectangle starts at data zero and is
        # clipped by the axes, and a hatch ships as a PDF tiling pattern whose
        # cell is defined in pattern space at negative coordinates.
        f = tmp_path / "hatched.pdf"
        fig, ax = plt.subplots(figsize=(3, 2))
        bars = ax.bar(["a", "b"], [0.72, 0.76], color=CORE[1])
        bars[1].set_hatch("//")
        ax.set_ylim(0.6, 0.8)
        fig.savefig(f, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
        assert check_clipping(f) == []


class TestPalette:
    def test_palette_pool_is_recognised(self, tmp_path):
        f = _plot(tmp_path / "onpalette.pdf", tight=True, colors=CORE[:4])
        assert check_palette(f) == []

    def test_hand_picked_hexes_flagged(self, tmp_path):
        f = _plot(
            tmp_path / "offpalette.pdf",
            tight=True,
            colors=["#2a78d6", "#eb6834", "#1baf7a"],
        )
        findings = check_palette(f)
        assert [x.check for x in findings] == ["off_palette"]
        assert findings[0].severity == "minor"

    def test_greyscale_figure_is_not_off_palette(self, tmp_path):
        # Structural ink (axes, text, grid) must never count as a palette choice.
        f = _plot(tmp_path / "grey.pdf", tight=True, colors=["#333333", "#888888"])
        assert check_palette(f) == []

    def test_rh_theme_axis_ink_is_not_off_palette(self, tmp_path):
        # stem_conference draws spines in navy #243447; RH's own theme must
        # not push a pool-coloured figure under the coverage floor.
        matplotlib.rcParams["axes.edgecolor"] = "#243447"
        f = _plot(tmp_path / "themed.pdf", tight=True, colors=CORE[:1])
        assert check_palette(f) == []

    def test_palette_rgb_covers_core(self):
        rgb = palette_rgb()
        assert len(rgb) >= len(CORE)


class TestGrayscale:
    def test_near_identical_luminance_flagged(self, tmp_path):
        f = _plot(
            tmp_path / "collapse.pdf",
            tight=True,
            colors=["#4daf4a", "#ff7f00"],
        )
        findings = check_grayscale_separability(f)
        assert [x.check for x in findings] == ["grayscale_collision"]
        assert findings[0].severity == "minor"

    def test_separated_hues_pass(self, tmp_path):
        # rh[0] and rh[1] share luminance (~0.031 apart). The pair the check
        # must let through is the darkest and the lightest in the pool.
        f = _plot(tmp_path / "sep.pdf", tight=True, colors=[CORE[0], CORE[5]])
        assert check_grayscale_separability(f) == []


class TestReporting:
    def test_directory_scan_sorts_majors_first(self, tmp_path):
        _plot(tmp_path / "a_clean.pdf", tight=True, colors=[CORE[0], CORE[5]])
        _plot(tmp_path / "b_clipped.pdf", tight=False, outside=True)
        report = check_figure_dir(tmp_path)
        assert not report.ok
        assert report.findings[0].severity == "major"
        assert report.to_dict()["major_count"] == 1

    def test_clean_directory_reports_clean(self, tmp_path):
        _plot(tmp_path / "ok.pdf", tight=True, colors=[CORE[0], CORE[5], CORE[3]])
        report = check_figure_dir(tmp_path)
        assert report.ok
        assert format_report(report) == "figures: clean"

    def test_check_figure_combines_both_families(self, tmp_path):
        f = _plot(
            tmp_path / "both.pdf",
            tight=False,
            outside=True,
            colors=["#2a78d6", "#eb6834"],
        )
        checks = {x.check for x in check_figure(f).findings}
        assert "clipped_content" in checks
        assert "off_palette" in checks


class TestTextCollisions:
    """Ink-overflow checks are blind to labels colliding inside the canvas."""

    def test_overlapping_labels_flagged(self, tmp_path):
        f = tmp_path / "collide.pdf"
        fig, ax = plt.subplots(figsize=(2, 2))
        ax.plot([0, 1], [0, 1], color=CORE[0])
        # Two labels written to the same spot: the legend-over-curve case.
        ax.text(0.5, 0.5, "log-rank P<0.001", ha="center")
        ax.text(0.5, 0.5, "High risk stratum", ha="center")
        fig.savefig(f, bbox_inches="tight", pad_inches=0.08)
        plt.close(fig)
        findings = check_text_collisions(f)
        assert [x.check for x in findings] == ["text_collision"]
        assert findings[0].severity == "major"

    def test_normal_labels_clean(self, tmp_path):
        f = tmp_path / "clean.pdf"
        fig, ax = plt.subplots(figsize=(4, 3))
        ax.plot([0, 1], [0, 1], color=CORE[0], label="series")
        ax.set_xlabel("months")
        ax.set_ylabel("probability")
        ax.legend(loc="lower right")
        fig.savefig(f, bbox_inches="tight", pad_inches=0.08)
        plt.close(fig)
        assert check_text_collisions(f) == []

    def test_dense_tick_labels_do_not_false_positive(self, tmp_path):
        # Adjacent tick labels share edges; that is typesetting, not collision.
        f = tmp_path / "ticks.pdf"
        fig, ax = plt.subplots(figsize=(4, 2.4))
        ax.bar(range(8), range(1, 9), color=CORE[1])
        ax.set_xticks(range(8))
        ax.set_xticklabels([f"cond{i}" for i in range(8)], rotation=45, ha="right")
        fig.savefig(f, bbox_inches="tight", pad_inches=0.08)
        plt.close(fig)
        assert check_text_collisions(f) == []


class TestRotationAndGluedLabels:
    """Two ways the word-box test misreads a figure, both found in real papers."""

    def _bars(self, path, labels, rotation):
        fig, ax = plt.subplots(figsize=(4, 2.4))
        ax.bar(range(len(labels)), range(1, len(labels) + 1), color=CORE[0])
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(
            labels, rotation=rotation, ha="right" if rotation else "center"
        )
        fig.savefig(path, bbox_inches="tight", pad_inches=0.08)
        plt.close(fig)
        return path

    def test_rotated_labels_are_not_collisions(self, tmp_path):
        # An axis-aligned box around rotated text always overlaps its neighbour's
        # box even when the glyphs clear. Rotation is the correct fix for crowded
        # labels, so flagging it would push authors away from the right repair.
        labels = [
            "FaceFormer",
            "EmoTalk",
            "EmoFace",
            "DiffPoseTalk",
            "CodeTalker",
            "Ours",
        ]
        for rotation in (30, 45):
            f = self._bars(tmp_path / f"rot{rotation}.pdf", labels, rotation)
            assert check_text_collisions(f) == [], (
                f"rotation={rotation} false-positived"
            )

    def test_horizontal_crowding_still_caught(self, tmp_path):
        # The same labels unrotated genuinely collide, and that must still fire.
        labels = [
            "FaceFormer",
            "EmoTalk",
            "EmoFace",
            "DiffPoseTalk",
            "CodeTalker",
            "Ours",
        ]
        f = self._bars(tmp_path / "flat.pdf", labels, 0)
        assert check_text_collisions(f)

    def test_camelcase_names_are_not_glued_labels(self, tmp_path):
        # Real method names carry internal capitals; only three-plus segments
        # with no separator indicate two labels printed with no gap.
        f = self._bars(tmp_path / "camel.pdf", ["FaceFormer", "DiffPoseTalk"], 45)
        assert check_text_collisions(f) == []


class TestClinicalPaletteIsApproved:
    """The clinical family must be poolable, and its tints must count as on-palette.

    Both halves come from one real defect: `biomed_omics` rendered with an
    eight-colour clinical set that lived only inside STYLE_PROFILES, so a figure
    that obeyed its own profile measured as fully off-palette, and writers were
    handed "tissue" instead. Downstream that pushed an author into hand-picking
    hex values for the light end of an ordered ramp.
    """

    def test_clinical_family_is_in_the_pool(self):
        from research_harness.visualization.experiment_figures import (
            PALETTE_POOL,
            STYLE_PROFILES,
        )

        assert "rh" in PALETTE_POOL
        # The profile must render from the pool entry, not a private copy that
        # can drift away from it.
        assert STYLE_PROFILES["biomed_omics"]["palette"] is PALETTE_POOL["rh"]

    def test_tints_of_an_approved_colour_are_on_palette(self):
        from research_harness.visualization.figure_integrity import (
            _hex_to_rgb,
            _is_tint_of,
        )

        base = _hex_to_rgb("#0072B5")
        for tint in ("#0072B5", "#4799CA", "#8ABEDD", "#CCE3F0"):
            assert _is_tint_of(_hex_to_rgb(tint), base), tint

    def test_an_unrelated_hue_is_not_a_tint(self):
        from research_harness.visualization.figure_integrity import (
            _hex_to_rgb,
            _is_tint_of,
        )

        base = _hex_to_rgb("#0072B5")
        # A hand-picked warm hue is exactly what the gate exists to catch.
        assert not _is_tint_of(_hex_to_rgb("#D89A54"), base)
        # Near-white greys are structural ink, not a tint of the brand blue.
        assert not _is_tint_of(_hex_to_rgb("#F2F2F2"), base)
