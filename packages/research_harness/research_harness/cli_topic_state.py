"""`rh topic state` — unified single-call topic introspection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import click


def _text_summary(result: dict[str, Any]) -> str:
    topic = result.get("topic") or {}
    next_action = result.get("next_action") or {}
    checkpoint = result.get("checkpoint") or {}
    lines: list[str] = []
    if isinstance(topic, dict) and topic.get("id") is not None:
        lines.append(
            f"topic {topic.get('id')}: {topic.get('name', '')} "
            f"[{checkpoint.get('current_stage') or '?'}/"
            f"{checkpoint.get('stage_state') or '?'}]"
        )
    else:
        lines.append("topic: not found")
    blockers = result.get("blockers") or []
    if blockers:
        lines.append("blockers: " + ", ".join(str(item) for item in blockers))
    trees = [
        tree
        for tree in result.get("state_trees") or []
        if int(tree.get("pool_db_bytes") or 0) > 0
    ]
    if len(trees) > 1:
        lines.append(f"WARNING: {len(trees)} non-empty state trees (split-brain risk)")
    lines.append(
        f"next [{next_action.get('code', '?')}]: {next_action.get('summary', '')}"
    )
    for command in next_action.get("commands") or []:
        lines.append(f"  -> {command}")
    return "\n".join(lines)


def register(
    topic: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    get_runtime_config: Callable[[click.Context], Any],
    echo: Callable[[click.Context, Any, str | None], None],
) -> None:
    """Register the `rh topic state` command."""

    @topic.command("state")
    @click.option("--topic", "topic_ref", required=True, help="Topic id or name.")
    @click.option(
        "--state-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Override the local auto-runner state directory.",
    )
    @click.pass_context
    def topic_state_command(
        ctx: click.Context,
        topic_ref: str,
        state_dir: Path | None,
    ) -> None:
        """Show the full state picture for one topic (rh.topic_state.v1)."""
        from .auto_runner.topic_state import topic_state

        result = topic_state(
            get_db(ctx),
            topic=topic_ref,
            base_dir=state_dir,
            runtime_config=get_runtime_config(ctx),
        )
        echo(ctx, result, _text_summary(result))
