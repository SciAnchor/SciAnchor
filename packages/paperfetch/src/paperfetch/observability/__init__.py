"""SPC 统一结构化事件与输出接口。"""

from paperfetch.observability.events import (
    EVENT_OUTCOMES,
    SPCEventLogger,
    SPCLogEvent,
    bind_event_context,
    bind_output_capture,
    canonical_publisher_key,
    configure_observability,
    current_business_status,
    current_run_id,
    emit_event,
    events_snapshot,
    get_event_logger,
    observability_status,
    reset_event_state,
    write_output,
    public_result_projection,
)

__all__ = [
    "EVENT_OUTCOMES",
    "SPCEventLogger",
    "SPCLogEvent",
    "bind_event_context",
    "bind_output_capture",
    "canonical_publisher_key",
    "configure_observability",
    "current_business_status",
    "current_run_id",
    "emit_event",
    "events_snapshot",
    "get_event_logger",
    "observability_status",
    "reset_event_state",
    "write_output",
    "public_result_projection",
]
