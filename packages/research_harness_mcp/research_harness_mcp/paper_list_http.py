"""FastAPI route registration for paper listing."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query


def _paper_list_service_ids(
    invoke_service: Callable[[str, dict[str, Any]], Any],
    topic_name: str | None,
) -> list[int]:
    arguments = {"topic": topic_name} if topic_name else {}
    result = invoke_service("paper_list", arguments)
    if result.status != "success":
        message = result.error["message"] if result.error else result.summary
        raise HTTPException(status_code=500, detail=message)

    output = result.output if isinstance(result.output, dict) else {}
    papers = output.get("papers")
    if not isinstance(papers, list):
        raise HTTPException(
            status_code=500,
            detail="ResearchService paper_list returned an invalid payload",
        )

    paper_ids: list[int] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        try:
            paper_ids.append(int(paper["id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return paper_ids


def _append_paper_id_filter(
    conditions: list[str],
    params: list[Any],
    paper_ids: list[int],
) -> None:
    if not paper_ids:
        conditions.append("1 = 0")
        return
    placeholders = ", ".join("?" for _ in paper_ids)
    conditions.append(f"p.id IN ({placeholders})")
    params.extend(paper_ids)


def register_paper_list_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    invoke_service: Callable[[str, dict[str, Any]], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    parse_json_field: Callable[[str | None, Any], Any],
    paginated_response_model: type[Any],
    pagination_meta_model: type[Any],
) -> None:
    """Register paper listing route with injected runtime dependencies."""

    @app.get("/api/papers", response_model=paginated_response_model)
    def list_papers(
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=1, le=200),
        search: str = Query("", description="Search in title/authors/venue"),
        topic_id: int | None = Query(None, description="Filter by topic"),
        domain_id: int | None = Query(None, description="Filter by domain (any topic)"),
        status: str | None = Query(None, description="Filter by paper status"),
        sort: str = Query("created_at", description="Sort field"),
        order: str = Query("desc", description="asc or desc"),
    ):
        with get_db_context() as conn:
            conditions: list[str] = []
            params: list[Any] = []
            service_paper_ids: list[int] | None = None

            if topic_id is not None:
                topic = conn.execute(
                    "SELECT name FROM topics WHERE id = ?",
                    (topic_id,),
                ).fetchone()
                if topic is None:
                    service_paper_ids = []
                else:
                    service_paper_ids = _paper_list_service_ids(
                        invoke_service,
                        topic["name"],
                    )
                conditions.append("pt.topic_id = ?")
                params.append(topic_id)

            if domain_id is not None and topic_id is None:
                conditions.append("t.domain_id = ?")
                params.append(domain_id)

            if status:
                conditions.append("p.status = ?")
                params.append(status)

            if search:
                conditions.append(
                    "(p.title LIKE ? OR p.authors LIKE ? OR p.venue LIKE ?)"
                )
                like = f"%{search}%"
                params.extend([like, like, like])

            if service_paper_ids is not None:
                _append_paper_id_filter(conditions, params, service_paper_ids)

            where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            if topic_id is not None:
                join_clause = "JOIN paper_topics pt ON pt.paper_id = p.id"
            elif domain_id is not None:
                join_clause = (
                    "JOIN paper_topics pt ON pt.paper_id = p.id "
                    "JOIN topics t ON t.id = pt.topic_id"
                )
            else:
                join_clause = "LEFT JOIN paper_topics pt ON pt.paper_id = p.id"

            count_sql = (
                "SELECT COUNT(DISTINCT p.id) AS c FROM papers p "
                f"{join_clause} {where_clause}"
            )
            total = conn.execute(count_sql, params).fetchone()["c"]

            allowed_sort = {
                "created_at",
                "year",
                "title",
                "citation_count",
                "venue",
                "id",
            }
            sort_col = sort if sort in allowed_sort else "created_at"
            sort_dir = "ASC" if order.lower() == "asc" else "DESC"
            offset = (page - 1) * per_page

            select_extra = ", pt.relevance AS relevance" if topic_id is not None else ""

            data_sql = f"""
                SELECT DISTINCT p.*{select_extra}
                FROM papers p
                {join_clause}
                {where_clause}
                ORDER BY p.{sort_col} {sort_dir}
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(data_sql, [*params, per_page, offset]).fetchall()

        papers = []
        for row in rows:
            paper = row_to_dict(row)
            paper["authors"] = parse_json_field(paper.get("authors"), [])
            if topic_id is None and "relevance" not in paper:
                paper["relevance"] = None
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
