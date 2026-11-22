# -*- coding: utf-8 -*-
"""跨数据源、跨进程的可靠元数据响应缓存。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from paperfetch.core.config_v1 import runtime_cache_root
from paperfetch.observability import get_event_logger

logger = get_event_logger("paperfetch.cache")

CACHE_SCHEMA_VERSION = "metadata-cache-v2"


@dataclass(frozen=True)
class MetadataCacheEntry:
    state: Literal["hit", "negative", "stale", "miss"]
    data: Any = None
    source: str | None = None
    stored_at: float | None = None
    expires_at: float | None = None
    schema_version: str | None = None


def metadata_cache_key(
    source: str,
    operation: str,
    identity: str,
    *,
    api_version: str,
    fields_version: str,
) -> str:
    """构造不泄露长查询文本且不会跨字段契约误命中的稳定缓存键。"""

    digest = hashlib.sha256(identity.strip().casefold().encode("utf-8")).hexdigest()
    return ":".join((source, api_version, operation, fields_version, digest))


class LocalMetadataCache:
    """SQLite 缓存，包含 TTL、权威负缓存和跨进程 single-flight。"""

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        self.db_path = db_path
        self._now = now
        self._sleep = sleep
        self._initialize_lock = asyncio.Lock()
        self._initialized = False

    @staticmethod
    def _resolve_default_db_path() -> str:
        configured = str(os.getenv("SPC_METADATA_CACHE_DB") or "").strip()
        if configured:
            return str(Path(configured).expanduser().resolve())
        return str(runtime_cache_root() / "metadata.sqlite3")

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            if not self.db_path:
                self.db_path = self._resolve_default_db_path()
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._init_db)
            self._initialized = True
            logger.info("元数据缓存已就绪: %s", self.db_path)

    def _connect(self) -> sqlite3.Connection:
        assert self.db_path
        connection = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _init_db(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS work_cache (
                    key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    stored_at REAL,
                    expires_at REAL,
                    schema_version TEXT,
                    value_status TEXT NOT NULL DEFAULT 'value'
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(work_cache)"
                ).fetchall()
            }
            migrations = {
                "stored_at": "ALTER TABLE work_cache ADD COLUMN stored_at REAL",
                "expires_at": "ALTER TABLE work_cache ADD COLUMN expires_at REAL",
                "schema_version": "ALTER TABLE work_cache ADD COLUMN schema_version TEXT",
                "value_status": "ALTER TABLE work_cache ADD COLUMN value_status TEXT NOT NULL DEFAULT 'value'",
            }
            for name, statement in migrations.items():
                if name not in columns:
                    connection.execute(statement)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS request_leases (
                    request_key TEXT PRIMARY KEY,
                    lease_token TEXT NOT NULL,
                    leased_until REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
        finally:
            connection.close()

    async def get_entry(
        self,
        key: str,
        *,
        expected_schema: str | None = None,
    ) -> MetadataCacheEntry:
        await self.initialize()
        return await asyncio.to_thread(
            self._db_get_entry,
            key.strip().lower(),
            expected_schema,
        )

    def _db_get_entry(
        self,
        key: str,
        expected_schema: str | None,
    ) -> MetadataCacheEntry:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT source, data, stored_at, expires_at, schema_version, value_status
                FROM work_cache WHERE key=?
                """,
                (key,),
            ).fetchone()
            if row is None:
                return MetadataCacheEntry("miss")
            source, raw_data, stored_at, expires_at, schema_version, value_status = row
            if expected_schema and schema_version != expected_schema:
                return MetadataCacheEntry("miss")
            expired = expires_at is not None and float(expires_at) <= self._now()
            data = json.loads(raw_data) if raw_data is not None else None
            if expired:
                return MetadataCacheEntry(
                    "stale", data, source, stored_at, expires_at, schema_version
                )
            state: Literal["hit", "negative", "stale", "miss"]
            state = (
                "negative"
                if value_status == "not_found"
                else ("stale" if expired else "hit")
            )
            return MetadataCacheEntry(
                state, data, source, stored_at, expires_at, schema_version
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"元数据缓存记录损坏：{key}") from exc
        finally:
            connection.close()

    async def get(self, key: str) -> Any | None:
        """兼容旧调用；仅返回未过期的正缓存值。"""

        entry = await self.get_entry(key)
        return entry.data if entry.state == "hit" else None

    async def set(
        self,
        key: str,
        data: Any,
        source: str,
        *,
        ttl_seconds: float | None = None,
        schema_version: str = CACHE_SCHEMA_VERSION,
    ) -> None:
        await self.initialize()
        await asyncio.to_thread(
            self._db_set,
            key.strip().lower(),
            data,
            source,
            ttl_seconds,
            schema_version,
            "value",
        )

    async def set_not_found(
        self,
        key: str,
        source: str,
        *,
        ttl_seconds: float,
        schema_version: str = CACHE_SCHEMA_VERSION,
    ) -> None:
        """只允许调用方在权威 404 后写入短期负缓存。"""

        await self.initialize()
        await asyncio.to_thread(
            self._db_set,
            key.strip().lower(),
            None,
            source,
            ttl_seconds,
            schema_version,
            "not_found",
        )

    def _db_set(
        self,
        key: str,
        data: Any,
        source: str,
        ttl_seconds: float | None,
        schema_version: str,
        value_status: str,
    ) -> None:
        stored_at = self._now()
        expires_at = (
            None if ttl_seconds is None else stored_at + max(0.0, float(ttl_seconds))
        )
        encoded = (
            None
            if data is None
            else json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        )
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO work_cache(
                    key, source, data, stored_at, expires_at, schema_version, value_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET source=excluded.source, data=excluded.data,
                    stored_at=excluded.stored_at, expires_at=excluded.expires_at,
                    schema_version=excluded.schema_version, value_status=excluded.value_status
                """,
                (
                    key,
                    source,
                    encoded,
                    stored_at,
                    expires_at,
                    schema_version,
                    value_status,
                ),
            )
        finally:
            connection.close()

    async def acquire_request(
        self, request_key: str, *, lease_seconds: float = 120.0
    ) -> str:
        """获取同请求跨进程租约；租约过期可恢复异常退出。"""

        await self.initialize()
        digest = hashlib.sha256(request_key.encode("utf-8")).hexdigest()
        while True:
            token, wake_at = await asyncio.to_thread(
                self._try_acquire_request, digest, max(1.0, float(lease_seconds))
            )
            if token:
                return token
            await self._sleep(min(max(0.01, wake_at - self._now()), 1.0))

    def _try_acquire_request(
        self, request_key: str, lease_seconds: float
    ) -> tuple[str | None, float]:
        now = self._now()
        token = uuid.uuid4().hex
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT leased_until FROM request_leases WHERE request_key=?",
                (request_key,),
            ).fetchone()
            if row is None or float(row[0]) <= now:
                connection.execute(
                    """
                    INSERT INTO request_leases(request_key, lease_token, leased_until, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(request_key) DO UPDATE SET lease_token=excluded.lease_token,
                        leased_until=excluded.leased_until, updated_at=excluded.updated_at
                    """,
                    (request_key, token, now + lease_seconds, now),
                )
                connection.execute("COMMIT")
                return token, now
            connection.execute("COMMIT")
            return None, float(row[0])
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    async def release_request(self, request_key: str, token: str) -> None:
        await self.initialize()
        digest = hashlib.sha256(request_key.encode("utf-8")).hexdigest()
        await asyncio.to_thread(self._release_request, digest, token)

    async def renew_request(
        self, request_key: str, token: str, *, lease_seconds: float = 120.0
    ) -> bool:
        await self.initialize()
        digest = hashlib.sha256(request_key.encode("utf-8")).hexdigest()
        return await asyncio.to_thread(
            self._renew_request, digest, token, max(1.0, float(lease_seconds))
        )

    def _renew_request(
        self, request_key: str, token: str, lease_seconds: float
    ) -> bool:
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE request_leases SET leased_until=?, updated_at=?
                WHERE request_key=? AND lease_token=?
                """,
                (self._now() + lease_seconds, self._now(), request_key, token),
            )
            return cursor.rowcount == 1
        finally:
            connection.close()

    @asynccontextmanager
    async def request_lease(self, request_key: str, *, lease_seconds: float = 120.0):
        """持有可续期的 single-flight 租约；异常退出后由数据库到期恢复。"""

        token = await self.acquire_request(request_key, lease_seconds=lease_seconds)
        stopped = asyncio.Event()

        async def heartbeat() -> None:
            interval = max(1.0, lease_seconds / 3.0)
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    if not await self.renew_request(
                        request_key, token, lease_seconds=lease_seconds
                    ):
                        raise RuntimeError("元数据请求租约所有权已丢失")

        task = asyncio.create_task(heartbeat())
        try:
            yield token
        finally:
            stopped.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await self.release_request(request_key, token)

    def _release_request(self, request_key: str, token: str) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "DELETE FROM request_leases WHERE request_key=? AND lease_token=?",
                (request_key, token),
            )
        finally:
            connection.close()


global_cache = LocalMetadataCache()
