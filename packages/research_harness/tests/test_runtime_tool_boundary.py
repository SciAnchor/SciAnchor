from __future__ import annotations

from research_harness.runtime.tool_boundary import (
    GATE_DECISION_RECORD_SCHEMA_VERSION,
    TOOL_BOUNDARY_RECORD_SCHEMA_VERSION,
    gate_decision_record_to_dict,
    normalize_gate_decision,
    normalize_tool_boundary,
    tool_boundary_record_to_dict,
)


def test_normalize_schema_invalid_service_error_without_input_leak():
    source = {
        "command": "paper_search",
        "status": "error",
        "error": {
            "code": "INVALID_ARGUMENT",
            "message": "query must be a string: /private/topic.db",
            "input_path": "arguments.query",
        },
        "http_status": 422,
        "arguments": {"query": "do not include raw arguments"},
    }
    original = dict(source)

    record = normalize_tool_boundary(source, origin_surface="service")
    payload = tool_boundary_record_to_dict(record)

    assert source == original
    assert record.event_type == "tool.schema_invalid"
    assert record.failure_family == "schema.invalid"
    assert record.tool_name == "paper_search"
    assert record.error_code == "invalid_argument"
    assert record.http_status == 422
    assert record.payload["input_path"] == "arguments.query"
    assert record.schema_version == TOOL_BOUNDARY_RECORD_SCHEMA_VERSION
    encoded = str(payload)
    assert "/private/topic.db" not in encoded
    assert "do not include raw arguments" not in encoded


def test_normalize_unknown_tool_as_denied_tool_boundary():
    record = normalize_tool_boundary(
        {
            "tool_name": "paper_teleport",
            "status": "error",
            "error_code": "UNKNOWN_COMMAND",
            "message": "Unknown tool: paper_teleport",
            "created_at": "2026-06-09T10:00:00Z",
        },
        origin_surface="mcp",
    )

    assert record.event_type == "tool.denied"
    assert record.failure_family == "tool.unknown"
    assert record.error_code == "unknown_command"
    assert record.origin_surface == "mcp"
    assert record.created_at == "2026-06-09T10:00:00Z"


def test_normalize_policy_denied_keeps_policy_metadata_only():
    record = normalize_tool_boundary(
        {
            "capability": "zotero_import_file_attachment",
            "status": "rejected",
            "reason": "Path /private/outside.pdf is outside trusted roots",
            "policy": "capability_allowlist",
            "approval_required": True,
            "context_mode": "read_only",
        },
        origin_surface="zotero",
    )
    payload = tool_boundary_record_to_dict(record)

    assert record.event_type == "tool.denied"
    assert record.failure_family == "policy.denied"
    assert record.error_code == "policy_denied"
    assert record.tool_name == "zotero_import_file_attachment"
    assert record.approval_required is True
    assert record.payload == {
        "policy": "capability_allowlist",
        "context_mode": "read_only",
    }
    assert "/private/outside.pdf" not in str(payload)


def test_normalize_primitive_failed_uses_backend_failure_without_trace_leak():
    record = normalize_tool_boundary(
        {
            "primitive": "claim_extract",
            "status": "error",
            "error": {
                "code": "PRIMITIVE_FAILED",
                "message": "Traceback with sk-test and /private/path",
            },
            "backend": "tracked_backend",
            "model_used": "gpt-test",
            "cost_usd": 0.03,
            "recovery_hint": "retry with narrower paper set",
            "trace_id": "trace-1",
            "topic_id": "7",
        },
        origin_surface="mcp",
    )
    payload = tool_boundary_record_to_dict(record)

    assert record.event_type == "tool.failed"
    assert record.failure_family == "backend.failed"
    assert record.error_code == "primitive_failed"
    assert record.tool_name == "claim_extract"
    assert record.backend == "tracked_backend"
    assert record.recovery_hint == "retry with narrower paper set"
    assert record.topic_id == 7
    assert record.payload["model_used"] == "gpt-test"
    assert record.payload["cost_usd"] == 0.03
    assert "sk-test" not in str(payload)
    assert "/private/path" not in str(payload)


def test_normalize_gate_blocked_preserves_decision_without_changing_it():
    source = {
        "topic_id": 9,
        "stage": "propose",
        "gate_type": "coverage_gate",
        "gate_decision": "needs_coverage",
        "can_advance": False,
        "missing_artifacts": ["claim_matrix", "baseline_table"],
        "blocking_reasons": ["missing required evidence"],
        "artifact_id": 44,
        "created_at": "2026-06-09T10:01:00Z",
    }
    original = dict(source)

    record = normalize_gate_decision(source, origin_surface="orchestrator")
    payload = gate_decision_record_to_dict(record)

    assert source == original
    assert record.event_type == "gate.blocked"
    assert record.gate_decision == "needs_coverage"
    assert record.can_advance is False
    assert record.stage == "propose"
    assert record.missing_artifacts == ("claim_matrix", "baseline_table")
    assert record.blocking_reasons == ("missing required evidence",)
    assert record.artifact_refs == ("project_artifacts:44",)
    assert record.error_code == "gate_blocked"
    assert payload["schema_version"] == GATE_DECISION_RECORD_SCHEMA_VERSION


def test_normalize_partial_completed_keeps_counts_and_reasons():
    record = normalize_tool_boundary(
        {
            "tool_name": "zotero_sync",
            "status": "partial",
            "counts": {"completed": 3, "skipped": 2},
            "warnings": ["2 papers missing DOI"],
            "partial_reasons": ["missing_pdf", "blocked_record"],
            "receipt_ref": "receipts/zotero-sync-1.json",
        },
        origin_surface="zotero",
    )

    assert record.event_type == "tool.partial"
    assert record.failure_family == "partial.completed"
    assert record.error_code == "partial_completed"
    assert record.partial_reasons == ("missing_pdf", "blocked_record")
    assert record.artifact_refs == ("receipts/zotero-sync-1.json",)
    assert record.payload["counts"] == {"completed": 3, "skipped": 2}
    assert record.payload["warning_count"] == 1
