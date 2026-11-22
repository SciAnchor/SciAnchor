"""Service-result contract for tracked primitive execution."""

from __future__ import annotations

from typing import Any

from research_harness.execution.harness_actions import (
    classify_error,
    compute_next_actions,
    compute_summary,
    extract_artifacts,
)
from research_harness.primitives.types import PrimitiveResult

from .types import ServiceResult


def primitive_result_to_service_result(
    result: PrimitiveResult,
    orch_state: dict[str, Any] | None = None,
) -> ServiceResult:
    """Convert a TrackedBackend PrimitiveResult into a transport-neutral result."""

    status = "success" if result.success else "error"
    error = None
    recovery_hint = ""
    if not result.success:
        message = result.error or f"{result.primitive} failed"
        error = {"code": "PRIMITIVE_FAILED", "message": message}
        recovery_hint = classify_error(message)

    return ServiceResult(
        command=result.primitive,
        status=status,
        summary=compute_summary(result.primitive, result),
        output=result.output,
        error=error,
        next_actions=tuple(compute_next_actions(result.primitive, result, orch_state)),
        artifacts=tuple(extract_artifacts(result)),
        recovery_hint=recovery_hint,
        metadata=_tracked_primitive_metadata(result),
    )


def _tracked_primitive_metadata(result: PrimitiveResult) -> dict[str, Any]:
    return {
        "primitive": result.primitive,
        "backend": result.backend,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "duration_seconds": result.duration_seconds,
        "provenance_recorded_by": "TrackedBackend",
    }
