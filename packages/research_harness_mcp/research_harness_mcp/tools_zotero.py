"""MCP Zotero tool helpers."""

from __future__ import annotations

import os
from typing import Any

from research_harness.storage.db import Database


def _execute_zotero_sync(db: Database, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute RH-owned Zotero sync from MCP/HTTP surfaces."""

    topic = str(arguments.get("topic") or "").strip()
    if not topic:
        return {"error": "topic is required"}

    direction = str(arguments.get("direction") or "push").strip()
    if direction not in {"push", "pull", "both"}:
        return {"error": "direction must be one of: push, pull, both"}

    dry_run = bool(arguments.get("dry_run", True))
    deferred_error = _zotero_stable_dry_run_deferred_error(
        direction=direction,
        dry_run=dry_run,
    )
    if deferred_error:
        return {"error": deferred_error}

    from research_harness import zotero_resource
    from research_harness.zotero_sync import DEFAULT_ROOT_COLLECTION, ZoteroSyncService

    library_id = str(arguments.get("library_id") or os.getenv("ZOTERO_LIBRARY_ID", ""))
    library_type = str(
        arguments.get("library_type") or os.getenv("ZOTERO_LIBRARY_TYPE", "user")
    )
    if library_type not in {"user", "group"}:
        return {"error": "library_type must be 'user' or 'group'"}

    client = None
    needs_zotero_client = (not dry_run) or direction in {"pull", "both"}
    if needs_zotero_client:
        client = zotero_resource.create_zotero_resource_from_env(
            library_id=library_id,
            library_type=library_type,
            api_key=str(arguments.get("api_key") or os.getenv("ZOTERO_API_KEY", "")),
            base_url=str(arguments.get("api_base") or os.getenv("ZOTERO_API_BASE", "")),
        )

    limit_value = arguments.get("limit")
    limit = int(limit_value) if limit_value is not None else None
    service = ZoteroSyncService(
        db_path=db.path,
        client=client,
        library_id=library_id,
        library_type=library_type,
    )

    push_result = None
    pull_result = None
    if direction in {"push", "both"}:
        push_result = service.sync_topic(
            topic,
            root_collection=str(
                arguments.get("root_collection") or DEFAULT_ROOT_COLLECTION
            ),
            include_notes=not bool(arguments.get("skip_notes", False)),
            dry_run=dry_run,
            limit=limit,
            force=bool(arguments.get("force", False)),
        )
    if direction in {"pull", "both"}:
        pull_result = service.pull_topic(
            topic,
            dry_run=dry_run,
            limit=limit,
            include_rh_generated=bool(arguments.get("include_rh_generated", False)),
        )

    return {
        "topic": topic,
        "direction": direction,
        "dry_run": dry_run,
        "push": push_result.to_dict() if push_result is not None else None,
        "pull": pull_result.to_dict() if pull_result is not None else None,
    }


def _zotero_stable_dry_run_deferred_error(
    *,
    direction: str,
    dry_run: bool,
) -> str:
    if not dry_run:
        return (
            "real Zotero sync/apply is deferred; stable Zotero routing only "
            "supports direction=push with dry_run=true"
        )
    if direction in {"pull", "both"}:
        return (
            "stable Zotero dry-run only supports direction=push; "
            f"{direction} dry-run requires Zotero read access and remains deferred"
        )
    return ""
