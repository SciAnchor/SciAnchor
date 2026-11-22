"""Read-only manuscript measurement (P-7).

Produces comparable numbers for a produced manuscript bundle so that
reconnaissance runs yield a baseline instead of hand-counted anecdotes.

Deliberate boundaries:

* Measurement only. This module has no thresholds, emits no verdict, and is
  never consulted by a gate. Floors belong to the orchestrator invariants and
  are set from venue statistics after the reconnaissance runs, not here.
* Read-only. No mutation, no network, no LLM.
* Asset count and narrative-reference count are reported as SEPARATE numbers.
  Conflating them is the exact defect this module exists to expose: a
  manuscript can carry six figure assets while the prose references none.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

MANUSCRIPT_MEASURE_SCHEMA = "rh.schema.report.manuscript_measure.v1"

_SECTION_RE = re.compile(r"\\section\*?\{([^}]*)\}")
_CITE_RE = re.compile(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]+)\}")
_FIGURE_ENV_RE = re.compile(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", re.DOTALL)
_TABLE_ENV_RE = re.compile(r"\\begin\{table\*?\}", re.DOTALL)
_GRAPHIC_RE = re.compile(r"\\includegraphics|\\begin\{tikzpicture\}|\\pgfplotsset")
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_REF_RE = re.compile(r"\\(?:auto|c|C)?ref\*?\{([^}]+)\}")
_BIB_ENTRY_RE = re.compile(r"^\s*@\w+\s*\{\s*([^,\s]+)", re.MULTILINE)

# Body extraction: drop the preamble and float/tabular internals so word counts
# reflect prose, not markup or table cells.
_PREAMBLE_RE = re.compile(r"^.*?\\begin\{document\}", re.DOTALL)
_END_DOC_RE = re.compile(r"\\end\{document\}.*$", re.DOTALL)
_FLOAT_BLOCK_RE = re.compile(
    r"\\begin\{(figure\*?|table\*?|tabular[x*]?|algorithm\*?)\}.*?"
    r"\\end\{\1\}",
    re.DOTALL,
)
_COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.MULTILINE)
_MACRO_RE = re.compile(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])*(?:\{[^{}]*\})*")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


def _strip_to_body(tex_source: str) -> str:
    body = _PREAMBLE_RE.sub("", tex_source)
    body = _END_DOC_RE.sub("", body)
    return _COMMENT_RE.sub("", body)


def _prose_words(tex_source: str) -> int:
    body = _strip_to_body(tex_source)
    body = _FLOAT_BLOCK_RE.sub(" ", body)
    body = _MACRO_RE.sub(" ", body)
    return len(_WORD_RE.findall(body))


def _split_keys(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


def _figure_assets(tex_source: str) -> int:
    """Count figures that render real graphic content.

    Mirrors the semantics already used by the orchestrator invariants: a
    figure environment counts when it contains graphic content, and standalone
    graphics outside any figure environment count individually.
    """
    in_env = sum(
        1
        for match in _FIGURE_ENV_RE.finditer(tex_source)
        if _GRAPHIC_RE.search(match.group(0))
    )
    outside = _FIGURE_ENV_RE.sub("", tex_source)
    return in_env + len(_GRAPHIC_RE.findall(outside))


def measure_tex_source(tex_source: str) -> dict[str, Any]:
    """Measure a single LaTeX source string. Pure function."""
    body = _strip_to_body(tex_source)

    sections = [s.strip() for s in _SECTION_RE.findall(body)]

    cite_instances = _CITE_RE.findall(tex_source)
    citation_keys: list[str] = []
    citation_instance_count = 0
    for raw in cite_instances:
        keys = _split_keys(raw)
        citation_instance_count += len(keys)
        citation_keys.extend(keys)
    unique_keys = sorted(set(citation_keys))

    # Figure label / narrative-reference semantics are defined ONCE, in the
    # orchestrator invariants, and delegated to here. Two same-named metrics
    # with subtly different definitions is precisely the defect this module
    # exists to expose, so it must not be reintroduced by measuring twice.
    from research_harness._workflow.orchestrator.invariants import (
        _tex_figure_label_keys,
        _tex_narrative_reference_keys,
    )

    figure_labels = _tex_figure_label_keys(tex_source)
    referenced = _tex_narrative_reference_keys(tex_source) & figure_labels

    return {
        "total_words": _prose_words(tex_source),
        "sections": sections,
        "section_count": len(sections),
        "citation_instance_count": citation_instance_count,
        "unique_citation_keys": len(unique_keys),
        "citation_keys": unique_keys,
        "figure_asset_count": _figure_assets(tex_source),
        "figure_label_count": len(figure_labels),
        "figure_narrative_reference_count": len(referenced),
        "unreferenced_figure_labels": sorted(figure_labels - referenced),
        "table_count": len(_TABLE_ENV_RE.findall(tex_source)),
    }


def _pick_tex(bundle_dir: Path) -> Path:
    candidates = sorted(bundle_dir.glob("*.tex"))
    if not candidates:
        raise FileNotFoundError(f"no .tex file found in {bundle_dir}")
    for preferred in ("main.tex", "paper.tex"):
        for path in candidates:
            if path.name == preferred:
                return path
    return candidates[0]


def measure_manuscript_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Measure a produced manuscript directory. Read-only."""
    root = Path(bundle_dir)
    tex_path = _pick_tex(root)
    tex_source = tex_path.read_text(encoding="utf-8", errors="replace")
    measurements = measure_tex_source(tex_source)

    bib_keys: set[str] = set()
    bib_files = sorted(root.glob("*.bib"))
    for bib in bib_files:
        raw = bib.read_text(encoding="utf-8", errors="replace")
        bib_keys.update(_BIB_ENTRY_RE.findall(raw))

    cited = set(measurements["citation_keys"])
    pdf_files = sorted(root.glob("*.pdf"))

    return {
        "schema": MANUSCRIPT_MEASURE_SCHEMA,
        "bundle_dir": str(root),
        "tex_file": str(tex_path),
        "bib_files": [str(p) for p in bib_files],
        "bib_entry_count": len(bib_keys),
        "cited_keys_missing_from_bib": sorted(cited - bib_keys) if bib_keys else [],
        "bib_entries_never_cited": sorted(bib_keys - cited) if bib_keys else [],
        "pdf_files": [str(p) for p in pdf_files],
        "measurements": measurements,
    }
