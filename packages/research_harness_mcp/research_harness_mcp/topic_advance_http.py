"""FastAPI route registration for topic orchestrator advance."""

from typing import Any, Callable

from fastapi import FastAPI


def register_topic_advance_routes(
    app: FastAPI,
    *,
    advance_request_model: type[Any],
    run_tool: Callable[[str, dict[str, Any]], Any],
) -> None:
    """Register topic advance route with injected runtime dependencies."""

    @app.post("/api/topics/{topic_id}/advance")
    def advance_topic(topic_id: int, body: advance_request_model):
        """Advance the topic to the next orchestrator stage."""
        return run_tool(
            "orchestrator_advance", {"topic_id": topic_id, "actor": body.actor}
        )
