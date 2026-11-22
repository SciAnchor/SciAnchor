"""SPC 1.0 下载 adapter 的边界、脱敏与稳定错误。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from paperfetch.fulltext.service import (
    DownloadRequest,
    PaperDownloadService,
    _download_error,
)
from paperfetch.core.models import FulltextStatus
from paperfetch.papers.models import (
    BibliographicMetadata,
    FieldProvenance,
    IdentifierSet,
    MetadataProvenance,
    PaperRecord,
    SourceSnapshot,
    new_paper_id,
)
from paperfetch.seedpacks.repository import SeedPackRepository


pytestmark = [pytest.mark.integration, pytest.mark.contract]


@pytest.mark.parametrize(
    ("error_class", "message_fragment", "retryable"),
    [
        ("network_error", "doctor --probe-traffic-classes", True),
        ("publisher_challenge", "自动验证", True),
        ("subscription_required", "未对当前凭证提供该资源的全文", False),
        ("unattended_auth_blocked", "人工确认", False),
        ("identity_mismatch", "身份不一致", False),
    ],
)
def test_download_failure_has_actionable_public_reason(
    error_class, message_fragment, retryable
):
    status = FulltextStatus(
        last_failure_class=error_class,
        failure_stage="pdf_transfer",
    )

    error = _download_error(status, audit_ref=None)

    assert error.code == error_class
    assert message_fragment in error.message
    assert error.retryable is retryable


def _paper() -> PaperRecord:
    now = datetime.now(timezone.utc)
    return PaperRecord(
        paper_id=new_paper_id(),
        identifiers=IdentifierSet(
            doi="10.1000/example", pubmed_id="123", pmc_id="PMC123"
        ),
        bibliographic=BibliographicMetadata(title="Example article"),
        provenance=MetadataProvenance(
            sources=[SourceSnapshot(source_id="src-1", source="test")],
            fields=[
                FieldProvenance(field="identifiers.doi", source_ids=["src-1"]),
                FieldProvenance(field="identifiers.pubmed_id", source_ids=["src-1"]),
                FieldProvenance(field="identifiers.pmc_id", source_ids=["src-1"]),
                FieldProvenance(field="bibliographic.title", source_ids=["src-1"]),
            ],
        ),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_adapter_materializes_only_identity_verified_pdf(
    monkeypatch, tmp_path: Path, make_pdf_bytes
):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    paper = _paper()
    repository.add([paper])
    source = tmp_path / "download.pdf"
    source.write_bytes(
        make_pdf_bytes(title=paper.bibliographic.title, doi=paper.identifiers.doi)
    )

    async def fake_download(_self, legacy):
        assert legacy.doi == paper.identifiers.doi
        legacy.fulltext_status = FulltextStatus(
            download_status="downloaded",
            download_attempted=True,
            resource_outcome="downloaded",
            local_path=str(source),
            magic_pdf=True,
            identity_verified=True,
            identity_status="verified_doi",
            identity_confidence="high",
            identity_evidence={
                "primary_dois": [paper.identifiers.doi],
                "discovered_dois": [paper.identifiers.doi],
            },
            successful_route="europe_pmc",
            discovery_events=[
                {
                    "source": "signed",
                    "url": "https://user:pass@example.org/file.pdf?token=secret&safe=yes",
                }
            ],
            download_attempts=[
                {
                    "route": "public_http",
                    "url": "https://example.org/file.pdf?X-Amz-Signature=secret",
                    "error": "Bearer super-secret-token-value",
                }
            ],
        )
        return legacy.fulltext_status

    async def fake_close(_self):
        return None

    monkeypatch.setattr(
        "paperfetch.fulltext.service.PDFDownloadManager.download_one", fake_download
    )
    monkeypatch.setattr(
        "paperfetch.fulltext.service.PDFDownloadManager.close", fake_close
    )
    outcome = await PaperDownloadService().download(
        DownloadRequest(paper=paper, seed_pack=repository.root, no_cache=True)
    )
    assert outcome.succeeded
    assert outcome.identity.method == "doi"
    assert outcome.successful_route == "europe_pmc"
    manifest = json.loads(
        (repository.root / outcome.pdf.manifest_path).read_text(encoding="utf-8")
    )
    assert manifest["kind"] == "paper_pdf"
    audit = (repository.root / outcome.audit_ref).read_text(encoding="utf-8")
    assert "user:pass" not in audit
    assert "secret" not in audit
    assert "%3Credacted%3E" in audit
    assert not list(
        (repository.root / ".spc" / "staging").glob(f"download-{paper.paper_id}-*")
    )


@pytest.mark.asyncio
async def test_adapter_rejects_downloaded_without_identity(
    monkeypatch, tmp_path: Path, make_pdf_bytes
):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    paper = _paper()
    repository.add([paper])
    source = tmp_path / "wrong.pdf"
    source.write_bytes(make_pdf_bytes(title="Different article", doi="10.1000/wrong"))

    async def fake_download(_self, legacy):
        legacy.fulltext_status = FulltextStatus(
            download_status="downloaded",
            download_attempted=True,
            resource_outcome="downloaded",
            local_path=str(source),
            magic_pdf=True,
            identity_verified=False,
            identity_status="mismatch",
            failure_taxonomy="metadata_poisoned",
            last_failure_class="metadata_poisoned",
        )
        return legacy.fulltext_status

    async def fake_close(_self):
        return None

    monkeypatch.setattr(
        "paperfetch.fulltext.service.PDFDownloadManager.download_one", fake_download
    )
    monkeypatch.setattr(
        "paperfetch.fulltext.service.PDFDownloadManager.close", fake_close
    )
    outcome = await PaperDownloadService().download(
        DownloadRequest(paper=paper, seed_pack=repository.root)
    )
    assert not outcome.succeeded
    assert outcome.error.code == "metadata_poisoned"
    assert not list((repository.root / "artifacts").rglob("article.pdf"))
    assert not list(
        (repository.root / ".spc" / "staging").glob(f"download-{paper.paper_id}-*")
    )


@pytest.mark.asyncio
async def test_unexpected_downloader_exception_becomes_stable_error(
    monkeypatch, tmp_path: Path
):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    paper = _paper()
    repository.add([paper])

    async def raise_timeout(_self, _legacy):
        raise TimeoutError("internal signed URL must not appear")

    async def fake_close(_self):
        return None

    monkeypatch.setattr(
        "paperfetch.fulltext.service.PDFDownloadManager.download_one", raise_timeout
    )
    monkeypatch.setattr(
        "paperfetch.fulltext.service.PDFDownloadManager.close", fake_close
    )
    outcome = await PaperDownloadService().download(
        DownloadRequest(paper=paper, seed_pack=repository.root)
    )
    assert outcome.error.code == "timeout"
    assert outcome.error.retryable is True
    assert "internal signed URL" not in outcome.error.message
    assert not list(
        (repository.root / ".spc" / "staging").glob(f"download-{paper.paper_id}-*")
    )


@pytest.mark.asyncio
async def test_pdf_file_save_failure_is_stable_and_cleans_staging(
    monkeypatch, tmp_path: Path, make_pdf_bytes
):
    repository = SeedPackRepository.initialize(tmp_path / "pack")
    paper = _paper()
    repository.add([paper])
    source = tmp_path / "download.pdf"
    source.write_bytes(
        make_pdf_bytes(title=paper.bibliographic.title, doi=paper.identifiers.doi)
    )

    async def fake_download(_self, legacy):
        legacy.fulltext_status = FulltextStatus(
            download_status="downloaded",
            download_attempted=True,
            resource_outcome="downloaded",
            local_path=str(source),
            magic_pdf=True,
            identity_verified=True,
            identity_status="verified_doi",
            identity_confidence="high",
            identity_evidence={"primary_dois": [paper.identifiers.doi]},
            successful_route="europe_pmc",
        )
        return legacy.fulltext_status

    async def fake_close(_self):
        return None

    def reject_save(*_args, **_kwargs):
        from paperfetch.artifacts.store import ArtifactStoreError

        raise ArtifactStoreError("artifact_pdf_invalid", "sensitive local detail")

    monkeypatch.setattr(
        "paperfetch.fulltext.service.PDFDownloadManager.download_one", fake_download
    )
    monkeypatch.setattr(
        "paperfetch.fulltext.service.PDFDownloadManager.close", fake_close
    )
    monkeypatch.setattr("paperfetch.fulltext.service.materialize_artifact", reject_save)

    outcome = await PaperDownloadService().download(
        DownloadRequest(paper=paper, seed_pack=repository.root)
    )
    assert outcome.error.code == "pdf_file_validation_failed"
    assert outcome.error.stage == "pdf_file_save"
    assert "sensitive local detail" not in outcome.error.message
    assert not list(
        (repository.root / ".spc" / "staging").glob(f"download-{paper.paper_id}-*")
    )


def test_identity_projection_never_uses_a_missing_doi_as_the_target():
    from paperfetch.fulltext.service import _identity_from_legacy

    paper = _paper().model_copy(
        update={
            "identifiers": IdentifierSet(pubmed_id="123", pmc_id="PMC123"),
            "provenance": MetadataProvenance(
                sources=[SourceSnapshot(source_id="src-1", source="test")],
                fields=[
                    FieldProvenance(
                        field="identifiers.pubmed_id", source_ids=["src-1"]
                    ),
                    FieldProvenance(field="identifiers.pmc_id", source_ids=["src-1"]),
                    FieldProvenance(field="bibliographic.title", source_ids=["src-1"]),
                ],
            ),
        }
    )
    status = FulltextStatus(
        identity_verified=True,
        identity_status="verified_doi",
        identity_evidence={"discovered_dois": ["10.1000/discovered"]},
    )

    identity = _identity_from_legacy(
        status, PaperRecord.model_validate(paper.model_dump())
    )

    assert identity.method == "pmc_id"
    assert identity.target == "PMC123"
    assert identity.observed == "PMC123"
