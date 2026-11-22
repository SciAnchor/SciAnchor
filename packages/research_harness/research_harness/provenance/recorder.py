"""Compatibility shim for the core provenance recorder."""

from __future__ import annotations

from research_harness._core.provenance.recorder import (
    ProvenanceRecorder,
    RecordedPrimitiveResult,
)

__all__ = ["ProvenanceRecorder", "RecordedPrimitiveResult"]
