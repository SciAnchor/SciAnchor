"""Compatibility shim for :mod:`research_harness._core.provenance.models`."""

from research_harness._core.provenance.models import (
    ProvenanceRecord,
    ProvenanceSummary,
)

__all__ = ["ProvenanceRecord", "ProvenanceSummary"]
