"""Provenance command group for the RH CLI."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import click


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    invoke_service_or_exit: Callable[[click.Context, str, dict[str, object]], object],
    legacy_summary_payload_for_cli: Callable[
        [click.Context, int | None, str | None], dict[str, object]
    ],
    summary_payload_for_cli: Callable[[object], dict[str, object]],
    legacy_export_records_for_cli: Callable[[click.Context, int | None], list[object]],
    export_records_for_cli: Callable[[object], list[object]],
    serialize_export: Callable[[list[object], str], str],
    write_text_output: Callable[[str | None, str], None],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register provenance commands on the root CLI group."""

    @main.group()
    def provenance() -> None:
        """Provenance tracking for research operations."""

    @provenance.command("list")
    @click.option("--topic", type=int, default=None)
    @click.option("--primitive", type=str, default=None)
    @click.option("--backend", "backend_name", type=str, default=None)
    @click.option("--limit", type=int, default=20)
    @click.pass_context
    def provenance_list(
        ctx: click.Context,
        topic: int | None,
        primitive: str | None,
        backend_name: str | None,
        limit: int,
    ) -> None:
        """List provenance records."""
        from .provenance import ProvenanceRecorder

        records = ProvenanceRecorder(get_db(ctx)).list_records(
            topic_id=topic,
            primitive=primitive,
            backend=backend_name,
            limit=limit,
        )
        payload = [dataclasses.asdict(record) for record in records]
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        for record in payload:
            click.echo(
                f"[{record['id']}] {record['primitive']} via {record['backend']} success={record['success']}"
            )

    @provenance.command("summary")
    @click.option("--topic", type=int, default=None)
    @click.option("--backend", "backend_name", type=str, default=None)
    @click.pass_context
    def provenance_summary(
        ctx: click.Context, topic: int | None, backend_name: str | None
    ) -> None:
        """Show provenance statistics."""
        if backend_name:
            payload = legacy_summary_payload_for_cli(ctx, topic, backend_name)
        else:
            service_args: dict[str, object] = {}
            if topic is not None:
                service_args["topic_id"] = topic
            service_output = invoke_service_or_exit(
                ctx, "provenance_summary", service_args
            )
            payload = summary_payload_for_cli(service_output)
        echo(
            ctx,
            payload,
            f"operations={payload.get('total_operations')} "
            f"cost={payload.get('total_cost_usd')}",
        )

    @provenance.command("show")
    @click.argument("record_id", type=int)
    @click.pass_context
    def provenance_show(ctx: click.Context, record_id: int) -> None:
        """Show a single provenance record."""
        from .provenance import ProvenanceRecorder

        record = ProvenanceRecorder(get_db(ctx)).get(record_id)
        if record is None:
            raise click.ClickException(f"provenance record {record_id} not found")
        payload = dataclasses.asdict(record)
        echo(ctx, payload, f"record {record_id}: {record.primitive}")

    @provenance.command("token-report")
    @click.option("--topic", required=False, help="Filter by topic name")
    @click.pass_context
    def provenance_token_report(ctx: click.Context, topic: str | None) -> None:
        """Long-term token/cost accounting grouped by (backend, model)."""
        from .provenance import ProvenanceRecorder

        db = get_db(ctx)
        topic_id: int | None = None
        if topic:
            conn = db.connect()
            try:
                topic_id = topic_id_or_exit(conn, topic)
            finally:
                conn.close()

        rows = ProvenanceRecorder(db).token_report_by_agent(topic_id=topic_id)
        totals = {
            "calls": sum(r["calls"] for r in rows),
            "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
            "completion_tokens": sum(r["completion_tokens"] for r in rows),
            "total_tokens": sum(r["total_tokens"] for r in rows),
            "cost_usd": sum(r["cost_usd"] for r in rows),
        }
        payload = {"topic_id": topic_id, "agents": rows, "totals": totals}
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return

        if not rows:
            click.echo("No provenance records found.")
            return

        header = f"{'backend':<14} {'model':<28} {'calls':>6} {'prompt_tok':>12} {'completion_tok':>15} {'cost_usd':>11} {'per_call':>10}"
        click.echo(header)
        click.echo("-" * len(header))
        for row in rows:
            click.echo(
                f"{row['backend']:<14} {row['model_used'][:28]:<28} {row['calls']:>6} "
                f"{row['prompt_tokens']:>12} {row['completion_tokens']:>15} "
                f"{row['cost_usd']:>11.4f} {row['cost_per_call']:>10.4f}"
            )
        click.echo("-" * len(header))
        click.echo(
            f"{'TOTAL':<14} {'':<28} {totals['calls']:>6} "
            f"{totals['prompt_tokens']:>12} {totals['completion_tokens']:>15} "
            f"{totals['cost_usd']:>11.4f}"
        )

    @provenance.command("export")
    @click.option("--topic", required=False, help="Filter by topic name")
    @click.option("--format", "fmt", type=click.Choice(["json", "csv"]), default="json")
    @click.option("--output", "-o", type=click.Path(), help="Output file path")
    @click.pass_context
    def provenance_export(
        ctx: click.Context, topic: str | None, fmt: str, output: str | None
    ) -> None:
        """Export provenance records for analysis."""
        db = get_db(ctx)
        topic_id: int | None = None
        if topic:
            conn = db.connect()
            try:
                topic_id = topic_id_or_exit(conn, topic)
            finally:
                conn.close()

        if fmt == "json":
            service_args: dict[str, object] = {"format": "json"}
            if topic_id is not None:
                service_args["topic_id"] = topic_id
            service_output = invoke_service_or_exit(
                ctx, "provenance_export", service_args
            )
            records = export_records_for_cli(service_output)
        else:
            records = legacy_export_records_for_cli(ctx, topic_id)
        serialized = serialize_export(records, fmt)
        if output:
            write_text_output(output, serialized)
            if not ctx.obj.get("json"):
                click.echo(f"Exported {len(records)} provenance records to {output}")
            return
        click.echo(serialized)
