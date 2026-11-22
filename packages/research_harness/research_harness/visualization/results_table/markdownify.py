"""Markdown export (borrowed from exptab's to_markdown idea).

A GitHub-flavored table for READMEs / issues / PR discussions: **bold** for the
best and statistically-tied results, *italic* for the runner-up (Markdown has no
underline). Spanners are flattened to "group metric" headers.
"""

from __future__ import annotations

from .aggregate import ResultMatrix


def _plain_cell(cell, precision: int = 2, show_uncertainty: bool = True) -> str:
    if not cell.present:
        return "—"
    if cell.display is not None:
        return cell.display
    if cell.mean is None:
        return "—"
    if show_uncertainty and cell.std is not None:
        return f"{cell.mean:.{precision}f} ± {cell.std:.{precision}f}"
    return f"{cell.mean:.{precision}f}"


def matrix_to_markdown(
    matrix: ResultMatrix,
    *,
    row_header: str = "Method",
    precision: int = 2,
    show_uncertainty: bool = True,
) -> str:
    headers = [row_header]
    for col in matrix.columns:
        headers.append(f"{col.group} {col.metric}".strip() if col.group else col.metric)

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in matrix.rows:
        group = matrix.row_group.get(row)
        label = f"_{group}_ · {row}" if group else row
        cells = [label]
        for i in range(len(matrix.columns)):
            c = matrix.cell(row, i)
            txt = _plain_cell(c, precision, show_uncertainty)
            if c.is_best or c.is_tied_best:
                txt = f"**{txt}**"
            elif c.is_second:
                txt = f"*{txt}*"
            cells.append(txt)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
