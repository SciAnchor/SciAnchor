"""FastAPI route registration for topic create and update."""

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_topic_write_routes(
    app: FastAPI,
    *,
    create_topic_request_model: type[Any],
    patch_topic_request_model: type[Any],
    get_db_context: Callable[[], Any],
    materialize_topic_workspace: Callable[..., str | None],
    run_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
    row_to_dict: Callable[[Any], dict[str, Any]],
    now_iso: Callable[[], str],
) -> None:
    """Register topic create/update routes with injected runtime dependencies."""

    @app.post("/api/topics")
    def create_topic(body: create_topic_request_model):
        """Create a new research topic and bootstrap its orchestrator run."""
        now = now_iso()
        domain_name: str | None = None
        with get_db_context() as conn:
            if body.domain_id is not None:
                domain = conn.execute(
                    "SELECT id, name FROM domains WHERE id = ?", (body.domain_id,)
                ).fetchone()
                if not domain:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Domain {body.domain_id} not found",
                    )
                domain_name = str(domain["name"])

            cur = conn.execute(
                """
                INSERT INTO topics (name, description, status, target_venue, deadline,
                                    domain_id, created_at)
                VALUES (?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    body.name,
                    body.description,
                    body.target_venue,
                    body.deadline,
                    body.domain_id,
                    now,
                ),
            )
            conn.commit()
            topic_id = cur.lastrowid

        workspace_path = materialize_topic_workspace(
            topic_id=int(topic_id),
            topic_name=body.name,
            description=body.description,
            target_venue=body.target_venue,
            deadline=body.deadline,
            domain_name=domain_name,
        )

        orch_result = run_tool("orchestrator_resume", {"topic_id": topic_id})

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

        result = row_to_dict(row)
        result["orchestrator"] = orch_result
        result["workspace_path"] = workspace_path
        return result

    @app.patch("/api/topics/{topic_id}")
    def update_topic(topic_id: int, body: patch_topic_request_model):
        """Partial update. Only fields explicitly present in the body are changed."""
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            raise HTTPException(status_code=400, detail="No fields to update")

        allowed = {
            "name",
            "description",
            "domain_id",
            "target_venue",
            "deadline",
            "status",
        }
        updates = {key: value for key, value in patch.items() if key in allowed}
        if not updates:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        with get_db_context() as conn:
            existing = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

            if "domain_id" in updates and updates["domain_id"] is not None:
                dom = conn.execute(
                    "SELECT id FROM domains WHERE id = ?", (updates["domain_id"],)
                ).fetchone()
                if not dom:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Domain {updates['domain_id']} not found",
                    )

            set_clause = ", ".join(f"{key} = ?" for key in updates)
            params = list(updates.values()) + [topic_id]
            conn.execute(f"UPDATE topics SET {set_clause} WHERE id = ?", params)
            conn.commit()

            row = conn.execute(
                """
                SELECT t.*, d.name AS domain_name,
                       (SELECT COUNT(*) FROM paper_topics pt WHERE pt.topic_id = t.id)
                           AS paper_count
                FROM topics t
                LEFT JOIN domains d ON d.id = t.domain_id
                WHERE t.id = ?
                """,
                (topic_id,),
            ).fetchone()
        return row_to_dict(row)
