"""Final-status helpers for paper-production runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..storage.db import Database


FINAL_PDF_ARTIFACT_TYPES = frozenset(
    {"final_bundle", "compiled_pdf", "publication_pack"}
)
REFERENCE_PAPER_DIR_NAMES = frozenset({"papers", "paper_pool", "downloads"})


def collect_final_pdf_paths(db: Database) -> list[str]:
    """Return PDF paths from RH output artifacts only.

    This intentionally ignores downloaded reference-paper PDFs. A final paper
    PDF must be represented by a final_bundle/compiled_pdf/publication_pack
    artifact, otherwise end-to-end tests can report false success after only
    literature acquisition.
    """

    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT artifact_type, path, payload_json
            FROM project_artifacts
            WHERE status = 'active'
              AND artifact_type IN ('final_bundle', 'compiled_pdf', 'publication_pack')
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()

    paths: list[str] = []
    seen: set[str] = set()
    for row in rows:
        artifact_type = str(row["artifact_type"] or "")
        payload = _loads_payload(row["payload_json"])
        candidates = _pdf_candidates_from_payload(payload)
        path_value = str(row["path"] or "").strip()
        if path_value:
            candidates.append(path_value)
        for candidate in candidates:
            normalized = _normalize_final_pdf_path(candidate, artifact_type)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            paths.append(normalized)
    return paths


def _loads_payload(payload_json: Any) -> dict[str, Any]:
    if isinstance(payload_json, dict):
        return payload_json
    if not isinstance(payload_json, str) or not payload_json.strip():
        return {}
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _pdf_candidates_from_payload(payload: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in (
        "pdf_path",
        "compiled_pdf_path",
        "final_pdf_path",
        "manuscript_pdf_path",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    outputs = payload.get("outputs")
    if isinstance(outputs, dict):
        candidates.extend(_pdf_candidates_from_payload(outputs))
    files = payload.get("files")
    if isinstance(files, dict):
        candidates.extend(_pdf_candidates_from_payload(files))
    return candidates


def _normalize_final_pdf_path(candidate: str, artifact_type: str) -> str:
    text = candidate.strip()
    if not text.lower().endswith(".pdf"):
        return ""
    path = Path(text)
    if any(part in REFERENCE_PAPER_DIR_NAMES for part in path.parts):
        return ""
    if artifact_type not in FINAL_PDF_ARTIFACT_TYPES:
        return ""
    return text
