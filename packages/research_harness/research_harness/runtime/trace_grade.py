"""Compatibility shim for core runtime trace grading."""

from __future__ import annotations

from research_harness._core.runtime.trace_grade import (
    RUNTIME_TRACE_GRADE_SCHEMA,
    grade_run_trace,
)

__all__ = ["RUNTIME_TRACE_GRADE_SCHEMA", "grade_run_trace"]
