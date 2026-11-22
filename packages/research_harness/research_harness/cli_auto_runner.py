"""Auto-runner command group for the RH CLI."""

from __future__ import annotations

from collections.abc import Callable

import click


def register(
    main: click.Group,
    *,
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register autonomous workflow runner commands on the root CLI group."""

    @main.group("auto-runner")
    def auto_runner_group() -> None:
        """Autonomous research workflow runner."""

    @auto_runner_group.command("start")
    @click.option("--topic-id", type=int, required=True, help="Topic ID")
    @click.option(
        "--direction", type=str, default="", help="Research direction description"
    )
    @click.option(
        "--mode",
        type=click.Choice(["explore", "standard", "strict", "demo"]),
        default="standard",
    )
    @click.option(
        "--session-command",
        type=str,
        default="claude-kimi",
        help="Session command (e.g. claude-kimi)",
    )
    @click.option(
        "--auto-approve",
        is_flag=True,
        default=False,
        help="Auto-approve human checkpoints (demo mode)",
    )
    @click.option(
        "--dry-run", is_flag=True, default=False, help="Show plan without executing"
    )
    @click.pass_context
    def auto_runner_start(
        ctx: click.Context,
        topic_id: int,
        direction: str,
        mode: str,
        session_command: str,
        auto_approve: bool,
        dry_run: bool,
    ) -> None:
        """Start a new autonomous workflow run."""
        from .auto_runner.runner import run_topic

        result = run_topic(
            topic_id,
            direction=direction,
            mode=mode,
            session_command=session_command.split(),
            auto_approve=auto_approve,
            dry_run=dry_run,
        )
        echo(ctx, result, result.get("summary", ""))

    @auto_runner_group.command("resume")
    @click.option("--topic-id", type=int, required=True, help="Topic ID")
    @click.option("--auto-approve", is_flag=True, default=False)
    @click.pass_context
    def auto_runner_resume(
        ctx: click.Context, topic_id: int, auto_approve: bool
    ) -> None:
        """Resume a paused workflow from checkpoint."""
        from .auto_runner.runner import resume_topic

        result = resume_topic(topic_id, auto_approve=auto_approve)
        echo(ctx, result, result.get("summary", ""))

    @auto_runner_group.command("status")
    @click.option("--topic-id", type=int, required=True, help="Topic ID")
    @click.pass_context
    def auto_runner_status(ctx: click.Context, topic_id: int) -> None:
        """Show current workflow status."""
        from .auto_runner.runner import get_status

        result = get_status(topic_id)
        echo(
            ctx,
            result,
            f"{result.get('current_stage', '?')} [{result.get('stage_state', '?')}]",
        )
