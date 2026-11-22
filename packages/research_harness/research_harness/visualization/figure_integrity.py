"""Deterministic integrity checks for figure files before they enter a manuscript.

Two defect families shipped in four manuscripts because nothing inspected the
rendered artwork:

* **Clipped content** — matplotlib writes the canvas at ``figsize``, but a
  legend, colourbar, or long tick label placed outside the axes is *not* pulled
  back in unless the figure is saved with a tight bounding box. The result is a
  PDF that paints ink outside the page box: the viewer simply does not draw it.
  The check measures *rendered* ink, not path bounds, because clipped bars and
  hatch tiling patterns both report geometry far outside the page while
  rendering perfectly — see :func:`ink_overflow_pt`.
* **Off-palette colour** — the Nature-family palette lives in
  ``experiment_figures.PALETTE_POOL``, but each ad-hoc plotting script picked
  its own hexes, so papers in one submission wave disagreed on colour.

Both checks read the file, not the script that produced it, so they hold
whoever drew the figure to the same standard. A later grayscale pass
flags two non-neutral hues that collapse to the same luminance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .experiment_figures import PALETTE_POOL, STYLE_PROFILES

# Stroke geometry legitimately bleeds a few points past the page box: a line
# drawn on the axis spine paints half its width outside, and matplotlib rounds
# the canvas to whole points. Only overflow past this margin means a reader
# actually loses content.
CLIP_TOLERANCE_PT = 6.0
# Below the clip threshold but still outside: not lost, but shaved at print.
TIGHT_MARGIN_PT = 1.0
# How far past the page box the probe looks for stray ink, and at what
# resolution. 72 dpi makes one pixel one point, so the measurement is already
# in the unit the report speaks.
OVERFLOW_PROBE_PT = 144.0
_PROBE_DPI = 72
# Anything lighter than this counts as paper, not ink.
_INK_LEVEL = 250

# Greys and near-black/white are structural (axes, text, grid), not palette
# choices, so they never count as off-palette.
_NEUTRAL_TOLERANCE = 0.06
# Share of coloured ink that must come from the palette before a figure counts
# as on-palette. Kept below 1.0 because colormaps (heatmaps, gradients) legally
# interpolate away from the discrete palette.
PALETTE_COVERAGE_FLOOR = 0.85
# Two categorical hues closer than this in relative luminance will not survive
# greyscale print. Kept below the core Nature-family pair gap (~0.076).
_GRAYSCALE_LUMINANCE_GAP = 0.05

# Share of the smaller word box that must be covered before two extracted words
# count as colliding. Adjacent words in one line share an edge and kerned glyph
# boxes overlap by a hairline, so anything below this is normal typesetting.
_COLLISION_AREA_RATIO = 0.25


@dataclass
class FigureFinding:
    check: str
    severity: str  # "major" | "minor"
    message: str
    figure: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "figure": self.figure,
        }


@dataclass
class FigureReport:
    findings: list[FigureFinding] = field(default_factory=list)

    @property
    def majors(self) -> list[FigureFinding]:
        return [f for f in self.findings if f.severity == "major"]

    @property
    def ok(self) -> bool:
        return not self.majors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "major_count": len(self.majors),
            "findings": [f.to_dict() for f in self.findings],
        }


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _is_neutral(rgb: Sequence[float]) -> bool:
    """True for greys, black and white — structural ink, not palette colour."""
    return max(rgb) - min(rgb) <= _NEUTRAL_TOLERANCE


def _is_tint_of(
    rgb: Sequence[float],
    base: Sequence[float],
    *,
    tolerance: float = 0.045,
    min_fraction: float = 0.12,
) -> bool:
    """True when ``rgb`` is ``base`` mixed with white.

    A tint keeps the hue and only loses saturation, so it stays inside the
    approved family. Solve the mixing fraction on the channel that moves most
    (the darkest one carries the signal) and check every channel agrees.
    """
    deltas = [1.0 - float(c) for c in base]
    span = max(deltas)
    if span < 1e-6:  # base is white; nothing is a tint of it
        return False
    fraction = (1.0 - float(rgb[deltas.index(span)])) / span
    if not (min_fraction <= fraction <= 1.0):
        return False
    return all(
        abs(float(c) - (1.0 - d * fraction)) <= tolerance for c, d in zip(rgb, deltas)
    )


def structural_rgb() -> set[tuple[float, float, float]]:
    """Axis, grid and text ink the RH style profiles themselves set.

    These are not data colours. ``stem_conference`` draws its spines in navy
    ``#243447``, which is too saturated to pass as neutral, so every figure
    rendered with RH's own theme measured its axes as off-palette.
    """
    out: set[tuple[float, float, float]] = set()
    for profile in STYLE_PROFILES.values():
        for key, value in profile.get("theme", {}).get("rc", {}).items():
            if "color" in key and isinstance(value, str) and value.startswith("#"):
                out.add(tuple(round(c, 2) for c in _hex_to_rgb(value)))  # type: ignore[arg-type]
    return out


def palette_rgb(pools: Iterable[str] | None = None) -> set[tuple[float, float, float]]:
    """Every colour the owner-approved palettes and RH sequential ramps allow, as rounded RGB.

    PALETTE_POOL *is* the set of approved palettes, so it is read whole rather
    than re-listed here. Also includes samples along RH's canonical ``YlGnBu``
    sequential ramp used for heatmaps and colourbars.
    """
    out: set[tuple[float, float, float]] = set()
    for name in pools if pools is not None else PALETTE_POOL:
        for hexcode in PALETTE_POOL.get(name, []):
            out.add(tuple(round(c, 2) for c in _hex_to_rgb(hexcode)))  # type: ignore[arg-type]
    # Canonical YlGnBu ramp stops (interpolated so continuous scatter/heatmap ramps pass check_palette).
    ylgnbu = [
        _hex_to_rgb(h)
        for h in (
            "#ffffd9",
            "#edf8b1",
            "#c7e9b4",
            "#7fcdbb",
            "#41b6c4",
            "#1d91c0",
            "#225ea8",
            "#253494",
            "#081d58",
        )
    ]
    for a, b in zip(ylgnbu, ylgnbu[1:]):
        for step in range(9):
            t = step / 8.0
            out.add(tuple(round(a[i] + t * (b[i] - a[i]), 2) for i in range(3)))  # type: ignore[arg-type]
    return out


def ink_overflow_pt(pdf_path: str | Path) -> float | None:
    """Points by which *rendered* ink extends past the page box, or ``None``.

    Path bounds are not the answer. A bar whose rectangle starts at data zero
    under a non-zero ``ylim`` reports geometry hundreds of points below the
    axes yet is clipped away by the axes clip path, and a matplotlib hatch is
    emitted as a PDF tiling pattern whose cell lives in pattern space at
    negative coordinates. Both look catastrophically clipped and both render
    perfectly. Rasterising the page on an enlarged media box measures what a
    reader actually loses. Negative means the ink stops short of the edge.
    """
    path = Path(pdf_path)
    try:
        import fitz  # type: ignore
        import numpy as np
    except ImportError:
        return None

    try:
        doc = fitz.open(path)
    except Exception:
        return None
    try:
        page = doc[0]
        box = page.rect
        m = OVERFLOW_PROBE_PT
        page.set_mediabox(fitz.Rect(box.x0 - m, box.y0 - m, box.x1 + m, box.y1 + m))
        pix = page.get_pixmap(dpi=_PROBE_DPI, colorspace=fitz.csGRAY)
        grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    except Exception:
        return None
    finally:
        doc.close()

    ys, xs = np.where(grey < _INK_LEVEL)
    if not len(xs):
        return None
    scale = 72.0 / _PROBE_DPI
    return float(
        max(
            m - xs.min() * scale,
            m - ys.min() * scale,
            (xs.max() + 1) * scale - (m + box.width),
            (ys.max() + 1) * scale - (m + box.height),
        )
    )


def check_clipping(pdf_path: str | Path) -> list[FigureFinding]:
    """Findings when drawn content falls outside the page box.

    Requires PyMuPDF; without it the check abstains rather than guessing.
    """
    path = Path(pdf_path)
    overflow = ink_overflow_pt(path)
    if overflow is None:
        return []

    if overflow > CLIP_TOLERANCE_PT:
        return [
            FigureFinding(
                check="clipped_content",
                severity="major",
                message=(
                    f"{overflow:.0f}pt of drawn content falls outside the page box and "
                    "will not render; save with bbox_inches='tight' (or enlarge the "
                    "figure) so legends and labels stay inside the canvas"
                ),
                figure=path.name,
            )
        ]
    if overflow > TIGHT_MARGIN_PT:
        return [
            FigureFinding(
                check="edge_tight_content",
                severity="minor",
                message=(
                    f"content extends {overflow:.1f}pt past the page box — within "
                    "stroke-width tolerance, but add pad_inches when saving so "
                    "nothing is shaved at print"
                ),
                figure=path.name,
            )
        ]
    return []


def check_palette(
    pdf_path: str | Path, pools: list[str] | None = None
) -> list[FigureFinding]:
    """Findings when a figure's colours fall outside the named palettes.

    ``pools`` defaults to the whole pool. A caller that has retired every pool
    but one passes that one, and a miss is then major rather than minor.
    """
    path = Path(pdf_path)
    structural = structural_rgb()
    used = [
        rgb
        for rgb in _drawing_rgbs(path)
        if not any(max(abs(a - b) for a, b in zip(rgb, s)) <= 0.04 for s in structural)
    ]
    if not used:
        return []

    allowed = palette_rgb(pools)

    def near_allowed(rgb: tuple[float, float, float]) -> bool:
        if any(max(abs(a - b) for a, b in zip(rgb, cand)) <= 0.04 for cand in allowed):
            return True
        # A tint of an approved colour on white is still that colour: ordered
        # quantities (a stop/low/high ladder, a stage axis) need a light-to-dark
        # ramp, and the pool ships discrete categoricals only. Accept a colour
        # that sits on the white line of some palette entry, so a writer encoding
        # order inside one hue is not pushed into inventing a second hue family.
        return any(_is_tint_of(rgb, cand) for cand in allowed)

    on = sum(1 for rgb in used if near_allowed(rgb))
    coverage = on / len(used)
    if coverage < PALETTE_COVERAGE_FLOOR:
        off = sorted(
            "#%02X%02X%02X" % tuple(int(round(c * 255)) for c in rgb)
            for rgb in used
            if not near_allowed(rgb)
        )
        return [
            FigureFinding(
                check="off_palette",
                severity="major" if pools is not None else "minor",
                message=(
                    f"{len(off)} of {len(used)} colours are outside the approved "
                    f"palettes (e.g. {', '.join(off[:4])}); import PALETTE_POOL from "
                    "research_harness.visualization.experiment_figures instead of "
                    "hand-picking hex values"
                ),
                figure=path.name,
            )
        ]
    return []


def _rotated_bands(page: Any) -> list[Any]:
    """Bounding boxes of text runs that are not horizontal.

    The PDF text layer records a direction vector per line, so rotated tick
    labels can be told apart from horizontal ones instead of being guessed at.
    """
    import fitz  # type: ignore

    bands: list[Any] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1.0, 0.0))
            if abs(dy) > 0.02 or dx < 0.98:
                bands.append(fitz.Rect(line["bbox"]))
    return bands


def check_text_collisions(pdf_path: str | Path) -> list[FigureFinding]:
    """Findings when text is drawn on top of other text inside the canvas.

    Clipping checks measure ink leaving the page box; they are blind to a legend
    printed over a curve, tick labels running into each other, or an at-risk
    table overlapping the caption row — all of which render "correctly" and all
    of which a reader cannot read. Overlap is judged on the extracted word
    boxes, so it sees the same collisions a person does.
    """
    path = Path(pdf_path)
    try:
        import fitz  # type: ignore
    except ImportError:
        return []

    try:
        doc = fitz.open(path)
    except Exception:
        return []

    try:
        words = doc[0].get_text("words")
        rotated = _rotated_bands(doc[0])
    except Exception:
        return []
    finally:
        doc.close()

    collisions: list[tuple[str, str]] = []
    # Rotated text is measured by an axis-aligned box that necessarily overlaps
    # its neighbour's box even when the glyphs clear comfortably, so a rotated
    # tick label always reads as a collision. Rotation is the correct fix for
    # crowded labels, so a checker that punishes it pushes authors the wrong way:
    # exclude rotated runs and judge them by eye.
    boxes = [
        (fitz.Rect(w[:4]), w[4])
        for w in words
        if not any(fitz.Rect(w[:4]).intersects(band) for band in rotated)
    ]
    for i, (a, wa) in enumerate(boxes):
        area_a = a.get_area()
        if area_a <= 0:
            continue
        for b, wb in boxes[i + 1 :]:
            area_b = b.get_area()
            if area_b <= 0:
                continue
            inter = a & b
            # A shared edge or a hairline touch is normal typesetting; only a
            # substantial shared area means one label is hiding another.
            if not inter.is_empty and inter.get_area() > _COLLISION_AREA_RATIO * min(
                area_a, area_b
            ):
                collisions.append((wa, wb))

    # Labels that touch exactly are extracted as ONE word ("Create" + "Access"
    # -> "CreateAccess"), so no overlap is ever reported and the defect is
    # invisible to the check above. Camel-case runs with no separator are the
    # signature; genuine CamelCase names (FaceFormer) are the false-positive
    # risk, so only flag runs of three or more capitalised segments.
    glued = [
        w for _, w in boxes if len(w) > 12 and len(re.findall(r"[a-z][A-Z]", w)) >= 2
    ]
    if glued:
        collisions.extend((w, "(adjacent label, no gap)") for w in glued[:3])

    if not collisions:
        return []
    sample = "; ".join(f"“{a}” over “{b}”" for a, b in collisions[:3])
    return [
        FigureFinding(
            check="text_collision",
            severity="major",
            message=(
                f"{len(collisions)} pair(s) of overlapping text inside the figure "
                f"({sample}); a legend printed over a curve or tick labels running "
                "together render fine and read as noise — widen the panel, rotate "
                "the labels, or move the legend outside the axes"
            ),
            figure=path.name,
        )
    ]


def _drawing_rgbs(pdf_path: str | Path) -> set[tuple[float, float, float]]:
    path = Path(pdf_path)
    try:
        import fitz  # type: ignore
    except ImportError:
        return set()
    try:
        doc = fitz.open(path)
    except Exception:
        return set()
    used: set[tuple[float, float, float]] = set()
    try:
        for drawing in doc[0].get_drawings():
            for key in ("fill", "color"):
                value = drawing.get(key)
                if not value:
                    continue
                rgb = tuple(round(float(c), 2) for c in value[:3])
                if not _is_neutral(rgb):
                    used.add(rgb)  # type: ignore[arg-type]
    finally:
        doc.close()
    return used


def _luminance(rgb: Sequence[float]) -> float:
    r, g, b = (float(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def check_grayscale_separability(pdf_path: str | Path) -> list[FigureFinding]:
    """Findings when two non-neutral hues collapse in greyscale print."""
    path = Path(pdf_path)
    used = _drawing_rgbs(path)
    if len(used) < 2:
        return []
    ranked = sorted((_luminance(rgb), rgb) for rgb in used)
    collisions: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    for (lum_a, rgb_a), (lum_b, rgb_b) in zip(ranked, ranked[1:]):
        if lum_b - lum_a < _GRAYSCALE_LUMINANCE_GAP:
            collisions.append((rgb_a, rgb_b))
    if not collisions:
        return []
    sample = ", ".join(
        "#%02X%02X%02X/~#%02X%02X%02X"
        % (
            int(round(a[0] * 255)),
            int(round(a[1] * 255)),
            int(round(a[2] * 255)),
            int(round(b[0] * 255)),
            int(round(b[1] * 255)),
            int(round(b[2] * 255)),
        )
        for a, b in collisions[:3]
    )
    return [
        FigureFinding(
            check="grayscale_collision",
            severity="minor",
            message=(
                f"{len(collisions)} colour pair(s) share nearly the same luminance "
                f"({sample}); they will not separate in greyscale print — recode "
                "one series with hatch or a darker/lighter step"
            ),
            figure=path.name,
        )
    ]


def check_figure(pdf_path: str | Path) -> FigureReport:
    """Run every integrity check over one figure file."""
    findings = (
        check_clipping(pdf_path)
        + check_palette(pdf_path)
        + check_text_collisions(pdf_path)
        + check_grayscale_separability(pdf_path)
    )
    return FigureReport(findings=findings)


def check_figure_dir(directory: str | Path) -> FigureReport:
    """Run the checks over every PDF figure in ``directory``."""
    findings: list[FigureFinding] = []
    for pdf in sorted(Path(directory).glob("*.pdf")):
        findings.extend(check_figure(pdf).findings)
    findings.sort(key=lambda f: (f.severity != "major", f.figure))
    return FigureReport(findings=findings)


def format_report(report: FigureReport) -> str:
    if not report.findings:
        return "figures: clean"
    lines = [
        f"figures: {len(report.majors)} major, "
        f"{len(report.findings) - len(report.majors)} minor"
    ]
    for f in report.findings:
        lines.append(f"  [{f.severity}] {f.check} — {f.figure}: {f.message}")
    return "\n".join(lines)


def demo() -> None:
    """Self-check: a clipped figure is caught, a tight-bbox one is not."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import tempfile

    core = PALETTE_POOL["rh"]
    with tempfile.TemporaryDirectory() as tmp:
        clipped = Path(tmp) / "clipped.pdf"
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.plot([0, 1], [0, 1], color=core[0])
        # A legend parked outside the axes with no tight bbox is the exact way
        # the shipped figures lost content.
        ax.legend(["series"], loc="center left", bbox_to_anchor=(1.4, 0.5))
        fig.savefig(clipped)
        plt.close(fig)

        clean = Path(tmp) / "clean.pdf"
        fig, ax = plt.subplots(figsize=(3, 2))
        ax.plot([0, 1], [0, 1], color=core[0])
        ax.legend(["series"], loc="center left", bbox_to_anchor=(1.02, 0.5))
        fig.savefig(clean, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)

        # A hatched bar under a non-zero ylim: geometry reports hundreds of
        # points outside the page, rendered ink reports none.
        hatched = Path(tmp) / "hatched.pdf"
        fig, ax = plt.subplots(figsize=(3, 2))
        bars = ax.bar(["a", "b"], [0.72, 0.76], color=core[1])
        bars[1].set_hatch("//")
        ax.set_ylim(0.6, 0.8)
        fig.savefig(hatched, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)

        clip_checks = {f.check for f in check_clipping(clipped)}
        assert "clipped_content" in clip_checks, clip_checks
        assert not [f for f in check_clipping(clean) if f.severity == "major"], (
            check_clipping(clean)
        )
        assert not check_clipping(hatched), check_clipping(hatched)

    assert palette_rgb(), "palette pool must not be empty"
    print("figure_integrity demo OK")


if __name__ == "__main__":
    demo()
