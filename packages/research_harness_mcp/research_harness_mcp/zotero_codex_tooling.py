"""Pure helpers for Zotero Codex dynamic-tool handling."""

from __future__ import annotations

import json
import re
from typing import Any


def zotero_capability_mode(context_payload: dict[str, Any]) -> str:
    kind = str(context_payload.get("kind") or "").strip()
    if kind == "paper":
        return "item"
    if kind in {"collection", "library"}:
        return kind
    return "reader_selection" if context_payload.get("selected_text") else "library"


def normalize_zotero_codex_tool_name(
    tool: Any,
    *,
    namespace: Any = None,
) -> str:
    name = str(tool or "").strip()
    ns = str(namespace or "").strip()
    if ns and not name.startswith(f"{ns}."):
        name = f"{ns}.{name}"
    aliases = {
        "paper.list": "rh.paper.list",
        "paper.search": "rh.paper.search",
        "topic.match": "rh.topic.match",
        "zotero.prepare_seed_import": "rh.zotero.prepare_seed_import",
        "zotero.sync_papers": "rh.zotero.sync_papers",
        "zotero.attach_pdf": "rh.zotero.attach_pdf",
        "zotero.create_collection": "rh.zotero.create_collection",
        "paper.annotate": "rh.paper.annotate",
        "claim.extract": "rh.claim.extract",
        "gap.detect": "rh.gap.detect",
        "provenance.summary": "rh.provenance.summary",
    }
    return aliases.get(name, name)


def coerce_codex_tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"text": value}
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    return {}


def coerce_zotero_capability_count(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 12))


def codex_output_requests_seed_import_preview(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "")).casefold()
    if not normalized:
        return False
    explicit_preview = "action_preview" in normalized or "确认卡" in normalized
    if not explicit_preview:
        return False
    seed_terms = (
        "seedimport",
        "起步文献",
        "种子论文",
        "候选预览",
        "候选论文",
        "找种子",
        "找起步",
    )
    write_terms = ("确认后", "导入", "入库", "同步", "写入")
    return any(term in normalized for term in seed_terms) and any(
        term in normalized for term in write_terms
    )
