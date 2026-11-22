import asyncio
import multiprocessing
import sqlite3

import pytest

from paperfetch.sources.key_pool import PersistentApiKeyPool
from paperfetch.sources.s2_pool import (
    PersistentS2KeyPool,
    S2KeyPoolUnavailableError,
    key_fingerprint,
    semantic_scholar_state_db,
)


class FakeClock:
    def __init__(self, value: float = 1000.0):
        self.value = value
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def _acquire_in_process(db_path: str, acquired) -> None:
    async def run() -> None:
        pool = PersistentS2KeyPool(
            ["secret"], db_path=db_path, min_interval_seconds=0, lease_seconds=3
        )
        lease = await pool.acquire()
        acquired.set()
        await pool.release(lease)

    asyncio.run(run())


@pytest.mark.asyncio
async def test_all_rate_limited_keys_wait_until_earliest_recovery(tmp_path):
    clock = FakeClock()
    pool = PersistentS2KeyPool(
        ["secret-a", "secret-b"],
        db_path=tmp_path / "pool.db",
        min_interval_seconds=0,
        now=clock.now,
        sleep=clock.sleep,
    )
    first = await pool.acquire()
    second = await pool.acquire()
    await pool.report_rate_limit(first, 5)
    await pool.report_rate_limit(second, 8)

    recovered = await pool.acquire()

    assert recovered.key == "secret-a"
    assert clock.value >= 1005
    assert clock.sleeps


@pytest.mark.asyncio
async def test_pool_is_shared_across_instances_and_releases_lease(tmp_path):
    db_path = tmp_path / "pool.db"
    first_pool = PersistentS2KeyPool(
        ["secret"], db_path=db_path, min_interval_seconds=0, lease_seconds=3
    )
    second_pool = PersistentS2KeyPool(
        ["secret"], db_path=db_path, min_interval_seconds=0, lease_seconds=3
    )
    first = await first_pool.acquire()
    waiter = asyncio.create_task(second_pool.acquire())
    await asyncio.sleep(0.05)
    assert not waiter.done()

    await first_pool.release(first)
    second = await asyncio.wait_for(waiter, timeout=2)
    assert second.key == "secret"


@pytest.mark.asyncio
async def test_pool_lease_is_enforced_across_processes(tmp_path):
    db_path = tmp_path / "pool.db"
    owner = PersistentS2KeyPool(
        ["secret"], db_path=db_path, min_interval_seconds=0, lease_seconds=3
    )
    lease = await owner.acquire()
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    process = context.Process(target=_acquire_in_process, args=(str(db_path), acquired))
    process.start()
    await asyncio.sleep(0.2)
    assert not acquired.is_set()

    await owner.release(lease)
    assert await asyncio.to_thread(acquired.wait, 3)
    await asyncio.to_thread(process.join, 3)
    assert process.exitcode == 0


@pytest.mark.asyncio
async def test_expired_lease_recovers_after_owner_crash(tmp_path):
    clock = FakeClock()
    db_path = tmp_path / "pool.db"
    crashed_pool = PersistentS2KeyPool(
        ["secret"],
        db_path=db_path,
        min_interval_seconds=0,
        lease_seconds=2,
        now=clock.now,
        sleep=clock.sleep,
    )
    recovered_pool = PersistentS2KeyPool(
        ["secret"],
        db_path=db_path,
        min_interval_seconds=0,
        lease_seconds=2,
        now=clock.now,
        sleep=clock.sleep,
    )
    await crashed_pool.acquire()

    recovered = await recovered_pool.acquire()

    assert recovered.key == "secret"
    assert clock.value >= 1002


@pytest.mark.asyncio
async def test_rejected_keys_are_permanent_and_secret_is_not_persisted(tmp_path):
    db_path = tmp_path / "pool.db"
    pool = PersistentS2KeyPool(["top-secret-value"], db_path=db_path)
    lease = await pool.acquire()
    await pool.report_auth_rejected(lease, "http_403")

    with pytest.raises(S2KeyPoolUnavailableError):
        await pool.acquire()

    assert b"top-secret-value" not in db_path.read_bytes()
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT key_id, disabled FROM api_keys WHERE provider='semantic_scholar'"
        ).fetchone()
    assert row == (key_fingerprint("top-secret-value"), 1)


@pytest.mark.asyncio
async def test_snapshot_has_counts_without_key_material(tmp_path):
    pool = PersistentS2KeyPool(
        ["a-secret", "b-secret"],
        db_path=tmp_path / "pool.db",
        min_interval_seconds=0,
    )
    lease = await pool.acquire()
    snapshot = await pool.snapshot()

    assert snapshot == {
        "configured": 2,
        "ready": 1,
        "cooling": 0,
        "leased": 1,
        "disabled": 0,
    }
    assert "secret" not in str(snapshot)
    await pool.release(lease)


def test_default_pool_path_uses_runtime_state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SPC_STATE_ROOT", str(tmp_path / "state-root"))
    monkeypatch.delenv("SEMANTIC_SCHOLAR_STATE_DB", raising=False)
    assert (
        semantic_scholar_state_db()
        == (tmp_path / "state-root" / "provider-keys.sqlite3").resolve()
    )


@pytest.mark.asyncio
async def test_provider_key_leases_are_isolated_in_shared_database(tmp_path):
    db_path = tmp_path / "provider-keys.db"
    s2 = PersistentApiKeyPool(
        "semantic_scholar",
        ["same-secret"],
        db_path=db_path,
        min_interval_seconds=0,
    )
    openalex = PersistentApiKeyPool(
        "openalex",
        ["same-secret"],
        db_path=db_path,
        min_interval_seconds=0,
    )

    s2_lease = await s2.acquire()
    openalex_lease = await openalex.acquire()

    assert s2_lease.key == openalex_lease.key == "same-secret"
    assert (await s2.snapshot())["leased"] == 1
    assert (await openalex.snapshot())["leased"] == 1
    await s2.release(s2_lease)
    await openalex.release(openalex_lease)
