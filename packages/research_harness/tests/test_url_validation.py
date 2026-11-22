"""Tests for URL-level PDF plausibility checks."""

from __future__ import annotations

import httpx
import pytest

from research_harness.acquisition.url_validation import (
    assess_pdf_url,
    doi_in_url,
    is_non_pdf_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://journals.plos.org/plosone/article/figure/image?id=10.1371/x.g001",
        "https://pubs.acs.org/doi/suppl/extlink/10.1021/x",
        "https://example.org/supplementary_material/paper.pdf",
        "https://www.science.org/cms/article/figure/f1.pdf",
        "https://journals.plos.org/plosone/article/file?id=10.1371/x&type=download",
    ],
)
def test_figure_and_supplement_urls_are_flagged(url: str) -> None:
    assert is_non_pdf_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/pdf/2401.00001",
        "https://dl.acm.org/doi/pdf/10.5555/rag.2026?download=true",
        "https://journals.plos.org/plosone/article/file?id=10.1371/x&type=printable",
        "",
        None,
    ],
)
def test_manuscript_urls_are_not_flagged(url) -> None:
    assert is_non_pdf_url(url) is False


def test_doi_in_url_matches_raw_and_percent_encoded() -> None:
    assert doi_in_url("10.5555/RAG.2026", "https://dl.acm.org/doi/pdf/10.5555/rag.2026")
    assert doi_in_url("10.5555/rag.2026", "https://x.org/pdf/10.5555%2Frag.2026")
    assert not doi_in_url("10.5555/rag.2026", "https://x.org/pdf/other")
    assert not doi_in_url("", "https://x.org/pdf/10.5555/rag.2026")


class TestAssessPdfUrl:
    def test_suspect_pattern_wins(self):
        verdict = assess_pdf_url(
            "10.1371/x", "https://journals.plos.org/article/figure/image?id=10.1371/x"
        )
        assert verdict == "suspect_non_pdf"

    def test_doi_match(self):
        assert (
            assess_pdf_url("10.5555/a", "https://pub.org/doi/pdf/10.5555/a")
            == "doi_match"
        )

    def test_trusted_host(self):
        assert (
            assess_pdf_url("10.5555/a", "https://arxiv.org/pdf/2401.1")
            == "trusted_host"
        )
        assert (
            assess_pdf_url(None, "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/p.pdf")
            == "trusted_host"
        )

    def test_neutral_and_unknown(self):
        assert assess_pdf_url("10.5555/a", "https://cdn.example.org/f.pdf") == "neutral"
        assert assess_pdf_url("10.5555/a", None) == "unknown"

    def test_lookalike_host_is_not_trusted(self):
        assert assess_pdf_url(None, "https://evilarxiv.org/pdf/x") == "neutral"


class _NoNetworkClient:
    """httpx.AsyncClient stand-in that fails the test on any fetch."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        raise AssertionError(f"network fetch attempted: {url}")


def test_downloader_skips_figure_url_without_network(monkeypatch, tmp_path):
    import asyncio

    from research_harness.acquisition import downloader
    from research_harness.pdf_download import PaperDownloadCandidate

    monkeypatch.setattr(httpx, "AsyncClient", _NoNetworkClient)
    from research_harness.acquisition import spc_bridge

    def no_spc(*args, **kwargs):
        raise AssertionError("non-PDF URL must not launch SPC")

    monkeypatch.setattr(spc_bridge, "spc_download", no_spc)
    figure_url = "https://journals.plos.org/plosone/article/figure/image?id=10.1371/x"
    candidate = PaperDownloadCandidate(
        paper_id=1, title="Figure Only Paper", url=figure_url
    )

    result = asyncio.run(
        downloader.download_single(candidate, tmp_path, asyncio.Semaphore(1))
    )

    assert result.status != "success"
    assert result.audit is not None
    skips = [
        attempt
        for attempt in result.audit.attempts
        if attempt.decision_reason == "non_pdf_url_pattern"
    ]
    assert skips and skips[0].error_class == "not_pdf"
    assert skips[0].skipped is True
