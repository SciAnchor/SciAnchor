"""Focused tests for Zotero write-intent plan helper extraction."""

from __future__ import annotations

from typing import Any

from research_harness_mcp.zotero_models_http import ZoteroChatRequest


def _body(
    message: str = "import papers",
    requested_action_type: str | None = None,
) -> ZoteroChatRequest:
    payload: dict[str, Any] = {
        "message": message,
        "item": {
            "current_directory_key": "COLL1",
            "current_directory_name": "Agent Seeds",
            "current_directory_path": "Library / Agent Seeds",
            "zotero_item_key": "ITEM1",
        },
    }
    if requested_action_type is not None:
        payload["requested_action_type"] = requested_action_type
    return ZoteroChatRequest.model_validate(payload)


def _deps(**overrides: Any) -> dict[str, Any]:
    deps: dict[str, Any] = {
        "zotero_capability_mode": lambda context_payload: context_payload.get(
            "kind", "collection"
        ),
        "looks_like_zotero_create_collection_request": lambda _message: False,
        "extract_zotero_create_collection_name": lambda _message: "",
        "looks_like_zotero_seed_search_request": lambda _message: False,
        "extract_zotero_import_count": lambda _message: None,
        "zotero_seed_request_flags": lambda _message: {},
        "zotero_explicit_seed_topic_name": lambda _message: "",
        "zotero_seed_search_query": lambda _body, *, topic_name: topic_name,
        "zotero_attachment_target_source_for_plan": lambda _body, _mode: "",
        "looks_like_zotero_pdf_attachment_request": lambda _message: False,
        "looks_like_zotero_import_request": lambda _message: False,
        "looks_like_unsupported_zotero_write_request": lambda _message: False,
        "unsupported_zotero_write_message": lambda _body, _matched: "unsupported",
    }
    return {**deps, **overrides}


def test_zotero_write_plan_module_imports_and_http_wrappers_exist():
    from research_harness_mcp import http_api, zotero_write_plan

    assert callable(zotero_write_plan.plan_zotero_write_intent)
    assert callable(zotero_write_plan.preview_zotero_write_plan)
    assert callable(http_api._plan_zotero_write_intent)
    assert callable(http_api._preview_zotero_write_plan)


def test_plan_zotero_write_intent_short_circuits_requested_action_and_empty_message():
    from research_harness_mcp.zotero_write_plan import plan_zotero_write_intent

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("dependency should not be called")

    assert plan_zotero_write_intent(
        body=_body(requested_action_type="zotero_attach_pdf"),
        matched={},
        context_payload={"kind": "item"},
        **_deps(zotero_capability_mode=fail),
    ) == {"kind": "chat"}

    assert plan_zotero_write_intent(
        body=_body("   "),
        matched={},
        context_payload={"kind": "collection"},
        **_deps(zotero_capability_mode=fail),
    ) == {"kind": "chat"}


def test_plan_zotero_write_intent_maps_create_collection():
    from research_harness_mcp.zotero_write_plan import plan_zotero_write_intent

    result = plan_zotero_write_intent(
        body=_body("new folder"),
        matched={"source": "directory"},
        context_payload={"kind": "collection"},
        **_deps(
            looks_like_zotero_create_collection_request=lambda _message: True,
            extract_zotero_create_collection_name=lambda _message: "Reading Queue",
        ),
    )

    assert result == {
        "kind": "capability_preview",
        "capability": "rh.zotero.create_collection",
        "arguments": {"collection_name": "Reading Queue"},
    }


def test_plan_zotero_write_intent_maps_collection_seed_search():
    from research_harness_mcp.zotero_write_plan import plan_zotero_write_intent

    result = plan_zotero_write_intent(
        body=_body("find 8 seed papers"),
        matched={"topic": {"id": 3}},
        context_payload={"kind": "collection"},
        **_deps(
            looks_like_zotero_seed_search_request=lambda _message: True,
            extract_zotero_import_count=lambda _message: 8,
            zotero_seed_request_flags=lambda _message: {
                "request_pdf_attachment": True,
                "request_deep_read": False,
            },
            zotero_explicit_seed_topic_name=lambda _message: "agentic discovery",
            zotero_seed_search_query=lambda _body, *, topic_name: f"query:{topic_name}",
        ),
    )

    assert result == {
        "kind": "capability_preview",
        "capability": "rh.zotero.prepare_seed_import",
        "arguments": {
            "count": 8,
            "request_pdf_attachment": True,
            "request_deep_read": False,
            "topic_name": "agentic discovery",
            "query": "query:agentic discovery",
        },
    }


def test_plan_zotero_write_intent_maps_pdf_attachment_when_allowed():
    from research_harness_mcp.zotero_write_plan import plan_zotero_write_intent

    source_result = plan_zotero_write_intent(
        body=_body("attach pdf"),
        matched={"paper": {"id": 7}},
        context_payload={"kind": "collection"},
        **_deps(
            zotero_attachment_target_source_for_plan=lambda _body, _mode: (
                "last_preview"
            ),
            looks_like_zotero_pdf_attachment_request=lambda _message: True,
        ),
    )

    item_result = plan_zotero_write_intent(
        body=_body("attach pdf"),
        matched={"paper": {"id": 7}},
        context_payload={"kind": "item"},
        **_deps(
            zotero_attachment_target_source_for_plan=lambda _body, _mode: "",
            looks_like_zotero_pdf_attachment_request=lambda _message: True,
        ),
    )

    assert source_result == {
        "kind": "capability_preview",
        "capability": "rh.zotero.attach_pdf",
        "arguments": {"target_source": "last_preview"},
    }
    assert item_result == {
        "kind": "capability_preview",
        "capability": "rh.zotero.attach_pdf",
        "arguments": {},
    }


def test_plan_zotero_write_intent_maps_sync_and_unsupported_write():
    from research_harness_mcp.zotero_write_plan import plan_zotero_write_intent

    sync_result = plan_zotero_write_intent(
        body=_body("import 4 papers"),
        matched={"topic": {"id": 3}},
        context_payload={"kind": "collection"},
        **_deps(
            looks_like_zotero_import_request=lambda _message: True,
            extract_zotero_import_count=lambda _message: 4,
        ),
    )
    unsupported_result = plan_zotero_write_intent(
        body=_body("delete this item"),
        matched={"paper": {"id": 9}},
        context_payload={"kind": "item"},
        **_deps(
            looks_like_unsupported_zotero_write_request=lambda _message: True,
            unsupported_zotero_write_message=lambda body, matched: (
                f"unsupported:{body.message}:{matched['paper']['id']}"
            ),
        ),
    )

    assert sync_result == {
        "kind": "capability_preview",
        "capability": "rh.zotero.sync_papers",
        "arguments": {"limit": 4},
    }
    assert unsupported_result == {
        "kind": "unsupported_write",
        "message": "unsupported:delete this item:9",
    }


def test_preview_zotero_write_plan_invokes_broker_with_context():
    from research_harness_mcp.zotero_write_plan import preview_zotero_write_plan

    calls: list[dict[str, Any]] = []

    class Broker:
        def invoke(
            self,
            capability: str,
            arguments: dict[str, Any],
            *,
            context: dict[str, Any],
        ) -> dict[str, Any]:
            calls.append(
                {
                    "capability": capability,
                    "arguments": arguments,
                    "context": context,
                }
            )
            return {"ok": True}

    body = _body("attach pdf")
    matched = {"paper": {"id": 7}}
    context_payload = {"kind": "item", "item_key": "ITEM1"}
    result = preview_zotero_write_plan(
        body=body,
        matched=matched,
        context_payload=context_payload,
        plan={
            "capability": "rh.zotero.attach_pdf",
            "arguments": {"target_source": "last_preview"},
        },
        build_zotero_capability_broker=lambda **kwargs: (
            calls.append({"broker_kwargs": kwargs}) or Broker()
        ),
        zotero_capability_mode=lambda context: context["kind"],
    )

    assert result == {"ok": True}
    assert calls == [
        {
            "broker_kwargs": {
                "body": body,
                "matched": matched,
                "context_payload": context_payload,
            }
        },
        {
            "capability": "rh.zotero.attach_pdf",
            "arguments": {"target_source": "last_preview"},
            "context": {
                "mode": "item",
                "matched": matched,
                "zotero_context": context_payload,
            },
        },
    ]
