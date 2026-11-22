"""FastAPI route registration for topic knowledge refresh operations."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def register_topic_knowledge_refresh_routes(
    app: FastAPI,
    *,
    invoke_service: Callable[[str, dict[str, Any]], Any],
    parse_positive_topic_id: Callable[[str], int | None],
    knowledge_api_error: Callable[..., JSONResponse],
    cache_control: str,
) -> None:
    """Register topic knowledge refresh routes with injected dependencies."""

    @app.post("/api/topics/knowledge-refresh-all")
    def post_topic_knowledge_refresh_all(request: Request):
        result = invoke_service("topic_knowledge_refresh", {"all": True})
        return _service_refresh_response(
            result,
            request=request,
            knowledge_api_error=knowledge_api_error,
            cache_control=cache_control,
        )

    @app.post("/api/topics/{topic_id}/knowledge-refresh")
    def post_topic_knowledge_refresh(request: Request, topic_id: str):
        selected_topic_id = parse_positive_topic_id(topic_id)
        if selected_topic_id is None:
            return knowledge_api_error(
                status_code=400,
                code="invalid_topic_id",
                message="topic_id must be a positive integer",
                request=request,
            )

        result = invoke_service(
            "topic_knowledge_refresh",
            {"topic_id": selected_topic_id},
        )
        return _service_refresh_response(
            result,
            request=request,
            knowledge_api_error=knowledge_api_error,
            cache_control=cache_control,
        )


def _service_refresh_response(
    result: Any,
    *,
    request: Request,
    knowledge_api_error: Callable[..., JSONResponse],
    cache_control: str,
) -> JSONResponse:
    if result.status == "success" and isinstance(result.output, dict):
        return JSONResponse(
            content=result.output,
            headers={"Cache-Control": cache_control},
        )

    error = result.error or {}
    code = str(error.get("code") or "topic_knowledge_refresh_failed")
    message = str(error.get("message") or result.summary or "topic knowledge failed")
    status_code = 500
    if code == "topic_not_found":
        status_code = 404
    elif code == "INVALID_ARGUMENT":
        status_code = 400
    return knowledge_api_error(
        status_code=status_code,
        code=code,
        message=message,
        request=request,
    )
