"""Result matrix -> reviewer-standard LaTeX (booktabs + siunitx via Styler).

We do NOT hand-assemble tabular strings. Numbers are formatted Python-side
(precision, mean +- std), best cells are marked with a CSS ``font-weight`` that
``Styler.to_latex(convert_css=True)`` turns into ``\\bfseries``, and siunitx
``S`` columns handle decimal alignment. The one classic gotcha -- bold breaking
S-column alignment -- is solved in the preamble with ``\\robustify\\bfseries``
and ``\\sisetup{detect-all}``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .aggregate import Cell, ResultMatrix

# Preamble every emitted table assumes. Mirrors RH latex_compiler, which
# already loads booktabs; siunitx/etoolbox/threeparttable are added on demand.
REQUIRED_PACKAGES = (
    r"\usepackage{booktabs}",
    r"\usepackage{array}",
    r"\usepackage{siunitx}",
    r"\usepackage{threeparttable}",
    r"\usepackage{etoolbox}",
    r"\robustify\bfseries",
)
SISETUP = r"\sisetup{detect-all, separate-uncertainty=true}"


@dataclass
class LatexTable:
    tabular: str
    table_env: str  # full float, threeparttable + caption
    column_format: str
    preamble_packages: tuple[str, ...] = REQUIRED_PACKAGES
    sisetup: str = SISETUP
    provenance: dict[str, Any] = field(default_factory=dict)


def _tex_escape(text: str) -> str:
    reps = {
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
        "$": r"\$",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(reps.get(ch, ch) for ch in str(text))


def _int_digits(x: float | None) -> int:
    if x is None or x == 0:
        return 1
    return max(1, int(math.floor(math.log10(abs(x)))) + 1)


def _derive_precision(matrix: ResultMatrix, col_idx: int, default: int = 2) -> int:
    """Pick decimals from the data's own granularity (bounded 1..3)."""
    decs: list[int] = []
    for row in matrix.rows:
        c = matrix.cell(row, col_idx)
        if c.present and c.mean is not None:
            frac = abs(c.mean - round(c.mean))
            decs.append(
                0 if frac < 1e-9 else (1 if c.mean == round(c.mean, 1) else default)
            )
    if not decs:
        return default
    # allow 0 decimals for genuine integer columns (counts); else 1..3
    return min(3, max(decs))


def _fmt(value: float, p: int) -> str:
    return f"{value:.{p}f}"


def _cell_string(cell: Cell, p: int, show_unc: bool, raw: bool = False) -> str:
    if not cell.present:
        return "{--}"
    if cell.display is not None:  # pre-formatted (Table-1 style)
        # raw=True: caller owns LaTeX (inline \textbf, [CI], math); else escape.
        return cell.display if raw else _tex_escape(cell.display)
    if cell.mean is None:
        return "{--}"
    # F: paper-stated significance vs baseline -> trailing dagger. siunitx keeps
    # decimal alignment (table-align-text-post) with the mark hanging after.
    dag = r"$^{\dagger}$" if getattr(cell, "significant", False) else ""
    if show_unc and cell.std is not None:
        return f"{_fmt(cell.mean, p)} +- {_fmt(cell.std, p)}{dag}"
    return f"{_fmt(cell.mean, p)}{dag}"


def _table_format(matrix: ResultMatrix, col_idx: int, p: int, has_unc: bool) -> str:
    intdig = 1
    for row in matrix.rows:
        c = matrix.cell(row, col_idx)
        if c.present and c.mean is not None:
            intdig = max(intdig, _int_digits(c.mean))
    core = str(intdig) if p == 0 else f"{intdig}.{p}"
    return f"{core}({p})" if has_unc else core


def matrix_to_latex(
    matrix: ResultMatrix,
    *,
    caption: str,
    label: str,
    row_header: str = "",
    show_uncertainty: bool = True,
    notes: list[str] | None = None,
    numeric: bool | None = None,
    raw_cells: bool = False,
    raw_headers: bool = False,
    direction_arrows: bool = False,
    placement: str = "t",
) -> LatexTable:
    if numeric is None:
        numeric = not any(c.display is not None for c in matrix.cells.values())

    # per-column precision + whether it carries uncertainty
    precisions: list[int] = []
    col_has_unc: list[bool] = []
    for i in range(len(matrix.columns)):
        p = _derive_precision(matrix, i)
        precisions.append(p)
        col_has_unc.append(
            show_uncertainty
            and any(matrix.cell(r, i).std is not None for r in matrix.rows)
        )

    def _lbl(text: str) -> str:
        # raw_headers: caller owns LaTeX (math like $_T$, $\kappa_w$); else escape.
        return text if raw_headers else _tex_escape(text)

    # display + bold-mask frames
    data: dict[Any, list[str]] = {}
    bold: dict[Any, list[bool]] = {}
    header_tuples: list[tuple[str, str] | str] = []
    for i, col in enumerate(matrix.columns):
        # D: direction arrow from higher_is_better (down for error/FID-like metrics).
        arrow = ""
        if direction_arrows:
            arrow = r"\,$\uparrow$" if col.higher_is_better else r"\,$\downarrow$"
        metric_lbl = (
            "{" + _lbl(col.metric) + arrow + "}"
            if numeric
            else _lbl(col.metric) + arrow
        )
        # Group labels must also be braced under numeric (S) columns: a
        # single-metric group lands directly in an S cell, and siunitx would
        # otherwise try to parse e.g. "CIFAR-100" as a number.
        if matrix.has_spanners:
            raw_group = col.group or ""
            group_lbl = (
                "{" + _lbl(raw_group) + "}"
                if numeric and raw_group
                else _lbl(raw_group)
            )
            key: tuple[str, str] | str = (group_lbl, metric_lbl)
        else:
            key = metric_lbl
        header_tuples.append(key)
        data[key] = [
            _cell_string(
                matrix.cell(r, i), precisions[i], col_has_unc[i], raw=raw_cells
            )
            for r in matrix.rows
        ]
        css_col: list[str] = []
        for r in matrix.rows:
            c = matrix.cell(r, i)
            if c.is_best or c.is_tied_best:
                css_col.append("font-weight: bold")
            elif c.is_second and not numeric:
                # underline the runner-up only in non-siunitx columns: an
                # \underline box inside an S column would break decimal alignment.
                css_col.append("text-decoration: underline")
            else:
                css_col.append("")
        bold[key] = css_col

    if matrix.has_spanners:
        columns = pd.MultiIndex.from_tuples(header_tuples)
    else:
        columns = pd.Index(header_tuples)
    disp = pd.DataFrame(
        {k: data[k] for k in data}, index=[_tex_escape(r) for r in matrix.rows]
    )
    disp.columns = columns
    disp.index.name = None
    css = pd.DataFrame({k: bold[k] for k in bold}, index=disp.index)
    css.columns = columns

    def _style(_frame: pd.DataFrame) -> pd.DataFrame:
        return css

    col_fmt_parts = ["l"]
    for i in range(len(matrix.columns)):
        if numeric:
            col_fmt_parts.append(
                f"S[table-format={_table_format(matrix, i, precisions[i], col_has_unc[i])}]"
            )
        else:
            col_fmt_parts.append("c")
    column_format = " ".join(col_fmt_parts)

    tabular = disp.style.apply(_style, axis=None).to_latex(
        hrules=True, column_format=column_format, convert_css=True, multicol_align="c"
    )
    if matrix.has_row_groups:
        tabular = _inject_row_groups(tabular, matrix)
    tabular = _inject_row_header(tabular, row_header) if row_header else tabular

    table_env = _wrap_table_env(
        tabular, caption=caption, label=label, notes=notes or [], placement=placement
    )
    prov = {
        "backend": "pandas_styler_siunitx",
        "numeric_columns": numeric,
        "spanners": matrix.has_spanners,
        "precisions": precisions,
        "columns_with_uncertainty": sum(col_has_unc),
        "packages": list(REQUIRED_PACKAGES),
    }
    return LatexTable(
        tabular=tabular,
        table_env=table_env,
        column_format=column_format,
        provenance=prov,
    )


def _inject_row_groups(tabular: str, matrix) -> str:
    """Insert ``\\emph{group}`` sub-header rows and \\quad-indent grouped rows.

    Styler emits one body line per matrix row in order, so we map body rows to
    ``matrix.rows`` positionally (robust to label escaping) and splice group
    headers in where the group changes. Ungrouped rows (e.g. a hindsight upper
    bound) stay flush-left with no header.
    """
    ncols = 1 + len(matrix.columns)
    lines = tabular.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == r"\midrule") + 1
        end = next(i for i, ln in enumerate(lines) if ln.strip() == r"\bottomrule")
    except StopIteration:
        return tabular
    body = lines[start:end]
    data_positions = [i for i, ln in enumerate(body) if ln.rstrip().endswith(r"\\")]
    out: list[str] = []
    prev_group: str | None = None
    for k, bi in enumerate(data_positions):
        line = body[bi]
        grp = matrix.row_group.get(matrix.rows[k]) if k < len(matrix.rows) else None
        if grp and grp != prev_group:
            out.append(
                rf"\multicolumn{{{ncols}}}{{l}}{{\emph{{{_tex_escape(grp)}}}}} \\"
            )
        if grp:
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            out.append(rf"{indent}\quad {stripped}")
        else:
            out.append(line)
        if grp:
            prev_group = grp
    return "\n".join(lines[:start] + out + lines[end:])


def _inject_row_header(tabular: str, row_header: str) -> str:
    """Place the row-axis label in the last header row's empty corner."""
    lines = tabular.splitlines()
    esc = _tex_escape(row_header)
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        if stripped.startswith("& ") and r"\midrule" in "\n".join(lines[i : i + 2]):
            indent = ln[: len(ln) - len(stripped)]
            lines[i] = f"{indent}{esc} {stripped}"
            break
    return "\n".join(lines)


def _wrap_table_env(
    tabular: str, *, caption: str, label: str, notes: list[str], placement: str
) -> str:
    note_block = ""
    if notes:
        items = "\n".join(rf"    \item {n}" for n in notes)
        note_block = (
            "  \\begin{tablenotes}[flushleft]\\footnotesize\n"
            f"{items}\n  \\end{{tablenotes}}\n"
        )
    body = (
        "  \\begin{threeparttable}\n"
        + _indent(tabular, 2)
        + "\n"
        + note_block
        + "  \\end{threeparttable}"
    )
    return (
        f"\\begin{{table}}[{placement}]\n"
        "  \\centering\n"
        f"  \\caption{{{caption}}}\n"
        f"  \\label{{{label}}}\n"
        f"{body}\n"
        "\\end{table}\n"
    )


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + ln if ln.strip() else ln for ln in text.splitlines())
