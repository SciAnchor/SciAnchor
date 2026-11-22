"""Tests for absorbing gap_ground_verify retrieval into the panorama."""

from __future__ import annotations

import json
import sqlite3

from research_harness.panorama import PanoramaStore
from research_harness.panorama.importers import absorb_verify_cache


def _make_pool_with_cache(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE search_cache (cache_key TEXT PRIMARY KEY, source TEXT, "
        "query_hash TEXT, result_json TEXT, created_at TEXT, expires_at TEXT)"
    )
    for i, (created_at, records) in enumerate(rows):
        conn.execute(
            "INSERT INTO search_cache (cache_key, source, query_hash, result_json, "
            "created_at, expires_at) VALUES (?,?,?,?,?,?)",
            (f"k{i}", "aggregated", f"h{i}", json.dumps(records), created_at, ""),
        )
    conn.commit()
    conn.close()


def _store(tmp_path):
    s = PanoramaStore(tmp_path / "panorama")
    s.init()
    return s


def test_absorb_flattens_triages_and_logs_capture_source(tmp_path):
    pool = tmp_path / "pool.db"
    _make_pool_with_cache(
        pool,
        [
            (
                "2026-08-01 10:00:00",
                [
                    {
                        "title": "An AI Scientist for autonomous discovery",
                        "abstract": "A research agent that automates scientific discovery.",
                        "year": 2025,
                        "venue": "arXiv",
                        "arxiv_id": "2501.00001v2",
                        "doi": "",
                        "url": "https://arxiv.org/abs/2501.00001",
                    },
                    {
                        "title": "Underwater basket weaving dynamics",
                        "abstract": "Nothing to do with the domain.",
                        "year": 2024,
                        "openalex_id": "W999",
                    },
                ],
            ),
            (
                "2025-01-01 00:00:00",  # older than `since`
                [{"title": "Old research agent paper", "abstract": "agentic research"}],
            ),
        ],
    )
    store = _store(tmp_path)
    direction_id = store.get_or_create_direction("automated-research", "AR")

    result = absorb_verify_cache(
        store, direction_id, pool, since="2026-08-01", round_no=2
    )

    # Only the 2026-08-01 entry is in-window: 2 records flattened.
    assert result["cache_records_flattened"] == 2
    # Triage keeps the AI-scientist paper, drops underwater basket weaving.
    assert result["imported"] == 1
    papers = store.entities(direction_id, kind="paper")
    assert len(papers) == 1
    assert papers[0]["ext_ids"]["arxiv"] == "2501.00001"  # version stripped

    # Logged as an independent capture source for coverage.
    runs = store.harvest_runs(direction_id)
    assert any(r["source"] == "gap-verify" and r["round"] == 2 for r in runs)
    assert "gap-verify" in store.capture_matrix(direction_id).get(
        "arxiv:2501.00001", set()
    )


def test_absorb_is_idempotent(tmp_path):
    pool = tmp_path / "pool.db"
    _make_pool_with_cache(
        pool,
        [
            (
                "2026-08-01 10:00:00",
                [
                    {
                        "title": "Autonomous research agent benchmark",
                        "abstract": "A benchmark for autonomous research agents.",
                        "year": 2025,
                        "arxiv_id": "2502.02002",
                    }
                ],
            )
        ],
    )
    store = _store(tmp_path)
    direction_id = store.get_or_create_direction("automated-research", "AR")

    absorb_verify_cache(store, direction_id, pool, since="2026-08-01")
    absorb_verify_cache(store, direction_id, pool, since="2026-08-01")

    assert len(store.entities(direction_id, kind="paper")) == 1


def test_absorb_all_when_no_since(tmp_path):
    pool = tmp_path / "pool.db"
    _make_pool_with_cache(
        pool,
        [
            (
                "2025-06-01 00:00:00",
                [
                    {
                        "title": "Research agent survey",
                        "abstract": "agentic science survey",
                    }
                ],
            )
        ],
    )
    store = _store(tmp_path)
    direction_id = store.get_or_create_direction("automated-research", "AR")

    result = absorb_verify_cache(store, direction_id, pool)
    assert result["cache_records_flattened"] == 1
    assert result["imported"] == 1
