"""Task command group for the RH CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import click


BUCKET_TASK_TEMPLATES: dict[str, dict[str, str]] = {
    "missing_pdf": {
        "title_template": "Attach PDF for: {title}",
        "description_template": "Paper {paper_id} has no PDF. Locate and attach the PDF file.",
        "priority": "medium",
    },
    "stale_annotations": {
        "title_template": "Refresh stale annotations for: {title}",
        "description_template": "Paper {paper_id} annotations are stale (PDF changed). Re-run annotation.",
        "priority": "high",
    },
    "missing_sections": {
        "title_template": "Annotate: {title}",
        "description_template": "Paper {paper_id} is missing annotation sections: {missing_sections}.",
        "priority": "high",
    },
    "missing_topic_note": {
        "title_template": "Draft topic note for: {title}",
        "description_template": "Paper {paper_id} has annotations but no topic note for this topic. Draft a note from the card.",
        "priority": "medium",
    },
}


def _generate_tasks_for_topic(
    conn: Any,
    topic_name: str,
    topic_id: int,
    dry_run: bool = False,
    *,
    paper_status_payload: Callable[[Any, Any], dict[str, object]],
    paper_queue_entry: Callable[..., dict[str, object]],
    check_review_ready: Callable[[Any, int], bool],
) -> dict[str, object]:
    from .core.paper_pool import PaperPool

    papers = PaperPool(conn).list_papers(topic_id=topic_id)
    proposed: list[dict[str, object]] = []
    created_count = 0
    skipped_count = 0

    for paper_obj in papers:
        status_payload = paper_status_payload(conn, paper_obj)
        entry = paper_queue_entry(
            topic_name, status_payload, conn=conn, topic_id=topic_id
        )
        bucket = entry["queue_bucket"]
        if bucket == "ready" or bucket not in BUCKET_TASK_TEMPLATES:
            continue

        template = BUCKET_TASK_TEMPLATES[bucket]
        title = template["title_template"].format(
            title=paper_obj.title[:60] if paper_obj.title else f"Paper {paper_obj.id}",
            paper_id=paper_obj.id,
            missing_sections=", ".join(entry.get("missing_sections", [])),
        )
        description = template["description_template"].format(
            paper_id=paper_obj.id,
            missing_sections=", ".join(entry.get("missing_sections", [])),
        )
        priority = template["priority"]

        existing = conn.execute(
            "SELECT id FROM tasks WHERE topic_id = ? AND paper_id = ? AND status IN ('pending', 'in_progress')",
            (topic_id, paper_obj.id),
        ).fetchone()
        if existing:
            skipped_count += 1
            continue

        task_info = {
            "paper_id": paper_obj.id,
            "title": title,
            "description": description,
            "priority": priority,
            "bucket": bucket,
        }
        proposed.append(task_info)

        if not dry_run:
            conn.execute(
                "INSERT INTO tasks (topic_id, paper_id, title, description, priority) VALUES (?, ?, ?, ?, ?)",
                (topic_id, paper_obj.id, title, description, priority),
            )
            created_count += 1

    if not dry_run:
        conn.commit()

    review_ready = check_review_ready(conn, topic_id)

    if dry_run:
        return {
            "topic": topic_name,
            "dry_run": True,
            "proposed_tasks": proposed,
            "review_ready": review_ready,
        }
    return {
        "topic": topic_name,
        "dry_run": False,
        "created_count": created_count,
        "skipped_count": skipped_count,
        "review_ready": review_ready,
    }


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
    paper_status_payload: Callable[[Any, Any], dict[str, object]],
    paper_queue_entry: Callable[..., dict[str, object]],
    check_review_ready: Callable[[Any, int], bool],
) -> None:
    """Register task commands on the root CLI group."""

    @main.group()
    def task() -> None:
        """Manage tasks."""

    @task.command("list")
    @click.option("--topic", "topic_name", default=None)
    @click.option("--status", default=None)
    @click.pass_context
    def task_list(
        ctx: click.Context,
        topic_name: str | None,
        status: str | None,
    ) -> None:
        db = get_db(ctx)
        conn = db.connect()
        try:
            query = "SELECT t.* FROM tasks t"
            joins: list[str] = []
            conditions: list[str] = []
            params: list[object] = []

            if topic_name:
                joins.append("JOIN topics tp ON t.topic_id = tp.id")
                conditions.append("tp.name = ?")
                params.append(topic_name)
            if status:
                conditions.append("t.status = ?")
                params.append(status)
            if joins:
                query += " " + " ".join(joins)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY CASE t.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, t.created_at, t.id"
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        if ctx.obj.get("json"):
            click.echo(
                json.dumps([dict(row) for row in rows], ensure_ascii=False, default=str)
            )
            return
        for row in rows:
            click.echo(
                f"[{row['id']}] [{row['status']}] [{row['priority']}] {row['title']}"
            )

    @task.command("add")
    @click.option("--topic", "topic_name", required=True)
    @click.option("--title", required=True)
    @click.option(
        "--priority", type=click.Choice(["high", "medium", "low"]), default="medium"
    )
    @click.option("--description", "-d", default="")
    @click.pass_context
    def task_add(
        ctx: click.Context,
        topic_name: str,
        title: str,
        priority: str,
        description: str,
    ) -> None:
        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
            conn.execute(
                "INSERT INTO tasks (topic_id, title, description, priority) VALUES (?, ?, ?, ?)",
                (topic_id, title, description, priority),
            )
            conn.commit()
            task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        finally:
            conn.close()
        echo(
            ctx,
            {
                "task_id": task_id,
                "title": title,
                "status": "pending",
            },
            f"Task added: id={task_id}",
        )

    @task.command("generate")
    @click.option("--topic", "topic_name", required=True)
    @click.option("--dry-run", is_flag=True, default=False)
    @click.pass_context
    def task_generate(ctx: click.Context, topic_name: str, dry_run: bool) -> None:
        """Auto-generate tasks from the paper queue for a topic."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
            result = _generate_tasks_for_topic(
                conn,
                topic_name,
                topic_id,
                dry_run=dry_run,
                paper_status_payload=paper_status_payload,
                paper_queue_entry=paper_queue_entry,
                check_review_ready=check_review_ready,
            )
        finally:
            conn.close()

        if ctx.obj.get("json"):
            click.echo(json.dumps(result, ensure_ascii=False, default=str))
            return
        if dry_run:
            click.echo(
                f"Dry run: {len(result['proposed_tasks'])} tasks would be created for topic '{topic_name}'"
            )
            for item in result["proposed_tasks"]:
                click.echo(f"  [{item['priority']}] {item['title']}")
        else:
            click.echo(
                f"Generated {result['created_count']} tasks for topic '{topic_name}' (skipped {result['skipped_count']})"
            )

    @task.command("update")
    @click.argument("task_id", type=int)
    @click.option(
        "--status", type=click.Choice(["pending", "in_progress", "done", "blocked"])
    )
    @click.option("--priority", type=click.Choice(["high", "medium", "low"]))
    @click.pass_context
    def task_update(
        ctx: click.Context, task_id: int, status: str | None, priority: str | None
    ) -> None:
        if not status and not priority:
            raise click.ClickException("Nothing to update")
        db = get_db(ctx)
        conn = db.connect()
        try:
            updates: list[str] = []
            params: list[object] = []
            if status:
                updates.append("status = ?")
                params.append(status)
            if priority:
                updates.append("priority = ?")
                params.append(priority)
            updates.append("updated_at = datetime('now')")
            params.append(task_id)
            conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
        finally:
            conn.close()
        echo(
            ctx,
            {
                "task_id": task_id,
                "status": status,
                "priority": priority,
                "updated": True,
            },
            f"Task {task_id} updated",
        )
