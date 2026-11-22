from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_harness._selfdev.spc_cache_seed_pack_read_only_replay import (
    SpcCacheSeedPackReplayError,
    replay_spc_cache_seed_pack,
)


def _make_source(root: Path) -> tuple[Path, Path]:
    cache = root / ".spc_cache" / "pdf" / "files"
    pack = root / "seed_pack" / "pack-one"
    (cache).mkdir(parents=True)
    (pack / "pdf").mkdir(parents=True)
    (cache / "cache-a.pdf").write_bytes(b"same-pdf")
    (cache / "cache-b.pdf").write_bytes(b"cache-only")
    (pack / "pdf" / "pack-a.pdf").write_bytes(b"same-pdf")
    (pack / "pdf" / "pack-b.pdf").write_bytes(b"pack-only")
    (pack / "seed_papers.jsonl").write_text(
        '{"title":"one","doi":"10.1/one"}\n{"title":"two","doi":"10.1/two"}\n',
        encoding="utf-8",
    )
    (pack / "run_report.json").write_text(
        json.dumps(
            {
                "report_version": "seed-paper-curator.run-report.v1",
                "papers": [{"doi": "10.1/one"}],
            }
        ),
        encoding="utf-8",
    )
    (pack / "coverage_report.json").write_text(
        json.dumps({"report_version": "seed-paper-curator.coverage.v3-summary"}),
        encoding="utf-8",
    )
    (pack / "pack_manifest.json").write_text("{}", encoding="utf-8")
    return cache, root / "seed_pack"


def test_replay_separates_cache_seed_and_logical_bases(tmp_path: Path) -> None:
    cache, seed_pack = _make_source(tmp_path / "source")

    report = replay_spc_cache_seed_pack(
        cache_root=cache,
        seed_pack_root=seed_pack,
        snapshot_id="spc-test",
        observed_at="2026-08-07T02:00:00Z",
        scan_host_id="mac-test",
    )

    assert report.counts.cache_physical_pdfs == 2
    assert report.counts.cache_unique_hashes == 2
    assert report.counts.seed_pack_physical_pdfs == 2
    assert report.counts.seed_pack_unique_hashes == 2
    assert report.counts.seed_pack_logical_rows == 2
    assert report.counts.run_report_records == 1
    assert report.counts.seed_pack_dirs == 1
    assert report.counts.cache_seed_overlap_hashes == 1
    assert report.to_portable()["raw_payloads_retained"] is False


def test_replay_digest_ignores_observation_time(tmp_path: Path) -> None:
    cache, seed_pack = _make_source(tmp_path / "source")
    first = replay_spc_cache_seed_pack(
        cache_root=cache,
        seed_pack_root=seed_pack,
        snapshot_id="spc-test",
        observed_at="2026-08-07T02:00:00Z",
        scan_host_id="mac-test",
    )
    second = replay_spc_cache_seed_pack(
        cache_root=cache,
        seed_pack_root=seed_pack,
        snapshot_id="spc-test",
        observed_at="2026-08-07T02:01:00Z",
        scan_host_id="mac-test",
    )

    assert first.stable_evidence_sha256 == second.stable_evidence_sha256


def test_replay_rejects_contract_drift_and_symlink(tmp_path: Path) -> None:
    cache, seed_pack = _make_source(tmp_path / "source")
    report_path = seed_pack / "pack-one" / "run_report.json"
    report_path.write_text(
        json.dumps({"report_version": "seed-paper-curator.run-report.v9"}),
        encoding="utf-8",
    )
    with pytest.raises(SpcCacheSeedPackReplayError, match="run_report_version"):
        replay_spc_cache_seed_pack(
            cache_root=cache,
            seed_pack_root=seed_pack,
            snapshot_id="spc-test",
            observed_at="2026-08-07T02:00:00Z",
            scan_host_id="mac-test",
        )

    report_path.write_text(
        json.dumps(
            {
                "report_version": "seed-paper-curator.run-report.v1",
                "papers": [],
            }
        ),
        encoding="utf-8",
    )
    (cache / "escape.pdf").symlink_to(seed_pack / "pack-one" / "pdf" / "pack-a.pdf")
    with pytest.raises(SpcCacheSeedPackReplayError, match="cache_symlink"):
        replay_spc_cache_seed_pack(
            cache_root=cache,
            seed_pack_root=seed_pack,
            snapshot_id="spc-test",
            observed_at="2026-08-07T02:00:00Z",
            scan_host_id="mac-test",
        )


def test_replay_rejects_relative_roots(tmp_path: Path) -> None:
    cache, seed_pack = _make_source(tmp_path / "source")
    with pytest.raises(SpcCacheSeedPackReplayError, match="unsafe_source_root"):
        replay_spc_cache_seed_pack(
            cache_root=Path("."),
            seed_pack_root=seed_pack,
            snapshot_id="spc-test",
            observed_at="2026-08-07T02:00:00Z",
            scan_host_id="mac-test",
        )
