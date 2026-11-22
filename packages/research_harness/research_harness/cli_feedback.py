"""`rh feedback` — targeted reinforcement loop for finished topics (S3)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import click


def _summary(result: dict[str, Any]) -> str:
    if result.get("status") != "success":
        return f"error: {result.get('summary', 'unknown error')}"
    lines = [str(result.get("summary") or "ok")]
    for item in result.get("items") or []:
        lines.append(
            f"[{item['feedback_artifact_id']}] {item['status']} "
            f"{item['target_kind']}:{item['target'] or '(general)'} — {item['note']}"
        )
    for command in result.get("next_commands") or []:
        lines.append(f"  -> {command}")
    return "\n".join(lines)


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    echo: Callable[[click.Context, Any, str | None], None],
) -> None:
    """Register the `rh feedback` command group."""

    @main.group("feedback")
    def feedback_group() -> None:
        """Record user feedback on a topic and apply targeted reinforcement."""

    state_dir_option = click.option(
        "--state-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Override the local auto-runner state directory.",
    )

    @feedback_group.command("add")
    @click.option("--topic", required=True, help="Topic id or name.")
    @click.option(
        "--target-kind",
        required=True,
        type=click.Choice(["section", "claim", "evidence", "experiment"]),
        help="What the feedback targets.",
    )
    @click.option(
        "--target",
        default="",
        help="Target identifier (e.g. section name, claim id).",
    )
    @click.option("--note", required=True, help="The feedback itself.")
    @click.option(
        "--severity",
        default="minor",
        type=click.Choice(["minor", "major"]),
    )
    @click.pass_context
    def feedback_add_command(
        ctx: click.Context,
        topic: str,
        target_kind: str,
        target: str,
        note: str,
        severity: str,
    ) -> None:
        """Record one feedback item (reset-safe artifact; items coexist)."""
        from .auto_runner.feedback_loop import feedback_add

        result = feedback_add(
            get_db(ctx),
            topic=topic,
            target_kind=target_kind,
            target=target,
            note=note,
            severity=severity,
        )
        echo(ctx, result, _summary(result))

    @feedback_group.command("list")
    @click.option("--topic", required=True, help="Topic id or name.")
    @click.option(
        "--status",
        default="open",
        type=click.Choice(["open", "addressed", "dismissed", "all"]),
    )
    @click.pass_context
    def feedback_list_command(ctx: click.Context, topic: str, status: str) -> None:
        """List feedback items for a topic."""
        from .auto_runner.feedback_loop import feedback_list

        result = feedback_list(get_db(ctx), topic=topic, status=status)
        if result.get("status") == "success":
            result["summary"] = f"{result['count']} {status} feedback item(s)"
        echo(ctx, result, _summary(result))

    @feedback_group.command("plan")
    @click.option("--topic", required=True, help="Topic id or name.")
    @click.option(
        "--no-record",
        is_flag=True,
        default=False,
        help="Preview the plan without recording a revision_plan artifact.",
    )
    @click.pass_context
    def feedback_plan_command(ctx: click.Context, topic: str, no_record: bool) -> None:
        """Map open feedback to a revision plan (re-entry stage + invalidation set)."""
        from .auto_runner.feedback_loop import build_revision_plan

        result = build_revision_plan(get_db(ctx), topic=topic, record=not no_record)
        echo(ctx, result, _summary(result))

    @feedback_group.command("apply")
    @click.option("--topic", required=True, help="Topic id or name.")
    @click.option(
        "--plan-artifact",
        "plan_artifact_id",
        type=int,
        default=None,
        help="Apply a specific revision_plan artifact (default: latest).",
    )
    @state_dir_option
    @click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Preview what would be superseded without changing anything.",
    )
    @click.pass_context
    def feedback_apply_command(
        ctx: click.Context,
        topic: str,
        plan_artifact_id: int | None,
        state_dir: Path | None,
        dry_run: bool,
    ) -> None:
        """Apply the revision plan: scoped reset + stage re-entry + context injection."""
        from .auto_runner.feedback_loop import apply_revision_plan

        result = apply_revision_plan(
            get_db(ctx),
            topic=topic,
            plan_artifact_id=plan_artifact_id,
            base_dir=state_dir,
            dry_run=dry_run,
        )
        echo(ctx, result, _summary(result))

    @feedback_group.command("address")
    @click.option("--topic", required=True, help="Topic id or name.")
    @click.option(
        "--feedback",
        "feedback_artifact_id",
        required=True,
        type=int,
        help="Feedback artifact id to mark addressed.",
    )
    @click.option(
        "--artifact",
        "addressed_by_artifact_id",
        type=int,
        default=None,
        help="Artifact id that addresses the feedback.",
    )
    @click.option("--note", default="", help="Resolution note.")
    @state_dir_option
    @click.pass_context
    def feedback_address_command(
        ctx: click.Context,
        topic: str,
        feedback_artifact_id: int,
        addressed_by_artifact_id: int | None,
        note: str,
        state_dir: Path | None,
    ) -> None:
        """Mark a feedback item addressed (clears injected context at zero open)."""
        from .auto_runner.feedback_loop import feedback_address

        result = feedback_address(
            get_db(ctx),
            topic=topic,
            feedback_artifact_id=feedback_artifact_id,
            addressed_by_artifact_id=addressed_by_artifact_id,
            note=note,
            base_dir=state_dir,
        )
        echo(ctx, result, _summary(result))
