"""Context-budget telemetry (P-6 / FIX02).

RH assembles model context with scattered hardcoded character limits and keeps
no record of what was dropped. Consequence: an evidence item can be absent from
the model input with no trace, so a wrong answer cannot be attributed to
"the evidence never arrived" versus "the model ignored it". That is a
provenance hole, not merely an efficiency problem.

This module records what was offered and what survived. Deliberate boundaries:

* Instrumentation ONLY — it never changes an assembly result, never truncates,
  never gates. Removing it must leave behaviour byte-identical.
* Never raises into a production path. A telemetry bug must not fail a run.
* Append-only JSONL, human-readable, git-friendly, replayable — the same
  substrate the authority model already requires for replayable events.

Conservation invariant: ``offered == kept + dropped`` for every event.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTEXT_BUDGET_SCHEMA = "rh.schema.event.context_budget.v1"

#: Set to a writable path to enable telemetry globally. When unset, scopes are
#: still valid no-ops so instrumented call sites cost almost nothing.
SINK_ENV = "RESEARCH_HARNESS_CONTEXT_TELEMETRY"

_local = threading.local()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active() -> dict[str, Any] | None:
    return getattr(_local, "scope", None)


def _default_sink() -> Path | None:
    raw = os.environ.get(SINK_ENV, "").strip()
    return Path(raw) if raw else None


def record_source(
    *,
    kind: str,
    source_id: str,
    offered: int,
    kept: int,
    reason: str = "",
) -> None:
    """Record one context source considered for inclusion.

    ``offered`` is the character length available; ``kept`` is what actually
    reached the prompt. ``kept == 0`` means the source never reached the model
    at all — the case that silently breaks provenance.

    A call outside any active scope is a no-op, so instrumented helpers stay
    safe when called from paths that do not open a scope.
    """
    scope = _active()
    if scope is None:
        return
    try:
        offered_i = max(0, int(offered))
        kept_i = max(0, min(int(kept), offered_i))
        scope["offered"] += offered_i
        scope["kept"] += kept_i
        scope["sources"] += 1
        if kept_i < offered_i:
            if kept_i == 0:
                scope["fully_dropped"] += 1
            scope["drops"].append(
                {
                    "source_kind": str(kind),
                    "source_id": str(source_id),
                    "offered_chars": offered_i,
                    "kept_chars": kept_i,
                    "dropped_chars": offered_i - kept_i,
                    "reason": str(reason) or "unspecified",
                }
            )
    except Exception:  # noqa: BLE001 - telemetry must never break a run
        return


@contextlib.contextmanager
def context_budget_scope(
    *,
    primitive: str,
    stage: str = "",
    topic_id: int | None = None,
    model_window: int | None = None,
    sink_path: str | Path | None = None,
) -> Iterator[None]:
    """Open a measurement scope around one primitive's context assembly.

    The event is emitted even when the body raises, so failed calls are still
    attributable; ``errored`` records which case it was.
    """
    previous = getattr(_local, "scope", None)
    scope: dict[str, Any] = {
        "offered": 0,
        "kept": 0,
        "sources": 0,
        "fully_dropped": 0,
        "drops": [],
    }
    _local.scope = scope
    errored = False
    try:
        yield
    except BaseException:
        errored = True
        raise
    finally:
        _local.scope = previous
        try:
            sink = Path(sink_path) if sink_path is not None else _default_sink()
            if sink is not None:
                offered = scope["offered"]
                kept = scope["kept"]
                event = {
                    "schema": CONTEXT_BUDGET_SCHEMA,
                    "recorded_at": _now(),
                    "primitive": primitive,
                    "stage": stage,
                    "topic_id": topic_id,
                    "model_window": model_window,
                    "offered_chars": offered,
                    "kept_chars": kept,
                    "dropped_chars": offered - kept,
                    "sources_offered": scope["sources"],
                    "sources_fully_dropped": scope["fully_dropped"],
                    "drops": scope["drops"],
                    "errored": errored,
                }
                sink.parent.mkdir(parents=True, exist_ok=True)
                with sink.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - telemetry must never break a run
            pass


def summarize_events(sink_path: str | Path) -> dict[str, Any]:
    """Aggregate a telemetry sink into a per-primitive truncation report."""
    path = Path(sink_path)
    per: dict[str, dict[str, Any]] = {}
    totals = {
        "calls": 0,
        "offered_chars": 0,
        "kept_chars": 0,
        "dropped_chars": 0,
        "sources_offered": 0,
        "sources_fully_dropped": 0,
    }

    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = str(event.get("primitive") or "(unknown)")
            row = per.setdefault(
                name,
                {
                    "primitive": name,
                    "calls": 0,
                    "offered_chars": 0,
                    "kept_chars": 0,
                    "dropped_chars": 0,
                    "sources_offered": 0,
                    "sources_fully_dropped": 0,
                },
            )
            row["calls"] += 1
            totals["calls"] += 1
            for key in (
                "offered_chars",
                "kept_chars",
                "dropped_chars",
                "sources_offered",
                "sources_fully_dropped",
            ):
                value = int(event.get(key) or 0)
                row[key] += value
                totals[key] += value

    for row in per.values():
        offered = row["offered_chars"]
        row["truncation_rate"] = (
            round(row["dropped_chars"] / offered, 4) if offered else 0.0
        )

    offered_total = totals["offered_chars"]
    totals["truncation_rate"] = (
        round(totals["dropped_chars"] / offered_total, 4) if offered_total else 0.0
    )

    return {
        "sink": str(path),
        "totals": totals,
        "per_primitive": sorted(
            per.values(), key=lambda r: r["dropped_chars"], reverse=True
        ),
    }


def telemetry_status() -> dict[str, Any]:
    """Report whether context telemetry is armed, in `rh doctor` shape.

    Telemetry that is off by default and invisible gets discovered to be off
    only after the run it was meant to instrument — and context drops cannot be
    reconstructed after the fact. Surfacing the state before a run is the whole
    value; the check is advisory (`ok` stays True) because non-instrumented runs
    are legitimate.
    """
    sink = _default_sink()
    events = 0
    if sink is not None and sink.exists():
        try:
            events = sum(
                1
                for line in sink.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        except OSError:
            events = 0

    enabled = sink is not None
    return {
        "check": "context_telemetry",
        "enabled": enabled,
        "sink": str(sink) if sink is not None else None,
        "events_recorded": events,
        "ok": True,
        "note": (
            "records what evidence was dropped during context assembly; "
            "drops cannot be reconstructed after a run"
        ),
        "remediation": (
            []
            if enabled
            else [f"set {SINK_ENV}=<path>.jsonl before a run to record context drops"]
        ),
    }
