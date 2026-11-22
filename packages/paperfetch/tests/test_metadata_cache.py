import asyncio
import sqlite3

import pytest

from paperfetch.utils.cache import LocalMetadataCache, metadata_cache_key


class FakeClock:
    def __init__(self, value: float = 1000.0):
        self.value = value

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += seconds


@pytest.mark.asyncio
async def test_cache_ttl_schema_and_authoritative_negative(tmp_path):
    clock = FakeClock()
    cache = LocalMetadataCache(str(tmp_path / "cache.db"), now=clock.now)
    await cache.set(
        "paper", {"title": "A"}, "openalex", ttl_seconds=10, schema_version="v1"
    )
    assert (await cache.get_entry("paper", expected_schema="v1")).state == "hit"
    assert (await cache.get_entry("paper", expected_schema="v2")).state == "miss"

    clock.value += 11
    assert (await cache.get_entry("paper", expected_schema="v1")).state == "stale"

    await cache.set_not_found("missing", "openalex", ttl_seconds=5, schema_version="v1")
    negative = await cache.get_entry("missing", expected_schema="v1")
    assert negative.state == "negative"
    assert negative.data is None


@pytest.mark.asyncio
async def test_cache_singleflight_is_cross_instance_and_released(tmp_path):
    db_path = str(tmp_path / "cache.db")
    first = LocalMetadataCache(db_path)
    second = LocalMetadataCache(db_path)
    entered = asyncio.Event()

    async def first_owner():
        async with first.request_lease("same-request", lease_seconds=3):
            entered.set()
            await asyncio.sleep(0.15)
            await first.set("result", {"ok": True}, "s2", ttl_seconds=10)

    async def second_owner():
        await entered.wait()
        async with second.request_lease("same-request", lease_seconds=3):
            return await second.get("result")

    owner = asyncio.create_task(first_owner())
    waiter = asyncio.create_task(second_owner())
    await owner
    assert await asyncio.wait_for(waiter, timeout=2) == {"ok": True}


@pytest.mark.asyncio
async def test_cache_request_lease_recovers_after_owner_crash(tmp_path):
    clock = FakeClock()
    db_path = str(tmp_path / "cache.db")
    crashed = LocalMetadataCache(db_path, now=clock.now, sleep=clock.sleep)
    recovered = LocalMetadataCache(db_path, now=clock.now, sleep=clock.sleep)
    await crashed.acquire_request("same", lease_seconds=2)

    new_token = await recovered.acquire_request("same", lease_seconds=2)

    assert new_token
    assert clock.value >= 1002


@pytest.mark.asyncio
async def test_corrupt_cache_is_not_silently_treated_as_miss(tmp_path):
    db_path = tmp_path / "cache.db"
    cache = LocalMetadataCache(str(db_path))
    await cache.initialize()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO work_cache(key, source, data, value_status) VALUES ('bad','s2','{','value')"
        )

    with pytest.raises(RuntimeError, match="缓存记录损坏"):
        await cache.get_entry("bad")


def test_versioned_cache_key_hides_identity_and_separates_field_contracts():
    first = metadata_cache_key(
        "openalex",
        "lookup",
        "10.1000/secret-doi",
        api_version="v1",
        fields_version="core-v1",
    )
    second = metadata_cache_key(
        "openalex",
        "lookup",
        "10.1000/secret-doi",
        api_version="v1",
        fields_version="core-v2",
    )
    assert "10.1000" not in first
    assert first != second


def test_default_cache_path_uses_runtime_cache_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SPC_CACHE_ROOT", str(tmp_path / "cache-root"))
    monkeypatch.delenv("SPC_METADATA_CACHE_DB", raising=False)
    assert LocalMetadataCache._resolve_default_db_path() == str(
        (tmp_path / "cache-root" / "metadata.sqlite3").resolve()
    )
