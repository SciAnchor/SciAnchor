"""Minimal checks for shared scholarly key pools."""

from __future__ import annotations

from research_harness.key_pool import (
    KeyPool,
    openalex_pool,
    read_env_keys,
    reset_pools,
    semantic_scholar_pool,
    split_keys,
)


def test_split_keys_accepts_comma_semicolon_whitespace():
    assert split_keys("a, b;c  d") == ["a", "b", "c", "d"]
    assert split_keys("") == []


def test_read_env_keys_merges_and_dedupes(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEYS", "k1,k2")
    monkeypatch.setenv("OPENALEX_API_KEY", "k2")
    assert read_env_keys("OPENALEX_API_KEYS", "OPENALEX_API_KEY") == ("k1", "k2")


def test_round_robin_and_cooldown():
    pool = KeyPool(name="t", keys=("a", "b"), default_cooldown=60.0)
    assert pool.get() == "a"
    assert pool.get() == "b"
    assert pool.get() == "a"
    pool.cooldown("a", seconds=999.0)
    assert pool.get() == "b"
    assert pool.get() == "b"  # a still cooling
    assert pool.available_count() == 1


def test_scholarly_source_pools_ignore_env_keys(monkeypatch):
    """Scholarly search sources run keyless: keys in the environment are not read."""
    reset_pools()
    monkeypatch.setenv("OPENALEX_API_KEYS", "oa-1,oa-2")
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEYS", "s2-a,s2-b")
    monkeypatch.setenv("S2_API_KEY", "s2-a")

    assert len(openalex_pool(refresh=True)) == 0
    assert len(semantic_scholar_pool(refresh=True)) == 0
