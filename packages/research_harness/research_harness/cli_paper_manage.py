"""Paper update/link subcommands for the RH CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click


def register_update(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register the paper update command on the existing paper group."""

    @paper.command("update")
    @click.argument("paper_id", type=int)
    @click.option("--title", default=None)
    @click.option("--year", type=int, default=None)
    @click.option("--venue", default=None)
    @click.option("--pdf-path", default=None)
    @click.option("--url", default=None)
    @click.option("--status", "new_status", default=None)
    @click.pass_context
    def paper_update(
        ctx: click.Context,
        paper_id: int,
        title: str | None,
        year: int | None,
        venue: str | None,
        pdf_path: str | None,
        url: str | None,
        new_status: str | None,
    ) -> None:
        """Update fields on an existing paper."""
        updates: list[str] = []
        params: list[object] = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if year is not None:
            updates.append("year = ?")
            params.append(year)
        if venue is not None:
            updates.append("venue = ?")
            params.append(venue)
        if pdf_path is not None:
            updates.append("pdf_path = ?")
            params.append(pdf_path)
        if url is not None:
            updates.append("url = ?")
            params.append(url)
        if new_status is not None:
            updates.append("status = ?")
            params.append(new_status)
        if not updates:
            raise click.ClickException("nothing to update; provide at least one option")

        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if row is None:
                raise click.ClickException(f"paper {paper_id} not found")
            params.append(paper_id)
            conn.execute(f"UPDATE papers SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
        finally:
            conn.close()
        echo(ctx, {"paper_id": paper_id, "updated": True}, f"Paper {paper_id} updated")


def register_link(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register the paper link command on the existing paper group."""

    @paper.command("link")
    @click.argument("paper_id", type=int)
    @click.option("--topic", "topic_name", required=True)
    @click.option(
        "--relevance", type=click.Choice(["high", "medium", "low"]), default="medium"
    )
    @click.pass_context
    def paper_link(
        ctx: click.Context, paper_id: int, topic_name: str, relevance: str
    ) -> None:
        """Link a paper to a topic (or update relevance if already linked)."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if row is None:
                raise click.ClickException(f"paper {paper_id} not found")
            topic_id = topic_id_or_exit(conn, topic_name)
            conn.execute(
                """
                INSERT INTO paper_topics (paper_id, topic_id, relevance)
                VALUES (?, ?, ?)
                ON CONFLICT(paper_id, topic_id) DO UPDATE SET relevance = excluded.relevance
                """,
                (paper_id, topic_id, relevance),
            )
            conn.commit()
        finally:
            conn.close()
        echo(
            ctx,
            {
                "paper_id": paper_id,
                "topic": topic_name,
                "topic_id": topic_id,
                "relevance": relevance,
                "linked": True,
            },
            f"Paper {paper_id} linked to topic '{topic_name}' (relevance={relevance})",
        )


def register(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register paper update/link commands on the existing paper group."""
    register_update(paper, get_db=get_db, echo=echo)
    register_link(
        paper,
        get_db=get_db,
        topic_id_or_exit=topic_id_or_exit,
        echo=echo,
    )
