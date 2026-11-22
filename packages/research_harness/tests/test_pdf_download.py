from __future__ import annotations

from types import SimpleNamespace

from research_harness.pdf_download import (
    PaperDownloadCandidate,
    build_candidate_urls,
    preferred_filename,
)


def test_arxiv_id_generates_pdf_url() -> None:
    candidate = PaperDownloadCandidate(paper_id=1, title="Test", arxiv_id="2302.01523")
    urls = build_candidate_urls(candidate)
    assert "https://arxiv.org/pdf/2302.01523.pdf" in urls


def test_arxiv_abs_url_expands_to_pdf() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=1, title="Test", url="https://arxiv.org/abs/2302.01523"
    )
    urls = build_candidate_urls(candidate)
    assert "https://arxiv.org/pdf/2302.01523.pdf" in urls


def test_openreview_forum_url_expands_to_pdf() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=1,
        title="Test",
        url="https://openreview.net/forum?id=abc123",
    )
    urls = build_candidate_urls(candidate)
    assert "https://openreview.net/pdf?id=abc123" in urls


def test_pmcid_generates_open_access_pdf_candidates() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=2,
        title="PMC Paper",
        pmcid="11117177",
    )

    urls = build_candidate_urls(candidate)

    assert "https://europepmc.org/api/getPdf?pmcid=PMC11117177" in urls
    assert "https://europepmc.org/articles/PMC11117177?pdf=render" in urls
    assert "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC11117177" in urls
    assert "https://pmc.ncbi.nlm.nih.gov/articles/PMC11117177/" in urls


def test_ieee_doi_generates_stamp_url() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=20,
        title="IEEE Paper",
        doi="10.1109/SSCI.2017.8285393",
    )
    urls = build_candidate_urls(candidate)
    assert any("stamp.jsp" in url and "arnumber=8285393" in url for url in urls), (
        f"Expected IEEE stamp URL with arnumber=8285393, got: {urls}"
    )


def test_acm_doi_generates_acm_pdf_url() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=13,
        title="KDD Paper",
        doi="10.1145/3637528.3671592",
    )
    urls = build_candidate_urls(candidate)
    assert any("dl.acm.org/doi/pdf" in url for url in urls)


def test_springer_doi_generates_pdf_url() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=21,
        title="Springer Paper",
        doi="10.1007/978-3-030-12345-6_1",
    )
    urls = build_candidate_urls(candidate)
    assert any("link.springer.com/content/pdf" in url for url in urls)


def test_elsevier_doi_generates_sciencedirect_url() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=22,
        title="Elsevier Paper",
        doi="10.1016/j.ejor.2021.08.019",
    )
    urls = build_candidate_urls(candidate)
    assert any("sciencedirect.com" in url for url in urls)


def test_informs_doi_generates_informs_url() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=23,
        title="INFORMS Paper",
        doi="10.1287/isre.2017.0724",
    )
    urls = build_candidate_urls(candidate)
    assert any("pubsonline.informs.org" in url for url in urls)


def test_doi_always_generates_doi_org_redirect() -> None:
    candidate = PaperDownloadCandidate(
        paper_id=24, title="Any Paper", doi="10.9999/test"
    )
    urls = build_candidate_urls(candidate)
    assert any("doi.org/10.9999/test" in url for url in urls)


def test_unpaywall_oa_url_returns_none_on_error(monkeypatch) -> None:
    from research_harness.pdf_download import _unpaywall_oa_url
    import urllib.request
    import urllib.error

    def mock_urlopen(*args, **kwargs):
        raise urllib.error.URLError("mock error")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    assert _unpaywall_oa_url("10.1234/test") is None


def test_pdf_identity_failure_returns_none_for_verified_pdf(monkeypatch, tmp_path):
    from research_harness.acquisition import downloader

    monkeypatch.setattr(
        downloader,
        "audit_pdf_identity",
        lambda **_: SimpleNamespace(status="verified", reason="matched title"),
    )
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n" + b"x" * 12_000)
    candidate = PaperDownloadCandidate(paper_id=1, title="Matching Paper")

    assert downloader._pdf_identity_failure(candidate, pdf_path) is None


def test_pdf_identity_failure_rejects_suspect_pdf(monkeypatch, tmp_path):
    from research_harness.acquisition import downloader

    monkeypatch.setattr(
        downloader,
        "audit_pdf_identity",
        lambda **_: SimpleNamespace(
            status="suspect",
            reason="no title/DOI/PMID signal in extracted PDF text",
        ),
    )
    pdf_path = tmp_path / "wrong.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n" + b"x" * 12_000)
    candidate = PaperDownloadCandidate(
        paper_id=1,
        title="Climate change and pregnancy outcomes",
        doi="10.1289/example",
        pmid="12345678",
    )

    assert (
        downloader._pdf_identity_failure(candidate, pdf_path)
        == "no title/DOI/PMID signal in extracted PDF text"
    )


def test_identifier_inference_with_both_arxiv_and_doi(monkeypatch) -> None:
    monkeypatch.setattr(
        "research_harness.pdf_download._unpaywall_oa_url", lambda doi: None
    )
    candidate = PaperDownloadCandidate(
        paper_id=13,
        title="Spending Programmed Bidding",
        venue="KDD 2024",
        doi="10.1145/3637528.3671592",
        arxiv_id="2405.12345",
    )
    urls = build_candidate_urls(candidate)
    assert "https://arxiv.org/pdf/2405.12345.pdf" in urls
    assert "https://dl.acm.org/doi/pdf/10.1145/3637528.3671592" in urls
    assert preferred_filename(candidate).startswith("13_Spending_Programmed_Bidding")


def test_preferred_filename() -> None:
    candidate = PaperDownloadCandidate(paper_id=5, title="Hello World: A Study!")
    assert preferred_filename(candidate) == "5_Hello_World_A_Study.pdf"
