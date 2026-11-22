"""FastAPI route registration for domain create/update writes."""

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_domain_write_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    domain_summary_model: type[Any],
    create_domain_request_model: type[Any],
    patch_domain_request_model: type[Any],
    now_factory: Callable[[], datetime] | None = None,
) -> None:
    """Register domain write routes with injected runtime dependencies."""

    clock = now_factory or (lambda: datetime.now(timezone.utc))

    @app.post("/api/domains", response_model=domain_summary_model)
    def create_domain(body: create_domain_request_model):
        now = clock().isoformat()
        with get_db_context() as conn:
            cur = conn.execute(
                """
                INSERT INTO domains (name, description, status, created_at)
                VALUES (?, ?, 'active', ?)
                """,
                (body.name, body.description, now),
            )
            conn.commit()
            domain_id = cur.lastrowid
        return domain_summary_model(
            id=domain_id,
            name=body.name,
            description=body.description,
            status="active",
            topic_count=0,
            created_at=now,
        )

    @app.patch("/api/domains/{domain_id}", response_model=domain_summary_model)
    def update_domain(domain_id: int, body: patch_domain_request_model):
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            raise HTTPException(status_code=400, detail="No fields to update")

        allowed = {"name", "description", "status"}
        updates = {k: v for k, v in patch.items() if k in allowed}
        if not updates:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [domain_id]

        with get_db_context() as conn:
            existing = conn.execute(
                "SELECT id FROM domains WHERE id = ?", (domain_id,)
            ).fetchone()
            if not existing:
                raise HTTPException(
                    status_code=404, detail=f"Domain {domain_id} not found"
                )
            conn.execute(f"UPDATE domains SET {set_clause} WHERE id = ?", params)
            conn.commit()

            row = conn.execute(
                """
                SELECT d.*, COUNT(t.id) AS topic_count
                FROM domains d
                LEFT JOIN topics t ON t.domain_id = d.id
                WHERE d.id = ?
                GROUP BY d.id
                """,
                (domain_id,),
            ).fetchone()
        return domain_summary_model(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            status=row["status"] or "active",
            topic_count=row["topic_count"] or 0,
            created_at=row["created_at"] or "",
        )
