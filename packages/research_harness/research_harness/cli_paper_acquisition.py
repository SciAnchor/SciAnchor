"""Paper ingest/acquisition/metadata subcommands for the RH CLI."""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable
from typing import Any

import click

from ._core.config import state_path
from .acquisition.spc_bridge import SPCAcquisitionError
from .paper_sources import PaperRecord
from .storage.models import Paper

logger = logging.getLogger(__name__)


def _pubmed_provider():
    from .paper_source_clients import SPCProvider

    return SPCProvider()


def _paper_from_pubmed_record(record: PaperRecord) -> Paper:
    return Paper(
        title=record.title,
        authors=list(record.authors),
        year=record.year,
        venue=record.venue,
        abstract=record.abstract,
        doi=record.doi,
        arxiv_id=record.arxiv_id,
        s2_id=record.s2_id,
        pmid=record.pmid,
        pmcid=record.pmcid,
        url=record.url,
        affiliations=list(record.affiliations),
        concepts_json=json.dumps(record.concepts, ensure_ascii=False)
        if record.concepts
        else "",
    )


def _json_authors(authors: list[str]) -> str:
    return json.dumps(authors, ensure_ascii=False)


def _has_authors(value: str | None) -> bool:
    if not value or value.strip() in {"", "[]", '""', "null"}:
        return False
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return bool(value.strip())
    return bool(parsed) if isinstance(parsed, list) else bool(str(parsed).strip())


def _is_placeholder_title(value: str | None) -> bool:
    text = (value or "").strip().lower()
    return not text or text.startswith(("doi:", "pmid:", "s2:", "pdf:"))


def _safe_identifier_update(
    conn: Any, paper_id: int, field_name: str, value: str
) -> bool:
    if not value:
        return False
    row = conn.execute(
        f"SELECT id FROM papers WHERE {field_name} = ? AND id != ?",
        (value, paper_id),
    ).fetchone()
    return row is None


def _apply_pubmed_record_update(
    conn: Any, row: Any, record: PaperRecord, *, dry_run: bool = False
) -> dict[str, str]:
    paper_id = int(row["id"])
    updates: dict[str, str] = {}
    set_clauses: list[str] = []
    params: list[object] = []

    def set_field(field_name: str, value: object, label: str | None = None) -> None:
        if value is None or value == "":
            return
        set_clauses.append(f"{field_name} = ?")
        params.append(value)
        updates[field_name] = str(label if label is not None else value)

    if record.title and _is_placeholder_title(row["title"]):
        set_field("title", record.title)
    if record.authors and not _has_authors(row["authors"]):
        set_field("authors", _json_authors(record.authors), str(len(record.authors)))
    if record.year and row["year"] is None:
        set_field("year", int(record.year))
    if record.venue and not (row["venue"] or "").strip():
        set_field("venue", record.venue)
    if record.abstract and not (row["abstract"] or "").strip():
        set_field("abstract", record.abstract, record.abstract[:80] + "...")
    for field_name, value in (
        ("doi", record.doi),
        ("pmid", record.pmid),
        ("pmcid", record.pmcid),
    ):
        if (
            value
            and not (row[field_name] or "").strip()
            and _safe_identifier_update(conn, paper_id, field_name, value)
        ):
            set_field(field_name, value)
    if record.url and not (row["url"] or "").strip():
        set_field("url", record.url)
    if record.concepts and not (row["concepts_json"] or "").strip():
        set_field("concepts_json", json.dumps(record.concepts, ensure_ascii=False))

    if set_clauses and not dry_run:
        params.append(paper_id)
        conn.execute(f"UPDATE papers SET {', '.join(set_clauses)} WHERE id = ?", params)
    return updates


def register_ingest(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register the paper ingest command on the existing paper group."""

    @paper.command("ingest")
    @click.option("--arxiv-id", default=None)
    @click.option("--doi", default=None)
    @click.option("--s2-id", default=None)
    @click.option("--pmid", default=None, help="PubMed PMID to fetch and ingest")
    @click.option("--title", default=None)
    @click.option("--authors", default=None, help="Comma-separated author names")
    @click.option("--year", type=int, default=None)
    @click.option("--venue", default=None)
    @click.option("--pdf-path", default=None, help="Path to local PDF")
    @click.option("--url", default=None, help="URL to paper PDF or landing page")
    @click.option("--topic", "topic_name", default=None)
    @click.option(
        "--relevance", type=click.Choice(["high", "medium", "low"]), default="medium"
    )
    @click.option("--dry-run", is_flag=True, default=False)
    @click.pass_context
    def paper_ingest(
        ctx: click.Context,
        arxiv_id: str | None,
        doi: str | None,
        s2_id: str | None,
        pmid: str | None,
        title: str | None,
        authors: str | None,
        year: int | None,
        venue: str | None,
        pdf_path: str | None,
        url: str | None,
        topic_name: str | None,
        relevance: str,
        dry_run: bool,
    ) -> None:
        from .core.paper_pool import PaperPool

        if not any([arxiv_id, doi, s2_id, pmid, title, url, pdf_path]):
            raise click.ClickException(
                "provide at least one of --arxiv-id, --doi, --s2-id, --pmid, --title, --url, --pdf-path"
            )

        pubmed_record: PaperRecord | None = None
        if pmid:
            try:
                pubmed_record = _pubmed_provider().fetch_by_pmid(pmid)
            except Exception as exc:
                raise click.ClickException(f"PubMed PMID lookup failed: {exc}") from exc
            if pubmed_record is None:
                raise click.ClickException(f"PubMed PMID not found: {pmid}")
            paper_obj = _paper_from_pubmed_record(pubmed_record)
        else:
            paper_obj = Paper(
                title=title or "",
                authors=[item.strip() for item in authors.split(",")]
                if authors
                else [],
                year=year,
                venue=venue or "",
                url=url or "",
                pdf_path=pdf_path or "",
                doi=doi or "",
                arxiv_id=arxiv_id or "",
                s2_id=s2_id or "",
            )
        if title:
            paper_obj.title = title
        if authors:
            paper_obj.authors = [
                item.strip() for item in authors.split(",") if item.strip()
            ]
        if year:
            paper_obj.year = year
        if venue:
            paper_obj.venue = venue
        if url:
            paper_obj.url = url
        if pdf_path:
            paper_obj.pdf_path = pdf_path
        if doi:
            paper_obj.doi = doi
        if arxiv_id:
            paper_obj.arxiv_id = arxiv_id
        if s2_id:
            paper_obj.s2_id = s2_id
        if pmid:
            paper_obj.pmid = pubmed_record.pmid if pubmed_record else pmid
        if dry_run:
            click.echo(
                json.dumps(
                    {"action": "ingest", "paper": dataclasses.asdict(paper_obj)},
                    ensure_ascii=False,
                )
            )
            return

        db = get_db(ctx)
        conn = db.connect()
        html_ingest_summary: dict[str, object] = {}
        knowledge_refresh: dict[str, object] = {}
        enrichment: dict[str, str] = {}
        try:
            topic_id = topic_id_or_exit(conn, topic_name) if topic_name else None
            paper_id = PaperPool(conn).ingest(
                paper_obj, topic_id=topic_id, relevance=relevance
            )
            # An identifier alone (--doi/--arxiv-id/--s2-id) used to land an empty row: title
            # '', authors [], year NULL (63 such DOI rows in the real pool). Resolve it the
            # way `rh paper enrich` does; a managed source failure fails the command.
            if (doi or arxiv_id or s2_id or pmid) and not (
                paper_obj.title or ""
            ).strip():
                try:
                    enrichment = PaperPool(conn).enrich_metadata(paper_id)
                except SPCAcquisitionError as exc:
                    raise click.ClickException(str(exc)) from exc
                except Exception as exc:  # noqa: BLE001 - network providers fail in many ways
                    enrichment = {"error": f"{type(exc).__name__}: {exc}"[:300]}
                row = conn.execute(
                    "SELECT title FROM papers WHERE id = ?", (paper_id,)
                ).fetchone()
                if row is not None and (row["title"] or "").strip():
                    paper_obj.title = row["title"]
            # URL-only ingest: fetch HTML so downstream claim_extract /
            # paper_summarize have text to read instead of silently landing
            # meta_only. See tool-gaps.md [2026-04-27].
            if (
                url
                and (url.startswith("http://") or url.startswith("https://"))
                and not pdf_path
            ):
                from .acquisition.html_ingest import fetch_html_as_markdown
                from .storage.models import PaperAnnotation

                page = fetch_html_as_markdown(url)
                if page.ok:
                    PaperPool(conn).upsert_annotation(
                        PaperAnnotation(
                            paper_id=paper_id,
                            section="summary",
                            content=page.markdown,
                            source=f"html_ingest:{url}",
                            confidence=0.9,
                            extractor_version="html_ingest.v1",
                        )
                    )
                    conn.execute(
                        "UPDATE papers SET status = ?, abstract = COALESCE(NULLIF(abstract, ''), ?) WHERE id = ?",
                        ("text_only", page.markdown[:2000], paper_id),
                    )
                    if page.title and not (paper_obj.title or "").strip():
                        conn.execute(
                            "UPDATE papers SET title = ? WHERE id = ?",
                            (page.title, paper_id),
                        )
                        paper_obj.title = page.title
                    conn.commit()
                    html_ingest_summary = {
                        "fetched": True,
                        "chars": len(page.markdown),
                        "http_status": page.http_status,
                    }
                else:
                    html_ingest_summary = {
                        "fetched": False,
                        "reason": page.error or "no body",
                    }
            from .knowledge.topic_refresh import refresh_topic_knowledge_after_ingest

            knowledge_refresh = refresh_topic_knowledge_after_ingest(
                db,
                topic_id=topic_id,
                paper_id=paper_id,
            )
        finally:
            conn.close()
        echo(
            ctx,
            {
                "paper_id": paper_id,
                "title": paper_obj.title,
                "status": "ingested",
                "pmid": paper_obj.pmid,
                "pmcid": paper_obj.pmcid,
                "html_ingest": html_ingest_summary,
                "knowledge_refresh": knowledge_refresh,
                "metadata_enrichment": enrichment,
            },
            f"Paper ingested: id={paper_id}, title='{paper_obj.title[:60]}'"
            + (
                f" [html: {html_ingest_summary.get('chars', 0)} chars]"
                if html_ingest_summary.get("fetched")
                else ""
            ),
        )


def register_metadata(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
) -> None:
    """Register paper metadata enrichment commands on the existing paper group."""

    @paper.command("enrich")
    @click.argument("paper_id", type=int, required=False)
    @click.option(
        "--topic", "topic_name", default=None, help="Enrich all papers in topic"
    )
    @click.option(
        "--with-s2/--no-s2",
        default=True,
        help="Call Semantic Scholar API for venue/citation/abstract (default: on)",
    )
    @click.option(
        "--limit", "max_papers", type=int, default=None, help="Max papers to enrich"
    )
    @click.option(
        "--missing",
        "missing_fields",
        default=None,
        help="Comma-separated fields to target, e.g. venue,citation_count",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Preview changes without applying",
    )
    @click.pass_context
    def paper_enrich(
        ctx: click.Context,
        paper_id: int | None,
        topic_name: str | None,
        with_s2: bool,
        max_papers: int | None,
        missing_fields: str | None,
        dry_run: bool,
    ) -> None:
        """Enrich paper metadata via Semantic Scholar API.

        Fills missing venue, citation_count, abstract, authors, affiliations,
        and cross-links (DOI, arXiv ID, S2 ID).  Also builds arXiv URL when absent.

        Examples:
            rh paper enrich 5                         # Enrich paper 5 via S2
            rh paper enrich --topic my-topic          # Enrich all in topic
            rh paper enrich --topic my-topic --missing venue,citation_count
            rh paper enrich --topic my-topic --limit 50 --dry-run
            rh paper enrich --no-s2 --topic my-topic  # URL-only (legacy mode)
        """
        import time

        from .core.paper_pool import PaperPool

        target_fields = set()
        if missing_fields:
            target_fields = {f.strip() for f in missing_fields.split(",") if f.strip()}

        db = get_db(ctx)
        conn = db.connect()
        try:
            pool = PaperPool(conn)
            papers_raw: list = []

            if paper_id is not None:
                p = pool.get(paper_id)
                if p is None:
                    raise click.ClickException(f"paper {paper_id} not found")
                papers_raw = [p]
            elif topic_name:
                topic_id = topic_id_or_exit(conn, topic_name)
                papers_raw = pool.list_papers(topic_id=topic_id)
            else:
                raise click.ClickException("provide either paper_id or --topic")

            candidates: list[tuple[int, str, str | None]] = []
            for p in papers_raw:
                pid = p.id or 0
                title = p.title or ""
                has_id = bool(p.arxiv_id or p.doi or getattr(p, "s2_id", None))
                if not has_id:
                    continue
                if target_fields:
                    row = conn.execute(
                        "SELECT * FROM papers WHERE id = ?", (pid,)
                    ).fetchone()
                    if row is None:
                        continue
                    needs = False
                    for f in target_fields:
                        val = row[f] if f in row.keys() else None
                        if not val or (
                            f == "venue"
                            and str(val).strip().lower()
                            in ("", "arxiv", "arxiv.org", "arxiv preprint")
                        ):
                            needs = True
                            break
                    if not needs:
                        continue
                candidates.append((pid, title, p.arxiv_id))
                if max_papers and len(candidates) >= max_papers:
                    break

            updated: list[dict] = []
            skipped: list[dict] = []
            s2_enriched = 0

            for pid, title, arxiv_id in candidates:
                result_info: dict = {"paper_id": pid, "title": title[:50]}

                if with_s2:
                    if dry_run:
                        result_info["action"] = "would_enrich_s2"
                        updated.append(result_info)
                        continue
                    try:
                        s2_result = pool.enrich_metadata(pid)
                        if s2_result and "error" not in s2_result:
                            result_info["s2_fields"] = list(s2_result.keys())
                            s2_enriched += 1
                            updated.append(result_info)
                        else:
                            err = (
                                s2_result.get("error", "unknown")
                                if s2_result
                                else "empty"
                            )
                            skipped.append({**result_info, "reason": f"s2: {err}"})
                        time.sleep(1.05)
                    except SPCAcquisitionError as exc:
                        raise click.ClickException(str(exc)) from exc
                    except Exception as exc:
                        skipped.append({**result_info, "reason": str(exc)[:80]})
                else:
                    if not arxiv_id:
                        skipped.append({**result_info, "reason": "no arxiv_id"})
                        continue
                    arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
                    if dry_run:
                        result_info.update(
                            {
                                "arxiv_id": arxiv_id,
                                "url": arxiv_url,
                                "action": "would_update",
                            }
                        )
                        updated.append(result_info)
                    else:
                        conn.execute(
                            "UPDATE papers SET url = ? WHERE id = ?", (arxiv_url, pid)
                        )
                        result_info.update({"arxiv_id": arxiv_id, "url": arxiv_url})
                        updated.append(result_info)

            if not dry_run:
                conn.commit()

            payload = {
                "dry_run": dry_run,
                "processed": len(candidates),
                "updated": len(updated),
                "s2_enriched": s2_enriched,
                "skipped": len(skipped),
                "updates": updated,
                "skip_reasons": skipped,
            }

            if ctx.obj.get("json"):
                click.echo(json.dumps(payload, ensure_ascii=False))
                return

            action_word = "would enrich" if dry_run else "enriched"
            click.echo(
                f"Paper enrichment: {len(updated)} {action_word} ({s2_enriched} via S2), {len(skipped)} skipped"
            )
            for u in updated:
                fields = u.get("s2_fields", [])
                label = ", ".join(fields) if fields else u.get("url", "url-only")
                click.echo(f"  [{u['paper_id']}] {u['title'][:45]}... -> {label}")
            for s in skipped:
                click.echo(f"  [{s['paper_id']}] skipped: {s['reason']}")
        finally:
            conn.close()

    @paper.command("backfill-pubmed")
    @click.option("--topic", "topic_name", default=None, help="Topic name or ID")
    @click.option(
        "--limit", "max_papers", type=int, default=100, help="Max papers per run"
    )
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    @click.pass_context
    def paper_backfill_pubmed(
        ctx: click.Context,
        topic_name: str | None,
        max_papers: int,
        dry_run: bool,
    ) -> None:
        """Backfill medical paper metadata from PubMed by PMID or DOI."""

        db = get_db(ctx)
        conn = db.connect()
        try:
            params: list[object] = []
            query = """
                SELECT p.*
                FROM papers p
            """
            if topic_name:
                topic_id = topic_id_or_exit(conn, topic_name)
                query += (
                    " JOIN paper_topics pt ON pt.paper_id = p.id WHERE pt.topic_id = ?"
                )
                params.append(topic_id)
                query += (
                    " AND (COALESCE(p.pmid, '') != '' OR COALESCE(p.doi, '') != '')"
                )
            else:
                query += (
                    " WHERE COALESCE(p.pmid, '') != '' OR COALESCE(p.doi, '') != ''"
                )
            query += " ORDER BY p.id LIMIT ?"
            params.append(max_papers)
            rows = conn.execute(query, params).fetchall()

            provider = _pubmed_provider()
            updates: list[dict[str, object]] = []
            skipped: list[dict[str, object]] = []

            for row in rows:
                record = None
                try:
                    if (row["pmid"] or "").strip():
                        record = provider.fetch_by_pmid(row["pmid"])
                    elif (row["doi"] or "").strip():
                        record = provider.fetch_by_doi(row["doi"])
                except SPCAcquisitionError as exc:
                    raise click.ClickException(str(exc)) from exc
                except Exception as exc:
                    skipped.append(
                        {
                            "paper_id": row["id"],
                            "reason": f"pubmed lookup failed: {exc}",
                        }
                    )
                    continue
                if record is None:
                    skipped.append({"paper_id": row["id"], "reason": "not found"})
                    continue
                changed = _apply_pubmed_record_update(
                    conn, row, record, dry_run=dry_run
                )
                if changed:
                    updates.append({"paper_id": row["id"], "fields": changed})
                else:
                    skipped.append({"paper_id": row["id"], "reason": "no gaps"})

            if not dry_run:
                conn.commit()
        finally:
            conn.close()

        payload = {
            "dry_run": dry_run,
            "processed": len(rows),
            "updated": len(updates),
            "skipped": len(skipped),
            "updates": updates,
            "skip_reasons": skipped,
        }
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        action = "would update" if dry_run else "updated"
        click.echo(f"PubMed backfill: {len(updates)} {action}, {len(skipped)} skipped")

    @paper.command("backfill-metadata")
    @click.option(
        "--missing",
        "missing_fields",
        default="venue,citation_count",
        help="Comma-separated fields to target",
    )
    @click.option(
        "--limit", "max_papers", type=int, default=100, help="Max papers per run"
    )
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    @click.pass_context
    def paper_backfill_metadata(
        ctx: click.Context,
        missing_fields: str,
        max_papers: int,
        dry_run: bool,
    ) -> None:
        """Batch-enrich papers missing key metadata across ALL topics.

        Scans the entire pool for papers missing the specified fields and calls
        Semantic Scholar to fill them. Rate-limited to ~1 req/sec.

        Examples:
            rh paper backfill-metadata                         # default: venue + citation_count, limit 100
            rh paper backfill-metadata --missing venue --limit 50
            rh paper backfill-metadata --dry-run
        """
        import time

        from .core.paper_pool import PaperPool

        fields = [f.strip() for f in missing_fields.split(",") if f.strip()]
        if not fields:
            raise click.ClickException("--missing must list at least one field")

        venue_placeholders = ("", "arxiv", "arxiv.org", "arxiv preprint")

        db = get_db(ctx)
        conn = db.connect()
        try:
            pool = PaperPool(conn)
            rows = conn.execute(
                "SELECT id, title, arxiv_id, doi, s2_id, venue, citation_count FROM papers ORDER BY id DESC"
            ).fetchall()

            candidates: list[tuple[int, str]] = []
            for row in rows:
                has_id = bool(
                    (row["arxiv_id"] or "").strip()
                    or (row["doi"] or "").strip()
                    or (row["s2_id"] or "").strip()
                )
                if not has_id:
                    continue
                for f in fields:
                    val = row[f] if f in row.keys() else None
                    if f == "venue" and (
                        not val or str(val).strip().lower() in venue_placeholders
                    ):
                        candidates.append((row["id"], (row["title"] or "")[:50]))
                        break
                    elif f != "venue" and (val is None or val == 0):
                        candidates.append((row["id"], (row["title"] or "")[:50]))
                        break
                if len(candidates) >= max_papers:
                    break

            click.echo(
                f"Found {len(candidates)} papers missing {', '.join(fields)} (limit {max_papers})"
            )
            if dry_run:
                for pid, title in candidates[:20]:
                    click.echo(f"  [{pid}] {title}")
                if len(candidates) > 20:
                    click.echo(f"  ... and {len(candidates) - 20} more")
                return

            enriched = 0
            failed = 0
            for i, (pid, title) in enumerate(candidates):
                try:
                    result = pool.enrich_metadata(pid)
                    if result and "error" not in result:
                        enriched += 1
                        if (i + 1) % 10 == 0:
                            click.echo(
                                f"  [{i + 1}/{len(candidates)}] enriched {enriched} so far..."
                            )
                    else:
                        failed += 1
                    time.sleep(1.05)
                except SPCAcquisitionError as exc:
                    raise click.ClickException(str(exc)) from exc
                except Exception as exc:
                    failed += 1
                    logger.debug("Backfill failed for paper %d: %s", pid, exc)

            click.echo(
                f"Done: {enriched} enriched, {failed} failed out of {len(candidates)}"
            )
        finally:
            conn.close()


def register_acquisition(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
) -> None:
    """Register PDF acquisition commands on the existing paper group."""

    @paper.command("acquire")
    @click.argument("topic_id", type=int)
    @click.option(
        "--download-dir", default=None, help="Directory to save downloaded PDFs"
    )
    @click.option(
        "--artifacts-root", default=None, help="Directory for paperindex artifacts"
    )
    @click.option(
        "--include-candidates",
        is_flag=True,
        default=False,
        help="Include unscreened provider candidates in acquisition.",
    )
    @click.pass_context
    def paper_acquire(
        ctx: click.Context,
        topic_id: int,
        download_dir: str | None,
        artifacts_root: str | None,
        include_candidates: bool,
    ) -> None:
        """Download PDFs and build paperindex annotations for a topic."""
        from .acquisition.pipeline import acquire_papers

        db = get_db(ctx)
        report = acquire_papers(
            db,
            topic_id,
            download_dir=download_dir,
            artifacts_root=artifacts_root,
            include_candidates=include_candidates,
        )

        if ctx.obj.get("json"):
            click.echo(json.dumps(report.to_dict(), ensure_ascii=False, default=str))
            return

        if report.total_papers == 0 and report.unscreened_candidates:
            click.echo(
                f"Nothing to acquire for topic {topic_id}: none of its "
                f"{report.unscreened_candidates} papers scored above the relevance floor. "
                f"Add seed papers to steer the search, widen the query, or pass "
                f"--include-candidates to take the pool as it stands."
            )
            return
        click.echo(f"Acquisition complete for topic {topic_id}:")
        click.echo(
            f"  Total: {report.total_papers}, Downloaded: {report.downloaded}, "
            f"Annotated: {report.annotated}, Needs manual: {report.needs_manual}, "
            f"Failed: {report.failed}"
        )
        if report.failure_taxonomies:
            breakdown = ", ".join(
                f"{name}={count}"
                for name, count in sorted(report.failure_taxonomies.items())
            )
            click.echo(f"  Failure breakdown: {breakdown}")
        if report.failure_taxonomies.get("no_candidate_identifier"):
            click.echo(
                "  Hint: papers without any identifier cannot be downloaded — "
                "run `rh paper enrich --topic ...` or re-ingest with DOI/arXiv/PMID."
            )
        if report.failure_taxonomies.get("no_direct_pdf_metadata"):
            click.echo(
                "  Hint: some papers only have landing-page URLs; supported routes "
                "were tried but no direct OA PDF is known. Enrich metadata or add "
                "the PDF manually."
            )
        if report.manual_list:
            click.echo(f"\n  {len(report.manual_list)} papers need manual download.")
            click.echo("  See .research-harness/manual_downloads/pending_manual.json")

    @paper.command("parse-mineru")
    @click.option("--topic", default=None, help="Topic name or ID to scope parsing")
    @click.option("--paper-id", type=int, default=None, help="Single paper id to parse")
    @click.option("--limit", type=int, default=None, help="Maximum PDFs to parse")
    @click.option(
        "--artifacts-root",
        default=None,
        show_default=False,
        help="Directory for MinerU parse artifacts (default: <state tree>/artifacts/mineru)",
    )
    @click.option(
        "--dry-run", is_flag=True, default=False, help="Preview without uploading PDFs"
    )
    @click.pass_context
    def paper_parse_mineru(
        ctx: click.Context,
        topic: str | None,
        paper_id: int | None,
        limit: int | None,
        artifacts_root: str | None,
        dry_run: bool,
    ) -> None:
        """Parse downloaded PDFs with MinerU."""
        from pathlib import Path

        from .integrations.mineru import MinerUParseItem, parse_mineru_items

        if topic and paper_id:
            raise click.ClickException("provide only one of --topic or --paper-id")
        db = get_db(ctx)
        conn = db.connect()
        try:
            params: list[object] = []
            query = "SELECT p.id, p.title, p.pdf_path FROM papers p"
            if topic:
                topic_id = _topic_id_from_name_or_id(conn, topic)
                if topic_id is None:
                    raise click.ClickException(f"Topic '{topic}' not found")
                query += (
                    " JOIN paper_topics pt ON pt.paper_id = p.id WHERE pt.topic_id = ?"
                )
                params.append(topic_id)
                query += " AND COALESCE(p.pdf_path, '') != ''"
            elif paper_id:
                query += " WHERE p.id = ? AND COALESCE(p.pdf_path, '') != ''"
                params.append(paper_id)
            else:
                query += " WHERE COALESCE(p.pdf_path, '') != ''"
            query += " ORDER BY p.id"
            if limit is not None and limit > 0:
                query += " LIMIT ?"
                params.append(limit)
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        root = (
            Path(artifacts_root)
            if artifacts_root
            else state_path("artifacts", "mineru")
        )
        items = [
            MinerUParseItem(
                paper_id=int(row["id"]),
                title=row["title"] or "",
                pdf_path=Path(row["pdf_path"] or ""),
                output_dir=root / str(row["id"]),
            )
            for row in rows
        ]
        report = parse_mineru_items(items, dry_run=dry_run)

        if not dry_run:
            conn = db.connect()
            try:
                for result in report.results:
                    pid = int(result.get("paper_id") or 0)
                    status = str(result.get("status") or "")
                    detail = json.dumps(result, ensure_ascii=False, sort_keys=True)
                    conn.execute(
                        "INSERT INTO pipeline_events (paper_id, event_type, detail, provider) VALUES (?, ?, ?, ?)",
                        (pid, f"mineru_parse_{status}", detail, "mineru"),
                    )
                    if status == "parsed":
                        conn.execute(
                            "INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata) VALUES (?, ?, ?, ?)",
                            (
                                pid,
                                "mineru_markdown",
                                str(result.get("markdown_path") or ""),
                                detail,
                            ),
                        )
                conn.commit()
            finally:
                conn.close()

        if ctx.obj.get("json"):
            click.echo(json.dumps(report.to_dict(), ensure_ascii=False, default=str))
            return
        click.echo(
            f"MinerU parse: processed={report.processed}, parsed={report.parsed}, "
            f"skipped={report.skipped}, failed={report.failed}"
        )

    @paper.command("ingest-manual")
    @click.option(
        "--manual-dir",
        default=None,
        help="Directory containing manually downloaded PDFs",
    )
    @click.option(
        "--artifacts-root", default=None, help="Directory for paperindex artifacts"
    )
    @click.pass_context
    def paper_ingest_manual(
        ctx: click.Context, manual_dir: str | None, artifacts_root: str | None
    ) -> None:
        """Ingest manually downloaded PDFs from the manual_downloads directory."""
        from .acquisition.pipeline import ingest_manual_downloads

        db = get_db(ctx)
        results = ingest_manual_downloads(
            db, manual_dir=manual_dir, artifacts_root=artifacts_root
        )

        if ctx.obj.get("json"):
            click.echo(json.dumps(results, ensure_ascii=False, default=str))
            return

        if not results:
            click.echo("No PDF files found in manual downloads directory.")
            return

        for r in results:
            status = r["status"]
            name = r.get("file", "")
            click.echo(f"  {name}: {status}")
        annotated = sum(1 for r in results if r["status"] == "annotated")
        click.echo(f"\nProcessed {len(results)} files, {annotated} annotated.")

    @paper.command("resolve-pdfs")
    @click.option("--topic", default=None, help="Topic name or ID to scope resolution")
    @click.option(
        "--dry-run", is_flag=True, help="Report matches without writing to DB"
    )
    @click.pass_context
    def paper_resolve_pdfs(
        ctx: click.Context, topic: str | None, dry_run: bool
    ) -> None:
        """Discover existing PDFs on disk and link them to papers in the DB."""
        from .acquisition.pdf_resolver import backfill_pdf_paths

        db = get_db(ctx)
        topic_id = None
        if topic:
            conn = db.connect()
            try:
                row = conn.execute(
                    "SELECT id FROM topics WHERE name = ? OR id = CAST(? AS INTEGER)",
                    (topic, topic),
                ).fetchone()
                if row:
                    topic_id = row["id"]
                else:
                    click.echo(f"Topic '{topic}' not found.", err=True)
                    return
            finally:
                conn.close()

        stats = backfill_pdf_paths(db, topic_id=topic_id, dry_run=dry_run)

        if ctx.obj.get("json"):
            click.echo(json.dumps(stats.to_dict(), ensure_ascii=False, default=str))
            return

        mode = " (DRY RUN)" if dry_run else ""
        click.echo(f"PDF Resolution{mode}:")
        click.echo(f"  Missing pdf_path: {stats.total_missing}")
        click.echo(f"  Matched:          {stats.matched}")
        click.echo(f"  Unmatched:        {stats.unmatched}")
        if stats.errors:
            click.echo(f"  Errors:           {stats.errors}")

        if stats.unmatched_papers:
            click.echo(f"\nUnmatched papers ({len(stats.unmatched_papers)}):")
            for p in stats.unmatched_papers[:20]:
                click.echo(
                    f"  [{p['paper_id']:>3}] {p['arxiv_id'] or p['doi'] or '?':20s} {p['title']}"
                )
            if len(stats.unmatched_papers) > 20:
                click.echo(f"  ... and {len(stats.unmatched_papers) - 20} more")

    @paper.command("pmc-links")
    @click.option("--topic", default=None, help="Topic name or ID to scope output")
    @click.pass_context
    def paper_pmc_links(ctx: click.Context, topic: str | None) -> None:
        """Generate PMC manual full-text download links for papers with PMCID."""

        db = get_db(ctx)
        conn = db.connect()
        try:
            params: list[object] = []
            query = """
                SELECT p.id, p.title, p.pmid, p.pmcid, p.doi, p.pdf_path
                FROM papers p
            """
            if topic:
                topic_id = _topic_id_from_name_or_id(conn, topic)
                if topic_id is None:
                    raise click.ClickException(f"Topic '{topic}' not found")
                query += (
                    " JOIN paper_topics pt ON pt.paper_id = p.id WHERE pt.topic_id = ?"
                )
                params.append(topic_id)
                query += " AND COALESCE(p.pmcid, '') != ''"
            else:
                query += " WHERE COALESCE(p.pmcid, '') != ''"
            query += " ORDER BY p.id"
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        items = []
        for row in rows:
            pmcid = _normalize_pmcid(str(row["pmcid"] or ""))
            items.append(
                {
                    "paper_id": row["id"],
                    "title": row["title"] or "",
                    "pmid": row["pmid"] or "",
                    "pmcid": pmcid,
                    "doi": row["doi"] or "",
                    "pmc_url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
                    "manual_required": not bool(row["pdf_path"]),
                    "treat_as_direct_pdf": False,
                }
            )

        payload = {"count": len(items), "items": items}
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        for item in items:
            click.echo(f"[{item['paper_id']}] {item['pmc_url']} {item['title']}")

    @paper.command("audit-pdfs")
    @click.option("--topic", default=None, help="Topic name or ID to scope audit")
    @click.pass_context
    def paper_audit_pdfs(ctx: click.Context, topic: str | None) -> None:
        """Audit whether linked PDFs match paper title, DOI, or PMID."""

        from .acquisition.pdf_audit import audit_pdf_identity

        db = get_db(ctx)
        conn = db.connect()
        try:
            params: list[object] = []
            query = """
                SELECT p.id, p.title, p.doi, p.pmid, p.arxiv_id, p.pmcid, p.pdf_path
                FROM papers p
            """
            if topic:
                topic_id = _topic_id_from_name_or_id(conn, topic)
                if topic_id is None:
                    raise click.ClickException(f"Topic '{topic}' not found")
                query += (
                    " JOIN paper_topics pt ON pt.paper_id = p.id WHERE pt.topic_id = ?"
                )
                params.append(topic_id)
                query += " AND COALESCE(p.pdf_path, '') != ''"
            else:
                query += " WHERE COALESCE(p.pdf_path, '') != ''"
            query += " ORDER BY p.id"
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        results = [
            audit_pdf_identity(
                paper_id=int(row["id"]),
                title=row["title"] or "",
                doi=row["doi"] or "",
                pmid=row["pmid"] or "",
                arxiv_id=row["arxiv_id"] or "",
                pmcid=row["pmcid"] or "",
                pdf_path=row["pdf_path"] or "",
            ).to_dict()
            for row in rows
        ]
        payload = {
            "total": len(results),
            "verified": sum(1 for item in results if item["status"] == "verified"),
            "suspect": sum(1 for item in results if item["status"] == "suspect"),
            "missing": sum(1 for item in results if item["status"] == "missing"),
            "items": results,
        }
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(
            f"PDF audit: {payload['verified']} verified, {payload['suspect']} suspect, {payload['missing']} missing"
        )

    @paper.command("import-seed-pack")
    @click.argument("pack_dir", type=click.Path())
    @click.option("--topic", "topic_id", type=int, required=True)
    @click.option("--download-dir", default=None, help="Directory to save PDFs")
    @click.option(
        "--artifacts-root", default=None, help="Directory for paperindex artifacts"
    )
    @click.option("--limit", type=int, default=None, help="Import at most N records")
    @click.option(
        "--no-annotate",
        is_flag=True,
        default=False,
        help="Skip PDF annotation after import",
    )
    @click.pass_context
    def paper_import_seed_pack(
        ctx: click.Context,
        pack_dir: str,
        topic_id: int,
        download_dir: str | None,
        artifacts_root: str | None,
        limit: int | None,
        no_annotate: bool,
    ) -> None:
        """Import a paperfetch seed pack directory into a topic."""
        from .acquisition.seed_pack_import import (
            SeedPackContractError,
            import_seed_pack,
        )

        db = get_db(ctx)
        try:
            report = import_seed_pack(
                db,
                pack_dir,
                topic_id,
                download_dir=download_dir,
                artifacts_root=artifacts_root,
                limit=limit,
                annotate=not no_annotate,
            )
        except SeedPackContractError as exc:
            raise click.ClickException(f"seed pack contract error: {exc}") from exc

        payload = report.to_dict()
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(
            f"Seed pack import: {payload['papers_seen']} papers"
            f" ({payload['papers_new']} new, {payload['papers_updated']} updated,"
            f" {payload['papers_skipped']} skipped),"
            f" {payload['pdfs_imported']} PDFs imported,"
            f" {len(payload['pdfs_rejected'])} rejected,"
            f" {payload['parse_imported']} parse artifacts,"
            f" {payload['audits_imported']} external audits"
        )

    @paper.command("export-spc-wants")
    @click.argument("topic_id", type=int)
    @click.option(
        "--output",
        default=None,
        help="Output JSON path (default: .research-harness/spc/wants-topic<id>.json)",
    )
    @click.option("--limit", type=int, default=None, help="Export at most N papers")
    @click.pass_context
    def paper_export_spc_wants(
        ctx: click.Context, topic_id: int, output: str | None, limit: int | None
    ) -> None:
        """Export papers still needing fulltext as SPC manual seeds."""
        from .acquisition.spc_bridge import export_spc_wants_list

        db = get_db(ctx)
        target = output or str(state_path("spc", f"wants-topic{topic_id}.json"))
        payload = export_spc_wants_list(db, topic_id, target, limit=limit)
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(f"Exported {payload['paper_count']} wanted papers to {target}")

    @paper.command("diagnose-acquisition")
    @click.argument("topic_id", type=int)
    @click.option(
        "--slow-threshold-ms",
        type=int,
        default=10_000,
        help="Attempts at or above this duration count as slow",
    )
    @click.pass_context
    def paper_diagnose_acquisition(
        ctx: click.Context, topic_id: int, slow_threshold_ms: int
    ) -> None:
        """Aggregate route audits into a per-topic acquisition diagnosis."""
        from .acquisition.diagnose import build_acquisition_diagnosis

        db = get_db(ctx)
        payload = build_acquisition_diagnosis(
            db, topic_id, slow_threshold_ms=slow_threshold_ms
        )
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        totals = payload["totals"]
        click.echo(
            f"Coverage: {totals['with_pdf']}/{totals['papers']} papers"
            f" ({totals['coverage_rate']:.0%})"
        )
        if payload["failure_taxonomy"]:
            ranked = sorted(payload["failure_taxonomy"].items(), key=lambda kv: -kv[1])
            click.echo(
                "Failures: " + ", ".join(f"{name}={count}" for name, count in ranked)
            )
        for item in payload["uncovered_papers"]:
            taxonomy = item["latest_failure_taxonomy"] or (
                "not attempted" if not item["attempted"] else "unknown"
            )
            click.echo(f"  missing: [{item['paper_id']}] {item['title']} ({taxonomy})")


def _topic_id_from_name_or_id(conn: Any, topic: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM topics WHERE name = ? OR id = CAST(? AS INTEGER)",
        (topic, topic),
    ).fetchone()
    return int(row["id"]) if row else None


def _normalize_pmcid(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    return clean if clean.upper().startswith("PMC") else f"PMC{clean}"


def register(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register paper ingest, metadata, and acquisition commands."""
    register_ingest(
        paper,
        get_db=get_db,
        topic_id_or_exit=topic_id_or_exit,
        echo=echo,
    )
    register_metadata(
        paper,
        get_db=get_db,
        topic_id_or_exit=topic_id_or_exit,
    )
    register_acquisition(paper, get_db=get_db)
