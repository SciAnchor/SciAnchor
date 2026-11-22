"""FastAPI route registration for paper ingest and batch enrichment."""

import json
import time
from typing import Any, Callable

from fastapi import BackgroundTasks, FastAPI


def _default_paper_pool_factory(conn: Any) -> Any:
    from research_harness.core.paper_pool import PaperPool

    return PaperPool(conn)


def _mark_field_brief_stale_if_needed(
    *,
    topic_id: int | None,
    get_db_context: Callable[[], Any],
) -> None:
    if topic_id is None:
        return
    try:
        with get_db_context() as conn:
            meta = conn.execute(
                "SELECT paper_count_at_build FROM field_brief_meta WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()
            if meta:
                current = conn.execute(
                    "SELECT COUNT(*) FROM paper_topics WHERE topic_id = ?",
                    (topic_id,),
                ).fetchone()[0]
                if current > meta["paper_count_at_build"] * 1.15:
                    conn.execute(
                        "UPDATE field_brief_meta SET stale = 1 WHERE topic_id = ?",
                        (topic_id,),
                    )
                    conn.commit()
    except Exception:
        pass


def register_paper_ingest_routes(
    app: FastAPI,
    *,
    paper_ingest_request_model: type[Any],
    api_factory: Callable[[], Any],
    ingest_paper_impl: Callable[..., dict[str, Any]],
    get_db_context: Callable[[], Any],
) -> None:
    """Register paper ingest route with injected runtime dependencies."""

    @app.post("/api/papers/ingest")
    def ingest_paper(body: paper_ingest_request_model):
        """Ingest a paper by arxiv ID, DOI, or URL."""
        api = api_factory()
        output = ingest_paper_impl(
            api,
            source=body.source,
            topic_id=body.topic_id,
            relevance=body.relevance,
        )

        _mark_field_brief_stale_if_needed(
            topic_id=body.topic_id,
            get_db_context=get_db_context,
        )

        return {
            "status": "success",
            "summary": f"Ingested paper {output.get('paper_id')}",
            "output": output,
        }


def register_paper_enrich_batch_routes(
    app: FastAPI,
    *,
    batch_enrich_request_model: type[Any],
    get_db_context: Callable[[], Any],
    paper_pool_factory: Callable[[Any], Any] = _default_paper_pool_factory,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    """Register paper batch-enrichment route with injected runtime dependencies."""

    @app.post("/api/papers/enrich-batch")
    def enrich_batch(
        body: batch_enrich_request_model, background_tasks: BackgroundTasks
    ):
        """Kick off batch enrichment in the background. Returns immediately."""

        with get_db_context() as conn:
            cursor = conn.execute(
                "INSERT INTO async_jobs (job_type, status, input_params) VALUES ('paper_enrich_batch', 'pending', ?)",
                (
                    json.dumps(
                        {
                            "topic_id": body.topic_id,
                            "limit": body.limit,
                            "missing_fields": body.missing_fields,
                        }
                    ),
                ),
            )
            job_id = cursor.lastrowid
            conn.commit()

        def _enrich_batch() -> int:
            venue_placeholders = ("", "arxiv", "arxiv.org", "arxiv preprint")
            with get_db_context() as conn:
                pool = paper_pool_factory(conn)
                where = ""
                params: list[Any] = []
                if body.topic_id is not None:
                    where = (
                        " AND id IN "
                        "(SELECT paper_id FROM paper_topics WHERE topic_id = ?)"
                    )
                    params.append(body.topic_id)
                rows = conn.execute(
                    "SELECT id, arxiv_id, doi, s2_id, venue, citation_count "
                    f"FROM papers WHERE 1=1{where} ORDER BY id DESC",
                    params,
                ).fetchall()

                count = 0
                for row in rows:
                    if count >= body.limit:
                        break
                    has_id = bool(
                        (row["arxiv_id"] or "").strip()
                        or (row["doi"] or "").strip()
                        or (row["s2_id"] or "").strip()
                    )
                    if not has_id:
                        continue
                    needs = False
                    for field_name in body.missing_fields:
                        value = row[field_name] if field_name in row.keys() else None
                        if field_name == "venue" and (
                            not value
                            or str(value).strip().lower() in venue_placeholders
                        ):
                            needs = True
                        elif field_name != "venue" and (value is None or value == 0):
                            needs = True
                    if not needs:
                        continue
                    pool.enrich_metadata(row["id"])
                    count += 1
                    sleep_fn(1.05)
                return count

        def _run_batch() -> None:
            from research_harness.acquisition.spc_bridge import SPCAcquisitionError

            def update_job(status: str, *, result=None, error=None) -> None:
                with get_db_context() as conn:
                    conn.execute(
                        "UPDATE async_jobs SET status = ?, result = ?, error = ?, "
                        "updated_at = datetime('now') WHERE id = ?",
                        (
                            status,
                            json.dumps(result) if result is not None else None,
                            json.dumps(error) if error is not None else None,
                            job_id,
                        ),
                    )
                    conn.commit()

            update_job("running")
            try:
                count = _enrich_batch()
            except SPCAcquisitionError as exc:
                update_job(
                    "failed", error={"code": exc.code, "retryable": exc.retryable}
                )
            except Exception:
                update_job(
                    "failed",
                    error={"code": "batch_enrichment_failed", "retryable": False},
                )
            else:
                update_job("completed", result={"enriched_count": count})

        background_tasks.add_task(_run_batch)
        return {
            "status": "started",
            "job_id": job_id,
            "limit": body.limit,
            "missing_fields": body.missing_fields,
        }
