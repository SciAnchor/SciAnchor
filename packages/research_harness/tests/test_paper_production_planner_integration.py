from __future__ import annotations

from unittest.mock import patch

from research_harness.auto_runner import checkpoint as ckpt
from research_harness.auto_runner.llm_planner import plan_stage
from research_harness.auto_runner.stage_executor import execute_stage
from research_harness.orchestrator.service import OrchestratorService
from research_harness.storage.db import Database


def _db_with_topic(tmp_path, *, target_venue: str = "NeurIPS 2026"):
    db = Database(tmp_path / "paper-production.db")
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            (
                "Agentic literature review",
                "Evidence-grounded AI agents for literature review with benchmark evaluation",
                target_venue,
            ),
        )
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) VALUES (1, 'paper', 'paper')",
        )
        conn.commit()
    finally:
        conn.close()
    svc = OrchestratorService(db)
    svc.resume_run(1)
    return db, svc


def test_plan_stage_init_includes_paper_production_runtime_context(tmp_path) -> None:
    db, svc = _db_with_topic(tmp_path)

    result = plan_stage(
        db=db,
        svc=svc,
        topic_id=1,
        stage="init",
        checkpoint_data=ckpt.new_checkpoint(1),
    )

    runtime_context = result["paper_production_runtime_context"]

    assert result["target_venue"] == "NeurIPS 2026"
    assert result["venue_overlay"]["format_family"] == "latex-two-column"
    assert result["paper_profile"]["schema_version"] == ("rh.delivery.paper_profile.v1")
    assert runtime_context["schema_version"] == (
        "rh.paper_production_runtime_context.v1"
    )
    assert runtime_context["status"] == "ready_for_evidence_acquisition"
    assert result["paper_plan_ready"] is False
    assert "paper_plan" not in result


def test_plan_stage_build_adds_runtime_context_when_llm_planner_fallbacks(
    tmp_path, monkeypatch
) -> None:
    db, svc = _db_with_topic(tmp_path)
    monkeypatch.setattr(
        "research_harness.auto_runner.llm_planner._call_planner_llm",
        lambda _prompt: {},
    )

    result = plan_stage(
        db=db,
        svc=svc,
        topic_id=1,
        stage="build",
        checkpoint_data=ckpt.new_checkpoint(1),
    )

    assert result["query"].startswith("Evidence-grounded AI agents")
    assert result["paper_production_context_status"] == (
        "ready_for_evidence_acquisition"
    )
    assert result["target_venue"] == "NeurIPS 2026"
    assert result["topic_venue_contract"]["target_venue"] == "NeurIPS 2026"
    assert result["domain_method_search_profile"]["search_route"] == (
        "ml-baseline-search"
    )


def test_execute_stage_rehydrates_runtime_context_after_stage_context_reset(
    tmp_path, monkeypatch
) -> None:
    db, svc = _db_with_topic(tmp_path)
    checkpoint_data = ckpt.new_checkpoint(1)
    checkpoint_data["stage_context"]["stale_key"] = "must disappear"

    monkeypatch.setattr(
        "research_harness.auto_runner.stage_executor.run_research_wiki_preflight",
        lambda **_kwargs: None,
    )

    def fake_dispatch(**kwargs):
        context = kwargs["checkpoint_data"]["stage_context"]
        assert "stale_key" not in context
        assert context["target_venue"] == "NeurIPS 2026"
        assert context["venue_overlay"]["venue_family"] == "ml_conference"
        assert context["paper_production_runtime_context"]["status"] == (
            "ready_for_evidence_acquisition"
        )
        return {"summary": "init skipped in test", "tool_results": [], "errors": []}

    with patch(
        "research_harness.auto_runner.stage_executor._execute_stage_tools",
        side_effect=fake_dispatch,
    ):
        result = execute_stage(
            db=db,
            svc=svc,
            topic_id=1,
            stage="init",
            mode="demo",
            checkpoint_data=checkpoint_data,
            base_dir=tmp_path,
        )

    assert result["status"] == "complete"
    assert checkpoint_data["stage_context"]["paper_plan_ready"] is False
