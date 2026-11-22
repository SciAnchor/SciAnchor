# -*- coding: utf-8 -*-

import asyncio

import httpx

from typing import Any, Optional
from dataclasses import dataclass
from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.base import (
    DownloadRunContext,
    PDFRouteCandidate,
    DownloadContext,
)
from paperfetch.downloaders.pipeline.scheduler import DownloadScheduler
from paperfetch.downloaders.pipeline.cache import PDFGlobalCache, PDFVerifier
from paperfetch.downloaders.pipeline.resolver import PDFResolver
from paperfetch.downloaders.backends.publisher_api.elsevier import ElsevierAPIBackend
from paperfetch.downloaders.pdf_common import PDFDownloadResult


@dataclass
class ElsevierAPIDownloadError(Exception):
    error_class: str
    message: str = ""
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    url: Optional[str] = None
    diagnostics: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message or self.error_class)


def elsevier_article_api_url(doi: str) -> str:
    from urllib.parse import quote

    cleaned = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    cleaned = cleaned.lstrip("/")
    return f"https://api.elsevier.com/content/article/doi/{quote(cleaned, safe='')}"


class ElsevierAPIDownloader:
    def __init__(
        self, client: httpx.AsyncClient, api_key: Optional[str] = None
    ) -> None:
        self.client = client
        self.api_key = api_key
        self._backend = ElsevierAPIBackend(api_key=api_key)

    async def download_pdf(
        self, doi: Optional[str], target_file: str
    ) -> PDFDownloadResult:
        if not doi:
            raise ElsevierAPIDownloadError("missing_doi")
        dummy_paper = PaperRecord(paper_id="dummy", title="dummy", doi=doi)
        dummy_candidate = PDFRouteCandidate("elsevier_api", priority=15)
        ctx = DownloadContext(
            paper=dummy_paper,
            candidate=dummy_candidate,
            target_file=target_file,
            run_context=None,
        )
        setattr(ctx, "client", self.client)
        try:
            return await self._backend.download(ctx)
        except Exception as e:
            from paperfetch.downloaders.pipeline.errors import DownloadError

            err = DownloadError.from_exception(e, route="elsevier_api")
            raise ElsevierAPIDownloadError(
                error_class=err.error_class,
                message=err.message,
                status_code=err.status_code,
                content_type=err.content_type,
                url=err.url,
                diagnostics=err.diagnostics,
            ) from e


def _run_context() -> DownloadRunContext:
    return DownloadRunContext(
        preflight={
            "proxy": {},
            "elsevier_api": {"configured": True, "route_state": "enabled"},
        }
    )


def test_elsevier_api_route_precedes_generic_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-key")
    monkeypatch.delenv("ELS_API_KEY", raising=False)

    resolver = PDFResolver(
        PDFGlobalCache(tmp_path / "cache"), run_context=_run_context()
    )
    paper = PaperRecord(
        paper_id="spc:elsevier",
        doi="10.1016/j.cities.2023.104510",
        title="Elsevier paper",
    )
    routes = resolver.resolve(paper, str(tmp_path / "pdf"))

    route_names = [candidate.route for candidate in routes]
    api_route = next(
        candidate for candidate in routes if candidate.route == "elsevier_api"
    )

    assert api_route.priority == 15
    assert api_route.url == elsevier_article_api_url("10.1016/j.cities.2023.104510")
    assert api_route.metadata["database_key"] == "sciencedirect"
    assert api_route.metadata["database_match_reason"] == "doi_prefix_match"
    assert api_route.metadata["route_provider"] == "elsevier_api"
    assert "doi_landing" not in route_names
    assert "publisher_resolver" not in route_names
    assert not any(name.startswith(("csust", "cstcloud")) for name in route_names)


def test_elsevier_api_route_requires_key_and_prefix(tmp_path, monkeypatch):
    resolver = PDFResolver(
        PDFGlobalCache(tmp_path / "cache"), run_context=_run_context()
    )

    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    monkeypatch.delenv("ELS_API_KEY", raising=False)
    no_key_routes = resolver.resolve(
        PaperRecord(paper_id="spc:no-key", doi="10.1016/example", title="No key"),
        str(tmp_path / "pdf"),
    )
    elsevier_route = next(
        (cand for cand in no_key_routes if cand.route == "elsevier_api"), None
    )
    assert elsevier_route is not None
    assert elsevier_route.metadata.get("error_class") == "missing_credentials"

    monkeypatch.setenv("ELSEVIER_API_KEY", "test-key")
    non_elsevier_routes = resolver.resolve(
        PaperRecord(paper_id="spc:non-sd", doi="10.1109/example", title="Non Elsevier"),
        str(tmp_path / "pdf"),
    )
    assert not any(
        candidate.route == "elsevier_api" for candidate in non_elsevier_routes
    )


def test_elsevier_api_downloader_writes_pdf_without_query_key(tmp_path):
    class FakeClient:
        def __init__(self):
            self.calls = []

        async def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            request = httpx.Request(method, url)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/pdf"},
                content=b"%PDF-1.4\n" + b"x" * 256,
                request=request,
            )

    client = FakeClient()
    target = tmp_path / "paper.pdf"
    result = asyncio.run(
        ElsevierAPIDownloader(client, api_key="test-key").download_pdf(
            "10.1016/j.cities.2023.104510", str(target)
        )
    )

    method, url, kwargs = client.calls[0]
    assert method == "GET"
    assert "apiKey" not in url
    assert kwargs["headers"]["X-ELS-APIKey"] == "test-key"
    assert kwargs["headers"]["Accept"] == "application/pdf"
    assert target.read_bytes().startswith(b"%PDF")
    assert result.source == "elsevier_api"
    assert result.content_type == "application/pdf"


def test_elsevier_api_never_sends_institution_token(tmp_path, monkeypatch):
    class FakeClient:
        def __init__(self):
            self.calls = []

        async def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            request = httpx.Request(method, url)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/pdf"},
                content=b"%PDF-1.4\n" + b"x" * 256,
                request=request,
            )

    monkeypatch.setenv("ELSEVIER_INSTTOKEN", "institution-secret")
    client = FakeClient()
    asyncio.run(
        ElsevierAPIDownloader(client, api_key="api-secret").download_pdf(
            "10.1016/j.cities.2023.104510",
            str(tmp_path / "paper.pdf"),
        )
    )

    _method, url, kwargs = client.calls[0]
    assert "institution-secret" not in url
    assert "X-ELS-Insttoken" not in kwargs["headers"]
    assert kwargs["headers"]["X-ELS-APIKey"] == "api-secret"


def test_elsevier_api_error_maps_to_route_attempt(tmp_path):
    class FakeProxyPolicy:
        def mode_for_candidate(self, candidate):
            return "no-proxy"

    class FakeFetcher:
        proxy_policy = FakeProxyPolicy()

    scheduler = DownloadScheduler(
        FakeFetcher(),
        PDFGlobalCache(tmp_path / "cache"),
        PDFVerifier(),
        retry_failed=True,
    )
    candidate = PDFRouteCandidate(
        "elsevier_api", url=elsevier_article_api_url("10.1016/example")
    )
    exc = ElsevierAPIDownloadError(
        "auth_failed",
        status_code=403,
        content_type="text/xml",
        url=candidate.url,
        diagnostics={"status_code": 403},
    )

    attempt = scheduler._attempt_from_exception(candidate, exc)

    assert attempt.route == "elsevier_api"
    assert attempt.error_class == "auth_failed"
    assert attempt.status_code == 403
    assert attempt.content_type == "text/xml"
    assert attempt.diagnostics == {"status_code": 403}


def test_elsevier_api_downloader_raises_subscription_required_on_warning_header(
    tmp_path,
):
    class FakeClient:
        async def request(self, method, url, **kwargs):
            request = httpx.Request(method, url)
            return httpx.Response(
                200,
                headers={
                    "Content-Type": "application/pdf",
                    "X-ELS-Status": "WARNING - Response limited to first page because requestor not entitled to resource",
                },
                content=b"%PDF-1.4\n" + b"x" * 256,
                request=request,
            )

    client = FakeClient()
    target = tmp_path / "paper.pdf"

    import pytest

    with pytest.raises(ElsevierAPIDownloadError) as exc_info:
        asyncio.run(
            ElsevierAPIDownloader(client, api_key="test-key").download_pdf(
                "10.1016/j.cities.2023.104510", str(target)
            )
        )

    assert exc_info.value.error_class == "subscription_required"
    assert exc_info.value.message == "Elsevier API 当前凭证无订阅全文权限"
    assert "limited to first page" in exc_info.value.diagnostics["authorization_status"]
