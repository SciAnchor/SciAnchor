"""Reusable Research Harness visualization helpers."""

# Results-table renderer (folded from tools4rh). Optional heavy deps
# (great_tables, autorank, jinja2) are only needed for PNG preview /
# stats backends — LaTeX path works with pandas+numpy.
try:
    from research_harness.visualization.results_table import (  # noqa: F401
        ResultTableArtifact,
        render_results_table,
        table_field_requirements,
    )
except ImportError:  # pragma: no cover - optional stack missing
    pass
