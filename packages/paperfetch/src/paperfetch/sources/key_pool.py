"""受配额 API provider 共用的跨进程可靠 Key 调度状态。

数据库只保存高熵 API key 的 SHA-256 指纹、租约和冷却时间，不保存明文凭证。
业务调用在所有 key 冷却时等待最早恢复时间；租约到期使异常退出的进程可自动恢复。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from paperfetch.core.config_v1 import runtime_state_root


class ApiKeyPoolUnavailableError(RuntimeError):
    """所有已配置 key 都被上游永久拒绝。"""


@dataclass(frozen=True)
class ApiKeyLease:
    key: str
    key_id: str
    token: str


def provider_key_state_db() -> Path:
    explicit = (os.getenv("SPC_API_KEY_STATE_DB") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return runtime_state_root() / "provider-keys.sqlite3"


def key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class PersistentApiKeyPool:
    """SQLite-backed key lease/cooldown pool shared by CLI jobs and processes."""

    def __init__(
        self,
        provider: str,
        keys: Sequence[str],
        *,
        db_path: str | os.PathLike[str] | None = None,
        min_interval_seconds: float = 1.1,
        lease_seconds: float = 60.0,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        normalized_provider = provider.strip().casefold().replace("-", "_")
        if (
            not normalized_provider
            or not normalized_provider.replace("_", "").isalnum()
        ):
            raise ValueError("无效 provider")
        self.provider = normalized_provider
        unique = dict.fromkeys(key.strip() for key in keys if key.strip())
        self._keys = {key_fingerprint(key): key for key in unique}
        self.db_path = (
            Path(db_path).expanduser().resolve() if db_path else provider_key_state_db()
        )
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.lease_seconds = max(1.0, float(lease_seconds))
        self._now = now
        self._sleep = sleep
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    @property
    def key_count(self) -> int:
        return len(self._keys)

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize_sync(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    provider TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    available_at REAL NOT NULL DEFAULT 0,
                    leased_until REAL NOT NULL DEFAULT 0,
                    lease_token TEXT,
                    last_used_at REAL NOT NULL DEFAULT 0,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    last_status TEXT,
                    consecutive_429 INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(provider, key_id)
                );
                CREATE TABLE IF NOT EXISTS provider_state (
                    provider TEXT PRIMARY KEY,
                    available_at REAL NOT NULL DEFAULT 0,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    last_status TEXT,
                    updated_at REAL NOT NULL DEFAULT 0
                );
                """
            )
            now = self._now()
            connection.execute(
                """
                UPDATE api_keys SET disabled=0, last_status='auth_recheck_due', updated_at=?
                WHERE provider=? AND disabled=1 AND updated_at < ?
                """,
                (now, self.provider, now - 86400.0),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO api_keys(provider, key_id, updated_at) VALUES (?, ?, ?)",
                [(self.provider, key_id, now) for key_id in self._keys],
            )
        finally:
            connection.close()

    async def acquire(self) -> ApiKeyLease:
        if not self._keys:
            raise ApiKeyPoolUnavailableError(f"未配置 {self.provider} API key")
        await self.initialize()
        while True:
            lease, wake_at, disabled_count = await asyncio.to_thread(
                self._try_acquire_sync
            )
            if lease is not None:
                return lease
            if disabled_count >= len(self._keys):
                raise ApiKeyPoolUnavailableError(
                    f"所有 {self.provider} API key 均被上游拒绝"
                )
            delay = max(0.01, wake_at - self._now())
            await self._sleep(min(delay, 1.0))

    def _try_acquire_sync(self) -> tuple[ApiKeyLease | None, float, int]:
        now = self._now()
        token = uuid.uuid4().hex
        placeholders = ",".join("?" for _ in self._keys)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            provider = connection.execute(
                "SELECT available_at FROM provider_state WHERE provider=?",
                (self.provider,),
            ).fetchone()
            provider_ready = float(provider[0]) if provider else 0.0
            rows = connection.execute(
                f"""
                SELECT key_id, available_at, leased_until, last_used_at, disabled
                FROM api_keys WHERE provider=? AND key_id IN ({placeholders})
                ORDER BY MAX(available_at, leased_until), last_used_at, key_id
                """,
                (self.provider, *self._keys),
            ).fetchall()
            disabled_count = sum(1 for row in rows if int(row[4]))
            candidates = [row for row in rows if not int(row[4])]
            ready = [
                row
                for row in candidates
                if max(float(row[1]), float(row[2]), provider_ready) <= now
            ]
            if ready:
                key_id = str(ready[0][0])
                connection.execute(
                    """
                    UPDATE api_keys
                    SET leased_until=?, lease_token=?, last_used_at=?,
                        available_at=MAX(available_at, ?), updated_at=?
                    WHERE provider=? AND key_id=?
                    """,
                    (
                        now + self.lease_seconds,
                        token,
                        now,
                        now + self.min_interval_seconds,
                        now,
                        self.provider,
                        key_id,
                    ),
                )
                connection.execute("COMMIT")
                return (
                    ApiKeyLease(self._keys[key_id], key_id, token),
                    now,
                    disabled_count,
                )
            wake_at = min(
                (
                    max(float(row[1]), float(row[2]), provider_ready)
                    for row in candidates
                ),
                default=now,
            )
            connection.execute("COMMIT")
            return None, wake_at, disabled_count
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    async def report_success(self, lease: ApiKeyLease, status: str = "ok") -> None:
        await self.initialize()
        await asyncio.to_thread(self._release_sync, lease, status, None, False)
        await asyncio.to_thread(self._provider_success_sync)

    async def report_rate_limit(
        self, lease: ApiKeyLease, cooldown_seconds: float
    ) -> None:
        await self.initialize()
        available_at = self._now() + max(0.0, float(cooldown_seconds))
        await asyncio.to_thread(
            self._release_sync, lease, "rate_limited", available_at, False
        )

    async def report_auth_rejected(self, lease: ApiKeyLease, status: str) -> None:
        await self.initialize()
        await asyncio.to_thread(self._release_sync, lease, status, None, True)

    async def report_temporary_failure(self, lease: ApiKeyLease, status: str) -> float:
        await self.initialize()
        await asyncio.to_thread(self._release_sync, lease, status, None, False)
        return await asyncio.to_thread(self._provider_failure_sync, status)

    async def release(self, lease: ApiKeyLease, status: str = "released") -> None:
        await self.initialize()
        await asyncio.to_thread(self._release_sync, lease, status, None, False)

    def _release_sync(
        self,
        lease: ApiKeyLease,
        status: str,
        available_at: float | None,
        disable: bool,
    ) -> None:
        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if available_at is None:
                connection.execute(
                    """
                    UPDATE api_keys SET leased_until=0, lease_token=NULL, last_status=?,
                        consecutive_429=CASE WHEN ?='rate_limited' THEN consecutive_429 + 1 ELSE 0 END,
                        disabled=CASE WHEN ? THEN 1 ELSE disabled END, updated_at=?
                    WHERE provider=? AND key_id=? AND lease_token=?
                    """,
                    (
                        status,
                        status,
                        int(disable),
                        now,
                        self.provider,
                        lease.key_id,
                        lease.token,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE api_keys SET leased_until=0, lease_token=NULL,
                        available_at=MAX(available_at, ?), last_status=?,
                        consecutive_429=consecutive_429 + 1,
                        disabled=CASE WHEN ? THEN 1 ELSE disabled END, updated_at=?
                    WHERE provider=? AND key_id=? AND lease_token=?
                    """,
                    (
                        available_at,
                        status,
                        int(disable),
                        now,
                        self.provider,
                        lease.key_id,
                        lease.token,
                    ),
                )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _provider_failure_sync(self, status: str) -> float:
        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT consecutive_failures FROM provider_state WHERE provider=?",
                (self.provider,),
            ).fetchone()
            failures = min(8, (int(row[0]) if row else 0) + 1)
            delay = min(60.0, float(2 ** (failures - 1)))
            connection.execute(
                """
                INSERT INTO provider_state(provider, available_at, consecutive_failures, last_status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET available_at=excluded.available_at,
                    consecutive_failures=excluded.consecutive_failures,
                    last_status=excluded.last_status, updated_at=excluded.updated_at
                """,
                (self.provider, now + delay, failures, status, now),
            )
            connection.execute("COMMIT")
            return delay
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _provider_success_sync(self) -> None:
        now = self._now()
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO provider_state(provider, available_at, consecutive_failures, last_status, updated_at)
                VALUES (?, 0, 0, 'ok', ?)
                ON CONFLICT(provider) DO UPDATE SET available_at=0, consecutive_failures=0,
                    last_status='ok', updated_at=excluded.updated_at
                """,
                (self.provider, now),
            )
        finally:
            connection.close()

    async def snapshot(self) -> dict[str, int | float | str]:
        await self.initialize()
        return await asyncio.to_thread(self._snapshot_sync)

    def _snapshot_sync(self) -> dict[str, int | float | str]:
        now = self._now()
        placeholders = ",".join("?" for _ in self._keys)
        connection = self._connect()
        try:
            if not self._keys:
                return {
                    "configured": 0,
                    "ready": 0,
                    "cooling": 0,
                    "leased": 0,
                    "disabled": 0,
                }
            rows = connection.execute(
                f"SELECT available_at, leased_until, disabled FROM api_keys WHERE provider=? AND key_id IN ({placeholders})",
                (self.provider, *self._keys),
            ).fetchall()
            return {
                "configured": len(self._keys),
                "ready": sum(
                    1
                    for a, lease, disabled in rows
                    if not disabled and a <= now and lease <= now
                ),
                "cooling": sum(
                    1
                    for a, lease, disabled in rows
                    if not disabled and a > now and lease <= now
                ),
                "leased": sum(
                    1 for _a, lease, disabled in rows if not disabled and lease > now
                ),
                "disabled": sum(1 for _a, _lease, disabled in rows if disabled),
            }
        finally:
            connection.close()
