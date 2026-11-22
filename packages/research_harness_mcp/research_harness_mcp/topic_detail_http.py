"""FastAPI route registration for topic detail reads."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def _topic_detail_service_topic(
    invoke_service: Callable[[str, dict[str, Any]], Any],
    topic_name: str,
) -> dict[str, Any]:
    result = invoke_service("topic_show", {"name": topic_name})
    if result.status != "success":
        message = result.error["message"] if result.error else result.summary
        raise HTTPException(status_code=500, detail=message)

    output = result.output if isinstance(result.output, dict) else {}
    if not output or output.get("error"):
        raise HTTPException(
            status_code=500,
            detail=str(
                output.get("error")
                or "ResearchService topic_show returned an invalid payload"
            ),
        )
    return output


def _topic_detail_service_orchestrator_status(
    invoke_service: Callable[[str, dict[str, Any]], Any],
    topic_id: int,
) -> dict[str, Any]:
    result = invoke_service("orchestrator_status", {"topic_id": topic_id})
    output = result.output if isinstance(result.output, dict) else {}
    if result.status != "success":
        if output.get("error") == "No orchestrator run found for this topic":
            return {}
        message = result.error["message"] if result.error else result.summary
        raise HTTPException(status_code=500, detail=message)
    if output.get("error"):
        return {}
    run = output.get("run")
    if run is not None and not isinstance(run, dict):
        raise HTTPException(
            status_code=500,
            detail="ResearchService orchestrator_status returned an invalid payload",
        )
    return output


def register_topic_detail_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    invoke_service: Callable[[str, dict[str, Any]], Any],
    topic_detail_model: type[Any],
) -> None:
    """Register topic detail route with injected runtime dependencies."""

    @app.get("/api/topics/{topic_id}", response_model=topic_detail_model)
    def get_topic(topic_id: int):
        with get_db_context() as conn:
            row = conn.execute(
                """
                SELECT t.*, d.name AS domain_name
                FROM topics t
                LEFT JOIN domains d ON d.id = t.domain_id
                WHERE t.id = ?
                """,
                (topic_id,),
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

            service_topic = _topic_detail_service_topic(invoke_service, row["name"])
            service_orch = _topic_detail_service_orchestrator_status(
                invoke_service,
                topic_id,
            )
            service_run = (
                service_orch.get("run") if isinstance(service_orch, dict) else None
            )
            if not isinstance(service_run, dict):
                service_run = {}

            paper_count = conn.execute(
                "SELECT COUNT(*) AS c FROM paper_topics WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()["c"]

            annotation_count = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM paper_annotations pa
                JOIN paper_topics pt ON pt.paper_id = pa.paper_id
                WHERE pt.topic_id = ?
                """,
                (topic_id,),
            ).fetchone()["c"]

            orch = conn.execute(
                """
                SELECT current_stage, stage_status, gate_status, mode, stop_before,
                       blocking_issue_count, unresolved_issue_count
                FROM orchestrator_runs
                WHERE topic_id = ?
                """,
                (topic_id,),
            ).fetchone()

            stage_rows = conn.execute(
                """
                SELECT pa.stage, COUNT(*) AS cnt
                FROM project_artifacts pa
                WHERE pa.topic_id = ?
                GROUP BY pa.stage
                """,
                (topic_id,),
            ).fetchall()
            artifact_counts = {r["stage"]: r["cnt"] for r in stage_rows}

        return topic_detail_model(
            id=row["id"],
            name=service_topic.get("name") or row["name"],
            description=service_topic.get("description") or row["description"] or "",
            status=service_topic.get("status") or row["status"] or "active",
            target_venue=row["target_venue"] or "",
            deadline=row["deadline"] or "",
            created_at=row["created_at"] or "",
            paper_count=paper_count,
            annotation_count=annotation_count,
            domain_id=row["domain_id"],
            domain_name=row["domain_name"],
            current_stage=service_run.get("current_stage")
            or (orch["current_stage"] if orch else None),
            stage_status=service_run.get("stage_status")
            or (orch["stage_status"] if orch else None),
            gate_status=orch["gate_status"] if orch else None,
            contributions=row["contributions"] or "",
            mode=service_run.get("mode") or (orch["mode"] if orch else None),
            stop_before=orch["stop_before"] if orch else None,
            blocking_issue_count=(
                service_run.get("blocking_issue_count")
                if service_run
                else (orch["blocking_issue_count"] if orch else 0)
            ),
            unresolved_issue_count=(
                service_run.get("unresolved_issue_count")
                if service_run
                else (orch["unresolved_issue_count"] if orch else 0)
            ),
            artifact_counts=artifact_counts,
        )
