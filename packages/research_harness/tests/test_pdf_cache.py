"""Tests for the verified PDF cache and failure TTL cache."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx

from research_harness.acquisition.pdf_cache import (
    CACHE_DIR_ENV,
    FAILURE_TTL_ENV,
    FailureTTLCache,
    VerifiedPDFCache,
    pdf_cache_key,
)


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4\n" + b"0" * 12_000


class TestKeyDerivation:
    def test_doi_wins_and_is_sanitized(self):
        assert pdf_cache_key(doi="10.5555/RAG.2026") == "doi_10.5555_rag.2026"

    def test_arxiv_fallback(self):
        assert pdf_cache_key(arxiv_id="2601.00001") == "arxiv_2601.00001"

    def test_title_hash_fallback_is_stable(self):
        key_a = pdf_cache_key(title="Some Paper")
        key_b = pdf_cache_key(title="some paper")
        assert key_a == key_b
        assert key_a.startswith("title_")


class TestVerifiedPDFCache:
    def test_disabled_without_env(self, monkeypatch):
        monkeypatch.delenv(CACHE_DIR_ENV, raising=False)
        cache = VerifiedPDFCache.from_env()
        assert cache.enabled is False
        assert cache.find("doi_x") is None
        assert cache.store("doi_x", Path("/nonexistent")) is None

    def test_store_then_find_roundtrip(self, tmp_path):
        cache = VerifiedPDFCache(tmp_path / "cache")
        source = tmp_path / "paper.pdf"
        source.write_bytes(_pdf_bytes())

        stored = cache.store("doi_a", source)

        assert stored is not None and stored.is_file()
        assert cache.find("doi_a") == stored

    def test_non_pdf_and_small_files_are_never_stored(self, tmp_path):
        cache = VerifiedPDFCache(tmp_path / "cache")
        html = tmp_path / "page.pdf"
        html.write_bytes(b"<html>nope</html>" + b"0" * 12_000)
        tiny = tmp_path / "tiny.pdf"
        tiny.write_bytes(b"%PDF-1.4 tiny")

        assert cache.store("doi_html", html) is None
        assert cache.store("doi_tiny", tiny) is None

    def test_corrupted_cache_entry_is_not_served(self, tmp_path):
        cache = VerifiedPDFCache(tmp_path / "cache")
        target = cache.path_for("doi_bad")
        target.parent.mkdir(parents=True)
        target.write_bytes(b"corrupt")

        assert cache.find("doi_bad") is None


class TestFailureTTLCache:
    def test_disabled_without_env(self, monkeypatch):
        monkeypatch.delenv(CACHE_DIR_ENV, raising=False)
        cache = FailureTTLCache.from_env()
        assert cache.enabled is False
        assert cache.get_fresh("k", "r", "h") is None

    def test_zero_ttl_disables(self, tmp_path):
        cache = FailureTTLCache(tmp_path, 0)
        assert cache.enabled is False

    def test_record_then_fresh_lookup(self, tmp_path):
        cache = FailureTTLCache(tmp_path, 3600)

        cache.record("doi_a", "doi_landing", "doi.org", "paywall")

        entry = cache.get_fresh("doi_a", "doi_landing", "doi.org")
        assert entry is not None
        assert entry["error_class"] == "paywall"
        assert cache.get_fresh("doi_a", "other_route", "doi.org") is None

    def test_expired_entry_is_not_fresh(self, tmp_path):
        cache = FailureTTLCache(tmp_path, 3600)
        cache.record("doi_a", "doi_landing", "doi.org", "paywall")
        store = json.loads((tmp_path / "failures.json").read_text())
        for entry in store.values():
            entry["recorded_at"] = time.time() - 7200
        (tmp_path / "failures.json").write_text(json.dumps(store))

        assert cache.get_fresh("doi_a", "doi_landing", "doi.org") is None

    def test_corrupt_store_is_tolerated(self, tmp_path):
        (tmp_path / "failures.json").write_text("{broken")
        cache = FailureTTLCache(tmp_path, 3600)

        assert cache.get_fresh("k", "r", "h") is None
        cache.record("k", "r", "h", "paywall")
        assert cache.get_fresh("k", "r", "h") is not None


class TestDownloaderWiring:
    def _candidate(self):
        from research_harness.pdf_download import PaperDownloadCandidate

        return PaperDownloadCandidate(
            paper_id=1,
            title="Cache Wiring Paper",
            doi="10.5555/cache.1",
            url="https://files.example.org/cache1.pdf",
        )

    def test_cache_hit_avoids_network(self, tmp_path, monkeypatch):
        from research_harness.acquisition import downloader

        cache_dir = tmp_path / "cache"
        monkeypatch.setenv(CACHE_DIR_ENV, str(cache_dir))
        # Identity audit must pass for the cached file to be served.
        monkeypatch.setattr(downloader, "_pdf_identity_failure", lambda c, p: None)

        class _NoNetworkClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, **kwargs):
                raise AssertionError(f"network fetch attempted: {url}")

        monkeypatch.setattr(httpx, "AsyncClient", _NoNetworkClient)

        candidate = self._candidate()
        key = pdf_cache_key(doi=candidate.doi)
        seeded = VerifiedPDFCache(cache_dir)
        source = tmp_path / "seed.pdf"
        source.write_bytes(_pdf_bytes())
        assert seeded.store(key, source) is not None

        result = asyncio.run(
            downloader.download_single(
                candidate, tmp_path / "out", asyncio.Semaphore(1)
            )
        )

        assert result.status == "success"
        assert result.provider == "local_cache"
        assert result.audit is not None
        assert result.audit.successful_route == "local_cache"
        assert result.audit.cache_hit is True
        assert Path(result.path).is_file()

    def test_fresh_failure_skips_route_without_fetch(self, tmp_path, monkeypatch):
        from research_harness.acquisition import downloader

        cache_dir = tmp_path / "cache"
        monkeypatch.setenv(CACHE_DIR_ENV, str(cache_dir))
        monkeypatch.setenv(FAILURE_TTL_ENV, "3600")

        candidate = self._candidate()
        key = pdf_cache_key(doi=candidate.doi)
        failure = FailureTTLCache(cache_dir, 3600)
        # RH caches the managed route; SPC owns its individual upstream routes.
        failure.record(key, "spc", "", "paywall")
        from research_harness.acquisition import spc_bridge

        def no_spc(*args, **kwargs):
            raise AssertionError("cached failure must not launch SPC")

        monkeypatch.setattr(spc_bridge, "spc_download", no_spc)

        class _NoNetworkClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, **kwargs):
                raise AssertionError(f"network fetch attempted: {url}")

        monkeypatch.setattr(httpx, "AsyncClient", _NoNetworkClient)

        result = asyncio.run(
            downloader.download_single(
                candidate, tmp_path / "out", asyncio.Semaphore(1)
            )
        )

        assert result.status != "success"
        assert result.audit is not None
        skipped = [
            attempt
            for attempt in result.audit.attempts
            if attempt.decision_reason == "failure_cache_ttl"
        ]
        assert skipped and all(attempt.skipped for attempt in skipped)

    def test_failures_are_recorded_after_run(self, tmp_path, monkeypatch):
        from research_harness.acquisition import downloader

        cache_dir = tmp_path / "cache"
        monkeypatch.setenv(CACHE_DIR_ENV, str(cache_dir))
        monkeypatch.setenv(FAILURE_TTL_ENV, "3600")

        class _TimeoutClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, **kwargs):
                import httpx

                raise httpx.ConnectError("boom")

        from research_harness.acquisition import spc_bridge
        import subprocess

        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("spc", 300)

        monkeypatch.setattr(spc_bridge, "spc_download", timeout)

        candidate = self._candidate()
        result = asyncio.run(
            downloader.download_single(
                candidate, tmp_path / "out", asyncio.Semaphore(1)
            )
        )

        assert result.status != "success"
        store = json.loads((cache_dir / "failures.json").read_text())
        assert store
        assert all(entry["error_class"] == "TimeoutExpired" for entry in store.values())
