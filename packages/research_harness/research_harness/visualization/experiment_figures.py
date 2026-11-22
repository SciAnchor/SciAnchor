"""Publication-style experiment figure suite rendering.

Two entry points:

- ``render_experiment_figure_suite`` — the legacy fixed suite: one standalone
  figure per supported record ``figure_type`` (benchmark bar, ablation heatmap,
  radar, pareto, sensitivity).
- ``render_figure_suite_spec`` — the exemplar-anchored path: takes a figure
  SUITE SPEC (normally produced by ``exemplar_plan(unit_type=
  "figure_suite")`` by analogy to published exemplars) plus plain
  experiment records, and composes multi-panel figures with per-discipline
  style profiles (STEM conference / Nature family / social-humanities).

Only FORM comes from the spec (chart kinds, panel composition, style); every
number rendered comes from the caller's records — the renderer never invents
data, and panels whose records are missing are skipped and reported in
provenance rather than faked.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from research_harness.visualization.result_plot_policy import (
    empty_effect_reason,
    refuse_chart_kind,
    resolve_result_plot_policy,
)


DEFAULT_FORMATS = ("png",)
BACKEND_NAME = "seaborn_matplotlib"
DEFAULT_STYLE_PROFILE = "stem_conference"
_GROUPED_BAR_HATCHES = ("", "///", "\\\\", "xx", "..", "++", "oo", "**")
_MAX_GROUPED_BAR_RAW_POINTS = 500


@dataclass(frozen=True)
class ExperimentFigureArtifact:
    figure_id: str
    title: str
    figure_type: str
    paths: dict[str, str] = field(default_factory=dict)
    status: str = "rendered"
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentFigureSuite:
    status: str
    figures: list[ExperimentFigureArtifact] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Discipline style profiles (STEM conference / Nature family / humanities)
# ---------------------------------------------------------------------------

# Owner-supplied soft scientific palettes (SCIPainter Nature-style) plus clinical/rh.
PALETTE_POOL: dict[str, list[str]] = {
    "core": ["#93cc82", "#6fb2e0", "#db6968", "#f3d78a", "#fcbc7e", "#b9c1d1"],
    "extended": [
        "#d4d66d",
        "#bdc328",
        "#93cc82",
        "#f3d78a",
        "#c9a1ca",
        "#b379b4",
        "#87d1d1",
        "#46c1be",
    ],
    "warm": [
        "#6fb2e0",
        "#e28485",
        "#f9b8b2",
        "#fba864",
        "#efc971",
        "#b889b9",
        "#ccd1dd",
    ],
    "tissue": [
        "#ea9c9d",
        "#fac7c2",
        "#f8984e",
        "#bfbb9b",
        "#46c1be",
        "#88c4e8",
        "#6fb2e0",
        "#b379b4",
    ],
    "lineage": [
        "#8b96ad",
        "#db6968",
        "#4d97cd",
        "#60bc55",
        "#f3d78a",
        "#fcbc7e",
        "#ea9c9d",
        "#b379b4",
    ],
    "pathway": [
        "#e99899",
        "#f3c966",
        "#93cc82",
        "#88c4e8",
        "#4d97cd",
        "#87d1d1",
        "#c9a1ca",
    ],
    "immune": [
        "#db6968",
        "#f9b8b2",
        "#fba864",
        "#87d1d1",
        "#dedbc3",
        "#d2b1d4",
        "#c5cbd8",
    ],
    "rh": [
        "#BC3C29",
        "#0072B5",
        "#E18727",
        "#20854E",
        "#7876B1",
        "#6F99AD",
        "#EE4C97",
        "#8B96AD",
    ],
}
SEQUENTIAL_CMAPS: tuple[str, ...] = ("YlGnBu", "YlGnBu_r")

STYLE_PROFILES: dict[str, dict[str, Any]] = {
    # Dense, colorblind-safe conference look (CCF-A / *ACL / NeurIPS family).
    "stem_conference": {
        "theme": dict(
            context="paper",
            style="whitegrid",
            font="DejaVu Sans",
            rc={
                "axes.titlesize": 12,
                "axes.labelsize": 10,
                "xtick.labelsize": 9,
                "ytick.labelsize": 9,
                "legend.fontsize": 9,
                "figure.dpi": 160,
                "savefig.dpi": 320,
                "axes.edgecolor": "#243447",
                "grid.color": "#e6ebf1",
                "grid.linewidth": 0.7,
            },
        ),
        "palette": PALETTE_POOL["rh"],
        "panel_label_fmt": "({})",
        "panel_label_case": "lower",
        "annotate_bars": True,
        "panel_size": (4.2, 3.4),
        "line_width": 2.0,
        "grid_axis": "y",
    },
    # Compact multi-panel journal look: thin ticks, no heavy grid, bold
    # lowercase panel letters, NPG-inspired palette.
    "nature_family": {
        "theme": dict(
            context="paper",
            style="ticks",
            font="DejaVu Sans",
            rc={
                "axes.titlesize": 10,
                "axes.labelsize": 8.5,
                "xtick.labelsize": 7.5,
                "ytick.labelsize": 7.5,
                "legend.fontsize": 7.5,
                "figure.dpi": 160,
                "savefig.dpi": 320,
                "axes.linewidth": 0.8,
                "axes.edgecolor": "#222222",
                "xtick.major.width": 0.8,
                "ytick.major.width": 0.8,
            },
        ),
        "palette": PALETTE_POOL["rh"],
        "panel_label_fmt": "{}",
        "panel_label_case": "lower",
        "annotate_bars": False,
        "panel_size": (3.5, 2.9),
        "line_width": 1.6,
        "grid_axis": None,
    },
    # Roomier serif look for social-science / humanities venues: muted
    # palette, larger type, coefficient/forest conventions.
    "social_humanities": {
        "theme": dict(
            context="notebook",
            style="whitegrid",
            rc={
                "font.family": "serif",
                "font.serif": ["DejaVu Serif"],
                "axes.titlesize": 13,
                "axes.labelsize": 11,
                "xtick.labelsize": 10,
                "ytick.labelsize": 10,
                "legend.fontsize": 10,
                "figure.dpi": 160,
                "savefig.dpi": 320,
                "grid.color": "#e3e0d8",
                "grid.linewidth": 0.8,
                "axes.edgecolor": "#3b3a36",
            },
        ),
        "palette": PALETTE_POOL["rh"],
        "panel_label_fmt": "({})",
        "panel_label_case": "upper",
        "annotate_bars": False,
        "panel_size": (4.8, 3.7),
        "line_width": 2.2,
        "grid_axis": "y",
    },
    # Bioinformatics / precision-oncology look (npj / Nature journals): dense
    # multi-panel with uppercase bold letters, clinical-diverging palette for
    # survival/expression figures, minimal grid.
    "biomed_omics": {
        "theme": dict(
            context="paper",
            style="ticks",
            font="DejaVu Sans",
            rc={
                "axes.titlesize": 10,
                "axes.labelsize": 9,
                "xtick.labelsize": 8,
                "ytick.labelsize": 8,
                "legend.fontsize": 8,
                "figure.dpi": 160,
                "savefig.dpi": 320,
                "axes.linewidth": 0.9,
                "axes.edgecolor": "#1a1a1a",
                "xtick.major.width": 0.9,
                "ytick.major.width": 0.9,
            },
        ),
        "palette": PALETTE_POOL["rh"],
        "panel_label_fmt": "{}",
        "panel_label_case": "upper",
        "annotate_bars": False,
        "panel_size": (3.6, 3.0),
        "line_width": 1.8,
        "grid_axis": None,
    },
}


def resolve_style_profile(name: str | None) -> tuple[str, dict[str, Any]]:
    """Return (resolved_name, profile). Unknown names fall back to the default."""
    key = str(name or "").strip().lower()
    if key in STYLE_PROFILES:
        return key, STYLE_PROFILES[key]
    return DEFAULT_STYLE_PROFILE, STYLE_PROFILES[DEFAULT_STYLE_PROFILE]


def _activate_profile(profile: dict[str, Any]) -> None:
    sns.set_theme(**profile["theme"])


def _profile_palette(
    profile: dict[str, Any],
    keys: Iterable[Any],
    panel: Mapping[str, Any] | None = None,
) -> dict[Any, str]:
    """Map series keys to colours.

    Panels restart at the head of the palette, so an entity that appears in
    several panels only keeps its colour when the series order happens to
    match. A panel may pin colours explicitly with ``series_colors`` to keep a
    recurring entity the same hue across a composed figure.
    """
    unique = list(dict.fromkeys(keys))
    pinned: dict[Any, str] = {}
    if isinstance(panel, Mapping):
        declared = panel.get("series_colors")
        if isinstance(declared, Mapping):
            pinned = {key: str(value) for key, value in declared.items()}
    spec = profile.get("palette", "colorblind")
    if isinstance(spec, (list, tuple)):
        base = [str(c) for c in spec]
        if len(base) < max(len(unique), 1):
            base = base * (len(unique) // len(base) + 1)
    else:
        base = sns.color_palette(str(spec), n_colors=max(len(unique), 3)).as_hex()
    resolved: dict[Any, str] = {}
    cursor = 0
    for key in unique:
        if key in pinned:
            resolved[key] = pinned[key]
            continue
        resolved[key] = base[cursor % len(base)]
        cursor += 1
    return resolved


# ---------------------------------------------------------------------------
# Legacy fixed suite (kept for callers that pass typed records only)
# ---------------------------------------------------------------------------


def render_experiment_figure_suite(
    *,
    records: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
    suite_id: str = "experiment",
    formats: Sequence[str] = DEFAULT_FORMATS,
    claim_boundary: str = "observed_or_reported_results",
    style: str = "publication",
) -> ExperimentFigureSuite:
    """Render a reusable suite of experiment analysis figures.

    The input intentionally uses plain records so paper-production runs can feed
    observed logs or reported baselines without a topic-specific plotting script.
    """

    cleaned = [
        _clean_record(record) for record in records if isinstance(record, Mapping)
    ]
    if not cleaned:
        return ExperimentFigureSuite(
            status="empty",
            provenance={
                "backend": BACKEND_NAME,
                "claim_boundary": claim_boundary,
                "limitations": ["no_experiment_records"],
            },
        )

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    requested_formats = tuple(_normalize_formats(formats))
    _apply_publication_style(style)

    df = pd.DataFrame(cleaned)
    figures: list[ExperimentFigureArtifact] = []
    renderers = (
        _render_benchmark_grouped_bar,
        _render_ablation_heatmap,
        _render_metric_radar,
        _render_pareto_scatter,
        _render_sensitivity_line,
    )
    for renderer in renderers:
        artifact = renderer(
            df=df,
            output_dir=root,
            suite_id=_slug(suite_id),
            formats=requested_formats,
            claim_boundary=claim_boundary,
        )
        if artifact is not None:
            figures.append(artifact)

    status = "rendered" if figures else "empty"
    limitations = [] if figures else ["no_supported_figure_records"]
    return ExperimentFigureSuite(
        status=status,
        figures=figures,
        provenance={
            "backend": BACKEND_NAME,
            "style": style,
            "claim_boundary": claim_boundary,
            "record_count": len(cleaned),
            "figure_count": len(figures),
            "figure_types": [figure.figure_type for figure in figures],
            "limitations": limitations,
        },
    )


def _clean_record(record: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = {str(key): value for key, value in record.items()}
    figure_type = str(cleaned.get("figure_type") or cleaned.get("kind") or "").strip()
    cleaned["figure_type"] = figure_type.lower()
    for key in (
        "value",
        "x",
        "y",
        "lo",
        "hi",
        "std",
        "time",
        "log2fc",
        "neg_log10_p",
    ):
        if key in cleaned:
            cleaned[key] = _coerce_float(cleaned[key])
    # "setting" (sensitivity_line's x-axis) is legitimately either numeric
    # (a hyperparameter sweep, e.g. guidance scale 0.4/0.8/1.2) or categorical
    # (a named condition, e.g. a missingness pattern like "MRI-only"). Only
    # coerce when it actually parses as a number; otherwise keep the label so
    # _draw_sensitivity's categorical x-axis isn't silently NaN'd out.
    if "setting" in cleaned:
        coerced = _coerce_float(cleaned["setting"])
        if coerced is not None:
            cleaned["setting"] = coerced
    cleaned["higher_is_better"] = bool(cleaned.get("higher_is_better", True))
    return cleaned


def _render_benchmark_grouped_bar(
    *,
    df: pd.DataFrame,
    output_dir: Path,
    suite_id: str,
    formats: Sequence[str],
    claim_boundary: str,
) -> ExperimentFigureArtifact | None:
    data = df[df["figure_type"].eq("benchmark")].dropna(subset=["value"])
    required = {"dataset", "method", "metric", "value"}
    if data.empty or not required.issubset(data.columns):
        return None

    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    meta = _draw_grouped_bar(ax, data, {}, STYLE_PROFILES[DEFAULT_STYLE_PROFILE])
    if meta is None:
        plt.close(fig)
        return None
    ax.set_title("Benchmark Performance Across Datasets")
    return _save_figure(
        fig=fig,
        output_dir=output_dir,
        figure_id=f"{suite_id}_benchmark_grouped_bar",
        title="Benchmark Performance Across Datasets",
        figure_type="grouped_bar",
        formats=formats,
        claim_boundary=claim_boundary,
        source_records=len(data),
    )


def _render_ablation_heatmap(
    *,
    df: pd.DataFrame,
    output_dir: Path,
    suite_id: str,
    formats: Sequence[str],
    claim_boundary: str,
) -> ExperimentFigureArtifact | None:
    data = df[df["figure_type"].eq("ablation")].dropna(subset=["value"])
    required = {"dataset", "variant", "value"}
    if data.empty or not required.issubset(data.columns):
        return None

    fig, ax = plt.subplots(figsize=(7.4, 4.8))
    meta = _draw_heatmap(ax, data, {}, STYLE_PROFILES[DEFAULT_STYLE_PROFILE])
    if meta is None:
        plt.close(fig)
        return None
    ax.set_title("Ablation Sensitivity Matrix")
    return _save_figure(
        fig=fig,
        output_dir=output_dir,
        figure_id=f"{suite_id}_ablation_heatmap",
        title="Ablation Sensitivity Matrix",
        figure_type="heatmap",
        formats=formats,
        claim_boundary=claim_boundary,
        source_records=len(data),
    )


def _render_metric_radar(
    *,
    df: pd.DataFrame,
    output_dir: Path,
    suite_id: str,
    formats: Sequence[str],
    claim_boundary: str,
) -> ExperimentFigureArtifact | None:
    data = df[df["figure_type"].eq("radar")].dropna(subset=["value"])
    required = {"method", "metric", "value"}
    if data.empty or not required.issubset(data.columns):
        return None

    fig, ax = plt.subplots(figsize=(6.4, 6.0), subplot_kw={"polar": True})
    meta = _draw_radar(ax, data, {}, STYLE_PROFILES[DEFAULT_STYLE_PROFILE])
    if meta is None:
        plt.close(fig)
        return None
    ax.set_title("Normalized Capability Profile", pad=20)
    return _save_figure(
        fig=fig,
        output_dir=output_dir,
        figure_id=f"{suite_id}_metric_radar",
        title="Normalized Capability Profile",
        figure_type="radar",
        formats=formats,
        claim_boundary=claim_boundary,
        source_records=len(data),
    )


def _render_pareto_scatter(
    *,
    df: pd.DataFrame,
    output_dir: Path,
    suite_id: str,
    formats: Sequence[str],
    claim_boundary: str,
) -> ExperimentFigureArtifact | None:
    data = df[df["figure_type"].eq("pareto")].dropna(subset=["x", "y"])
    required = {"method", "x", "y"}
    if data.empty or not required.issubset(data.columns):
        return None

    fig, ax = plt.subplots(figsize=(6.8, 4.8))
    meta = _draw_pareto(ax, data, {}, STYLE_PROFILES[DEFAULT_STYLE_PROFILE])
    if meta is None:
        plt.close(fig)
        return None
    ax.set_title("Quality-Efficiency Pareto View")
    return _save_figure(
        fig=fig,
        output_dir=output_dir,
        figure_id=f"{suite_id}_pareto_scatter",
        title="Quality-Efficiency Pareto View",
        figure_type="pareto_scatter",
        formats=formats,
        claim_boundary=claim_boundary,
        source_records=len(data),
    )


def _render_sensitivity_line(
    *,
    df: pd.DataFrame,
    output_dir: Path,
    suite_id: str,
    formats: Sequence[str],
    claim_boundary: str,
) -> ExperimentFigureArtifact | None:
    data = df[df["figure_type"].eq("sensitivity")].dropna(subset=["setting", "value"])
    required = {"setting", "value", "metric"}
    if data.empty or not required.issubset(data.columns):
        return None

    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    meta = _draw_sensitivity(ax, data, {}, STYLE_PROFILES[DEFAULT_STYLE_PROFILE])
    if meta is None:
        plt.close(fig)
        return None
    ax.set_title("Parameter Sensitivity")
    return _save_figure(
        fig=fig,
        output_dir=output_dir,
        figure_id=f"{suite_id}_sensitivity_line",
        title="Parameter Sensitivity",
        figure_type="sensitivity_line",
        formats=formats,
        claim_boundary=claim_boundary,
        source_records=len(data),
    )


# ---------------------------------------------------------------------------
# Panel drawers (ax-level; shared by the legacy suite and the spec path)
# ---------------------------------------------------------------------------


def _col(panel: Mapping[str, Any], key: str, default: str) -> str:
    return str(panel.get(key) or default)


def _as_number_list(value: Any) -> list[float]:
    """Accept a scalar or a sequence of numbers; drop anything uncoercible."""
    if value is None or isinstance(value, bool):
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    out: list[float] = []
    for item in items:
        number = _coerce_float(item)
        if number is not None:
            out.append(float(number))
    return out


def _panel_reference_marks(ax: plt.Axes, panel: Mapping[str, Any]) -> None:
    """Reference lines, shaded spans and explicit limits, shared by every chart.

    A coefficient panel without a zero line, or an event study without the event
    marked, reads as an unlabelled squiggle; every drawer routes through here so
    the spec can ask for those marks once rather than per chart kind.
    """
    for y in _as_number_list(panel.get("hline")):
        ax.axhline(y, color="#8A8A8A", linewidth=0.9, linestyle=(0, (4, 3)), zorder=0.6)
    for x in _as_number_list(panel.get("vline")):
        ax.axvline(x, color="#8B1A10", linewidth=1.0, linestyle=(0, (4, 3)), zorder=0.6)
    span = panel.get("span")
    if isinstance(span, (list, tuple)) and len(span) == 2:
        bounds = _as_number_list(list(span))
        if len(bounds) == 2:
            ax.axvspan(
                min(bounds),
                max(bounds),
                color="#000000",
                alpha=0.045,
                linewidth=0,
                zorder=0.4,
            )
            # A shaded band with no name asks the reader to find the answer in
            # the caption. Name it on the band.
            span_label = str(panel.get("span_label", "") or "").strip()
            if span_label:
                ax.text(
                    (min(bounds) + max(bounds)) / 2.0,
                    0.985,
                    span_label,
                    transform=ax.get_xaxis_transform(),
                    ha="center",
                    va="top",
                    fontsize=plt.rcParams["xtick.labelsize"],
                    color="#5A6572",
                    zorder=0.5,
                )
    xlim = _as_number_list(panel.get("xlim"))
    if len(xlim) == 2:
        ax.set_xlim(min(xlim), max(xlim))
    ylim = _as_number_list(panel.get("ylim"))
    if len(ylim) == 2:
        ax.set_ylim(min(ylim), max(ylim))
    _panel_annotations(ax, panel)


def _panel_annotations(ax: plt.Axes, panel: Mapping[str, Any]) -> None:
    """Callouts placed on a panel: what the reader should see, said on the chart.

    A headline panel whose point lives in the caption makes the reader read the
    caption to know what they are looking at. Each entry gives ``text`` and a
    position; ``coords`` picks data units (default) or fractions of the axes,
    and an optional ``to`` point draws a leader arrow from the text to it.
    """
    for note in panel.get("annotations") or []:
        if not isinstance(note, Mapping):
            continue
        text = str(note.get("text", "") or "").strip()
        at = _as_number_list([note.get("x"), note.get("y")])
        if not text or len(at) != 2:
            continue
        transform = (
            ax.transAxes if str(note.get("coords", "data")) == "axes" else ax.transData
        )
        color = str(note.get("color", "#243447") or "#243447")
        common = dict(
            color=color,
            ha=str(note.get("ha", "left")),
            va=str(note.get("va", "bottom")),
            fontsize=_coerce_float(note.get("fontsize"))
            or plt.rcParams["xtick.labelsize"],
            zorder=6,
        )
        target = _as_number_list(note.get("to"))
        if len(target) == 2:
            ax.annotate(
                text,
                xy=(target[0], target[1]),
                xytext=(at[0], at[1]),
                xycoords=transform,
                textcoords=transform,
                arrowprops=dict(
                    arrowstyle="-", color=color, linewidth=0.8, shrinkA=2, shrinkB=2
                ),
                **common,
            )
        else:
            ax.text(at[0], at[1], text, transform=transform, **common)


def _panel_labels(ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any]) -> None:
    xl = str(panel.get("x_label", "") or "").strip()
    yl = str(panel.get("y_label", "") or "").strip()
    if xl:
        ax.set_xlabel(xl)
    if yl:
        ax.set_ylabel(yl)
    title = str(panel.get("title", "") or "").strip()
    if title:
        ax.set_title(_wrap_title(ax, title))
    _panel_reference_marks(ax, panel)


def _wrap_title(ax: plt.Axes, title: str) -> str:
    """Wrap a panel title to the width of its own panel.

    Matplotlib centres a title and lets it overhang; in a multi-panel grid the
    overhang lands on the neighbour's panel letter (rendered live, 2026-09-08).
    Estimate the characters the panel can hold from its width in points and the
    title font size, and wrap rather than overhang.
    """
    fig = ax.get_figure()
    if fig is None:
        return title
    width_pt = ax.get_window_extent().width / fig.dpi * 72.0
    if width_pt <= 0:
        return title
    # ~0.52 em per character averaged over mixed-case sans text, and the panel
    # letter carried inside a left-aligned title costs about four characters.
    per_char = max(plt.rcParams["axes.titlesize"] * 0.52, 1.0)
    budget = int(width_pt / per_char) - 4
    if budget < 8 or len(title) <= budget:
        return title
    return "\n".join(textwrap.wrap(title, budget)) or title


def _error_extent(group: pd.DataFrame) -> float | None:
    """Symmetric error for one bar/point: explicit ``std``, half of a
    declared ``lo``/``hi`` interval, or the sample std of repeated ``value``
    rows (multi-seed). Returns None when a single deterministic value."""
    if "std" in group.columns:
        std = _coerce_float(group["std"].iloc[0])
        if std is not None and std >= 0:
            return std
    if {"lo", "hi"}.issubset(group.columns):
        lo = _coerce_float(group["lo"].iloc[0])
        hi = _coerce_float(group["hi"].iloc[0])
        if lo is not None and hi is not None and hi >= lo:
            return (hi - lo) / 2.0
    values = group["value"].astype(float)
    if len(values) > 1:
        std = float(values.std(ddof=1))
        return std if std > 0 else None
    return None


def _has_variance(data: pd.DataFrame, group_cols: list[str]) -> bool:
    if "std" in data.columns or {"lo", "hi"}.issubset(data.columns):
        return True
    if not group_cols:
        return False
    return bool((data.groupby(group_cols, sort=False).size() > 1).any())


def _draw_grouped_bar(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    required = {"dataset", "method", "metric", "value"}
    data = data.dropna(subset=["value"]) if "value" in data.columns else data
    if data.empty or not required.issubset(data.columns):
        return None
    # Grouping is data-shaped, not hardcoded: the panel may name the axis and
    # series columns, and a single-dataset frame carrying several metrics must
    # group by metric — averaging distinct metrics into one bar per method
    # (the old fixed dataset x method grouping) silently fabricates a number
    # that appears nowhere in the records.
    group_col = _col(panel, "x_col", "")
    series_col = _col(panel, "hue_col", "")
    if not group_col or group_col not in data.columns:
        group_col = "dataset"
        # ponytail: a grade/stratum column carries the comparison the records were
        # built for; grouping by dataset collapses it into one bar. ISSUE-figure-package-not-wired-2026-09-30.
        facet = next(
            (
                c
                for c in ("grade", "level", "condition")
                if c in data.columns and data[c].nunique() > 1
            ),
            "",
        )
        if facet:
            group_col = facet
        elif (
            data["dataset"].nunique(dropna=False) <= 1 and data["metric"].nunique() > 1
        ):
            group_col = "metric"
    if not series_col or series_col not in data.columns:
        series_col = "method"
    y_label = (
        str(data["metric"].iloc[0])
        if group_col != "metric"
        else _col(panel, "y_label", "value")
    )
    metric = y_label
    palette = _profile_palette(profile, data[series_col], panel)
    datasets = list(dict.fromkeys(data[group_col]))
    methods = list(dict.fromkeys(data[series_col]))
    show_err = _has_variance(data, [group_col, series_col])

    n_methods = max(len(methods), 1)
    width = 0.8 / n_methods
    x_base = np.arange(len(datasets))
    err_recorded = False
    raw_points = 0
    # Hatches keep the series apart in grayscale print; the policy decides.
    # The legend sits above the axes (below) so hatch strokes do not cross it.
    print_safe_hatches = bool(profile.get("print_safe_hatches"))
    cells_by_method = tuple(
        tuple(
            data[(data[group_col] == dataset) & (data[series_col] == method)]
            for dataset in datasets
        )
        for method in methods
    )
    cell_sizes = [
        len(cell)
        for method_cells in cells_by_method
        for cell in method_cells
        if not cell.empty
    ]
    min_cell_n = min(cell_sizes) if cell_sizes else 0
    # Mean-only bars at n<10 hide the distribution; overlay when replicates exist.
    reveal_raw_points = bool(profile.get("reveal_raw_points")) or (1 < min_cell_n < 10)
    raw_samples, raw_points_available = _sample_raw_replicates(
        cells_by_method,
        limit=_MAX_GROUPED_BAR_RAW_POINTS if reveal_raw_points else 0,
    )
    for m_index, method in enumerate(methods):
        heights, errs = [], []
        method_cells = cells_by_method[m_index]
        for cell in method_cells:
            if cell.empty:
                heights.append(np.nan)
                errs.append(0.0)
                continue
            heights.append(float(cell["value"].astype(float).mean()))
            extent = _error_extent(cell) if show_err else None
            errs.append(extent if extent is not None else 0.0)
        offset = (m_index - (n_methods - 1) / 2.0) * width
        hatch = (
            _GROUPED_BAR_HATCHES[m_index % len(_GROUPED_BAR_HATCHES)]
            if print_safe_hatches
            else None
        )
        ax.bar(
            x_base + offset,
            heights,
            width=width * 0.92,
            label=str(method),
            color=palette[method],
            yerr=errs if show_err and any(errs) else None,
            capsize=2.5 if show_err else 0,
            error_kw={"elinewidth": 0.9, "alpha": 0.8},
            hatch=hatch,
            edgecolor="#242424" if print_safe_hatches else None,
            linewidth=0.7 if print_safe_hatches else None,
        )
        if reveal_raw_points:
            raw_points += _overlay_raw_replicates(
                ax,
                values_by_cell=raw_samples[m_index],
                center_offset=offset,
                bar_width=width,
            )
        err_recorded = err_recorded or (show_err and any(errs))
    ax.set_xticks(x_base)
    ax.set_xticklabels([str(d) for d in datasets])
    ax.set_xlabel("")
    ax.set_ylabel(metric)
    # Below the axes. Above it, adjacent panels' legends land on each other's
    # panel letter. ISSUE-figure-package-not-wired-2026-09-30.
    if n_methods > 1:
        # Above the axes. Below them the hatch strokes of the bars cross the
        # legend text and fail the Nature collision audit.
        # ISSUE-figure-package-not-wired-2026-09-30.
        ax.legend(
            title="",
            ncol=min(3, n_methods),
            frameon=False,
            loc="lower center",
            bbox_to_anchor=(0.5, 1.02),
            handlelength=1.4,
            columnspacing=1.2,
            borderaxespad=0.0,
        )
    # ponytail: value labels collide once a group holds more than two bars.
    if (
        profile.get("annotate_bars")
        and not err_recorded
        and data[series_col].nunique() <= 2
    ):
        _annotate_bar_values(ax)
    _despine_grid(ax, profile)
    _panel_labels(ax, data, panel)
    metadata: dict[str, Any] = {"records": len(data), "error_bars": err_recorded}
    if profile.get("result_plot_policy"):
        if not reveal_raw_points:
            replicate_visibility = "not_requested"
        elif raw_points_available > raw_points:
            replicate_visibility = "overlaid_sampled"
        elif raw_points:
            replicate_visibility = "overlaid"
        else:
            replicate_visibility = "not_available"
        metadata.update(
            {
                "raw_points": raw_points,
                "raw_points_available": raw_points_available,
                "replicate_visibility": replicate_visibility,
                "uncertainty": _grouped_bar_uncertainty(data),
                "category_encoding": (
                    "color_and_hatch" if print_safe_hatches else "color"
                ),
            }
        )
    return metadata


def _raw_replicate_values(cell: pd.DataFrame) -> list[float]:
    """Return only values that can defensibly be treated as raw replicates."""
    if cell.empty or "value" not in cell.columns:
        return []
    replicate_fields = {
        "replicate_id",
        "replicate",
        "seed",
        "run_id",
        "sample_id",
        "subject_id",
    }
    identified = any(
        str(value).strip()
        for field in replicate_fields.intersection(cell.columns)
        for value in cell[field].dropna()
    )
    if len(cell) < 2 and not identified:
        return []
    values = pd.to_numeric(cell["value"], errors="coerce").dropna()
    return [float(value) for value in values]


def _sample_raw_replicates(
    cells_by_method: Sequence[Sequence[pd.DataFrame]], *, limit: int
) -> tuple[tuple[tuple[tuple[float, ...], ...], ...], int]:
    observations = tuple(
        (method_index, dataset_index, value)
        for method_index, cells in enumerate(cells_by_method)
        for dataset_index, cell in enumerate(cells)
        for value in _raw_replicate_values(cell)
    )
    available = len(observations)
    if limit <= 0:
        selected: tuple[tuple[int, int, float], ...] = ()
    elif available <= limit:
        selected = observations
    else:
        selected = tuple(
            observations[index * (available - 1) // (limit - 1)]
            for index in range(limit)
        )
    samples = tuple(
        tuple(
            tuple(
                value
                for observed_method, observed_dataset, value in selected
                if observed_method == method_index and observed_dataset == dataset_index
            )
            for dataset_index in range(len(cells))
        )
        for method_index, cells in enumerate(cells_by_method)
    )
    return samples, available


def _overlay_raw_replicates(
    ax: plt.Axes,
    *,
    values_by_cell: Sequence[Sequence[float]],
    center_offset: float,
    bar_width: float,
) -> int:
    plotted = 0
    for dataset_index, values in enumerate(values_by_cell):
        if not values:
            continue
        jitter = (
            np.linspace(-bar_width * 0.2, bar_width * 0.2, len(values))
            if len(values) > 1
            else np.zeros(1)
        )
        ax.scatter(
            dataset_index + center_offset + jitter,
            values,
            s=14,
            marker="o",
            facecolors="white",
            edgecolors="#242424",
            linewidths=0.6,
            zorder=4,
        )
        plotted += len(values)
    return plotted


def _grouped_bar_uncertainty(data: pd.DataFrame) -> str:
    if "std" in data.columns and data["std"].map(_coerce_float).notna().any():
        return "recorded_standard_deviation"
    if {"lo", "hi"}.issubset(data.columns):
        bounds = data[["lo", "hi"]].apply(lambda column: column.map(_coerce_float))
        valid_bounds = bounds.notna().all(axis=1) & bounds["hi"].ge(bounds["lo"])
        if valid_bounds.any():
            return "recorded_interval"
    if (data.groupby(["dataset", "method"], sort=False).size() > 1).any():
        return "sample_standard_deviation"
    return "none"


def _draw_heatmap(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    row_col = _col(panel, "row_col", "variant")
    col_col = _col(panel, "col_col", "dataset")
    data = data.dropna(subset=["value"]) if "value" in data.columns else data
    if data.empty or not {row_col, col_col, "value"}.issubset(data.columns):
        return None
    matrix = data.pivot_table(
        index=row_col, columns=col_col, values="value", aggfunc="mean"
    )
    metric = _first_nonempty(data, "metric", "score")
    sns.heatmap(
        matrix,
        cmap="YlGnBu_r",
        linewidths=0.8,
        linecolor="white",
        annot=True,
        fmt=".2f",
        cbar_kws={"label": metric},
        ax=ax,
    )
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.tick_params(axis="x", rotation=0)
    ax.tick_params(axis="y", rotation=0)
    _panel_labels(ax, data, panel)
    return {"records": len(data)}


def _draw_radar(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    required = {"method", "metric", "value"}
    data = data.dropna(subset=["value"]) if "value" in data.columns else data
    if data.empty or not required.issubset(data.columns):
        return None
    if "higher_is_better" not in data.columns:
        data = data.assign(higher_is_better=True)
    normalized = _normalize_metric_values(data)
    metrics = list(normalized["metric"].drop_duplicates())
    if len(metrics) < 3:
        return None
    angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False).tolist()
    angles += angles[:1]
    palette = _profile_palette(profile, normalized["method"], panel)
    for method, group in normalized.groupby("method", sort=False):
        values_by_metric = {
            str(row.metric): float(row.normalized_value)
            for row in group.itertuples(index=False)
        }
        values = [values_by_metric.get(metric, 0.0) for metric in metrics]
        values += values[:1]
        ax.plot(
            angles,
            values,
            linewidth=profile.get("line_width", 2.0),
            label=str(method),
            color=palette[method],
        )
        ax.fill(angles, values, alpha=0.08, color=palette[method])
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(metrics)
    ax.set_ylim(0, 1)
    ax.set_yticklabels([])
    ax.grid(color="#d7dde5", linewidth=0.7)
    ax.legend(loc="upper right", bbox_to_anchor=(1.22, 1.12), frameon=False)
    title = str(panel.get("title", "") or "").strip()
    if title:
        ax.set_title(title, pad=18)
    return {"records": len(data)}


def _draw_pareto(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    required = {"method", "x", "y"}
    data = data.dropna(subset=["x", "y"]) if {"x", "y"}.issubset(data.columns) else data
    if data.empty or not required.issubset(data.columns):
        return None
    sns.scatterplot(
        data=data,
        x="x",
        y="y",
        hue="method",
        palette=_profile_palette(profile, data["method"], panel),
        s=110,
        edgecolor="white",
        linewidth=1.1,
        ax=ax,
    )
    for row in data.itertuples(index=False):
        ax.annotate(
            str(row.method),
            (float(row.x), float(row.y)),
            xytext=(6, 5),
            textcoords="offset points",
            fontsize=9,
        )
    ax.set_xlabel(_first_nonempty(data, "x_label", "Cost / latency"))
    ax.set_ylabel(_first_nonempty(data, "y_label", "Quality"))
    legend = ax.get_legend()
    if legend is not None:
        legend.remove()
    _despine_grid(ax, profile)
    _panel_labels(ax, data, panel)
    return {"records": len(data)}


def _draw_sensitivity(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    required = {"setting", "value", "metric"}
    data = (
        data.dropna(subset=["setting", "value"])
        if {"setting", "value"}.issubset(data.columns)
        else data
    )
    if data.empty or not required.issubset(data.columns):
        return None
    hue = (
        "method" if "method" in data.columns and data["method"].nunique() > 1 else None
    )
    sns.lineplot(
        data=data,
        x="setting",
        y="value",
        hue=hue,
        marker="o",
        linewidth=profile.get("line_width", 2.0),
        markersize=7,
        color=None if hue else "#1f77b4",
        palette=_profile_palette(profile, data["method"], panel) if hue else None,
        ax=ax,
    )
    ax.set_xlabel(_first_nonempty(data, "parameter", "Setting"))
    ax.set_ylabel(_first_nonempty(data, "metric", "Metric"))
    if hue:
        ax.legend(title="", frameon=False)
    _despine_grid(ax, profile)
    _panel_labels(ax, data, panel)
    return {"records": len(data)}


def _draw_line(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    x_col = _col(panel, "x_col", "x")
    y_col = _col(panel, "y_col", "y")
    series_col = _col(panel, "series_col", "series")
    if series_col not in data.columns and "method" in data.columns:
        series_col = "method"
    if not {x_col, y_col}.issubset(data.columns):
        return None
    data = data.dropna(subset=[y_col])
    if data.empty:
        return None
    # Categorical x (e.g. ANOVA interaction plots) keeps string order; numeric x
    # (convergence/training curves) sorts ascending.
    numeric_x = pd.to_numeric(data[x_col], errors="coerce").notna().all()
    if numeric_x:
        data = data.assign(**{x_col: pd.to_numeric(data[x_col])}).sort_values(x_col)
        x_ticks = None
    else:
        order = list(dict.fromkeys(data[x_col].astype(str)))
        pos = {v: i for i, v in enumerate(order)}
        data = data.assign(_xpos=data[x_col].astype(str).map(pos))
        x_ticks = (list(range(len(order))), order)
    series = (
        list(dict.fromkeys(data[series_col]))
        if series_col in data.columns and data[series_col].nunique() > 1
        else [None]
    )
    band = bool(panel.get("band", True)) and {"lo", "hi"}.issubset(data.columns)
    palette = _profile_palette(
        profile, [s for s in series if s is not None] or ["_line"], panel
    )
    marker_cycle = ("o", "s", "^", "D")
    declared_markers = (
        panel.get("series_markers")
        if isinstance(panel.get("series_markers"), Mapping)
        else {}
    )
    declared_linestyles = (
        panel.get("series_linestyles")
        if isinstance(panel.get("series_linestyles"), Mapping)
        else {}
    )
    banded = False
    for i, s in enumerate(series):
        grp = data if s is None else data[data[series_col] == s]
        xv = grp[x_col].to_numpy() if numeric_x else grp["_xpos"].to_numpy()
        color = palette["_line"] if s is None else palette[s]
        key = str(s) if s is not None else "_line"
        marker = declared_markers.get(key) or (
            marker_cycle[i % len(marker_cycle)] if s is not None else "o"
        )
        linestyle = declared_linestyles.get(key) or "-"
        n = len(xv)
        markevery = max(1, n // 40) if n > 48 else 1
        ax.plot(
            xv,
            grp[y_col].astype(float),
            marker=marker,
            linestyle=linestyle,
            linewidth=profile.get("line_width", 2.0),
            markersize=5,
            markevery=markevery,
            color=color,
            label=None if s is None else str(s),
        )
        if band:
            ax.fill_between(
                xv,
                grp["lo"].astype(float),
                grp["hi"].astype(float),
                color=color,
                alpha=0.15,
                linewidth=0,
            )
            banded = True
    if x_ticks is not None:
        ax.set_xticks(x_ticks[0])
        ax.set_xticklabels(x_ticks[1])
    if series != [None]:
        ax.legend(title="", frameon=False)
    _despine_grid(ax, profile)
    _panel_labels(ax, data, panel)
    return {"records": len(data), "confidence_band": banded}


def _draw_scatter(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    x_col = _col(panel, "x_col", "x")
    y_col = _col(panel, "y_col", "y")
    series_col = _col(panel, "series_col", "series")
    if series_col not in data.columns and "method" in data.columns:
        series_col = "method"
    if not {x_col, y_col}.issubset(data.columns):
        return None
    data = data.dropna(subset=[x_col, y_col])
    if data.empty:
        return None
    hue = series_col if series_col in data.columns else None
    sns.scatterplot(
        data=data,
        x=x_col,
        y=y_col,
        hue=hue,
        palette=_profile_palette(profile, data[hue], panel) if hue else None,
        s=70,
        edgecolor="white",
        linewidth=0.8,
        ax=ax,
    )
    # Few enough points to label in place reads better than any legend, and a
    # default-placed legend lands on top of the data (matplotlib's "best" only
    # avoids collisions it can see).
    annotate = bool(panel.get("annotate")) and hue and len(data) <= 8
    if annotate:
        for _, row in data.iterrows():
            ax.annotate(
                str(row[hue]),
                (float(row[x_col]), float(row[y_col])),
                textcoords="offset points",
                xytext=(7, 4),
                fontsize=plt.rcParams["font.size"] * 0.85,
            )
        legend = ax.get_legend()
        if legend is not None:
            legend.remove()
        ax.margins(x=0.22, y=0.12)
    elif hue:
        ax.legend(
            title="",
            frameon=False,
            ncol=min(3, data[hue].nunique()),
            loc="lower center",
            bbox_to_anchor=(0.5, 1.02),
            borderaxespad=0.0,
        )
    _despine_grid(ax, profile)
    _panel_labels(ax, data, panel)
    return {"records": len(data)}


def _draw_box(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    return _draw_distribution(ax, data, panel, profile, kind="box")


def _draw_violin(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    return _draw_distribution(ax, data, panel, profile, kind="violin")


def _draw_distribution(
    ax: plt.Axes,
    data: pd.DataFrame,
    panel: Mapping[str, Any],
    profile: dict[str, Any],
    *,
    kind: str,
) -> dict[str, Any] | None:
    group_col = _col(panel, "group_col", "group")
    value_col = _col(panel, "value_col", "value")
    if group_col not in data.columns and "method" in data.columns:
        group_col = "method"
    if not {group_col, value_col}.issubset(data.columns):
        return None
    data = data.dropna(subset=[value_col])
    if data.empty:
        return None
    plot_fn = sns.boxplot if kind == "box" else sns.violinplot
    plot_fn(
        data=data,
        x=group_col,
        y=value_col,
        hue=group_col,
        palette=_profile_palette(profile, data[group_col], panel),
        legend=False,
        saturation=1.0,  # keep the palette hue exactly as registered
        ax=ax,
    )
    ax.set_xlabel("")
    _despine_grid(ax, profile)
    _panel_labels(ax, data, panel)
    return {"records": len(data)}


def _draw_bar(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    # ponytail: a plan says "bar" while the records carry the comparison in a
    # grade column. Drawing by method collapses every grade into one bar.
    # ISSUE-figure-package-not-wired-2026-09-30.
    if (
        "grade" in data.columns
        and data["grade"].nunique() > 1
        and {"dataset", "method", "metric", "value"}.issubset(data.columns)
    ):
        return _draw_grouped_bar(ax, data, panel, profile)
    label_col = _col(panel, "label_col", "label")
    value_col = _col(panel, "value_col", "value")
    if label_col not in data.columns or data[label_col].isna().all():
        for candidate in ("method", "category", "dataset"):
            if candidate in data.columns and not data[candidate].isna().all():
                label_col = candidate
                break
    if not {label_col, value_col}.issubset(data.columns):
        return None
    data = data.dropna(subset=[value_col])
    if data.empty:
        return None
    # Journal convention: colour encodes something or nothing. A one-series
    # categorical bar chart gets ONE colour (plus an accent for a named
    # highlight); a rainbow of categories reads as decoration.
    highlight = str(panel.get("highlight", "") or "").strip()
    accent = _profile_palette(profile, ["_accent"], panel)["_accent"]
    # Baselines are named methods, not background: each gets its own hue from
    # the profile palette so a reader can track a baseline across panels. The
    # highlighted method keeps the accent hue and is the only fully saturated
    # bar; baselines are drawn at reduced alpha by the caller-facing style, so
    # the proposed method still reads first without greying the comparison out.
    palette = list(profile.get("palette") or [])
    if isinstance(palette, str) or not palette:
        palette = [accent]
    baseline_hues = [c for c in palette if c != accent] or palette
    colors, i = {}, 0
    for label in data[label_col]:
        key = str(label)
        if key in colors:
            continue
        if highlight and key == highlight:
            colors[key] = accent
        else:
            colors[key] = baseline_hues[i % len(baseline_hues)]
            i += 1
    # A production suite pins method identities before filtering each panel.
    # Keep those colors even when a panel reorders methods or highlights one.
    declared = panel.get("series_colors")
    if isinstance(declared, Mapping):
        colors = {key: str(declared.get(key, color)) for key, color in colors.items()}
    sns.barplot(
        data=data,
        x=label_col,
        y=value_col,
        hue=label_col,
        palette=colors,
        legend=False,
        errorbar=None,
        # seaborn desaturates categorical fills to 0.75 by default, which
        # silently repaints every PALETTE_POOL hue (#6fb2e0 -> #7DAFD2) and
        # puts the figure off the approved palette.
        saturation=1.0,
        ax=ax,
    )
    # Declared targets and measurements must not share an encoding. A hatched
    # bar reads as "asserted, not observed" even in greyscale, so a reader can
    # never mistake a design target for a measured baseline.
    target_col = _col(panel, "target_col", "is_target")
    if target_col in data.columns:
        flags = [bool(v) for v in data[target_col]]
        for patch, is_target in zip(ax.patches, flags):
            if is_target:
                patch.set_hatch("//")
                patch.set_edgecolor("#242424")
                patch.set_linewidth(0.8)
    _draw_value_errorbars(ax, data, label_col, value_col)
    group_sizes = data.groupby(label_col, sort=False).size()
    min_n = int(group_sizes.min()) if len(group_sizes) else 0
    if 1 < min_n < 10:
        labels = list(dict.fromkeys(data[label_col]))
        for index, label in enumerate(labels):
            values = (
                pd.to_numeric(
                    data.loc[data[label_col] == label, value_col], errors="coerce"
                )
                .dropna()
                .to_numpy()
            )
            if len(values) < 2:
                continue
            jitter = (
                np.linspace(-0.18, 0.18, len(values))
                if len(values) > 1
                else np.zeros(1)
            )
            ax.scatter(
                np.full(len(values), index) + jitter,
                values,
                s=14,
                marker="o",
                facecolors="white",
                edgecolors="#242424",
                linewidths=0.6,
                zorder=4,
            )
    ax.set_xlabel("")
    if profile.get("annotate_bars"):
        _annotate_bar_values(ax)
    _despine_grid(ax, profile)
    _panel_labels(ax, data, panel)
    return {"records": len(data)}


def _draw_value_errorbars(
    ax: plt.Axes, data: pd.DataFrame, label_col: str, value_col: str
) -> None:
    """Overlay dispersion whiskers when the records carry them.

    Records routinely ship std/sem or lo/hi columns that the bar drawer used
    to discard, producing point estimates with no visible uncertainty — the
    single most common reviewer complaint about generated result figures.
    """
    lo = hi = None
    if {"lo", "hi"}.issubset(data.columns):
        lo = pd.to_numeric(data["lo"], errors="coerce")
        hi = pd.to_numeric(data["hi"], errors="coerce")
    else:
        for col in ("std", "sd", "sem", "stderr", "ci"):
            if col in data.columns:
                spread = pd.to_numeric(data[col], errors="coerce")
                values = pd.to_numeric(data[value_col], errors="coerce")
                lo, hi = values - spread, values + spread
                break
    if lo is None or hi is None:
        return
    values = pd.to_numeric(data[value_col], errors="coerce")
    mask = lo.notna() & hi.notna() & values.notna()
    if not mask.any():
        return
    positions = np.arange(len(data))[mask.to_numpy()]
    yerr = np.vstack(
        [
            (values[mask] - lo[mask]).clip(lower=0).to_numpy(),
            (hi[mask] - values[mask]).clip(lower=0).to_numpy(),
        ]
    )
    ax.errorbar(
        positions,
        values[mask].to_numpy(),
        yerr=yerr,
        fmt="none",
        # ecolor drives the whisker; the caps follow `color`, which otherwise
        # takes the next hue off the cycle and paints them off-palette blue.
        color="#333333",
        ecolor="#333333",
        elinewidth=0.9,
        capsize=2.5,
        zorder=5,
    )


def _draw_forest(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    """Coefficient / effect-size plot with CI whiskers (social-science staple)."""
    label_col = _col(panel, "label_col", "label")
    value_col = _col(panel, "value_col", "value")
    lo_col = _col(panel, "lo_col", "lo")
    hi_col = _col(panel, "hi_col", "hi")
    if not {label_col, value_col}.issubset(data.columns):
        return None
    data = data.dropna(subset=[value_col])
    if data.empty:
        return None
    has_ci = {lo_col, hi_col}.issubset(data.columns)
    if bool(panel.get("sort", True)):
        data = data.sort_values(value_col)
    labels = [str(v) for v in data[label_col]]
    values = data[value_col].astype(float).to_numpy()
    positions = np.arange(len(labels))
    # A forest is a comparison chart, so the thing being compared belongs in the
    # ink. Colour rows by `group_col`, and leave a row's marker hollow when
    # `filled_col` is false -- the convention for an estimate that did not clear
    # the study's significance rule. Without these the distinction has to be
    # spelled out inside each row label, which is where it was going.
    group_col = _col(panel, "group_col", "group")
    # Colour by group whenever the column is there, including when this panel
    # holds only one of them: sibling panels of a composed figure each show one
    # arm, and they must not all come out in the palette's first colour.
    groups = (
        data[group_col].astype(str).to_numpy() if group_col in data.columns else None
    )
    if groups is None:
        colors = {"_forest": _profile_palette(profile, ["_forest"], panel)["_forest"]}
        row_keys = np.array(["_forest"] * len(labels))
    else:
        colors = _profile_palette(profile, groups, panel)
        row_keys = groups
    filled_col = _col(panel, "filled_col", "filled")
    if filled_col in data.columns:
        filled = [
            bool(v) and str(v).strip().lower() not in {"0", "false", "no", ""}
            for v in data[filled_col]
        ]
    else:
        filled = [True] * len(labels)
    lo = data[lo_col].astype(float).to_numpy() if has_ci else None
    hi = data[hi_col].astype(float).to_numpy() if has_ci else None
    seen: list[str] = []
    for i, key in enumerate(row_keys):
        color = colors[key]
        face = color if filled[i] else "white"
        label = None
        if groups is not None and key not in seen:
            seen.append(key)
            label = key
        if has_ci:
            ax.errorbar(
                values[i],
                positions[i],
                xerr=[[max(values[i] - lo[i], 0.0)], [max(hi[i] - values[i], 0.0)]],
                fmt="o",
                color=color,
                ecolor=color,
                elinewidth=1.6,
                capsize=3,
                markersize=6,
                markerfacecolor=face,
                markeredgecolor=color,
                markeredgewidth=1.4,
                label=label,
            )
        else:
            ax.plot(
                values[i],
                positions[i],
                "o",
                color=color,
                markersize=6,
                markerfacecolor=face,
                markeredgecolor=color,
                markeredgewidth=1.4,
                label=label,
            )
    # The artists carry their labels either way, so a figure-level legend can
    # still collect them; only draw one inside the panel when the panel itself
    # shows a comparison.
    if groups is not None and len(seen) > 1:
        ax.legend(loc=str(panel.get("legend_loc", "best")), frameon=False)
    # Scale to the estimates, not to zero. A C-index forest anchored at 0
    # crams every point into the right quarter of the panel and puts the
    # "no effect" line where no effect lives for that metric (rendered live,
    # 2026-08-16). The reference defaults to the metric's own null: 0 for
    # effect sizes/log-ratios, 0.5 for discrimination indices bounded in
    # [0, 1]. A panel may always name `ref` explicitly.
    lo_all = (
        min(float(lo.min()), float(values.min())) if has_ci else float(values.min())
    )
    hi_all = (
        max(float(hi.max()), float(values.max())) if has_ci else float(values.max())
    )
    explicit_ref = panel.get("ref")
    if explicit_ref is None:
        discrimination = lo_all >= 0.35 and hi_all <= 1.0
        ref = 0.5 if discrimination else 0.0
    else:
        ref = _coerce_float(explicit_ref)
    span = max(hi_all - lo_all, 1e-6)
    pad = span * 0.18
    left, right = lo_all - pad, hi_all + pad
    if ref is not None and left <= ref <= right:
        ax.axvline(ref, color="#8a8a8a", linewidth=1.0, linestyle="--")
    elif ref is not None and abs(ref - left) < span:
        left = min(left, ref - pad * 0.5)
        ax.axvline(ref, color="#8a8a8a", linewidth=1.0, linestyle="--")
    # Sibling forest panels of the same metric must share a range, or the eye
    # compares two different scales and reads a difference that is not there.
    x_min, x_max = _coerce_float(panel.get("x_min")), _coerce_float(panel.get("x_max"))
    if x_min is not None:
        left = x_min
    if x_max is not None:
        right = x_max
    ax.set_xlim(left, right)
    ax.set_yticks(positions)
    ax.set_yticklabels(labels)
    ax.grid(axis="x", alpha=0.6)
    ax.grid(axis="y", visible=False)
    sns.despine(ax=ax)
    _panel_labels(ax, data, panel)
    return {"records": len(data), "ci": has_ci}


def _draw_hist(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    """Distribution histogram (optional KDE, optional grouping)."""
    value_col = _col(panel, "value_col", "value")
    if value_col not in data.columns:
        for candidate in ("x", "y"):
            if candidate in data.columns:
                value_col = candidate
                break
    if value_col not in data.columns:
        return None
    data = data.dropna(subset=[value_col])
    if data.empty:
        return None
    group_col = _col(panel, "group_col", "group")
    hue = (
        group_col
        if group_col in data.columns and data[group_col].nunique() > 1
        else None
    )
    bins = int(_coerce_float(panel.get("bins")) or 0) or "auto"
    # Integer-valued data (years, counts) gets one bin per integer: "auto" split 25 AAER years
    # into 17 bins 1.41 wide, 7 of them holding two years each.
    values = pd.to_numeric(data[value_col], errors="coerce").astype(float).dropna()
    discrete = (
        bins == "auto"
        and not values.empty
        and bool((values % 1 == 0).all())
        and values.max() - values.min() < 200
    )
    sns.histplot(
        data=data,
        x=value_col,
        hue=hue,
        bins=bins,
        discrete=discrete or None,
        kde=bool(panel.get("kde", False)),
        palette=_profile_palette(profile, data[hue], panel) if hue else None,
        color=None if hue else _profile_palette(profile, ["_hist"], panel)["_hist"],
        edgecolor="white",
        linewidth=0.5,
        ax=ax,
    )
    legend = ax.get_legend()
    if legend is not None:
        legend.set_title(str(panel.get("legend_title", "") or ""))
    _despine_grid(ax, profile)
    _panel_labels(ax, data, panel)
    return {"records": len(data)}


def _draw_stacked_bar(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    """Composition bars: value stacked by segment within each category."""
    cat_col = _col(panel, "category_col", "category")
    seg_col = _col(panel, "segment_col", "segment")
    value_col = _col(panel, "value_col", "value")
    if not {cat_col, seg_col, value_col}.issubset(data.columns):
        return None
    data = data.dropna(subset=[value_col])
    if data.empty:
        return None
    matrix = data.pivot_table(
        index=cat_col, columns=seg_col, values=value_col, aggfunc="sum", fill_value=0.0
    )
    segments = list(matrix.columns)
    palette = _profile_palette(profile, segments, panel)
    bottoms = np.zeros(len(matrix))
    positions = np.arange(len(matrix))
    for seg in segments:
        heights = matrix[seg].to_numpy(dtype=float)
        ax.bar(positions, heights, bottom=bottoms, label=str(seg), color=palette[seg])
        bottoms += heights
    ax.set_xticks(positions)
    ax.set_xticklabels([str(v) for v in matrix.index])
    ax.legend(title="", frameon=False, ncol=min(3, len(segments)))
    _despine_grid(ax, profile)
    _panel_labels(ax, data, panel)
    return {"records": len(data), "segments": len(segments)}


def _draw_km_survival(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    """Kaplan-Meier step curves with censoring ticks (biomedical staple).

    Records carry ``time``, ``value`` (survival probability in [0,1]), optional
    ``group`` and ``censored`` (bool) columns. The estimate is supplied by the
    caller — the renderer only draws the step function, it does not compute KM.
    """
    time_col = _col(panel, "time_col", "time")
    surv_col = _col(panel, "value_col", "value")
    if not {time_col, surv_col}.issubset(data.columns):
        return None
    data = data.dropna(subset=[time_col, surv_col])
    if data.empty:
        return None
    group_col = _col(panel, "group_col", "group")
    groups = (
        list(dict.fromkeys(data[group_col])) if group_col in data.columns else [None]
    )
    palette = _profile_palette(
        profile, [g for g in groups if g is not None] or ["_km"], panel
    )
    for g in groups:
        grp = (data if g is None else data[data[group_col] == g]).sort_values(time_col)
        color = palette["_km"] if g is None else palette[g]
        ax.step(
            grp[time_col].astype(float),
            grp[surv_col].astype(float),
            where="post",
            color=color,
            linewidth=profile.get("line_width", 1.8),
            label=None if g is None else str(g),
        )
        if "censored" in grp.columns:
            cens = grp[grp["censored"].astype(bool)]
            if not cens.empty:
                ax.plot(
                    cens[time_col].astype(float),
                    cens[surv_col].astype(float),
                    "|",
                    color=color,
                    markersize=7,
                    markeredgewidth=1.2,
                )
    ax.set_ylim(0, 1.02)
    ax.set_xlabel(_first_nonempty(data, "x_label", "Time"))
    ax.set_ylabel(_first_nonempty(data, "y_label", "Survival probability"))
    if groups != [None]:
        ax.legend(title="", frameon=False)
    _despine_grid(ax, profile)
    title = str(panel.get("title", "") or "").strip()
    if title:
        ax.set_title(title)
    return {"records": len(data), "groups": len([g for g in groups if g is not None])}


def _draw_volcano(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    """Differential-expression volcano: log2 fold-change vs -log10 p, with
    significance thresholds coloring up/down/ns points."""
    x_col = _col(panel, "x_col", "log2fc")
    y_col = _col(panel, "y_col", "neg_log10_p")
    if not {x_col, y_col}.issubset(data.columns):
        return None
    data = data.dropna(subset=[x_col, y_col])
    if data.empty:
        return None
    fc_thr = _coerce_float(panel.get("fc_threshold", 1.0)) or 1.0
    p_thr = _coerce_float(panel.get("p_threshold", 1.301)) or 1.301  # -log10(0.05)
    xv = data[x_col].astype(float).to_numpy()
    yv = data[y_col].astype(float).to_numpy()
    up = (xv >= fc_thr) & (yv >= p_thr)
    down = (xv <= -fc_thr) & (yv >= p_thr)
    ns = ~(up | down)
    ax.scatter(
        xv[ns], yv[ns], s=14, color="#b8bcc4", alpha=0.6, linewidths=0, label="ns"
    )
    ax.scatter(
        xv[up], yv[up], s=18, color="#BC3C29", alpha=0.85, linewidths=0, label="up"
    )
    ax.scatter(
        xv[down],
        yv[down],
        s=18,
        color="#0072B5",
        alpha=0.85,
        linewidths=0,
        label="down",
    )
    ax.axvline(fc_thr, color="#8a8a8a", linewidth=0.8, linestyle="--")
    ax.axvline(-fc_thr, color="#8a8a8a", linewidth=0.8, linestyle="--")
    ax.axhline(p_thr, color="#8a8a8a", linewidth=0.8, linestyle="--")
    ax.set_xlabel(_first_nonempty(data, "x_label", "log$_2$ fold change"))
    ax.set_ylabel(_first_nonempty(data, "y_label", "-log$_{10}$ p"))
    ax.legend(title="", frameon=False, markerscale=1.3)
    _despine_grid(ax, profile)
    title = str(panel.get("title", "") or "").strip()
    if title:
        ax.set_title(title)
    return {"records": len(data), "up": int(up.sum()), "down": int(down.sum())}


def _draw_image(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    """Render an external asset image into a panel (composite figures, maps,
    micrographs). The asset must exist; a missing file skips the panel rather
    than fabricating content."""
    path = str(panel.get("asset_path", "") or "")
    if not path and "path" in data.columns and not data.empty:
        path = str(data["path"].iloc[0] or "")
    if not path or not Path(path).is_file():
        return None
    try:
        image = plt.imread(path)
    except Exception:
        return None
    ax.imshow(image)
    ax.axis("off")
    title = str(panel.get("title", "") or "").strip()
    if title:
        ax.set_title(title)
    return {"records": 1, "asset_path": path}


def _draw_qualitative_grid(
    ax: plt.Axes, data: pd.DataFrame, panel: Mapping[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    """Case-study image grid: records carry ``path`` (+ optional ``label``);
    missing assets are skipped and reported, never fabricated. Drawn inside the
    given ax by carving a sub-gridspec so it composes in multi-panel figures."""
    path_col = _col(panel, "path_col", "path")
    items: list[tuple[str, str]] = []
    # spec-level assets (list of {path,label}) take precedence over record rows
    spec_assets = panel.get("assets")
    if isinstance(spec_assets, (list, tuple)):
        for item in spec_assets:
            if isinstance(item, Mapping):
                p = str(item.get("path", "") or "")
                if p and Path(p).is_file():
                    items.append((p, str(item.get("label", "") or "")))
    elif path_col in data.columns:
        for row in data.itertuples(index=False):
            p = str(getattr(row, path_col, "") or "")
            if p and Path(p).is_file():
                label = (
                    str(getattr(row, "label", "") or "")
                    if "label" in data.columns
                    else ""
                )
                items.append((p, label))
    if not items:
        return None
    ncols = int(_coerce_float(panel.get("cols")) or 0) or min(3, len(items))
    nrows = math.ceil(len(items) / ncols)
    ax.axis("off")
    inner = ax.get_subplotspec().subgridspec(nrows, ncols, wspace=0.08, hspace=0.12)
    fig = ax.figure
    drawn = 0
    for idx, (path, label) in enumerate(items):
        try:
            image = plt.imread(path)
        except Exception:
            continue
        sub = fig.add_subplot(inner[idx])
        sub.imshow(image)
        sub.axis("off")
        if label:
            sub.set_title(label, fontsize=7)
        drawn += 1
    if drawn == 0:
        return None
    title = str(panel.get("title", "") or "").strip()
    if title:
        ax.set_title(title, fontsize=plt.rcParams["axes.titlesize"])
    return {"records": len(data), "cells": drawn, "skipped": len(data) - drawn}


# Chart-kind registry: kind -> (drawer, needs polar axes, default record
# figure_type filter). The plan prompt vocabulary in exemplar_impls must stay a
# subset of these kinds (guarded by a test).
PANEL_CHARTS: dict[str, tuple[Callable[..., dict[str, Any] | None], bool, str]] = {
    "grouped_bar": (_draw_grouped_bar, False, "benchmark"),
    "heatmap": (_draw_heatmap, False, "ablation"),
    "radar": (_draw_radar, True, "radar"),
    "pareto_scatter": (_draw_pareto, False, "pareto"),
    "sensitivity_line": (_draw_sensitivity, False, "sensitivity"),
    "line": (_draw_line, False, "line"),
    "scatter": (_draw_scatter, False, "scatter"),
    "box": (_draw_box, False, "box"),
    "violin": (_draw_violin, False, "violin"),
    "bar": (_draw_bar, False, "bar"),
    "forest": (_draw_forest, False, "forest"),
    "hist": (_draw_hist, False, "hist"),
    "stacked_bar": (_draw_stacked_bar, False, "composition"),
    "km_survival": (_draw_km_survival, False, "survival"),
    "volcano": (_draw_volcano, False, "volcano"),
    "image": (_draw_image, False, "asset"),
    "qualitative_grid": (_draw_qualitative_grid, False, "case"),
}

_CHART_ALIASES = {
    "bar_grouped": "grouped_bar",
    "benchmark_bar": "grouped_bar",
    "ablation_heatmap": "heatmap",
    "heat_map": "heatmap",
    "pareto": "pareto_scatter",
    "efficiency_scatter": "pareto_scatter",
    "sensitivity": "sensitivity_line",
    "convergence": "line",
    "line_chart": "line",
    "training_curve": "line",
    "boxplot": "box",
    "box_plot": "box",
    "violinplot": "violin",
    "violin_plot": "violin",
    "coefficient": "forest",
    "coefficient_plot": "forest",
    "forest_plot": "forest",
    "effect_size": "forest",
    "scatterplot": "scatter",
    "capability_radar": "radar",
    "histogram": "hist",
    "distribution": "hist",
    "stacked_bar_chart": "stacked_bar",
    "composition_bar": "stacked_bar",
    "kaplan_meier": "km_survival",
    "km_curve": "km_survival",
    "survival_curve": "km_survival",
    "volcano_plot": "volcano",
    "case_grid": "qualitative_grid",
    "image_grid": "qualitative_grid",
    "asset_image": "image",
    "panel_image": "image",
}


def canonical_chart_kind(kind: str) -> str | None:
    key = str(kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in PANEL_CHARTS:
        return key
    return _CHART_ALIASES.get(key)


# Per-chart record contract: required record columns, optional (nice-to-have)
# columns, and the natural logging granularity. Single source of truth consumed
# by the figure-suite planning layer (derive_logging_requirements / reconcile).
CHART_FIELD_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "grouped_bar": {
        "required": ["dataset", "method", "metric", "value"],
        "optional": [
            "std",
            "lo",
            "hi",
            "replicate_id",
            "replicate",
            "seed",
            "run_id",
            "sample_id",
            "subject_id",
        ],
        "granularity": "per-run (n>=3 for error bars)",
    },
    "heatmap": {
        "required": ["variant", "dataset", "value"],
        "optional": ["metric"],
        "granularity": "per-cell",
    },
    "radar": {
        "required": ["method", "metric", "value"],
        "optional": ["higher_is_better"],
        "granularity": "per-metric",
    },
    "pareto_scatter": {
        "required": ["method", "x", "y"],
        "optional": ["x_label", "y_label"],
        "granularity": "per-method",
    },
    "sensitivity_line": {
        "required": ["setting", "value", "metric"],
        "optional": ["method"],
        "granularity": "per-setting",
    },
    "line": {
        "required": ["x", "y"],
        "optional": ["series", "lo", "hi"],
        "granularity": "per-step (per-epoch for curves)",
    },
    "scatter": {
        "required": ["x", "y"],
        "optional": ["series"],
        "granularity": "per-instance",
    },
    "box": {
        "required": ["group", "value"],
        "optional": [],
        "granularity": "per-instance (distribution)",
    },
    "violin": {
        "required": ["group", "value"],
        "optional": [],
        "granularity": "per-instance (distribution)",
    },
    "bar": {
        "required": ["label", "value"],
        "optional": ["std"],
        "granularity": "per-label",
    },
    "forest": {
        "required": ["label", "value", "lo", "hi"],
        "optional": ["ref"],
        "granularity": "per-coefficient (point + CI)",
    },
    "hist": {
        "required": ["value"],
        "optional": ["group"],
        "granularity": "per-instance (distribution)",
    },
    "stacked_bar": {
        "required": ["category", "segment", "value"],
        "optional": [],
        "granularity": "per-segment",
    },
    "km_survival": {
        "required": ["time", "value"],
        "optional": ["group", "censored"],
        "granularity": "per-event-time (survival estimate + censoring)",
    },
    "volcano": {
        "required": ["log2fc", "neg_log10_p"],
        "optional": ["label"],
        "granularity": "per-feature",
    },
    "image": {
        "required": [],
        "optional": ["asset_path"],
        "granularity": "external asset",
    },
    "qualitative_grid": {
        "required": [],
        "optional": ["path", "assets"],
        "granularity": "external assets",
    },
}


def chart_field_requirements(kind: str) -> dict[str, Any]:
    """Record contract for a (canonicalized) chart kind; empty dict if unknown."""
    canon = canonical_chart_kind(kind)
    return dict(CHART_FIELD_REQUIREMENTS.get(canon or "", {}))


# ---------------------------------------------------------------------------
# Spec-driven suite rendering (the EAG figure_suite execution layer)
# ---------------------------------------------------------------------------


def _normalize_suite_spec(spec: Mapping[str, Any] | None) -> dict[str, Any]:
    """Accept the raw exemplar_plan payload or a bare suite dict."""
    if not isinstance(spec, Mapping):
        return {}
    inner = spec
    for wrapper in ("plan", "suite", "figure_suite"):
        nested = inner.get(wrapper)
        if isinstance(nested, Mapping) and "figures" in nested:
            inner = nested
            break
    figures = inner.get("figures")
    if not isinstance(figures, list):
        return {}
    target_venue = inner.get("target_venue") or spec.get("target_venue", "")
    discipline = inner.get("discipline") or spec.get("discipline", "")
    article_type = (
        inner.get("article_type")
        or inner.get("paper_type")
        or spec.get("article_type")
        or spec.get("paper_type", "")
    )
    return {
        "style_profile": inner.get("style_profile", ""),
        "target_venue": target_venue,
        "discipline": discipline,
        "article_type": article_type,
        "figures": [f for f in figures if isinstance(f, Mapping)],
        "narrative_order": inner.get("narrative_order", []),
        "notes": inner.get("notes", ""),
    }


def _grid_shape(figure_spec: Mapping[str, Any], n_panels: int) -> tuple[int, int]:
    comp = figure_spec.get("composition")
    if isinstance(comp, Mapping):
        rows = int(_coerce_float(comp.get("rows")) or 0)
        cols = int(_coerce_float(comp.get("cols")) or 0)
        if rows > 0 and cols > 0 and rows * cols >= n_panels:
            return rows, cols
    if isinstance(comp, str) and "x" in comp.lower():
        try:
            rows_s, cols_s = comp.lower().split("x", 1)
            rows, cols = int(rows_s), int(cols_s)
            if rows > 0 and cols > 0 and rows * cols >= n_panels:
                return rows, cols
        except ValueError:
            pass
    cols = min(3, max(1, n_panels))
    rows = math.ceil(n_panels / cols)
    return rows, cols


def _panel_layout(figure: Mapping[str, Any], panels: Sequence[Mapping[str, Any]]):
    """Resolve GridSpec cells and parent-relative insets before creating axes.

    ``layout_span`` is deliberately separate from the legacy x-domain ``span``.
    Mosaic labels are panel IDs (case-insensitive single characters).
    """
    ids = [str(p.get("panel_id") or chr(97 + i)) for i, p in enumerate(panels)]
    if len(set(ids)) != len(ids):
        raise ValueError("layout has duplicate panel identities")
    main = [i for i, p in enumerate(panels) if not p.get("inset", False)]
    if not main:
        raise ValueError("layout needs at least one non-inset panel")
    comp = figure.get("composition")
    mosaic = (
        isinstance(comp, str)
        and bool(comp.strip())
        and not re.fullmatch(r"\s*\d+\s*x\s*\d+\s*", comp, re.I)
    )
    advanced = any(
        any(k in p for k in ("layout_span", "grid_position", "inset")) for p in panels
    )
    rows, cols = _grid_shape(figure, 1 if advanced and comp else len(main))
    cells = {}
    if mosaic:
        matrix = [list(row.strip()) for row in comp.replace(";", "\n").splitlines()]
        if not matrix or not matrix[0] or len({len(row) for row in matrix}) != 1:
            raise ValueError("mosaic must have equal nonempty row lengths")
        rows, cols = len(matrix), len(matrix[0])
        labels = {value.upper() for row in matrix for value in row if value != "."}
        if labels != {ids[i].upper() for i in main} or len(labels) != len(main):
            raise ValueError(
                "mosaic labels must exactly match non-inset panel identities"
            )
        for i in main:
            coordinates = [
                (r, c)
                for r, row in enumerate(matrix)
                for c, value in enumerate(row)
                if value.upper() == ids[i].upper()
            ]
            r0, c0 = map(min, zip(*coordinates))
            r1, c1 = map(max, zip(*coordinates))
            if len(coordinates) != (r1 - r0 + 1) * (c1 - c0 + 1):
                raise ValueError("mosaic panel must occupy a rectangle")
            cells[i] = (r0, c0, r1 + 1, c1 + 1)
    occupied = set()
    for i in main:
        panel = panels[i]
        span = panel.get("layout_span", [1, 1])
        if (
            not isinstance(span, (list, tuple))
            or len(span) != 2
            or any(type(v) is not int or v < 1 for v in span)
        ):
            raise ValueError("layout span must contain two positive integers")
        position = panel.get("grid_position")
        if position is not None and (
            not isinstance(position, (list, tuple))
            or len(position) != 2
            or any(type(v) is not int or v < 0 for v in position)
        ):
            raise ValueError("layout position must contain two nonnegative integers")
        if mosaic:
            r, c, end_r, end_c = cells[i]
            if "layout_span" in panel and list(span) != [end_r - r, end_c - c]:
                raise ValueError("layout span conflicts with mosaic")
            if position is not None and list(position) != [r, c]:
                raise ValueError("layout position conflicts with mosaic")
        else:
            candidates = (
                [position]
                if position is not None
                else [(r, c) for r in range(rows) for c in range(cols)]
            )
            for r, c in candidates:
                end_r, end_c = r + span[0], c + span[1]
                if end_r > rows or end_c > cols:
                    continue
                wanted = {(y, x) for y in range(r, end_r) for x in range(c, end_c)}
                if not wanted & occupied:
                    cells[i] = (r, c, end_r, end_c)
                    occupied |= wanted
                    break
            else:
                raise ValueError("layout span overlaps or exceeds the grid")
    insets = {}
    for i, panel in enumerate(panels):
        if type(panel.get("inset", False)) is not bool:
            raise ValueError("inset must be boolean")
        if not panel.get("inset"):
            if "inset_parent" in panel or "inset_bounds" in panel:
                raise ValueError("inset settings require inset=true")
            continue
        if panel.get("layout_span", [1, 1]) != [1, 1] or "grid_position" in panel:
            raise ValueError("inset cannot also occupy grid cells")
        previous = [j for j in main if j < i]
        parent = panel.get("inset_parent", ids[previous[-1]] if previous else None)
        if parent not in [ids[j] for j in main]:
            raise ValueError("inset needs a non-inset parent panel")
        bounds = panel.get("inset_bounds", [0.55, 0.55, 0.4, 0.4])
        if (
            not isinstance(bounds, (list, tuple))
            or len(bounds) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
        ):
            raise ValueError("inset bounds must contain four finite numbers")
        x, y, w, h = bounds
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1 or y + h > 1:
            raise ValueError("inset bounds exceed its parent")
        for other_parent, (ox, oy, ow, oh) in insets.values():
            if (
                parent == ids[other_parent]
                and x < ox + ow
                and ox < x + w
                and y < oy + oh
                and oy < y + h
            ):
                raise ValueError("inset bounds overlap another inset")
        insets[i] = (ids.index(parent), list(bounds))
    return rows, cols, cells, insets


def _filter_miss(df: pd.DataFrame, panel: Mapping[str, Any]) -> str:
    """Which half of a panel's filter the records could not answer.

    "no_matching_records" reads the same whether the records carry the field and no
    row holds the value, or carry no such field at all. The second is a plan written
    against a vocabulary the evidence never used, and telling the two apart cost a
    paid WRITE stage and a hand query: every panel of a four-figure suite reported
    no_matching_records against 884 records, because the plan filtered on task/model/
    target/split and not one record had any of them.
    """
    record_filter = panel.get("record_filter")
    if not isinstance(record_filter, Mapping) or not record_filter:
        return ""
    absent = [str(key) for key in record_filter if str(key) not in df.columns]
    if absent:
        return f":records_carry_no_field:{','.join(absent)}"
    return ":no_row_matches:" + ",".join(
        f"{key}={value}" for key, value in record_filter.items()
    )


def _select_panel_records(
    df: pd.DataFrame, panel: Mapping[str, Any], chart_kind: str
) -> pd.DataFrame:
    record_filter = panel.get("record_filter")
    if isinstance(record_filter, Mapping) and record_filter:
        data = df
        for key, value in record_filter.items():
            key = str(key)
            if key not in data.columns:
                # A filter naming a column the records do not carry matches nothing
                # only when the records are typed. Untyped rows have no such column
                # to disagree with, so the filter does not apply to them.
                if "figure_type" in data.columns:
                    data = data[data["figure_type"].fillna("").astype(str).eq("")]
                continue
            data = data[data[key] == value]
        # A stated filter is the whole selection: a miss is reported, not widened
        # to whatever the panel id or chart type would otherwise pick up.
        return data
    panel_id = str(panel.get("panel_id", "") or "").strip()
    if panel_id and "panel" in df.columns:
        matched = df[df["panel"].astype(str) == panel_id]
        if not matched.empty:
            return matched
    default_type = PANEL_CHARTS[chart_kind][2]
    if "figure_type" in df.columns:
        matched = df[df["figure_type"].eq(default_type)]
        if not matched.empty:
            return matched
        # Untyped records feed ANY chart kind. Restricting this to the
        # "generic" kinds silently dropped grouped_bar/heatmap/radar/pareto/
        # sensitivity panels whenever the records carried no figure_type —
        # the most common benchmark panel vanished from the composed figure
        # behind a limitations note (found live, 2026-08-16).
        untyped = df[df["figure_type"].eq("")]
        if not untyped.empty:
            return untyped
    # Records with no figure_type column at all are untyped too: a result row
    # that names its track and metric still draws, rather than emptying the suite.
    if "figure_type" not in df.columns and not df.empty:
        return df
    # image/qualitative panels may bind purely via asset_path in the spec, with
    # no matching records — hand them an empty-but-nonzero frame so the drawer
    # (which reads the asset from the panel) still runs.
    if chart_kind in ("image", "qualitative_grid") and (
        panel.get("asset_path") or panel.get("assets")
    ):
        return df.iloc[0:1]
    return df.iloc[0:0]


def _panel_letter(index: int, profile: dict[str, Any]) -> str:
    letter = chr(ord("a") + index) if index < 26 else f"p{index}"
    if profile.get("panel_label_case") == "upper":
        letter = letter.upper()
    return str(profile.get("panel_label_fmt", "({})")).format(letter)


def _spec_fingerprint(spec: Mapping[str, Any]) -> str:
    canonical = json.dumps(spec, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def render_figure_suite_spec(
    *,
    spec: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
    suite_id: str = "experiment",
    formats: Sequence[str] = DEFAULT_FORMATS,
    claim_boundary: str = "observed_or_reported_results",
    style_profile: str | None = None,
) -> ExperimentFigureSuite:
    """Render composed multi-panel figures from an exemplar-derived suite spec.

    The spec supplies FORM only (chart kinds, panel composition, labels,
    discipline style); all rendered numbers come from ``records``. Panels whose
    records are missing are skipped and reported in ``provenance.limitations``,
    never invented.
    """

    normalized = _normalize_suite_spec(spec)
    limitations: list[str] = []
    if not normalized:
        return ExperimentFigureSuite(
            status="empty",
            provenance={
                "backend": BACKEND_NAME,
                "claim_boundary": claim_boundary,
                "limitations": ["no_figures_in_spec"],
            },
        )

    cleaned = [
        _clean_record(record) for record in records if isinstance(record, Mapping)
    ]
    policy_resolution = resolve_result_plot_policy(
        explicit_style_profile=style_profile,
        spec_style_profile=str(normalized.get("style_profile") or ""),
        target_venue=str(normalized.get("target_venue") or ""),
        discipline=str(normalized.get("discipline") or ""),
        article_type=str(normalized.get("article_type") or ""),
        records=cleaned,
    )
    policy_provenance = policy_resolution.as_provenance()
    profile_name, base_profile = resolve_style_profile(
        policy_resolution.policy.style_profile
    )
    requested_profile = style_profile or normalized.get("style_profile")
    if requested_profile:
        requested_name, _ = resolve_style_profile(str(requested_profile))
        if requested_name != str(requested_profile).strip().lower():
            limitations.append(
                f"unknown_style_profile:{requested_profile}->{profile_name}"
            )
    if not cleaned:
        return ExperimentFigureSuite(
            status="empty",
            provenance={
                "backend": BACKEND_NAME,
                "style_profile": profile_name,
                "result_plot_policy": policy_resolution.as_provenance(),
                "claim_boundary": claim_boundary,
                "spec_fingerprint": _spec_fingerprint(normalized),
                "limitations": ["no_experiment_records"],
            },
        )
    # ponytail: a result whose spread lives in summary.grade_counts has one scalar
    # value at the top, so a bar panel of it draws flat. Expand those counts into
    # rows. The numbers are the record's own. ISSUE-figure-plan-recurate-2026-09-29.
    expanded = []
    for record in cleaned:
        summary = (
            record.get("summary") if isinstance(record.get("summary"), Mapping) else {}
        )
        groups = [("by_condition", "condition")]
        spread = False
        for key, facet in groups:
            block = summary.get(key)
            if not isinstance(block, Mapping):
                continue
            rows = {"": block} if facet == {} else block
            for facet_value, counts in rows.items():
                if not isinstance(counts, Mapping):
                    continue
                for grade, count in counts.items():
                    if grade not in (
                        "Normal/Mild",
                        "Moderate",
                        "Severe",
                    ) or not isinstance(count, (int, float)):
                        continue
                    spread = True
                    row = {
                        **record,
                        "grade": str(grade),
                        "metric": "grade_count",
                        "value": count,
                    }
                    # The facet is the series, not a replicate of one method.
                    # Leaving method as the series makes grouped_bar average the
                    # strata and draw them as error bars. ISSUE-figure-package-not-wired-2026-09-30.
                    if facet:
                        row["method"] = str(facet_value).replace("_", " ")
                    expanded.append(row)
        if not spread:
            expanded.append(record)
    cleaned = expanded
    profile = {
        **base_profile,
        "result_plot_policy": policy_provenance,
        "reveal_raw_points": policy_resolution.policy.reveal_raw_points,
        "print_safe_hatches": policy_resolution.policy.print_safe_hatches,
    }
    _activate_profile(profile)

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    requested_formats = tuple(_normalize_formats(formats))
    df = pd.DataFrame(cleaned)
    slug = _slug(suite_id)

    figures: list[ExperimentFigureArtifact] = []
    for figure_index, figure_spec in enumerate(normalized["figures"]):
        figure_id = _slug(
            str(figure_spec.get("figure_id", "") or f"figure_{figure_index + 1}")
        )
        panels = [
            p for p in (figure_spec.get("panels") or []) if isinstance(p, Mapping)
        ]
        if not panels:
            limitations.append(f"{figure_id}: no_panels_in_spec")
            continue
        intended_layout = _panel_layout(figure_spec, panels)

        # Resolve chart kinds and records first so the grid reflows around skips.
        drawable: list[tuple[Mapping[str, Any], str, pd.DataFrame]] = []
        for panel_index, panel in enumerate(panels):
            panel_name = str(panel.get("panel_id", "") or chr(ord("a") + panel_index))
            requested = str(panel.get("chart", ""))
            refused = refuse_chart_kind(requested)
            if refused:
                limitations.append(f"{figure_id}/{panel_name}: {refused}")
                continue
            kind = canonical_chart_kind(requested)
            if kind is None:
                limitations.append(
                    f"{figure_id}/{panel_name}: unsupported_chart:{panel.get('chart')}"
                )
                continue
            # No fallback to every record: a panel whose chart no record feeds is
            # skipped and reported, never drawn from another chart's evidence.
            data = _select_panel_records(df, panel, kind)
            if data.empty:
                limitations.append(
                    f"{figure_id}/{panel_name}: no_matching_records{_filter_miss(df, panel)}"
                )
                continue
            empty = empty_effect_reason(kind, data.to_dict("records"))
            if empty:
                limitations.append(f"{figure_id}/{panel_name}: retained_{empty}")
            drawable.append((panel, kind, data))
        if not drawable:
            limitations.append(f"{figure_id}: all_panels_skipped")
            continue

        rows, cols, layout_cells, layout_insets = (
            intended_layout
            if len(drawable) == len(panels)
            else _panel_layout(figure_spec, [panel for panel, _, _ in drawable])
        )
        panel_w, panel_h = profile.get("panel_size", (4.2, 3.4))
        # A profile's panel size suits one panel, but a wide row of them
        # overflows the text block it has to sit in. A figure may state its own
        # panel size, or the total width the composed figure must not exceed.
        spec_panel = figure_spec.get("panel_size")
        if isinstance(spec_panel, (list, tuple)) and len(spec_panel) == 2:
            override = [_coerce_float(v) for v in spec_panel]
            if all(v and v > 0 for v in override):
                panel_w, panel_h = float(override[0]), float(override[1])
        # Row-labelled charts (forest/coefficient plots) carry their category
        # names on the y-axis; with long outcome names the labels ate most of
        # a default-width panel and clipped the x-axis title (rendered live,
        # 2026-08-16). Widen the panel for the longest label actually drawn.
        longest_row_label = 0
        for panel, kind, data in drawable:
            if kind != "forest":
                continue
            label_col = _col(panel, "label_col", "label")
            if label_col in data.columns:
                longest_row_label = max(
                    [longest_row_label]
                    + [len(str(v)) for v in data[label_col].tolist()]
                )
        if longest_row_label > 22:
            panel_w += min((longest_row_label - 22) * 0.085, 3.2)
        # Clamp last: the row-label widening above must not push a figure back
        # past the width its page can hold.
        max_width = _coerce_float(figure_spec.get("max_width_in"))
        if max_width and max_width > 0 and panel_w * cols > max_width:
            shrink = max_width / (panel_w * cols)
            panel_w *= shrink
            panel_h *= shrink
        # A legend below the axes needs width, or it spills into the next panel.
        legend_w = max(
            (
                len(str(m))
                for _, _, data in drawable
                for m in (data["method"].unique() if "method" in data.columns else [])
            ),
            default=0,
        )
        if legend_w > 8:
            panel_w = max(panel_w, 3.2 + legend_w * 0.13)
        fig = plt.figure(
            figsize=(panel_w * cols, panel_h * rows), constrained_layout=True
        )
        ratios = _as_number_list(figure_spec.get("height_ratios"))
        grid = fig.add_gridspec(
            rows,
            cols,
            height_ratios=ratios if len(ratios) == rows and min(ratios) > 0 else None,
        )
        axes = {
            slot: fig.add_subplot(
                grid[r0:r1, c0:c1], polar=PANEL_CHARTS[drawable[slot][1]][1]
            )
            for slot, (r0, c0, r1, c1) in layout_cells.items()
        }
        for slot, (parent, bounds) in layout_insets.items():
            axes[slot] = axes[parent].inset_axes(
                bounds, polar=PANEL_CHARTS[drawable[slot][1]][1]
            )
        panel_provenance: list[dict[str, Any]] = []
        drawn_axes: list[tuple[int, plt.Axes]] = []
        drawn = 0
        for slot, (panel, kind, data) in enumerate(drawable):
            drawer, needs_polar, _ = PANEL_CHARTS[kind]
            ax = axes[slot]
            meta = drawer(ax, data, panel, profile)
            panel_name = str(panel.get("panel_id", "") or chr(ord("a") + slot))
            if meta is None:
                if any(parent == slot for parent, _ in layout_insets.values()):
                    plt.close(fig)
                    raise ValueError("inset parent has no renderable data")
                ax.remove()
                limitations.append(
                    f"{figure_id}/{panel_name}: missing_required_columns"
                )
                continue
            if not needs_polar:
                _tidy_categorical_axis(ax)
            if len(drawable) > 1:
                letter = _panel_letter(drawn, profile)
                # A title, an above-axes legend and the panel letter all want
                # the strip over the axes. Measure the legend once and give
                # each of them its own band.
                legend = ax.get_legend()
                legend_rows = 0
                if legend is not None:
                    anchor = getattr(legend, "_bbox_to_anchor", None)
                    if anchor is not None and getattr(anchor, "y0", 0) >= 1.0:
                        legend_rows = math.ceil(
                            len(legend.get_texts()) / max(legend._ncols, 1)
                        )
                title = ax.get_title()
                if title:
                    # A centred title long enough to reach the left edge sits
                    # under a floating letter at any y it is lifted to, because
                    # the title band grows with it. Carry the letter inside a
                    # left-aligned title instead: nothing then floats, at any
                    # panel width.
                    ax.set_title("", loc="center")
                    ax.set_title(
                        f"$\\bf{{{letter}}}$   {title}",
                        loc="left",
                        pad=6 + 11 * legend_rows,
                    )
                else:
                    ax.text(
                        -0.08,
                        1.06 + 0.10 * legend_rows,
                        letter,
                        transform=ax.transAxes,
                        fontweight="bold",
                        fontsize=plt.rcParams["axes.titlesize"],
                        va="bottom",
                        ha="left",
                    )
            panel_provenance.append({"panel_id": panel_name, "chart": kind, **meta})
            if slot not in layout_insets:
                r0, c0, r1, c1 = layout_cells[slot]
                drawn_axes.append(((r1 - 1) * cols + c0, ax))
            drawn += 1
        _compose_panels(fig, drawn_axes, rows, cols, figure_spec)
        if drawn == 0:
            plt.close(fig)
            limitations.append(f"{figure_id}: all_panels_skipped")
            continue

        suptitle = str(figure_spec.get("suptitle", "") or "").strip()
        if suptitle:
            fig.suptitle(suptitle)
        title = str(figure_spec.get("title", "") or figure_id).strip()
        artifact = _save_figure(
            fig=fig,
            output_dir=root,
            figure_id=f"{slug}_{figure_id}",
            title=title,
            figure_type=(panel_provenance[0]["chart"] if drawn == 1 else "multi_panel"),
            formats=requested_formats,
            claim_boundary=claim_boundary,
            source_records=int(sum(p.get("records", 0) for p in panel_provenance)),
            extra_provenance={
                "style_profile": profile_name,
                "result_plot_policy": policy_resolution.as_provenance(),
                "spec_figure_id": str(figure_spec.get("figure_id", "") or figure_id),
                "role": str(figure_spec.get("role", "") or ""),
                "placement": str(figure_spec.get("placement", "main") or "main"),
                "panels": panel_provenance,
                "caption_skeleton": str(figure_spec.get("caption_skeleton", "") or ""),
                "source_note": str(figure_spec.get("source_note", "") or ""),
            },
        )
        figures.append(artifact)

    status = "rendered" if figures else "empty"
    if not figures and "no_renderable_figures" not in limitations:
        limitations.append("no_renderable_figures")
    return ExperimentFigureSuite(
        status=status,
        figures=figures,
        provenance={
            "backend": BACKEND_NAME,
            "style_profile": profile_name,
            "result_plot_policy": policy_resolution.as_provenance(),
            "claim_boundary": claim_boundary,
            "record_count": len(cleaned),
            "figure_count": len(figures),
            "figure_types": [figure.figure_type for figure in figures],
            "spec_fingerprint": _spec_fingerprint(normalized),
            "limitations": limitations,
        },
    )


def _compose_panels(
    fig: plt.Figure,
    drawn_axes: Sequence[tuple[int, plt.Axes]],
    rows: int,
    cols: int,
    figure_spec: Mapping[str, Any],
) -> None:
    """Make a grid of panels read as one figure rather than as several.

    Two conventions, both opt-in per figure. ``shared_legend`` lifts one legend
    out to the figure and drops the per-panel copies, which otherwise repeat the
    same two entries in every panel and sit on the data. ``share_axis_labels``
    keeps an axis title only on the outer panels, and only where every panel
    agrees on the wording -- panels measuring different things keep their own.
    """
    if len(drawn_axes) < 2:
        return
    if bool(figure_spec.get("shared_legend", False)):
        handles: list[Any] = []
        labels: list[str] = []
        for _, ax in drawn_axes:
            for handle, label in zip(*ax.get_legend_handles_labels()):
                if label not in labels:
                    handles.append(handle)
                    labels.append(label)
            legend = ax.get_legend()
            if legend is not None:
                legend.remove()
        if handles:
            fig.legend(
                handles,
                labels,
                loc="outside upper center",
                ncols=min(len(labels), 4),
                frameon=False,
            )
    if bool(figure_spec.get("share_x", False)):
        # One x axis for a stacked column: the scale is read once, at the foot.
        first = drawn_axes[0][1]
        for slot, ax in drawn_axes[1:]:
            ax.sharex(first)
        for slot, ax in drawn_axes:
            if slot // cols != rows - 1:
                ax.tick_params(axis="x", labelbottom=False)
    if bool(figure_spec.get("share_axis_labels", False)):
        for axis in ("x", "y"):
            getter = "get_xlabel" if axis == "x" else "get_ylabel"
            setter = "set_xlabel" if axis == "x" else "set_ylabel"
            texts = {getattr(ax, getter)() for _, ax in drawn_axes}
            if len(texts) != 1 or not next(iter(texts)):
                continue  # panels disagree: each keeps its own
            shared = next(iter(texts))
            for _, ax in drawn_axes:
                getattr(ax, setter)("")
            # matplotlib sizes a figure-level label like a suptitle; it is the
            # same axis label as before, so it keeps the axis label's size.
            (fig.supxlabel if axis == "x" else fig.supylabel)(
                shared, fontsize=plt.rcParams["axes.labelsize"]
            )
    # A row of panels whose titles wrap to different numbers of lines has its
    # axes starting at different heights, which reads as a misalignment rather
    # than as a long name. Give every title the tallest one's line count.
    titles = {ax: ax.get_title(loc="left") or ax.get_title() for _, ax in drawn_axes}
    depth = max((t.count("\n") for t in titles.values() if t), default=0)
    if depth:
        for ax, text in titles.items():
            if not text or text.count("\n") == depth:
                continue
            padded = "\n" * (depth - text.count("\n")) + text
            loc = "left" if ax.get_title(loc="left") else "center"
            ax.set_title(padded, loc=loc)


def summarize_records_for_plan(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compact inventory of available experiment records.

    Feed this into the ``figure_suite`` plan step so the exemplar-derived
    suite only plans panels for data that actually exists.
    """
    cleaned = [
        _clean_record(record) for record in records if isinstance(record, Mapping)
    ]
    if not cleaned:
        return {"record_count": 0}
    df = pd.DataFrame(cleaned)
    inventory: dict[str, Any] = {
        "record_count": len(cleaned),
        "columns": sorted(str(c) for c in df.columns),
        "supported_charts": sorted(PANEL_CHARTS),
    }
    if "figure_type" in df.columns:
        counts = df["figure_type"].value_counts()
        inventory["figure_types"] = {
            str(k): int(v) for k, v in counts.items() if str(k)
        }
    for column in ("dataset", "method", "metric", "variant", "group", "label"):
        if column in df.columns:
            values = [str(v) for v in df[column].dropna().unique()][:12]
            if values:
                inventory[f"{column}s"] = values
    return inventory


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _save_figure(
    *,
    fig: plt.Figure,
    output_dir: Path,
    figure_id: str,
    title: str,
    figure_type: str,
    formats: Sequence[str],
    claim_boundary: str,
    source_records: int,
    extra_provenance: Mapping[str, Any] | None = None,
) -> ExperimentFigureArtifact:
    try:
        managed_layout = fig.get_layout_engine() is not None
    except AttributeError:  # older matplotlib
        managed_layout = bool(getattr(fig, "get_constrained_layout", lambda: False)())
    if not managed_layout:
        fig.tight_layout()
    paths: dict[str, str] = {}
    for fmt in formats:
        path = output_dir / f"{figure_id}.{fmt}"
        fig.savefig(path, dpi=320, bbox_inches="tight", facecolor="white")
        paths[fmt] = str(path)
    plt.close(fig)
    provenance: dict[str, Any] = {
        "backend": BACKEND_NAME,
        "claim_boundary": claim_boundary,
        "source_records": source_records,
        "formats": list(formats),
    }
    if extra_provenance:
        provenance.update(dict(extra_provenance))
    return ExperimentFigureArtifact(
        figure_id=figure_id,
        title=title,
        figure_type=figure_type,
        paths=paths,
        provenance=provenance,
    )


def _apply_publication_style(style: str) -> None:
    sns.set_theme(
        context="paper",
        style="whitegrid",
        font="DejaVu Sans",
        rc={
            "axes.titlesize": 13,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "figure.dpi": 160,
            "savefig.dpi": 320,
            "axes.edgecolor": "#243447",
            "grid.color": "#e6ebf1",
            "grid.linewidth": 0.7,
        },
    )
    if style == "compact":
        plt.rcParams.update({"axes.titlesize": 12, "axes.labelsize": 9})


def _normalize_metric_values(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for metric, group in data.groupby("metric", sort=False):
        values = group["value"].astype(float)
        min_value = float(values.min())
        max_value = float(values.max())
        span = max(max_value - min_value, 1e-9)
        higher_is_better = bool(group["higher_is_better"].iloc[0])
        for row in group.itertuples(index=False):
            raw = (float(row.value) - min_value) / span
            normalized = raw if higher_is_better else 1.0 - raw
            rows.append(
                {
                    "method": row.method,
                    "metric": metric,
                    "normalized_value": normalized,
                }
            )
    return pd.DataFrame(rows)


def _annotate_bar_values(ax: plt.Axes) -> None:
    for container in ax.containers:
        ax.bar_label(container, fmt="%.2f", padding=2, fontsize=7)


def _despine_grid(ax: plt.Axes, profile: dict[str, Any] | None = None) -> None:
    sns.despine(ax=ax, left=False, bottom=False)
    grid_axis = (profile or {}).get("grid_axis", "y")
    if grid_axis:
        ax.grid(axis=grid_axis, alpha=0.75)
        ax.grid(axis="x" if grid_axis == "y" else "y", visible=False)
    else:
        ax.grid(visible=False)


def _tidy_categorical_axis(ax: plt.Axes) -> None:
    """Keep long categorical tick labels legible.

    Publication figures die on overlapping method names ("EmoFaceDiffPose-
    TalkMEDTalk" ran together in a rendered benchmark panel, 2026-08-16).
    Rotate once the labels no longer fit the axis width; keep them horizontal
    when they do, because rotation costs readability.
    """
    labels = [t.get_text() for t in ax.get_xticklabels()]
    if not labels or not any(label.strip() for label in labels):
        return

    def _numeric(text: str) -> bool:
        try:
            float(text.replace("−", "-").replace(",", ""))
        except ValueError:
            return False
        return True

    # A numeric axis is already compact; rotating it only costs readability.
    if all(_numeric(label) for label in labels if label.strip()):
        return
    fig = ax.get_figure()
    if fig is None:
        return
    try:
        width_in = ax.get_window_extent().width / fig.dpi
    except Exception:  # noqa: BLE001 - layout not realized yet
        return
    longest = max(len(label) for label in labels)
    # ~0.075 in per character at paper-context tick sizes.
    needed_in = len(labels) * (longest * 0.075 + 0.12)
    if needed_in <= width_in:
        return
    rotation = 30 if needed_in < width_in * 2 else 45
    for tick in ax.get_xticklabels():
        tick.set_rotation(rotation)
        tick.set_ha("right")
        tick.set_rotation_mode("anchor")


def _first_nonempty(data: pd.DataFrame, column: str, default: str) -> str:
    if column not in data.columns:
        return default
    values = [str(value).strip() for value in data[column].tolist()]
    return next((value for value in values if value and value != "nan"), default)


def _normalize_formats(formats: Sequence[str]) -> list[str]:
    normalized = []
    for fmt in formats or DEFAULT_FORMATS:
        value = str(fmt).strip().lower().lstrip(".")
        if value in {"png", "pdf", "svg"} and value not in normalized:
            normalized.append(value)
    return normalized or ["png"]


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in str(value))
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "experiment"
