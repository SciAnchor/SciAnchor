"""FastAPI route registration for topic paper listing."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query


def register_topic_paper_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
    paginated_response_model: type[Any],
    pagination_meta_model: type[Any],
) -> None:
    """Register topic-scoped paper listing route."""

    @app.get("/api/topics/{topic_id}/papers", response_model=paginated_response_model)
    def list_topic_papers(
        topic_id: int,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=1, le=200),
        search: str = Query("", description="Search in title/authors/venue"),
        sort: str = Query(
            "created_at",
            description="Sort field: created_at, year, title, citation_count",
        ),
        order: str = Query("desc", description="asc or desc"),
    ):
        with get_db_context() as conn:
            topic = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if not topic:
                raise HTTPException(
                    status_code=404, detail=f"Topic {topic_id} not found"
                )

            allowed_sort = {"created_at", "year", "title", "citation_count", "venue"}
            sort_col = sort if sort in allowed_sort else "created_at"
            sort_dir = "ASC" if order.lower() == "asc" else "DESC"

            base_where = "pt.topic_id = ?"
            params: list[Any] = [topic_id]

            if search:
                base_where += (
                    " AND (p.title LIKE ? OR p.authors LIKE ? OR p.venue LIKE ?)"
                )
                like = f"%{search}%"
                params.extend([like, like, like])

            count_sql = (
                "SELECT COUNT(*) AS c FROM papers p "
                "JOIN paper_topics pt ON pt.paper_id = p.id "
                f"WHERE {base_where}"
            )
            total = conn.execute(count_sql, params).fetchone()["c"]

            offset = (page - 1) * per_page
            data_sql = f"""
                SELECT p.*, pt.relevance
                FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE {base_where}
                ORDER BY p.{sort_col} {sort_dir}
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(data_sql, [*params, per_page, offset]).fetchall()

        papers = []
        for row in rows:
            paper = row_to_dict(row)
            paper["authors"] = parse_json_field(paper.get("authors"), [])
            papers.append(paper)

        total_pages = max(1, (total + per_page - 1) // per_page)
        return paginated_response_model(
            data=papers,
            pagination=pagination_meta_model(
                page=page,
                per_page=per_page,
                total=total,
                total_pages=total_pages,
            ),
        )
