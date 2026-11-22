"""FastAPI route registration for cross-topic atlas reads."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, Query, Request

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


def register_cross_topic_atlas_routes(
    app: FastAPI,
    *,
    invoke_service: Callable[[str, dict[str, Any]], Any],
) -> None:
    """Register cross-topic atlas route with injected runtime dependencies."""

    @app.get("/api/topics/cross-topic-atlas")
    def get_cross_topic_atlas(
        request: Request,
        topic_id: list[str] | None = Query(
            None, description="Repeat for each topic id"
        ),
        query: str = Query("", max_length=200),
        max_results: str = Query("10"),
    ):
        selected_max_results = _knowledge_http._parse_cross_topic_max_results(
            max_results
        )
        if selected_max_results is None:
            return _knowledge_api_error(
                status_code=400,
                code="invalid_max_results",
                message="max_results must be between 1 and 20",
                request=request,
            )
        topic_ids: list[int] = []
        for raw_topic_id in topic_id or []:
            parsed_topic_id = _knowledge_http._parse_positive_topic_id(raw_topic_id)
            if parsed_topic_id is None:
                return _knowledge_api_error(
                    status_code=400,
                    code="invalid_topic_id",
                    message="topic_id must be a positive integer",
                    request=request,
                )
            topic_ids.append(parsed_topic_id)
        selected_topic_ids = tuple(dict.fromkeys(topic_ids))
        if len(selected_topic_ids) < 2:
            return _knowledge_api_error(
                status_code=400,
                code="invalid_topic_ids",
                message="at least two distinct topic ids are required",
                request=request,
            )
        result = invoke_service(
            "cross_topic_atlas",
            {
                "topic_ids": list(selected_topic_ids),
                "query": query.strip(),
                "max_results": selected_max_results,
            },
        )
        if result.status == "success" and isinstance(result.output, dict):
            return result.output

        error = result.error or {}
        code = str(error.get("code") or "cross_topic_atlas_unavailable")
        message = str(
            error.get("message") or result.summary or "cross-topic atlas failed"
        )
        status_code = 404 if code == "cross_topic_atlas_unavailable" else 500
        if code == "INVALID_ARGUMENT":
            status_code = 400
        return _knowledge_api_error(
            status_code=status_code,
            code=code,
            message=message,
            request=request,
        )
