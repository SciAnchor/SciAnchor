"""Topic management subcommands for the RH CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click


def register_update(
    topic: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register the topic update command on the existing topic group."""

    @topic.command("update")
    @click.argument("topic_name")
    @click.option("--new-name", default=None)
    @click.option("--description", "description", default=None)
    @click.option("--venue", default=None)
    @click.option("--deadline", default=None)
    @click.option("--status", type=click.Choice(["active", "paused", "archived"]))
    @click.option(
        "--compute-location",
        "compute_location",
        default=None,
        help="Durable compute constraint, e.g. 'remote_only' (BUG-015).",
    )
    @click.option(
        "--expected-organism",
        "expected_organism",
        default=None,
        help="Declared organism, e.g. 'human'; enables cross-species gate (BUG-012).",
    )
    @click.pass_context
    def topic_update(
        ctx: click.Context,
        topic_name: str,
        new_name: str | None,
        description: str | None,
        venue: str | None,
        deadline: str | None,
        status: str | None,
        compute_location: str | None,
        expected_organism: str | None,
    ) -> None:
        """Update topic metadata."""
        if all(
            value is None
            for value in (
                new_name,
                description,
                venue,
                deadline,
                status,
                compute_location,
                expected_organism,
            )
        ):
            raise click.ClickException("Nothing to update")

        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id, name FROM topics WHERE name = ?", (topic_name,)
            ).fetchone()
            if row is None:
                raise click.ClickException(f"topic '{topic_name}' not found")

            updates: list[str] = []
            params: list[object] = []
            if new_name is not None:
                updates.append("name = ?")
                params.append(new_name)
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            if venue is not None:
                updates.append("target_venue = ?")
                params.append(venue)
            if deadline is not None:
                updates.append("deadline = ?")
                params.append(deadline)
            if status is not None:
                updates.append("status = ?")
                params.append(status)
            if compute_location is not None:
                updates.append("compute_location = ?")
                params.append(compute_location)
            if expected_organism is not None:
                updates.append("expected_organism = ?")
                params.append(expected_organism)
            params.append(row["id"])
            conn.execute(f"UPDATE topics SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            updated_name = new_name or row["name"]
        finally:
            conn.close()

        echo(
            ctx,
            {"topic": updated_name, "previous_name": topic_name, "updated": True},
            f"Topic '{topic_name}' updated",
        )

    @topic.command("summary-refresh")
    @click.argument("topic_id", type=int)
    @click.pass_context
    def topic_summary_refresh(ctx: click.Context, topic_id: int) -> None:
        """Invalidate the cached topic literature overview.

        The overview cache only refreshes when the paper count changes, so a
        rerun that keeps the pool but narrows the manuscript scope keeps
        feeding a stale field summary to consistency_check. Run this after
        scope changes; the next consumer recompiles the overview.
        """
        from ._workflow.execution.compiled_summary import invalidate_topic_summary

        db = get_db(ctx)
        deleted = invalidate_topic_summary(db, topic_id)
        echo(
            ctx,
            {"topic_id": topic_id, "cache_invalidated": deleted},
            (
                f"Topic {topic_id} summary cache invalidated"
                if deleted
                else f"Topic {topic_id} had no cached summary"
            ),
        )
