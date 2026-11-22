"""Persist search-time PDF candidates so acquisition can retry them later.

Provider search surfaces rich per-paper ``pdf_candidates`` (OpenAlex best-OA
locations, S2 openAccessPdf, arXiv direct links, ...), but the ``papers`` table
only holds a single ``url``. This module stores the full candidate list in
``paper_artifacts`` (artifact_type=``pdf_candidates``) at ingest time so
``paper acquire`` can attempt the same URLs the search stage already found,
instead of collapsing to DOI/landing-page reconstruction.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

ARTIFACT_TYPE = "pdf_candidates"


def normalize_candidate(item: Any) -> dict[str, Any] | None:
    """Coerce a PDFCandidate dataclass or dict into the stored JSON shape."""
    if isinstance(item, dict):
        get = item.get
    elif hasattr(item, "url"):
        get = lambda key, default=None: getattr(item, key, default)  # noqa: E731
    else:
        return None
    url = str(get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    try:
        confidence = float(get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "url": url,
        "source_type": str(get("source_type") or ""),
        "provider": str(get("provider") or ""),
        "requires_browser": bool(get("requires_browser") or False),
        "confidence": confidence,
        "license_hint": str(get("license_hint") or ""),
    }


def save_pdf_candidates(conn: Any, paper_id: int, candidates: list[Any]) -> int:
    """Replace the stored candidate list for a paper; returns count saved.

    List order is preserved (callers pass rank-sorted candidates), so loaders
    can treat position as priority.
    """
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates or []:
        data = normalize_candidate(item)
        if data is None or data["url"] in seen:
            continue
        seen.add(data["url"])
        normalized.append(data)
    conn.execute(
        "DELETE FROM paper_artifacts WHERE paper_id = ? AND artifact_type = ?",
        (paper_id, ARTIFACT_TYPE),
    )
    if normalized:
        conn.execute(
            "INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata)"
            " VALUES (?, ?, '', ?)",
            (paper_id, ARTIFACT_TYPE, json.dumps(normalized, ensure_ascii=False)),
        )
    conn.commit()
    return len(normalized)


def load_pdf_candidates(conn: Any, paper_id: int) -> list[dict[str, Any]]:
    """Load stored PDF candidates for a paper (latest record wins)."""
    row = conn.execute(
        """
        SELECT metadata FROM paper_artifacts
        WHERE paper_id = ? AND artifact_type = ?
        ORDER BY id DESC LIMIT 1
        """,
        (paper_id, ARTIFACT_TYPE),
    ).fetchone()
    if row is None:
        return []
    try:
        parsed = json.loads(row["metadata"] or "[]")
    except (TypeError, ValueError):
        logger.debug("Unparseable pdf_candidates metadata for paper %d", paper_id)
        return []
    if not isinstance(parsed, list):
        return []
    output: list[dict[str, Any]] = []
    for item in parsed:
        data = normalize_candidate(item)
        if data is not None:
            output.append(data)
    return output
