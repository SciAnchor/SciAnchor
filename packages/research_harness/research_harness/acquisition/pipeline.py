"""Paper acquisition pipeline: download → annotate → triage."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..pdf_download import PaperDownloadCandidate
from ..storage.db import Database
from .candidate_store import load_pdf_candidates
from .downloader import DownloadResult, download_batch
from .routes import PDFRouteAudit, audit_summary
from research_harness.config import state_path

logger = logging.getLogger(__name__)

# Resolved against this process's state tree, not its working directory: a relative literal
# here put the downloads beside whatever directory the caller was in, which is why acquisition
# had never run anywhere but a developer checkout.
DEFAULT_DOWNLOAD_DIR = str(state_path("downloads"))
DEFAULT_MANUAL_DIR = str(state_path("manual_downloads"))


def _record_event(
    db: Database, paper_id: int, event_type: str, detail: str = "", provider: str = ""
) -> None:
    """Append a pipeline event to the event log."""
    try:
        conn = db.connect()
        conn.execute(
            "INSERT INTO pipeline_events (paper_id, event_type, detail, provider) VALUES (?, ?, ?, ?)",
            (paper_id, event_type, detail, provider),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.debug(
            "Failed to record pipeline event %s for paper %d",
            event_type,
            paper_id,
            exc_info=True,
        )


def _record_route_audit(db: Database, paper_id: int, audit: PDFRouteAudit) -> None:
    payload = audit.to_dict()
    summary = audit_summary(audit)
    provider = audit.successful_route or audit.failure_taxonomy or ""
    _record_event(
        db,
        paper_id,
        "download_route_audit",
        detail=json.dumps(summary, ensure_ascii=False, sort_keys=True),
        provider=provider,
    )
    try:
        conn = db.connect()
        conn.execute(
            """
            INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata)
            VALUES (?, ?, ?, ?)
            """,
            (
                paper_id,
                "pdf_route_audit",
                audit.local_path or "",
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.debug(
            "Failed to record route audit artifact for paper %d",
            paper_id,
            exc_info=True,
        )


@dataclass
class AcquisitionReport:
    topic_id: int
    total_papers: int = 0
    downloaded: int = 0
    annotated: int = 0
    needs_manual: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    manual_list: list[dict[str, Any]] = field(default_factory=list)
    # failure_taxonomy -> paper count, so callers can tell "no identifier on
    # record" / "landing pages only" / "browser challenge" apart from a
    # generic all_routes_failed.
    failure_taxonomies: dict[str, int] = field(default_factory=dict)
    #: Papers held by the topic that the strict selection cannot reach until someone screens.
    unscreened_candidates: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def unscreened_pool(db: Database, topic_id: int) -> int:
    """Papers this topic holds that the strict selection will never reach.

    `paper search --auto-ingest` files everything it finds as `candidate`, and the only
    promotion to `screened_in` is a person running `rh paper bulk-update`. So a topic can
    hold sixty papers and offer the strict selection none of them, for as long as nobody
    screens -- which is not a state acquire can fix, only one it must not report as done.
    """
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM paper_topics pt WHERE pt.topic_id = ? "
            "AND pt.screening_status = 'candidate'",
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


def _build_candidates(
    db: Database,
    topic_id: int,
    *,
    limit: int | None = None,
    include_candidates: bool = False,
) -> list[PaperDownloadCandidate]:
    limit_clause = ""
    screening_clause = ""
    if include_candidates:
        screening_clause = "AND pt.screening_status IN ('screened_in', 'candidate')"
    else:
        screening_clause = (
            "AND pt.screening_status = 'screened_in' AND pt.manuscript_eligible = 1"
        )
    params: tuple[Any, ...]
    if limit is not None and limit > 0:
        limit_clause = "LIMIT ?"
        params = (topic_id, int(limit))
    else:
        params = (topic_id,)
    conn = db.connect()
    try:
        rows = conn.execute(
            f"""
            SELECT p.id, p.title, p.year, p.venue, p.doi, p.arxiv_id,
                   p.pmid, p.pmcid, p.url,
                   p.status, p.pdf_path
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND (p.status = 'meta_only' OR p.pdf_path IS NULL OR p.pdf_path = '')
              AND COALESCE(pt.relevance, '') NOT LIKE 'dismissed%'
              AND COALESCE(pt.relevance, '') NOT LIKE 'excluded%'
              AND TRIM(COALESCE(p.title, '')) != ''
              {screening_clause}
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY p.id
            {limit_clause}
            """,
            params,
        ).fetchall()
    finally:
        conn.close()

    conn = db.connect()
    try:
        candidates = []
        for row in rows:
            candidates.append(
                PaperDownloadCandidate(
                    paper_id=int(row["id"]),
                    title=row["title"] or "",
                    year=row["year"],
                    venue=row["venue"] or "",
                    doi=row["doi"] or "",
                    arxiv_id=row["arxiv_id"] or "",
                    pmid=row["pmid"] or "",
                    pmcid=row["pmcid"] or "",
                    url=row["url"] or "",
                    extra_urls=_stored_candidate_urls(conn, int(row["id"])),
                )
            )
    finally:
        conn.close()
    return candidates


def _stored_candidate_urls(conn: Any, paper_id: int) -> tuple[str, ...]:
    """Search-time PDF candidate URLs persisted at ingest, rank order kept.

    Browser-only candidates are excluded; the downloader cannot execute them.
    """
    urls: list[str] = []
    try:
        stored = load_pdf_candidates(conn, paper_id)
    except Exception:
        logger.debug(
            "Failed to load stored pdf candidates for paper %d",
            paper_id,
            exc_info=True,
        )
        return ()
    for item in stored:
        if item.get("requires_browser"):
            continue
        urls.append(item["url"])
    return tuple(urls)


def _run_download_batch(
    candidates: list[PaperDownloadCandidate], download_path: Path
) -> list[DownloadResult]:
    """Run async PDF downloads from both sync and already-async callers.

    MCP tool dispatch may execute primitives while an event loop is already
    running. Calling ``asyncio.run`` in that environment raises
    ``RuntimeError: asyncio.run() cannot be called from a running event loop``.
    The CLI path remains the common no-running-loop case, while MCP dispatch is
    handled by running the coroutine in a short-lived worker thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(download_batch(candidates, download_path))

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            lambda: asyncio.run(download_batch(candidates, download_path))
        )
        return future.result()


def _annotate_paper(
    db: Database, paper_id: int, pdf_path: Path, artifacts_root: Path
) -> bool:
    try:
        from ..integrations.paperindex_adapter import PaperIndexAdapter
    except ImportError:
        logger.warning(
            "paperindex not installed, skipping annotation for paper %d", paper_id
        )
        return False

    conn = db.connect()
    try:
        adapter = PaperIndexAdapter(conn, artifacts_root)
        adapter.annotate_paper(paper_id, pdf_path, skip_card=True)
        # Defensive: ensure pdf_path is written even if adapter didn't set it
        conn.execute(
            "UPDATE papers SET pdf_path = COALESCE(NULLIF(pdf_path, ''), ?) WHERE id = ?",
            (str(pdf_path), paper_id),
        )
        conn.commit()
        logger.info("Annotated paper %d from %s", paper_id, pdf_path)
        return True
    except Exception:
        logger.exception("Failed to annotate paper %d", paper_id)
        conn.execute(
            "UPDATE papers SET pdf_path = ?, status = ? WHERE id = ?",
            (str(pdf_path), "downloaded", paper_id),
        )
        conn.commit()
        return False
    finally:
        conn.close()


def _annotate_and_compile(
    db: Database, paper_id: int, pdf_path: Path, artifacts_root: Path
) -> bool:
    """Annotate one paper and eagerly compile its summary (worker unit)."""
    ok = _annotate_paper(db, paper_id, pdf_path, artifacts_root)
    if ok:
        try:
            from ..execution.compiled_summary import ensure_compiled_summary

            ensure_compiled_summary(db, paper_id)
        except Exception:
            logger.debug(
                "Eager compilation failed for paper %d", paper_id, exc_info=True
            )
    return ok


def _annotation_workers() -> int:
    raw = os.environ.get("RESEARCH_HARNESS_ANNOTATE_WORKERS", "")
    try:
        value = int(raw)
    except ValueError:
        value = 0
    return value if value > 0 else 4


def _process_results(
    db: Database,
    results: list[DownloadResult],
    candidates: list[PaperDownloadCandidate],
    artifacts_root: Path,
) -> AcquisitionReport:
    candidate_map = {c.paper_id: c for c in candidates}
    report = AcquisitionReport(topic_id=0, total_papers=len(results))

    # Annotation (PDF parse + summary compile) dominates wall time at
    # 20-60s/paper; run it across worker threads. Each worker opens its own
    # SQLite connection and the DB runs in WAL mode with busy_timeout, so
    # concurrent writers are safe.
    successes = [r for r in results if r.status == "success" and r.path]
    annotate_ok: dict[int, bool] = {}
    if successes:
        for result in successes:
            _record_event(db, result.paper_id, "annotate_start")
        workers = min(_annotation_workers(), len(successes))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                result.paper_id: pool.submit(
                    _annotate_and_compile,
                    db,
                    result.paper_id,
                    result.path,
                    artifacts_root,
                )
                for result in successes
            }
            for paper_id, future in futures.items():
                try:
                    annotate_ok[paper_id] = future.result()
                except Exception:
                    logger.exception("Annotation worker failed for paper %d", paper_id)
                    annotate_ok[paper_id] = False

    for result in results:
        entry: dict[str, Any] = {
            "paper_id": result.paper_id,
            "status": result.status,
            "path": str(result.path) if result.path else None,
            "failure_reason": result.failure_reason,
        }
        if result.audit is not None:
            _record_route_audit(db, result.paper_id, result.audit)
            entry["audit"] = result.audit.to_dict()
            if result.audit.failure_taxonomy:
                taxonomy = result.audit.failure_taxonomy
                entry["failure_taxonomy"] = taxonomy
                report.failure_taxonomies[taxonomy] = (
                    report.failure_taxonomies.get(taxonomy, 0) + 1
                )

        if result.status == "success" and result.path:
            _record_event(
                db, result.paper_id, "download_ok", provider=result.provider or ""
            )
            report.downloaded += 1
            if annotate_ok.get(result.paper_id, False):
                _record_event(db, result.paper_id, "annotate_ok")
                report.annotated += 1
                entry["annotated"] = True
            else:
                _record_event(db, result.paper_id, "annotate_fail")
                entry["annotated"] = False
        elif result.status == "needs_manual":
            _record_event(
                db,
                result.paper_id,
                "download_fail",
                detail=result.failure_reason or "needs manual",
                provider="paywall",
            )
            report.needs_manual += 1
            cand = candidate_map.get(result.paper_id)
            if cand:
                report.manual_list.append(
                    {
                        "paper_id": cand.paper_id,
                        "title": cand.title,
                        "year": cand.year,
                        "venue": cand.venue,
                        "doi": cand.doi,
                        "arxiv_id": cand.arxiv_id,
                        "pmid": cand.pmid,
                        "pmcid": cand.pmcid,
                        "failure_reason": result.failure_reason,
                        "failure_taxonomy": (
                            result.audit.failure_taxonomy if result.audit else None
                        ),
                    }
                )
        else:
            _record_event(
                db,
                result.paper_id,
                "download_fail",
                detail=result.failure_reason or "all URLs failed",
            )
            report.failed += 1

        report.results.append(entry)

    return report


def acquire_papers(
    db: Database,
    topic_id: int,
    download_dir: str | Path | None = None,
    artifacts_root: str | Path | None = None,
    limit: int | None = None,
    include_candidates: bool = False,
) -> AcquisitionReport:
    download_path = Path(download_dir or DEFAULT_DOWNLOAD_DIR)
    artifacts_path = Path(artifacts_root) if artifacts_root else state_path("artifacts")

    candidates = _build_candidates(
        db,
        topic_id,
        limit=limit,
        include_candidates=include_candidates,
    )
    if not candidates:
        waiting = 0 if include_candidates else unscreened_pool(db, topic_id)
        if waiting:
            # "Acquisition complete" over an empty selection is how a topic with a full pool
            # spent days looking finished: every downstream step then judged on abstracts
            # alone, and exemplar curate kept nothing without ever saying why.
            logger.info(
                "topic %d: nothing screened in; %d candidates are waiting to be screened",
                topic_id,
                waiting,
            )
        else:
            logger.info("No papers need downloading for topic %d", topic_id)
        return AcquisitionReport(
            topic_id=topic_id, total_papers=0, unscreened_candidates=waiting
        )

    logger.info("Downloading %d papers for topic %d", len(candidates), topic_id)
    for c in candidates:
        _record_event(db, c.paper_id, "download_start")
    results = _run_download_batch(candidates, download_path)

    report = _process_results(db, results, candidates, artifacts_path)
    report.topic_id = topic_id

    if report.manual_list:
        # Stamp topic_id on every manual entry (BUG-002): the shared
        # pending_manual.json accumulates across topics, so entries must carry
        # their topic to stop one topic's manual papers surfacing in another's
        # pending list / coverage view.
        for item in report.manual_list:
            item["topic_id"] = topic_id
        _write_manual_list(report.manual_list, Path(DEFAULT_MANUAL_DIR))

    return report


def _write_manual_list(manual_list: list[dict[str, Any]], manual_dir: Path) -> None:
    manual_dir.mkdir(parents=True, exist_ok=True)

    json_path = manual_dir / "pending_manual.json"
    existing: list[dict[str, Any]] = []
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []

    existing_ids = {item["paper_id"] for item in existing}
    for item in manual_list:
        if item["paper_id"] not in existing_ids:
            existing.append(item)

    json_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))

    readme_path = manual_dir / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# Manual Downloads\n\n"
            "Place PDF files here with filename format: `{paper_id}_{title}.pdf`\n\n"
            "The paper_id prefix is required for matching. Example: `42_attention_is_all_you_need.pdf`\n\n"
            "After placing files, run: `rhub paper ingest-manual`\n"
        )

    logger.info(
        "Wrote %d papers to manual download list: %s", len(manual_list), json_path
    )


def ingest_manual_downloads(
    db: Database,
    manual_dir: str | Path | None = None,
    artifacts_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    manual_path = Path(manual_dir or DEFAULT_MANUAL_DIR)
    artifacts_path = Path(artifacts_root) if artifacts_root else state_path("artifacts")

    if not manual_path.exists():
        return []

    results: list[dict[str, Any]] = []
    for pdf_file in sorted(manual_path.glob("*.pdf")):
        name = pdf_file.stem
        parts = name.split("_", 1)
        try:
            paper_id = int(parts[0])
        except (ValueError, IndexError):
            logger.warning(
                "Skipping %s: filename must start with paper_id", pdf_file.name
            )
            results.append(
                {
                    "file": pdf_file.name,
                    "status": "skipped",
                    "reason": "invalid filename",
                }
            )
            continue

        if _annotate_paper(db, paper_id, pdf_file, artifacts_path):
            results.append(
                {"file": pdf_file.name, "paper_id": paper_id, "status": "annotated"}
            )
        else:
            results.append(
                {
                    "file": pdf_file.name,
                    "paper_id": paper_id,
                    "status": "downloaded_only",
                }
            )

    if results:
        pending_path = manual_path / "pending_manual.json"
        if pending_path.exists():
            try:
                pending = json.loads(pending_path.read_text())
                ingested_ids = {r["paper_id"] for r in results if "paper_id" in r}
                remaining = [p for p in pending if p["paper_id"] not in ingested_ids]
                pending_path.write_text(
                    json.dumps(remaining, ensure_ascii=False, indent=2)
                )
            except (json.JSONDecodeError, OSError):
                pass

    return results
