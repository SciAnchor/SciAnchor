"""Late topic extras subcommands for the RH CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import click


def register(
    topic: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register late topic extras on the existing topic group."""

    @topic.command("stats")
    @click.argument("topic_name")
    @click.pass_context
    def topic_stats(ctx: click.Context, topic_name: str) -> None:
        """Show distribution statistics for a topic (venue, year, status, relevance)."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id, name FROM topics WHERE name = ? OR id = CAST(? AS INTEGER)",
                (topic_name, topic_name),
            ).fetchone()
            if not row:
                raise click.ClickException(f"Topic '{topic_name}' not found")
            tid = row["id"]
            tname = row["name"]

            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM paper_topics WHERE topic_id = ?",
                (tid,),
            ).fetchone()["cnt"]

            venue_dist = conn.execute(
                """
                SELECT COALESCE(p.venue, '(unknown)') as venue, COUNT(*) as cnt
                FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                GROUP BY venue ORDER BY cnt DESC LIMIT 15
                """,
                (tid,),
            ).fetchall()

            year_dist = conn.execute(
                """
                SELECT COALESCE(p.year, 0) as year, COUNT(*) as cnt
                FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                GROUP BY year ORDER BY year DESC
                """,
                (tid,),
            ).fetchall()

            status_dist = conn.execute(
                """
                SELECT COALESCE(p.status, 'unknown') as status, COUNT(*) as cnt
                FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                GROUP BY status ORDER BY cnt DESC
                """,
                (tid,),
            ).fetchall()

            relevance_dist = conn.execute(
                """
                SELECT COALESCE(pt.relevance, 'unset') as relevance, COUNT(*) as cnt
                FROM paper_topics pt
                WHERE pt.topic_id = ?
                GROUP BY relevance ORDER BY cnt DESC
                """,
                (tid,),
            ).fetchall()

            survey_count = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM topic_paper_notes
                WHERE topic_id = ? AND note_type = 'survey_flag'
                """,
                (tid,),
            ).fetchone()["cnt"]

        finally:
            conn.close()

        result = {
            "topic": tname,
            "total_papers": total,
            "surveys": survey_count,
            "venue": {r["venue"]: r["cnt"] for r in venue_dist},
            "year": {r["year"]: r["cnt"] for r in year_dist},
            "status": {r["status"]: r["cnt"] for r in status_dist},
            "relevance": {r["relevance"]: r["cnt"] for r in relevance_dist},
        }

        if ctx.obj.get("json"):
            click.echo(json.dumps(result, ensure_ascii=False, default=str))
            return

        click.echo(f"Topic: {tname} ({total} papers, {survey_count} surveys)")
        click.echo()

        click.echo("Venue distribution:")
        for r in venue_dist:
            click.echo(f"  {r['venue']:40s} {r['cnt']:>4d}")
        click.echo()

        click.echo("Year distribution:")
        for r in year_dist:
            yr = r["year"] if r["year"] else "unknown"
            click.echo(f"  {yr!s:10s} {r['cnt']:>4d}")
        click.echo()

        click.echo("Status distribution:")
        for r in status_dist:
            click.echo(f"  {r['status']:15s} {r['cnt']:>4d}")
        click.echo()

        click.echo("Relevance distribution:")
        for r in relevance_dist:
            click.echo(f"  {r['relevance']:10s} {r['cnt']:>4d}")

    @topic.command("get-contributions")
    @click.argument("topic_name")
    @click.pass_context
    def topic_get_contributions(ctx: click.Context, topic_name: str) -> None:
        """Read the contributions text for a topic."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id, contributions FROM topics WHERE name = ?", (topic_name,)
            ).fetchone()
            if row is None:
                raise click.ClickException(f"topic '{topic_name}' not found")
        finally:
            conn.close()
        contributions = row["contributions"] or ""
        echo(
            ctx,
            {"topic": topic_name, "contributions": contributions},
            contributions if contributions else "(no contributions set)",
        )

    @topic.command("set-contributions")
    @click.argument("topic_name")
    @click.argument("text")
    @click.pass_context
    def topic_set_contributions(ctx: click.Context, topic_name: str, text: str) -> None:
        """Write the contributions text for a topic."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id FROM topics WHERE name = ?", (topic_name,)
            ).fetchone()
            if row is None:
                raise click.ClickException(f"topic '{topic_name}' not found")
            conn.execute(
                "UPDATE topics SET contributions = ? WHERE id = ?", (text, row["id"])
            )
            conn.commit()
        finally:
            conn.close()
        echo(
            ctx,
            {"topic": topic_name, "contributions": text, "updated": True},
            f"Contributions updated for topic '{topic_name}'",
        )
