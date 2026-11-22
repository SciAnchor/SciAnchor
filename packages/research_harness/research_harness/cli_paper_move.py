"""Paper move/bulk-update subcommands for the RH CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click


def register(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register paper move and bulk-update commands on the existing paper group."""

    @paper.command("move")
    @click.argument("paper_ids", nargs=-1, type=int, required=True)
    @click.option(
        "--from-topic", "from_topic", required=True, help="Source topic name or ID"
    )
    @click.option(
        "--to-topic", "to_topic", required=True, help="Target topic name or ID"
    )
    @click.option(
        "--relevance",
        type=click.Choice(["high", "medium", "low"]),
        default=None,
        help="Override relevance in target",
    )
    @click.pass_context
    def paper_move(
        ctx: click.Context,
        paper_ids: tuple[int, ...],
        from_topic: str,
        to_topic: str,
        relevance: str | None,
    ) -> None:
        """Move papers from one topic to another."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            from_row = conn.execute(
                "SELECT id FROM topics WHERE name = ? OR id = CAST(? AS INTEGER)",
                (from_topic, from_topic),
            ).fetchone()
            to_row = conn.execute(
                "SELECT id FROM topics WHERE name = ? OR id = CAST(? AS INTEGER)",
                (to_topic, to_topic),
            ).fetchone()
            if not from_row:
                raise click.ClickException(f"Source topic '{from_topic}' not found")
            if not to_row:
                raise click.ClickException(f"Target topic '{to_topic}' not found")
            from_id = from_row["id"]
            to_id = to_row["id"]

            moved = 0
            for pid in paper_ids:
                link = conn.execute(
                    "SELECT relevance FROM paper_topics WHERE paper_id = ? AND topic_id = ?",
                    (pid, from_id),
                ).fetchone()
                if not link:
                    click.echo(
                        f"  Paper {pid}: not in source topic, skipping", err=True
                    )
                    continue

                rel = relevance or link["relevance"] or "medium"
                conn.execute(
                    "DELETE FROM paper_topics WHERE paper_id = ? AND topic_id = ?",
                    (pid, from_id),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
                    (pid, to_id, rel),
                )
                moved += 1
            conn.commit()
        finally:
            conn.close()
        echo(
            ctx,
            {"moved": moved, "from_topic": from_topic, "to_topic": to_topic},
            f"Moved {moved}/{len(paper_ids)} papers from '{from_topic}' to '{to_topic}'",
        )

    @paper.command("bulk-update")
    @click.argument("paper_ids", nargs=-1, type=int, required=True)
    @click.option(
        "--relevance", type=click.Choice(["high", "medium", "low"]), default=None
    )
    @click.option(
        "--screening-status",
        type=click.Choice(["candidate", "screened_in", "screened_out"]),
        default=None,
    )
    @click.option("--evidence-role", default=None)
    @click.option("--manuscript-eligible", is_flag=True, default=False)
    @click.option(
        "--paper-status",
        type=click.Choice(["meta_only", "downloaded", "annotated"]),
        default=None,
    )
    @click.option(
        "--topic",
        "topic_name",
        default=None,
        help="Topic context for topic-paper updates",
    )
    @click.pass_context
    def paper_bulk_update(
        ctx: click.Context,
        paper_ids: tuple[int, ...],
        relevance: str | None,
        screening_status: str | None,
        evidence_role: str | None,
        manuscript_eligible: bool,
        paper_status: str | None,
        topic_name: str | None,
    ) -> None:
        """Bulk update topic-paper screening fields and paper status."""
        topic_updates: list[str] = []
        topic_params: list[object] = []
        if relevance is not None:
            topic_updates.append("relevance = ?")
            topic_params.append(relevance)
        if screening_status is not None:
            topic_updates.append("screening_status = ?")
            topic_params.append(screening_status)
        if evidence_role is not None:
            topic_updates.append("evidence_role = ?")
            topic_params.append(evidence_role)
        if manuscript_eligible:
            topic_updates.append("manuscript_eligible = 1")
        if not topic_updates and paper_status is None:
            raise click.ClickException(
                "nothing to update; provide at least one update option"
            )

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = None
            if topic_name:
                row = conn.execute(
                    "SELECT id FROM topics WHERE name = ? OR id = CAST(? AS INTEGER)",
                    (topic_name, topic_name),
                ).fetchone()
                if not row:
                    raise click.ClickException(f"Topic '{topic_name}' not found")
                topic_id = row["id"]

            updated = 0
            skipped_multi_topic: list[int] = []
            for pid in paper_ids:
                row_updated = False
                if topic_updates:
                    scope_topic_id = topic_id
                    if scope_topic_id is None:
                        # BUG-002: never update paper_topics without a topic
                        # scope. An unscoped UPDATE mutates this paper's
                        # screening in EVERY topic it belongs to, leaking one
                        # topic's decisions into another. Scope to the paper's
                        # sole topic; refuse (and report) when it spans several.
                        linked = [
                            int(r["topic_id"])
                            for r in conn.execute(
                                "SELECT topic_id FROM paper_topics WHERE paper_id = ?",
                                (pid,),
                            ).fetchall()
                        ]
                        if len(linked) > 1:
                            skipped_multi_topic.append(pid)
                            scope_topic_id = None
                        elif linked:
                            scope_topic_id = linked[0]
                    if scope_topic_id is not None:
                        result = conn.execute(
                            f"UPDATE paper_topics SET {', '.join(topic_updates)} "
                            "WHERE paper_id = ? AND topic_id = ?",
                            [*topic_params, pid, scope_topic_id],
                        )
                        row_updated = result.rowcount > 0
                if paper_status is not None:
                    result = conn.execute(
                        "UPDATE papers SET status = ? WHERE id = ?",
                        (paper_status, pid),
                    )
                    row_updated = row_updated or result.rowcount > 0
                if row_updated:
                    updated += 1
            conn.commit()
        finally:
            conn.close()
        payload = {
            "updated": updated,
            "relevance": relevance,
            "screening_status": screening_status,
            "evidence_role": evidence_role,
            "manuscript_eligible": manuscript_eligible or None,
            "paper_status": paper_status,
            "skipped_multi_topic": skipped_multi_topic,
        }
        summary = f"Updated {updated}/{len(paper_ids)} papers"
        if skipped_multi_topic:
            summary += (
                f"; skipped {len(skipped_multi_topic)} paper(s) linked to multiple "
                "topics — re-run with --topic to scope: "
                f"{', '.join(map(str, skipped_multi_topic))}"
            )
        echo(ctx, payload, summary)
