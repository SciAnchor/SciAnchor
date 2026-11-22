"""Fallback action preparation from Zotero-backed Codex assistant output."""

from __future__ import annotations

from typing import Any, Callable

from research_harness_mcp.zotero_models_http import ZoteroChatRequest

CountExtractor = Callable[[str], int | None]
PreviewBuilder = Callable[..., dict[str, Any]]


def maybe_prepare_zotero_codex_output_action(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    assistant_text: str,
    context_payload: dict[str, Any],
    zotero_capability_mode: Callable[[dict[str, Any]], str],
    codex_output_requests_seed_import_preview: Callable[[str], bool],
    extract_zotero_import_count: CountExtractor,
    zotero_preview_seed_import: PreviewBuilder,
) -> dict[str, Any] | None:
    """Convert Codex's explicit seed-import preview decision into a safe preview."""

    if zotero_capability_mode(context_payload) != "collection":
        return None
    if not codex_output_requests_seed_import_preview(assistant_text):
        return None
    count = extract_zotero_import_count(body.message) or extract_zotero_import_count(
        assistant_text
    )
    return zotero_preview_seed_import(
        body=body,
        matched=matched,
        args={"count": count or 5},
    )
