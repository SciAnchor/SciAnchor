from __future__ import annotations

import json
from pathlib import Path

from research_harness._core.storage.db import Database
from research_harness.runtime.event_normalizer import (
    RuntimeEventRecord,
    normalize_longtask_event,
    normalize_provenance_record,
    normalize_selfdev_cloud_command,
    normalize_selfdev_cloud_submit,
    normalize_selfdev_cloud_submit_failure,
    normalize_selfdev_cloud_submit_started,
    normalize_selfdev_codex_command,
    normalize_selfdev_gate_report,
    normalize_selfdev_handoff,
    normalize_selfdev_next_action,
    normalize_selfdev_prompt,
    normalize_selfdev_slice_status_change,
    normalize_selfdev_status,
)
from research_harness.runtime.event_store import (
    _append_runtime_event,
    _diagnose_runtime_event_store,
    _read_runtime_event_by_event_id,
)
from research_harness.runtime.tool_boundary import (
    gate_decision_record_to_dict,
    normalize_gate_decision,
    normalize_tool_boundary,
    tool_boundary_record_to_dict,
)


def _migrated_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "runtime-event-contract.db")
    db.migrate()
    return db


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _tool_failure_fixture() -> RuntimeEventRecord:
    record = normalize_tool_boundary(
        {
            "primitive": "claim_extract",
            "status": "error",
            "error": {
                "code": "PRIMITIVE_FAILED",
                "message": "Traceback with /private/path",
            },
            "trace_id": "trace-fixture",
            "topic_id": 1,
            "job_id": "job-fixture",
            "created_at": "2026-06-09T18:01:00Z",
        },
        origin_surface="mcp",
    )
    return RuntimeEventRecord(
        event_id=f"tool_boundary:{record.record_id}",
        event_type=record.event_type,
        created_at=record.created_at,
        origin_surface=record.origin_surface,
        trace_id=record.trace_id,
        topic_id=record.topic_id,
        job_id=record.job_id,
        tool_name=record.tool_name,
        artifact_refs=record.artifact_refs,
        error_code=record.error_code,
        payload=tool_boundary_record_to_dict(record),
    )


def _gate_decision_fixture() -> RuntimeEventRecord:
    record = normalize_gate_decision(
        {
            "topic_id": 1,
            "stage": "propose",
            "gate_type": "coverage_gate",
            "gate_decision": "needs_coverage",
            "can_advance": False,
            "missing_artifacts": ["claim_matrix"],
            "blocking_reasons": ["missing required evidence"],
            "created_at": "2026-06-09T18:02:00Z",
        },
        origin_surface="orchestrator",
    )
    return RuntimeEventRecord(
        event_id=f"gate_decision:{record.record_id}",
        event_type=record.event_type,
        created_at=record.created_at,
        origin_surface=record.origin_surface,
        topic_id=record.topic_id,
        job_id=record.job_id,
        tool_name=record.tool_name,
        artifact_refs=record.artifact_refs,
        gate_decision=record.gate_decision,
        error_code=record.error_code,
        payload=gate_decision_record_to_dict(record),
    )


def _selfdev_checkpoint_fixture() -> RuntimeEventRecord:
    return RuntimeEventRecord(
        event_id="selfdev_checkpoint:20260610T010203Z",
        event_type="selfdev.checkpoint_created",
        created_at="20260610T010203Z",
        origin_surface="self_dev",
        actor="codex",
        job_id="K122_RUNTIME_EVENT_STORE_SELFDEV_CHECKPOINT_SOURCE",
        tool_name="rh-selfdev checkpoint",
        artifact_refs=(".rh-selfdev/checkpoint.md",),
        payload={},
    )


def _expanded_selfdev_fixtures() -> tuple[RuntimeEventRecord, ...]:
    slices_path = Path(".rh-selfdev/slices.md")
    command_context = {
        "attempts": 2,
        "branch": "selfdev/k149",
        "command_argc": 10,
        "environment_id_present": True,
    }
    return (
        _selfdev_checkpoint_fixture(),
        normalize_selfdev_gate_report(
            path=Path(
                ".rh-selfdev/gates/"
                "K125_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE-"
                "20260610T044011Z.md"
            ),
            text=(
                "# Gate: K125_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE\n\n"
                "Task id: task-17\n"
                "Recommendation: approve\n"
            ),
            created_at="20260610T044011Z",
        ),
        normalize_selfdev_prompt(
            path=Path(
                ".tmp/rh-selfdev-prompts/"
                "K127_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE.md"
            ),
            text=("Slice: K127_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE\nPhase: P6\n"),
            created_at="20260610T044923Z",
        ),
        normalize_selfdev_slice_status_change(
            path=slices_path,
            slice_id="K129_RUNTIME_EVENT_STORE_SELFDEV_SLICE_STATUS_SOURCE",
            previous_status="todo",
            new_status="in_progress",
            created_at="20260610T050304Z",
        ),
        normalize_selfdev_next_action(
            path=slices_path,
            action={
                "action": "create_slice",
                "slice_id": "K149_RUNTIME_EVENT_STORE_SELFDEV_EVENT_STORE_CONTRACT_REFRESH",
                "phase": "P6",
                "risk": "high",
                "reason": "contract refresh",
                "human_gate": "covered by K144",
            },
            created_at="20260610T153100Z",
        ),
        normalize_selfdev_status(
            path=slices_path,
            status_payload={
                "action": "create_slice",
                "dirty_file_count": 3,
                "risk_flags": {
                    "benchmark_claim_changed": False,
                    "dependency_changed": False,
                    "orchestrator_gate_changed": False,
                    "public_surface_changed": False,
                    "storage_or_provenance_changed": False,
                },
                "slice_id": "K149_RUNTIME_EVENT_STORE_SELFDEV_EVENT_STORE_CONTRACT_REFRESH",
            },
            created_at="20260610T153101Z",
        ),
        normalize_selfdev_cloud_command(
            path=slices_path,
            command_context={
                **command_context,
                "slice_id": "K134_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_COMMAND_SOURCE",
            },
            created_at="20260610T064300Z",
        ),
        normalize_selfdev_codex_command(
            path=slices_path,
            command_context={
                "command_argc": 14,
                "model": "gpt-5.4",
                "output_path": ".rh-selfdev/out.json",
                "prompt_path": ".tmp/prompts/K135.md",
                "slice_id": "K135_RUNTIME_EVENT_STORE_SELFDEV_CODEX_COMMAND_SOURCE",
                "worktree_path": "../rh-selfdev-k135",
            },
            created_at="20260610T064500Z",
        ),
        normalize_selfdev_cloud_submit_started(
            path=slices_path,
            command_context={
                **command_context,
                "slice_id": (
                    "K143_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STARTED_SOURCE"
                ),
            },
            created_at="20260610T104500Z",
        ),
        normalize_selfdev_cloud_submit(
            path=slices_path,
            command_context={
                **command_context,
                "returncode": 0,
                "slice_id": "K141_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_SOURCE",
            },
            created_at="20260610T101500Z",
        ),
        normalize_selfdev_cloud_submit_failure(
            path=slices_path,
            command_context={
                **command_context,
                "returncode": 17,
                "slice_id": (
                    "K142_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_FAILURE_SOURCE"
                ),
            },
            created_at="20260610T102300Z",
        ),
    )


def _contract_fixtures() -> tuple[RuntimeEventRecord, ...]:
    return (
        normalize_provenance_record(
            {
                "id": 21,
                "primitive": "paper_search",
                "success": 1,
                "topic_id": 1,
                "origin": "mcp",
                "actor": "codex",
                "finished_at": "2026-06-09T18:00:00Z",
            }
        ),
        normalize_longtask_event(
            {
                "id": 22,
                "run_id": "run-fixture",
                "task_id": "task-fixture",
                "event_type": "task_completed",
                "payload_json": '{"artifact_path":"outputs/runtime.md","count":2}',
                "created_at": "2026-06-09T18:00:30Z",
            }
        ),
        normalize_selfdev_handoff(
            path=Path(
                ".rh-selfdev/handoffs/"
                "K116_RUNTIME_EVENT_STORE_WRITER_HELPER-20260609T175459Z.md"
            ),
            text=(
                "# Handoff: K116_RUNTIME_EVENT_STORE_WRITER_HELPER\n\nStatus: done\n"
            ),
            created_at="2026-06-09T17:54:59Z",
        ),
        _tool_failure_fixture(),
        _gate_decision_fixture(),
        *_expanded_selfdev_fixtures(),
    )


def test_runtime_event_store_health_reports_ready_empty_store(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)

    health = _diagnose_runtime_event_store(db)

    assert health.ok is True
    assert health.table_exists is True
    assert health.append_only_triggers_present is True
    assert health.required_indexes_present is True
    assert health.row_count == 0
    assert health.invalid_json_event_ids == ()


def test_runtime_event_store_health_reports_invalid_json_rows(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO runtime_events (
                event_id, event_type, origin_surface, schema_version,
                artifact_refs_json, payload_json, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "runtime:invalid-json",
                "tool.failed",
                "test",
                "runtime_event_record.v0",
                "[]",
                "{not-json",
                "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    health = _diagnose_runtime_event_store(db)

    assert health.ok is False
    assert health.invalid_json_event_ids == ("runtime:invalid-json",)


def test_runtime_event_store_health_reports_database_connect_failure(
    tmp_path: Path,
) -> None:
    bad_db_path = tmp_path / "runtime-event-store-directory.db"
    bad_db_path.mkdir()
    db = Database(bad_db_path)

    health = _diagnose_runtime_event_store(db)

    assert health.ok is False
    assert health.table_exists is False
    assert health.append_only_triggers_present is False
    assert health.required_indexes_present is False
    assert health.row_count == 0
    assert health.error_code == "bad_connection"


def test_normalized_event_fixtures_write_read_and_stable_json_round_trip(
    tmp_path: Path,
) -> None:
    db = _migrated_db(tmp_path)
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'runtime')")
        for fixture in _contract_fixtures():
            result = _append_runtime_event(
                conn,
                fixture,
                metadata={"fixture": fixture.event_type},
            )
            assert result.status == "inserted"

            stored = _read_runtime_event_by_event_id(conn, fixture.event_id)
            row = conn.execute(
                """
                SELECT artifact_refs_json, payload_json, metadata_json
                FROM runtime_events
                WHERE event_id = ?
                """,
                (fixture.event_id,),
            ).fetchone()

            assert stored is not None
            assert stored.record == fixture
            assert stored.metadata == {"fixture": fixture.event_type}
            assert row["artifact_refs_json"] == _stable_json(
                list(fixture.artifact_refs)
            )
            assert row["payload_json"] == _stable_json(dict(fixture.payload or {}))
            assert row["metadata_json"] == _stable_json({"fixture": fixture.event_type})
    finally:
        conn.close()


def test_runtime_event_store_contract_covers_expanded_selfdev_event_families() -> None:
    event_types = {fixture.event_type for fixture in _contract_fixtures()}

    assert {
        "selfdev.checkpoint_created",
        "selfdev.gate_report_created",
        "selfdev.prompt_created",
        "selfdev.slice_status_changed",
        "selfdev.next_action_reported",
        "selfdev.status_reported",
        "selfdev.cloud_command_rendered",
        "selfdev.codex_command_rendered",
        "selfdev.cloud_submit_started",
        "selfdev.cloud_submit_recorded",
        "selfdev.cloud_submit_failed",
    }.issubset(event_types)


def test_runtime_event_store_health_helper_is_private() -> None:
    import research_harness.runtime as runtime

    assert "_diagnose_runtime_event_store" not in runtime.__all__
