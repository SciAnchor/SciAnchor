"""BibTeX command group for the RH CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register BibTeX commands on the root CLI group."""

    @main.group()
    def bib() -> None:
        """Manage BibTeX entries."""

    @bib.command("set")
    @click.option("--paper-id", type=int, required=True)
    @click.option("--key", "bibtex_key", required=True)
    @click.option("--bibtex", required=True)
    @click.option("--source", default="")
    @click.option("--verified-by", default="")
    @click.pass_context
    def bib_set(
        ctx: click.Context,
        paper_id: int,
        bibtex_key: str,
        bibtex: str,
        source: str,
        verified_by: str,
    ) -> None:
        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if row is None:
                raise click.ClickException(f"paper {paper_id} not found")
            conn.execute(
                """
                INSERT INTO bib_entries (paper_id, bibtex_key, bibtex, source, verified_by, verified_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT (paper_id)
                DO UPDATE SET
                    bibtex_key = excluded.bibtex_key,
                    bibtex = excluded.bibtex,
                    source = excluded.source,
                    verified_by = excluded.verified_by,
                    verified_at = datetime('now')
                """,
                (paper_id, bibtex_key, bibtex, source, verified_by),
            )
            conn.commit()
            entry = conn.execute(
                "SELECT * FROM bib_entries WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        finally:
            conn.close()
        payload = dict(entry)
        echo(ctx, payload, f"BibTeX set for paper {paper_id}")

    @bib.command("show")
    @click.argument("paper_id", type=int)
    @click.pass_context
    def bib_show(ctx: click.Context, paper_id: int) -> None:
        db = get_db(ctx)
        conn = db.connect()
        try:
            entry = conn.execute(
                "SELECT * FROM bib_entries WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        finally:
            conn.close()
        if entry is None:
            raise click.ClickException(f"bib entry for paper {paper_id} not found")
        payload = dict(entry)
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(
            f"[{payload['bibtex_key']}] source={payload['source']} verified_by={payload['verified_by']}"
        )
        click.echo(payload["bibtex"])

    @bib.command("export")
    @click.option("--topic", "topic_name", required=True)
    @click.option("--output", "-o", type=click.Path(), default=None)
    @click.pass_context
    def bib_export(ctx: click.Context, topic_name: str, output: str | None) -> None:
        db = get_db(ctx)
        conn = db.connect()
        try:
            rows = conn.execute(
                """
                SELECT b.bibtex
                FROM bib_entries b
                JOIN paper_topics pt ON b.paper_id = pt.paper_id
                JOIN topics t ON pt.topic_id = t.id
                WHERE t.name = ?
                ORDER BY b.bibtex_key
                """,
                (topic_name,),
            ).fetchall()
        finally:
            conn.close()

        bib_content = "\n\n".join(row["bibtex"] for row in rows)
        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(bib_content)
            click.echo(f"Exported {len(rows)} entries to {output}")
            return
        click.echo(bib_content)
