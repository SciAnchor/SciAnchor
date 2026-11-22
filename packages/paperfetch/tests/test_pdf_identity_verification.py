# -*- coding: utf-8 -*-
"""PDF 论文身份校验与污染缓存隔离测试。"""

from pathlib import Path

import pytest

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.pipeline.cache import PDFGlobalCache, PDFVerifier
from paperfetch.downloaders.pipeline.manager import PDFDownloadManager


def test_pdf_identity_accepts_expected_doi(tmp_path, make_pdf_bytes):
    paper = PaperRecord(
        paper_id="spc:identity-ok",
        doi="10.1016/j.example.2026.100001",
        title="Reliable Identity Verification for Research Papers",
    )
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(make_pdf_bytes(title=paper.title, doi=paper.doi))

    result = PDFVerifier().verify_file(str(pdf), paper)

    assert result["valid"] is True
    assert result["identity_verified"] is True
    assert result["identity_status"] == "verified_doi"
    assert paper.doi in result["identity_evidence"]["discovered_dois"]


def test_pdf_identity_repairs_glued_doi_label_only_for_expected_identifier(
    tmp_path,
    make_pdf_bytes,
):
    expected = "10.64898/2026.04.28.26351937"
    paper = PaperRecord(
        paper_id="spc:medrxiv-doi-label",
        doi=expected,
        title="Predicting one-year postoperative functional status in contrast-enhancing glioma",
    )
    pdf = tmp_path / "medrxiv.pdf"
    pdf.write_bytes(
        make_pdf_bytes(
            title="Unrelated metadata title",
            doi=f"{expected}doi",
        )
    )

    result = PDFVerifier().verify_file(str(pdf), paper)

    assert result["valid"] is True
    assert result["identity_status"] == "verified_doi"
    assert result["identity_confidence"] == "high"
    assert result["identity_evidence"]["primary_dois"] == [expected]
    assert result["identity_evidence"]["discovered_dois"] == [expected]


def test_doi_label_repair_does_not_truncate_unrelated_identifier():
    expected = "10.64898/2026.04.28.26351937"

    discovered = PDFVerifier._extract_dois(
        "doi:10.1234/exampledoi",
        expected_doi=expected,
    )

    assert discovered == {"10.1234/exampledoi"}


def test_pdf_identity_rejects_conflicting_document(tmp_path, make_pdf_bytes):
    paper = PaperRecord(
        paper_id="spc:identity-wrong",
        doi="10.1016/j.example.2026.100001",
        title="Reliable Identity Verification for Research Papers",
    )
    pdf = tmp_path / "wrong.pdf"
    pdf.write_bytes(
        make_pdf_bytes(
            title="An Unrelated Clinical Trial Report",
            doi="10.1093/brain/awad001",
        )
    )

    result = PDFVerifier().verify_file(str(pdf), paper)

    assert result["valid"] is False
    assert result["error_class"] == "metadata_poisoned"
    assert result["identity_status"] == "mismatch"


def test_pdf_identity_rejects_insufficient_evidence(tmp_path, make_pdf_bytes):
    paper = PaperRecord(
        paper_id="spc:identity-unknown",
        doi="10.1016/j.example.2026.100001",
        title="Reliable Identity Verification for Research Papers",
    )
    pdf = tmp_path / "unknown.pdf"
    pdf.write_bytes(make_pdf_bytes(title="", doi=""))

    result = PDFVerifier().verify_file(str(pdf), paper)

    assert result["valid"] is False
    assert result["error_class"] == "identity_unverified"
    assert result["identity_status"] == "unverified"


def test_global_cache_quarantines_identity_mismatch(tmp_path, make_pdf_bytes):
    paper = PaperRecord(
        paper_id="spc:cache-poison",
        doi="10.1016/j.example.2026.100001",
        title="Reliable Identity Verification for Research Papers",
    )
    cache = PDFGlobalCache(tmp_path / "cache")
    cached = cache.pdf_path(paper)
    cached.write_bytes(
        make_pdf_bytes(
            title="An Unrelated Clinical Trial Report",
            doi="10.1093/brain/awad001",
        )
    )

    found, result = cache.inspect_verified(paper, PDFVerifier())

    assert found is None
    assert result["error_class"] == "metadata_poisoned"
    assert not cached.exists()
    quarantined = list((cache.root / "quarantine").glob("*.pdf"))
    assert len(quarantined) == 1
    assert quarantined[0].with_suffix(".json").exists()


def test_global_cache_uses_verified_manifest(tmp_path, monkeypatch, make_pdf_bytes):
    paper = PaperRecord(
        paper_id="spc:cache-manifest",
        doi="10.1016/j.example.2026.100001",
        title="Reliable Identity Verification for Research Papers",
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(make_pdf_bytes(title=paper.title, doi=paper.doi))
    verifier = PDFVerifier()
    verification = verifier.verify_file(str(source), paper)
    cache = PDFGlobalCache(tmp_path / "cache")
    stored = cache.store_verified(
        paper, str(source), verifier, verification=verification
    )
    assert stored is not None

    def fail_if_reparsed(*args, **kwargs):
        raise AssertionError("可信 manifest 命中不应重复解析 PDF 文本")

    monkeypatch.setattr(verifier, "verify_identity", fail_if_reparsed)
    found, result = cache.inspect_verified(paper, verifier)

    assert found == stored
    assert result["identity_verified"] is True
    assert result["identity_status"] == "verified_doi"


@pytest.mark.asyncio
async def test_download_rejects_and_quarantines_wrong_pdf(
    tmp_path,
    monkeypatch,
    make_pdf_bytes,
):
    paper = PaperRecord(
        paper_id="spc:network-poison",
        doi="10.1016/j.example.2026.100001",
        title="Reliable Identity Verification for Research Papers",
    )
    paper.fulltext_status.pdf_url = "https://example.org/wrong.pdf"
    payload = make_pdf_bytes(
        title="An Unrelated Clinical Trial Report",
        doi="10.1093/brain/awad001",
    )

    async def mock_download(self, ctx):
        from paperfetch.downloaders.pdf_common import build_pdf_result

        path = str(ctx.target_file) + ".test.part"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(payload)
        return build_pdf_result(
            path, ctx.candidate.url, ctx.candidate.route, "application/pdf"
        )

    from paperfetch.core.settings import reset_settings

    monkeypatch.setattr(
        "paperfetch.downloaders.backends.http_direct.HTTPDirectBackend.download",
        mock_download,
    )
    monkeypatch.setattr(
        "paperfetch.downloaders.pipeline.direct.DirectResourceDiscovery.discover",
        lambda self, paper, timeout=8.0: __import__("asyncio").sleep(
            0, result=(self._local_resources(paper), [])
        ),
    )
    reset_settings()

    cache_root = tmp_path / "cache"
    manager = PDFDownloadManager(str(tmp_path / "output"), cache_root=cache_root)
    try:
        await manager.download_many([paper])
    finally:
        await manager.close()

    assert paper.fulltext_status.download_status == "failed"
    assert any(
        item.get("error_class") == "metadata_poisoned"
        for item in paper.fulltext_status.download_attempts
    )
    assert list((cache_root / "quarantine").glob("*.pdf"))
    assert not list((cache_root / "files").glob("*.pdf"))
