"""Top-level results-table render (mirrors render_experiment_figure_suite).

records -> matrix -> LaTeX (.tex) -> tectonic PDF/PNG (ground truth)
                                  -> Great Tables PNG (polished preview)
plus a provenance block recording evidence boundary, coverage, and best cells.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .aggregate import build_matrix
from .latexify import matrix_to_latex
from .preview import compile_latex, great_tables_png
from .records import clean_records


@dataclass
class ResultTableArtifact:
    table_id: str
    title: str
    table_type: str
    status: str
    paths: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


def render_results_table(
    *,
    records: Sequence[Mapping[str, Any]],
    table_type: str,
    output_dir: str | Path,
    table_id: str = "results",
    caption: str = "",
    label: str | None = None,
    row_header: str = "Method",
    notes: list[str] | None = None,
    show_uncertainty: bool = True,
    raw_cells: bool = False,
    raw_headers: bool = False,
    direction_arrows: bool = False,
    make_pdf: bool = True,
    make_gt: bool = True,
    rows_order: Sequence[str] | None = None,
    columns_order: Sequence[str] | None = None,
    groups_order: Sequence[str] | None = None,
    mark_ties: bool = True,
    mark_second: bool = True,
    use_autorank: bool = True,
    alpha: float = 0.05,
) -> ResultTableArtifact:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    label = label or f"tab:{table_id}"

    cleaned = clean_records(records)
    matrix = build_matrix(
        cleaned,
        table_type=table_type,
        rows_order=rows_order,
        columns_order=columns_order,
        groups_order=groups_order,
        mark_ties=mark_ties,
        mark_second=mark_second,
        use_autorank=use_autorank,
        alpha=alpha,
    )
    if not matrix.rows or not matrix.columns:
        return ResultTableArtifact(
            table_id=table_id,
            title=caption,
            table_type=matrix.table_type,
            status="empty",
            provenance={**matrix.provenance, "limitations": ["no_tabulatable_records"]},
        )

    default_notes = _default_notes(matrix, show_uncertainty)
    lt = matrix_to_latex(
        matrix,
        caption=caption or table_id,
        label=label,
        row_header=row_header,
        show_uncertainty=show_uncertainty,
        notes=notes if notes is not None else default_notes,
        raw_cells=raw_cells,
        raw_headers=raw_headers,
        direction_arrows=direction_arrows,
    )

    paths: dict[str, str] = {}
    tex_path = out / f"{table_id}.tex"
    tex_path.write_text(lt.table_env, encoding="utf-8")
    paths["tex"] = str(tex_path)
    preamble_path = out / f"{table_id}.preamble.tex"
    preamble_path.write_text(
        "\n".join(lt.preamble_packages) + "\n" + lt.sisetup + "\n", encoding="utf-8"
    )
    paths["preamble"] = str(preamble_path)

    from .markdownify import matrix_to_markdown

    md_path = out / f"{table_id}.md"
    md_path.write_text(
        matrix_to_markdown(
            matrix, row_header=row_header, show_uncertainty=show_uncertainty
        ),
        encoding="utf-8",
    )
    paths["md"] = str(md_path)

    preview: dict[str, Any] = {}
    if make_pdf:
        pr = compile_latex(lt, out, table_id, to_png=True)
        preview["latex"] = {
            "status": pr.status,
            "backend": pr.backend,
            "reason": pr.reason,
        }
        if pr.status == "ok" and pr.path:
            key = "png" if pr.path.endswith(".png") else "pdf"
            paths[key] = pr.path
    if make_gt:
        gr = great_tables_png(
            matrix, out, table_id, title=caption, show_uncertainty=show_uncertainty
        )
        preview["great_tables"] = {"status": gr.status, "reason": gr.reason}
        if gr.status == "ok" and gr.path:
            paths["gt_png"] = gr.path

    provenance = {
        **matrix.provenance,
        "latex": lt.provenance,
        "preview": preview,
        "column_format": lt.column_format,
        "notes": lt.provenance.get(
            "notes", notes if notes is not None else default_notes
        ),
    }
    return ResultTableArtifact(
        table_id=table_id,
        title=caption or table_id,
        table_type=matrix.table_type,
        status="rendered",
        paths=paths,
        provenance=provenance,
    )


def _default_notes(matrix, show_uncertainty: bool) -> list[str]:
    notes: list[str] = []
    if show_uncertainty and any(
        matrix.cell(r, i).std is not None
        for r in matrix.rows
        for i in range(len(matrix.columns))
    ):
        notes.append(r"Values are mean $\pm$ standard deviation over repeated runs.")
    if any(c.is_best for c in matrix.cells.values()):
        tests = sorted(
            {
                s.get("test", "")
                for s in matrix.provenance.get("column_stats", [])
                if s.get("backend") == "autorank" and s.get("test")
            }
        )
        tie_clause = (
            "results statistically indistinguishable from the best "
            + (f"({', '.join(tests)}) " if tests else "")
            + "are also in bold"
        )
        second_clause = (
            "; the runner-up is underlined"
            if any(c.is_second for c in matrix.cells.values())
            else ""
        )
        notes.append(
            rf"\textbf{{Best}} result per column in bold; {tie_clause}{second_clause}."
        )
    if matrix.provenance.get("missing_cells"):
        notes.append(r"``--'' denotes a configuration with no recorded result.")
    return notes
