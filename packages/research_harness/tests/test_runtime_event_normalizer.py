from __future__ import annotations

from pathlib import Path

from research_harness.runtime.event_normalizer import (
    RUNTIME_EVENT_RECORD_SCHEMA_VERSION,
    normalize_human_feedback_record,
    normalize_longtask_event,
    normalize_provenance_record,
    normalize_selfdev_cloud_command,
    normalize_selfdev_cloud_submit_started,
    normalize_selfdev_cloud_submit,
    normalize_selfdev_cloud_submit_failure,
    normalize_selfdev_codex_command,
    normalize_selfdev_gate_report,
    normalize_selfdev_handoff,
    normalize_selfdev_next_action,
    normalize_selfdev_prompt,
    normalize_selfdev_slice_status_change,
    normalize_selfdev_status,
    runtime_event_record_to_dict,
)


def test_normalize_successful_provenance_record_to_tool_completed_event():
    source = {
        "id": 17,
        "primitive": "paper_search",
        "success": 1,
        "topic_id": 3,
        "stage": "search",
        "backend": "local",
        "actor": "codex",
        "origin": "mcp",
        "artifact_id": 44,
        "started_at": "2026-06-09T07:00:00Z",
        "finished_at": "2026-06-09T07:00:02Z",
        "error": "",
    }

    record = normalize_provenance_record(source)

    assert record.event_id == "provenance_records:17"
    assert record.event_type == "tool.completed"
    assert record.trace_id is None
    assert record.created_at == "2026-06-09T07:00:02Z"
    assert record.origin_surface == "mcp"
    assert record.actor == "codex"
    assert record.topic_id == 3
    assert record.tool_name == "paper_search"
    assert record.artifact_refs == ("project_artifacts:44", "provenance_records:17")
    assert record.error_code is None
    assert record.schema_version == RUNTIME_EVENT_RECORD_SCHEMA_VERSION


def test_normalize_failed_provenance_record_sets_public_error_code_without_leak():
    source = {
        "id": 18,
        "primitive": "claim_extract",
        "success": 0,
        "topic_id": "5",
        "backend": "remote",
        "created_at": "2026-06-09T07:01:00Z",
        "error": "Traceback with /private/path and SQL SELECT detail",
    }

    record = normalize_provenance_record(source)
    payload = runtime_event_record_to_dict(record)

    assert payload["event_type"] == "tool.failed"
    assert payload["topic_id"] == 5
    assert payload["error_code"] == "tool_failed"
    encoded = str(payload)
    assert "/private/path" not in encoded
    assert "SELECT " not in encoded


def test_normalize_human_feedback_record_links_experience_lesson_and_artifact():
    record = normalize_human_feedback_record(
        payload={
            "experience_record_id": 10,
            "lesson_id": 11,
            "artifact_id": 12,
            "topic_id": 3,
            "stage": "write",
            "section": "figure_quality",
            "workspace_path": "/tmp/rh-workspace/demo",
            "agent": "claude-code",
            "trigger_class": "human_feedback",
            "feedback_excerpt": "Figure typo should trigger RH improvement.",
        },
        created_at="2026-06-30T00:00:00Z",
    )

    assert record.event_type == "selfdev.human_feedback_recorded"
    assert record.origin_surface == "human_feedback"
    assert record.actor == "claude-code"
    assert record.topic_id == 3
    assert record.artifact_refs == (
        "experience_records:10",
        "lessons:11",
        "project_artifacts:12",
    )
    assert record.payload["workspace_path"] == "/tmp/rh-workspace/demo"
    assert record.payload["trigger_class"] == "human_feedback"


def test_normalize_selfdev_handoff_is_stable_and_does_not_read_file(tmp_path: Path):
    handoff_path = tmp_path / "K102_KNOWLEDGE_PUBLIC_HTTP_API-20260609T075056Z.md"
    text = """# K102 Knowledge Public HTTP API Handoff

Date: 20260609T075056Z
Status: complete

## Completed

- Implemented HTTP API.
"""

    record = normalize_selfdev_handoff(
        path=handoff_path,
        text=text,
        created_at="2026-06-09T07:50:56Z",
    )

    assert record.event_type == "selfdev.handoff_created"
    assert record.event_id.startswith("selfdev_handoff:K102_")
    assert record.created_at == "2026-06-09T07:50:56Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == "K102_KNOWLEDGE_PUBLIC_HTTP_API"
    assert record.artifact_refs == (str(handoff_path),)
    assert record.payload["status"] == "complete"


def test_normalize_selfdev_gate_report_is_stable_and_does_not_read_file(
    tmp_path: Path,
):
    gate_path = (
        tmp_path
        / "K125_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE-20260610T044011Z.md"
    )
    text = """# Gate: K125_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE

Date: 20260610T044011Z
Executor: codex
Task id: task-17
Recommendation: approve

## Objective

Route gate report events.
"""

    record = normalize_selfdev_gate_report(
        path=gate_path,
        text=text,
        created_at="20260610T044011Z",
    )

    assert record.event_type == "selfdev.gate_report_created"
    assert record.event_id == (
        "selfdev_gate_report:"
        "K125_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE:20260610T044011Z"
    )
    assert record.created_at == "20260610T044011Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == "K125_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE"
    assert record.gate_decision == "approve"
    assert record.artifact_refs == (str(gate_path),)
    assert record.payload == {
        "filename": gate_path.name,
        "recommendation": "approve",
        "task_id": "task-17",
    }


def test_normalize_selfdev_prompt_is_stable_and_does_not_read_file(tmp_path: Path):
    prompt_path = tmp_path / "K127_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE.md"
    text = """You are a Codex worker executing one Research Harness self-development slice.

Slice: K127_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE
Phase: P6
"""

    record = normalize_selfdev_prompt(
        path=prompt_path,
        text=text,
        created_at="20260610T044923Z",
    )

    assert record.event_type == "selfdev.prompt_created"
    assert record.event_id == (
        "selfdev_prompt:K127_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE:20260610T044923Z"
    )
    assert record.created_at == "20260610T044923Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == "K127_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE"
    assert record.artifact_refs == (str(prompt_path),)
    assert record.payload == {
        "filename": prompt_path.name,
        "prompt_bytes": len(text.encode("utf-8")),
    }


def test_normalize_selfdev_slice_status_change_is_stable_without_reading_file(
    tmp_path: Path,
):
    slices_path = tmp_path / "rh-self-dev-slices.md"

    record = normalize_selfdev_slice_status_change(
        path=slices_path,
        slice_id="K129_RUNTIME_EVENT_STORE_SELFDEV_SLICE_STATUS_SOURCE",
        previous_status="todo",
        new_status="in_progress",
        created_at="20260610T050304Z",
    )

    assert record.event_type == "selfdev.slice_status_changed"
    assert record.event_id == (
        "selfdev_slice_status:"
        "K129_RUNTIME_EVENT_STORE_SELFDEV_SLICE_STATUS_SOURCE:"
        "20260610T050304Z"
    )
    assert record.created_at == "20260610T050304Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == "K129_RUNTIME_EVENT_STORE_SELFDEV_SLICE_STATUS_SOURCE"
    assert record.artifact_refs == (str(slices_path),)
    assert record.payload == {
        "filename": slices_path.name,
        "new_status": "in_progress",
        "previous_status": "todo",
    }


def test_normalize_selfdev_next_action_is_stable_without_reading_file(
    tmp_path: Path,
):
    slices_path = tmp_path / "rh-self-dev-slices.md"

    record = normalize_selfdev_next_action(
        path=slices_path,
        action={
            "action": "wait_for_gate",
            "slice_id": "K131_RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_SOURCE",
            "phase": "P6",
            "risk": "high",
            "reason": "fresh gate required",
            "human_gate": "approval required",
        },
        created_at="20260610T051954Z",
    )

    assert record.event_type == "selfdev.next_action_reported"
    assert record.event_id == (
        "selfdev_next_action:"
        "K131_RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_SOURCE:"
        "wait_for_gate:20260610T051954Z"
    )
    assert record.created_at == "20260610T051954Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == "K131_RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_SOURCE"
    assert record.artifact_refs == (str(slices_path),)
    assert record.payload == {
        "action": "wait_for_gate",
        "filename": slices_path.name,
        "human_gate": "approval required",
        "phase": "P6",
        "reason": "fresh gate required",
        "risk": "high",
        "slice_id": "K131_RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_SOURCE",
    }


def test_normalize_selfdev_status_is_stable_without_reading_file(tmp_path: Path):
    slices_path = tmp_path / "rh-self-dev-slices.md"
    payload = {
        "action": "create_slice",
        "dirty_file_count": 3,
        "risk_flags": {
            "benchmark_claim_changed": False,
            "dependency_changed": False,
            "orchestrator_gate_changed": False,
            "public_surface_changed": True,
            "storage_or_provenance_changed": False,
        },
        "slice_id": "K133_RUNTIME_EVENT_STORE_SELFDEV_STATUS_SOURCE",
    }

    record = normalize_selfdev_status(
        path=slices_path,
        status_payload=payload,
        created_at="20260610T063300Z",
    )

    assert record.event_type == "selfdev.status_reported"
    assert (
        record.event_id
        == "selfdev_status:K133_RUNTIME_EVENT_STORE_SELFDEV_STATUS_SOURCE:20260610T063300Z"
    )
    assert record.created_at == "20260610T063300Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == "K133_RUNTIME_EVENT_STORE_SELFDEV_STATUS_SOURCE"
    assert record.artifact_refs == (str(slices_path),)
    assert record.payload == {
        "action": "create_slice",
        "dirty_file_count": 3,
        "filename": slices_path.name,
        "risk_flags": {
            "benchmark_claim_changed": False,
            "dependency_changed": False,
            "orchestrator_gate_changed": False,
            "public_surface_changed": True,
            "storage_or_provenance_changed": False,
        },
        "slice_id": "K133_RUNTIME_EVENT_STORE_SELFDEV_STATUS_SOURCE",
    }


def test_normalize_selfdev_cloud_command_is_stable_without_prompt_payload(
    tmp_path: Path,
):
    slices_path = tmp_path / "rh-self-dev-slices.md"
    command_context = {
        "attempts": 2,
        "branch": "selfdev/k134",
        "command_argc": 10,
        "environment_id_present": True,
        "slice_id": "K134_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_COMMAND_SOURCE",
    }

    record = normalize_selfdev_cloud_command(
        path=slices_path,
        command_context=command_context,
        created_at="20260610T064300Z",
    )

    assert record.event_type == "selfdev.cloud_command_rendered"
    assert record.event_id == (
        "selfdev_cloud_command:"
        "K134_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_COMMAND_SOURCE:"
        "20260610T064300Z"
    )
    assert record.created_at == "20260610T064300Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == "K134_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_COMMAND_SOURCE"
    assert record.tool_name == "rh-selfdev cloud-command"
    assert record.artifact_refs == (str(slices_path),)
    assert record.payload == {
        "attempts": 2,
        "branch": "selfdev/k134",
        "command_argc": 10,
        "environment_id_present": True,
        "filename": slices_path.name,
        "slice_id": "K134_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_COMMAND_SOURCE",
    }
    assert "prompt" not in record.payload


def test_normalize_selfdev_codex_command_is_stable_without_prompt_payload(
    tmp_path: Path,
):
    slices_path = tmp_path / "rh-self-dev-slices.md"
    command_context = {
        "command_argc": 14,
        "model": "gpt-5.4",
        "output_path": ".rh-selfdev/out.json",
        "prompt_path": ".tmp/prompts/K135.md",
        "slice_id": "K135_RUNTIME_EVENT_STORE_SELFDEV_CODEX_COMMAND_SOURCE",
        "worktree_path": "../rh-selfdev-k135",
    }

    record = normalize_selfdev_codex_command(
        path=slices_path,
        command_context=command_context,
        created_at="20260610T064500Z",
    )

    assert record.event_type == "selfdev.codex_command_rendered"
    assert record.event_id == (
        "selfdev_codex_command:"
        "K135_RUNTIME_EVENT_STORE_SELFDEV_CODEX_COMMAND_SOURCE:"
        "20260610T064500Z"
    )
    assert record.created_at == "20260610T064500Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == "K135_RUNTIME_EVENT_STORE_SELFDEV_CODEX_COMMAND_SOURCE"
    assert record.tool_name == "rh-selfdev codex-command"
    assert record.artifact_refs == (str(slices_path),)
    assert record.payload == {
        "command_argc": 14,
        "filename": slices_path.name,
        "model": "gpt-5.4",
        "output_path": ".rh-selfdev/out.json",
        "prompt_path": ".tmp/prompts/K135.md",
        "slice_id": "K135_RUNTIME_EVENT_STORE_SELFDEV_CODEX_COMMAND_SOURCE",
        "worktree_path": "../rh-selfdev-k135",
    }
    assert "prompt_text" not in record.payload


def test_normalize_selfdev_cloud_submit_is_stable_without_prompt_or_output_payload(
    tmp_path: Path,
):
    slices_path = tmp_path / "rh-self-dev-slices.md"
    command_context = {
        "attempts": 2,
        "branch": "selfdev/k141",
        "command_argc": 10,
        "environment_id_present": True,
        "returncode": 0,
        "slice_id": "K141_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_SOURCE",
    }

    record = normalize_selfdev_cloud_submit(
        path=slices_path,
        command_context=command_context,
        created_at="20260610T101500Z",
    )

    assert record.event_type == "selfdev.cloud_submit_recorded"
    assert record.event_id == (
        "selfdev_cloud_submit:"
        "K141_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_SOURCE:"
        "20260610T101500Z"
    )
    assert record.created_at == "20260610T101500Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == "K141_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_SOURCE"
    assert record.tool_name == "rh-selfdev cloud-submit"
    assert record.artifact_refs == (str(slices_path),)
    assert record.payload == {
        "attempts": 2,
        "branch": "selfdev/k141",
        "command_argc": 10,
        "environment_id_present": True,
        "filename": slices_path.name,
        "returncode": 0,
        "slice_id": "K141_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_SOURCE",
    }
    assert "environment_id" not in record.payload
    assert "prompt" not in record.payload
    assert "stdout" not in record.payload
    assert "stderr" not in record.payload


def test_normalize_selfdev_cloud_submit_started_is_stable_without_prompt_or_output_payload(
    tmp_path: Path,
):
    slices_path = tmp_path / "rh-self-dev-slices.md"
    command_context = {
        "attempts": 2,
        "branch": "selfdev/k143",
        "command_argc": 10,
        "environment_id_present": True,
        "slice_id": "K143_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STARTED_SOURCE",
    }

    record = normalize_selfdev_cloud_submit_started(
        path=slices_path,
        command_context=command_context,
        created_at="20260610T104500Z",
    )

    assert record.event_type == "selfdev.cloud_submit_started"
    assert record.event_id == (
        "selfdev_cloud_submit_started:"
        "K143_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STARTED_SOURCE:"
        "20260610T104500Z"
    )
    assert record.created_at == "20260610T104500Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == (
        "K143_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STARTED_SOURCE"
    )
    assert record.tool_name == "rh-selfdev cloud-submit"
    assert record.artifact_refs == (str(slices_path),)
    assert record.payload == {
        "attempts": 2,
        "branch": "selfdev/k143",
        "command_argc": 10,
        "environment_id_present": True,
        "filename": slices_path.name,
        "slice_id": "K143_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STARTED_SOURCE",
    }
    assert "environment_id" not in record.payload
    assert "prompt" not in record.payload
    assert "stdout" not in record.payload
    assert "stderr" not in record.payload
    assert "returncode" not in record.payload


def test_normalize_selfdev_cloud_submit_failure_is_stable_without_prompt_or_output_payload(
    tmp_path: Path,
):
    slices_path = tmp_path / "rh-self-dev-slices.md"
    command_context = {
        "attempts": 1,
        "branch": "selfdev/k142",
        "command_argc": 10,
        "environment_id_present": True,
        "returncode": 17,
        "slice_id": "K142_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_FAILURE_SOURCE",
    }

    record = normalize_selfdev_cloud_submit_failure(
        path=slices_path,
        command_context=command_context,
        created_at="20260610T102300Z",
    )

    assert record.event_type == "selfdev.cloud_submit_failed"
    assert record.event_id == (
        "selfdev_cloud_submit_failed:"
        "K142_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_FAILURE_SOURCE:"
        "20260610T102300Z"
    )
    assert record.created_at == "20260610T102300Z"
    assert record.origin_surface == "self_dev"
    assert record.job_id == (
        "K142_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_FAILURE_SOURCE"
    )
    assert record.tool_name == "rh-selfdev cloud-submit"
    assert record.error_code == "cloud_submit_failed"
    assert record.artifact_refs == (str(slices_path),)
    assert record.payload == {
        "attempts": 1,
        "branch": "selfdev/k142",
        "command_argc": 10,
        "environment_id_present": True,
        "filename": slices_path.name,
        "returncode": 17,
        "slice_id": "K142_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_FAILURE_SOURCE",
    }
    assert "environment_id" not in record.payload
    assert "prompt" not in record.payload
    assert "stdout" not in record.payload
    assert "stderr" not in record.payload


def test_normalize_longtask_event_parses_payload_json_without_mutating_source():
    source = {
        "id": 9,
        "run_id": "run-1",
        "task_id": "task-7",
        "event_type": "task_completed",
        "message": "done",
        "payload_json": '{"artifact_path": "outputs/report.md", "count": 2}',
        "created_at": "2026-06-09T08:00:00Z",
    }
    original = dict(source)

    record = normalize_longtask_event(source)

    assert source == original
    assert record.event_id == "longtask_events:9"
    assert record.event_type == "longtask.task_completed"
    assert record.created_at == "2026-06-09T08:00:00Z"
    assert record.origin_surface == "longtask"
    assert record.job_id == "run-1"
    assert record.payload["task_id"] == "task-7"
    assert record.payload["message"] == "done"
    assert record.payload["count"] == 2
    assert record.artifact_refs == ("outputs/report.md",)
