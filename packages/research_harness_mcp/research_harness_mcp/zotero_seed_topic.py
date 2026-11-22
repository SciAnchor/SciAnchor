"""Zotero seed-topic creation helpers for HTTP wiring."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any


def get_or_create_zotero_seed_topic(
    *,
    topic_id: int | None,
    topic_name: str,
    description: str,
    get_db_context: Callable[[], AbstractContextManager[sqlite3.Connection]],
    materialize_topic_workspace: Callable[..., Any],
    run_tool: Callable[[str, dict[str, Any]], Any],
    now_iso: Callable[[], str],
    missing_topic_error: Callable[[int], BaseException],
    bootstrap_exception_types: tuple[type[BaseException], ...] = (),
    log_warning: Callable[..., Any] | None = None,
) -> tuple[int, bool]:
    name = str(topic_name or "").strip()
    if topic_id is not None:
        normalized_topic_id = int(topic_id)
        with get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM topics WHERE id = ?", (normalized_topic_id,)
            ).fetchone()
        if row is None:
            raise missing_topic_error(normalized_topic_id)
        return normalized_topic_id, False

    with get_db_context() as conn:
        existing = conn.execute(
            "SELECT id FROM topics WHERE name = ? ORDER BY id ASC LIMIT 1",
            (name,),
        ).fetchone()
        if existing:
            return int(existing["id"]), False
        cur = conn.execute(
            """
            INSERT INTO topics (name, description, status, created_at)
            VALUES (?, ?, 'active', ?)
            """,
            (name, description, now_iso()),
        )
        conn.commit()
        created_id = int(cur.lastrowid)

    materialize_topic_workspace(
        topic_id=created_id,
        topic_name=name,
        description=description,
    )
    try:
        run_tool("orchestrator_resume", {"topic_id": created_id})
    except Exception as exc:
        if bootstrap_exception_types and isinstance(exc, bootstrap_exception_types):
            raise
        if log_warning is not None:
            log_warning("Failed to bootstrap Zotero seed topic", exc_info=True)
    return created_id, True
