"""Verified figure-asset records from SPC MinerU artifacts (UF02).

Parser image/caption/bbox blocks are candidates. A record is verified only
when page, caption, contained bytes, and a non-ambiguous bbox are all present.
This module does not parse PDFs.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_FIGURE_ASSET_BRIDGE = "rh.figure_asset_bridge.v1"
SCHEMA_FIGURE_ASSET = "rh.figure_asset_record.v1"

VERIFIED = "verified"
CANDIDATE = "candidate"
REJECTED = "rejected"
SCOPE_FIGURE = "complete_figure"
SCOPE_PANEL = "panel"
CAPTION_LINKED = "linked"
CAPTION_MISSING = "missing"
CAPTION_MULTI = "multi_panel_unsplit"
BBOX_OK = "ok"
BBOX_MISSING = "missing"
BBOX_AMBIGUOUS = "ambiguous"

_BODY_REF_RE = re.compile(r"\b(?:Figure|Fig\.?|FIGURE)\s+(\d+[A-Za-z]?)\b")
_FIGURE_ID_RE = re.compile(
    r"(?:figure|fig\.?)\s*(\d+)([a-z])?",
    re.IGNORECASE,
)
_PANEL_LABEL_RE = re.compile(r"\(([a-z])\)", re.IGNORECASE)


class FigureAssetBridgeError(ValueError):
    """Invalid figure-asset bridge input."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contained(root: Path, candidate: Path) -> Path | None:
    try:
        resolved_root = root.resolve()
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(resolved_root):
        return None
    return resolved


def load_content_list(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.is_file():
        raise FigureAssetBridgeError("content_list not found")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FigureAssetBridgeError(f"content_list unreadable: {exc}") from exc
    if not isinstance(payload, list):
        raise FigureAssetBridgeError("content_list must be a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def body_references(markdown: str, figure_number: str) -> list[str]:
    if not markdown or not figure_number:
        return []
    wanted = figure_number.lower()
    hits: list[str] = []
    seen: set[str] = set()
    for match in _BODY_REF_RE.finditer(markdown):
        token = match.group(1)
        if token.lower() == wanted or token.lower().startswith(wanted):
            snippet = match.group(0)
            key = snippet.lower()
            if key not in seen:
                seen.add(key)
                hits.append(snippet)
    return hits


def _caption_text(entry: Mapping[str, Any]) -> str:
    for key in ("img_caption", "caption", "text", "figure_caption"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _image_relpath(entry: Mapping[str, Any]) -> str:
    for key in ("img_path", "image_path", "path", "img_file"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _page(entry: Mapping[str, Any]) -> int | None:
    raw = entry.get("page_idx", entry.get("page"))
    try:
        page_idx = int(raw)
    except (TypeError, ValueError):
        return None
    if page_idx < 0:
        return None
    if entry.get("page") is not None and "page_idx" not in entry:
        return page_idx if page_idx >= 1 else None
    return page_idx + 1


def _bbox(entry: Mapping[str, Any]) -> list[float] | None:
    raw = entry.get("bbox") or entry.get("box")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        box = [float(part) for part in raw]
    except (TypeError, ValueError):
        return None
    if any(part != part or part in (float("inf"), float("-inf")) for part in box):
        return None
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def _figure_identity(
    caption: str, entry: Mapping[str, Any], index: int
) -> tuple[str, str]:
    explicit = str(entry.get("figure_id") or entry.get("panel_id") or "").strip()
    match = _FIGURE_ID_RE.search(caption) or _FIGURE_ID_RE.search(explicit)
    if match:
        number = match.group(1)
        panel = (match.group(2) or "").lower()
        if panel:
            return f"fig:{number}{panel}", SCOPE_PANEL
        return f"fig:{number}", SCOPE_FIGURE
    if explicit:
        return explicit, SCOPE_PANEL if entry.get("panel_id") else SCOPE_FIGURE
    return f"fig:candidate-{index}", SCOPE_FIGURE


def _panel_labels(caption: str) -> list[str]:
    labels = [match.group(1).lower() for match in _PANEL_LABEL_RE.finditer(caption)]
    return list(dict.fromkeys(labels))


def build_figure_asset_records(
    *,
    content_list: Sequence[Mapping[str, Any]],
    markdown: str = "",
    source_dir: Path | str,
    dest_dir: Path | str | None = None,
    parser_name: str = "mineru",
    parser_version: str = "",
) -> dict[str, Any]:
    root = Path(source_dir)
    if not root.is_dir():
        raise FigureAssetBridgeError("source_dir must be a directory")
    dest = Path(dest_dir) if dest_dir is not None else None
    if dest is not None:
        dest.mkdir(parents=True, exist_ok=True)

    image_entries = [
        dict(entry)
        for entry in content_list
        if str(entry.get("type") or "").lower() in {"image", "figure"}
    ]
    bbox_groups: dict[tuple[int | None, tuple[float, ...]], list[int]] = {}
    for index, entry in enumerate(image_entries):
        box = _bbox(entry)
        page = _page(entry)
        if box is not None:
            bbox_groups.setdefault((page, tuple(box)), []).append(index)
    ambiguous = {
        idx for indexes in bbox_groups.values() if len(indexes) > 1 for idx in indexes
    }

    seen_paths: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for index, entry in enumerate(image_entries):
        caption = _caption_text(entry)
        figure_id, scope = _figure_identity(caption, entry, index)
        page = _page(entry)
        box = _bbox(entry)
        labels = _panel_labels(caption)
        caption_status = CAPTION_MISSING
        if caption:
            caption_status = (
                CAPTION_MULTI
                if len(labels) >= 2 and scope == SCOPE_FIGURE
                else CAPTION_LINKED
            )
        bbox_status = (
            BBOX_MISSING
            if box is None
            else (BBOX_AMBIGUOUS if index in ambiguous else BBOX_OK)
        )
        number = figure_id.split(":", 1)[-1].rstrip("abcdefghijklmnopqrstuvwxyz")
        refs = body_references(markdown, number)

        rel = _image_relpath(entry)
        asset_path = ""
        digest = ""
        issues: list[str] = []
        status = CANDIDATE
        if not parser_version:
            issues.append("parser_version_missing")
        if not rel:
            issues.append("vector_or_page_render_without_bytes")
        else:
            contained = _contained(root, root / rel)
            if contained is None or not contained.is_file():
                issues.append("path_not_contained_or_missing")
                status = REJECTED
            else:
                data = contained.read_bytes()
                digest = _sha256_bytes(data)
                prior = seen_paths.get(str(contained))
                if prior and prior != digest:
                    issues.append("duplicate_path_hash_conflict")
                    status = REJECTED
                seen_paths[str(contained)] = digest
                if dest is not None:
                    copied = dest / "figures" / contained.name
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    if not copied.exists():
                        shutil.copy2(contained, copied)
                    asset_path = str(copied)
                else:
                    asset_path = str(contained)

        if status != REJECTED:
            if (
                page is not None
                and caption_status == CAPTION_LINKED
                and bbox_status == BBOX_OK
                and digest
                and asset_path
                and parser_version
            ):
                status = VERIFIED
            else:
                status = CANDIDATE
                if caption_status == CAPTION_MISSING:
                    issues.append("caption_missing")
                if caption_status == CAPTION_MULTI:
                    issues.append("multi_panel_caption_unsplit")
                if bbox_status != BBOX_OK:
                    issues.append(f"bbox_{bbox_status}")
                if page is None:
                    issues.append("page_missing")

        records.append(
            {
                "schema_version": SCHEMA_FIGURE_ASSET,
                "figure_id": figure_id,
                "scope": scope,
                "verification_status": status,
                "page": page,
                "bbox": box,
                "bbox_status": bbox_status,
                "caption_text": caption,
                "caption_status": caption_status,
                "panel_labels": labels,
                "body_references": refs,
                "asset_path": asset_path,
                "bytes_sha256": digest,
                "parser_name": parser_name,
                "parser_version": parser_version,
                "rights_status": "internal_retrieval",
                "issues": issues,
            }
        )

    return {
        "schema_version": SCHEMA_FIGURE_ASSET_BRIDGE,
        "parser_name": parser_name,
        "parser_version": parser_version,
        "records": records,
        "verified_count": sum(
            1 for rec in records if rec["verification_status"] == VERIFIED
        ),
        "candidate_count": sum(
            1 for rec in records if rec["verification_status"] == CANDIDATE
        ),
        "rejected_count": sum(
            1 for rec in records if rec["verification_status"] == REJECTED
        ),
    }
