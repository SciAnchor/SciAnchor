"""Capability broker for the RH Zotero lightweight Codex client.

The broker is intentionally small: it validates which RH/Zotero capabilities
are available in the current Zotero context and returns either a read result, a
write preview, or a refusal. It does not classify natural-language intent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

CapabilityHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ZoteroCapability:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    context_modes: tuple[str, ...] = ()
    read_only: bool = True
    requires_confirmation: bool = False
    handler: CapabilityHandler | None = None
    preview_handler: CapabilityHandler | None = None
    apply_handler: CapabilityHandler | None = None
    receipt_formatter: CapabilityHandler | None = None


@dataclass(frozen=True)
class CapabilityResult:
    capability: str
    status: str
    success: bool
    message: str
    output: dict[str, Any] = field(default_factory=dict)
    action_preview: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "capability": self.capability,
            "status": self.status,
            "success": self.success,
            "message": self.message,
            "output": self.output,
        }
        if self.action_preview is not None:
            payload["action_preview"] = self.action_preview
        if self.receipt is not None:
            payload["receipt"] = self.receipt
        return payload


class ZoteroCapabilityBroker:
    """Allowlist executor for Codex-originated RH/Zotero capability calls."""

    def __init__(self) -> None:
        self._capabilities: dict[str, ZoteroCapability] = {}

    def register(self, capability: ZoteroCapability) -> None:
        if not capability.name:
            raise ValueError("capability name is required")
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> ZoteroCapability | None:
        return self._capabilities.get(str(name or "").strip())

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "description": item.description,
                "input_schema": item.input_schema,
                "context_modes": list(item.context_modes),
                "read_only": item.read_only,
                "requires_confirmation": item.requires_confirmation,
            }
            for item in sorted(
                self._capabilities.values(), key=lambda entry: entry.name
            )
        ]

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
    ) -> CapabilityResult:
        capability_name = str(name or "").strip()
        capability = self.get(capability_name)
        if capability is None:
            return CapabilityResult(
                capability=capability_name,
                status="rejected",
                success=False,
                message=f"Capability is not allowlisted for Zotero: {capability_name}",
            )

        call_context = dict(context or {})
        mode = str(call_context.get("mode") or call_context.get("context_mode") or "")
        if capability.context_modes and mode not in capability.context_modes:
            return CapabilityResult(
                capability=capability.name,
                status="rejected",
                success=False,
                message=(
                    f"Capability {capability.name} is not available in Zotero "
                    f"context mode {mode or 'unknown'}"
                ),
            )

        payload = _coerce_arguments(arguments)
        try:
            if capability.requires_confirmation:
                if capability.preview_handler is None:
                    return CapabilityResult(
                        capability=capability.name,
                        status="rejected",
                        success=False,
                        message=(
                            f"Capability {capability.name} requires confirmation "
                            "but has no preview handler"
                        ),
                    )
                preview = capability.preview_handler(payload, call_context)
                action_preview = _extract_action_preview(preview)
                if action_preview is None:
                    assistant_message = _extract_assistant_message(preview)
                    if assistant_message is not None:
                        return CapabilityResult(
                            capability=capability.name,
                            status="assistant_message",
                            success=True,
                            message=assistant_message,
                            output=preview,
                        )
                    return CapabilityResult(
                        capability=capability.name,
                        status="rejected",
                        success=False,
                        message=(
                            f"Capability {capability.name} could not build an "
                            "action preview"
                        ),
                        output=preview,
                    )
                return CapabilityResult(
                    capability=capability.name,
                    status="preview",
                    success=True,
                    message=str(
                        action_preview.get("message")
                        or action_preview.get("title")
                        or "Action preview is ready"
                    ),
                    output={"preview_ready": True},
                    action_preview=action_preview,
                )

            if capability.handler is None:
                return CapabilityResult(
                    capability=capability.name,
                    status="rejected",
                    success=False,
                    message=f"Capability {capability.name} has no read handler",
                )
            output = capability.handler(payload, call_context)
            receipt = (
                capability.receipt_formatter(output, call_context)
                if capability.receipt_formatter is not None
                else None
            )
            return CapabilityResult(
                capability=capability.name,
                status="completed",
                success=True,
                message=str(
                    output.get("summary") or output.get("message") or "Completed"
                ),
                output=output,
                receipt=receipt,
            )
        except Exception as exc:
            return CapabilityResult(
                capability=capability.name,
                status="error",
                success=False,
                message=str(exc),
            )


def result_to_dynamic_tool_response(result: CapabilityResult) -> dict[str, Any]:
    """Convert a broker result to Codex app-server DynamicToolCallResponse."""

    return {
        "success": bool(result.success),
        "contentItems": [
            {
                "type": "inputText",
                "text": json.dumps(
                    result.to_dict(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
        ],
    }


def rejection_to_dynamic_tool_response(message: str) -> dict[str, Any]:
    result = CapabilityResult(
        capability="",
        status="rejected",
        success=False,
        message=message,
    )
    return result_to_dynamic_tool_response(result)


def zotero_execute_read_tool(
    tool_name: str,
    args: dict[str, Any],
    *,
    run_tool: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if tool_name in {"claim_extract", "gap_detect"} and not (
        args.get("paper_ids") or args.get("topic_id")
    ):
        raise ValueError(f"{tool_name} requires paper_ids or topic_id")
    if run_tool is None:
        from research_harness_mcp.tools import execute_tool

        run_tool = execute_tool
    output = run_tool(tool_name, args)
    return {
        "summary": f"Executed {tool_name}",
        "tool": tool_name,
        "output": output,
    }


def zotero_capability_paper_list(
    args: dict[str, Any],
    _context: dict[str, Any],
    *,
    get_db_context: Callable[[], Any],
    parse_json_field: Callable[[str | None, Any], Any],
) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 12), 50))
    params: list[Any] = []
    joins = ""
    filters = ["1 = 1"]
    topic_id = args.get("topic_id")
    topic_name = str(args.get("topic_name") or "").strip()
    if topic_id is not None or topic_name:
        joins = "JOIN paper_topics pt ON pt.paper_id = p.id JOIN topics t ON t.id = pt.topic_id"
        if topic_id is not None:
            filters.append("t.id = ?")
            params.append(int(topic_id))
        if topic_name:
            filters.append("t.name = ?")
            params.append(topic_name)
    if args.get("deep_read") is True:
        filters.append("COALESCE(p.deep_read, 0) = 1")
    elif args.get("deep_read") is False:
        filters.append("COALESCE(p.deep_read, 0) = 0")
    params.append(limit)
    with get_db_context() as conn:
        rows = conn.execute(
            f"""
            SELECT p.id, p.title, p.authors, p.year, p.venue, p.doi, p.arxiv_id,
                   p.status, p.deep_read
            FROM papers p
            {joins}
            WHERE {" AND ".join(filters)}
            ORDER BY COALESCE(p.deep_read, 0) DESC, p.year DESC, p.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    papers = []
    for row in rows:
        papers.append(
            {
                "id": int(row["id"]),
                "title": row["title"] or "",
                "authors": parse_json_field(row["authors"], []),
                "year": row["year"],
                "venue": row["venue"] or "",
                "doi": row["doi"] or "",
                "arxiv_id": row["arxiv_id"] or "",
                "status": row["status"] or "",
                "deep_read": bool(row["deep_read"]),
            }
        )
    return {
        "summary": f"Found {len(papers)} RH papers",
        "papers": papers,
        "limit": limit,
    }


def zotero_capability_paper_search(
    args: dict[str, Any],
    _context: dict[str, Any],
    *,
    api_factory: Callable[[], Any],
    search_papers_impl: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    max_results = max(1, min(int(args.get("max_results") or 5), 12))
    topic_id = args.get("topic_id")
    out = search_papers_impl(
        api_factory(),
        query=query,
        topic_id=int(topic_id) if topic_id is not None else None,
        max_results=max_results,
    )
    papers = list(out.get("papers") or [])[:max_results]
    return {
        "summary": f"Found {len(papers)} candidate papers for {query}",
        "query": query,
        "papers": papers,
        "provider_errors": list(out.get("provider_errors") or []),
    }


def _coerce_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return dict(arguments)
    return {}


def _extract_action_preview(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("kind") == "action_preview" and isinstance(
        payload.get("preview"), dict
    ):
        return dict(payload["preview"])
    if isinstance(payload.get("action_preview"), dict):
        return dict(payload["action_preview"])
    if str(payload.get("action_type") or ""):
        return dict(payload)
    return None


def _extract_assistant_message(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("kind") != "assistant_message":
        return None
    message = str(payload.get("message") or "").strip()
    return message or None
