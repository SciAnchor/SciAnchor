"""Standalone results-table renderer for Research Harness.

Turns evidence-bound experiment records into reviewer-standard LaTeX tables
(booktabs + siunitx via pandas Styler) plus polished Great Tables PNG previews.
Schema-compatible with the RH experiment-figure renderer so it can fold back in.
"""

from .aggregate import Cell, Column, ResultMatrix, build_matrix
from .contracts import (
    TABLE_FIELD_REQUIREMENTS,
    canonical_table_kind,
    table_field_requirements,
)
from .latexify import LatexTable, matrix_to_latex
from .markdownify import matrix_to_markdown
from .records import clean_records
from .render import ResultTableArtifact, render_results_table
from .stats import ColumnStats, analyze_column

__all__ = [
    "render_results_table",
    "ResultTableArtifact",
    "build_matrix",
    "matrix_to_latex",
    "LatexTable",
    "matrix_to_markdown",
    "ResultMatrix",
    "Cell",
    "Column",
    "ColumnStats",
    "analyze_column",
    "clean_records",
    "table_field_requirements",
    "canonical_table_kind",
    "TABLE_FIELD_REQUIREMENTS",
]
