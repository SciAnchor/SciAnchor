"""Domain command group for the RH CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import click

CS_DOMAIN_SEED: list[tuple[str, str]] = [
    ("cs.AI", "Artificial Intelligence"),
    ("cs.LG", "Machine Learning"),
    ("cs.CV", "Computer Vision"),
    ("cs.CL", "Computation and Language / NLP"),
    ("cs.IR", "Information Retrieval"),
    ("cs.RO", "Robotics"),
    ("cs.CR", "Cryptography and Security"),
    ("cs.DB", "Databases"),
    ("cs.DC", "Distributed Computing"),
    ("cs.DS", "Data Structures and Algorithms"),
    ("cs.HC", "Human-Computer Interaction"),
    ("cs.PL", "Programming Languages"),
    ("cs.SE", "Software Engineering"),
    ("cs.SY", "Systems and Control"),
    ("cs.OTHER", "Other Computer Science"),
]


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register domain commands on the root CLI group."""

    @main.group()
    def domain() -> None:
        """Manage research domains."""

    @domain.command("seed")
    @click.argument("kind", type=click.Choice(["cs"]))
    @click.pass_context
    def domain_seed(ctx: click.Context, kind: str) -> None:
        """Seed a pre-defined set of domains (currently: cs → 15 arxiv CS cats)."""
        db = get_db(ctx)
        if kind != "cs":
            raise click.ClickException(f"Unknown seed kind: {kind}")
        inserted: list[str] = []
        updated: list[str] = []
        conn = db.connect()
        try:
            for name, description in CS_DOMAIN_SEED:
                existing = conn.execute(
                    "SELECT id, description FROM domains WHERE name = ?", (name,)
                ).fetchone()
                if existing is None:
                    conn.execute(
                        "INSERT INTO domains (name, description) VALUES (?, ?)",
                        (name, description),
                    )
                    inserted.append(name)
                elif not existing[1]:
                    conn.execute(
                        "UPDATE domains SET description = ? WHERE name = ?",
                        (description, name),
                    )
                    updated.append(name)
            conn.commit()
        finally:
            conn.close()
        payload = {
            "kind": kind,
            "inserted": inserted,
            "updated": updated,
            "skipped": [
                n for n, _ in CS_DOMAIN_SEED if n not in inserted and n not in updated
            ],
        }
        echo(
            ctx,
            payload,
            f"Seeded CS domains — {len(inserted)} inserted, {len(updated)} updated, "
            f"{len(payload['skipped'])} already present.",
        )

    @domain.command("init")
    @click.argument("name")
    @click.option("--description", "-d", default="")
    @click.pass_context
    def domain_init(ctx: click.Context, name: str, description: str) -> None:
        """Create a new domain."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO domains (name, description) VALUES (?, ?)",
                (name, description),
            )
            conn.commit()
            domain_id = conn.execute(
                "SELECT id FROM domains WHERE name = ?", (name,)
            ).fetchone()[0]
        finally:
            conn.close()
        echo(
            ctx,
            {"id": domain_id, "name": name, "status": "active"},
            f"Domain '{name}' created (id={domain_id})",
        )

    @domain.command("list")
    @click.pass_context
    def domain_list(ctx: click.Context) -> None:
        """List all domains with topic counts."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            rows = conn.execute(
                """
                SELECT d.*, COALESCE(tc.cnt, 0) AS topic_count
                FROM domains d
                LEFT JOIN (
                    SELECT domain_id, COUNT(*) AS cnt FROM topics WHERE domain_id IS NOT NULL GROUP BY domain_id
                ) tc ON tc.domain_id = d.id
                ORDER BY d.created_at DESC, d.id DESC
                """
            ).fetchall()
        finally:
            conn.close()
        if ctx.obj.get("json"):
            click.echo(
                json.dumps([dict(row) for row in rows], ensure_ascii=False, default=str)
            )
            return
        for row in rows:
            click.echo(
                f"[{row['id']}] {row['name']} ({row['status']}) topics={row['topic_count']}"
            )

    @domain.command("show")
    @click.argument("domain_name")
    @click.pass_context
    def domain_show(ctx: click.Context, domain_name: str) -> None:
        """Show domain details with its topics."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM domains WHERE name = ?", (domain_name,)
            ).fetchone()
            if row is None:
                raise click.ClickException(f"domain '{domain_name}' not found")
            domain_id = row["id"]
            topics = conn.execute(
                "SELECT id, name, status FROM topics WHERE domain_id = ? ORDER BY created_at",
                (domain_id,),
            ).fetchall()
        finally:
            conn.close()

        topic_list = [dict(t) for t in topics]
        payload = {**dict(row), "topics": topic_list}
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(f"Domain: {row['name']} (id={domain_id})")
        click.echo(f"Description: {row['description'] or '-'}")
        click.echo(f"Status: {row['status']}  Topics: {len(topic_list)}")
        for t in topic_list:
            click.echo(f"  [{t['id']}] {t['name']} ({t['status']})")
