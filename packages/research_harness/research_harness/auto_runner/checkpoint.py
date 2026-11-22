"""Checkpoint persistence for the auto-runner.

The checkpoint is the runner-local resume state. The orchestrator DB is
canonical for workflow semantics; the checkpoint is canonical for mid-stage
runner state (pending tool, retry counters, codex handoff, context summaries).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..runtime import RunTrace, TraceStep

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_human_decision() -> dict[str, Any]:
    return {
        "schema_version": "rh.human_decision_request.v2",
        "requested": False,
        "request_id": "",
        "stage": "",
        "checkpoint": "",
        "reason_code": "",
        "prompt": "",
        "options": [],  # Now each option can have: action, label, description, recommended, preference_score, expected_effect, default_action
        "selected": "",
        "decision_status": "",
        "reasoning": "",
        "params": {},
        "created_at": "",
        "decided_at": "",
        "auto_selected": False,  # v2: whether decision was auto-applied in autonomous mode
        "auto_selection_reason": "",  # v2: why this option was chosen automatically
    }


def _new_run_trace(
    topic_id: int,
    *,
    mode: str,
    session_command: list[str],
    created_at: str,
) -> dict[str, Any]:
    trace = RunTrace(
        run_id=f"auto_runner.topic.{topic_id}.{created_at}",
        task_id=f"topic:{topic_id}",
        trial_id=f"topic:{topic_id}",
        status="running",
        started_at=created_at,
        inputs={
            "topic_id": topic_id,
            "mode": mode,
            "session_command": list(session_command),
        },
    )
    return trace.to_dict()


def _event_status(event: str) -> str:
    lowered = event.lower()
    if "block" in lowered or "halt" in lowered:
        return "blocked"
    if "error" in lowered or "fail" in lowered:
        return "failed"
    return "success"


def _ensure_run_trace(data: dict[str, Any]) -> dict[str, Any]:
    trace = data.get("run_trace")
    if isinstance(trace, dict):
        return trace

    created_at = str(data.get("created_at") or _utc_now())
    session_command = data.get("session_command")
    if not isinstance(session_command, list):
        session_command = ["claude-kimi"]
    trace = _new_run_trace(
        int(data.get("topic_id") or 0),
        mode=str(data.get("mode") or "standard"),
        session_command=[str(item) for item in session_command],
        created_at=created_at,
    )
    data["run_trace"] = trace
    return trace


def new_checkpoint(
    topic_id: int,
    *,
    mode: str = "standard",
    session_command: list[str] | None = None,
) -> dict[str, Any]:
    """Create a fresh checkpoint seeded with defaults."""
    created_at = _utc_now()
    command = session_command or ["claude-kimi"]
    return {
        "schema_version": SCHEMA_VERSION,
        "topic_id": topic_id,
        "mode": mode,
        "session_command": command,
        "current_stage": "init",
        "current_stage_attempt": 1,
        "stage_state": "pending",  # pending | running | needs_codex | needs_human | blocked | complete | error
        "artifacts": {},
        "stage_context": {
            "summary_md": "",
            "paper_ids": [],
            "open_issue_ids": [],
            "search_queries": [],
        },
        "codex_handoff": {
            "requested": False,
            "stage": "",
            "request_path": "",
            "response_path": "",
            "verdict": "",
        },
        "human_decision": _empty_human_decision(),
        "last_error": {
            "kind": "",
            "message": "",
            "tool_name": "",
            "recovery_hint": "",
            "retry_count": 0,
        },
        "history": [],
        "run_trace": _new_run_trace(
            topic_id,
            mode=mode,
            session_command=command,
            created_at=created_at,
        ),
        "created_at": created_at,
        "updated_at": created_at,
    }


def checkpoint_path(base_dir: Path, topic_id: int) -> Path:
    """Return the checkpoint file path for a topic."""
    return base_dir / "auto_runner" / "checkpoints" / f"topic_{topic_id}.json"


def handoff_dir(base_dir: Path, topic_id: int, stage: str) -> Path:
    """Return the handoff directory for a topic stage."""
    return base_dir / "auto_runner" / "handoffs" / f"topic_{topic_id}" / stage


def _clean_stale_temps(directory: Path) -> None:
    """Remove stale .tmp files left by interrupted save_checkpoint calls."""
    if not directory.is_dir():
        return
    for tmp in directory.glob("*.tmp"):
        try:
            tmp.unlink()
            logger.info("Cleaned stale temp file: %s", tmp)
        except OSError:
            pass


@contextmanager
def checkpoint_lock(path: Path) -> Iterator[None]:
    """Serialize checkpoint writers and sync read-check-write transactions."""
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - RH runner targets POSIX hosts
        raise RuntimeError("checkpoint file locking is unavailable") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_checkpoint(path: Path) -> dict[str, Any] | None:
    """Load checkpoint from file. Returns None if not found."""
    _clean_stale_temps(path.parent)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION:
            logger.warning("Checkpoint schema version mismatch: %s", path)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load checkpoint %s: %s", path, exc)
        return None


def _save_checkpoint_unlocked(path: Path, data: dict[str, Any]) -> None:
    """Persist checkpoint to file atomically (write-to-temp + rename)."""
    data["updated_at"] = _utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.replace(tmp_path, str(path))
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_checkpoint(
    path: Path,
    data: dict[str, Any],
    *,
    acquire_lock: bool = True,
) -> None:
    """Persist a checkpoint atomically while serializing normal writers."""
    if not acquire_lock:
        _save_checkpoint_unlocked(path, data)
        return
    with checkpoint_lock(path):
        _save_checkpoint_unlocked(path, data)


def record_event(
    data: dict[str, Any],
    *,
    stage: str,
    event: str,
    detail: str = "",
) -> None:
    """Append an event to the checkpoint history."""
    ts = _utc_now()
    data.setdefault("history", []).append(
        {
            "ts": ts,
            "stage": stage,
            "event": event,
            "detail": detail,
        }
    )
    # Keep history bounded
    if len(data["history"]) > 200:
        data["history"] = data["history"][-200:]

    trace = RunTrace(**_ensure_run_trace(data))
    step_index = len(trace.steps) + 1
    step = TraceStep(
        step_id=f"{stage}.{event}.{step_index}",
        kind="stage_event",
        status=_event_status(event),
        started_at=ts,
        finished_at=ts,
        metadata={
            "stage": stage,
            "event": event,
            "detail": detail,
        },
    )
    data["run_trace"] = RunTrace(
        run_id=trace.run_id,
        task_id=trace.task_id,
        trial_id=trace.trial_id,
        status=trace.status,
        started_at=trace.started_at,
        finished_at=trace.finished_at,
        inputs=trace.inputs,
        steps=(*trace.steps, step),
        outputs=trace.outputs,
        costs=trace.costs,
        errors=trace.errors,
    ).to_dict()


def record_artifact(
    data: dict[str, Any],
    *,
    stage: str,
    artifact_type: str,
    artifact_id: int,
    version: int = 1,
) -> None:
    """Record an artifact ID in the checkpoint."""
    stage_artifacts = data.setdefault("artifacts", {}).setdefault(stage, {})
    stage_artifacts[artifact_type] = {
        "artifact_id": artifact_id,
        "version": version,
    }


def record_error(
    data: dict[str, Any],
    *,
    kind: str,
    message: str,
    tool_name: str = "",
    recovery_hint: str = "",
) -> None:
    """Record the latest error in the checkpoint."""
    err = data.setdefault("last_error", {})
    err["kind"] = kind
    err["message"] = message[:500]
    err["tool_name"] = tool_name
    err["recovery_hint"] = recovery_hint[:500]
    err["retry_count"] = err.get("retry_count", 0) + 1


def clear_error(data: dict[str, Any]) -> None:
    """Clear error state after successful recovery."""
    data["last_error"] = {
        "kind": "",
        "message": "",
        "tool_name": "",
        "recovery_hint": "",
        "retry_count": 0,
    }


def update_stage(
    data: dict[str, Any],
    *,
    stage: str,
    state: str,
    summary_md: str = "",
) -> None:
    """Update the current stage and state."""
    data["current_stage"] = stage
    data["stage_state"] = state
    if summary_md:
        data.setdefault("stage_context", {})["summary_md"] = summary_md


def set_human_decision_request(
    data: dict[str, Any],
    *,
    stage: str,
    checkpoint: str,
    reason_code: str,
    prompt: str,
    options: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a pending human decision request in the checkpoint."""
    created_at = _utc_now()
    request = _empty_human_decision()
    request.update(
        {
            "requested": True,
            "request_id": f"human.topic.{data.get('topic_id', 0)}.{stage}.{reason_code}.{created_at}",
            "stage": stage,
            "checkpoint": checkpoint,
            "reason_code": reason_code,
            "prompt": prompt,
            "options": list(options),
            "decision_status": "pending",
            "params": dict(params or {}),
            "created_at": created_at,
        }
    )
    data["human_decision"] = request
    record_event(
        data,
        stage=stage,
        event="human_decision_requested",
        detail=f"{checkpoint}:{reason_code}",
    )
    return request


def record_human_decision(
    data: dict[str, Any],
    *,
    choice: str,
    reasoning: str = "",
    params: dict[str, Any] | None = None,
    decision_status: str = "accepted",
) -> dict[str, Any]:
    """Record the selected choice for a pending human decision request."""
    decision = data.get("human_decision")
    if not isinstance(decision, dict) or not decision.get("requested"):
        raise ValueError("No pending human decision request")
    actions = {
        str(option.get("action"))
        for option in decision.get("options", [])
        if isinstance(option, dict) and option.get("action")
    }
    if actions and choice not in actions:
        raise ValueError(f"Unsupported human decision: {choice}")
    merged_params = dict(decision.get("params") or {})
    merged_params.update(params or {})
    decision.update(
        {
            "requested": False,
            "selected": choice,
            "decision_status": decision_status,
            "reasoning": reasoning,
            "params": merged_params,
            "decided_at": _utc_now(),
        }
    )
    data["human_decision"] = decision
    record_event(
        data,
        stage=str(decision.get("stage") or data.get("current_stage") or ""),
        event="human_decision_recorded",
        detail=choice,
    )
    return decision


def set_codex_handoff(
    data: dict[str, Any],
    *,
    stage: str,
    request_path: str,
    response_path: str,
) -> None:
    """Mark that a codex handoff is pending."""
    data["codex_handoff"] = {
        "requested": True,
        "stage": stage,
        "request_path": request_path,
        "response_path": response_path,
        "verdict": "",
    }


def clear_codex_handoff(
    data: dict[str, Any], *, verdict: str = "", stage: str = ""
) -> None:
    """Clear codex handoff after completion. Preserves stage for verdict scoping."""
    prev_stage = data.get("codex_handoff", {}).get("stage", "")
    data["codex_handoff"] = {
        "requested": False,
        "stage": stage or prev_stage,
        "request_path": "",
        "response_path": "",
        "verdict": verdict,
    }


# Paper-production run-policy schema membership. One source of truth: the
# entry writes v2 while several consumers compared against a v1 literal,
# which silently disabled the autonomous completion gate (and every blocker
# behind it) on all live runs. Any new schema version is added HERE only.
PAPER_PRODUCTION_POLICY_SCHEMAS = frozenset(
    {
        "rh.paper_production_run_policy.v1",
        "rh.paper_production_run_policy.v2",
    }
)


def paper_production_policy(checkpoint_data: dict[str, Any]) -> dict[str, Any]:
    """The run policy dict, or {} when absent or of an unknown schema."""
    policy = checkpoint_data.get("paper_production_run_policy")
    if not isinstance(policy, dict):
        return {}
    if str(policy.get("schema_version") or "") not in PAPER_PRODUCTION_POLICY_SCHEMAS:
        return {}
    return policy
