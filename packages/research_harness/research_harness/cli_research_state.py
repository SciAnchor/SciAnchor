"""Research-state command group for the RH CLI."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import click


def _research_state_summary_text(payload: dict[str, object]) -> str:
    artifact_id = int(payload.get("research_state_update_artifact_id") or 0)
    event_type = str(payload.get("event_type") or "progress")
    stage = str(payload.get("stage") or "")
    lines = [f"Research state update: {event_type} ({stage})"]
    if artifact_id > 0:
        lines.append(f"artifact_id: {artifact_id}")
    for key, label in (
        ("failure_reasons", "failures"),
        ("fix_records", "fixes"),
        ("contradictions", "contradictions"),
        ("review_feedback", "review feedback"),
        ("next_actions", "next actions"),
    ):
        value = payload.get(key)
        if isinstance(value, list) and value:
            lines.append(f"{label}: {len(value)}")
    return "\n".join(lines)


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register research-state commands on the root CLI group."""

    @main.group("research-state")
    def research_state() -> None:
        """Record durable research-state updates for later rounds."""

    @research_state.command("record")
    @click.option("--topic", "topic_name", required=True, help="Topic name")
    @click.option("--stage", required=True, help="Stage name for this state update")
    @click.option("--event-type", default="progress", help="Event class")
    @click.option("--title", default="", help="Artifact title")
    @click.option("--summary", default="", help="One-line update summary")
    @click.option("--failure", "failure_reasons", multiple=True, help="Failure reason")
    @click.option("--fix", "fix_records", multiple=True, help="Fix record")
    @click.option(
        "--contradiction", "contradictions", multiple=True, help="Contradiction"
    )
    @click.option("--review", "review_feedback", multiple=True, help="Review feedback")
    @click.option("--next-action", "next_actions", multiple=True, help="Next action")
    @click.option(
        "--record-artifact/--no-record-artifact",
        default=True,
        help="Persist the research_state_update artifact.",
    )
    @click.pass_context
    def research_state_record_cli(
        ctx: click.Context,
        topic_name: str,
        stage: str,
        event_type: str,
        title: str,
        summary: str,
        failure_reasons: tuple[str, ...],
        fix_records: tuple[str, ...],
        contradictions: tuple[str, ...],
        review_feedback: tuple[str, ...],
        next_actions: tuple[str, ...],
        record_artifact: bool,
    ) -> None:
        """Record failures, fixes, contradictions, and review feedback as research state."""
        from .execution.local import LocalBackend
        from .execution.tracked import TrackedBackend
        from .provenance import ProvenanceRecorder

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        backend = TrackedBackend(
            LocalBackend(db),
            ProvenanceRecorder(db),
            default_topic_id=topic_id,
        )
        result = backend.execute(
            "research_state_update",
            topic_id=topic_id,
            stage=stage,
            event_type=event_type,
            title=title,
            summary=summary,
            failure_reasons=list(failure_reasons),
            fix_records=list(fix_records),
            contradictions=list(contradictions),
            review_feedback=list(review_feedback),
            next_actions=list(next_actions),
            record_artifact=record_artifact,
            _stage=stage,
            _actor="cli",
            _origin="research-state",
        )
        if not result.success:
            raise click.ClickException(result.error or "research_state_update failed")
        if not dataclasses.is_dataclass(result.output):
            raise click.ClickException(
                "research_state_update returned an invalid output"
            )

        payload = dataclasses.asdict(result.output)
        echo(ctx, payload, _research_state_summary_text(payload))
