"""Background runner for topic expansion HTTP jobs."""

from __future__ import annotations

import concurrent.futures as _cf
import logging
import sqlite3
import threading
import time as _time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any


def run_expansion_job(
    job_id: int,
    topic_id: int,
    *,
    db_path: Path,
    api_factory: Callable[..., Any],
    get_db_context: Callable[[], AbstractContextManager[sqlite3.Connection]],
    update_expansion_job: Callable[..., None],
    expansion_job_is_cancelled: Callable[[int], bool],
    build_expansion_query: Callable[[sqlite3.Connection, int, str, str], str],
    search_papers_impl: Callable[..., dict[str, Any]],
    ingest_paper_impl: Callable[..., dict[str, Any]],
    deep_read_paper_impl: Callable[..., dict[str, Any]],
    pick_candidate_source: Callable[[dict[str, Any]], str],
    paper_already_in_topic: Callable[[sqlite3.Connection, int, str], bool],
    deep_read_provider_pool: Callable[[], Sequence[str]],
    expansion_deep_read_concurrency: Callable[[int], int],
    expansion_deep_read_paper_timeout: Callable[[], float],
    logger_obj: logging.Logger | None = None,
) -> None:
    """Run one topic expansion job with explicit HTTP-layer dependencies."""
    log = logger_obj or logging.getLogger(__name__)
    api = api_factory(db_path=db_path)
    all_rounds_errored = True
    try:
        with get_db_context() as conn:
            topic = conn.execute(
                "SELECT id, name, description FROM topics WHERE id = ?",
                (topic_id,),
            ).fetchone()
            job = conn.execute(
                "SELECT * FROM expansion_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if topic is None or job is None:
                return
            update_expansion_job(conn, job_id, status="running", current_round=0)
            retrieval_target = int(job["retrieval_target"])
            deep_read_target = int(job["deep_read_target"])
            rounds_target = int(job["rounds_target"])

        per_round = max(1, round(retrieval_target / rounds_target))
        seen_sources: set[str] = set()
        papers_fetched = 0
        papers_deep_read = 0
        last_error = ""
        topic_name = str(topic["name"] or "").strip()
        topic_description = str(topic["description"] or "").strip()

        for round_index in range(1, rounds_target + 1):
            if expansion_job_is_cancelled(job_id):
                return
            with get_db_context() as conn:
                update_expansion_job(conn, job_id, current_round=round_index)
                query = (
                    build_expansion_query(conn, topic_id, topic_name, topic_description)
                    if round_index > 1
                    else " ".join(
                        part for part in (topic_name, topic_description) if part
                    ).strip()
                    or topic_name
                )
            round_ingested = 0
            round_error_count = 0
            round_only_errors = False
            try:
                search_out = search_papers_impl(
                    api, query=query, topic_id=topic_id, max_results=per_round
                )
            except Exception as exc:
                last_error = str(exc)[:2000]
                round_only_errors = True
                with get_db_context() as conn:
                    update_expansion_job(conn, job_id, last_error=last_error)
                continue
            provider_errors = search_out.get("provider_errors") or []
            if provider_errors:
                last_error = "; ".join(str(err) for err in provider_errors)[:2000]
                with get_db_context() as conn:
                    update_expansion_job(conn, job_id, last_error=last_error)
            if not provider_errors:
                all_rounds_errored = False
            elif not (search_out.get("papers") or []):
                round_only_errors = True
            for candidate in search_out.get("papers") or []:
                if expansion_job_is_cancelled(job_id):
                    return
                source = pick_candidate_source(candidate)
                if not source or source in seen_sources:
                    continue
                seen_sources.add(source)
                with get_db_context() as conn:
                    already_linked = paper_already_in_topic(conn, topic_id, source)
                if already_linked:
                    continue
                try:
                    ingest_out = ingest_paper_impl(
                        api, source=source, topic_id=topic_id, relevance="high"
                    )
                except Exception as exc:
                    round_error_count += 1
                    last_error = str(exc)[:2000]
                    with get_db_context() as conn:
                        update_expansion_job(conn, job_id, last_error=last_error)
                    continue
                paper_id = int(ingest_out.get("paper_id", 0) or 0)
                if paper_id:
                    with get_db_context() as conn:
                        linked = conn.execute(
                            "SELECT 1 FROM paper_topics WHERE topic_id = ? AND paper_id = ?",
                            (topic_id, paper_id),
                        ).fetchone()
                        if linked and not already_linked:
                            papers_fetched += 1
                            round_ingested += 1
                            update_expansion_job(
                                conn, job_id, papers_fetched=papers_fetched
                            )
                all_rounds_errored = False
                if papers_fetched >= retrieval_target:
                    break
            if round_ingested == 0 and round_error_count == len(
                search_out.get("papers") or []
            ):
                round_only_errors = bool(search_out.get("papers"))
                with get_db_context() as conn:
                    update_expansion_job(conn, job_id, last_error=last_error)
            if round_only_errors:
                continue
            if papers_fetched >= retrieval_target or round_ingested == 0:
                break

        if expansion_job_is_cancelled(job_id):
            return

        with get_db_context() as conn:
            rows = conn.execute(
                """
                SELECT p.id
                FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ? AND COALESCE(p.deep_read, 0) = 0
                ORDER BY CASE pt.relevance
                            WHEN 'high' THEN 3
                            WHEN 'medium' THEN 2
                            ELSE 1
                         END DESC,
                         COALESCE(p.year, 0) DESC,
                         p.id DESC
                LIMIT ?
                """,
                (topic_id, deep_read_target),
            ).fetchall()

        provider_pool = list(deep_read_provider_pool())
        max_workers = expansion_deep_read_concurrency(len(provider_pool))
        paper_timeout = expansion_deep_read_paper_timeout()
        paper_ids = [int(row["id"]) for row in rows]
        progress_lock = threading.Lock()
        log.info(
            "expansion job %d deep-read phase: %d papers, pool=%s, max_workers=%d, timeout=%.0fs",
            job_id,
            len(paper_ids),
            provider_pool,
            max_workers,
            paper_timeout,
        )

        provider_failures: dict[str, int] = {}
        quarantined: set[str] = set()
        failure_lock = threading.Lock()

        def _try_provider(
            paper_id: int, provider: str
        ) -> tuple[dict[str, Any] | None, str]:
            from research_harness.execution.llm_primitives import (
                set_provider_override,
            )

            set_provider_override(provider or None)
            t0 = _time.monotonic()
            try:
                result = deep_read_paper_impl(api, paper_id=paper_id, topic_id=topic_id)
            finally:
                set_provider_override(None)
            elapsed = _time.monotonic() - t0
            model_used = (result or {}).get("model_used", "?")
            log.info(
                "expansion job %d paper %d provider=%s model=%s elapsed=%.1fs",
                job_id,
                paper_id,
                provider or "default",
                model_used,
                elapsed,
            )
            return result, ""

        def _record_failure(provider: str) -> bool:
            """Return True if provider is now quarantined."""
            with failure_lock:
                provider_failures[provider] = provider_failures.get(provider, 0) + 1
                if provider_failures[provider] >= 2 and provider not in quarantined:
                    quarantined.add(provider)
                    return True
                return False

        def _next_provider(tried: set[str]) -> str | None:
            if not provider_pool:
                return None
            with failure_lock:
                for provider in provider_pool:
                    if provider in tried:
                        continue
                    if provider in quarantined:
                        continue
                    return provider
            return None

        def _run_one(
            paper_id: int, initial_provider: str
        ) -> tuple[int, dict[str, Any] | None, str]:
            tried: set[str] = set()
            provider = initial_provider
            last_err = ""
            while True:
                if expansion_job_is_cancelled(job_id):
                    return paper_id, None, ""
                if provider in quarantined:
                    next_provider = _next_provider(tried)
                    if next_provider is None:
                        return paper_id, None, last_err or "all providers quarantined"
                    provider = next_provider
                tried.add(provider)
                try:
                    result, _ = _try_provider(paper_id, provider)
                    if result is not None and result.get("model_used") != "none":
                        return paper_id, result, ""
                    _record_failure(provider)
                except Exception as exc:
                    last_err = f"{provider}: {str(exc)[:1500]}"
                    newly_quarantined = _record_failure(provider)
                    if not newly_quarantined and provider_failures.get(provider, 0) < 2:
                        continue
                next_provider = _next_provider(tried)
                if next_provider is None:
                    return paper_id, None, last_err or f"{provider}: empty output"
                provider = next_provider

        pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix=f"expansion-{job_id}-dr"
        )
        try:
            futures = []
            for idx, paper_id in enumerate(paper_ids):
                provider = (
                    provider_pool[idx % len(provider_pool)] if provider_pool else ""
                )
                futures.append(pool.submit(_run_one, paper_id, provider))

            batch_timeout = paper_timeout + 60.0
            try:
                for fut in as_completed(futures, timeout=batch_timeout):
                    if expansion_job_is_cancelled(job_id):
                        for pending in futures:
                            pending.cancel()
                        return
                    _pid, result, err = fut.result()
                    if result is not None and result.get("model_used") != "none":
                        with progress_lock:
                            papers_deep_read += 1
                            current = papers_deep_read
                        with get_db_context() as conn:
                            update_expansion_job(conn, job_id, papers_deep_read=current)
                        all_rounds_errored = False
                    elif err:
                        last_error = err
                        with get_db_context() as conn:
                            update_expansion_job(conn, job_id, last_error=last_error)
                    if papers_deep_read >= deep_read_target:
                        for pending in futures:
                            pending.cancel()
                        break
            except _cf.TimeoutError:
                hung = [f for f in futures if not f.done()]
                last_error = (
                    f"{len(hung)} deep-read worker(s) hung past "
                    f"{batch_timeout:.0f}s; moving on"
                )
                log.warning(
                    "expansion job %d: %s",
                    job_id,
                    last_error,
                )
                for pending in hung:
                    pending.cancel()
                with get_db_context() as conn:
                    update_expansion_job(conn, job_id, last_error=last_error)
        finally:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                pool.shutdown(wait=False)

        if expansion_job_is_cancelled(job_id):
            return
        with get_db_context() as conn:
            status = (
                "failed" if all_rounds_errored and papers_fetched == 0 else "completed"
            )
            update_expansion_job(
                conn,
                job_id,
                status=status,
                last_error=last_error if status == "failed" else last_error,
            )
    except Exception as exc:
        with get_db_context() as conn:
            if not expansion_job_is_cancelled(job_id):
                update_expansion_job(
                    conn,
                    job_id,
                    status="failed",
                    last_error=str(exc)[:2000],
                )
