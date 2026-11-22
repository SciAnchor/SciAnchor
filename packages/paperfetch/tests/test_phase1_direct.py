# -*- coding: utf-8 -*-
"""当前 Phase 1 直连下载实现的契约测试。"""

import json
import asyncio
import time
from pathlib import Path

import httpx
import pytest

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.base import PDFRouteCandidate
from paperfetch.downloaders.backends.http_direct import HTTPDirectBackend
from paperfetch.downloaders.pipeline.cache import PDFGlobalCache, PDFVerifier
from paperfetch.downloaders.pipeline.direct import (
    DirectDownloadPipeline,
    DirectResourceDiscovery,
    DiscoveredPDFResource,
    normalize_resource_url,
    normalize_resources,
    trusted_repository_proxy_mode,
)
from paperfetch.downloaders.pipeline.report import build_download_run_report
from paperfetch.downloaders.pipeline.scheduler import DownloadScheduler, PDFRouteAttempt
from paperfetch.downloaders.registry import BackendRegistry


def test_normalization_preserves_signature_and_removes_tracking():
    url = "HTTPS://Example.COM:443/paper.pdf?X-Amz-Signature=abc&token=secret&utm_source=test#page=2"
    normalized = normalize_resource_url(url)

    assert (
        normalized == "https://example.com/paper.pdf?X-Amz-Signature=abc&token=secret"
    )


def test_resources_from_multiple_sources_are_transferred_once():
    resources = [
        DiscoveredPDFResource("metadata", "https://example.org/paper.pdf?utm_source=a"),
        DiscoveredPDFResource("unpaywall", "https://example.org/paper.pdf"),
        DiscoveredPDFResource("crossref_tdm", "https://example.org/other.pdf"),
    ]

    candidates, duplicates = normalize_resources(resources)

    assert duplicates == 1
    assert len(candidates) == 2
    assert candidates[0].sources == ["metadata", "unpaywall"]


def test_rsna_doi_adds_official_publisher_pdf_candidate():
    paper = PaperRecord(
        paper_id="spc:rsna",
        doi="10.1148/ryai.230182",
        title="RSNA Paper",
    )

    resources = DirectResourceDiscovery(object())._local_resources(paper)
    rsna = next(item for item in resources if item.source == "rsna_rule")

    assert rsna.url == "https://pubs.rsna.org/doi/pdf/10.1148/ryai.230182"
    assert rsna.referer == "https://pubs.rsna.org/doi/10.1148/ryai.230182"
    assert rsna.public_access == "open"


def test_numeric_pmc_id_is_normalized_before_building_candidates():
    paper = PaperRecord(
        paper_id="spc:pmc",
        pmc_id="11294954",
        title="PMC Paper",
    )

    resources = DirectResourceDiscovery(object())._local_resources(paper)

    assert any(
        item.source == "pmc_canonical" and "/articles/PMC11294954/pdf/" in item.url
        for item in resources
    )


def test_modern_pmc_article_url_recovers_pmc_and_europe_pmc_pdf_candidates():
    paper = PaperRecord(
        paper_id="spc:sni-75",
        doi="10.25259/sni_75_2026",
        title="Intraoperative ultrasonography with intraoperative MRI confirmation",
        fulltext_status={
            "oa_status": "open",
            "pdf_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13157918/",
            "pdf_source": "openalex_oa_url",
        },
    )

    resources = DirectResourceDiscovery(object())._local_resources(paper)

    assert paper.pmc_id == "PMC13157918"
    assert any(
        item.source == "pmc_canonical"
        and item.url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC13157918/pdf/"
        for item in resources
    )
    assert any(
        item.source == "europe_pmc"
        and item.url == "https://europepmc.org/articles/PMC13157918?pdf=render"
        for item in resources
    )
    candidates, _ = normalize_resources(resources)
    assert candidates[0].sources == ["europe_pmc"]
    assert candidates[1].sources == ["pmc_canonical"]


@pytest.mark.asyncio
async def test_europe_pmc_exact_doi_recovers_identifiers_for_existing_record(
    monkeypatch,
):
    doi = "10.3390/curroncol29090518"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.ebi.ac.uk"
        assert request.url.params["query"] == f"DOI:{doi}"
        return httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "doi": doi,
                            "pmid": "36135087",
                            "pmcid": "PMC9498154",
                            "isOpenAccess": "Y",
                            "inEPMC": "Y",
                            "hasPDF": "Y",
                            "title": "Evaluation of a Navigated 3D Ultrasound Integration for Brain Tumor Surgery",
                        }
                    ]
                }
            },
            request=request,
        )

    async def unexpected_weak_discovery(*args, **kwargs):
        raise AssertionError(
            "exact Europe PMC DOI hit must finish the strong first wave"
        )

    monkeypatch.setattr(
        DirectResourceDiscovery, "_semantic_scholar", unexpected_weak_discovery
    )
    monkeypatch.setattr(
        DirectResourceDiscovery, "_unpaywall", unexpected_weak_discovery
    )
    monkeypatch.setattr(DirectResourceDiscovery, "_crossref", unexpected_weak_discovery)
    monkeypatch.setattr(
        DirectResourceDiscovery, "_doi_landing", unexpected_weak_discovery
    )

    paper = PaperRecord(
        paper_id="spc:195e43f5-b2c7-4648-b0d3-b6063abff239",
        doi=doi,
        title="Evaluation of a Navigated 3D Ultrasound Integration for Brain Tumor Surgery",
        journal="Current Oncology",
        fulltext_status={
            "download_status": "failed",
            "pdf_url": f"https://www.mdpi.com/{doi}/pdf",
            "pdf_source": "mdpi_rule",
            "oa_status": "open",
            "failure_taxonomy": "auth_required",
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        trust_env=False,
    ) as client:
        resources, events = await DirectResourceDiscovery(client).discover(paper)

    assert paper.pubmed_id == "36135087"
    assert paper.pmc_id == "PMC9498154"
    candidates, _ = normalize_resources(resources)
    assert candidates[0].sources == ["europe_pmc_doi"]
    assert candidates[0].url == "https://europepmc.org/articles/PMC9498154?pdf=render"
    assert any(item.sources == ["pmc_canonical_doi"] for item in candidates)
    assert any(
        event["source"] == "europe_pmc_doi" and event["result"] == "found"
        for event in events
    )


@pytest.mark.asyncio
async def test_europe_pmc_doi_rejects_nonexact_or_nonretrievable_result():
    doi = "10.3390/curroncol29090518"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "doi": "10.3390/unrelated",
                            "pmcid": "PMC9498154",
                            "isOpenAccess": "Y",
                            "inEPMC": "Y",
                            "hasPDF": "Y",
                        },
                        {
                            "doi": doi,
                            "pmcid": "PMC9498154",
                            "isOpenAccess": "Y",
                            "inEPMC": "Y",
                            "hasPDF": "N",
                        },
                    ]
                }
            },
            request=request,
        )

    paper = PaperRecord(paper_id="spc:reject-epmc", doi=doi, title="Target")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        resources = await DirectResourceDiscovery(client)._europe_pmc_doi(paper)

    assert resources == []
    assert paper.pmc_id is None
    assert paper.pubmed_id is None


@pytest.mark.asyncio
async def test_openalex_repository_resolves_allowlisted_main_pdf_and_recovers_pmid():
    doi = "10.1016/S1470-2045(25)00642-4"
    landing = "https://freidok.uni-freiburg.de/data/275391"
    main_pdf = (
        "https://freidok.uni-freiburg.de/files/275391/FeXuMVaoTEsy-XpN/"
        "O-2-18F+fluoroethyl-L-tyrosine-PET-guided.pdf"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200,
                json={
                    "doi": f"https://doi.org/{doi.lower()}",
                    "ids": {
                        "pmid": "https://pubmed.ncbi.nlm.nih.gov/41429128",
                    },
                    "locations": [
                        {
                            "landing_page_url": landing,
                            "pdf_url": None,
                            "version": "publishedVersion",
                        },
                        {
                            "landing_page_url": "https://untrusted.example/paper",
                            "version": "acceptedVersion",
                        },
                    ],
                },
                request=request,
            )
        assert request.url.host == "freidok.uni-freiburg.de"
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text=(
                "<a href='/files/275391/dgMu98Hu5eAQCqeY/"
                "1-s2.0-S1470204525006424-mmc1.pdf'>Supplement</a>"
                "<a href='https://mirror.invalid/main.pdf'>Mirror</a>"
                f"<a href='{main_pdf}'>Main text</a>"
            ),
            request=request,
        )

    paper = PaperRecord(paper_id="spc:gliaa", doi=doi, title="GLIAA")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        trust_env=False,
    ) as client:
        resources = await DirectResourceDiscovery(client)._openalex_repository(paper)

    assert paper.pubmed_id == "41429128"
    assert len(resources) == 1
    resource = resources[0]
    assert resource.source == "openalex_repository"
    assert resource.url == main_pdf
    assert resource.referer == landing
    assert resource.public_access == "open"
    assert resource.confidence == "high"
    assert resource.diagnostics["repository_host"] == "freidok.uni-freiburg.de"
    assert resource.diagnostics["version"] == "publishedVersion"


@pytest.mark.asyncio
async def test_openalex_repository_does_not_fetch_non_allowlisted_landing():
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "doi": "https://doi.org/10.0000/repository",
                "locations": [
                    {"landing_page_url": "https://repository.example/paper"},
                ],
            },
            request=request,
        )

    paper = PaperRecord(
        paper_id="spc:repository-denied",
        doi="10.0000/repository",
        title="Repository denied",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        resources = await DirectResourceDiscovery(client)._openalex_repository(paper)

    assert resources == []
    assert len(requests) == 1


def test_pmc_pow_is_not_misclassified_as_publisher_challenge():
    error_class = HTTPDirectBackend._classify(
        200,
        "text/html",
        b"<html>Cloudflare verify you are human</html>",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC11770880/pdf/",
        httpx.Headers({}),
    )

    assert error_class == "pmc_download_challenge"


def test_legacy_phase1_routes_are_not_registered():
    routes = BackendRegistry.all_backends()

    assert "public_http" in routes
    assert "public_browser" in routes
    assert "oa_resolver" not in routes
    assert "open_access_browser" not in routes
    assert "doi_landing" not in routes
    assert "publisher_resolver" not in routes
    assert "publisher_api_crossref_tdm" not in routes


@pytest.mark.asyncio
async def test_crossref_discovers_mdpi_static_pdf_without_challenge_page():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "short-container-title": ["Diagnostics"],
                    "volume": "13",
                    "issue": "24",
                    "page": "3611",
                    "link": [],
                }
            },
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        resources = await DirectResourceDiscovery(client)._crossref(
            "10.3390/diagnostics13243611"
        )

    assert len(resources) == 1
    assert resources[0].source == "crossref_mdpi_static"
    assert resources[0].url == (
        "https://mdpi-res.com/d_attachment/diagnostics/diagnostics-13-03611/"
        "article_deploy/diagnostics-13-03611.pdf"
    )


@pytest.mark.asyncio
async def test_public_http_streams_to_part_then_atomically_commits(
    tmp_path, make_pdf_bytes
):
    pdf_bytes = make_pdf_bytes(title="Streaming Paper", doi="10.0000/stream")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=pdf_bytes,
            request=request,
        )

    cache = PDFGlobalCache(tmp_path / "cache")
    scheduler = DownloadScheduler(cache, PDFVerifier(), no_cache=True)
    await scheduler.direct_client.aclose()
    scheduler.direct_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True, trust_env=False
    )
    paper = PaperRecord(
        paper_id="spc:stream", doi="10.0000/stream", title="Streaming Paper"
    )
    candidate = PDFRouteCandidate(
        "public_http",
        url="https://example.org/paper.pdf",
        metadata={
            "resource_fingerprint": "fingerprint",
            "transport": "http",
            "proxy_mode": "no-proxy",
            "anonymous_auth": True,
        },
    )
    target = tmp_path / "pdf" / "paper.pdf"
    scheduler._reset_status_for_attempt(paper.fulltext_status)
    try:
        await scheduler.attempt_candidates(paper, [candidate], str(target))
    finally:
        await scheduler.close()

    assert paper.fulltext_status.download_status == "downloaded"
    assert paper.fulltext_status.successful_route == "public_http"
    assert target.read_bytes().startswith(b"%PDF")
    assert list(target.parent.glob("*.part")) == []
    assert paper.fulltext_status.identity_verified is True


def test_failure_cache_v2_isolated_from_legacy_and_uses_error_ttl(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    (root / "failures.json").write_text(
        json.dumps({"legacy": {"timestamp_epoch": 9999999999}}), encoding="utf-8"
    )
    cache = PDFGlobalCache(root)
    paper = PaperRecord(paper_id="spc:failure", doi="10.0000/failure", title="Failure")
    candidate = PDFRouteCandidate(
        "public_http",
        url="https://example.org/failure.pdf",
        metadata={
            "resource_fingerprint": "abc",
            "transport": "http",
            "proxy_mode": "no-proxy",
            "anonymous_auth": True,
        },
    )
    attempt = PDFRouteAttempt("public_http", error_class="timeout", diagnostics={})

    cache.record_failure(paper, candidate, attempt)
    data = json.loads((root / "failures.v2.json").read_text(encoding="utf-8"))

    assert len(data) == 1
    assert next(iter(data.values()))["ttl_seconds"] == 120
    assert cache.should_skip(paper, candidate) is True


def test_run_report_has_only_stage_oriented_contract():
    paper = PaperRecord(paper_id="spc:report", doi="10.0000/report", title="Report")
    status = paper.fulltext_status
    status.download_attempted = True
    status.download_status = "failed"
    status.discovery_events = [
        {"source": "unpaywall", "result": "no_result", "duration_ms": 20}
    ]
    status.normalized_resources = []
    status.download_attempts = [
        {
            "route": "public_http",
            "error_class": "not_found",
            "duration_ms": 10,
            "proxy_mode": "no-proxy",
        }
    ]

    report = build_download_run_report([paper], total_candidates=1)

    assert report["report_version"] == "paperfetch.run-report.v3"
    assert report["schema_purpose"] == "data_format_only"
    assert set(report["metrics"]) == {
        "discovery",
        "deduplication",
        "transfer",
        "verification",
    }
    assert set(report["papers"][0]) >= {
        "discovery_events",
        "normalized_resources",
        "transfer_attempts",
        "verification",
        "final_result",
    }
    assert "download" not in report
    assert "route_success" not in json.dumps(report)
    assert "success_rate" not in report["metrics"]["transfer"]
    assert report["metrics"]["transfer"]["attempt_success_rate"] == 0.0
    assert report["papers"][0]["final_result"]["identity_verified"] is False
    assert report["papers"][0]["final_result"]["primary_failure_class"] == "not_found"
    assert report["papers"][0]["final_result"]["last_failure_class"] == "not_found"
    assert (
        report["papers"][0]["final_result"]["resource_outcome"]
        == "resource_not_discovered"
    )


def test_run_report_preserves_primary_last_and_discovered_transfer_failure():
    paper = PaperRecord(
        paper_id="spc:failure-chain", doi="10.0000/failure", title="Failure chain"
    )
    status = paper.fulltext_status
    status.download_attempted = True
    status.download_status = "failed"
    status.normalized_resources = [{"url": "https://example/paper.pdf"}]
    status.download_attempts = [
        {"route": "public_http", "error_class": "pmc_download_challenge"},
        {"route": "public_browser", "error_class": "publisher_challenge"},
    ]

    final = build_download_run_report([paper])["papers"][0]["final_result"]

    assert final["primary_failure_class"] == "pmc_download_challenge"
    assert final["last_failure_class"] == "publisher_challenge"
    assert final["resource_outcome"] == "resource_discovered_but_transfer_failed"
    assert [item["route"] for item in final["attempted_route_summary"]] == [
        "public_http",
        "public_browser",
    ]


@pytest.mark.asyncio
async def test_first_oa_result_does_not_cancel_other_oa_locations(monkeypatch):

    async def semantic(self, doi):
        return [
            DiscoveredPDFResource("semantic_scholar", "https://example.org/paper.pdf")
        ]

    async def unpaywall(self, doi):
        return [
            DiscoveredPDFResource("unpaywall", "https://repository.example/paper.pdf")
        ]

    async def empty(self, doi):
        return []

    monkeypatch.setattr(DirectResourceDiscovery, "_semantic_scholar", semantic)
    monkeypatch.setattr(DirectResourceDiscovery, "_unpaywall", unpaywall)
    monkeypatch.setattr(DirectResourceDiscovery, "_crossref", empty)
    monkeypatch.setattr(DirectResourceDiscovery, "_doi_landing", empty)
    monkeypatch.setattr(DirectResourceDiscovery, "_europe_pmc_doi", empty)
    monkeypatch.setattr(DirectResourceDiscovery, "_openalex_repository", empty)
    paper = PaperRecord(paper_id="spc:cancel", doi="10.0000/cancel", title="Cancel")
    async with httpx.AsyncClient() as client:
        resources, events = await DirectResourceDiscovery(client).discover(
            paper, timeout=1
        )

    assert {resource.source for resource in resources} == {
        "semantic_scholar",
        "unpaywall",
    }
    assert not any(event.get("reason") == "oa_result_found" for event in events)


@pytest.mark.asyncio
async def test_same_wait_batch_oa_completion_does_not_reprocess_removed_task(
    monkeypatch,
):
    async def found(self, doi):
        return [
            DiscoveredPDFResource("semantic_scholar", "https://example.org/paper.pdf")
        ]

    async def empty(self, doi):
        return []

    monkeypatch.setattr(DirectResourceDiscovery, "_semantic_scholar", found)
    monkeypatch.setattr(DirectResourceDiscovery, "_unpaywall", found)
    monkeypatch.setattr(DirectResourceDiscovery, "_crossref", empty)
    monkeypatch.setattr(DirectResourceDiscovery, "_doi_landing", empty)
    monkeypatch.setattr(DirectResourceDiscovery, "_europe_pmc_doi", empty)
    monkeypatch.setattr(DirectResourceDiscovery, "_openalex_repository", empty)
    paper = PaperRecord(
        paper_id="spc:same-batch", doi="10.0000/same-batch", title="Same batch"
    )
    async with httpx.AsyncClient() as client:
        resources, events = await DirectResourceDiscovery(client).discover(
            paper, timeout=1
        )

    assert resources
    assert any(event["result"] == "found" for event in events)
    assert sum(event["result"] == "found" for event in events) == 2


@pytest.mark.asyncio
async def test_unpaywall_returns_all_distinct_oa_locations(monkeypatch):
    monkeypatch.setenv("UNPAYWALL_EMAIL", "test@example.org")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "best_oa_location": {
                    "url_for_pdf": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/pdf/",
                    "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/",
                    "host_type": "repository",
                    "version": "acceptedVersion",
                },
                "oa_locations": [
                    {
                        "url_for_pdf": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/pdf/",
                        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/",
                    },
                    {
                        "url_for_pdf": "https://escholarship.org/content/example.pdf",
                        "url": "https://escholarship.org/uc/item/example",
                        "host_type": "repository",
                        "version": "acceptedVersion",
                    },
                ],
            },
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        discovery = DirectResourceDiscovery(client)
        discovery.api_host_semaphores["api.unpaywall.org"] = asyncio.Semaphore(1)
        resources = await discovery._unpaywall("10.0000/example")

    assert [item.url for item in resources] == [
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/pdf/",
        "https://escholarship.org/content/example.pdf",
    ]


@pytest.mark.asyncio
async def test_phase1_hard_budget_cancels_slow_transfer(monkeypatch, tmp_path):
    class FakeScheduler:
        def __init__(self):
            self.direct_client = object()
            self.calls = 0

        async def attempt_candidates(
            self, paper, candidates, target, on_candidate_attempt=None
        ):
            self.calls += 1
            await asyncio.sleep(1)

    scheduler = FakeScheduler()
    pipeline = DirectDownloadPipeline(scheduler)
    pipeline.TOTAL_BUDGET_SECONDS = 0.05
    pipeline.DISCOVERY_BUDGET_SECONDS = 0.01
    pipeline.RESOURCE_BUDGET_SECONDS = 1
    resources = [
        DiscoveredPDFResource("metadata", f"https://example.org/{index}.pdf")
        for index in range(4)
    ]

    async def discover(paper, timeout=8.0):
        return resources, []

    monkeypatch.setattr(pipeline.discovery, "discover", discover)
    paper = PaperRecord(paper_id="spc:budget", title="Budget")
    started = time.monotonic()
    await pipeline.run(paper, str(tmp_path / "paper.pdf"), [])

    assert time.monotonic() - started < 0.2
    assert 1 <= scheduler.calls <= pipeline.MAX_PUBLIC_RESOURCES


@pytest.mark.asyncio
async def test_exact_europe_pmc_resource_gets_trusted_large_pdf_budget(
    monkeypatch, tmp_path
):
    class FakeScheduler:
        def __init__(self):
            self.direct_client = object()
            self.timeout = None

        async def attempt_candidates(
            self, paper, candidates, target, on_candidate_attempt=None
        ):
            self.timeout = candidates[0].metadata["attempt_timeout_seconds"]
            paper.fulltext_status.download_status = "downloaded"

    scheduler = FakeScheduler()
    pipeline = DirectDownloadPipeline(scheduler)

    async def discover(paper, timeout=8.0):
        return [
            DiscoveredPDFResource(
                "europe_pmc_doi",
                "https://europepmc.org/articles/PMC9498154?pdf=render",
                public_access="open",
                confidence="high",
            )
        ], []

    monkeypatch.setattr(pipeline.discovery, "discover", discover)
    paper = PaperRecord(
        paper_id="spc:epmc-budget",
        doi="10.3390/curroncol29090518",
        title="Europe PMC large PDF",
    )

    await pipeline.run(paper, str(tmp_path / "paper.pdf"), [])

    assert scheduler.timeout is not None
    assert scheduler.timeout > pipeline.RESOURCE_BUDGET_SECONDS
    assert scheduler.timeout <= pipeline.TRUSTED_REPOSITORY_RESOURCE_BUDGET_SECONDS


@pytest.mark.asyncio
async def test_trusted_repository_extends_only_bounded_total_budget(
    monkeypatch, tmp_path
):
    class FakeScheduler:
        direct_client = object()
        shared_client = object()

        def __init__(self):
            self.timeout = None

        async def attempt_candidates(
            self, paper, candidates, target, on_candidate_attempt=None
        ):
            self.timeout = candidates[0].metadata["attempt_timeout_seconds"]
            paper.fulltext_status.download_status = "downloaded"

    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)
    scheduler = FakeScheduler()
    pipeline = DirectDownloadPipeline(scheduler)

    async def discover(paper, timeout=10.0):
        return [
            DiscoveredPDFResource(
                "europe_pmc",
                "https://europepmc.org/articles/PMC9498154?pdf=render",
            )
        ], []

    monkeypatch.setattr(pipeline.discovery, "discover", discover)
    await pipeline.run(
        PaperRecord(paper_id="spc:large-epmc", title="Large PDF"),
        str(tmp_path / "paper.pdf"),
        [],
    )

    assert scheduler.timeout is not None
    assert (
        pipeline.RESOURCE_BUDGET_SECONDS
        < scheduler.timeout
        <= pipeline.TRUSTED_REPOSITORY_RESOURCE_BUDGET_SECONDS
    )
    assert (
        pipeline.TRUSTED_REPOSITORY_TOTAL_BUDGET_SECONDS > pipeline.TOTAL_BUDGET_SECONDS
    )


def test_timeout_audit_preserves_trusted_repository_transport(monkeypatch):
    class FakeScheduler:
        no_cache = True

        def _mark_route(self, status, route):
            status.attempted_routes.append(route)

        def _record_attempt(self, status, attempt):
            status.download_attempts.append(attempt.audit_dict())

    pipeline = DirectDownloadPipeline.__new__(DirectDownloadPipeline)
    pipeline.scheduler = FakeScheduler()
    paper = PaperRecord(paper_id="spc:timeout-audit", title="Timeout audit")
    candidate = PDFRouteCandidate(
        "public_http",
        url="https://europepmc.org/articles/PMC9498154?pdf=render",
        metadata={
            "proxy_mode": "no-proxy",
            "resource_fingerprint": "abc",
        },
    )

    pipeline._record_timeout(
        paper, candidate, 120000, "trusted_repository_budget_exhausted"
    )

    attempt = paper.fulltext_status.download_attempts[-1]
    assert attempt["proxy_mode"] == "no-proxy"
    assert attempt["client_kind"] == "direct_client"


@pytest.mark.asyncio
async def test_existing_pmc_resource_uses_trusted_budget_without_proxy(
    monkeypatch, tmp_path
):
    class FakeScheduler:
        direct_client = object()
        shared_client = object()

        def __init__(self):
            self.timeout = None
            self.proxy_mode = None

        async def attempt_candidates(
            self, paper, candidates, target, on_candidate_attempt=None
        ):
            self.timeout = candidates[0].metadata["attempt_timeout_seconds"]
            self.proxy_mode = candidates[0].metadata["proxy_mode"]
            paper.fulltext_status.download_status = "downloaded"

    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)
    scheduler = FakeScheduler()
    pipeline = DirectDownloadPipeline(scheduler)

    async def discover(paper, timeout=10.0):
        return [
            DiscoveredPDFResource(
                "europe_pmc",
                "https://europepmc.org/articles/PMC7643394?pdf=render",
                public_access="declared",
                confidence="medium",
            )
        ], []

    monkeypatch.setattr(pipeline.discovery, "discover", discover)
    await pipeline.run(
        PaperRecord(paper_id="spc:hbm", title="HBM"), str(tmp_path / "paper.pdf"), []
    )

    assert scheduler.timeout > pipeline.RESOURCE_BUDGET_SECONDS
    assert scheduler.timeout <= pipeline.TRUSTED_REPOSITORY_RESOURCE_BUDGET_SECONDS
    assert scheduler.proxy_mode == "no-proxy"


@pytest.mark.asyncio
async def test_openalex_repository_resource_gets_trusted_large_pdf_budget(
    monkeypatch, tmp_path
):
    class FakeScheduler:
        def __init__(self):
            self.direct_client = object()
            self.timeout = None
            self.proxy_mode = None

        async def attempt_candidates(
            self, paper, candidates, target, on_candidate_attempt=None
        ):
            self.timeout = candidates[0].metadata["attempt_timeout_seconds"]
            self.proxy_mode = candidates[0].metadata["proxy_mode"]
            paper.fulltext_status.download_status = "downloaded"

    from paperfetch.core.settings import reset_settings

    scheduler = FakeScheduler()
    monkeypatch.setenv("DOWNLOAD_PROXY", "http://127.0.0.1:7897")
    reset_settings()
    pipeline = DirectDownloadPipeline(scheduler)

    async def discover(paper, timeout=8.0):
        return [
            DiscoveredPDFResource(
                "openalex_repository",
                "https://freidok.uni-freiburg.de/files/275391/main.pdf",
                public_access="open",
                confidence="high",
            )
        ], []

    monkeypatch.setattr(pipeline.discovery, "discover", discover)
    paper = PaperRecord(paper_id="spc:repository-budget", title="Repository PDF")

    await pipeline.run(paper, str(tmp_path / "paper.pdf"), [])

    assert scheduler.timeout is not None
    assert scheduler.timeout > pipeline.RESOURCE_BUDGET_SECONDS
    assert scheduler.timeout <= pipeline.TRUSTED_REPOSITORY_RESOURCE_BUDGET_SECONDS
    assert scheduler.proxy_mode == "download-proxy"


def test_openalex_repository_uses_direct_client_when_download_proxy_is_absent(
    monkeypatch,
):
    class FakeScheduler:
        direct_client = object()
        shared_client = object()

    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)

    pipeline = DirectDownloadPipeline(FakeScheduler())

    assert pipeline.discovery.repository_client is FakeScheduler.direct_client


def test_false_download_proxy_means_no_proxy(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_PROXY", "false")

    assert trusted_repository_proxy_mode() == "no-proxy"


@pytest.mark.asyncio
async def test_openalex_repository_reports_no_proxy_when_download_proxy_is_absent(
    monkeypatch, tmp_path
):
    class FakeScheduler:
        direct_client = object()
        shared_client = object()

        def __init__(self):
            self.proxy_mode = None

        async def attempt_candidates(
            self, paper, candidates, target, on_candidate_attempt=None
        ):
            self.proxy_mode = candidates[0].metadata["proxy_mode"]
            paper.fulltext_status.download_status = "downloaded"

    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)
    scheduler = FakeScheduler()
    pipeline = DirectDownloadPipeline(scheduler)

    async def discover(paper, timeout=10.0):
        return [
            DiscoveredPDFResource(
                "openalex_repository",
                "https://freidok.uni-freiburg.de/files/275391/main.pdf",
            )
        ], []

    monkeypatch.setattr(pipeline.discovery, "discover", discover)
    await pipeline.run(
        PaperRecord(paper_id="spc:proxy-label", title="Proxy label"),
        str(tmp_path / "paper.pdf"),
        [],
    )

    assert scheduler.proxy_mode == "no-proxy"


@pytest.mark.asyncio
async def test_challenge_never_starts_browser(monkeypatch, tmp_path):
    class FakeScheduler:
        def __init__(self):
            self.direct_client = object()
            self.routes = []

        async def attempt_candidates(
            self, paper, candidates, target, on_candidate_attempt=None
        ):
            route = candidates[0].route
            self.routes.append(route)
            paper.fulltext_status.download_attempts.append(
                {"route": route, "error_class": "publisher_challenge"}
            )

    scheduler = FakeScheduler()
    pipeline = DirectDownloadPipeline(scheduler)

    async def discover(paper, timeout=8.0):
        return [
            DiscoveredPDFResource(
                "frontiers_rule",
                "https://www.frontiersin.org/articles/10.3389/test/pdf",
            )
        ], []

    monkeypatch.setattr(pipeline.discovery, "discover", discover)
    paper = PaperRecord(paper_id="spc:challenge", title="Challenge")
    await pipeline.run(paper, str(tmp_path / "paper.pdf"), [])

    assert scheduler.routes == ["public_http"]


@pytest.mark.asyncio
async def test_known_public_rsna_pdf_can_use_allowlisted_browser(monkeypatch, tmp_path):
    class FakeScheduler:
        def __init__(self):
            self.direct_client = object()
            self.routes = []

        async def attempt_candidates(
            self, paper, candidates, target, on_candidate_attempt=None
        ):
            candidate = candidates[0]
            self.routes.append(candidate.route)
            if candidate.route == "public_http":
                paper.fulltext_status.download_attempts.append(
                    {"route": candidate.route, "error_class": "publisher_challenge"}
                )
            else:
                assert candidate.metadata["known_public_pdf"] is True
                assert candidate.metadata["ordinary_html_confirmed"] is False

    scheduler = FakeScheduler()
    pipeline = DirectDownloadPipeline(scheduler)

    async def discover(paper, timeout=8.0):
        return [
            DiscoveredPDFResource(
                "rsna_rule",
                "https://pubs.rsna.org/doi/pdf/10.1148/ryai.230182",
                "https://pubs.rsna.org/doi/10.1148/ryai.230182",
                "open",
                "high",
            )
        ], []

    monkeypatch.setattr(pipeline.discovery, "discover", discover)
    paper = PaperRecord(paper_id="spc:rsna", doi="10.1148/ryai.230182", title="RSNA")
    await pipeline.run(paper, str(tmp_path / "paper.pdf"), [])

    assert scheduler.routes == ["public_http", "public_browser"]


def test_rate_limit_ttl_uses_retry_after_with_ten_minute_cap(tmp_path):
    cache = PDFGlobalCache(tmp_path / "cache")

    assert cache._failure_ttl("rate_limited", {"retry_after": "30"}) == 30
    assert cache._failure_ttl("rate_limited", {"retry_after": "3600"}) == 600


@pytest.mark.asyncio
async def test_missing_api_credentials_are_planned_skip_without_execution(
    monkeypatch, tmp_path
):
    class FakeScheduler:
        def __init__(self):
            self.direct_client = object()
            self.calls = 0

        async def attempt_candidates(self, *args, **kwargs):
            self.calls += 1

    scheduler = FakeScheduler()
    pipeline = DirectDownloadPipeline(scheduler)

    async def discover(paper, timeout=8.0):
        return [], []

    monkeypatch.setattr(pipeline.discovery, "discover", discover)
    paper = PaperRecord(paper_id="spc:skip", title="Skip")
    candidate = PDFRouteCandidate(
        "elsevier_api", metadata={"missing_credentials": True}
    )
    await pipeline.run(paper, str(tmp_path / "paper.pdf"), [candidate])

    assert scheduler.calls == 0
    assert paper.fulltext_status.discovery_events[0]["result"] == "planned_skip"


@pytest.mark.asyncio
async def test_new_medrxiv_doi_resolves_official_pdf_when_crossref_times_out(
    monkeypatch,
):
    doi = "10.64898/2026.04.28.26351937"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("26351937.full.pdf"):
            return httpx.Response(
                302,
                headers={
                    "Location": f"https://www.medrxiv.org/content/{doi}v1.full.pdf"
                },
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf", "Content-Length": "880212"},
            request=request,
        )

    async def no_result(*args, **kwargs):
        return []

    async def crossref_timeout(*args, **kwargs):
        raise httpx.ConnectTimeout("crossref unavailable")

    monkeypatch.setattr(DirectResourceDiscovery, "_semantic_scholar", no_result)
    monkeypatch.setattr(DirectResourceDiscovery, "_unpaywall", no_result)
    monkeypatch.setattr(DirectResourceDiscovery, "_crossref", crossref_timeout)
    monkeypatch.setattr(DirectResourceDiscovery, "_doi_landing", no_result)
    monkeypatch.setattr(DirectResourceDiscovery, "_europe_pmc_doi", no_result)
    monkeypatch.setattr(DirectResourceDiscovery, "_openalex_repository", no_result)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        trust_env=False,
    ) as client:
        paper = PaperRecord(
            paper_id="spc:existing-medrxiv",
            doi=doi,
            title="Predicting one-year postoperative functional status in contrast-enhancing glioma",
            journal="medRxiv",
        )
        paper.fulltext_status.pdf_url = f"https://doi.org/{doi}"
        paper.fulltext_status.pdf_source = "openalex_oa_url"
        paper.fulltext_status.pdf_candidates = [
            {
                "url": f"https://doi.org/{doi}",
                "source": "openalex_oa_url",
                "priority": 40,
            }
        ]
        resources, events = await DirectResourceDiscovery(client).discover(paper)

    candidates, _ = normalize_resources(resources)
    candidate = candidates[0]
    assert candidate.sources == ["medrxiv_rule"]
    assert candidate.url == f"https://www.medrxiv.org/content/{doi}v1.full.pdf"
    assert candidate.referer == f"https://www.medrxiv.org/content/{doi}v1"
    assert candidate.public_access == "open"
    assert candidate.confidence == "high"
    assert candidate.diagnostics == {
        "publisher_rule": "medrxiv_official_pdf",
        "canonical_version": "v1",
        "version_resolution": "official_versionless_pdf_redirect",
    }
    assert any(
        event["source"] == "crossref_tdm"
        and event["result"] == "error"
        and event["error_class"] == "ConnectTimeout"
        for event in events
    )


@pytest.mark.asyncio
async def test_medrxiv_rule_rejects_pdf_redirect_to_non_official_host():
    doi = "10.64898/2026.04.28.26351937"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.medrxiv.org":
            return httpx.Response(
                302,
                headers={
                    "Location": f"https://mirror.invalid/content/{doi}v1.full.pdf"
                },
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        trust_env=False,
    ) as client:
        resources = await DirectResourceDiscovery(client)._medrxiv_resource(doi)

    assert resources == []
