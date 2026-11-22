# -*- coding: utf-8 -*-
"""
tests/test_issues_fixes.py
测试新增 Issue 解决方案和潜在漏洞优化的正确性。
包括：管线细粒度异常映射、元数据 PDF 候选与运行报告等。
"""

import json
import os
import asyncio
import httpx
import pytest
from urllib.parse import urljoin
from paperfetch.core.models import MergeConfidence, PaperRecord
from paperfetch.downloaders.base import DownloadRunContext, PDFRouteCandidate
from paperfetch.downloaders.pipeline.cache import PDFGlobalCache, PDFVerifier
from paperfetch.downloaders.pipeline.errors import DownloadError
from paperfetch.downloaders.pipeline.manager import PDFDownloadManager
from paperfetch.downloaders.pipeline.report import build_download_run_report
from paperfetch.downloaders.pipeline.resolver import PDFResolver
from paperfetch.downloaders.pipeline.scheduler import DownloadScheduler, PDFRouteAttempt


def test_pdf_pipeline_attempt_from_exception(monkeypatch):
    """测试 _attempt_from_exception 对 ValueError、HTTP 网关错误与本地 IO 错误的归类。"""

    manager = PDFDownloadManager(output_dir="test_out")
    candidate = PDFRouteCandidate(
        route="public_http", url="http://test.url", source="public"
    )

    exc_magic = ValueError("PDF 文件魔数校验失败")
    attempt_magic = manager.scheduler._attempt_from_exception(candidate, exc_magic)
    assert attempt_magic.error_class == "magic_bytes_mismatch"

    request = httpx.Request("GET", "https://repo.example.org/error/500?code=504")
    exc_http_gateway = httpx.HTTPStatusError(
        "网关物理超时故障 (HTTP 504)",
        request=request,
        response=httpx.Response(200, request=request),
    )
    attempt_http_gateway = manager.scheduler._attempt_from_exception(
        candidate, exc_http_gateway
    )
    assert attempt_http_gateway.error_class == "gateway_fault"

    exc_gateway_value = ValueError("upstream gateway fault threshold reached")
    attempt_gateway_value = manager.scheduler._attempt_from_exception(
        candidate, exc_gateway_value
    )
    assert attempt_gateway_value.error_class == "gateway_fault"

    local_io = DownloadError.from_exception(
        PermissionError(13, "permission denied", "/state/pdf/cache.part"),
        route="public_http",
    )
    assert local_io.error_class == "local_io_error"
    assert local_io.diagnostics["stage"] == "local_state_io"
    assert local_io.diagnostics["exception_type"] == "PermissionError"


@pytest.mark.asyncio
async def test_phase1_public_http_never_falls_back_to_environment_proxy(
    tmp_path, monkeypatch, make_pdf_bytes
):
    paper = PaperRecord(
        paper_id="spc:agent-proxy", doi="10.0000/agent", title="Agent PDF"
    )
    paper.fulltext_status.pdf_url = "https://repo.example.edu/paper.pdf"
    paper.fulltext_status.pdf_source = "agent_browser"

    calls = []

    async def mock_download(self, ctx):
        client = ctx.client
        calls.append(getattr(client, "marker", "unknown"))
        raise DownloadError("timeout", route=ctx.candidate.route, url=ctx.candidate.url)

    monkeypatch.setattr(
        "paperfetch.downloaders.backends.http_direct.HTTPDirectBackend.download",
        mock_download,
    )
    monkeypatch.setattr(
        "paperfetch.downloaders.pipeline.direct.DirectResourceDiscovery.discover",
        lambda self, paper, timeout=8.0: asyncio.sleep(
            0, result=(self._local_resources(paper), [])
        ),
    )

    manager = PDFDownloadManager(str(tmp_path / "pdf"), cache_root=tmp_path / "cache")
    manager.scheduler.direct_client.marker = "direct"
    manager.scheduler.shared_client.marker = "proxy"
    try:
        status = await manager.download_one(paper)
    finally:
        await manager.close()

    attempts = [
        attempt
        for attempt in status.download_attempts
        if attempt["route"] == "public_http"
    ]
    assert status.download_status == "failed"
    assert calls == ["direct"]
    assert attempts[0]["proxy_mode"] == "no-proxy"
    assert attempts[0]["error_class"] == "timeout"


@pytest.mark.asyncio
async def test_http_classifier_distinguishes_waf_and_auth_required(
    tmp_path, monkeypatch
):
    from paperfetch.downloaders.backends.http_direct import HTTPDirectBackend

    waf_headers = httpx.Headers(
        {"Content-Type": "text/html", "x-amzn-waf-action": "challenge"}
    )
    auth_headers = httpx.Headers({"Content-Type": "text/html"})
    assert (
        HTTPDirectBackend._classify(
            202,
            "text/html",
            b"<html>challenge</html>",
            "https://ieeexplore.ieee.org/document/123",
            waf_headers,
        )
        == "publisher_challenge"
    )
    assert (
        HTTPDirectBackend._classify(
            403,
            "text/html",
            b"<html>Institutional sign in required</html>",
            "https://dl.acm.org/doi/pdf/10.1145/123",
            auth_headers,
        )
        == "auth_required"
    )


def test_openalex_prefers_structured_pdf_url_over_oa_landing():
    from paperfetch.sources.openalex import OpenAlexSource

    source = OpenAlexSource(None)
    record = source._to_paper_record(
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.0000/test",
            "title": "OpenAlex PDF",
            "publication_year": 2026,
            "primary_location": {
                "pdf_url": "https://repo.example.org/primary.pdf",
                "source": {"type": "journal", "display_name": "Journal"},
            },
            "best_oa_location": {"pdf_url": "https://repo.example.org/best.pdf"},
            "locations": [{"pdf_url": "https://repo.example.org/location.pdf"}],
            "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/41429128"},
            "open_access": {
                "is_oa": True,
                "oa_url": "https://repo.example.org/landing",
            },
        },
        "test",
    )

    assert record.fulltext_status.pdf_url == "https://repo.example.org/primary.pdf"
    assert record.fulltext_status.pdf_source == "openalex_primary_location"
    assert record.pubmed_id == "41429128"
    assert any(ref.field == "pubmed_id" for ref in record.source_refs)


def test_openalex_extracts_pmcid_from_modern_pmc_oa_url():
    from paperfetch.sources.openalex import OpenAlexSource

    source = OpenAlexSource(None)
    record = source._to_paper_record(
        {
            "id": "https://openalex.org/W7154700658",
            "doi": "https://doi.org/10.25259/SNI_75_2026",
            "title": "SNI PMC Paper",
            "publication_year": 2026,
            "primary_location": {
                "source": {
                    "type": "journal",
                    "display_name": "Surgical Neurology International",
                }
            },
            "locations": [],
            "open_access": {
                "is_oa": True,
                "oa_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13157918/",
            },
        },
        "test",
    )

    assert record.pmc_id == "PMC13157918"
    assert record.fulltext_status.pdf_url == (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC13157918/"
    )
    assert any(ref.field == "pmc_id" for ref in record.source_refs)


def test_semantic_scholar_extracts_open_access_pdf():
    from paperfetch.sources.semantic_scholar import SemanticScholarSource

    source = SemanticScholarSource(None)
    record = source._to_paper_record(
        {
            "paperId": "s2-1",
            "title": "S2 PDF",
            "year": 2026,
            "externalIds": {"DOI": "10.0000/s2"},
            "openAccessPdf": {"url": "https://s2.example.org/paper.pdf"},
            "isOpenAccess": True,
        },
        "test",
    )

    assert "openAccessPdf" in source.default_fields
    assert record.fulltext_status.pdf_url == "https://s2.example.org/paper.pdf"
    assert record.fulltext_status.pdf_source == "semantic_scholar_openAccessPdf"


def test_dedup_merges_fulltext_pdf_candidates_without_losing_source_url():
    from paperfetch.core.dedup import merge_records

    left = PaperRecord(paper_id="spc:left", doi="10.0000/same", title="Same Paper")
    left.fulltext_status.pdf_url = "https://left.example.org/paper.pdf"
    left.fulltext_status.pdf_source = "openalex_primary_location"
    right = PaperRecord(paper_id="spc:right", doi="10.0000/same", title="Same Paper")
    right.fulltext_status.pdf_url = "https://right.example.org/paper.pdf"
    right.fulltext_status.pdf_source = "semantic_scholar_openAccessPdf"

    merged = merge_records(left, right, MergeConfidence.HIGH)

    urls = {candidate["url"] for candidate in merged.fulltext_status.pdf_candidates}
    assert "https://left.example.org/paper.pdf" in urls
    assert "https://right.example.org/paper.pdf" in urls
    assert merged.fulltext_status.pdf_url in urls


@pytest.mark.asyncio
async def test_doi_resolve_response_reused_across_doi_routes(tmp_path, monkeypatch):
    from paperfetch.downloaders.pipeline.direct import DirectResourceDiscovery

    paper = PaperRecord(
        paper_id="spc:doi-cache", doi="10.0000/doi-cache", title="DOI Cache"
    )
    calls = []

    async def handler(request):
        calls.append(str(request.url))
        if request.url.host == "doi.org":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=b"<html>landing</html>",
                request=request,
            )
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        _, events = await DirectResourceDiscovery(client).discover(paper)

    assert sum(httpx.URL(url).host == "doi.org" for url in calls) == 1
    assert any(event["source"] == "doi_landing" for event in events)


def test_run_report_includes_transfer_and_verification_metrics():

    paper = PaperRecord(
        paper_id="spc:report",
        doi="10.1016/example",
        title="Report",
        publisher="Elsevier",
    )
    status = paper.fulltext_status
    status.download_attempted = True
    status.download_status = "failed"
    status.failure_taxonomy = "publisher_pdf_challenge"
    status.candidate_pdf_urls = [
        {
            "route": "public_http",
            "metadata": {"decision_reason": "normalized_public_resource"},
        },
    ]
    status.route_errors = [
        {
            "route": "public_http",
            "error_class": "publisher_pdf_challenge",
            "error": "publisher_pdf_challenge",
        }
    ]
    status.download_attempts = [
        PDFRouteAttempt(
            "public_http",
            duration_ms=123,
            queue_ms=0,
            diagnostics={"stage_timings": {"preheat_ms": 10, "pdf_request_ms": 50}},
            error_class="publisher_pdf_challenge",
        ).audit_dict()
    ]

    report = build_download_run_report([paper], total_candidates=1)

    assert report["report_version"] == "paperfetch.run-report.v3"
    assert (
        report["metrics"]["transfer"]["error_classes"]["publisher_pdf_challenge"] == 1
    )
    assert report["metrics"]["transfer"]["timing"]["count"] == 1
    assert report["metrics"]["verification"]["statuses"]["not_checked"] == 1
