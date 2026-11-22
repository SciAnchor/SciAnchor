"""Rubric calibration command group for the RH CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
) -> None:
    """Register rubric calibration commands on the root CLI group."""

    @main.group()
    def calibrate() -> None:
        """Rubric threshold calibration (Youden's J on anchor corpus)."""

    @calibrate.command("run")
    @click.option("--stage", required=True, help="Stage to calibrate (e.g. analyze)")
    @click.option("--tier", default="standard", help="Tier (economy/standard/premium)")
    @click.option("--venue-tier", default="B", help="Venue tier (A/B/workshop)")
    @click.option(
        "--dry-run", is_flag=True, help="Print recommendation without writing"
    )
    @click.pass_context
    def calibrate_run(
        ctx: click.Context,
        stage: str,
        tier: str,
        venue_tier: str,
        dry_run: bool,
    ) -> None:
        """Run rubric calibration for a stage+tier and write the threshold."""
        from .calibration import calibrate_stage_tier, load_anchors

        anchors = load_anchors()
        matching = [a for a in anchors if a.stage == stage and a.tier == tier]
        click.echo(f"Stage: {stage}, Tier: {tier}, Venue: {venue_tier}")
        click.echo(f"Anchor corpus: {len(matching)} entries for this (stage, tier)")

        if dry_run:
            from .calibration.roc import youdens_j_threshold
            from .calibration.runner import _score_anchor
            from .rubrics import get_threshold

            if not matching:
                click.echo("No anchors — dry-run would fall back to default threshold.")
                click.echo(
                    f"Default threshold (venue {venue_tier}): {get_threshold(venue_tier)}"
                )
                return
            pos = [_score_anchor(a) for a in matching if a.label == "accept"]
            neg = [_score_anchor(a) for a in matching if a.label == "reject"]
            th, fr, rr = youdens_j_threshold(pos, neg, get_threshold(venue_tier))
            click.echo(
                f"[DRY RUN] threshold={th} false_rollback={fr:.2%} reject_rate={rr:.2%}"
            )
            return

        db = get_db(ctx)
        conn = db.connect()
        try:
            result = calibrate_stage_tier(
                conn, stage, tier, anchors=anchors, venue_tier=venue_tier
            )
        finally:
            conn.close()
        click.echo(
            f"Wrote: threshold={result.threshold} "
            f"anchors={result.anchor_count} "
            f"false_rollback={result.false_rollback_rate:.2%} "
            f"reject_rate={result.reject_rate:.2%}"
            + (" (default — no anchors)" if result.used_default else "")
        )

    @calibrate.command("all")
    @click.pass_context
    def calibrate_all_cmd(ctx: click.Context) -> None:
        """Calibrate every (stage × tier) pair using the bundled anchor corpus."""
        from .calibration import calibrate_all

        db = get_db(ctx)
        conn = db.connect()
        try:
            results = calibrate_all(conn)
        finally:
            conn.close()

        click.echo(f"Calibrated {len(results)} (stage, tier) pairs:")
        for r in results:
            suffix = " (default)" if r.used_default else ""
            click.echo(
                f"  {r.stage}/{r.tier}: threshold={r.threshold} anchors={r.anchor_count}"
                f" fr={r.false_rollback_rate:.2%} rr={r.reject_rate:.2%}{suffix}"
            )

    @calibrate.command("list")
    @click.pass_context
    def calibrate_list(ctx: click.Context) -> None:
        """List current calibration state from rubric_calibrations."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT stage, tier, threshold, anchor_count, false_rollback_rate,"
                " reject_rate, calibrated_at FROM rubric_calibrations"
                " ORDER BY stage, tier"
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            click.echo("No calibrations recorded. Run `rh calibrate all` to seed them.")
            return
        for r in rows:
            click.echo(
                f"{r['stage']}/{r['tier']}: threshold={r['threshold']}"
                f" anchors={r['anchor_count']} calibrated_at={r['calibrated_at']}"
            )
