"""Pure read-model normalization for runtime event-like records."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


RUNTIME_EVENT_RECORD_SCHEMA_VERSION = "runtime_event_record.v0"


@dataclass(frozen=True)
class RuntimeEventRecord:
    """Internal normalized view over existing RH event/provenance sources."""

    event_id: str
    event_type: str
    created_at: str | None
    origin_surface: str
    actor: str | None = None
    trace_id: str | None = None
    topic_id: int | None = None
    job_id: str | None = None
    tool_name: str | None = None
    artifact_refs: tuple[str, ...] = ()
    gate_decision: str | None = None
    error_code: str | None = None
    schema_version: str = RUNTIME_EVENT_RECORD_SCHEMA_VERSION
    payload: Mapping[str, Any] | None = None


def normalize_provenance_record(source: Mapping[str, Any]) -> RuntimeEventRecord:
    """Normalize a provenance row into a runtime event without leaking errors."""

    record_id = _optional_str(_lookup(source, "id"))
    success = _truthy_success(_lookup(source, "success"))
    provenance_ref = f"provenance_records:{record_id}"
    artifact_refs = _compact_tuple(
        _prefixed_ref("project_artifacts", _lookup(source, "artifact_id")),
        provenance_ref,
    )

    payload = _compact_dict(
        {
            "record_id": _coerce_int(_lookup(source, "id")),
            "stage": _optional_str(_lookup(source, "stage")),
            "backend": _optional_str(_lookup(source, "backend")),
            "success": success,
        }
    )

    return RuntimeEventRecord(
        event_id=provenance_ref,
        trace_id=_optional_str(_lookup(source, "trace_id")),
        event_type="tool.completed" if success else "tool.failed",
        created_at=_first_text(
            source,
            "finished_at",
            "completed_at",
            "created_at",
            "started_at",
        ),
        origin_surface=_first_text(source, "origin", "origin_surface") or "provenance",
        actor=_optional_str(_lookup(source, "actor")),
        topic_id=_coerce_int(_lookup(source, "topic_id")),
        job_id=_optional_str(_lookup(source, "job_id", "run_id")),
        tool_name=_first_text(source, "primitive", "tool_name"),
        artifact_refs=artifact_refs,
        gate_decision=_optional_str(_lookup(source, "gate_decision")),
        error_code=None if success else "tool_failed",
        payload=payload,
    )


def normalize_selfdev_handoff(
    *,
    path: Path,
    text: str,
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a supplied self-dev handoff body without reading the file."""

    slice_id = _selfdev_slice_id(path)
    status = _parse_frontmatter_value(text, "Status")
    event_timestamp = _selfdev_timestamp(path)
    event_id = f"selfdev_handoff:{slice_id}"
    if event_timestamp:
        event_id = f"{event_id}:{event_timestamp}"

    return RuntimeEventRecord(
        event_id=event_id,
        event_type="selfdev.handoff_created",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        artifact_refs=(str(path),),
        payload=_compact_dict(
            {
                "status": status,
                "filename": path.name,
            }
        ),
    )


def normalize_selfdev_gate_report(
    *,
    path: Path,
    text: str,
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a supplied self-dev gate report body without reading the file."""

    slice_id = _selfdev_slice_id(path)
    recommendation = _parse_frontmatter_value(text, "Recommendation")
    task_id = _parse_frontmatter_value(text, "Task id")
    event_timestamp = _selfdev_timestamp(path)
    event_id = f"selfdev_gate_report:{slice_id}"
    if event_timestamp:
        event_id = f"{event_id}:{event_timestamp}"

    return RuntimeEventRecord(
        event_id=event_id,
        event_type="selfdev.gate_report_created",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        artifact_refs=(str(path),),
        gate_decision=recommendation,
        payload=_compact_dict(
            {
                "filename": path.name,
                "recommendation": recommendation,
                "task_id": task_id,
            }
        ),
    )


def normalize_selfdev_prompt(
    *,
    path: Path,
    text: str,
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a supplied self-dev worker prompt without reading the file."""

    slice_id = _selfdev_slice_id(path)
    prompt_bytes = len(text.encode("utf-8"))
    return RuntimeEventRecord(
        event_id=f"selfdev_prompt:{slice_id}:{created_at}",
        event_type="selfdev.prompt_created",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        artifact_refs=(str(path),),
        payload={
            "filename": path.name,
            "prompt_bytes": prompt_bytes,
        },
    )


def normalize_selfdev_slice_status_change(
    *,
    path: Path,
    slice_id: str,
    previous_status: str,
    new_status: str,
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a script-owned self-dev slice status update."""

    return RuntimeEventRecord(
        event_id=f"selfdev_slice_status:{slice_id}:{created_at}",
        event_type="selfdev.slice_status_changed",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        artifact_refs=(str(path),),
        payload={
            "filename": path.name,
            "new_status": new_status,
            "previous_status": previous_status,
        },
    )


def normalize_selfdev_next_action(
    *,
    path: Path,
    action: Mapping[str, Any],
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a script-owned self-dev next-action report."""

    action_name = _optional_str(_lookup(action, "action")) or "unknown"
    slice_id = _optional_str(_lookup(action, "slice_id"))
    event_target = slice_id or "none"
    return RuntimeEventRecord(
        event_id=f"selfdev_next_action:{event_target}:{action_name}:{created_at}",
        event_type="selfdev.next_action_reported",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        artifact_refs=(str(path),),
        payload=_compact_dict(
            {
                "action": action_name,
                "filename": path.name,
                "human_gate": _optional_str(_lookup(action, "human_gate")),
                "phase": _optional_str(_lookup(action, "phase")),
                "reason": _optional_str(_lookup(action, "reason")),
                "risk": _optional_str(_lookup(action, "risk")),
                "slice_id": slice_id,
            }
        ),
    )


def normalize_human_feedback_record(
    *,
    payload: Mapping[str, Any],
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a durable human-feedback record into the runtime event shape."""

    record_id = _coerce_int(_lookup(payload, "experience_record_id"))
    lesson_id = _coerce_int(_lookup(payload, "lesson_id"))
    artifact_id = _coerce_int(_lookup(payload, "artifact_id"))
    topic_id = _coerce_int(_lookup(payload, "topic_id"))
    stage = _optional_str(_lookup(payload, "stage"))
    section = _optional_str(_lookup(payload, "section"))
    agent = _optional_str(_lookup(payload, "agent"))
    event_target = str(record_id or artifact_id or created_at)
    artifact_refs = _compact_tuple(
        _prefixed_ref("experience_records", record_id),
        _prefixed_ref("lessons", lesson_id),
        _prefixed_ref("project_artifacts", artifact_id),
    )
    return RuntimeEventRecord(
        event_id=f"human_feedback:{event_target}:{created_at}",
        event_type="selfdev.human_feedback_recorded",
        created_at=created_at,
        origin_surface="human_feedback",
        actor=agent,
        topic_id=topic_id,
        artifact_refs=artifact_refs,
        payload=_compact_dict(
            {
                "experience_record_id": record_id,
                "lesson_id": lesson_id,
                "artifact_id": artifact_id,
                "stage": stage,
                "section": section,
                "workspace_path": _optional_str(_lookup(payload, "workspace_path")),
                "agent": agent,
                "trigger_class": _optional_str(_lookup(payload, "trigger_class")),
                "feedback_excerpt": _optional_str(_lookup(payload, "feedback_excerpt")),
            }
        ),
    )


def normalize_selfdev_status(
    *,
    path: Path,
    status_payload: Mapping[str, Any],
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a script-owned self-dev status report."""

    slice_id = _optional_str(_lookup(status_payload, "slice_id"))
    event_target = slice_id or "none"
    risk_flags = _lookup(status_payload, "risk_flags")
    return RuntimeEventRecord(
        event_id=f"selfdev_status:{event_target}:{created_at}",
        event_type="selfdev.status_reported",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        artifact_refs=(str(path),),
        payload=_compact_dict(
            {
                "action": _optional_str(_lookup(status_payload, "action")),
                "dirty_file_count": _coerce_int(
                    _lookup(status_payload, "dirty_file_count")
                ),
                "filename": path.name,
                "phase": _optional_str(_lookup(status_payload, "phase")),
                "reason": _optional_str(_lookup(status_payload, "reason")),
                "risk": _optional_str(_lookup(status_payload, "risk")),
                "risk_flags": dict(risk_flags)
                if isinstance(risk_flags, Mapping)
                else None,
                "slice_id": slice_id,
            }
        ),
    )


def normalize_selfdev_cloud_command(
    *,
    path: Path,
    command_context: Mapping[str, Any],
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a script-owned cloud-command dry-run render."""

    slice_id = _optional_str(_lookup(command_context, "slice_id"))
    event_target = slice_id or "none"
    return RuntimeEventRecord(
        event_id=f"selfdev_cloud_command:{event_target}:{created_at}",
        event_type="selfdev.cloud_command_rendered",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        tool_name="rh-selfdev cloud-command",
        artifact_refs=(str(path),),
        payload=_compact_dict(
            {
                "attempts": _coerce_int(_lookup(command_context, "attempts")),
                "branch": _optional_str(_lookup(command_context, "branch")),
                "command_argc": _coerce_int(_lookup(command_context, "command_argc")),
                "environment_id_present": bool(
                    _lookup(command_context, "environment_id_present")
                ),
                "filename": path.name,
                "slice_id": slice_id,
            }
        ),
    )


def normalize_selfdev_cloud_submit(
    *,
    path: Path,
    command_context: Mapping[str, Any],
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a script-owned cloud-submit completion without output bodies."""

    slice_id = _optional_str(_lookup(command_context, "slice_id"))
    event_target = slice_id or "none"
    return RuntimeEventRecord(
        event_id=f"selfdev_cloud_submit:{event_target}:{created_at}",
        event_type="selfdev.cloud_submit_recorded",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        tool_name="rh-selfdev cloud-submit",
        artifact_refs=(str(path),),
        payload=_compact_dict(
            {
                "attempts": _coerce_int(_lookup(command_context, "attempts")),
                "branch": _optional_str(_lookup(command_context, "branch")),
                "command_argc": _coerce_int(_lookup(command_context, "command_argc")),
                "environment_id_present": bool(
                    _lookup(command_context, "environment_id_present")
                ),
                "filename": path.name,
                "returncode": _coerce_int(_lookup(command_context, "returncode")),
                "slice_id": slice_id,
            }
        ),
    )


def normalize_selfdev_cloud_submit_started(
    *,
    path: Path,
    command_context: Mapping[str, Any],
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a script-owned cloud-submit start without prompt/output bodies."""

    slice_id = _optional_str(_lookup(command_context, "slice_id"))
    event_target = slice_id or "none"
    return RuntimeEventRecord(
        event_id=f"selfdev_cloud_submit_started:{event_target}:{created_at}",
        event_type="selfdev.cloud_submit_started",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        tool_name="rh-selfdev cloud-submit",
        artifact_refs=(str(path),),
        payload=_compact_dict(
            {
                "attempts": _coerce_int(_lookup(command_context, "attempts")),
                "branch": _optional_str(_lookup(command_context, "branch")),
                "command_argc": _coerce_int(_lookup(command_context, "command_argc")),
                "environment_id_present": bool(
                    _lookup(command_context, "environment_id_present")
                ),
                "filename": path.name,
                "slice_id": slice_id,
            }
        ),
    )


def normalize_selfdev_cloud_submit_failure(
    *,
    path: Path,
    command_context: Mapping[str, Any],
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a script-owned cloud-submit failure without output bodies."""

    slice_id = _optional_str(_lookup(command_context, "slice_id"))
    event_target = slice_id or "none"
    return RuntimeEventRecord(
        event_id=f"selfdev_cloud_submit_failed:{event_target}:{created_at}",
        event_type="selfdev.cloud_submit_failed",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        tool_name="rh-selfdev cloud-submit",
        error_code="cloud_submit_failed",
        artifact_refs=(str(path),),
        payload=_compact_dict(
            {
                "attempts": _coerce_int(_lookup(command_context, "attempts")),
                "branch": _optional_str(_lookup(command_context, "branch")),
                "command_argc": _coerce_int(_lookup(command_context, "command_argc")),
                "environment_id_present": bool(
                    _lookup(command_context, "environment_id_present")
                ),
                "filename": path.name,
                "returncode": _coerce_int(_lookup(command_context, "returncode")),
                "slice_id": slice_id,
            }
        ),
    )


def normalize_selfdev_codex_command(
    *,
    path: Path,
    command_context: Mapping[str, Any],
    created_at: str,
) -> RuntimeEventRecord:
    """Normalize a script-owned codex-command dry-run render."""

    slice_id = _optional_str(_lookup(command_context, "slice_id"))
    event_target = slice_id or "none"
    return RuntimeEventRecord(
        event_id=f"selfdev_codex_command:{event_target}:{created_at}",
        event_type="selfdev.codex_command_rendered",
        created_at=created_at,
        origin_surface="self_dev",
        job_id=slice_id,
        tool_name="rh-selfdev codex-command",
        artifact_refs=(str(path),),
        payload=_compact_dict(
            {
                "command_argc": _coerce_int(_lookup(command_context, "command_argc")),
                "filename": path.name,
                "model": _optional_str(_lookup(command_context, "model")),
                "output_path": _optional_str(_lookup(command_context, "output_path")),
                "prompt_path": _optional_str(_lookup(command_context, "prompt_path")),
                "slice_id": slice_id,
                "worktree_path": _optional_str(
                    _lookup(command_context, "worktree_path")
                ),
            }
        ),
    )


def normalize_longtask_event(source: Mapping[str, Any]) -> RuntimeEventRecord:
    """Normalize a longtask event row into the runtime event read-model."""

    record_id = _optional_str(_lookup(source, "id"))
    parsed_payload = _parse_payload_json(_lookup(source, "payload_json"))
    artifact_path = _optional_str(
        parsed_payload.get("artifact_path") or _lookup(source, "artifact_path")
    )
    event_name = _optional_str(_lookup(source, "event_type")) or "event"

    payload = _compact_dict(
        {
            "task_id": _optional_str(_lookup(source, "task_id")),
            "message": _optional_str(_lookup(source, "message")),
            **parsed_payload,
        }
    )

    return RuntimeEventRecord(
        event_id=f"longtask_events:{record_id}",
        event_type=f"longtask.{event_name}",
        created_at=_first_text(source, "created_at", "finished_at", "started_at"),
        origin_surface="longtask",
        actor=_optional_str(_lookup(source, "actor")),
        trace_id=_optional_str(_lookup(source, "trace_id")),
        topic_id=_coerce_int(_lookup(source, "topic_id")),
        job_id=_optional_str(_lookup(source, "run_id", "job_id")),
        artifact_refs=_compact_tuple(artifact_path),
        error_code=_optional_str(_lookup(source, "error_code")),
        payload=payload,
    )


def runtime_event_record_to_dict(record: RuntimeEventRecord) -> dict[str, Any]:
    """Return a JSON-like dictionary for a normalized runtime event record."""

    payload = asdict(record)
    payload["artifact_refs"] = list(record.artifact_refs)
    payload["payload"] = dict(record.payload or {})
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


def _truthy_success(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "success", "succeeded", "completed"}:
        return True
    if text in {"0", "false", "no", "n", "failed", "failure", "error"}:
        return False
    return bool(text)


def _prefixed_ref(prefix: str, value: Any) -> str | None:
    text = _optional_str(value)
    if text is None:
        return None
    return f"{prefix}:{text}"


def _compact_tuple(*values: str | None) -> tuple[str, ...]:
    return tuple(value for value in values if value)


def _compact_dict(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _parse_payload_json(value: Any) -> dict[str, Any]:
    text = _optional_str(value)
    if text is None:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"payload_parse_error": "invalid_json"}
    if not isinstance(parsed, dict):
        return {"payload_parse_error": "non_object_json"}
    return dict(parsed)


def _selfdev_slice_id(path: Path) -> str:
    stem = path.stem
    match = re.match(r"^(?P<slice_id>[A-Z]\d+_[A-Z0-9_]+)-\d{8}T\d{6}Z$", stem)
    if match:
        return match.group("slice_id")
    return stem.rsplit("-", 1)[0] if "-" in stem else stem


def _selfdev_timestamp(path: Path) -> str | None:
    match = re.search(r"-(?P<timestamp>\d{8}T\d{6}Z)$", path.stem)
    if match:
        return match.group("timestamp")
    return None


def _parse_frontmatter_value(text: str, key: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(?P<value>.+?)\s*$", re.I | re.M)
    match = pattern.search(text)
    if match:
        return match.group("value")
    return None
