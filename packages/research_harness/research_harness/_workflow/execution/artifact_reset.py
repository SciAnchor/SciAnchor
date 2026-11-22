"""Scoped supersede of manuscript artifacts (shared by reset-run and feedback apply)."""

from __future__ import annotations

import json
from typing import Any

from research_harness.storage.db import Database

DEFAULT_RESET_TYPES: frozenset[str] = frozenset(
    {
        "draft_pack",
        "final_bundle",
        "final_bundle_quality_report",
        "process_summary",
        "publication_pack",
        "publication_pack_trace",
        "figure_plan",
        "consistency_resolution",
        "authorship_statement",
        "literature_map",
        "topic_knowledge_snapshot",
        "section_draft",
    }
)

PROTECTED_ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        "gate_decision",
        "rollback_event",
        "provenance_record",
        "human_feedback_record",
    }
)

_SECTION_SCOPED_TYPES = frozenset({"section_draft"})


def _section_matches(row: dict[str, Any], sections: list[str]) -> bool:
    title = str(row.get("title") or "").lower()
    payload_section = ""
    try:
        payload = json.loads(row.get("payload_json") or "{}")
        payload_section = str(payload.get("section") or "").lower()
    except (TypeError, ValueError):
        payload_section = ""
    for section in sections:
        needle = section.strip().lower()
        if not needle:
            continue
        if needle in title or needle == payload_section:
            return True
    return False


def supersede_manuscript_artifacts(
    db: Database,
    *,
    topic_id: int,
    stages: list[str],
    types: set[str] | None = None,
    sections: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Mark matching active artifacts superseded; protected types never touched.

    ``sections`` narrows only section-scoped types (section_draft) by title or
    payload ``section``; assembly-level types in scope are always superseded.
    When a section filter matches zero section rows, all section rows in scope
    are included instead (broad-redraft fallback) and flagged in the result.
    """
    reset_types = set(types) if types else set(DEFAULT_RESET_TYPES)
    reset_types -= set(PROTECTED_ARTIFACT_TYPES)
    stage_list = [stage for stage in stages if stage]
    if not stage_list or not reset_types:
        return {
            "topic_id": topic_id,
            "dry_run": dry_run,
            "superseded": [],
            "section_filter": list(sections or []),
            "section_match_fallback": False,
        }

    conn = db.connect()
    try:
        stage_marks = ",".join("?" for _ in stage_list)
        type_marks = ",".join("?" for _ in reset_types)
        rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT id, stage, artifact_type, version, title, payload_json
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active'
                  AND stage IN ({stage_marks})
                  AND artifact_type IN ({type_marks})
                ORDER BY id
                """,
                (topic_id, *stage_list, *sorted(reset_types)),
            ).fetchall()
        ]

        section_match_fallback = False
        if sections:
            section_rows = [
                row for row in rows if row["artifact_type"] in _SECTION_SCOPED_TYPES
            ]
            matched = [row for row in section_rows if _section_matches(row, sections)]
            if section_rows and not matched:
                section_match_fallback = True
                matched = section_rows
            keep_ids = {row["id"] for row in matched}
            rows = [
                row
                for row in rows
                if row["artifact_type"] not in _SECTION_SCOPED_TYPES
                or row["id"] in keep_ids
            ]

        affected = [
            {
                "id": int(row["id"]),
                "stage": str(row["stage"]),
                "type": str(row["artifact_type"]),
                "version": int(row["version"]),
                "title": str(row["title"] or ""),
            }
            for row in rows
        ]
        if not dry_run and affected:
            conn.execute(
                f"""
                UPDATE project_artifacts
                SET status = 'superseded', updated_at = datetime('now')
                WHERE id IN ({",".join("?" for _ in affected)})
                """,
                tuple(item["id"] for item in affected),
            )
            conn.commit()
    finally:
        conn.close()

    return {
        "topic_id": topic_id,
        "dry_run": dry_run,
        "superseded": affected,
        "section_filter": list(sections or []),
        "section_match_fallback": section_match_fallback,
    }
