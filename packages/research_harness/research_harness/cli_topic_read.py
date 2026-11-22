"""Topic read subcommands for the RH CLI."""

from __future__ import annotations

import json
from collections.abc import Callable

import click


def register(
    topic: click.Group,
    *,
    invoke_service_or_exit: Callable[
        [click.Context, str, dict[str, object] | None], object
    ],
    topic_list_payload_for_cli: Callable[
        [click.Context, object], list[dict[str, object]]
    ],
    topic_show_payload_for_cli: Callable[[click.Context, object], dict[str, object]],
) -> None:
    """Register read-only topic commands on the existing topic group."""

    @topic.command("list")
    @click.pass_context
    def topic_list(ctx: click.Context) -> None:
        service_output = invoke_service_or_exit(ctx, "topic_list", {})
        rows = topic_list_payload_for_cli(ctx, service_output)
        if ctx.obj.get("json"):
            click.echo(json.dumps(rows, ensure_ascii=False, default=str))
            return
        for row in rows:
            click.echo(f"[{row['id']}] {row['name']} ({row['status']})")

    @topic.command("show")
    @click.argument("topic_name")
    @click.pass_context
    def topic_show(ctx: click.Context, topic_name: str) -> None:
        """Show topic details."""
        service_output = invoke_service_or_exit(ctx, "topic_show", {"name": topic_name})
        payload = topic_show_payload_for_cli(ctx, service_output)
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(f"Topic: {payload['name']} (id={payload['id']})")
        click.echo(f"Description: {payload.get('description') or '-'}")
        click.echo(
            f"Venue: {payload.get('target_venue') or '-'}  "
            f"Deadline: {payload.get('deadline') or '-'}"
        )
        click.echo(
            f"Status: {payload.get('status')}  Papers: {payload.get('paper_count', 0)}"
        )


def _coverage_audit_for_cli(ctx: click.Context, topic: str) -> dict[str, object]:
    """Run the pool audit for a topic. Split out so tests can substitute it."""
    from research_harness.paper_pool_audit import audit_topic_paper_pool
    from research_harness.storage.db import Database

    runtime_config = ctx.obj["runtime_config"]
    db = Database(runtime_config.db_path)
    try:
        topic_id = int(topic)
    except ValueError as exc:
        raise click.ClickException(
            f"topic must be a numeric id for coverage diagnostics, got {topic!r}"
        ) from exc
    return audit_topic_paper_pool(db, topic_id, min_coverage_eligible=50)


def register_coverage(topic: click.Group) -> None:
    """Register the read-only coverage diagnostic command."""

    @topic.command("coverage")
    @click.argument("topic")
    @click.pass_context
    def topic_coverage(ctx: click.Context, topic: str) -> None:
        """Show coverage progress, what is blocking it, and acquisition yield.

        Answers the three questions an operator has mid-run: how far from the
        gate, blocked by what, and is fetching still buying eligible papers?
        Before this existed those answers required writing a script, so in
        practice nobody consulted them until the postmortem.
        """
        from research_harness.acquisition import yield_monitor

        audit = _coverage_audit_for_cli(ctx, topic)
        blockers = dict(audit.get("coverage_blockers") or {})
        try:
            trend = yield_monitor.yield_trend(
                int(audit.get("topic_id") or 0),
                ledger_path=yield_monitor.DEFAULT_LEDGER,
            )
        except Exception:  # noqa: BLE001 - diagnostics must not fail the command
            trend = {"snapshots": 0, "should_stop": False}

        payload = {
            "topic_id": audit.get("topic_id"),
            "coverage_blockers": blockers,
            "acquisition_yield": trend,
        }
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return

        click.echo(
            f"Coverage: {blockers.get('eligible', 0)}/{blockers.get('required', 0)} "
            f"eligible  (shortfall {blockers.get('shortfall', 0)})"
        )
        click.echo(
            f"  repairable papers    {blockers.get('repairable_papers', 0)}  "
            f"closable by repair: {blockers.get('shortfall_closable_by_repair')}"
        )
        if blockers.get("blockers"):
            click.echo("  blocked by:")
            for row in blockers["blockers"]:
                click.echo(f"    {row['blocker']:<26} {row['papers']}")
        if blockers.get("single_blocker_ranking"):
            click.echo("  one repair converts (ranked):")
            for row in blockers["single_blocker_ranking"]:
                click.echo(
                    f"    {row['blocker']:<26} {row['papers']}  "
                    f"repairable={row['repairable']}"
                )
        if trend.get("snapshots"):
            click.echo(
                f"  acquisition yield    {trend.get('snapshots')} snapshots, "
                f"{trend.get('fetched_per_eligible')} fetched per eligible"
            )
            if trend.get("should_stop"):
                click.echo(f"    STOP: {trend.get('stop_detail')}")
