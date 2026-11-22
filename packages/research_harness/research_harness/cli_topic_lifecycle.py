"""Topic lifecycle subcommands for the RH CLI."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from .topic_workspace import materialize_topic_workspace

DOMAIN_ALIASES: dict[str, tuple[str, str]] = {
    "ai": ("cs.AI", "Artificial Intelligence"),
    "artificial-intelligence": ("cs.AI", "Artificial Intelligence"),
    "artificial intelligence": ("cs.AI", "Artificial Intelligence"),
    "ml": ("cs.LG", "Machine Learning"),
    "machine-learning": ("cs.LG", "Machine Learning"),
    "machine learning": ("cs.LG", "Machine Learning"),
    "stem": ("cs.AI", "Artificial Intelligence"),
}


def _resolve_or_create_domain_id(conn: Any, domain_name: str) -> int:
    row = conn.execute(
        "SELECT id FROM domains WHERE name = ?", (domain_name,)
    ).fetchone()
    if row:
        return int(row[0])

    canonical, description = DOMAIN_ALIASES.get(
        domain_name.strip().lower(), (domain_name, "")
    )
    row = conn.execute("SELECT id FROM domains WHERE name = ?", (canonical,)).fetchone()
    if row:
        return int(row[0])

    conn.execute(
        "INSERT INTO domains (name, description) VALUES (?, ?)",
        (canonical, description),
    )
    row = conn.execute("SELECT id FROM domains WHERE name = ?", (canonical,)).fetchone()
    if row is None:  # pragma: no cover - defensive database invariant
        raise click.ClickException(f"domain '{domain_name}' could not be created")
    return int(row[0])


def _materialize_topic_workspace_for_cli(
    ctx: click.Context,
    *,
    get_runtime_config: Callable[[click.Context], Any],
    topic_id: int,
    name: str,
    description: str,
    venue: str,
    deadline: str,
    workspace_root: str | Path | None = None,
    workspace_domain: str | None = None,
    slug: str | None = None,
) -> dict[str, object]:
    runtime_config = get_runtime_config(ctx)
    result = materialize_topic_workspace(
        workspace_root=workspace_root or runtime_config.research_workspace_root,
        topic_id=topic_id,
        topic_name=name,
        description=description,
        target_venue=venue,
        deadline=deadline,
        db_path=runtime_config.db_path,
        workspace_domain=workspace_domain,
        slug=slug,
    )
    if result is None:
        return {"workspace_path": None, "workspace_status": "not_configured"}
    return {
        "workspace_path": str(result.workspace_path),
        "workspace_status": "materialized",
        "workspace_created_files": [str(path) for path in result.created_files],
        "workspace_created_directories": [
            str(path) for path in result.created_directories
        ],
    }


def register_init_workspace(
    topic: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    get_runtime_config: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register topic creation and workspace materialization commands."""

    @topic.command("init")
    @click.argument("name")
    @click.option("--description", "-d", default="")
    @click.option("--venue", default="")
    @click.option("--deadline", default="")
    @click.option("--domain", "domain_name", default=None, help="Assign to a domain")
    @click.pass_context
    def topic_init(
        ctx: click.Context,
        name: str,
        description: str,
        venue: str,
        deadline: str,
        domain_name: str | None,
    ) -> None:
        db = get_db(ctx)
        conn = db.connect()
        try:
            domain_id: int | None = None
            if domain_name:
                domain_id = _resolve_or_create_domain_id(conn, domain_name)
            conn.execute(
                """
                INSERT INTO topics
                    (name, description, target_venue, deadline, domain_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, description, venue, deadline, domain_id),
            )
            conn.commit()
            topic_id = conn.execute(
                "SELECT id FROM topics WHERE name = ?", (name,)
            ).fetchone()[0]
        finally:
            conn.close()
        workspace_payload = _materialize_topic_workspace_for_cli(
            ctx,
            get_runtime_config=get_runtime_config,
            topic_id=int(topic_id),
            name=name,
            description=description,
            venue=venue,
            deadline=deadline,
            workspace_domain=domain_name,
        )
        echo(
            ctx,
            {
                "id": topic_id,
                "name": name,
                "status": "created",
                "domain_id": domain_id,
                **workspace_payload,
            },
            f"Topic '{name}' created (id={topic_id})",
        )

    @topic.command("workspace")
    @click.argument("topic_name")
    @click.option(
        "--workspace-root",
        default=None,
        help="Override the configured rh-workspace root.",
    )
    @click.option(
        "--workspace-domain",
        default=None,
        help="Optional rh-workspace domain directory, e.g. auto-academic.",
    )
    @click.option("--slug", default=None, help="Optional topic directory slug.")
    @click.pass_context
    def topic_workspace(
        ctx: click.Context,
        topic_name: str,
        workspace_root: str | None,
        workspace_domain: str | None,
        slug: str | None,
    ) -> None:
        """Materialize or refresh the rh-workspace directory for an existing topic."""
        db = get_db(ctx)
        conn = db.connect()
        try:
            row = conn.execute(
                """
                SELECT t.*, d.name AS domain_name
                FROM topics t
                LEFT JOIN domains d ON d.id = t.domain_id
                WHERE t.name = ?
                """,
                (topic_name,),
            ).fetchone()
            if row is None:
                raise click.ClickException(f"topic '{topic_name}' not found")
            topic_id = int(row["id"])
            name = str(row["name"])
            description = str(row["description"] or "")
            venue = str(row["target_venue"] or "")
            deadline = str(row["deadline"] or "")
            default_domain = str(row["domain_name"] or "") or None
        finally:
            conn.close()

        workspace_payload = _materialize_topic_workspace_for_cli(
            ctx,
            get_runtime_config=get_runtime_config,
            topic_id=topic_id,
            name=name,
            description=description,
            venue=venue,
            deadline=deadline,
            workspace_root=workspace_root,
            workspace_domain=workspace_domain or default_domain,
            slug=slug,
        )
        if workspace_payload["workspace_path"] is None:
            raise click.ClickException(
                "No rh-workspace root configured. Set "
                "RESEARCH_HARNESS_WORKSPACE_ROOT or pass --workspace-root."
            )
        payload = {
            "id": topic_id,
            "name": name,
            "status": "workspace_materialized",
            **workspace_payload,
        }
        echo(
            ctx,
            payload,
            f"Topic workspace: {workspace_payload['workspace_path']}",
        )


def register_export(
    topic: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    write_text_output: Callable[[str | None, str], None],
) -> None:
    """Register the topic export command on the existing topic group."""

    @topic.command("export")
    @click.argument("name")
    @click.option("--output", "-o", type=click.Path(), help="Output file path")
    @click.pass_context
    def topic_export(ctx: click.Context, name: str, output: str | None) -> None:
        """Export a topic's full state as JSON."""
        from .core.paper_pool import PaperPool
        from .provenance import ProvenanceRecorder

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_row = conn.execute(
                "SELECT * FROM topics WHERE name = ?", (name,)
            ).fetchone()
            if topic_row is None:
                raise click.ClickException(f"topic '{name}' not found")
            topic_id = int(topic_row["id"])

            pool = PaperPool(conn)
            papers = [
                dataclasses.asdict(item) for item in pool.list_papers(topic_id=topic_id)
            ]
            tasks = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM tasks WHERE topic_id = ? ORDER BY created_at, id",
                    (topic_id,),
                ).fetchall()
            ]

            orchestrator_runs = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM orchestrator_runs
                    WHERE topic_id = ?
                    ORDER BY created_at
                    """,
                    (topic_id,),
                ).fetchall()
            ]

            orchestrator_artifacts = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM project_artifacts
                    WHERE topic_id = ?
                    ORDER BY created_at
                    """,
                    (topic_id,),
                ).fetchall()
            ]

            provenance = [
                dataclasses.asdict(item)
                for item in ProvenanceRecorder(db).list_records(
                    topic_id=topic_id, limit=10000
                )
            ]
        finally:
            conn.close()

        payload = {
            "topic": dict(topic_row),
            "papers": papers,
            "claims": [],
            "tasks": tasks,
            "orchestrator_runs": orchestrator_runs,
            "orchestrator_artifacts": orchestrator_artifacts,
            "provenance": provenance,
        }
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        if output:
            write_text_output(output, serialized)
            if not ctx.obj.get("json"):
                click.echo(f"Exported topic '{name}' to {output}")
            return
        click.echo(serialized)
