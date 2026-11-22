"""Command-line entry (borrowed from exptab's one-command ergonomics).

    python -m results_table results.csv                 # LaTeX + Markdown + previews
    python -m results_table results.json --md -o out/
    python -m results_table results.csv --lower-is-better --caption "Main results"

CSV: a ``method`` column (or first column) + one column per metric; multiple
rows per method are treated as repeated seeds (aggregated to mean +- std, with
autorank significance when >=5). JSON: ``{"Method": {"Metric": [v, ...]}}``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .render import render_results_table

_METHOD_KEYS = ("method", "model", "approach", "system", "name")


def _records_from_csv(path: Path, lower_is_better: bool) -> list[dict]:
    import csv

    rows = list(csv.DictReader(path.open()))
    if not rows:
        raise SystemExit(f"empty CSV: {path}")
    cols = list(rows[0].keys())
    method_col = next((c for c in cols if c.strip().lower() in _METHOD_KEYS), cols[0])
    metric_cols = [c for c in cols if c != method_col]
    recs = []
    for r in rows:
        for m in metric_cols:
            try:
                v = float(r[m])
            except (TypeError, ValueError):
                continue
            recs.append(
                {
                    "table_type": "main_results",
                    "method": r[method_col],
                    "metric": m,
                    "value": v,
                    "higher_is_better": not lower_is_better,
                }
            )
    return recs


def _records_from_json(path: Path, lower_is_better: bool) -> list[dict]:
    data = json.loads(path.read_text())
    recs = []
    for method, metrics in data.items():
        for metric, vals in metrics.items():
            seq = vals if isinstance(vals, (list, tuple)) else [vals]
            for v in seq:
                recs.append(
                    {
                        "table_type": "main_results",
                        "method": method,
                        "metric": metric,
                        "value": float(v),
                        "higher_is_better": not lower_is_better,
                    }
                )
    return recs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="results_table", description="Experiment records -> publication table."
    )
    ap.add_argument("input", type=Path, help="results .csv or .json")
    ap.add_argument("-o", "--output-dir", type=Path, default=Path("."))
    ap.add_argument("--id", default=None, help="table id / output stem")
    ap.add_argument("--caption", default="")
    ap.add_argument("--label", default=None)
    ap.add_argument("--lower-is-better", action="store_true")
    ap.add_argument(
        "--no-autorank", action="store_true", help="disable autorank backend"
    )
    ap.add_argument("--no-preview", action="store_true", help="skip PDF/PNG previews")
    ap.add_argument("--md-only", action="store_true", help="print Markdown and exit")
    args = ap.parse_args(argv)

    if not args.input.exists():
        raise SystemExit(f"not found: {args.input}")
    load = (
        _records_from_json
        if args.input.suffix.lower() == ".json"
        else _records_from_csv
    )
    records = load(args.input, args.lower_is_better)
    table_id = args.id or args.input.stem

    art = render_results_table(
        records=records,
        table_type="main_results",
        output_dir=args.output_dir,
        table_id=table_id,
        caption=args.caption,
        label=args.label,
        use_autorank=not args.no_autorank,
        make_pdf=not args.no_preview,
        make_gt=not args.no_preview,
    )
    if args.md_only:
        sys.stdout.write(Path(art.paths["md"]).read_text())
        return 0
    print(
        f"[{art.status}] {table_id}: "
        f"{art.provenance.get('rows')}x{art.provenance.get('columns')} cells, "
        f"stats={art.provenance.get('stats_backend')}"
    )
    for k, v in art.paths.items():
        print(f"  {k:9} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
