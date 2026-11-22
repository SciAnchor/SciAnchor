"""SPC 1.0 论文事实契约。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from paperfetch.artifacts.models import ArtifactPointer
from paperfetch.core.contracts_v1 import ErrorInfo
from paperfetch.papers.models import (
    BibliographicMetadata,
    FieldProvenance,
    FulltextState,
    IdentifierSet,
    IdentityVerification,
    MetadataProvenance,
    PaperRecord,
    ParseTerminal,
    PdfTerminal,
    SourceSnapshot,
    new_paper_id,
)


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _provenance(*fields: str) -> MetadataProvenance:
    return MetadataProvenance(
        sources=[
            SourceSnapshot(source_id="src-1", source="crossref", record_id="record-1")
        ],
        fields=[FieldProvenance(field=field, source_ids=["src-1"]) for field in fields],
    )


def _pointer(kind: str) -> ArtifactPointer:
    artifact_id = f"art_{'a' if kind == 'paper_pdf' else 'b'}" + "0" * 31
    category = "pdf" if kind == "paper_pdf" else "fulltext"
    return ArtifactPointer(
        artifact_id=artifact_id,
        kind=kind,
        manifest_path=f"artifacts/spc_{'1' * 32}/{category}/{artifact_id}/manifest.json",
    )


def test_identifier_set_normalizes_only_strong_identifiers():
    identifiers = IdentifierSet(
        doi="HTTPS://DOI.ORG/10.1000/Example",
        pubmed_id=" 12345 ",
        pmc_id="pmc12345",
        arxiv_id="arXiv:2608.05733v2",
    )
    assert identifiers.model_dump() == {
        "doi": "10.1000/example",
        "pubmed_id": "12345",
        "pmc_id": "PMC12345",
        "arxiv_id": "2608.05733v2",
    }
    assert identifiers.canonical() == ("doi", "10.1000/example")


@pytest.mark.parametrize("payload", [{}, {"doi": "not-a-doi"}, {"pmc_id": "123"}])
def test_identifier_set_rejects_missing_or_invalid_values(payload):
    with pytest.raises(ValidationError):
        IdentifierSet(**payload)


def test_paper_requires_field_level_provenance_for_title_and_identifiers():
    with pytest.raises(ValidationError, match="missing provenance"):
        PaperRecord(
            paper_id=new_paper_id(),
            identifiers=IdentifierSet(doi="10.1000/example"),
            bibliographic=BibliographicMetadata(title="Example"),
            provenance=_provenance("bibliographic.title"),
        )


def test_paper_record_has_no_review_route_or_available_files_payload():
    record = PaperRecord(
        paper_id=new_paper_id(),
        identifiers=IdentifierSet(doi="10.1000/example"),
        bibliographic=BibliographicMetadata(title="  A   compact  title "),
        provenance=_provenance("identifiers.doi", "bibliographic.title"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    payload = record.model_dump(mode="json")
    assert payload["bibliographic"]["title"] == "A compact title"
    serialized = str(payload)
    for removed in (
        "agent_review",
        "available_files",
        "download_attempts",
        "route_errors",
        "primary_failure_class",
        "last_failure_class",
        "failure_taxonomy",
        "reproducibility_status",
    ):
        assert removed not in serialized


def test_fulltext_terminal_requires_verified_pdf_before_parse():
    paper_id = f"spc_{'1' * 32}"
    pdf = ArtifactPointer(
        artifact_id=f"art_{'a' * 32}",
        kind="paper_pdf",
        manifest_path=f"artifacts/{paper_id}/pdf/art_{'a' * 32}/manifest.json",
    )
    markdown = ArtifactPointer(
        artifact_id=f"art_{'b' * 32}",
        kind="mineru_fulltext",
        manifest_path=f"artifacts/{paper_id}/fulltext/art_{'b' * 32}/manifest.json",
    )
    state = FulltextState(
        pdf=PdfTerminal(
            status="available",
            artifact=pdf,
            identity=IdentityVerification(
                method="doi", target="10.1000/example", observed="10.1000/example"
            ),
        ),
        parse=ParseTerminal(status="available", artifact=markdown),
    )
    assert state.pdf.identity.verified is True
    with pytest.raises(ValidationError, match="requires an available verified PDF"):
        FulltextState(
            parse=ParseTerminal(
                status="failed",
                error=ErrorInfo(
                    code="mineru_artifact_tls_failed",
                    error_class="tls_error",
                    stage="parse.artifact_download",
                    retryable=True,
                    message="MinerU 制品下载失败",
                ),
            )
        )


def test_unknown_legacy_paper_fields_are_rejected():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PaperRecord(
            paper_id=new_paper_id(),
            identifiers=IdentifierSet(doi="10.1000/example"),
            bibliographic=BibliographicMetadata(title="Example"),
            provenance=_provenance("identifiers.doi", "bibliographic.title"),
            available_files={},
        )
