"""State-surface labelling for RH run-progress diagnostics (BUG-06).

RH exposes two distinct state surfaces for a topic's run progress:

``orchestrator_run``
    The ``orchestrator_runs`` row in the RH database. This is the
    **authoritative** surface and is what ``rh orchestrator status`` reads.

``local_auto_runner_checkpoint``
    The local auto-runner checkpoint JSON at
    ``<state-dir>/auto_runner/checkpoints/topic_<id>.json``. This is what
    ``rh paper-production status`` reads, and it can go stale while the
    orchestrator run advances.

The two surfaces can legitimately disagree. A status reader who cannot tell
which surface produced a line has no way to notice that disagreement — that is
exactly how a stale ``init`` checkpoint was read as "the run reverted" while the
orchestrator run was at ``build``. Every status command therefore labels the
surface it read, and any command reading the non-authoritative surface reports
a divergence instead of silently presenting stale state as truth.

This module only *describes* state. It never reads or writes run state.
"""

from __future__ import annotations

from typing import Any

STATE_SURFACE_SCHEMA_VERSION = "rh.state_surface.v1"

ORCHESTRATOR_RUN_SURFACE = "orchestrator_run"
LOCAL_CHECKPOINT_SURFACE = "local_auto_runner_checkpoint"

#: The orchestrator run always wins when the surfaces disagree.
AUTHORITATIVE_STATE_SURFACE = ORCHESTRATOR_RUN_SURFACE


def normalize_stage_label(value: object) -> str | None:
    """Strip an auto-runner ``"3/6: build"`` progress prefix down to ``"build"``.

    The checkpoint surface renders stages with an ordinal prefix while the
    orchestrator surface stores the bare stage name; both must be comparable.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "?":
        return None
    _, separator, tail = text.partition(": ")
    if separator and tail.strip():
        return tail.strip()
    return text


def orchestrator_run_surface_labels(
    *,
    orchestrator_run_id: int | None,
) -> dict[str, Any]:
    """Labels for a payload read from the authoritative orchestrator run."""
    return {
        "state_surface_schema_version": STATE_SURFACE_SCHEMA_VERSION,
        "state_surface": ORCHESTRATOR_RUN_SURFACE,
        "state_surface_source": {"orchestrator_run_id": orchestrator_run_id},
        "state_surface_authoritative": True,
        "authoritative_state_surface": AUTHORITATIVE_STATE_SURFACE,
        "state_surface_divergence": None,
    }


def local_checkpoint_surface_labels(
    *,
    checkpoint_path: str,
    divergence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Labels for a payload read from the local auto-runner checkpoint."""
    return {
        "state_surface_schema_version": STATE_SURFACE_SCHEMA_VERSION,
        "state_surface": LOCAL_CHECKPOINT_SURFACE,
        "state_surface_source": {"checkpoint_path": checkpoint_path},
        "state_surface_authoritative": False,
        "authoritative_state_surface": AUTHORITATIVE_STATE_SURFACE,
        "state_surface_divergence": divergence,
    }


def detect_checkpoint_divergence(
    *,
    checkpoint_path: str,
    checkpoint_stage: object,
    orchestrator_run_id: int | None,
    orchestrator_stage: object,
    orchestrator_stage_status: object = None,
) -> dict[str, Any] | None:
    """Describe a checkpoint/orchestrator stage disagreement, if there is one.

    Returns ``None`` when there is no orchestrator run, when either stage is
    unknown, or when the two surfaces agree.
    """
    if orchestrator_run_id is None:
        return None
    read_stage = normalize_stage_label(checkpoint_stage)
    authoritative_stage = normalize_stage_label(orchestrator_stage)
    if read_stage is None or authoritative_stage is None:
        return None
    if read_stage == authoritative_stage:
        return None

    stage_status = str(orchestrator_stage_status) if orchestrator_stage_status else None
    return {
        "detected": True,
        "read_surface": LOCAL_CHECKPOINT_SURFACE,
        "read_stage": read_stage,
        "checkpoint_path": checkpoint_path,
        "authoritative_surface": AUTHORITATIVE_STATE_SURFACE,
        "authoritative_stage": authoritative_stage,
        "authoritative_stage_status": stage_status,
        "orchestrator_run_id": orchestrator_run_id,
        "message": (
            f"STATE SURFACE DIVERGENCE: {LOCAL_CHECKPOINT_SURFACE} "
            f"({checkpoint_path}) reports stage '{read_stage}', while "
            f"{ORCHESTRATOR_RUN_SURFACE} (run id {orchestrator_run_id}) reports "
            f"stage '{authoritative_stage}'"
            + (f" ({stage_status})" if stage_status else "")
            + f". The {AUTHORITATIVE_STATE_SURFACE} surface is authoritative; "
            "this command read the local checkpoint, which may be stale."
        ),
    }


def state_surface_text_lines(payload: dict[str, Any]) -> list[str]:
    """Render the human-readable state-surface block for a status payload."""
    surface = payload.get("state_surface")
    if not surface:
        return []

    source = payload.get("state_surface_source")
    source_bits: list[str] = []
    if isinstance(source, dict):
        for key, value in source.items():
            if value is not None:
                source_bits.append(f"{key}={value}")
    authority = (
        "authoritative"
        if payload.get("state_surface_authoritative")
        else f"NOT authoritative; authoritative surface is "
        f"{payload.get('authoritative_state_surface', AUTHORITATIVE_STATE_SURFACE)}"
    )
    header = f"Read from state_surface={surface} ({authority})"
    if source_bits:
        header += " | " + " ".join(source_bits)
    lines = [header]

    divergence = payload.get("state_surface_divergence")
    if isinstance(divergence, dict) and divergence.get("detected"):
        lines.append(str(divergence.get("message", "")))
    return lines


def append_state_surface_text(text: str, payload: dict[str, Any]) -> str:
    """Append the state-surface block to an existing human summary."""
    lines = state_surface_text_lines(payload)
    if not lines:
        return text
    block = "\n".join(lines)
    return f"{text}\n{block}" if text else block


__all__ = [
    "AUTHORITATIVE_STATE_SURFACE",
    "LOCAL_CHECKPOINT_SURFACE",
    "ORCHESTRATOR_RUN_SURFACE",
    "STATE_SURFACE_SCHEMA_VERSION",
    "append_state_surface_text",
    "detect_checkpoint_divergence",
    "local_checkpoint_surface_labels",
    "normalize_stage_label",
    "orchestrator_run_surface_labels",
    "state_surface_text_lines",
]
