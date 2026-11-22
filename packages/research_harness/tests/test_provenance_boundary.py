from __future__ import annotations


def test_provenance_models_are_core_canonical_and_public_path_reexports() -> None:
    from research_harness._core.provenance.models import ProvenanceRecord
    from research_harness._core.provenance.models import ProvenanceSummary
    from research_harness.provenance.models import ProvenanceRecord as PublicRecord
    from research_harness.provenance.models import ProvenanceSummary as PublicSummary

    assert PublicRecord is ProvenanceRecord
    assert PublicSummary is ProvenanceSummary


def test_provenance_recorder_is_core_canonical_and_public_path_reexports() -> None:
    from research_harness._core.provenance.recorder import ProvenanceRecorder
    from research_harness.provenance.recorder import (
        ProvenanceRecorder as PublicRecorder,
    )

    assert PublicRecorder is ProvenanceRecorder
