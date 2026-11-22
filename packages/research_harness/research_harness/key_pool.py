"""Shared multi-key pools for scholarly / provider credentials.

Org-wide convention:
- ``PROVIDER_API_KEY``  — single key (legacy / primary alias)
- ``PROVIDER_API_KEYS`` — comma/semicolon/whitespace-separated pool

Callers request a live key via :meth:`KeyPool.get`; on 429/403 they
:meth:`KeyPool.cooldown` that key and retry. Single-key callers that only need
"is anything configured?" use :meth:`KeyPool.primary` / ``bool(pool)``.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Sequence

_SPLIT_RE = re.compile(r"[,;\s]+")

# Canonical env names per provider. Order = preference when merging.
# Scholarly search sources (Semantic Scholar, OpenAlex, PubMed, ...) are used
# keyless on purpose and have no entry: their pools are always empty.
PROVIDER_ENV: dict[str, tuple[str, ...]] = {
    "zotero": ("ZOTERO_API_KEYS", "ZOTERO_API_KEY"),
    "mineru": ("MINERU_API_TOKENS", "MINERU_API_TOKEN"),
}

_DEFAULT_COOLDOWN = 60.0
_POOLS: dict[str, "KeyPool"] = {}
_POOLS_LOCK = threading.Lock()


def split_keys(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part for part in _SPLIT_RE.split(raw.strip()) if part]


def read_env_keys(*env_names: str) -> tuple[str, ...]:
    """Collect unique keys from one or more env vars (pool + single aliases)."""
    seen: set[str] = set()
    keys: list[str] = []
    for name in env_names:
        for key in split_keys(os.environ.get(name, "")):
            if key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return tuple(keys)


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return f"{key[:2]}…"
    return f"{key[:4]}…{key[-4:]}"


@dataclass
class KeyPool:
    """Thread-safe round-robin key pool with per-key cooldown."""

    name: str
    keys: tuple[str, ...]
    default_cooldown: float = _DEFAULT_COOLDOWN

    def __post_init__(self) -> None:
        object.__setattr__(self, "keys", tuple(k for k in self.keys if k))
        self._lock = threading.Lock()
        self._index = 0
        self._cooldown_until: dict[str, float] = {}

    def __bool__(self) -> bool:
        return bool(self.keys)

    def __len__(self) -> int:
        return len(self.keys)

    @property
    def primary(self) -> str:
        """First configured key (stable); empty string if none."""
        return self.keys[0] if self.keys else ""

    def all_keys(self) -> tuple[str, ...]:
        return self.keys

    def masked(self) -> list[str]:
        return [mask_key(k) for k in self.keys]

    def get(self) -> str:
        """Next non-cooling key (round-robin). Empty if all cooling / none."""
        if not self.keys:
            return ""
        now = time.monotonic()
        with self._lock:
            n = len(self.keys)
            for _ in range(n):
                key = self.keys[self._index % n]
                self._index = (self._index + 1) % n
                if now >= self._cooldown_until.get(key, 0.0):
                    return key
            return ""

    def cooldown(self, key: str, seconds: float | None = None) -> None:
        if not key or key not in self.keys:
            return
        duration = (
            self.default_cooldown if seconds is None else max(0.0, float(seconds))
        )
        with self._lock:
            self._cooldown_until[key] = time.monotonic() + duration

    def available_count(self) -> int:
        now = time.monotonic()
        with self._lock:
            return sum(1 for k in self.keys if now >= self._cooldown_until.get(k, 0.0))


def get_pool(
    provider: str,
    *,
    keys: Sequence[str] | None = None,
    env_names: Sequence[str] | None = None,
    default_cooldown: float = _DEFAULT_COOLDOWN,
    refresh: bool = False,
) -> KeyPool:
    """Return a process-wide pool for *provider*.

    If *keys* is given, builds (or replaces) the pool from that list.
    Otherwise reads ``PROVIDER_ENV[provider]`` or *env_names*.
    """
    provider = provider.strip().lower()
    if keys is None:
        names = (
            tuple(env_names)
            if env_names is not None
            else PROVIDER_ENV.get(provider, ())
        )
        resolved = read_env_keys(*names)
    else:
        resolved = tuple(k for k in keys if k)

    with _POOLS_LOCK:
        existing = _POOLS.get(provider)
        if (
            not refresh
            and existing is not None
            and existing.keys == resolved
            and existing.default_cooldown == default_cooldown
        ):
            return existing
        pool = KeyPool(name=provider, keys=resolved, default_cooldown=default_cooldown)
        _POOLS[provider] = pool
        return pool


def reset_pools() -> None:
    """Test helper: drop cached pools."""
    with _POOLS_LOCK:
        _POOLS.clear()


def openalex_pool(*, refresh: bool = False) -> KeyPool:
    return get_pool("openalex", refresh=refresh)


def semantic_scholar_pool(*, refresh: bool = False) -> KeyPool:
    return get_pool("semantic_scholar", refresh=refresh)
