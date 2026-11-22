"""Records -> evidence-bound result matrix.

Aggregates plain records into a (row x column) matrix of cells, resolves the
"best" cell per column from ``higher_is_better``, and flags statistical ties
(best and runner-up within one standard error). Every number is traceable to a
caller record; missing (row, column) intersections are recorded as gaps rather
than invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, stdev
from typing import Any, Mapping, Sequence

from .contracts import metric_higher_is_better, table_field_requirements


@dataclass
class Cell:
    mean: float | None = None
    std: float | None = None
    lo: float | None = None
    hi: float | None = None
    n: int | None = None
    present: bool = False
    is_best: bool = False
    is_tied_best: bool = False  # statistically indistinguishable from best
    is_second: bool = False  # runner-up (underline, exptab-style)
    significant: bool = False  # paper-stated sig. vs baseline -> dagger mark
    eligible_best: bool = True  # reference/UB rows: shown, never bolded
    samples: list[float] = field(default_factory=list)  # raw values (for stats backend)
    display: str | None = None  # only for pre-formatted tables


@dataclass
class Column:
    group: str | None  # spanner (e.g. dataset), or None
    metric: str  # metric label / cohort group
    higher_is_better: bool = True
    no_best: bool = False


@dataclass
class ResultMatrix:
    table_type: str
    rows: list[str] = field(default_factory=list)
    columns: list[Column] = field(default_factory=list)
    cells: dict[tuple[str, int], Cell] = field(default_factory=dict)
    row_group: dict[str, str] = field(default_factory=dict)  # row label -> group
    group_order: list[str] = field(default_factory=list)  # group render order
    provenance: dict[str, Any] = field(default_factory=dict)

    def cell(self, row: str, col_index: int) -> Cell:
        return self.cells.get((row, col_index), Cell())

    @property
    def has_spanners(self) -> bool:
        return any(c.group for c in self.columns)

    @property
    def has_row_groups(self) -> bool:
        return bool(self.group_order)


def _ordered_unique(
    values: Sequence[Any], preferred: Sequence[str] | None
) -> list[str]:
    seen: list[str] = []
    if preferred:
        for p in preferred:
            if p in values and p not in seen:
                seen.append(p)
    for v in values:
        if v is not None and v not in seen:
            seen.append(v)
    return seen


def _pooled(values: list[float]) -> tuple[float, float | None, int]:
    if len(values) == 1:
        return values[0], None, 1
    return mean(values), stdev(values), len(values)


def build_matrix(
    records: Sequence[Mapping[str, Any]],
    *,
    table_type: str,
    rows_order: Sequence[str] | None = None,
    columns_order: Sequence[str] | None = None,
    groups_order: Sequence[str] | None = None,
    mark_ties: bool = True,
    mark_second: bool = True,
    use_autorank: bool = True,
    alpha: float = 0.05,
) -> ResultMatrix:
    contract = table_field_requirements(table_type)
    row_key = contract.get("row", "method")
    group_key = contract.get("group")
    metric_key = contract.get("metric", "metric")
    no_best = bool(contract.get("no_best"))
    preformatted = bool(contract.get("preformatted"))

    rel = [
        r
        for r in records
        if r.get(row_key) is not None and r.get(metric_key) is not None
    ]
    skipped = len(records) - len(rel)

    row_labels = _ordered_unique([r.get(row_key) for r in rel], rows_order)
    # a group_key is a *possible* spanner; if no record carries it, fall back to
    # a single flat level (many tables have no dataset/group dimension).
    groups = (
        [None]
        if not group_key
        else (_ordered_unique([r.get(group_key) for r in rel], groups_order) or [None])
    )
    metrics = _ordered_unique([r.get(metric_key) for r in rel], columns_order)

    # Column order: group-major so spanners stay contiguous.
    columns: list[Column] = []
    col_index: dict[tuple[str | None, str], int] = {}
    for g in groups:
        for m in metrics:
            has_any = any(
                r.get(metric_key) == m and (group_key is None or r.get(group_key) == g)
                for r in rel
            )
            if not has_any:
                continue
            hib = None
            for r in rel:
                if r.get(metric_key) == m and r.get("higher_is_better") is not None:
                    hib = bool(r.get("higher_is_better"))
                    break
            columns.append(
                Column(
                    group=g,
                    metric=str(m),
                    higher_is_better=metric_higher_is_better(m, hib),
                    no_best=no_best,
                )
            )
            col_index[(g, str(m))] = len(columns) - 1

    matrix = ResultMatrix(table_type=table_type, rows=row_labels, columns=columns)

    # row grouping (categorized rows, e.g. "Revenue-only" / "Multi-objective")
    for r in rel:
        rl = str(r.get(row_key))
        g = r.get("row_group")
        if g and rl not in matrix.row_group:
            matrix.row_group[rl] = str(g)
    if matrix.row_group:
        for rl in row_labels:
            g = matrix.row_group.get(rl)
            if g and g not in matrix.group_order:
                matrix.group_order.append(g)

    # Fill cells: aggregate duplicate (row, group, metric) records.
    buckets: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    for r in rel:
        g = None if group_key is None else r.get(group_key)
        m = str(r.get(metric_key))
        idx = col_index.get((g, m))
        if idx is None:
            continue
        buckets.setdefault((str(r.get(row_key)), idx), []).append(r)

    for (row, idx), recs in buckets.items():
        if preformatted:
            disp = next(
                (str(x.get("value")) for x in recs if x.get("value") is not None), None
            )
            matrix.cells[(row, idx)] = Cell(present=disp is not None, display=disp)
            continue
        vals = [
            x.get("value") for x in recs if isinstance(x.get("value"), (int, float))
        ]
        if not vals:
            continue
        sample_vals = [float(v) for v in vals]
        mu, pooled_std, n = _pooled(sample_vals)
        # a single record may carry its own std / CI
        own_std = next((x.get("std") for x in recs if x.get("std") is not None), None)
        lo = next((x.get("lo") for x in recs if x.get("lo") is not None), None)
        hi = next((x.get("hi") for x in recs if x.get("hi") is not None), None)
        own_n = next((x.get("n") for x in recs if x.get("n") is not None), None)
        eligible = not any(bool(x.get("exclude_from_best")) for x in recs)
        sig = any(bool(x.get("significant")) for x in recs)
        matrix.cells[(row, idx)] = Cell(
            mean=mu,
            std=pooled_std if pooled_std is not None else own_std,
            lo=lo,
            hi=hi,
            n=int(own_n) if own_n else n,
            present=True,
            significant=sig,
            eligible_best=eligible,
            samples=sample_vals,
        )

    stat_summaries = _apply_stats(
        matrix,
        mark_ties=mark_ties,
        mark_second=mark_second,
        use_autorank=use_autorank,
        alpha=alpha,
    )

    filled = sum(1 for c in matrix.cells.values() if c.present)
    total = len(row_labels) * len(columns)
    missing = [
        {"row": row, "column": _col_name(columns[i])}
        for row in row_labels
        for i in range(len(columns))
        if not matrix.cell(row, i).present
    ]
    matrix.provenance = {
        "backend": "pandas_styler_siunitx",
        "evidence_boundary": "values_from_records_only",
        "table_type": table_type,
        "record_count": len(records),
        "used_records": len(rel),
        "skipped_records": skipped,
        "rows": len(row_labels),
        "columns": len(columns),
        "cells_filled": filled,
        "cells_total": total,
        "coverage": round(filled / total, 3) if total else 0.0,
        "missing_cells": missing,
        "best_cells": sum(1 for c in matrix.cells.values() if c.is_best),
        "tied_cells": sum(1 for c in matrix.cells.values() if c.is_tied_best),
        "second_cells": sum(1 for c in matrix.cells.values() if c.is_second),
        "column_stats": stat_summaries,
        "stats_backend": (
            "autorank"
            if any(s["backend"] == "autorank" for s in stat_summaries)
            else ("heuristic" if stat_summaries else "none")
        ),
        "limitations": ([] if filled else ["no_tabulatable_records"]),
    }
    return matrix


def _apply_stats(
    matrix: ResultMatrix,
    *,
    mark_ties: bool,
    mark_second: bool,
    use_autorank: bool,
    alpha: float,
) -> list[dict[str, Any]]:
    """Set best/tied/second per column via the statistics backend (autorank
    when possible, else heuristic). Returns per-column stat summaries."""
    from .stats import RowStat, analyze_column

    summaries: list[dict[str, Any]] = []
    for i, col in enumerate(matrix.columns):
        if col.no_best:
            continue
        rows = [
            RowStat(
                row=row,
                mean=matrix.cell(row, i).mean,
                std=matrix.cell(row, i).std,
                samples=matrix.cell(row, i).samples,
            )
            for row in matrix.rows
            if matrix.cell(row, i).present
            and matrix.cell(row, i).mean is not None
            and matrix.cell(row, i).eligible_best
        ]
        if not rows:
            continue
        cs = analyze_column(
            rows,
            higher_is_better=col.higher_is_better,
            alpha=alpha,
            use_autorank=use_autorank,
        )
        if cs.best is not None:
            matrix.cell(cs.best, i).is_best = True
        if mark_ties:
            for r in cs.tied:
                if r != cs.best:
                    matrix.cell(r, i).is_tied_best = True
        if mark_second and cs.second is not None:
            matrix.cell(cs.second, i).is_second = True
        summaries.append(
            {
                "column": _col_name(col),
                "backend": cs.backend,
                "central": cs.central,
                "test": cs.test,
                "tied": sorted(cs.tied),
                "second": cs.second,
            }
        )
    return summaries


def _col_name(col: Column) -> str:
    return f"{col.group}/{col.metric}" if col.group else col.metric
