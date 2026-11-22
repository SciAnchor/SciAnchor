"""Capability registration helpers for Zotero Codex turns."""

from __future__ import annotations

from typing import Any, Callable

from research_harness_mcp.zotero_capabilities import (
    ZoteroCapability,
    ZoteroCapabilityBroker,
)


def build_zotero_capability_broker(
    *,
    body: Any,
    matched: dict[str, Any],
    context_payload: dict[str, Any],
    zotero_capability_paper_list: Callable[
        [dict[str, Any], dict[str, Any]], dict[str, Any]
    ],
    zotero_capability_paper_search: Callable[
        [dict[str, Any], dict[str, Any]], dict[str, Any]
    ],
    zotero_preview_seed_import: Callable[..., dict[str, Any]],
    zotero_preview_create_collection: Callable[..., dict[str, Any]],
    zotero_preview_sync_papers: Callable[..., dict[str, Any]],
    zotero_preview_attach_pdf: Callable[..., dict[str, Any]],
    zotero_execute_read_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> ZoteroCapabilityBroker:
    broker = ZoteroCapabilityBroker()
    broker.register(
        ZoteroCapability(
            name="rh.paper.list",
            description="List papers from the local RH library.",
            input_schema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "integer"},
                    "topic_name": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "deep_read": {"type": "boolean"},
                },
            },
            context_modes=("library", "collection", "item", "reader_selection"),
            read_only=True,
            handler=zotero_capability_paper_list,
        )
    )
    broker.register(
        ZoteroCapability(
            name="rh.paper.search",
            description="Search candidate papers through the existing RH paper search path.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "topic_id": {"type": "integer"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                "required": ["query"],
            },
            context_modes=("library", "collection", "item", "reader_selection"),
            read_only=True,
            handler=zotero_capability_paper_search,
        )
    )
    broker.register(
        ZoteroCapability(
            name="rh.topic.match",
            description="Return the current Zotero context matched to an RH topic/paper.",
            input_schema={"type": "object"},
            context_modes=("library", "collection", "item", "reader_selection"),
            read_only=True,
            handler=lambda _args, _ctx: {
                "summary": "Current Zotero context match",
                "matched": matched,
                "context": context_payload,
            },
        )
    )
    broker.register(
        ZoteroCapability(
            name="rh.zotero.prepare_seed_import",
            description=(
                "Preview candidate seed-paper import for the current Zotero "
                "collection. Defaults topic/query to the current collection "
                "name when omitted."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "topic_name": {"type": "string"},
                    "query": {"type": "string"},
                    "count": {"type": "integer", "minimum": 1, "maximum": 12},
                    "request_deep_read": {"type": "boolean"},
                    "request_pdf_attachment": {"type": "boolean"},
                    "request_pdf_annotations": {"type": "boolean"},
                },
            },
            context_modes=("collection",),
            read_only=False,
            requires_confirmation=True,
            preview_handler=lambda args, _ctx: zotero_preview_seed_import(
                body=body,
                matched=matched,
                args=args,
            ),
        )
    )
    broker.register(
        ZoteroCapability(
            name="rh.zotero.create_collection",
            description="Preview creating a Zotero collection under the current selection.",
            input_schema={
                "type": "object",
                "properties": {"collection_name": {"type": "string"}},
                "required": ["collection_name"],
            },
            context_modes=("library", "collection"),
            read_only=False,
            requires_confirmation=True,
            preview_handler=lambda args, _ctx: zotero_preview_create_collection(
                body=body,
                matched=matched,
                args=args,
            ),
        )
    )
    broker.register(
        ZoteroCapability(
            name="rh.zotero.sync_papers",
            description="Preview syncing RH papers into the current Zotero collection.",
            input_schema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "integer"},
                    "paper_ids": {"type": "array", "items": {"type": "integer"}},
                    "limit": {"type": "integer"},
                },
            },
            context_modes=("collection", "item"),
            read_only=False,
            requires_confirmation=True,
            preview_handler=lambda args, _ctx: zotero_preview_sync_papers(
                body=body,
                matched=matched,
                args=args,
            ),
        )
    )
    broker.register(
        ZoteroCapability(
            name="rh.zotero.attach_pdf",
            description="Ensure an RH PDF is locally available, then preview attaching it to Zotero.",
            input_schema={"type": "object"},
            context_modes=("library", "collection", "item", "reader_selection"),
            read_only=False,
            requires_confirmation=True,
            preview_handler=lambda args, _ctx: zotero_preview_attach_pdf(
                body=body,
                matched=matched,
                args=args,
            ),
        )
    )
    broker.register(
        ZoteroCapability(
            name="rh.paper.annotate",
            description="Preview the PDF annotation write path; apply remains user-confirmed.",
            input_schema={"type": "object"},
            context_modes=("item", "reader_selection"),
            read_only=False,
            requires_confirmation=True,
            preview_handler=lambda _args, _ctx: {
                "kind": "assistant_message",
                "message": "PDF 批注写入需要走种子论文或 paper-reading-annotation 的确认式 apply 流程；当前工具调用不会直接写入。",
            },
        )
    )
    for primitive_name, tool_name in (
        ("rh.claim.extract", "claim_extract"),
        ("rh.gap.detect", "gap_detect"),
        ("rh.provenance.summary", "provenance_summary"),
    ):
        broker.register(
            ZoteroCapability(
                name=primitive_name,
                description=f"Invoke RH primitive wrapper `{tool_name}` and return its result.",
                input_schema={"type": "object"},
                context_modes=("library", "collection", "item", "reader_selection"),
                read_only=True,
                handler=lambda args, _ctx, tool_name=tool_name: (
                    zotero_execute_read_tool(
                        tool_name,
                        args,
                    )
                ),
            )
        )
    return broker
