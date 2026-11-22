#!/usr/bin/env python3
"""Remove RH-generated PDF annotations from a paper."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

try:
    # `import fitz` prints a deprecation warning on stdout since PyMuPDF 1.28,
    # which corrupts this script's --json output; prefer the modern name.
    import pymupdf as fitz
except ImportError:  # pragma: no cover - import guard
    try:
        import fitz  # PyMuPDF < 1.24.3
    except Exception as exc:
        raise SystemExit("PyMuPDF is required: pip install pymupdf") from exc


DEFAULT_MARKERS = ("RH-PHD-v1", "RH-PHD-v2")


def _should_remove(info: dict[str, str], markers: tuple[str, ...]) -> bool:
    content = str(info.get("content") or "")
    return any(marker in content for marker in markers)


def reset_annotations(pdf_path: Path, out_path: Path, markers: tuple[str, ...]) -> dict[str, object]:
    doc = fitz.open(str(pdf_path))
    removed = 0
    kept = 0
    removed_subjects: list[str] = []

    for page in doc:
        annot = page.first_annot
        while annot:
            current = annot
            annot = annot.next
            info = current.info or {}
            if _should_remove(info, markers):
                removed += 1
                removed_subjects.append(str(info.get("subject") or ""))
                page.delete_annot(current)
            else:
                kept += 1

    if out_path == pdf_path:
        tmp = out_path.with_suffix(out_path.suffix + ".tmp-rh-reset")
        doc.save(str(tmp), garbage=4, deflate=True)
        doc.close()
        tmp.replace(out_path)
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path), garbage=4, deflate=True)
        doc.close()

    return {
        "status": "success",
        "pdf_path": str(pdf_path),
        "output_path": str(out_path),
        "markers": list(markers),
        "removed_count": removed,
        "kept_count": kept,
        "removed_subjects": removed_subjects,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, help="Input PDF path")
    parser.add_argument("--out", default="", help="Output PDF path; defaults to input when --in-place")
    parser.add_argument("--in-place", action="store_true", help="Modify PDF in place")
    parser.add_argument("--no-backup", action="store_true", help="Do not create backup for --in-place")
    parser.add_argument(
        "--marker",
        action="append",
        default=[],
        help="Annotation marker to remove. Repeat for multiple markers.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable receipt")
    args = parser.parse_args(argv)

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    markers = tuple(args.marker) if args.marker else DEFAULT_MARKERS

    if args.in_place:
        out_path = pdf_path
        if not args.no_backup:
            suffix = datetime.now().strftime("%Y%m%d%H%M%S")
            backup = pdf_path.with_name(pdf_path.name + f".bak-rh-reset-{suffix}")
            shutil.copy2(pdf_path, backup)
        else:
            backup = None
    else:
        if not args.out:
            raise SystemExit("Provide --out unless using --in-place")
        out_path = Path(args.out).expanduser().resolve()
        backup = None

    receipt = reset_annotations(pdf_path, out_path, markers)
    if backup is not None:
        receipt["backup_path"] = str(backup)

    if args.json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    else:
        print(
            f"Removed {receipt['removed_count']} RH annotations from {receipt['output_path']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
