"""Compatibility shim for :mod:`research_harness._core.core.search_cache`."""

from research_harness._core.core.search_cache import (
    _cache_key,
    cache_evict_expired,
    cache_get,
    cache_put,
)

__all__ = ["_cache_key", "cache_evict_expired", "cache_get", "cache_put"]
