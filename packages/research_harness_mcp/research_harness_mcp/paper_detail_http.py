"""FastAPI route registration for paper detail reads."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException


def register_paper_detail_routes(
    app: FastAPI,
    *,
    get_db_context: Callable[[], Any],
    row_to_dict: Callable[[Any], dict[str, Any]],
    rows_to_list: Callable[[list[Any]], list[dict[str, Any]]],
    parse_json_field: Callable[[str | None, Any], Any],
    paper_detail_model: type[Any],
) -> None:
    """Register paper detail route with injected runtime dependencies."""

    @app.get("/api/papers/{paper_id}", response_model=paper_detail_model)
    def get_paper(paper_id: int):
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id = ?",
                (paper_id,),
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=404, detail=f"Paper {paper_id} not found"
                )

            ann_rows = conn.execute(
                """
                SELECT id, section, content, source, confidence, created_at, updated_at
                FROM paper_annotations
                WHERE paper_id = ?
                ORDER BY section
                """,
                (paper_id,),
            ).fetchall()

            topic_rows = conn.execute(
                """
                SELECT t.id, t.name, pt.relevance
                FROM topics t
                JOIN paper_topics pt ON pt.topic_id = t.id
                WHERE pt.paper_id = ?
                """,
                (paper_id,),
            ).fetchall()

        annotations = []
        for ann_row in ann_rows:
            annotation = row_to_dict(ann_row)
            annotation["content"] = parse_json_field(
                annotation.get("content"),
                annotation.get("content"),
            )
            annotations.append(annotation)

        return paper_detail_model(
            id=row["id"],
            title=row["title"] or "",
            authors=parse_json_field(row["authors"], []),
            year=row["year"],
            venue=row["venue"] or "",
            doi=row["doi"] or "",
            arxiv_id=row["arxiv_id"] or "",
            s2_id=row["s2_id"] or "",
            url=row["url"] or "",
            abstract=row["abstract"] or "",
            citation_count=row["citation_count"],
            deep_read=bool(row["deep_read"]) if "deep_read" in row.keys() else False,
            status=row["status"] or "meta_only",
            pdf_path=row["pdf_path"] or "",
            created_at=row["created_at"] or "",
            annotations=annotations,
            topics=rows_to_list(topic_rows),
        )
