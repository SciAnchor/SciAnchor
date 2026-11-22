"""Focused tests for MCP service-backed dispatch helpers."""

from __future__ import annotations


def test_service_backed_tool_set_preserves_membership() -> None:
    from research_harness_mcp.tools_service_dispatch import (
        _SERVICE_BACKED_CONVENIENCE_TOOLS,
    )

    assert _SERVICE_BACKED_CONVENIENCE_TOOLS == {
        "paper_search",
        "paper_ingest",
        "paper_summarize",
        "claim_extract",
        "evidence_link",
        "gap_detect",
        "baseline_identify",
        "section_draft",
        "figure_generate",
        "consistency_check",
        "exemplar_curate",
        "exemplar_retrieve",
        "exemplar_plan",
        "exemplar_generate",
        "exemplar_critique",
        "figure_suite_plan",
        "figure_suite_render",
        "manuscript_review",
        "manuscript_polish",
        "topic_list",
        "topic_show",
        "topic_state",
        "paper_list",
        "provenance_summary",
        "provenance_export",
        "orchestrator_status",
        "orchestrator_gate_check",
        "orchestrator_resume",
        "orchestrator_advance",
        "orchestrator_record_artifact",
        "paper_commit_version",
        "paper_task_intake",
        "topic_init",
        "paper_production_start",
        "paper_production_pending_decisions",
        "paper_production_decide",
        "paper_production_status",
        "paper_production_resume",
        "paper_production_mode",
        "paper_production_set_mode",
        "paper_production_export",
        "adversarial_review",
        "advisory_check",
        "zotero_sync",
        "topic_knowledge_status",
        "topic_knowledge_refresh",
        "cross_topic_atlas",
        "paperindex_search",
        "skill_list",
        "skill_get",
        "productization_boundary",
        "resource_ready_get",
        "figure_package",
    }


def test_execute_service_backed_convenience_preserves_output_shapes() -> None:
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools_service_dispatch import (
        _execute_service_backed_convenience,
    )

    calls: list[tuple[str, dict, object]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments), self.db))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={"value": 1},
            )

    db = object()

    assert _execute_service_backed_convenience(
        "topic_list",
        {"limit": 1},
        db,
        service_factory=FakeService,
    ) == {"value": 1}
    assert calls == [("topic_list", {"limit": 1}, db)]


def test_execute_service_backed_convenience_preserves_error_mapping() -> None:
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools_service_dispatch import (
        _execute_service_backed_convenience,
    )

    class FakeOutputErrorService:
        def __init__(self, db=None) -> None:
            pass

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            return ServiceResult(
                command=name,
                status="error",
                summary="ignored",
                output={"error": "raw output error"},
            )

    class FakeMessageErrorService:
        def __init__(self, db=None) -> None:
            pass

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            return ServiceResult(
                command=name,
                status="error",
                summary="fallback summary",
                output={},
                error={"message": "structured error"},
            )

    assert _execute_service_backed_convenience(
        "topic_show",
        {},
        service_factory=FakeOutputErrorService,
    ) == {"error": "raw output error"}
    assert _execute_service_backed_convenience(
        "topic_show",
        {},
        service_factory=FakeMessageErrorService,
    ) == {"error": "structured error"}


def test_execute_service_backed_primitive_preserves_envelope_and_callbacks() -> None:
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools_service_dispatch import (
        _execute_service_backed_primitive,
    )

    calls: list[tuple[str, object]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append(("invoke", (name, dict(arguments), self.db)))
            return ServiceResult(
                command=name,
                status="success",
                summary="Found papers",
                output={"papers": [{"id": 1}]},
                next_actions=("paper_ingest",),
                artifacts=({"kind": "search"},),
                recovery_hint="retry later",
                metadata={
                    "primitive": name,
                    "backend": "local",
                    "model_used": "test-model",
                    "cost_usd": 0.3,
                },
            )

    def topic_id_extractor(arguments: dict) -> int:
        calls.append(("topic", dict(arguments)))
        return 7

    def orch_state_provider(db, topic_id: int) -> dict:
        calls.append(("orch", (db, topic_id)))
        return {"run": {"current_stage": "build"}}

    def session_advisory_provider(db, name: str, arguments: dict, orch_state) -> str:
        calls.append(("advisory", (db, name, dict(arguments), orch_state)))
        return "session advice"

    def nudge_provider(db, name: str, arguments: dict, primitive_result) -> str:
        calls.append(("nudge", (db, name, dict(arguments), primitive_result.primitive)))
        return "nudge text"

    db = object()

    result = _execute_service_backed_primitive(
        "paper_search",
        {"topic_id": 7, "query": "x"},
        db,
        service_factory=FakeService,
        orch_state_provider=orch_state_provider,
        topic_id_extractor=topic_id_extractor,
        session_advisory_provider=session_advisory_provider,
        nudge_provider=nudge_provider,
    )

    assert result == {
        "status": "success",
        "summary": "Found papers",
        "output": {"papers": [{"id": 1}]},
        "next_actions": ["paper_ingest"],
        "artifacts": [{"kind": "search"}],
        "recovery_hint": "retry later",
        "primitive": "paper_search",
        "backend": "local",
        "model_used": "test-model",
        "cost_usd": 0.3,
        "session_advisory": "session advice",
        "nudge": "nudge text",
    }
    assert calls[0] == ("invoke", ("paper_search", {"topic_id": 7, "query": "x"}, db))
    assert calls[1] == ("topic", {"topic_id": 7, "query": "x"})
    assert calls[2] == ("orch", (db, 7))
    assert calls[3][0] == "advisory"
    assert calls[4] == (
        "nudge",
        (db, "paper_search", {"topic_id": 7, "query": "x"}, "paper_search"),
    )


def test_execute_service_backed_primitive_preserves_unknown_arguments_for_compatibility() -> (
    None
):
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools_service_dispatch import (
        _execute_service_backed_primitive,
    )

    calls: list[tuple[str, dict, object]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments), self.db))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={"arguments": dict(arguments)},
            )

    db = object()

    result = _execute_service_backed_primitive(
        "paper_search",
        {"query": "x", "adapter_passthrough": True},
        db,
        service_factory=FakeService,
        orch_state_provider=lambda db, topic_id: None,
        topic_id_extractor=lambda arguments: None,
        session_advisory_provider=lambda db, name, arguments, orch_state: "",
        nudge_provider=lambda db, name, arguments, primitive_result: "",
    )

    assert result["output"] == {
        "arguments": {"query": "x", "adapter_passthrough": True}
    }
    assert calls == [("paper_search", {"query": "x", "adapter_passthrough": True}, db)]
