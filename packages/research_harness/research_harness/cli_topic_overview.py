"""Topic overview subcommand for the RH CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import click


def register(
    topic: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[..., int],
    paper_status_payload: Callable[..., dict[str, object]],
    paper_queue_entry: Callable[..., dict[str, object]],
    check_review_ready: Callable[[Any, int], bool],
) -> None:
    """Register the topic overview command on the existing topic group."""

    @topic.command("overview")
    @click.argument("topic_name")
    @click.pass_context
    def topic_overview(ctx: click.Context, topic_name: str) -> None:
        """Show a summary of topic progress: papers, queue, tasks, orchestrator."""
        from .core.paper_pool import PaperPool

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
            papers = PaperPool(conn).list_papers(topic_id=topic_id)
            queue_items = []
            for paper_obj in papers:
                status_payload = paper_status_payload(conn, paper_obj)
                queue_items.append(
                    paper_queue_entry(
                        topic_name,
                        status_payload,
                        conn=conn,
                        topic_id=topic_id,
                    )
                )

            bucket_counts: dict[str, int] = {}
            for item in queue_items:
                bucket = str(item["queue_bucket"])
                bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

            tasks = conn.execute(
                """
                SELECT status, COUNT(*) as cnt
                FROM tasks
                WHERE topic_id = ?
                GROUP BY status
                """,
                (topic_id,),
            ).fetchall()
            task_summary = {row["status"]: row["cnt"] for row in tasks}
            task_total = sum(task_summary.values())

            orchestrator_run = conn.execute(
                """
                SELECT id, current_stage, stage_status, mode, created_at
                FROM orchestrator_runs
                WHERE topic_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            orchestrator_info = dict(orchestrator_run) if orchestrator_run else None

            review_ready = check_review_ready(conn, topic_id)
        finally:
            conn.close()

        payload = {
            "topic": topic_name,
            "topic_id": topic_id,
            "paper_count": len(papers),
            "queue_summary": {
                "by_bucket": bucket_counts,
                "actionable": sum(v for k, v in bucket_counts.items() if k != "ready"),
                "ready": bucket_counts.get("ready", 0),
            },
            "task_summary": {
                "total": task_total,
                "by_status": task_summary,
            },
            "orchestrator": orchestrator_info,
            "review_ready": review_ready,
        }

        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return

        click.echo(f"Topic: {topic_name}")
        click.echo(
            f"Papers: {len(papers)} total, "
            f"{payload['queue_summary']['actionable']} actionable, "
            f"{payload['queue_summary']['ready']} ready"
        )
        if bucket_counts:
            parts = [f"{k}={v}" for k, v in sorted(bucket_counts.items())]
            click.echo(f"  Queue: {', '.join(parts)}")
        click.echo(
            (
                "Tasks: "
                f"{task_total} total "
                f"({', '.join(f'{k}={v}' for k, v in sorted(task_summary.items()))})"
            )
            if task_summary
            else "Tasks: 0"
        )
        if orchestrator_info:
            click.echo(
                "Orchestrator: "
                f"stage={orchestrator_info['current_stage']} "
                f"status={orchestrator_info['stage_status']} "
                f"mode={orchestrator_info['mode']}"
            )
        else:
            click.echo("Orchestrator: no run")
        if payload["review_ready"]:
            click.echo("All tasks done. Ready for gate review.")
