from __future__ import annotations

from research_harness.medical_screening import screening_row
from research_harness.paper_sources import PaperRecord


def test_screening_row_classifies_systematic_review_and_maternal_tags() -> None:
    record = PaperRecord(
        title="Heat exposure and pregnancy outcomes",
        abstract="A systematic review of heat exposure and preterm birth.",
        year=2025,
        doi="10.1289/example",
        pmid="12345678",
        pmcid="PMC1234567",
        venue="Environmental Health Perspectives",
        concepts=[
            {
                "source": "pubmed",
                "kind": "publication_type",
                "display_name": "Systematic Review",
            },
            {
                "source": "pubmed",
                "kind": "mesh",
                "display_name": "Pregnancy Outcome",
                "major_topic": True,
            },
        ],
    )

    row = screening_row(record)

    assert row.evidence_type == "systematic_review"
    assert "heat" in row.exposure_tags
    assert "pregnancy" in row.life_stage_tags
    assert "preterm_birth" in row.outcome_tags
    assert row.priority_tier == "high"
    assert row.journal_quartile_status == "needs_external_verification"
