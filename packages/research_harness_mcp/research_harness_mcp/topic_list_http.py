"""FastAPI route registration for topic listing."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query


def _topic_list_service_topics(
    invoke_service: Callable[[str, dict[str, Any]], Any],
) -> list[dict[str, Any]]:
    result = invoke_service("topic_list", {})
    if result.status != "success":
        message = result.error["message"] if result.error else result.summary
        raise HTTPException(status_code=500, detail=message)

    output = result.output if isinstance(result.output, dict) else {}
    topics = output.get("topics")
    if not isinstance(topics, list):
        raise HTTPException(
            status_code=500,
            detail="ResearchService topic_list returned an invalid payload",
        )
    return [topic for topic in topics if isinstance(topic, dict)]


def _topic_summaries_from_service(
    *,
    domain_id: int | None,
    invoke_service: Callable[[str, dict[str, Any]], Any],
    get_db_context: Callable[[], Any],
    topic_summary_model: type[Any],
) -> list[Any]:
    service_topics = _topic_list_service_topics(invoke_service)
    topic_ids: list[int] = []
    for topic in service_topics:
        try:
            topic_ids.append(int(topic["id"]))
        except (KeyError, TypeError, ValueError):
            continue

    if not topic_ids:
        return []

    placeholders = ", ".join("?" for _ in topic_ids)
    conditions = [f"t.id IN ({placeholders})"]
    params: list[Any] = list(topic_ids)
    if domain_id is not None:
        conditions.append("t.domain_id = ?")
        params.append(domain_id)

    with get_db_context() as conn:
        rows = conn.execute(
            f"""
            SELECT t.*,
                   d.name AS domain_name,
                   COUNT(pt.paper_id) AS paper_count,
                   o.current_stage AS orch_current_stage,
                   o.stage_status AS orch_stage_status
            FROM topics t
            LEFT JOIN domains d ON d.id = t.domain_id
            LEFT JOIN paper_topics pt ON pt.topic_id = t.id
            LEFT JOIN orchestrator_runs o ON o.topic_id = t.id
            WHERE {" AND ".join(conditions)}
            GROUP BY t.id
            ORDER BY t.id
            """,
            params,
        ).fetchall()

    rows_by_id = {int(row["id"]): row for row in rows}
    summaries: list[Any] = []
    for topic in service_topics:
        try:
            topic_id = int(topic["id"])
        except (KeyError, TypeError, ValueError):
            continue
        row = rows_by_id.get(topic_id)
        if row is None:
            continue
        summaries.append(
            topic_summary_model(
                id=topic_id,
                name=topic.get("name") or row["name"],
                description=topic.get("description") or row["description"] or "",
                status=topic.get("status") or row["status"] or "active",
                target_venue=row["target_venue"] or "",
                deadline=row["deadline"] or "",
                created_at=row["created_at"] or "",
                paper_count=row["paper_count"] or 0,
                domain_id=row["domain_id"],
                domain_name=row["domain_name"],
                current_stage=row["orch_current_stage"],
                stage_status=row["orch_stage_status"],
            )
        )
    return summaries


def register_topic_list_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    invoke_service: Callable[[str, dict[str, Any]], Any],
    topic_summary_model: type[Any],
) -> None:
    """Register topic listing route with injected runtime dependencies."""

    @app.get("/api/topics", response_model=list[topic_summary_model])
    def list_topics(
        domain_id: int | None = Query(None, description="Filter by domain"),
    ):
        return _topic_summaries_from_service(
            domain_id=domain_id,
            invoke_service=invoke_service,
            get_db_context=get_db_context,
            topic_summary_model=topic_summary_model,
        )
