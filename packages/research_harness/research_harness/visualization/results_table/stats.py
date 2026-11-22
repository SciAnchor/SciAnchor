"""Statistical backend for best / tie / significance decisions.

Adopts **autorank** (Herbold, JOSS 2020) as the rigorous engine: given the raw
per-seed samples for the methods in one column, autorank picks the correct test
(Shapiro-Wilk normality -> paired t / Wilcoxon, or repeated-measures ANOVA+Tukey
/ Friedman+Nemenyi), reports the appropriate central tendency (mean+-std when
normal, else median+-MAD), and confidence intervals. We use its per-method CIs
to decide which methods are statistically indistinguishable from the best
(honest tie set) instead of a hand-rolled "within one s.d." heuristic.

Everything degrades gracefully: if autorank is missing, or samples are too few /
unequal / single-point, we fall back to a transparent CI/std-overlap heuristic.
"""

from __future__ import annotations

import contextlib
import io
import warnings
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RowStat:
    row: str
    mean: float
    std: float | None = None
    samples: list[float] = field(default_factory=list)


@dataclass
class ColumnStats:
    backend: str = "none"  # autorank | heuristic | none
    central: str = "mean"  # mean | median
    test: str = ""  # e.g. "anova+tukeyhsd"
    best: str | None = None
    tied: set[str] = field(
        default_factory=set
    )  # indistinguishable from best (incl. best)
    second: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _autorank_ready(rows: list[RowStat]) -> bool:
    if len(rows) < 3:
        return False
    counts = {len(r.samples) for r in rows}
    return counts and min(counts) >= 5 and len(counts) == 1  # paired, >=5 each


def analyze_column(
    rows: list[RowStat],
    *,
    higher_is_better: bool,
    alpha: float = 0.05,
    use_autorank: bool = True,
) -> ColumnStats:
    rows = [r for r in rows if r.mean is not None]
    if not rows:
        return ColumnStats()
    if len(rows) == 1:
        return ColumnStats(backend="none", best=rows[0].row, tied={rows[0].row})

    if use_autorank and _autorank_ready(rows):
        got = _autorank_analyze(rows, higher_is_better=higher_is_better, alpha=alpha)
        if got is not None:
            return got
    return _heuristic_analyze(rows, higher_is_better=higher_is_better)


def _autorank_analyze(
    rows: list[RowStat], *, higher_is_better: bool, alpha: float
) -> ColumnStats | None:
    try:
        import pandas as pd
        from autorank import autorank
    except Exception:
        return None
    try:
        df = pd.DataFrame({r.row: r.samples for r in rows})
        with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter("ignore")
            res = autorank(
                df,
                alpha=alpha,
                verbose=False,
                order="descending" if higher_is_better else "ascending",
            )
        rankdf = res.rankdf
        # rank 1 (lowest meanrank) is the best; rankdf row order is not reliable.
        if "meanrank" in rankdf.columns:
            order = list(rankdf.sort_values("meanrank").index)
        else:
            order = list(rankdf.index)
        best = order[0]
        central = "mean" if getattr(res, "all_normal", True) else "median"
        # tie set: CIs overlapping the best method's CI (autorank computes the CI
        # under the correct test) -> statistically indistinguishable from best.
        tied = {best}
        if {"ci_lower", "ci_upper"}.issubset(rankdf.columns):
            b_lo, b_hi = rankdf.loc[best, "ci_lower"], rankdf.loc[best, "ci_upper"]
            for r in order[1:]:
                lo, hi = rankdf.loc[r, "ci_lower"], rankdf.loc[r, "ci_upper"]
                if lo <= b_hi and hi >= b_lo:  # interval overlap
                    tied.add(r)
        second = next((r for r in order[1:] if r not in tied), None)
        test = f"{getattr(res, 'omnibus', '')}+{getattr(res, 'posthoc', '')}".strip("+")
        return ColumnStats(
            backend="autorank",
            central=central,
            test=test,
            best=best,
            tied=tied,
            second=second,
            details={
                "all_normal": bool(getattr(res, "all_normal", True)),
                "alpha": alpha,
            },
        )
    except Exception:  # any autorank edge (e.g. degenerate variance)
        return None


def _heuristic_analyze(rows: list[RowStat], *, higher_is_better: bool) -> ColumnStats:
    ordered = sorted(rows, key=lambda r: r.mean, reverse=higher_is_better)
    best = ordered[0]
    tied = {best.row}
    b_lo = best.mean - (best.std or 0.0)
    b_hi = best.mean + (best.std or 0.0)
    for r in ordered[1:]:
        lo = r.mean - (r.std or 0.0)
        hi = r.mean + (r.std or 0.0)
        # overlap only counts when at least one side carries a spread
        if (best.std or r.std) and lo <= b_hi and hi >= b_lo:
            tied.add(r.row)
    second = next((r.row for r in ordered[1:] if r.row not in tied), None)
    return ColumnStats(
        backend="heuristic",
        central="mean",
        test="ci/std-overlap",
        best=best.row,
        tied=tied,
        second=second,
    )
