"""FastAPI route registration for the local Codex LongTask supervisor."""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from research_harness.longtask import (
    CodexExecutor,
    DryRunExecutor,
    LongTaskStore,
    LongTaskSupervisor,
)


class LongTaskGateDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "paused", "replan_requested"]
    actor: str = Field(default="mobile", min_length=1, max_length=80)
    token: str | None = Field(default=None, max_length=512)
    note: str = Field(default="", max_length=2000)


class LongTaskStartRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=20000)
    max_workers: int = Field(default=2, ge=1, le=8)


class LongTaskGateCreateRequest(BaseModel):
    task_id: str | None = Field(default=None, max_length=80)
    gate_type: str = Field(default="continue_next_wave", min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    token: str | None = Field(default=None, max_length=512)


class LongTaskDispatchRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=8)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    execute: bool = False
    cwd: str = Field(default=".", max_length=2000)


class LongTaskSuperviseRequest(BaseModel):
    max_cycles: int = Field(default=10, ge=1, le=100)
    limit_per_cycle: int | None = Field(default=None, ge=1, le=8)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    execute: bool = False
    cwd: str = Field(default=".", max_length=2000)


def _longtask_store(home_provider: Callable[[], Path]) -> LongTaskStore:
    return LongTaskStore(home_provider())


def _longtask_base_url(request: Request) -> str:
    return os.environ.get("RESEARCH_HARNESS_PUBLIC_BASE_URL") or str(
        request.base_url
    ).rstrip("/")


def _longtask_api_executor(execute: bool, cwd: str):
    if not execute:
        return DryRunExecutor()
    if os.environ.get("RESEARCH_HARNESS_LONGTASK_API_EXECUTE") != "1":
        raise HTTPException(
            status_code=403,
            detail="real Codex execution through HTTP is disabled; set RESEARCH_HARNESS_LONGTASK_API_EXECUTE=1",
        )
    return CodexExecutor(Path(cwd).resolve())


def register_longtask_routes(
    app: FastAPI, *, home_provider: Callable[[], Path]
) -> None:
    """Register LongTask endpoints on an existing FastAPI app."""

    def store() -> LongTaskStore:
        return _longtask_store(home_provider)

    @app.get("/api/longtasks/runs")
    def list_longtask_runs(limit: int = Query(default=20, ge=1, le=100)):
        """List recent Codex LongTask supervisor runs."""
        return store().list_runs(limit=limit)

    @app.post("/api/longtasks/runs", status_code=201)
    def create_longtask_run(body: LongTaskStartRequest):
        """Create a new longtask run from a mobile/web client."""
        supervisor = LongTaskSupervisor(store())
        run = supervisor.start_run(
            title=body.title,
            objective_text=body.objective,
            max_workers=body.max_workers,
        )
        return supervisor.store.get_run_detail(run.id)

    @app.get("/api/longtasks/runs/{run_id}")
    def get_longtask_run(run_id: str, request: Request):
        """Return a run, its execution path, attempts, gates, and event log."""
        supervisor = LongTaskSupervisor(store())
        try:
            return supervisor.describe_run(
                run_id,
                base_url=_longtask_base_url(request),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="longtask run not found"
            ) from exc

    @app.post("/api/longtasks/runs/{run_id}/dispatch")
    def dispatch_longtask_run(run_id: str, body: LongTaskDispatchRequest):
        """Dispatch currently ready work; HTTP defaults to safe dry-run execution."""
        supervisor = LongTaskSupervisor(store())
        try:
            supervisor.store.get_run_detail(run_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="longtask run not found"
            ) from exc
        results = supervisor.dispatch_ready(
            run_id,
            executor=_longtask_api_executor(body.execute, body.cwd),
            limit=body.limit,
            timeout_seconds=body.timeout_seconds,
        )
        return {
            "run_id": run_id,
            "dispatched": len(results),
            "results": [result.result for result in results],
        }

    @app.post("/api/longtasks/runs/{run_id}/supervise")
    def supervise_longtask_run(run_id: str, body: LongTaskSuperviseRequest):
        """Run dry-run supervision cycles until complete, gated, or blocked."""
        supervisor = LongTaskSupervisor(store())
        try:
            supervisor.store.get_run_detail(run_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="longtask run not found"
            ) from exc
        return supervisor.supervise(
            run_id,
            executor=_longtask_api_executor(body.execute, body.cwd),
            max_cycles=body.max_cycles,
            limit_per_cycle=body.limit_per_cycle,
            timeout_seconds=body.timeout_seconds,
        )

    @app.post("/api/longtasks/runs/{run_id}/gates", status_code=201)
    def create_longtask_gate(
        run_id: str, body: LongTaskGateCreateRequest, request: Request
    ):
        """Create a pending mobile/human approval gate for a run."""
        longtask_store = store()
        try:
            longtask_store.get_run_detail(run_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="longtask run not found"
            ) from exc
        supervisor = LongTaskSupervisor(longtask_store)
        gate = supervisor.create_gate(
            run_id=run_id,
            task_id=body.task_id,
            gate_type=body.gate_type,
            title=body.title,
            token=body.token,
        )
        return {
            **gate.__dict__,
            "notification": supervisor.gate_notification_payload(
                gate.id,
                base_url=_longtask_base_url(request),
            ),
        }

    @app.post("/api/longtasks/gates/{gate_id}/decision")
    def decide_longtask_gate(gate_id: str, body: LongTaskGateDecisionRequest):
        """Record a mobile approval/rejection/pause/replan decision for a gate."""
        supervisor = LongTaskSupervisor(store())
        decision = supervisor.decide_gate(
            gate_id,
            decision=body.decision,
            actor=body.actor,
            token=body.token,
            note=body.note,
        )
        if not decision.accepted:
            raise HTTPException(status_code=403, detail=decision.message)
        return decision.__dict__

    @app.get("/api/longtasks/gates/{gate_id}/action")
    def confirm_longtask_gate_signed_action(
        request: Request,
        gate_id: str,
        decision: Literal["approved", "rejected", "paused", "replan_requested"],
        expires_at: int = Query(ge=0),
        signature: str = Query(min_length=32, max_length=256),
        view: bool = Query(default=False),
    ):
        """Confirm a signed mobile/chat action URL without mutating state."""
        supervisor = LongTaskSupervisor(store())
        result = supervisor.validate_gate_signature(
            gate_id,
            decision=decision,
            expires_at=expires_at,
            signature=signature,
        )
        if not result.accepted:
            status_code = 409 if result.message == "gate is not pending" else 403
            if view:
                return HTMLResponse(
                    _signed_gate_action_html(
                        gate_id=gate_id,
                        run_id="",
                        title="",
                        decision=decision,
                        error=result.message,
                        action_url=str(request.url),
                    ),
                    status_code=status_code,
                )
            raise HTTPException(status_code=status_code, detail=result.message)
        gate = supervisor.store.get_gate(gate_id)
        if view:
            return HTMLResponse(
                _signed_gate_action_html(
                    gate_id=gate_id,
                    run_id=str(gate["run_id"]),
                    title=str(gate["title"]),
                    decision=decision,
                    action_url=str(request.url),
                )
            )
        return {
            "gate_id": gate_id,
            "decision": decision,
            "title": gate["title"],
            "status": gate["status"],
            "expires_at": expires_at,
            "requires_post": True,
        }

    @app.post("/api/longtasks/gates/{gate_id}/action")
    def decide_longtask_gate_signed_action(
        gate_id: str,
        decision: Literal["approved", "rejected", "paused", "replan_requested"],
        expires_at: int = Query(ge=0),
        signature: str = Query(min_length=32, max_length=256),
    ):
        """Consume a signed mobile/chat action URL after explicit confirmation."""
        supervisor = LongTaskSupervisor(store())
        result = supervisor.decide_gate_with_signature(
            gate_id,
            decision=decision,
            expires_at=expires_at,
            signature=signature,
            actor="signed-link",
        )
        if not result.accepted:
            status_code = 409 if result.message == "gate is not pending" else 403
            raise HTTPException(status_code=status_code, detail=result.message)
        return result.__dict__


def _signed_gate_action_html(
    *,
    gate_id: str,
    run_id: str,
    title: str,
    decision: str,
    action_url: str,
    error: str | None = None,
) -> str:
    safe_title = html.escape(title or gate_id)
    safe_run_id = html.escape(run_id)
    safe_decision = html.escape(decision)
    safe_action = html.escape(action_url)
    note = f'<p class="state">{html.escape(error or "")}</p>' if error else ""
    return f"""
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Codex LongTask Gate</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }}
    .card {{ margin: 0 auto; max-width: 30rem; padding: 1rem; border: 1px solid #334155; background: #1e293b; border-radius: 14px; margin-top: 2.5rem; }}
    h1 {{ margin: 0 0 .75rem 0; font-size: 1.1rem; }}
    p {{ margin: .35rem 0; color: #cbd5e1; font-size: .95rem; }}
    .state {{ color: #fda4af; }}
    button {{ margin-top: .75rem; width: 100%; border: none; border-radius: .6rem; padding: .7rem 1rem; background: #4f46e5; color: white; font-size: 1rem; }}
    #result {{ margin-top: .75rem; display: none; padding: .7rem; background: #0b1220; border: 1px solid #334155; border-radius: .6rem; white-space: pre-wrap; }}
  </style>
  <script>
    async function confirmAction() {{
      const response = await fetch(window.location.pathname + window.location.search, {{
        method: 'POST',
      }});
      const text = await response.text();
      const result = document.getElementById('result');
      result.style.display = 'block';
      result.textContent = text;
      if (!response.ok) {{
        result.style.color = '#fca5a5';
      }} else {{
        result.style.color = '#86efac';
      }}
    }}
  </script>
</head>
<body>
  <main class="card">
    <h1>{safe_title}</h1>
    <p><strong>Run:</strong> {safe_run_id}</p>
    <p><strong>Decision:</strong> {safe_decision}</p>
    <p>Mobile confirmation for signed LongTask gate link.</p>
    {note}
    <p class="state">Action endpoint: <code>{safe_action}</code></p>
    <button type="button" onclick="confirmAction()">Confirm this decision</button>
    <pre id="result"></pre>
  </main>
</body>
</html>
"""
