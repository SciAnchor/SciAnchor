"""MCP primitive tool helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import asdict
from typing import Any

from mcp.types import Tool

from research_harness.primitives.registry import list_primitives
from research_harness.primitives.types import PrimitiveResult
from research_harness.storage.db import Database

logger = logging.getLogger(__name__)


def _primitive_tool_definitions(
    *,
    primitive_lister: Callable[[], Iterable[Any]] = list_primitives,
) -> list[Tool]:
    """Convert registered PrimitiveSpecs into MCP Tool definitions."""
    tools = []
    for spec in primitive_lister():
        tools.append(
            Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.input_schema,
            )
        )
    return tools


def _record_iterative_retrieval_artifact(
    db: Database,
    arguments: dict[str, Any],
    result: PrimitiveResult,
    *,
    orchestrator_service_factory: Callable[[Database], Any] | None = None,
) -> None:
    """Persist an iterative_retrieval_loop result as an orchestrator artifact."""
    topic_id = arguments.get("topic_id")
    if topic_id is None:
        return
    try:
        output = result.output
        if output is None:
            return
        payload = (
            asdict(output) if hasattr(output, "__dataclass_fields__") else dict(output)
        )

        if orchestrator_service_factory is None:
            from research_harness.orchestrator import OrchestratorService

            orchestrator_service_factory = OrchestratorService

        svc = orchestrator_service_factory(db)
        svc.record_artifact(
            topic_id=int(topic_id),
            stage="build",
            artifact_type="iterative_retrieval_loop_result",
            title=(
                f"Retrieval loop: {payload.get('rounds_run', 0)} rounds, "
                f"+{payload.get('total_new_papers', 0)} papers, "
                f"converged={payload.get('convergence_reached', False)}"
            ),
            payload=payload,
        )
    except Exception:  # pragma: no cover - best-effort bookkeeping
        pass


def _execute_primitive(
    name: str,
    arguments: dict[str, Any],
    *,
    db_resolver: Callable[[], Database],
    backend_factory: Callable[[Database], Any],
    result_serializer: Callable[..., dict[str, Any]],
    orch_state_provider: Callable[[Database, int | None], dict[str, Any] | None],
    session_advisory_provider: Callable[
        [Database, str, dict[str, Any], dict[str, Any] | None], str
    ],
    nudge_provider: Callable[[Database, str, dict[str, Any], PrimitiveResult], str],
    iterative_artifact_recorder: Callable[
        [Database, dict[str, Any], PrimitiveResult], None
    ] = _record_iterative_retrieval_artifact,
    logger_obj: logging.Logger = logger,
) -> dict[str, Any]:
    """Execute a research primitive and return serializable result."""
    db = db_resolver()
    backend = backend_factory(db)
    result: PrimitiveResult = backend.execute(name, **arguments)

    # Post-execution hooks
    if name == "iterative_retrieval_loop" and result.success:
        iterative_artifact_recorder(db, arguments, result)

    if name == "paper_search" and result.success:
        topic_id = arguments.get("topic_id")
        if topic_id:
            conn = db.connect()
            try:
                conn.execute(
                    "UPDATE topics SET last_search_at = datetime('now') WHERE id = ?",
                    (topic_id,),
                )
                query_text = arguments.get("query", "")
                if query_text:
                    conn.execute(
                        """INSERT INTO search_query_registry (topic_id, query, source, last_searched_at)
                           VALUES (?, ?, 'auto_generated', datetime('now'))
                           ON CONFLICT(topic_id, query) DO UPDATE SET last_searched_at = datetime('now')""",
                        (topic_id, query_text),
                    )
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

    # Auto-extract writing patterns after successful deep_read
    if name == "deep_read" and result.success:
        paper_id = arguments.get("paper_id")
        if paper_id:
            try:
                backend.execute("writing_pattern_extract", paper_id=int(paper_id))
                logger_obj.info(
                    "Auto-extracted writing patterns for paper %s", paper_id
                )
            except Exception as exc:
                logger_obj.debug(
                    "Writing pattern extract skipped for paper %s: %s", paper_id, exc
                )

    orch_state = orch_state_provider(db, arguments.get("topic_id"))
    session_advisory = session_advisory_provider(db, name, arguments, orch_state)
    nudge_text = nudge_provider(db, name, arguments, result)
    return result_serializer(
        result, orch_state, session_advisory=session_advisory, nudge=nudge_text
    )
