from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from research_harness._selfdev.local_rh_source_read_only_replay import (
    LocalRhSourceReplayError,
    replay_local_rh_source,
)


def _make_source(root: Path) -> Path:
    state = root / ".research-harness"
    downloads = state / "downloads"
    artifacts = state / "artifacts" / "paper_1"
    downloads.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    (downloads / "a.pdf").write_bytes(b"pdf-a")
    (downloads / "b.pdf").write_bytes(b"pdf-a")
    (downloads / "notes.txt").write_text("derived", encoding="utf-8")
    (artifacts / "card.json").write_text(
        json.dumps({"paper_id": 1, "title": "derived"}), encoding="utf-8"
    )
    (artifacts / "structure.json").write_text(
        json.dumps({"paper_id": 1, "pages": 2}), encoding="utf-8"
    )
    connection = sqlite3.connect(state / "pool.db")
    connection.executescript(
        """
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            pdf_path TEXT,
            pdf_hash TEXT,
            status TEXT
        );
        INSERT INTO papers VALUES
          (1, 'one', 'downloads/a.pdf', '', 'downloaded'),
          (2, 'two', 'missing.pdf', '', 'meta_only'),
          (3, 'three', '', '', 'meta_only');
        """
    )
    connection.commit()
    connection.close()
    return root


def test_replay_separates_logical_physical_hash_path_and_derived_counts(
    tmp_path: Path,
) -> None:
    root = _make_source(tmp_path / "source")

    report = replay_local_rh_source(
        rh_root=root,
        snapshot_id="local-rh-test",
        observed_at="2026-08-07T00:00:00Z",
        scan_host_id="mac-test",
    )

    assert report.counts.logical_rows == 3
    assert report.counts.physical_files == 3
    assert report.counts.unique_content_hashes == 2
    assert report.counts.resolvable_paths == 1
    assert report.counts.stale_paths == 1
    assert report.counts.empty_paths == 1
    assert report.counts.derived_json_files == 2
    assert report.counts.derived_artifact_directories == 1
    assert report.to_portable()["raw_payloads_retained"] is False


def test_replay_digest_is_stable_across_observation_time(tmp_path: Path) -> None:
    root = _make_source(tmp_path / "source")
    first = replay_local_rh_source(
        rh_root=root,
        snapshot_id="local-rh-test",
        observed_at="2026-08-07T00:00:00Z",
        scan_host_id="mac-test",
    )
    second = replay_local_rh_source(
        rh_root=root,
        snapshot_id="local-rh-test",
        observed_at="2026-08-07T00:01:00Z",
        scan_host_id="mac-test",
    )

    assert first.stable_evidence_sha256 == second.stable_evidence_sha256
    assert first.to_portable()["observed_at"] != second.to_portable()["observed_at"]


def test_replay_rejects_symlinked_database_and_download_file(tmp_path: Path) -> None:
    root = _make_source(tmp_path / "source")
    state = root / ".research-harness"
    real_db = state / "pool.db"
    real_db.rename(state / "pool.db.real")
    real_db.symlink_to(state / "pool.db.real")
    with pytest.raises(LocalRhSourceReplayError, match="database_symlink"):
        replay_local_rh_source(
            rh_root=root,
            snapshot_id="local-rh-test",
            observed_at="2026-08-07T00:00:00Z",
            scan_host_id="mac-test",
        )


def test_replay_rejects_unsafe_root_and_write_capable_database(tmp_path: Path) -> None:
    root = _make_source(tmp_path / "source")
    with pytest.raises(LocalRhSourceReplayError, match="unsafe_rh_root"):
        replay_local_rh_source(
            rh_root=Path("."),
            snapshot_id="local-rh-test",
            observed_at="2026-08-07T00:00:00Z",
            scan_host_id="mac-test",
        )

    report = replay_local_rh_source(
        rh_root=root,
        snapshot_id="local-rh-test",
        observed_at="2026-08-07T00:00:00Z",
        scan_host_id="mac-test",
    )
    assert report.sqlite_access == "immutable_query_only"
