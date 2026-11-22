import asyncio

import httpx
import pytest

from paperfetch.sources.s2_pool import PersistentS2KeyPool
from paperfetch.sources.semantic_scholar import (
    SemanticScholarAuthenticationError,
    SemanticScholarSource,
)
from paperfetch.utils.cache import LocalMetadataCache


@pytest.mark.asyncio
async def test_keyed_429_is_internal_and_next_key_returns_data(tmp_path):
    calls = []

    class Client:
        async def request(self, method, url, **kwargs):
            calls.append(kwargs["headers"]["x-api-key"])
            request = httpx.Request(method, url)
            if len(calls) == 1:
                return httpx.Response(
                    429, request=request, headers={"Retry-After": "0.01"}
                )
            return httpx.Response(200, request=request, json={"data": []})

    pool = PersistentS2KeyPool(
        ["key-a", "key-b"],
        db_path=tmp_path / "pool.db",
        min_interval_seconds=0,
    )
    source = SemanticScholarSource(Client(), key_pool=pool)
    response = await source._send_request_with_key_rotator(
        "GET", "/paper/search", params={"query": "x"}
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert calls[0] != calls[1]


@pytest.mark.asyncio
async def test_all_rejected_keys_raise_permanent_auth_error(tmp_path):
    class Client:
        async def request(self, method, url, **kwargs):
            return httpx.Response(403, request=httpx.Request(method, url))

    pool = PersistentS2KeyPool(
        ["key-a", "key-b"],
        db_path=tmp_path / "pool.db",
        min_interval_seconds=0,
    )
    source = SemanticScholarSource(Client(), key_pool=pool)

    with pytest.raises(SemanticScholarAuthenticationError):
        await source._send_request_with_key_rotator(
            "GET", "/paper/search", params={"query": "x"}
        )


@pytest.mark.asyncio
async def test_quota_403_is_cooling_not_auth_rejection(tmp_path):
    calls = 0

    class Client:
        async def request(self, method, url, **kwargs):
            nonlocal calls
            calls += 1
            request = httpx.Request(method, url)
            if calls == 1:
                return httpx.Response(
                    403,
                    request=request,
                    headers={"Retry-After": "0.01"},
                    text="API quota rate limit exceeded",
                )
            return httpx.Response(200, request=request, json={"data": []})

    pool = PersistentS2KeyPool(
        ["key-a", "key-b"],
        db_path=tmp_path / "pool.db",
        min_interval_seconds=0,
    )
    source = SemanticScholarSource(Client(), key_pool=pool)
    response = await source._send_request_with_key_rotator(
        "GET", "/paper/search", params={"query": "x"}
    )

    assert response.status_code == 200
    assert (await pool.snapshot())["disabled"] == 0


@pytest.mark.asyncio
async def test_lookup_authoritative_404_is_negative_cached(monkeypatch, tmp_path):
    calls = 0

    class Client:
        async def request(self, method, url, **kwargs):
            nonlocal calls
            calls += 1
            return httpx.Response(404, request=httpx.Request(method, url))

    cache = LocalMetadataCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("paperfetch.sources.semantic_scholar.global_cache", cache)
    pool = PersistentS2KeyPool(
        ["key"], db_path=tmp_path / "pool.db", min_interval_seconds=0
    )
    source = SemanticScholarSource(Client(), key_pool=pool)

    assert await source.lookup("10.1000/missing") is None
    assert await source.lookup("10.1000/missing") is None
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_identical_lookup_is_singleflight(monkeypatch, tmp_path):
    calls = 0

    class Client:
        async def request(self, method, url, **kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.1)
            return httpx.Response(
                200,
                request=httpx.Request(method, url),
                json={
                    "paperId": "s2-id",
                    "title": "Reliable metadata",
                    "externalIds": {"DOI": "10.1000/reliable"},
                    "authors": [],
                },
            )

    cache = LocalMetadataCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr("paperfetch.sources.semantic_scholar.global_cache", cache)
    pool = PersistentS2KeyPool(
        ["key-a", "key-b"],
        db_path=tmp_path / "pool.db",
        min_interval_seconds=0,
    )
    source = SemanticScholarSource(Client(), key_pool=pool)

    first, second = await asyncio.gather(
        source.lookup("10.1000/reliable"),
        source.lookup("10.1000/reliable"),
    )

    assert first.doi == second.doi == "10.1000/reliable"
    assert calls == 1


@pytest.mark.asyncio
async def test_cancelled_request_releases_key_lease(tmp_path):
    started = asyncio.Event()

    class Client:
        async def request(self, method, url, **kwargs):
            started.set()
            await asyncio.Event().wait()

    pool = PersistentS2KeyPool(
        ["key"], db_path=tmp_path / "pool.db", min_interval_seconds=0
    )
    source = SemanticScholarSource(Client(), key_pool=pool)
    task = asyncio.create_task(
        source._send_request_with_key_rotator(
            "GET", "/paper/search", params={"query": "x"}
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (await pool.snapshot())["leased"] == 0
