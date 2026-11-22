"""Shared helper functions for Research Harness HTTP route wiring."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def rows_to_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) for row in rows]


def parse_json_field(value: str | None, fallback: Any = None) -> Any:
    """Safely parse a JSON string field. Returns fallback on failure."""
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize_result(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


def topic_exists(conn: sqlite3.Connection, topic_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,)).fetchone()
    return row is not None
