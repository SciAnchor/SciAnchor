"""Paper status and queue subcommands for the RH CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import click


def register(
    paper: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    paper_status_payload: Callable[[Any, Any], dict[str, object]],
    paper_queue_entry: Callable[..., dict[str, object]],
) -> None:
    """Register paper status/queue commands on the existing paper group."""

    @paper.command("status")
    @click.argument("paper_id", type=int)
    @click.pass_context
    def paper_status(ctx: click.Context, paper_id: int) -> None:
        from .core.paper_pool import PaperPool

        db = get_db(ctx)
        conn = db.connect()
        try:
            pool = PaperPool(conn)
            paper_obj = pool.get(paper_id)
            if paper_obj is None:
                raise click.ClickException(f"paper {paper_id} not found")
            payload = paper_status_payload(conn, paper_obj)
        finally:
            conn.close()

        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        paper_payload = payload["paper"]
        linked_topics = payload["linked_topics"]
        note_count = payload["topic_note_status"]["count"]
        completed_sections = payload["annotation_status"]["completed_sections"]
        missing_sections = payload["annotation_status"]["missing_sections"]
        artifact_types = payload["artifact_status"]["types"]
        click.echo(f"[{paper_payload['id']}] {paper_payload['title']}")
        click.echo(
            f"status={paper_payload['status']} "
            f"pdf={'yes' if paper_payload['pdf_path'] else 'no'} "
            f"topics={len(linked_topics)} notes={note_count}"
        )
        click.echo(
            "annotations: "
            f"{len(completed_sections)}/"
            f"{payload['annotation_status']['total_expected']} complete"
        )
        if missing_sections:
            click.echo(f"missing: {', '.join(missing_sections)}")
        if artifact_types:
            click.echo(f"artifacts: {', '.join(artifact_types)}")

    @paper.command("queue")
    @click.option("--topic", "topic_name", required=True)
    @click.option("--limit", type=int, default=None)
    @click.option("--only-actionable", is_flag=True, default=False)
    @click.pass_context
    def paper_queue(
        ctx: click.Context, topic_name: str, limit: int | None, only_actionable: bool
    ) -> None:
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
                        topic_name, status_payload, conn=conn, topic_id=topic_id
                    )
                )
        finally:
            conn.close()

        queue_items.sort(
            key=lambda item: (
                item["priority_rank"],
                -len(item["missing_sections"]),
                item["title"].lower(),
                item["paper_id"],
            )
        )
        if only_actionable:
            queue_items = [
                item for item in queue_items if item["queue_bucket"] != "ready"
            ]
        if limit is not None:
            queue_items = queue_items[:limit]

        summary = {
            "total_papers": len(queue_items),
            "actionable_papers": sum(
                1 for item in queue_items if item["queue_bucket"] != "ready"
            ),
            "by_bucket": {
                bucket: sum(1 for item in queue_items if item["queue_bucket"] == bucket)
                for bucket in [
                    "missing_pdf",
                    "stale_annotations",
                    "missing_sections",
                    "missing_card",
                    "missing_topic_note",
                    "ready",
                ]
            },
        }
        payload = {
            "topic": topic_name,
            "summary": summary,
            "papers": queue_items,
        }
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(f"Topic queue: {topic_name}")
        click.echo(
            f"papers={summary['total_papers']} "
            f"actionable={summary['actionable_papers']}"
        )
        for item in queue_items:
            click.echo(f"[{item['paper_id']}] [{item['queue_bucket']}] {item['title']}")
            click.echo(f"actions: {', '.join(item['next_actions'])}")
            if item["missing_sections"]:
                click.echo(f"missing: {', '.join(item['missing_sections'])}")
