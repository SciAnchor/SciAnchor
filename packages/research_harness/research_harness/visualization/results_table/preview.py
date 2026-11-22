"""Preview / QA renders for a result table.

Two independent, best-effort backends:

- ``compile_latex`` -- the GROUND TRUTH: compile the emitted booktabs+siunitx
  LaTeX with tectonic to a PDF (optionally rasterized to PNG). This proves the
  reviewer-facing artifact actually typesets, alignment and all.
- ``great_tables_png`` -- a polished bitmap preview via Great Tables (the
  user-selected second engine), for quick visual QA without a TeX toolchain.

Both degrade gracefully: a missing toolchain yields ``status != "ok"`` and a
reason, never an exception that sinks the render.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .aggregate import ResultMatrix
from .latexify import LatexTable


@dataclass
class PreviewResult:
    status: str
    path: str | None = None
    reason: str | None = None
    backend: str = ""


def _standalone_doc(table: LatexTable) -> str:
    pkgs = "\n".join(p for p in table.preamble_packages)
    return (
        "\\documentclass[border=8pt,varwidth=\\maxdimen]{standalone}\n"
        f"{pkgs}\n{table.sisetup}\n"
        "\\begin{document}\n"
        "\\begin{threeparttable}\n"
        f"{table.tabular}\n"
        "\\end{threeparttable}\n"
        "\\end{document}\n"
    )


def compile_latex(
    table: LatexTable, out_dir: str | Path, stem: str, *, to_png: bool = True
) -> PreviewResult:
    tectonic = shutil.which("tectonic")
    if not tectonic:
        return PreviewResult(
            status="skipped", reason="tectonic_not_found", backend="tectonic"
        )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tex_path = out / f"{stem}.standalone.tex"
    tex_path.write_text(_standalone_doc(table), encoding="utf-8")
    try:
        proc = subprocess.run(
            [
                tectonic,
                "-X",
                "compile",
                "--outdir",
                str(out),
                str(tex_path),
                "--keep-logs",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception:  # pragma: no cover - toolchain edge
        # older tectonic without the -X subcommand form
        proc = subprocess.run(
            [tectonic, "--outdir", str(out), str(tex_path)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    pdf_path = out / f"{stem}.standalone.pdf"
    if not pdf_path.exists():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
        return PreviewResult(
            status="error",
            reason="; ".join(tail) or "compile_failed",
            backend="tectonic",
        )
    if not to_png:
        return PreviewResult(status="ok", path=str(pdf_path), backend="tectonic")
    png = _pdf_to_png(pdf_path, out / f"{stem}.png")
    if png:
        return PreviewResult(status="ok", path=str(png), backend="tectonic+raster")
    return PreviewResult(
        status="ok",
        path=str(pdf_path),
        reason="pdf_only_no_rasterizer",
        backend="tectonic",
    )


def _pdf_to_png(pdf: Path, png: Path) -> Path | None:
    if shutil.which("pdftoppm"):
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                "300",
                "-singlefile",
                str(pdf),
                str(png.with_suffix("")),
            ],
            capture_output=True,
        )
        return png if png.exists() else None
    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        subprocess.run(
            [magick, "-density", "300", str(pdf), "-quality", "100", str(png)],
            capture_output=True,
        )
        return png if png.exists() else None
    return None


# --------------------------------------------------------------------------- #
# Great Tables polished PNG                                                    #
# --------------------------------------------------------------------------- #


def great_tables_png(
    matrix: ResultMatrix,
    out_dir: str | Path,
    stem: str,
    *,
    title: str = "",
    subtitle: str = "",
    show_uncertainty: bool = True,
) -> PreviewResult:
    try:
        from great_tables import GT, style, loc
    except Exception as exc:  # pragma: no cover
        return PreviewResult(
            status="skipped",
            reason=f"great_tables_import:{exc}",
            backend="great_tables",
        )

    import pandas as pd

    def disp(cell) -> str:
        if not cell.present:
            return "—"  # em dash
        if cell.display is not None:
            return cell.display
        if cell.mean is None:
            return "—"
        p = 2
        if show_uncertainty and cell.std is not None:
            return f"{cell.mean:.{p}f} ± {cell.std:.{p}f}"
        return f"{cell.mean:.{p}f}"

    row_key = "__row__"
    col_ids = [f"c{i}" for i in range(len(matrix.columns))]
    frame = {row_key: list(matrix.rows)}
    for i, cid in enumerate(col_ids):
        frame[cid] = [disp(matrix.cell(r, i)) for r in matrix.rows]
    df = pd.DataFrame(frame)

    gt = GT(df, rowname_col=row_key)
    if title:
        gt = (
            gt.tab_header(title=title, subtitle=subtitle)
            if subtitle
            else gt.tab_header(title=title)
        )
    # column labels + spanners
    gt = gt.cols_label(
        **{cid: matrix.columns[i].metric for i, cid in enumerate(col_ids)}
    )
    seen_groups: dict[str, list[str]] = {}
    for i, col in enumerate(matrix.columns):
        if col.group:
            seen_groups.setdefault(col.group, []).append(col_ids[i])
    for gname, cids in seen_groups.items():
        gt = gt.tab_spanner(label=gname, columns=cids)
    # bold best/tied cells; underline runner-up (clean in a bitmap, unlike siunitx)
    for i, cid in enumerate(col_ids):
        best_rows = [
            j
            for j, r in enumerate(matrix.rows)
            if matrix.cell(r, i).is_best or matrix.cell(r, i).is_tied_best
        ]
        if best_rows:
            gt = gt.tab_style(
                style=style.text(weight="bold"),
                locations=loc.body(columns=cid, rows=best_rows),
            )
        second_rows = [
            j for j, r in enumerate(matrix.rows) if matrix.cell(r, i).is_second
        ]
        if second_rows:
            try:
                gt = gt.tab_style(
                    style=style.text(decorate="underline"),
                    locations=loc.body(columns=cid, rows=second_rows),
                )
            except Exception:
                gt = gt.tab_style(
                    style=style.text(style="italic"),
                    locations=loc.body(columns=cid, rows=second_rows),
                )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    png = out / f"{stem}.gt.png"
    saver = getattr(gt, "gtsave", None) or getattr(gt, "save")
    try:
        saver(str(png))
    except Exception as exc:
        return PreviewResult(
            status="skipped", reason=f"gt_save:{exc}", backend="great_tables"
        )
    return PreviewResult(status="ok", path=str(png), backend="great_tables")
