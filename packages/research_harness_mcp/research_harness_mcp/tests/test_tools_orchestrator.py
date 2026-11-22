"""Focused tests for MCP orchestrator tool definitions."""

from __future__ import annotations


def test_orchestrator_tool_set_preserves_membership() -> None:
    from research_harness_mcp.tools_orchestrator import _ORCHESTRATOR_TOOLS

    assert set(_ORCHESTRATOR_TOOLS) == {
        "orchestrator_status",
        "orchestrator_advance",
        "orchestrator_record_artifact",
        "orchestrator_add_artifact_dependency",
        "orchestrator_mark_artifact_stale",
        "orchestrator_clear_artifact_stale",
        "orchestrator_list_stale_artifacts",
        "orchestrator_resume",
        "orchestrator_gate_check",
        "paper_commit_version",
        "paper_task_intake",
        "integrity_check",
        "finalize",
        "review_bundle_create",
        "review_add_issue",
        "review_issues",
        "review_respond",
        "review_resolve",
        "review_status",
        "adversarial_run",
        "adversarial_resolve",
        "adversarial_status",
        "adversarial_review",
        "experiment_handoff_prepare",
        "experiment_handoff_submit",
        "workflow_entry",
        "claim_verify",
        "adversarial_section_review",
    }
    for name, tool in _ORCHESTRATOR_TOOLS.items():
        assert tool.name == name


def test_orchestrator_definition_schemas_preserve_lineage_and_resume_fields() -> None:
    from research_harness_mcp.tools_orchestrator import _ORCHESTRATOR_TOOLS

    record_schema = _ORCHESTRATOR_TOOLS["orchestrator_record_artifact"].inputSchema
    resume_schema = _ORCHESTRATOR_TOOLS["orchestrator_resume"].inputSchema
    intake_schema = _ORCHESTRATOR_TOOLS["paper_task_intake"].inputSchema

    assert record_schema["required"] == ["topic_id", "stage", "artifact_type"]
    assert "dependency_artifact_ids" in record_schema["properties"]
    assert "dependency_type" in record_schema["properties"]
    assert resume_schema["required"] == ["topic_id"]
    assert "stop_before" in resume_schema["properties"]
    assert intake_schema["required"] == ["task", "target_venue"]
    assert intake_schema["properties"]["mode"]["enum"] == [
        "explore",
        "standard",
        "strict",
        "demo",
    ]


def test_orchestrator_executor_preserves_resume_payload_with_injected_service() -> None:
    from research_harness_mcp.tools_orchestrator import _execute_orchestrator

    calls: dict[str, object] = {}

    class FakeDB:
        db_path = "/tmp/fake-rh.db"

    class FakeRun:
        id = 42
        topic_id = 7
        current_stage = "evidence_synthesis"
        stage_status = {"evidence_synthesis": "in_progress"}
        stop_before = "experiment"

    class FakeService:
        def __init__(self, db: FakeDB) -> None:
            calls["db"] = db

        def resume_run(
            self,
            *,
            topic_id: int,
            mode: str,
            force_stage: str | None,
            stop_before: str | None,
        ) -> FakeRun:
            calls["resume"] = {
                "topic_id": topic_id,
                "mode": mode,
                "force_stage": force_stage,
                "stop_before": stop_before,
            }
            return FakeRun()

        def infer_stage_from_artifacts(self, topic_id: int) -> str:
            calls["infer_topic_id"] = topic_id
            return "evidence_synthesis"

    fake_db = FakeDB()
    result = _execute_orchestrator(
        "orchestrator_resume",
        {
            "topic_id": 7,
            "mode": "standard",
            "force_stage": "evidence_synthesis",
            "stop_before": "experiment",
        },
        db_resolver=lambda: fake_db,
        service_factory=FakeService,
    )

    assert calls["db"] is fake_db
    assert calls["resume"] == {
        "topic_id": 7,
        "mode": "standard",
        "force_stage": "evidence_synthesis",
        "stop_before": "experiment",
    }
    assert calls["infer_topic_id"] == 7
    assert result == {
        "success": True,
        "run_id": 42,
        "topic_id": 7,
        "current_stage": "evidence_synthesis",
        "inferred_stage": "evidence_synthesis",
        "stage_status": {"evidence_synthesis": "in_progress"},
        "stop_before": "experiment",
    }


def test_orchestrator_executor_routes_paper_task_intake_through_service_dispatch(
    monkeypatch,
) -> None:
    import research_harness_mcp.tools_orchestrator as orchestrator_module
    from research_harness_mcp.tools_orchestrator import _execute_orchestrator

    calls: list[tuple[str, object]] = []

    class FakeDB:
        db_path = "/tmp/fake-rh.db"

    class FakeService:
        def __init__(self, db: FakeDB) -> None:
            calls.append(("orchestrator_init", db))

    def fake_dispatch(name: str, arguments: dict, db: FakeDB) -> dict:
        calls.append(("dispatch", (name, dict(arguments), db)))
        return {"rh_state": {"sync_status": "RH_SYNCED"}}

    monkeypatch.setattr(
        orchestrator_module,
        "_execute_service_backed_convenience",
        fake_dispatch,
    )
    fake_db = FakeDB()

    result = _execute_orchestrator(
        "paper_task_intake",
        {
            "task": "Write an RH paper",
            "target_venue": "NeurIPS 2026",
            "mode": "demo",
        },
        db_resolver=lambda: fake_db,
        service_factory=FakeService,
    )

    assert calls == [
        ("orchestrator_init", fake_db),
        (
            "dispatch",
            (
                "paper_task_intake",
                {
                    "task": "Write an RH paper",
                    "target_venue": "NeurIPS 2026",
                    "mode": "demo",
                },
                fake_db,
            ),
        ),
    ]
    assert result == {"rh_state": {"sync_status": "RH_SYNCED"}}
