"""Zotero command group for the RH CLI."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import click


def _echo_zotero_push_result(result: Any, *, topic_name: str, dry_run: bool) -> None:
    if dry_run:
        click.echo(
            f"Would sync {result.planned_count} papers "
            f"from topic '{topic_name}' to Zotero"
        )
        for record in result.records:
            marker = "deep" if record["deep_read"] else "todo"
            click.echo(f"- [{record['paper_id']}] {marker} {record['title'][:80]}")
        return
    click.echo(
        f"Synced topic '{topic_name}' to Zotero: "
        f"{result.synced_count} changed, {result.skipped_count} unchanged"
    )
    for paper in result.papers:
        click.echo(
            f"- [{paper.paper_id}] {paper.action}: "
            f"{paper.title[:80]} ({paper.zotero_item_key})"
        )


def _echo_zotero_pull_result(result: Any, *, topic_name: str, dry_run: bool) -> None:
    verb = "Would import" if dry_run else "Imported"
    click.echo(
        f"{verb} {result.planned_count if dry_run else result.imported_count} "
        f"Zotero reading records for topic '{topic_name}' "
        f"({result.skipped_count} skipped)"
    )
    for item in result.items:
        click.echo(
            f"- [{item.paper_id}] {item.action}: "
            f"{item.zotero_child_key} -> {item.target_table or 'preview'}"
        )


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
) -> None:
    """Register Zotero commands on the root CLI group."""

    @main.group()
    def zotero() -> None:
        """Sync Research Harness topics with Zotero."""

    @zotero.command("sync")
    @click.option("--topic", "topic_name", required=True, help="RH topic name to sync")
    @click.option(
        "--root-collection",
        default="Research Harness",
        show_default=True,
        help="Top-level Zotero collection for RH-managed topics",
    )
    @click.option("--library-id", default=None, help="Zotero user/group library ID")
    @click.option(
        "--library-type",
        type=click.Choice(["user", "group"]),
        default="user",
        show_default=True,
    )
    @click.option(
        "--api-key",
        default=None,
        help="Zotero API key with write access; defaults to ZOTERO_API_KEY",
    )
    @click.option(
        "--api-base",
        default=None,
        help="Override Zotero API base URL; defaults to https://api.zotero.org",
    )
    @click.option(
        "--adapter",
        type=click.Choice(["web", "connector"]),
        default=None,
        help="Zotero adapter: web API or local desktop connector",
    )
    @click.option(
        "--connector-url",
        default=None,
        help="Local Zotero Connector URL; defaults to http://127.0.0.1:23119",
    )
    @click.option(
        "--zotero-db-path",
        default=None,
        help="Local Zotero zotero.sqlite path for connector read-after-write lookup",
    )
    @click.option(
        "--topic-collection",
        "topic_collection_name",
        default=None,
        help="Display name for the Zotero topic collection; defaults to RH topic name",
    )
    @click.option(
        "--direction",
        type=click.Choice(["push", "pull", "both"]),
        default="push",
        show_default=True,
        help="Sync direction: RH to Zotero, Zotero to RH, or both",
    )
    @click.option("--limit", type=int, default=None, help="Sync at most N papers")
    @click.option(
        "--skip-notes",
        is_flag=True,
        default=False,
        help="Do not create/update RH child notes",
    )
    @click.option(
        "--force",
        is_flag=True,
        default=False,
        help="Update Zotero even if the RH content hash is unchanged",
    )
    @click.option(
        "--include-rh-generated",
        is_flag=True,
        default=False,
        help="When pulling, also import RH-generated Zotero notes",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Preview without mutating RH/Zotero; pull previews still read Zotero",
    )
    @click.pass_context
    def zotero_sync(
        ctx: click.Context,
        topic_name: str,
        root_collection: str,
        library_id: str | None,
        library_type: str,
        api_key: str | None,
        api_base: str | None,
        adapter: str | None,
        connector_url: str | None,
        zotero_db_path: str | None,
        topic_collection_name: str | None,
        direction: str,
        limit: int | None,
        skip_notes: bool,
        force: bool,
        include_rh_generated: bool,
        dry_run: bool,
    ) -> None:
        """Synchronize RH papers/notes and Zotero reading records.

        ``--direction push`` sends RH papers/deep-read notes to Zotero.
        ``--direction pull`` imports Zotero user notes/PDF annotations back into RH.
        ``--direction both`` runs push first, then pull.
        """
        from . import zotero_resource
        from .zotero_sync import ZoteroSyncService

        db = get_db(ctx)
        effective_adapter = adapter or os.getenv("ZOTERO_ADAPTER", "web")
        effective_library_id = library_id or (
            "local"
            if effective_adapter in {"connector", "local", "desktop"}
            else os.getenv("ZOTERO_LIBRARY_ID", "")
        )
        client = None
        needs_zotero_client = (not dry_run) or direction in {"pull", "both"}
        if needs_zotero_client:
            client = zotero_resource.create_zotero_resource(
                adapter=effective_adapter,
                library_id=effective_library_id,
                library_type=library_type or os.getenv("ZOTERO_LIBRARY_TYPE", "user"),
                api_key=api_key or os.getenv("ZOTERO_API_KEY", ""),
                base_url=api_base or os.getenv("ZOTERO_API_BASE", ""),
                connector_url=connector_url or os.getenv("ZOTERO_CONNECTOR_URL", ""),
                db_path=zotero_db_path or os.getenv("ZOTERO_DB_PATH", ""),
            )

        service = ZoteroSyncService(
            db_path=db.path,
            client=client,
            library_id=effective_library_id,
            library_type=library_type,
        )
        push_result = None
        pull_result = None
        if direction in {"push", "both"}:
            push_result = service.sync_topic(
                topic_name,
                root_collection=root_collection,
                topic_collection_name=topic_collection_name,
                include_notes=not skip_notes,
                dry_run=dry_run,
                limit=limit,
                force=force,
            )
        if direction in {"pull", "both"}:
            pull_result = service.pull_topic(
                topic_name,
                dry_run=dry_run,
                limit=limit,
                include_rh_generated=include_rh_generated,
            )

        if ctx.obj.get("json"):
            if direction == "push":
                payload = push_result.to_dict() if push_result is not None else {}
            elif direction == "pull":
                payload = pull_result.to_dict() if pull_result is not None else {}
            else:
                payload = {
                    "topic": topic_name,
                    "direction": direction,
                    "dry_run": dry_run,
                    "push": push_result.to_dict() if push_result is not None else None,
                    "pull": pull_result.to_dict() if pull_result is not None else None,
                }
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        if push_result is not None:
            _echo_zotero_push_result(
                push_result, topic_name=topic_name, dry_run=dry_run
            )
        if pull_result is not None:
            _echo_zotero_pull_result(
                pull_result, topic_name=topic_name, dry_run=dry_run
            )

    zotero.add_command(zotero_sync, "push")

    @zotero.command("pull")
    @click.option(
        "--topic", "topic_name", required=True, help="RH topic name to pull into"
    )
    @click.option("--library-id", default=None, help="Zotero user/group library ID")
    @click.option(
        "--library-type",
        type=click.Choice(["user", "group"]),
        default="user",
        show_default=True,
    )
    @click.option(
        "--api-key",
        default=None,
        help="Zotero API key with read access; defaults to ZOTERO_API_KEY",
    )
    @click.option(
        "--api-base",
        default=None,
        help="Override Zotero API base URL; defaults to https://api.zotero.org",
    )
    @click.option(
        "--limit", type=int, default=None, help="Pull at most N mapped papers"
    )
    @click.option(
        "--include-rh-generated",
        is_flag=True,
        default=False,
        help="Also import RH-generated Zotero notes",
    )
    @click.option("--dry-run", is_flag=True, default=False, help="Preview imports")
    @click.pass_context
    def zotero_pull(
        ctx: click.Context,
        topic_name: str,
        library_id: str | None,
        library_type: str,
        api_key: str | None,
        api_base: str | None,
        limit: int | None,
        include_rh_generated: bool,
        dry_run: bool,
    ) -> None:
        """Pull Zotero user notes and PDF annotations back into RH."""
        from . import zotero_resource
        from .zotero_sync import ZoteroSyncService

        db = get_db(ctx)
        effective_library_id = library_id or os.getenv("ZOTERO_LIBRARY_ID", "")
        client = zotero_resource.create_zotero_resource_from_env(
            library_id=effective_library_id,
            library_type=library_type or os.getenv("ZOTERO_LIBRARY_TYPE", "user"),
            api_key=api_key or os.getenv("ZOTERO_API_KEY", ""),
            base_url=api_base or os.getenv("ZOTERO_API_BASE", ""),
        )
        service = ZoteroSyncService(
            db_path=db.path,
            client=client,
            library_id=effective_library_id,
            library_type=library_type,
        )
        result = service.pull_topic(
            topic_name,
            dry_run=dry_run,
            limit=limit,
            include_rh_generated=include_rh_generated,
        )
        payload = result.to_dict()
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        _echo_zotero_pull_result(result, topic_name=topic_name, dry_run=dry_run)
