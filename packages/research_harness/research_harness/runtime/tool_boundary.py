"""Pure read-model normalization for tool failures and gate decisions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping


TOOL_BOUNDARY_RECORD_SCHEMA_VERSION = "tool_boundary_record.v0"
GATE_DECISION_RECORD_SCHEMA_VERSION = "gate_decision_record.v0"


@dataclass(frozen=True)
class ToolBoundaryRecord:
    """Internal normalized view over existing tool-boundary payloads."""

    record_id: str
    event_type: str
    origin_surface: str
    tool_name: str | None = None
    failure_family: str | None = None
    error_code: str | None = None
    created_at: str | None = None
    trace_id: str | None = None
    topic_id: int | None = None
    job_id: str | None = None
    http_status: int | None = None
    backend: str | None = None
    recovery_hint: str | None = None
    approval_required: bool | None = None
    partial_reasons: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    schema_version: str = TOOL_BOUNDARY_RECORD_SCHEMA_VERSION
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class GateDecisionRecord:
    """Internal normalized view over existing gate-result payloads."""

    record_id: str
    event_type: str
    origin_surface: str
    gate_decision: str
    can_advance: bool
    gate_type: str | None = None
    stage: str | None = None
    created_at: str | None = None
    topic_id: int | None = None
    job_id: str | None = None
    tool_name: str | None = None
    blocking_reasons: tuple[str, ...] = ()
    missing_artifacts: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    error_code: str | None = None
    schema_version: str = GATE_DECISION_RECORD_SCHEMA_VERSION
    payload: Mapping[str, Any] | None = None


def normalize_tool_boundary(
    source: Mapping[str, Any],
    *,
    origin_surface: str | None = None,
) -> ToolBoundaryRecord:
    """Normalize an existing tool result/error payload without side effects."""

    error = _nested(source, "error")
    tool_name = _first(
        source, "tool_name", "command", "primitive", "capability", "name"
    )
    status = _first(source, "status", "state")
    raw_code = _first(error, "code", "error_code") or _first(
        source, "error_code", "code"
    )
    code = _code(raw_code)
    message = (
        _first(error, "message", "detail")
        or _first(source, "message", "detail", "reason")
        or (None if error else _first(source, "error"))
    )
    http_status = _int(_get(source, "http_status", "status_code"))
    event_type, failure_family, error_code = _classify(
        status=status,
        raw_code=raw_code,
        code=code,
        message=message,
        http_status=http_status,
        source=source,
    )
    capability = _first(source, "capability")
    payload = _compact(
        {
            "input_path": _first(error, "input_path", "loc", "path")
            or _first(source, "input_path", "loc", "path"),
            "message": _safe_message(message),
            "policy": _first(source, "policy", "approval_policy"),
            "context_mode": _first(source, "context_mode", "mode"),
            "action_type": _first(source, "action_type"),
            "capability": None if capability == tool_name else capability,
            "target_refs": _nonempty(_text_list(_get(source, "target_refs"))),
            "registered_only": _bool(_get(source, "registered_only")),
            "model_used": _first(source, "model_used"),
            "cost_usd": _float(_get(source, "cost_usd")),
            "counts": _safe_mapping(_get(source, "counts")),
            "warning_count": _count(_get(source, "warnings")),
            "writable_count": _int(_get(source, "writable_count")),
        }
    )
    return ToolBoundaryRecord(
        record_id=_record_id(
            "tool_boundary",
            _get(source, "id", "event_id", "tool_call_id"),
            origin_surface or _first(source, "origin_surface", "origin"),
            tool_name,
            status,
            code,
            _first(source, "created_at", "finished_at", "started_at"),
        ),
        event_type=event_type,
        origin_surface=origin_surface
        or _first(source, "origin_surface", "origin")
        or "unknown",
        tool_name=tool_name,
        failure_family=failure_family,
        error_code=error_code,
        created_at=_first(source, "created_at", "finished_at", "started_at"),
        trace_id=_first(source, "trace_id"),
        topic_id=_int(_get(source, "topic_id")),
        job_id=_first(source, "job_id", "run_id"),
        http_status=http_status,
        backend=_first(source, "backend"),
        recovery_hint=_safe_message(_first(source, "recovery_hint")),
        approval_required=_bool(_get(source, "approval_required")),
        partial_reasons=tuple(
            _text_list(_get(source, "partial_reasons", "skipped_reasons"))
        ),
        artifact_refs=_artifact_refs(source),
        payload=payload,
    )


def normalize_gate_decision(
    source: Mapping[str, Any],
    *,
    origin_surface: str | None = None,
) -> GateDecisionRecord:
    """Normalize an existing gate result without changing the decision."""

    gate = _nested(source, "gate")
    decision = (
        _first(source, "gate_decision", "decision", "gate_status")
        or _first(gate, "gate_decision", "decision", "status")
        or "unknown"
    )
    can_advance = _bool(_get(source, "can_advance"))
    if can_advance is None:
        can_advance = _bool(_get(gate, "can_advance"))
    if can_advance is None:
        can_advance = decision == "pass"
    blocked = not can_advance or decision != "pass"
    return GateDecisionRecord(
        record_id=_record_id(
            "gate_decision",
            _get(source, "id", "gate_id"),
            origin_surface or _first(source, "origin_surface", "origin"),
            _first(source, "gate_type") or _first(gate, "gate_type"),
            _first(source, "stage", "current_stage") or _first(gate, "stage"),
            decision,
            _get(source, "topic_id"),
        ),
        event_type="gate.blocked" if blocked else "gate.evaluated",
        origin_surface=origin_surface
        or _first(source, "origin_surface", "origin")
        or "unknown",
        gate_decision=decision,
        can_advance=can_advance,
        gate_type=_first(source, "gate_type") or _first(gate, "gate_type"),
        stage=_first(source, "stage", "current_stage") or _first(gate, "stage"),
        created_at=_first(source, "created_at", "finished_at", "started_at"),
        topic_id=_int(_get(source, "topic_id")),
        job_id=_first(source, "job_id", "run_id"),
        tool_name=_first(source, "tool_name", "command"),
        blocking_reasons=tuple(
            value
            for value in _text_list(
                _get(source, "blocking_reasons", "reasons", "reason")
                or _get(gate, "blocking_reasons", "reasons", "reason")
            )
            if _safe_message(value)
        ),
        missing_artifacts=tuple(
            _text_list(
                _get(source, "missing_artifacts", "missing")
                or _get(gate, "missing_artifacts", "missing")
            )
        ),
        artifact_refs=_artifact_refs(
            source, extra_project_fields=("gate_decision_artifact_id",)
        ),
        error_code="gate_blocked" if blocked else None,
        payload=_compact(
            {
                "source_status": _first(source, "status"),
                "gate_status": _first(source, "gate_status") or _first(gate, "status"),
            }
        ),
    )


def tool_boundary_record_to_dict(record: ToolBoundaryRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["partial_reasons"] = list(record.partial_reasons)
    payload["artifact_refs"] = list(record.artifact_refs)
    payload["payload"] = _json_clone(record.payload or {})
    return payload


def gate_decision_record_to_dict(record: GateDecisionRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["blocking_reasons"] = list(record.blocking_reasons)
    payload["missing_artifacts"] = list(record.missing_artifacts)
    payload["artifact_refs"] = list(record.artifact_refs)
    payload["payload"] = _json_clone(record.payload or {})
    return payload


def _classify(
    *,
    status: str | None,
    raw_code: str | None,
    code: str | None,
    message: str | None,
    http_status: int | None,
    source: Mapping[str, Any],
) -> tuple[str, str | None, str | None]:
    status_text = (status or "").lower()
    raw_upper = (raw_code or "").upper()
    message_text = (message or "").lower()
    if status_text == "partial" or _get(source, "partial_reasons") is not None:
        return "tool.partial", "partial.completed", "partial_completed"
    if raw_upper in {"INVALID_ARGUMENT", "VALIDATION_ERROR"} or http_status in {
        400,
        422,
    }:
        return "tool.schema_invalid", "schema.invalid", code or "schema_invalid"
    if (
        raw_upper in {"UNKNOWN_COMMAND", "UNKNOWN_TOOL"}
        or "unknown tool" in message_text
    ):
        return "tool.denied", "tool.unknown", code or "unknown_tool"
    if (
        raw_upper in {"COMMAND_NOT_ROUTED", "POLICY_DENIED", "FORBIDDEN"}
        or _get(source, "policy") is not None
        or status_text in {"rejected", "denied"}
    ):
        return "tool.denied", "policy.denied", code or "policy_denied"
    if raw_upper == "PRIMITIVE_FAILED":
        return "tool.failed", "backend.failed", code or "primitive_failed"
    if code or status_text in {"error", "failed", "failure"}:
        return "tool.failed", "backend.failed", code or "tool_failed"
    if status_text in {"completed", "complete", "success", "succeeded", "ok"}:
        return "tool.completed", None, None
    return "tool.requested", None, None


def _get(source: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = source.get(name)
        if value is not None:
            return value
    return None


def _nested(source: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = _get(source, name)
    return value if isinstance(value, Mapping) else {}


def _first(source: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = _str(_get(source, name))
        if value:
            return value
    return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _code(value: str | None) -> str | None:
    text = _str(value)
    if text is None:
        return None
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or None


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "required", "approved", "pass"}:
        return True
    if text in {"0", "false", "no", "none", "rejected", "fail", "blocked"}:
        return False
    return None


def _text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Mapping):
        return [str(key) for key in value.keys()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (Mapping, list, tuple, set)):
        return len(value)
    return 1 if str(value).strip() else 0


def _safe_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    safe = {
        str(key): item
        for key, item in value.items()
        if isinstance(item, (str, int, float, bool)) or item is None
    }
    return safe or None


def _artifact_refs(
    source: Mapping[str, Any],
    *,
    extra_project_fields: tuple[str, ...] = (),
) -> tuple[str, ...]:
    refs: list[str] = []
    for field in ("artifact_id", *extra_project_fields):
        value = _str(_get(source, field))
        if value:
            refs.append(f"project_artifacts:{value}")
    for field in ("output_ref", "receipt_ref", "artifact_path"):
        value = _str(_get(source, field))
        if value:
            refs.append(value)
    return tuple(refs)


def _safe_message(value: str | None) -> str | None:
    text = _str(value)
    if text is None:
        return None
    lower = text.lower()
    if any(
        marker in lower
        for marker in ("/private/", "traceback", "select ", " sk-", "token=", "secret")
    ):
        return None
    return text[:240]


def _nonempty(value: list[str]) -> list[str] | None:
    return value or None


def _compact(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _json_clone(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return str(value)


def _record_id(prefix: str, explicit_id: Any, *parts: Any) -> str:
    explicit = _str(explicit_id)
    if explicit:
        return f"{prefix}:{explicit}"
    text = json.dumps([_str(part) for part in parts], sort_keys=True)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"
