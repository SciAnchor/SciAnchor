"""Focused tests for Zotero capability broker registration extraction."""

from __future__ import annotations

from typing import Any

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


def _body() -> ZoteroChatRequest:
    return ZoteroChatRequest.model_validate(
        {
            "message": "use capabilities",
            "item": {
                "zotero_item_key": "ITEM1",
                "current_directory_key": "COLL1",
                "current_directory_name": "Agent Seeds",
                "current_directory_path": "Library / Agent Seeds",
            },
        }
    )


def _build_deps(calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "zotero_capability_paper_list": lambda args, ctx: (
            calls.append({"handler": "paper_list", "args": args, "ctx": ctx})
            or {"summary": "paper list"}
        ),
        "zotero_capability_paper_search": lambda args, ctx: (
            calls.append({"handler": "paper_search", "args": args, "ctx": ctx})
            or {"summary": "paper search"}
        ),
        "zotero_preview_seed_import": lambda **kwargs: (
            calls.append({"handler": "seed", **kwargs})
            or {
                "kind": "action_preview",
                "preview": {
                    "action_type": "zotero_seed_paper_search",
                    "message": "seed ready",
                },
            }
        ),
        "zotero_preview_create_collection": lambda **kwargs: (
            calls.append({"handler": "create_collection", **kwargs})
            or {
                "kind": "action_preview",
                "preview": {
                    "action_type": "zotero_create_collection",
                    "message": "collection ready",
                },
            }
        ),
        "zotero_preview_sync_papers": lambda **kwargs: (
            calls.append({"handler": "sync", **kwargs})
            or {
                "kind": "action_preview",
                "preview": {
                    "action_type": "zotero_sync_papers",
                    "message": "sync ready",
                },
            }
        ),
        "zotero_preview_attach_pdf": lambda **kwargs: (
            calls.append({"handler": "attach_pdf", **kwargs})
            or {
                "kind": "action_preview",
                "preview": {
                    "action_type": "zotero_attach_pdf",
                    "message": "attach ready",
                },
            }
        ),
        "zotero_execute_read_tool": lambda tool_name, args: (
            calls.append({"handler": "primitive", "tool": tool_name, "args": args})
            or {"summary": f"Executed {tool_name}"}
        ),
    }


def test_zotero_capability_broker_registry_imports_and_http_wrapper_exists():
    from research_harness_mcp import http_api, zotero_capability_broker

    assert callable(zotero_capability_broker.build_zotero_capability_broker)
    assert callable(http_api._build_zotero_capability_broker)


def test_build_zotero_capability_broker_registers_expected_names_and_metadata():
    from research_harness_mcp.zotero_capability_broker import (
        build_zotero_capability_broker,
    )

    broker = build_zotero_capability_broker(
        body=_body(),
        matched={"topic": {"id": 3}},
        context_payload={"kind": "collection"},
        **_build_deps([]),
    )

    capabilities = broker.list()
    assert [item["name"] for item in capabilities] == [
        "rh.claim.extract",
        "rh.gap.detect",
        "rh.paper.annotate",
        "rh.paper.list",
        "rh.paper.search",
        "rh.provenance.summary",
        "rh.topic.match",
        "rh.zotero.attach_pdf",
        "rh.zotero.create_collection",
        "rh.zotero.prepare_seed_import",
        "rh.zotero.sync_papers",
    ]

    by_name = {item["name"]: item for item in capabilities}
    assert by_name["rh.paper.list"]["read_only"] is True
    assert by_name["rh.paper.list"]["requires_confirmation"] is False
    assert by_name["rh.paper.list"]["input_schema"]["properties"]["limit"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
    }
    assert by_name["rh.zotero.prepare_seed_import"]["read_only"] is False
    assert by_name["rh.zotero.prepare_seed_import"]["requires_confirmation"] is True
    assert by_name["rh.zotero.prepare_seed_import"]["context_modes"] == ["collection"]
    assert by_name["rh.paper.annotate"]["context_modes"] == [
        "item",
        "reader_selection",
    ]


def test_build_zotero_capability_broker_delegates_topic_and_preview_handlers():
    from research_harness_mcp.zotero_capability_broker import (
        build_zotero_capability_broker,
    )

    calls: list[dict[str, Any]] = []
    body = _body()
    matched = {"paper": {"id": 9}}
    context_payload = {"kind": "collection", "collection_key": "COLL1"}
    broker = build_zotero_capability_broker(
        body=body,
        matched=matched,
        context_payload=context_payload,
        **_build_deps(calls),
    )

    topic_result = broker.invoke(
        "rh.topic.match",
        {},
        context={"mode": "collection"},
    )
    seed_result = broker.invoke(
        "rh.zotero.prepare_seed_import",
        {"count": 2},
        context={"mode": "collection"},
    )

    assert topic_result.output == {
        "summary": "Current Zotero context match",
        "matched": matched,
        "context": context_payload,
    }
    assert seed_result.status == "preview"
    assert seed_result.action_preview == {
        "action_type": "zotero_seed_paper_search",
        "message": "seed ready",
    }
    assert calls == [
        {
            "handler": "seed",
            "body": body,
            "matched": matched,
            "args": {"count": 2},
        }
    ]


def test_build_zotero_capability_broker_delegates_read_primitives():
    from research_harness_mcp.zotero_capability_broker import (
        build_zotero_capability_broker,
    )

    calls: list[dict[str, Any]] = []
    broker = build_zotero_capability_broker(
        body=_body(),
        matched={},
        context_payload={"kind": "library"},
        **_build_deps(calls),
    )

    result = broker.invoke(
        "rh.provenance.summary",
        {"topic_id": 7},
        context={"mode": "library"},
    )

    assert result.status == "completed"
    assert result.output == {"summary": "Executed provenance_summary"}
    assert calls == [
        {
            "handler": "primitive",
            "tool": "provenance_summary",
            "args": {"topic_id": 7},
        }
    ]
