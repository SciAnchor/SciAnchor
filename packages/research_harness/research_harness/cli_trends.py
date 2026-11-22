"""Domain trends command group for the RH CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
) -> None:
    """Register domain trends commands on the root CLI group."""

    @main.group()
    def trends() -> None:
        """Domain trends pipeline."""

    @trends.command("refresh")
    @click.option("--tier", default="standard", help="Tier (economy/standard/premium)")
    @click.option("--dry-run", is_flag=True, help="Print results without writing to DB")
    @click.pass_context
    def trends_refresh(ctx: click.Context, tier: str, dry_run: bool) -> None:
        """Refresh domain trends by analyzing the paper corpus."""
        from .trends import refresh_trends

        db = get_db(ctx)
        conn = db.connect()
        try:
            clusters = refresh_trends(conn, tier=tier, dry_run=dry_run)
            if dry_run:
                click.echo(f"[DRY RUN] Found {len(clusters)} trend clusters:")
            else:
                click.echo(f"Wrote {len(clusters)} trend clusters (tier={tier})")
            for i, c in enumerate(clusters):
                click.echo(
                    f"  {i + 1}. {c.name} — score={c.publishability_score:.1f}, "
                    f"velocity={c.velocity_yoy:.0f}%"
                )
        finally:
            conn.close()
