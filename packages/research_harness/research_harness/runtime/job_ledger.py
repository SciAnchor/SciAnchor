"""Pure read-model normalization for runtime job ledger records."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping


JOB_LEDGER_RECORD_SCHEMA_VERSION = "job_ledger_record.v0"

LedgerRecordType = Literal[
    "run",
    "task",
    "attempt",
    "gate",
    "origin",
    "workspace",
    "log",
    "artifact",
]
LedgerState = Literal[
    "queued",
    "running",
    "waiting_for_approval",
    "waiting_for_input",
    "blocked_by_gate",
    "failed",
    "cancelled",
    "completed",
]


@dataclass(frozen=True)
class JobLedgerRecord:
    """Internal normalized view over existing job-like RH state."""

    record_id: str
    record_type: LedgerRecordType
    source_type: str
    ledger_state: LedgerState
    source_status: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    attempt_id: str | None = None
    gate_id: str | None = None
    topic_id: int | None = None
    domain_id: int | None = None
    title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    artifact_refs: tuple[str, ...] = ()
    error_code: str | None = None
    schema_version: str = JOB_LEDGER_RECORD_SCHEMA_VERSION
    payload: Mapping[str, Any] | None = None


def normalize_longtask_run(source: Mapping[str, Any]) -> JobLedgerRecord:
    """Normalize a LongTask run row without mutating the source."""

    run_id = _optional_str(_lookup(source, "id", "run_id"))
    source_status = _first_text(source, "status")
    return JobLedgerRecord(
        record_id=f"longtask_runs:{run_id}",
        record_type="run",
        source_type="longtask_run",
        ledger_state=_normalize_longtask_state(source_status),
        source_status=source_status,
        run_id=run_id,
        title=_first_text(source, "title"),
        created_at=_first_text(source, "created_at"),
        updated_at=_first_text(source, "updated_at"),
        payload=_compact_dict(
            {
                "objective": _first_text(source, "objective"),
                "max_workers": _coerce_int(_lookup(source, "max_workers")),
            }
        ),
    )


def normalize_longtask_task(source: Mapping[str, Any]) -> JobLedgerRecord:
    """Normalize a LongTask task row into the ledger vocabulary."""

    task_id = _optional_str(_lookup(source, "id", "task_id"))
    source_status = _first_text(source, "status")
    return JobLedgerRecord(
        record_id=f"longtask_tasks:{task_id}",
        record_type="task",
        source_type="longtask_task",
        ledger_state=_normalize_longtask_state(source_status),
        source_status=source_status,
        run_id=_optional_str(_lookup(source, "run_id")),
        task_id=task_id,
        title=_first_text(source, "title"),
        created_at=_first_text(source, "created_at"),
        updated_at=_first_text(source, "updated_at"),
        artifact_refs=_compact_tuple(
            _first_text(source, "final_path"),
            _first_text(source, "result_path"),
        ),
        error_code=_longtask_error_code(source_status, "task_failed"),
        payload=_compact_dict(
            {
                "dependencies": _parse_jsonish_list(
                    _lookup(source, "dependencies", "dependencies_json")
                ),
                "write_scope": _parse_jsonish_list(
                    _lookup(source, "write_scope", "write_scope_json")
                ),
                "risk_level": _first_text(source, "risk_level"),
                "summary": _first_text(source, "summary"),
                "result": _parse_jsonish_object(_lookup(source, "result_json")),
            }
        ),
    )


def normalize_longtask_attempt(source: Mapping[str, Any]) -> JobLedgerRecord:
    """Normalize a LongTask attempt row without exposing raw error text."""

    attempt_id = _optional_str(_lookup(source, "id", "attempt_id"))
    source_status = _first_text(source, "status")
    artifact_refs = _compact_tuple(
        _first_text(source, "events_path"),
        _first_text(source, "final_path"),
        _first_text(source, "result_path"),
        _first_text(source, "quarantine_reason_path"),
    )
    return JobLedgerRecord(
        record_id=f"longtask_attempts:{attempt_id}",
        record_type="attempt",
        source_type="longtask_attempt",
        ledger_state=_normalize_longtask_state(source_status),
        source_status=source_status,
        run_id=_optional_str(_lookup(source, "run_id")),
        task_id=_optional_str(_lookup(source, "task_id")),
        attempt_id=attempt_id,
        started_at=_first_text(source, "started_at"),
        finished_at=_first_text(source, "finished_at"),
        artifact_refs=artifact_refs,
        error_code=_longtask_error_code(source_status, "attempt_failed"),
        payload=_compact_dict(
            {
                "exit_code": _coerce_int(_lookup(source, "exit_code")),
            }
        ),
    )


def normalize_longtask_gate(source: Mapping[str, Any]) -> JobLedgerRecord:
    """Normalize a LongTask gate row without exposing private notes or hashes."""

    gate_id = _optional_str(_lookup(source, "id", "gate_id"))
    source_status = _first_text(source, "status")
    decision = _first_text(source, "decision")
    return JobLedgerRecord(
        record_id=f"longtask_gates:{gate_id}",
        record_type="gate",
        source_type="longtask_gate",
        ledger_state=_normalize_gate_state(source_status, decision),
        source_status=source_status,
        run_id=_optional_str(_lookup(source, "run_id")),
        task_id=_optional_str(_lookup(source, "task_id")),
        gate_id=gate_id,
        title=_first_text(source, "title"),
        created_at=_first_text(source, "created_at"),
        updated_at=_first_text(source, "updated_at", "decided_at"),
        artifact_refs=_compact_tuple(_first_text(source, "decision_path")),
        payload=_compact_dict(
            {
                "gate_type": _first_text(source, "gate_type"),
                "decision": decision,
                "actor": _first_text(source, "actor"),
                "token_required": _coerce_bool(_lookup(source, "token_required"))
                or _lookup(source, "token_hash") is not None,
            }
        ),
    )


def normalize_async_job(source: Mapping[str, Any]) -> JobLedgerRecord:
    """Normalize an async_jobs row into a generic run ledger record."""

    job_id = _optional_str(_lookup(source, "id", "job_id"))
    source_status = _first_text(source, "status")
    return JobLedgerRecord(
        record_id=f"async_jobs:{job_id}",
        record_type="run",
        source_type="async_job",
        ledger_state=_normalize_async_state(source_status),
        source_status=source_status,
        run_id=job_id,
        task_id=_first_text(source, "job_type"),
        topic_id=_coerce_int(_lookup(source, "topic_id")),
        domain_id=_coerce_int(_lookup(source, "domain_id")),
        created_at=_first_text(source, "created_at"),
        updated_at=_first_text(source, "updated_at"),
        error_code=_async_error_code(source_status),
        payload=_compact_dict(
            {
                "job_type": _first_text(source, "job_type"),
                "idempotency_key": _first_text(source, "idempotency_key"),
                "input_params": _parse_jsonish_object(_lookup(source, "input_params")),
                "result": _parse_jsonish_object(_lookup(source, "result")),
            }
        ),
    )


def normalize_expansion_job(source: Mapping[str, Any]) -> JobLedgerRecord:
    """Normalize an expansion_jobs row with progress counters only."""

    job_id = _optional_str(_lookup(source, "id", "job_id"))
    source_status = _first_text(source, "status")
    return JobLedgerRecord(
        record_id=f"expansion_jobs:{job_id}",
        record_type="run",
        source_type="expansion_job",
        ledger_state=_normalize_async_state(source_status),
        source_status=source_status,
        run_id=job_id,
        topic_id=_coerce_int(_lookup(source, "topic_id")),
        created_at=_first_text(source, "created_at"),
        updated_at=_first_text(source, "updated_at"),
        error_code=_expansion_error_code(source_status),
        payload=_compact_dict(
            {
                "retrieval_target": _coerce_int(_lookup(source, "retrieval_target")),
                "deep_read_target": _coerce_int(_lookup(source, "deep_read_target")),
                "rounds_target": _coerce_int(_lookup(source, "rounds_target")),
                "current_round": _coerce_int(_lookup(source, "current_round")),
                "papers_fetched": _coerce_int(_lookup(source, "papers_fetched")),
                "papers_deep_read": _coerce_int(_lookup(source, "papers_deep_read")),
            }
        ),
    )


def job_ledger_record_to_dict(record: JobLedgerRecord) -> dict[str, Any]:
    """Return a JSON-like dictionary for a normalized job ledger record."""

    payload = asdict(record)
    payload["artifact_refs"] = list(record.artifact_refs)
    payload["payload"] = _clone_json_like(record.payload or {})
    return payload


def _lookup(source: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if hasattr(source, "get"):
            value = source.get(name)  # type: ignore[attr-defined]
            if value is not None:
                return value
            continue
        try:
            value = source[name]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            continue
        if value is not None:
            return value
    return None


def _first_text(source: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = _optional_str(_lookup(source, name))
        if value:
            return value
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "required"}:
        return True
    if text in {"0", "false", "no", "n", "none"}:
        return False
    return None


def _normalize_longtask_state(status: str | None) -> LedgerState:
    text = (status or "").strip().lower()
    if text in {"queued", "pending"}:
        return "queued"
    if text in {"active", "running", "dispatched"}:
        return "running"
    if text in {"waiting_gate", "awaiting_gate", "pending_gate"}:
        return "waiting_for_approval"
    if text in {"paused", "needs_input", "input_required", "replan_requested"}:
        return "waiting_for_input"
    if text in {"blocked", "rejected"}:
        return "blocked_by_gate"
    if text in {"complete", "completed", "done", "success", "succeeded"}:
        return "completed"
    if text in {"cancelled", "canceled", "skipped"}:
        return "cancelled"
    if text in {"quarantined", "failed", "failure", "error"}:
        return "failed"
    return "queued"


def _normalize_gate_state(status: str | None, decision: str | None) -> LedgerState:
    text = (decision or status or "").strip().lower()
    if text in {"approved", "complete", "completed"}:
        return "completed"
    if text == "replan_requested":
        return "waiting_for_input"
    if text in {"rejected", "blocked"}:
        return "blocked_by_gate"
    if text in {"paused", "needs_input"}:
        return "waiting_for_input"
    if text in {"pending", "waiting_gate", "waiting_for_approval"}:
        return "waiting_for_approval"
    return _normalize_longtask_state(status)


def _normalize_async_state(status: str | None) -> LedgerState:
    text = (status or "").strip().lower()
    if text in {"pending", "queued"}:
        return "queued"
    if text in {"running", "active"}:
        return "running"
    if text in {"completed", "complete", "done", "success", "succeeded"}:
        return "completed"
    if text in {"cancelled", "canceled"}:
        return "cancelled"
    if text in {"failed", "failure", "error"}:
        return "failed"
    return "queued"


def _longtask_error_code(status: str | None, code: str) -> str | None:
    return code if _normalize_longtask_state(status) == "failed" else None


def _async_error_code(status: str | None) -> str | None:
    return "async_job_failed" if _normalize_async_state(status) == "failed" else None


def _expansion_error_code(status: str | None) -> str | None:
    return (
        "expansion_job_failed" if _normalize_async_state(status) == "failed" else None
    )


def _compact_tuple(*values: str | None) -> tuple[str, ...]:
    return tuple(value for value in values if value)


def _compact_dict(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _parse_jsonish_object(value: Any) -> dict[str, Any] | None:
    parsed = _parse_jsonish(value)
    if parsed is None:
        return None
    if isinstance(parsed, Mapping):
        return dict(parsed)
    return {"value": _clone_json_like(parsed)}


def _parse_jsonish_list(value: Any) -> list[Any] | None:
    parsed = _parse_jsonish(value)
    if parsed is None:
        return None
    if isinstance(parsed, list):
        return [_clone_json_like(item) for item in parsed]
    return [_clone_json_like(parsed)]


def _parse_jsonish(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, int, float, bool)):
        return _clone_json_like(value)
    text = _optional_str(value)
    if text is None:
        return None
    try:
        return _clone_json_like(json.loads(text))
    except json.JSONDecodeError:
        return text


def _clone_json_like(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _clone_json_like(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_clone_json_like(item) for item in value]
    if isinstance(value, list):
        return [_clone_json_like(item) for item in value]
    return value
