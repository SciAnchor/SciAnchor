"""FastAPI route registration for topic artifact recording."""

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def _resolved_artifact_stage(
    *,
    topic_id: int,
    explicit_stage: str | None,
    run_tool: Callable[[str, dict[str, Any]], Any],
) -> str:
    if explicit_stage:
        return explicit_stage

    status = run_tool("orchestrator_status", {"topic_id": topic_id})
    candidates = [
        status.get("output", {}).get("run", {}).get("current_stage")
        if isinstance(status, dict)
        else None,
        status.get("run", {}).get("current_stage")
        if isinstance(status, dict)
        else None,
        status.get("current_stage") if isinstance(status, dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    raise HTTPException(
        status_code=400,
        detail="stage is required when orchestrator status cannot resolve it",
    )


def register_topic_artifact_record_routes(
    app: FastAPI,
    *,
    record_artifact_request_model: type[Any],
    run_tool: Callable[[str, dict[str, Any]], Any],
) -> None:
    """Register topic artifact record route with injected runtime dependencies."""

    @app.post("/api/topics/{topic_id}/artifacts")
    def record_artifact(topic_id: int, body: record_artifact_request_model):
        """Record an artifact for the topic's current (or specified) stage."""
        stage = _resolved_artifact_stage(
            topic_id=topic_id,
            explicit_stage=body.stage,
            run_tool=run_tool,
        )
        arguments = {
            "topic_id": topic_id,
            "stage": stage,
            "artifact_type": body.artifact_type,
            "payload": body.payload,
        }
        if body.title:
            arguments["title"] = body.title
        return run_tool(
            "orchestrator_record_artifact",
            arguments,
        )
