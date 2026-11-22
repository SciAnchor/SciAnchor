"""FastAPI route registration for topic knowledge-status reads."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, Request

from research_harness_mcp import knowledge_http as _knowledge_http


def _knowledge_api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    request: Request | None = None,
):
    return _knowledge_http._knowledge_api_error_response(
        status_code=status_code,
        code=code,
        message=message,
        request=request,
    )


def register_topic_knowledge_status_routes(
    app: FastAPI,
    *,
    invoke_service: Callable[[str, dict[str, Any]], Any],
) -> None:
    """Register topic knowledge-status route with injected runtime dependencies."""

    @app.get("/api/topics/{topic_id}/knowledge-status")
    def get_topic_knowledge_status(request: Request, topic_id: str):
        selected_topic_id = _knowledge_http._parse_positive_topic_id(topic_id)
        if selected_topic_id is None:
            return _knowledge_api_error(
                status_code=400,
                code="invalid_topic_id",
                message="topic_id must be a positive integer",
                request=request,
            )
        result = invoke_service(
            "topic_knowledge_status",
            {"topic_id": selected_topic_id},
        )
        if result.status == "success" and isinstance(result.output, dict):
            return result.output

        error = result.error or {}
        code = str(error.get("code") or "knowledge_status_unavailable")
        message = str(
            error.get("message")
            or result.summary
            or f"knowledge status is unavailable for topic {selected_topic_id}"
        )
        status_code = 404 if code == "knowledge_status_unavailable" else 500
        return _knowledge_api_error(
            status_code=status_code,
            code=code,
            message=message,
            request=request,
        )
