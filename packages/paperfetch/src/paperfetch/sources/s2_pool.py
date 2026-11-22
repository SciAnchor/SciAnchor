"""Semantic Scholar 对通用持久 API Key 池的薄适配。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Sequence
import asyncio
import time

from paperfetch.sources.key_pool import (
    ApiKeyLease,
    ApiKeyPoolUnavailableError,
    PersistentApiKeyPool,
    key_fingerprint,
    provider_key_state_db,
)

S2KeyLease = ApiKeyLease
S2KeyPoolUnavailableError = ApiKeyPoolUnavailableError


def semantic_scholar_state_db() -> Path:
    explicit = (os.getenv("SEMANTIC_SCHOLAR_STATE_DB") or "").strip()
    return (
        Path(explicit).expanduser().resolve() if explicit else provider_key_state_db()
    )


class PersistentS2KeyPool(PersistentApiKeyPool):
    def __init__(
        self,
        keys: Sequence[str],
        *,
        db_path: str | os.PathLike[str] | None = None,
        min_interval_seconds: float = 1.1,
        lease_seconds: float = 60.0,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        super().__init__(
            "semantic_scholar",
            keys,
            db_path=db_path or semantic_scholar_state_db(),
            min_interval_seconds=min_interval_seconds,
            lease_seconds=lease_seconds,
            now=now,
            sleep=sleep,
        )
