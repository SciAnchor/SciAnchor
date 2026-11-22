from __future__ import annotations

from research_harness.runtime.job_ledger import (
    JOB_LEDGER_RECORD_SCHEMA_VERSION,
    job_ledger_record_to_dict,
    normalize_async_job,
    normalize_expansion_job,
    normalize_longtask_attempt,
    normalize_longtask_gate,
    normalize_longtask_run,
    normalize_longtask_task,
)


def test_normalize_longtask_run_maps_active_to_running_without_mutating_source():
    source = {
        "id": "run-1",
        "title": "Runtime shell dry run",
        "objective": "Normalize job state.",
        "status": "active",
        "max_workers": 2,
        "created_at": "2026-06-09T08:12:00Z",
        "updated_at": "2026-06-09T08:13:00Z",
    }
    original = dict(source)

    record = normalize_longtask_run(source)

    assert source == original
    assert record.record_id == "longtask_runs:run-1"
    assert record.record_type == "run"
    assert record.source_type == "longtask_run"
    assert record.ledger_state == "running"
    assert record.run_id == "run-1"
    assert record.title == "Runtime shell dry run"
    assert record.payload["max_workers"] == 2
    assert record.schema_version == JOB_LEDGER_RECORD_SCHEMA_VERSION


def test_normalize_longtask_task_and_gate_use_approved_ledger_states():
    task = normalize_longtask_task(
        {
            "id": "T002",
            "run_id": "run-1",
            "title": "Review output",
            "status": "waiting_gate",
            "dependencies": ["T001"],
            "write_scope": ["docs/**"],
            "risk_level": "low",
            "created_at": "2026-06-09T08:14:00Z",
            "updated_at": "2026-06-09T08:15:00Z",
        }
    )
    gate = normalize_longtask_gate(
        {
            "id": "gate-1",
            "run_id": "run-1",
            "task_id": "T002",
            "gate_type": "human_review",
            "title": "Approve public API",
            "status": "rejected",
            "decision": "rejected",
            "note": "Do not leak this reviewer note",
            "actor": "human",
            "token_required": True,
            "created_at": "2026-06-09T08:16:00Z",
            "decided_at": "2026-06-09T08:17:00Z",
        }
    )

    assert task.record_id == "longtask_tasks:T002"
    assert task.record_type == "task"
    assert task.ledger_state == "waiting_for_approval"
    assert task.run_id == "run-1"
    assert task.task_id == "T002"
    assert task.payload["dependencies"] == ["T001"]

    assert gate.record_id == "longtask_gates:gate-1"
    assert gate.record_type == "gate"
    assert gate.ledger_state == "blocked_by_gate"
    assert gate.gate_id == "gate-1"
    assert gate.payload["decision"] == "rejected"
    assert gate.payload["token_required"] is True
    assert "reviewer note" not in str(job_ledger_record_to_dict(gate))


def test_normalize_longtask_attempt_collects_artifacts_without_error_leak():
    record = normalize_longtask_attempt(
        {
            "id": 11,
            "run_id": "run-1",
            "task_id": "T002",
            "status": "quarantined",
            "started_at": "2026-06-09T08:18:00Z",
            "finished_at": "2026-06-09T08:19:00Z",
            "exit_code": 1,
            "error": "Traceback in /private/tmp/worktree with token=secret",
            "events_path": "runs/run-1/T002/events.jsonl",
            "final_path": "runs/run-1/T002/final.md",
            "result_path": "runs/run-1/T002/result.json",
            "quarantine_reason_path": "runs/run-1/T002/quarantine.json",
        }
    )
    payload = job_ledger_record_to_dict(record)

    assert record.record_id == "longtask_attempts:11"
    assert record.record_type == "attempt"
    assert record.ledger_state == "failed"
    assert record.error_code == "attempt_failed"
    assert record.artifact_refs == (
        "runs/run-1/T002/events.jsonl",
        "runs/run-1/T002/final.md",
        "runs/run-1/T002/result.json",
        "runs/run-1/T002/quarantine.json",
    )
    assert "/private/tmp" not in str(payload)
    assert "token=secret" not in str(payload)


def test_normalize_async_job_parses_json_and_uses_stable_failure_code():
    source = {
        "id": 42,
        "job_type": "topic_candidates",
        "status": "failed",
        "topic_id": "7",
        "domain_id": 3,
        "idempotency_key": "abc",
        "input_params": '{"domain_id": 3, "query": "agents"}',
        "result": '{"count": 0}',
        "error": "SQL SELECT failed at /private/db.sqlite",
        "created_at": "2026-06-09T08:20:00Z",
        "updated_at": "2026-06-09T08:21:00Z",
    }
    original = dict(source)

    record = normalize_async_job(source)
    payload = job_ledger_record_to_dict(record)

    assert source == original
    assert record.record_id == "async_jobs:42"
    assert record.record_type == "run"
    assert record.source_type == "async_job"
    assert record.ledger_state == "failed"
    assert record.topic_id == 7
    assert record.error_code == "async_job_failed"
    assert record.payload["input_params"]["query"] == "agents"
    assert record.payload["result"]["count"] == 0
    assert "SELECT " not in str(payload)
    assert "/private/db.sqlite" not in str(payload)


def test_normalize_expansion_job_preserves_progress_without_last_error_leak():
    record = normalize_expansion_job(
        {
            "id": 51,
            "topic_id": 9,
            "status": "cancelled",
            "retrieval_target": 20,
            "deep_read_target": 5,
            "rounds_target": 3,
            "current_round": 2,
            "papers_fetched": 12,
            "papers_deep_read": 4,
            "last_error": "Provider key failed: sk-test",
            "created_at": "2026-06-09T08:22:00Z",
            "updated_at": "2026-06-09T08:23:00Z",
        }
    )

    assert record.record_id == "expansion_jobs:51"
    assert record.record_type == "run"
    assert record.source_type == "expansion_job"
    assert record.ledger_state == "cancelled"
    assert record.topic_id == 9
    assert record.payload["papers_fetched"] == 12
    assert record.payload["papers_deep_read"] == 4
    assert "sk-test" not in str(job_ledger_record_to_dict(record))
