from __future__ import annotations

from pathlib import Path

from research_harness.acquisition.pdf_audit import audit_pdf_identity


def test_pdf_audit_verifies_matching_doi_with_injected_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    result = audit_pdf_identity(
        paper_id=1,
        title="Climate change and pregnancy outcomes",
        doi="10.1289/example",
        pmid="12345678",
        pdf_path=str(pdf_path),
        text_extractor=lambda _: (
            "Climate change and pregnancy outcomes DOI 10.1289/example"
        ),
    )

    assert result.status == "verified"
    assert result.doi_match is True


def test_pdf_audit_marks_unrelated_pdf_suspect_with_injected_text(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "wrong.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    result = audit_pdf_identity(
        paper_id=1,
        title="Climate change and pregnancy outcomes",
        doi="10.1289/example",
        pmid="12345678",
        pdf_path=str(pdf_path),
        text_extractor=lambda _: "EPA climate adaptation plan for infrastructure",
    )

    assert result.status == "suspect"
    assert "no title/DOI/PMID signal" in result.reason


def test_pdf_audit_does_not_verify_from_generic_climate_health_words(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "wrong-generic.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    result = audit_pdf_identity(
        paper_id=18,
        title="The Effects of Climate Change on Obstetric and Gynecologic Health.",
        doi="10.1097/AOG.0000000000006290",
        pmid="42314205",
        pdf_path=str(pdf_path),
        text_extractor=lambda _: (
            "U.S. Environmental Protection Agency climate adaptation action plan. "
            "This document discusses effects of climate change on public health."
        ),
    )

    assert result.status == "suspect"
    assert result.doi_match is False
    assert result.pmid_match is False
