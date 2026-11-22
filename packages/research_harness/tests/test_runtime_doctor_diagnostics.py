from __future__ import annotations

import json
from pathlib import Path

from research_harness.runtime.doctor_diagnostics import (
    DOCTOR_CHECK_RECORD_SCHEMA_VERSION,
    check_artifact_path_writability,
    check_event_source_integrity,
    check_generated_skill_cache,
    check_job_ledger_state,
    check_showcase_bundle_paths,
    check_skill_manifest_validity,
    check_skill_provenance,
    doctor_check_record_to_dict,
    load_job_ledger_records,
    normalize_doctor_check,
    redact_runtime_diagnostic_output,
)


def _seed_longtask_state_db(db_path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE longtask_runs (
          id TEXT PRIMARY KEY, title TEXT, objective TEXT, status TEXT,
          max_workers INTEGER, created_at TEXT, updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO longtask_runs VALUES (?,?,?,?,?,?,?)",
        ("r1", "Run one", "objective", "failed", 2, "2026-01-01", "2026-01-02"),
    )
    conn.commit()
    conn.close()


def test_load_job_ledger_records_returns_empty_when_db_absent(tmp_path: Path):
    assert load_job_ledger_records(tmp_path / "missing" / "state.db") == []


def test_load_job_ledger_records_reads_longtask_runs_read_only(tmp_path: Path):
    db_path = tmp_path / "state.db"
    _seed_longtask_state_db(db_path)
    records = load_job_ledger_records(db_path)
    assert any(r.get("source_type") == "longtask_run" for r in records)
    assert any(r.get("ledger_state") for r in records)
    # read-only: no WAL/journal side files created by the loader
    assert not (tmp_path / "state.db-wal").exists()


def test_check_skill_provenance_is_read_only_and_never_raises(tmp_path: Path):
    # A directory with no skills/ must degrade gracefully, not crash doctor.
    record = check_skill_provenance(tmp_path)
    payload = doctor_check_record_to_dict(record)
    assert payload["check_name"] == "skill_provenance"
    assert payload["status"] in {"pass", "warn", "fail"}
    # tmp_path is unchanged (read-only check)
    assert list(tmp_path.iterdir()) == []


def test_check_skill_provenance_reports_surface_for_real_repo():
    repo_root = next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "skills").is_dir() and (p / "setup.sh").is_file()
    )
    record = check_skill_provenance(repo_root)
    payload = doctor_check_record_to_dict(record)
    assert payload["check_name"] == "skill_provenance"
    assert payload["payload"]["public_skill_count"] >= 14
    assert "validation_status_counts" in payload["payload"]


def test_normalize_existing_doctor_check_without_mutating_source():
    source = {
        "check": "database",
        "path": "/private/rh/pool.db",
        "size_kb": 12,
        "ok": True,
    }
    original = dict(source)

    record = normalize_doctor_check(source, origin_surface="cli")
    payload = doctor_check_record_to_dict(record)

    assert source == original
    assert record.schema_version == DOCTOR_CHECK_RECORD_SCHEMA_VERSION
    assert record.record_id == "doctor_check:cli:database"
    assert record.event_type == "doctor.check_completed"
    assert record.check_name == "database"
    assert record.status == "pass"
    assert record.origin_surface == "cli"
    assert record.artifact_refs == ("/private/rh/pool.db",)
    assert payload["artifact_refs"] == ["/private/rh/pool.db"]
    assert payload["payload"]["size_kb"] == 12


def test_normalize_optional_doctor_check_as_skipped_internal_status():
    record = normalize_doctor_check(
        {
            "check": "paperindex",
            "version": "not installed",
            "note": "optional",
            "ok": True,
        },
        origin_surface="cli",
    )

    assert record.event_type == "doctor.check_completed"
    assert record.status == "skipped"
    assert record.error_code is None
    assert record.payload["note"] == "optional"


def test_check_skill_manifest_validity_reads_manifest_without_writes(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    alpha_dir = skills_dir / "alpha"
    alpha_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "1.0",
        "generated_at": "2026-06-09T00:00:00Z",
        "skills": [{"name": "alpha", "path": "skills/alpha"}],
    }
    manifest_path = skills_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    before = manifest_path.read_text(encoding="utf-8")

    record = check_skill_manifest_validity(tmp_path)

    assert manifest_path.read_text(encoding="utf-8") == before
    assert record.status == "pass"
    assert record.check_name == "skill_manifest_validity"
    assert record.payload["manifest_skill_count"] == 1
    assert record.payload["missing_skill_paths"] == []
    assert record.artifact_refs == (str(manifest_path),)


def test_check_skill_manifest_validity_fails_for_invalid_json(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    manifest_path = skills_dir / "manifest.json"
    manifest_path.write_text("{not json", encoding="utf-8")

    record = check_skill_manifest_validity(tmp_path)

    assert record.status == "fail"
    assert record.event_type == "doctor.check_failed"
    assert record.error_code == "invalid_skill_manifest"
    assert record.payload["manifest_parse_error"] == "invalid_json"


def test_check_generated_skill_cache_detects_generated_files(tmp_path: Path):
    cache_dir = tmp_path / "skills" / "alpha" / "scripts" / "__pycache__"
    cache_dir.mkdir(parents=True)
    pyc_path = cache_dir / "helper.cpython-311.pyc"
    pyc_path.write_bytes(b"compiled")
    pytest_cache = tmp_path / "skills" / "alpha" / ".pytest_cache" / "README.md"
    pytest_cache.parent.mkdir()
    pytest_cache.write_text("cache", encoding="utf-8")

    record = check_generated_skill_cache(tmp_path)

    assert record.status == "warn"
    assert record.check_name == "generated_skill_cache"
    assert record.error_code == "generated_skill_cache_present"
    assert record.payload["generated_cache_count"] == 2
    assert sorted(record.artifact_refs) == sorted((str(pyc_path), str(pytest_cache)))


def test_check_job_ledger_state_summarizes_internal_states_without_mutation():
    records = [
        {"ledger_state": "completed", "source_type": "longtask_run"},
        {"ledger_state": "failed", "source_type": "async_job"},
        {"ledger_state": "blocked_by_gate", "source_type": "longtask_gate"},
    ]
    original = [dict(record) for record in records]

    record = check_job_ledger_state(records)

    assert records == original
    assert record.status == "warn"
    assert record.check_name == "job_ledger_state"
    assert record.error_code == "job_ledger_attention_required"
    assert record.payload["state_counts"] == {
        "blocked_by_gate": 1,
        "completed": 1,
        "failed": 1,
    }
    assert record.payload["source_type_counts"] == {
        "async_job": 1,
        "longtask_gate": 1,
        "longtask_run": 1,
    }


def test_check_event_source_integrity_reports_duplicate_or_incomplete_events():
    records = [
        {"event_id": "event-1", "event_type": "tool.completed"},
        {"event_id": "event-1", "event_type": "tool.completed"},
        {"event_id": "event-2"},
    ]

    record = check_event_source_integrity(records)

    assert record.status == "fail"
    assert record.event_type == "doctor.check_failed"
    assert record.error_code == "event_source_integrity_failed"
    assert record.payload["event_count"] == 3
    assert record.payload["duplicate_event_ids"] == ["event-1"]
    assert record.payload["missing_event_type_count"] == 1


def test_check_artifact_path_writability_uses_parent_without_probe_write(
    tmp_path: Path,
):
    target = tmp_path / "artifacts" / "report.json"
    target.parent.mkdir()

    record = check_artifact_path_writability(target)

    assert target.exists() is False
    assert record.status == "pass"
    assert record.check_name == "artifact_path_writability"
    assert record.artifact_refs == (str(target),)
    assert record.payload["checked_path"] == str(target)
    assert record.payload["writable_parent"] == str(target.parent)


def test_check_showcase_bundle_paths_marks_missing_explicit_paths(tmp_path: Path):
    existing = tmp_path / "showcase" / "manifest.json"
    existing.parent.mkdir()
    existing.write_text('{"schema_version": "showcase.v0"}\n', encoding="utf-8")
    missing = tmp_path / "missing" / "manifest.json"

    record = check_showcase_bundle_paths([existing, missing])

    assert record.status == "fail"
    assert record.check_name == "showcase_bundle_paths"
    assert record.error_code == "showcase_bundle_missing"
    assert record.payload["provided_path_count"] == 2
    assert record.payload["missing_paths"] == [str(missing)]
    assert record.artifact_refs == (str(existing), str(missing))


def test_check_showcase_bundle_paths_not_applicable_without_explicit_paths():
    record = check_showcase_bundle_paths([])

    assert record.status == "not_applicable"
    assert record.error_code is None
    assert record.payload["provided_path_count"] == 0


def test_redact_runtime_diagnostic_output_removes_secrets_urls_and_raw_paths(
    tmp_path: Path,
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace_file = repo_root / "skills" / "manifest.json"
    workspace_file.parent.mkdir()
    workspace_file.write_text("{}", encoding="utf-8")
    outside_file = tmp_path / "outside" / "pool.db"

    payload = {
        "api_key": "sk-test-secret-token",
        "base_url": "https://internal.example.invalid/v1",
        "artifact_refs": [str(workspace_file), str(outside_file)],
        "payload": {
            "checked_path": str(workspace_file),
            "writable_parent": str(outside_file.parent),
        },
        "warnings": [
            f"multiple state trees: {workspace_file} (1 KB), {outside_file} (2 KB)"
        ],
    }

    redacted = redact_runtime_diagnostic_output(payload, repo_root)

    assert redacted["api_key"] == "<redacted>"
    assert redacted["base_url"] == "<redacted:url>"
    assert redacted["artifact_refs"] == [
        "workspace:skills/manifest.json",
        "local:pool.db",
    ]
    assert redacted["payload"]["checked_path"] == "workspace:skills/manifest.json"
    assert redacted["payload"]["writable_parent"] == "local:outside"
    assert redacted["warnings"] == [
        "multiple state trees: workspace:skills/manifest.json (1 KB), "
        "local:pool.db (2 KB)"
    ]
