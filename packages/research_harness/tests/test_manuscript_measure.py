"""Tests for the read-only manuscript measurement harness (P-7).

This measures a produced manuscript bundle so the 5-paper reconnaissance runs
yield comparable numbers instead of hand-counted anecdotes. It is measurement
only: it must never gate, never mutate, and never require an LLM.
"""

from __future__ import annotations

import json

import pytest

from research_harness.reports.manuscript_measure import (
    MANUSCRIPT_MEASURE_SCHEMA,
    measure_manuscript_bundle,
    measure_tex_source,
)


SAMPLE_TEX = r"""
\documentclass{article}
\begin{document}

\section{Introduction}
Prior work established the baseline \cite{smith2024}. Later work extended it
\cite{jones2023,liu2025}. See Figure~\ref{fig:arch} for the architecture.

\section{Method}
We build on \cite{smith2024} again and add a component \citep{wu2026}.

\begin{figure}[t]
\includegraphics[width=\linewidth]{arch.png}
\caption{Architecture.}
\label{fig:arch}
\end{figure}

\begin{figure}[t]
\includegraphics[width=\linewidth]{results.png}
\caption{Results.}
\label{fig:results}
\end{figure}

\begin{table}[t]
\begin{tabular}{lr}
Method & Score \\
Ours & 0.91 \\
\end{tabular}
\caption{Scores.}
\label{tab:scores}
\end{table}

\end{document}
"""


def test_schema_id_is_stable() -> None:
    assert MANUSCRIPT_MEASURE_SCHEMA == "rh.schema.report.manuscript_measure.v1"


def test_word_count_excludes_preamble_and_markup() -> None:
    m = measure_tex_source(SAMPLE_TEX)
    # Body prose only — must not count \documentclass, tabular cells, etc.
    assert 20 < m["total_words"] < 80, m["total_words"]


def test_sections_are_listed_in_order() -> None:
    m = measure_tex_source(SAMPLE_TEX)
    assert m["sections"] == ["Introduction", "Method"]
    assert m["section_count"] == 2


def test_unique_citation_keys_are_deduplicated() -> None:
    m = measure_tex_source(SAMPLE_TEX)
    # Fixture cites: smith2024, {jones2023,liu2025}, smith2024 again, wu2026.
    # => 5 instances, 4 distinct keys. Deduplication is the point: a draft that
    # cites the same three papers everywhere must not look well-sourced.
    assert m["citation_instance_count"] == 5
    assert m["unique_citation_keys"] == 4
    assert m["citation_keys"] == ["jones2023", "liu2025", "smith2024", "wu2026"]


def test_figure_assets_versus_narrative_references() -> None:
    m = measure_tex_source(SAMPLE_TEX)
    assert m["figure_asset_count"] == 2
    assert m["figure_label_count"] == 2
    # Only fig:arch is referenced from the body; fig:results is orphaned.
    assert m["figure_narrative_reference_count"] == 1
    assert m["unreferenced_figure_labels"] == ["fig:results"]


def test_table_count() -> None:
    m = measure_tex_source(SAMPLE_TEX)
    assert m["table_count"] == 1


def test_zero_figure_manuscript_is_measured_not_rejected() -> None:
    """The real topic-5 output had 0 figures and 0 tables — measurement must
    report that plainly rather than erroring or gating."""
    tex = r"""
\documentclass{article}
\begin{document}
\section{Introduction}
Some prose with one citation \cite{a2024}.
\end{document}
"""
    m = measure_tex_source(tex)
    assert m["figure_asset_count"] == 0
    assert m["table_count"] == 0
    assert m["unique_citation_keys"] == 1
    assert m["sections"] == ["Introduction"]


def test_measure_bundle_reads_tex_and_bib(tmp_path) -> None:
    (tmp_path / "paper.tex").write_text(SAMPLE_TEX, encoding="utf-8")
    (tmp_path / "references.bib").write_text(
        "@article{smith2024,\n title={A},\n}\n@article{jones2023,\n title={B},\n}\n",
        encoding="utf-8",
    )
    report = measure_manuscript_bundle(tmp_path)

    assert report["schema"] == MANUSCRIPT_MEASURE_SCHEMA
    assert report["tex_file"].endswith("paper.tex")
    assert report["bib_entry_count"] == 2
    # Cited-but-missing-from-bib is a real failure mode worth surfacing.
    assert report["cited_keys_missing_from_bib"] == ["liu2025", "wu2026"]
    assert report["measurements"]["figure_asset_count"] == 2


def test_measure_bundle_is_json_serialisable(tmp_path) -> None:
    (tmp_path / "paper.tex").write_text(SAMPLE_TEX, encoding="utf-8")
    report = measure_manuscript_bundle(tmp_path)
    json.dumps(report)  # must not raise


def test_missing_tex_raises_clear_error(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        measure_manuscript_bundle(tmp_path)
