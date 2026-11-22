#!/usr/bin/env python3
"""Normalize deliverable PDFs for maximal reader compatibility.

tectonic/xdvipdfmx emits PDF 1.5 object streams. Preview and poppler read
them fine, but WPS (and some journal submission portals) fail to resolve the
page tree and render the document as a 1%-zoom sliver. This rewrites each PDF
without object streams, with a compacted xref, changing no page content.

Run after every compile of a deliverable bundle:

    python scripts/normalize-deliverable-pdf.py deliverables/*/main.pdf
    python scripts/normalize-deliverable-pdf.py --check deliverables/*/main.pdf
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - dependency is in the RH venv
    sys.exit("PyMuPDF is required: pip install pymupdf")


def uses_object_streams(path: Path) -> bool:
    """True when the file carries /ObjStm — the structure WPS chokes on."""
    return b"/ObjStm" in path.read_bytes()


def normalize(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    before = path.stat().st_size
    if not uses_object_streams(path):
        return False, f"already compatible ({before // 1024}KB)"
    doc = fitz.open(path)
    pages = doc.page_count
    tmp = path.with_suffix(".normalizing.pdf")
    doc.save(tmp, garbage=4, deflate=True, clean=True, use_objstms=0)
    doc.close()
    shutil.move(tmp, path)
    after = path.stat().st_size
    # re-open as a sanity gate: a normalized file that cannot be parsed is worse
    check = fitz.open(path)
    ok = check.page_count == pages
    check.close()
    if not ok:
        return False, "REWRITE CHANGED PAGE COUNT — investigate"
    return True, f"{pages}p {before // 1024}KB -> {after // 1024}KB"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("--check", action="store_true",
                    help="report only; exit 1 if any file needs normalizing")
    args = ap.parse_args()

    needs_work = 0
    for p in args.pdfs:
        if args.check:
            bad = p.exists() and uses_object_streams(p)
            needs_work += bad
            print(f"{'NEEDS-NORMALIZE' if bad else 'ok'}  {p}")
        else:
            changed, note = normalize(p)
            print(f"{'normalized' if changed else 'skipped'}  {p}  ({note})")
            if note.startswith("REWRITE"):
                needs_work += 1
    return 1 if (args.check and needs_work) else 0


if __name__ == "__main__":
    sys.exit(main())
