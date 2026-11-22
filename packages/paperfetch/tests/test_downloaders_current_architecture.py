# -*- coding: utf-8 -*-

import json

import pytest

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.base import DownloadRunContext, PDFRouteCandidate
from paperfetch.downloaders.pipeline.cache import PDFGlobalCache
from paperfetch.downloaders.pipeline.errors import DownloadError
from paperfetch.downloaders.pipeline.direct import DirectDownloadPipeline
from paperfetch.downloaders.pipeline.manager import PDFDownloadManager
from paperfetch.downloaders.pipeline.orchestrator import BatchOrchestrator
from paperfetch.downloaders.pipeline.resolver import PDFResolver
from paperfetch.downloaders.pipeline.scheduler import DownloadScheduler


def test_phase1_api_budget_fits_default_validation_p95_gate():
    assert DirectDownloadPipeline.API_BUDGET_SECONDS <= 12.5


def test_oa_browser_headless_default_is_platform_aware():
    from paperfetch.downloaders.browser.auth_pool import resolve_browser_headless

    assert resolve_browser_headless(None, platform_name="nt") is False
    assert resolve_browser_headless(None, platform_name="posix") is True
    assert resolve_browser_headless("true", platform_name="nt") is True
    assert resolve_browser_headless("false", platform_name="posix") is False


@pytest.mark.asyncio
async def test_oa_browser_pool_uses_ephemeral_context(monkeypatch):
    from paperfetch.downloaders.browser.auth_pool import BrowserPool

    captured = {}

    class FakeContext:
        async def add_init_script(self, _script):
            return None

        async def close(self):
            return None

    class FakeChromium:
        async def launch(self, **kwargs):
            captured["kwargs"] = kwargs
            return FakeBrowser()

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured["context_kwargs"] = kwargs
            return FakeContext()

        async def close(self):
            return None

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()

        async def stop(self):
            return None

    class FakeAsyncPlaywright:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setenv("PDF_BROWSER_HEADLESS", "true")
    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)
    monkeypatch.setattr(
        "paperfetch.downloaders.browser.auth_pool.async_playwright",
        lambda: FakeAsyncPlaywright(),
    )
    monkeypatch.setattr(
        "paperfetch.downloaders.browser.auth_pool.PLAYWRIGHT_AVAILABLE",
        True,
    )
    monkeypatch.setattr(
        "paperfetch.downloaders.browser.auth_pool.resolve_chrome_executable_path",
        lambda: r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )

    pool = BrowserPool()
    await pool.start()
    context = await pool.get_context()
    try:
        assert captured["kwargs"]["executable_path"].endswith("chrome.exe")
        assert captured["kwargs"]["headless"] is True
        assert captured["context_kwargs"]["accept_downloads"] is True
        await context.close()
    finally:
        await pool.close()


def test_download_manager_exposes_run_context(tmp_path, monkeypatch):
    manager = PDFDownloadManager(str(tmp_path / "pdf"), cache_root=tmp_path / "cache")
    try:
        assert isinstance(manager.run_context, DownloadRunContext)
        assert manager.scheduler.run_context is manager.run_context
        assert manager.resolver.run_context is manager.run_context
        assert manager.run_context.preflight == {}
    finally:
        import asyncio

        asyncio.run(manager.close())


def test_fast_phase_keeps_only_official_api_candidates():
    routes = {"elsevier_api", "publisher_api_springer"}
    candidates = [
        PDFRouteCandidate("local_cache", priority=1),
        PDFRouteCandidate("elsevier_api", priority=15),
        PDFRouteCandidate("publisher_api_springer", priority=15),
    ]

    selected = BatchOrchestrator._fast_candidates(candidates, routes)

    assert {candidate.route for candidate in selected} == routes


def test_download_error_classifies_chrome_network_error():
    chrome_error = DownloadError.from_exception(
        RuntimeError(
            'Page.goto: Navigation interrupted by "chrome-error://chromewebdata/"'
        ),
        route="public_browser",
    )

    assert chrome_error.error_class == "network_error"


def test_download_error_preserves_playwright_timeout_class():
    playwright_timeout = type("TimeoutError", (Exception,), {})

    error = DownloadError.from_exception(
        playwright_timeout("Timeout 30000ms exceeded"),
        route="public_browser",
    )

    assert error.error_class == "timeout"
