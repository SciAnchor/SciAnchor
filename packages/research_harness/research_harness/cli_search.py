"""Search command group for the RH CLI."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import click


def _pubmed_provider():
    from .paper_source_clients import SPCProvider

    return SPCProvider()


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register search commands on the root CLI group."""

    @main.group()
    def search() -> None:
        """Manage search history."""

    @search.command("log")
    @click.option("--topic", "topic_name", default=None)
    @click.option("--query", "-q", required=True)
    @click.option(
        "--provider", required=True, help="semantic-scholar|arxiv|dblp|refcheck"
    )
    @click.option("--result-count", type=int, default=0)
    @click.option("--ingested-count", type=int, default=0)
    @click.pass_context
    def search_log(
        ctx: click.Context,
        topic_name: str | None,
        query: str,
        provider: str,
        result_count: int,
        ingested_count: int,
    ) -> None:
        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name) if topic_name else None
            conn.execute(
                "INSERT INTO search_runs (topic_id, query, provider, result_count, ingested_count) VALUES (?, ?, ?, ?, ?)",
                (topic_id, query, provider, result_count, ingested_count),
            )
            conn.commit()
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        finally:
            conn.close()
        echo(
            ctx,
            {
                "id": run_id,
                "query": query,
                "provider": provider,
                "result_count": result_count,
                "ingested_count": ingested_count,
            },
            f"Search logged: '{query}' via {provider}",
        )

    @search.command("list")
    @click.option("--topic", "topic_name", default=None)
    @click.option("--provider", default=None)
    @click.option("--limit", type=int, default=20, show_default=True)
    @click.pass_context
    def search_list(
        ctx: click.Context, topic_name: str | None, provider: str | None, limit: int
    ) -> None:
        """List logged search runs."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            query = """
            SELECT s.*, t.name AS topic_name
            FROM search_runs s
            LEFT JOIN topics t ON s.topic_id = t.id
        """
            conditions: list[str] = []
            params: list[object] = []
            if topic_name:
                conditions.append("t.name = ?")
                params.append(topic_name)
            if provider:
                conditions.append("s.provider = ?")
                params.append(provider)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY s.created_at DESC, s.id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        payload = [dict(row) for row in rows]
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        for row in payload:
            scope = row["topic_name"] or "global"
            click.echo(
                f"[{row['id']}] {row['provider']} [{scope}] {row['query']} -> {row['result_count']} results, {row['ingested_count']} ingested"
            )

    @search.command("providers")
    @click.pass_context
    def search_providers(ctx: click.Context) -> None:
        from .paper_source_clients import provider_status_report

        payload = provider_status_report()
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        for item in payload:
            state = "enabled" if item["enabled"] else "disabled"
            ready = "ready" if item["ready"] else "not-ready"
            click.echo(f"{item['name']}: {state}/{ready} ({item['reason']})")

    @search.command("sciverse")
    @click.option(
        "--query",
        "query_text",
        default=None,
        help="Semantic query for Sciverse agentic-search",
    )
    @click.option(
        "--doc-id", default=None, help="Sciverse document id for content fetch"
    )
    @click.option("--top-k", type=int, default=3, show_default=True)
    @click.option("--offset", type=int, default=0, show_default=True)
    @click.option("--limit", type=int, default=2000, show_default=True)
    @click.pass_context
    def search_sciverse(
        ctx: click.Context,
        query_text: str | None,
        doc_id: str | None,
        top_k: int,
        offset: int,
        limit: int,
    ) -> None:
        """Search or fetch content from Sciverse."""

        if bool(query_text) == bool(doc_id):
            raise click.ClickException("provide exactly one of --query or --doc-id")
        import shutil
        import subprocess
        from .acquisition.spc_bridge import SPCAcquisitionError

        cli = shutil.which("spc")
        if not cli:
            raise click.ClickException("SPC production unavailable")
        args = [cli, "paper", "sciverse", "--output-format", "json"]
        args += (
            ["--query", query_text, "--top-k", str(top_k)]
            if query_text
            else ["--doc-id", doc_id, "--offset", str(offset), "--limit", str(limit)]
        )
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=180)
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise click.ClickException("SPC semantic retrieval: invalid_response")
            if (
                result.returncode
                or payload.get("error")
                or payload.get("status") not in (None, "completed")
            ):
                raise click.ClickException(
                    str(SPCAcquisitionError("sciverse", payload))
                )
            data = payload.get("data", payload)
            if not isinstance(data, dict):
                raise click.ClickException("SPC semantic retrieval: invalid_response")
            hits = data.get("hits", [])
            text = data.get("text", "")
            if query_text and (
                not isinstance(hits, list)
                or not all(
                    isinstance(hit, dict)
                    and any(
                        isinstance(hit.get(field), str) and hit[field].strip()
                        for field in ("title", "doc_id", "chunk")
                    )
                    for hit in hits
                )
            ):
                raise click.ClickException("SPC semantic retrieval: invalid_response")
            if (query_text and not hits) or (
                doc_id and (not isinstance(text, str) or not text.strip())
            ):
                raise click.ClickException("SPC semantic retrieval: no_results")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise click.ClickException(
                f"SPC semantic retrieval unavailable: {type(exc).__name__}"
            ) from exc
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        if query_text:
            click.echo(f"Sciverse hits: {len(hits)}")
            for hit in hits:
                title = hit.get("title") or "untitled"
                score = hit.get("score", "")
                click.echo(f"- {title} score={score}")
            return
        click.echo(text)

    @search.command("papers")
    @click.option("--query", "query_text", required=True)
    @click.option("--topic", "topic_name", default=None)
    @click.option("--limit", type=int, default=10, show_default=True)
    @click.option("--year-from", type=int, default=None)
    @click.option("--year-to", type=int, default=None)
    @click.option(
        "--log-run",
        is_flag=True,
        default=False,
        help="Record this multi-source search in search_runs",
    )
    @click.pass_context
    def search_papers(
        ctx: click.Context,
        query_text: str,
        topic_name: str | None,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        log_run: bool,
    ) -> None:
        from .paper_source_clients import available_provider_specs, build_provider_suite
        from .paper_sources import PDFResolver, SearchAggregator, SearchQuery
        from .acquisition.spc_bridge import SPCAcquisitionError

        providers = build_provider_suite()
        if not providers:
            raise click.ClickException("no search providers are configured")

        aggregator = SearchAggregator(providers)
        resolver = PDFResolver()
        query = SearchQuery(
            query=query_text,
            topic=topic_name or "",
            year_from=year_from,
            year_to=year_to,
            limit=limit,
        )
        try:
            outcome = aggregator.search(query, output_limit=limit)
        except SPCAcquisitionError as exc:
            raise click.ClickException(str(exc)) from exc
        results = outcome.results

        payload = {
            "query": query_text,
            "topic": topic_name or "",
            "provider_specs": [
                dataclasses.asdict(item) for item in available_provider_specs()
            ],
            "provider_errors": [
                dataclasses.asdict(item) for item in outcome.provider_errors
            ],
            "result_count": len(results),
            "results": [
                {
                    "title": item.title,
                    "authors": item.authors,
                    "year": item.year,
                    "venue": item.venue,
                    "abstract": item.abstract,
                    "doi": item.doi,
                    "arxiv_id": item.arxiv_id,
                    "s2_id": item.s2_id,
                    "openalex_id": item.openalex_id,
                    "openreview_id": item.openreview_id,
                    "pmid": item.pmid,
                    "pmcid": item.pmcid,
                    "url": item.url,
                    "provider": item.provider,
                    "citation_count": item.citation_count,
                    "pdf_candidates": [
                        dataclasses.asdict(candidate)
                        for candidate in resolver.plan(item)
                    ],
                }
                for item in results
            ],
        }

        if log_run:
            db = get_db(ctx)
            conn = db.connect()
            try:
                topic_id = topic_id_or_exit(conn, topic_name) if topic_name else None
                conn.execute(
                    "INSERT INTO search_runs (topic_id, query, provider, result_count, ingested_count) VALUES (?, ?, ?, ?, ?)",
                    (topic_id, query_text, "multi-source", len(results), 0),
                )
                conn.commit()
            finally:
                conn.close()

        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return

        click.echo(f"query={query_text} results={len(results)}")
        for row in payload["results"]:
            best_pdf = (
                row["pdf_candidates"][0]["source_type"]
                if row["pdf_candidates"]
                else "none"
            )
            click.echo(f"- {row['title']} ({row['provider']}) pdf={best_pdf}")

    @search.command("pubmed-screen")
    @click.option("--query", "query_text", required=True)
    @click.option("--limit", type=int, default=50, show_default=True)
    @click.option("--year-from", type=int, default=None)
    @click.option("--year-to", type=int, default=None)
    @click.pass_context
    def search_pubmed_screen(
        ctx: click.Context,
        query_text: str,
        limit: int,
        year_from: int | None,
        year_to: int | None,
    ) -> None:
        """Search PubMed and emit a medical screening table."""

        from .medical_screening import screening_row
        from .paper_sources import SearchQuery

        provider = _pubmed_provider()
        try:
            records = provider.search(
                SearchQuery(
                    query=query_text,
                    year_from=year_from,
                    year_to=year_to,
                    limit=limit,
                    per_provider_limit=limit,
                )
            )
        except Exception as exc:  # noqa: BLE001 — surface provider/network/XML-parse failures as a typed CLI error, not a stack trace
            error_payload = {
                "query": query_text,
                "count": 0,
                "rows": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
            if ctx.obj.get("json"):
                click.echo(json.dumps(error_payload, ensure_ascii=False, default=str))
            else:
                click.echo(f"PubMed search failed: {type(exc).__name__}: {exc}")
            return
        rows = [screening_row(record).to_dict() for record in records]
        payload = {"query": query_text, "count": len(rows), "rows": rows}
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(f"PubMed screening rows: {len(rows)}")
        for row in rows:
            click.echo(
                f"- PMID {row['pmid'] or '?'} | {row['priority_tier']} | {row['title']}"
            )
