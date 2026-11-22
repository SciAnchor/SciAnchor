from __future__ import annotations

from research_harness._core.storage.db import Database
from research_harness.runtime.durable_semantics import (
    diagnose_durable_semantics,
)


def _migrated_db(tmp_path):
    db = Database(tmp_path / "durable-semantics.db")
    db.migrate()
    return db


def test_durable_semantics_accepts_current_migrated_schema(tmp_path) -> None:
    db = _migrated_db(tmp_path)

    report = diagnose_durable_semantics(db)
    checks_by_id = {check.check_id: check for check in report.checks}

    assert report.ok is True
    assert report.status == "stable_local_executable_guards"
    assert report.schema_migration_required is False
    assert report.rollback_or_dry_run_evidence == "local_read_only_diagnostics"
    assert checks_by_id["runtime-events-append-only"].ok is True
    assert checks_by_id["project-artifact-lineage-columns"].ok is True
    assert checks_by_id["artifact-dependency-unique-edge"].ok is True
    assert checks_by_id["orchestrator-run-read-model-columns"].ok is True
    assert checks_by_id["orchestrator-stage-event-read-model-columns"].ok is True


def test_durable_semantics_reports_missing_runtime_event_trigger(tmp_path) -> None:
    db = _migrated_db(tmp_path)

    with db.connect() as conn:
        conn.execute("DROP TRIGGER trg_runtime_events_no_delete")

    report = diagnose_durable_semantics(db)
    checks_by_id = {check.check_id: check for check in report.checks}

    assert report.ok is False
    assert report.status == "local_guard_failed"
    assert checks_by_id["runtime-events-append-only"].ok is False
    assert (
        "trg_runtime_events_no_delete"
        in checks_by_id["runtime-events-append-only"].missing
    )


def test_durable_semantics_reports_missing_project_artifact_lineage_column(
    tmp_path,
) -> None:
    db = _migrated_db(tmp_path)

    with db.connect() as conn:
        conn.execute("ALTER TABLE project_artifacts RENAME TO project_artifacts_old")
        conn.execute(
            """
            CREATE TABLE project_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                topic_id INTEGER NOT NULL,
                stage TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                version INTEGER NOT NULL DEFAULT 1,
                title TEXT NOT NULL DEFAULT '',
                path TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )

    report = diagnose_durable_semantics(db)
    checks_by_id = {check.check_id: check for check in report.checks}

    assert report.ok is False
    assert checks_by_id["project-artifact-lineage-columns"].ok is False
    assert {
        "parent_artifact_id",
        "provenance_record_id",
        "stale",
        "stale_reason",
    } <= set(checks_by_id["project-artifact-lineage-columns"].missing)


def test_durable_semantics_helper_is_private_runtime_surface() -> None:
    import research_harness.runtime as runtime

    assert "diagnose_durable_semantics" not in runtime.__all__
