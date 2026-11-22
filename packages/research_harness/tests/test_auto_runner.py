"""Tests for auto_runner — checkpoint, stage_policy, codex_bridge, runner."""

from __future__ import annotations

import json

import pytest

from research_harness.auto_runner.checkpoint import (
    clear_codex_handoff,
    clear_error,
    load_checkpoint,
    new_checkpoint,
    record_artifact,
    record_error,
    record_event,
    record_human_decision,
    save_checkpoint,
    set_codex_handoff,
    set_human_decision_request,
    update_stage,
)
from research_harness.auto_runner.codex_bridge import (
    _normalize_review,
    _parse_codex_output,
    codex_issues_to_objections,
)
from research_harness.auto_runner.runner import _can_auto_approve
from research_harness.auto_runner.stage_policy import (
    decide_recovery,
    get_policy,
    max_retries,
    should_invoke_codex,
    should_pause_human,
)


@pytest.fixture(autouse=True)
def _stub_stage_planner_for_auto_runner_tests(monkeypatch):
    """Keep auto-runner tests from invoking live LLM/CLI planner routes."""

    monkeypatch.setattr(
        "research_harness.auto_runner.llm_planner.plan_stage",
        lambda **_kwargs: {},
    )


# ---------------------------------------------------------------------------
# Checkpoint tests
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def test_new_checkpoint(self):
        cp = new_checkpoint(1, mode="standard")
        assert cp["topic_id"] == 1
        assert cp["mode"] == "standard"
        assert cp["current_stage"] == "init"
        assert cp["stage_state"] == "pending"
        assert cp["schema_version"] == 1
        assert cp["human_decision"]["requested"] is False
        assert cp["human_decision"]["schema_version"] == "rh.human_decision_request.v2"

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "test_cp.json"
        cp = new_checkpoint(1)
        save_checkpoint(path, cp)
        loaded = load_checkpoint(path)
        assert loaded is not None
        assert loaded["topic_id"] == 1
        assert "updated_at" in loaded

    def test_load_missing(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        assert load_checkpoint(path) is None

    def test_record_event(self):
        cp = new_checkpoint(1)
        record_event(cp, stage="topic_framing", event="stage_start", detail="test")
        assert len(cp["history"]) == 1
        assert cp["history"][0]["event"] == "stage_start"

    def test_record_artifact(self):
        cp = new_checkpoint(1)
        record_artifact(
            cp,
            stage="topic_framing",
            artifact_type="topic_brief",
            artifact_id=5,
            version=1,
        )
        assert cp["artifacts"]["topic_framing"]["topic_brief"]["artifact_id"] == 5

    def test_record_and_clear_error(self):
        cp = new_checkpoint(1)
        record_error(cp, kind="api", message="rate limited", tool_name="paper_search")
        assert cp["last_error"]["kind"] == "api"
        assert cp["last_error"]["retry_count"] == 1
        record_error(cp, kind="api", message="rate limited again")
        assert cp["last_error"]["retry_count"] == 2
        clear_error(cp)
        assert cp["last_error"]["retry_count"] == 0

    def test_update_stage(self):
        cp = new_checkpoint(1)
        update_stage(
            cp, stage="literature_mapping", state="running", summary_md="searching..."
        )
        assert cp["current_stage"] == "literature_mapping"
        assert cp["stage_state"] == "running"

    def test_codex_handoff(self):
        cp = new_checkpoint(1)
        set_codex_handoff(
            cp,
            stage="adversarial_optimization",
            request_path="/tmp/req.json",
            response_path="/tmp/resp.json",
        )
        assert cp["codex_handoff"]["requested"] is True
        clear_codex_handoff(cp, verdict="approve")
        assert cp["codex_handoff"]["requested"] is False
        assert cp["codex_handoff"]["verdict"] == "approve"

    def test_human_decision_request_and_record(self):
        cp = new_checkpoint(1)
        request = set_human_decision_request(
            cp,
            stage="init",
            checkpoint="paper_production_evidence_gate",
            reason_code="insufficient_seed_papers",
            prompt="Choose evidence acquisition policy.",
            options=[{"action": "broaden_search"}, {"action": "stop"}],
            params={"seed_paper_count": 0},
        )
        assert request["requested"] is True
        assert request["decision_status"] == "pending"
        assert cp["human_decision"]["reason_code"] == "insufficient_seed_papers"

        decision = record_human_decision(
            cp,
            choice="broaden_search",
            reasoning="approved",
            params={"local_only": False},
        )
        assert decision["requested"] is False
        assert decision["selected"] == "broaden_search"
        assert decision["decision_status"] == "accepted"
        assert decision["reasoning"] == "approved"
        assert decision["params"]["seed_paper_count"] == 0
        assert decision["params"]["local_only"] is False

    def test_history_bounded(self):
        cp = new_checkpoint(1)
        for i in range(250):
            record_event(cp, stage="test", event=f"e{i}")
        assert len(cp["history"]) == 200


# ---------------------------------------------------------------------------
# Stage policy tests
# ---------------------------------------------------------------------------


class TestStagePolicy:
    def test_all_stages_have_policy(self):
        from research_harness.orchestrator.stages import STAGE_ORDER

        for stage in STAGE_ORDER:
            assert get_policy(stage) is not None, f"Missing policy: {stage}"

    def test_propose_requires_codex(self):
        assert should_invoke_codex("propose", "standard") is True
        assert should_invoke_codex("propose", "explore") is True

    def test_write_codex_by_mode(self):
        assert should_invoke_codex("write", "standard") is True  # recommended
        assert should_invoke_codex("write", "explore") is False

    def test_optional_codex_only_in_strict(self):
        assert should_invoke_codex("build", "strict") is True
        assert should_invoke_codex("build", "standard") is False

    def test_human_checkpoints(self):
        assert should_pause_human("init", "standard") is True
        assert should_pause_human("init", "demo") is False
        assert should_pause_human("analyze", "standard") is True
        assert should_pause_human("build", "standard") is True  # conditional + standard
        assert should_pause_human("write", "standard") is True

    def test_auto_approve_cannot_bypass_high_risk_or_failed_gate(self):
        assert _can_auto_approve("propose") is False
        assert _can_auto_approve("write") is False
        assert _can_auto_approve("build", "needs_coverage") is False
        assert _can_auto_approve("build", "pass") is True

    def test_max_retries(self):
        assert max_retries("build") == 2
        assert max_retries("propose") == 1
        assert max_retries("init") == 0
        assert max_retries("write") == 1

    def test_decide_recovery_retry(self):
        assert decide_recovery("build", "api_error", 0) == "retry"
        assert decide_recovery("build", "api_error", 1) == "retry"

    def test_decide_recovery_exhausted(self):
        assert decide_recovery("build", "api_error", 2) == "fallback_stage"
        assert decide_recovery("init", "api_error", 0) == "pause_human"  # no fallback


# ---------------------------------------------------------------------------
# Codex bridge tests
# ---------------------------------------------------------------------------


class TestCodexBridge:
    def test_parse_json_output(self):
        raw = json.dumps(
            {
                "verdict": "approve",
                "issues": [
                    {
                        "severity": "minor",
                        "category": "clarity",
                        "target": "abstract",
                        "reasoning": "unclear",
                    }
                ],
                "scores": {"novelty": 4.5, "clarity": 3.0},
                "notes": "good work",
            }
        )
        result = _parse_codex_output(raw)
        assert result["verdict"] == "approve"
        assert len(result["issues"]) == 1
        assert result["scores"]["novelty"] == 4.5

    def test_parse_fenced_json(self):
        raw = 'Here is my review:\n```json\n{"verdict": "revise", "issues": [], "scores": {}, "notes": "fix it"}\n```\n'
        result = _parse_codex_output(raw)
        assert result["verdict"] == "revise"

    def test_parse_text_fallback(self):
        raw = "This looks good. VERDICT: APPROVE"
        result = _parse_codex_output(raw)
        assert result["verdict"] == "approve"

    def test_normalize_review(self):
        data = {
            "verdict": "APPROVE",
            "issues": "not a list",
            "scores": 42,
            "notes": "ok",
        }
        norm = _normalize_review(data)
        assert norm["verdict"] == "approve"
        assert norm["issues"] == []
        assert norm["scores"] == {}

    def test_issues_to_objections(self):
        issues = [
            {
                "severity": "major",
                "category": "novelty",
                "target": "method",
                "reasoning": "not new",
            },
            {
                "severity": "minor",
                "category": "clarity",
                "target": "abstract",
                "reasoning": "unclear",
            },
        ]
        objs = codex_issues_to_objections(issues)
        assert len(objs) == 2
        assert objs[0]["severity"] == "major"
        assert objs[0]["category"] == "novelty"


# ---------------------------------------------------------------------------
# Runner dry-run test
# ---------------------------------------------------------------------------


class TestRunnerDryRun:
    def test_dry_run(self):
        """Test _dry_run directly to avoid side effects from run_project's
        internal DB/config resolution."""
        from research_harness.auto_runner.runner import _dry_run

        result = _dry_run("init", "standard")
        assert result["status"] == "dry_run"
        assert len(result["plan"]) == 6
        assert result["plan"][0]["stage"] == "init"
        assert result["plan"][4]["stage"] == "experiment"
        assert result["plan"][-1]["stage"] == "write"


# ---------------------------------------------------------------------------
# Integration tests for stage execution
# ---------------------------------------------------------------------------


class TestStageExecutorIntegration:
    """Test execute_stage with real DB but mocked tool dispatch."""

    @pytest.fixture
    def setup_db(self, tmp_path):
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "runner.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO topics (name, description) VALUES (?, ?)",
                ("test-topic", "Runner test"),
            )
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'test', 'test')",
            )
            conn.commit()
        finally:
            conn.close()
        svc = OrchestratorService(db)
        svc.resume_run(1)
        return db, svc, tmp_path

    def test_all_tools_failed_triggers_recovery(self, setup_db):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1)

        def fake_dispatch_all_fail(**kwargs):
            return {
                "summary": "Stage build: 0/2 tools succeeded",
                "tool_results": [
                    {"tool": "paper_search", "success": False, "error": "timeout"},
                    {"tool": "paper_ingest", "success": False, "error": "no source"},
                ],
                "errors": ["paper_search: timeout", "paper_ingest: no source"],
            }

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_all_fail,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="build",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        # Should trigger retry (build has retry_twice policy)
        assert result["status"] == "retry"
        assert "All" in result.get("summary", "") or "failed" in result.get("error", "")

    def test_auto_artifacts_prevent_all_tools_failed_recovery(self, setup_db):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["paper_production_run_policy"] = {
            "schema_version": "rh.paper_production_run_policy.v1",
            "autonomous_completion": True,
            "stop_on_gate_failure": True,
            "mode": "demo",
            "evidence_boundary": "demo_limited_seed_pool",
            "local_only": True,
            "external_actions": [],
        }

        def fake_dispatch_fail_with_auto_artifact(**kwargs):
            return {
                "summary": "Stage analyze: 0/2 tools succeeded; demo artifacts recorded",
                "tool_results": [
                    {"tool": "claim_extract", "success": False, "error": "network"},
                    {"tool": "gap_detect", "success": False, "error": "network"},
                ],
                "errors": ["claim_extract: network", "gap_detect: network"],
                "auto_artifacts": [("evidence_pack", 123)],
            }

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_fail_with_auto_artifact,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="analyze",
                mode="demo",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        assert result["status"] == "complete"
        assert "demo artifacts recorded" in result["summary"]

    def test_successful_tools_returns_needs_human(self, setup_db):
        """analyze stage in standard mode returns needs_human (human_checkpoint=always)."""
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1)

        def fake_dispatch_ok(**kwargs):
            return {
                "summary": "Stage analyze: 3/3 tools succeeded",
                "tool_results": [
                    {"tool": "claim_extract", "success": True, "error": ""},
                ],
                "errors": [],
            }

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_ok,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="analyze",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        # analyze has human_checkpoint="always" → needs_human in standard mode
        assert result["status"] == "needs_human"

    def test_execute_stage_records_research_wiki_preflight_before_tools(self, setup_db):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1)

        def fake_preflight(**kwargs):
            assert kwargs["topic_id"] == 1
            assert kwargs["stage"] == "write"
            return {
                "schema_version": "research_wiki_preflight.v1",
                "topic_id": 1,
                "stage": "write",
                "action_name": "paper_writing",
                "paper_wiki_status": "loaded",
                "status_reason": "wiki_context_pack_loaded",
                "priority_evidence_layer": "research_wiki",
                "fallback_allowed": False,
                "fallback_must_be_declared": True,
                "must_not_silent_markdown_fallback": True,
                "degraded": True,
                "warning_codes": ["snapshot_stale"],
                "page_count": 8,
                "evidence_anchor_count": 24,
                "unavailable_reasons": [],
            }

        def fake_dispatch_ok(**kwargs):
            assert (
                kwargs["checkpoint_data"]["stage_context"]["research_wiki_preflight"][
                    "paper_wiki_status"
                ]
                == "loaded"
            )
            return {
                "summary": "Stage write: tools skipped in test",
                "tool_results": [],
                "errors": [],
            }

        with (
            patch(
                "research_harness.auto_runner.stage_executor.run_research_wiki_preflight",
                side_effect=fake_preflight,
            ) as preflight_mock,
            patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                side_effect=fake_dispatch_ok,
            ),
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="write",
                mode="explore",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        assert result["status"] == "needs_human"
        preflight_mock.assert_called_once()
        assert (
            checkpoint_data["stage_context"]["research_wiki_preflight"][
                "paper_wiki_status"
            ]
            == "loaded"
        )
        assert any(
            event["event"] == "research_wiki_preflight"
            and "paper_wiki_status=loaded" in event["detail"]
            and "warnings=snapshot_stale" in event["detail"]
            for event in checkpoint_data["history"]
        )

    def test_demo_seed_pool_reuses_loaded_research_wiki_preflight_after_analyze(
        self, setup_db
    ):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["paper_production_run_policy"] = {
            "schema_version": "rh.paper_production_run_policy.v1",
            "autonomous_completion": True,
            "mode": "demo",
            "evidence_boundary": "demo_limited_seed_pool",
            "external_actions": [],
        }
        checkpoint_data["stage_context"]["research_wiki_preflight"] = {
            "schema_version": "research_wiki_preflight.v1",
            "topic_id": 1,
            "stage": "analyze",
            "action_name": "science_discovery",
            "paper_wiki_status": "loaded",
            "status_reason": "wiki_context_pack_loaded",
            "priority_evidence_layer": "research_wiki",
            "fallback_allowed": False,
            "fallback_must_be_declared": True,
            "must_not_silent_markdown_fallback": True,
            "degraded": True,
            "warning_codes": ["snapshot_stale"],
            "page_count": 8,
            "evidence_anchor_count": 8,
            "unavailable_reasons": [],
        }

        def fake_dispatch_ok(**kwargs):
            summary = kwargs["checkpoint_data"]["stage_context"][
                "research_wiki_preflight"
            ]
            assert summary["stage"] == "propose"
            assert summary["action_name"] == "experiment_design"
            assert summary["status_reason"] == "reused_from_analyze_preflight"
            return {
                "summary": "Stage propose: reused wiki preflight",
                "tool_results": [],
                "errors": [],
            }

        with (
            patch(
                "research_harness.auto_runner.stage_executor.run_research_wiki_preflight",
                side_effect=AssertionError("must not rebuild wiki preflight"),
            ) as preflight_mock,
            patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                side_effect=fake_dispatch_ok,
            ),
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                mode="demo",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        assert result["status"] == "complete"
        preflight_mock.assert_not_called()
        assert any(
            event["event"] == "research_wiki_preflight_reused"
            and "from_stage=analyze" in event["detail"]
            and "to_stage=propose" in event["detail"]
            for event in checkpoint_data["history"]
        )

    def test_demo_seed_pool_analyze_still_builds_research_wiki_preflight(
        self, setup_db
    ):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["paper_production_run_policy"] = {
            "schema_version": "rh.paper_production_run_policy.v1",
            "autonomous_completion": True,
            "mode": "demo",
            "evidence_boundary": "demo_limited_seed_pool",
            "external_actions": [],
        }

        def fake_preflight(**kwargs):
            return {
                "schema_version": "research_wiki_preflight.v1",
                "topic_id": kwargs["topic_id"],
                "stage": kwargs["stage"],
                "action_name": "science_discovery",
                "paper_wiki_status": "loaded",
                "status_reason": "wiki_context_pack_loaded",
                "priority_evidence_layer": "research_wiki",
                "fallback_allowed": False,
                "fallback_must_be_declared": True,
                "must_not_silent_markdown_fallback": True,
                "degraded": False,
                "warning_codes": [],
                "page_count": 1,
                "evidence_anchor_count": 1,
                "unavailable_reasons": [],
            }

        with (
            patch(
                "research_harness.auto_runner.stage_executor.run_research_wiki_preflight",
                side_effect=fake_preflight,
            ) as preflight_mock,
            patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                return_value={
                    "summary": "Stage analyze: preflight built",
                    "tool_results": [],
                    "errors": [],
                },
            ),
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="analyze",
                mode="demo",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        assert result["status"] == "complete"
        preflight_mock.assert_called_once()

    def test_paper_production_local_only_context_survives_stage_reset(self, setup_db):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.paper_production_context import (
            build_paper_production_runtime_context,
        )
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        runtime_context = build_paper_production_runtime_context(
            topic="Evidence-grounded AI agents for literature review",
            target_venue="NeurIPS 2026",
            local_only=True,
        )
        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["paper_production_run_policy"] = {
            "schema_version": "rh.paper_production_run_policy.v1",
            "autonomous_completion": True,
            "stop_on_gate_failure": True,
            "local_only": True,
            "external_actions": [],
        }
        checkpoint_data["stage_context"].update(runtime_context.to_stage_context())
        checkpoint_data["stage_context"]["paper_production_runtime_context"] = (
            runtime_context.to_dict()
        )

        def fake_dispatch_ok(**kwargs):
            context = kwargs["checkpoint_data"]["stage_context"]
            evidence_plan = context["paper_production_evidence_plan"]
            search_params = evidence_plan["search_parameters"]
            assert context["local_only"] is True
            assert search_params["local_only"] is True
            assert search_params["provider_allowlist"] == []
            assert search_params["provider_denylist"] == ["pasa"]
            return {
                "summary": "Stage build: local-only context preserved",
                "tool_results": [
                    {"tool": "paper_search", "success": True, "error": ""},
                ],
                "errors": [],
            }

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_ok,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="build",
                mode="demo",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        assert result["status"] == "complete"

    def test_paper_production_policy_blocks_write_without_pdf_and_pack(self, setup_db):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["paper_production_run_policy"] = {
            "schema_version": "rh.paper_production_run_policy.v1",
            "autonomous_completion": True,
            "stop_on_gate_failure": True,
            "external_actions": [],
        }
        svc.record_artifact(
            topic_id=1,
            stage="write",
            artifact_type="final_bundle",
            title="Draft bundle",
            payload={"status": "draft", "sections": ["abstract"]},
        )
        svc.record_artifact(
            topic_id=1,
            stage="write",
            artifact_type="process_summary",
            title="Process summary",
            payload={"sections_count": 1},
        )

        def fake_dispatch_ok(**kwargs):
            return {
                "summary": "Stage write: paper-production closure completed",
                "tool_results": [],
                "errors": [],
            }

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_ok,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="write",
                mode="demo",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        assert result["status"] == "error"
        assert checkpoint_data["stage_state"] == "error"
        gate = result["paper_production_completion_gate"]
        assert gate["status"] == "blocked"
        assert "final_bundle_is_draft" in gate["blockers"]
        assert "missing_publication_pack" in gate["blockers"]

    def test_paper_production_policy_blocks_under_threshold_final_bundle(
        self, setup_db
    ):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["paper_production_run_policy"] = {
            "schema_version": "rh.paper_production_run_policy.v1",
            "autonomous_completion": True,
            "stop_on_gate_failure": True,
            "external_actions": [],
        }
        svc.record_artifact(
            topic_id=1,
            stage="write",
            artifact_type="final_bundle",
            title="Final bundle",
            payload={
                "pdf_path": str(tmp_path / "paper.pdf"),
                "finality_status": "final_ready",
                "reference_pool_evidence": {
                    "passed": False,
                    "usable_screened_paper_count": 12,
                    "minimum_required": 40,
                },
            },
        )
        svc.record_artifact(
            topic_id=1,
            stage="write",
            artifact_type="publication_pack",
            title="Publication pack",
            payload={"status": "ready"},
        )
        svc.record_artifact(
            topic_id=1,
            stage="write",
            artifact_type="process_summary",
            title="Process summary",
            payload={"sections_count": 6},
        )

        def fake_dispatch_ok(**kwargs):
            return {"summary": "ok", "tool_results": [], "errors": []}

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_ok,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="write",
                mode="demo",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        assert result["status"] == "error"
        gate = result["paper_production_completion_gate"]
        assert "final_bundle_reference_pool_below_final_threshold" in gate["blockers"]

    def test_paper_production_policy_allows_autonomous_write_completion_with_pdf_pack(
        self, setup_db
    ):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["paper_production_run_policy"] = {
            "schema_version": "rh.paper_production_run_policy.v1",
            "autonomous_completion": True,
            "stop_on_gate_failure": True,
            "external_actions": [],
        }
        pdf_path = tmp_path / "paper.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
        svc.record_artifact(
            topic_id=1,
            stage="write",
            artifact_type="final_bundle",
            title="Final bundle",
            payload={"pdf_path": str(pdf_path)},
        )
        svc.record_artifact(
            topic_id=1,
            stage="write",
            artifact_type="publication_pack",
            title="Publication pack",
            payload={"status": "ready"},
        )
        svc.record_artifact(
            topic_id=1,
            stage="write",
            artifact_type="process_summary",
            title="Process summary",
            payload={"sections_count": 6},
        )

        def fake_dispatch_ok(**kwargs):
            return {
                "summary": "Stage write: paper-production closure completed",
                "tool_results": [],
                "errors": [],
            }

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_ok,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="write",
                mode="demo",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        assert result["status"] == "complete"
        assert checkpoint_data["stage_state"] == "complete"

    def test_execute_stage_tools_enforces_checkpoint_runtime_contract(self, setup_db):
        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import _execute_stage_tools
        from research_harness.runtime import (
            CapabilityManifest,
            RunSpec,
            RunVisibleInputs,
        )

        db, svc, _tmp_path = setup_db
        capability = CapabilityManifest(
            name="build-capability",
            version="0.1.0",
            capability_type="evaluator",
            owner="core",
            license="MIT",
            input_schema="rh.schema.input.build_capability.v0",
            output_schema="rh.schema.artifact.build_report.v0",
            allowed_tools=("paper_list",),
            required_artifacts=("topic_brief",),
            produced_artifacts=("build_report",),
            guardrails=("topic_brief_required",),
        )
        spec = RunSpec(
            run_id="run.build.blocked",
            task_type="evaluation",
            topic_id=1,
            objective="Verify checkpoint runtime contract gates stage tools.",
            visible_inputs=RunVisibleInputs(
                artifact_refs=("artifact:topic_brief:1",),
            ),
            required_outputs=("build_report",),
            capability_policy={
                "allowed_capabilities": ("build-capability",),
                "allowed_tools": ("paper_list",),
            },
            guardrails={"input": ("topic_brief_required",)},
        )
        checkpoint_data = ckpt.new_checkpoint(1)
        checkpoint_data["runtime_contract"] = {
            "capability_manifest": capability.to_dict(),
            "run_spec": spec.to_dict(),
        }

        result = _execute_stage_tools(
            db=db,
            svc=svc,
            topic_id=1,
            stage="build",
            checkpoint_data=checkpoint_data,
        )

        assert result["runtime_gate"]["passed"] is False
        assert result["tool_results"][0]["tool"] == "runtime_contract"
        assert "capability_allowed_tools" in result["errors"][0]

    def test_execute_stage_tools_materializes_and_executes_skill_runtime_contract(
        self, setup_db
    ):
        from pathlib import Path

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import _execute_stage_tools
        from research_harness.orchestrator.artifacts import ArtifactManager

        db, svc, tmp_path = setup_db
        tex_path = tmp_path / "paper.tex"
        pdf_path = tmp_path / "paper.pdf"
        log_path = tmp_path / "paper.log"
        tex_path.write_text(
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "Auto-runner skill execution.\n"
            "\\end{document}\n",
            encoding="utf-8",
        )
        pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
        log_path.write_text("", encoding="utf-8")
        final_bundle = svc.record_artifact(
            topic_id=1,
            stage="write",
            artifact_type="final_bundle",
            title="Final bundle",
            payload={
                "tex_path": str(tex_path),
                "compiled_pdf_path": str(pdf_path),
                "log_path": str(log_path),
                "target_profile": "AAAI-style-science-discovery",
            },
        )
        repo_root = next(
            p
            for p in Path(__file__).resolve().parents
            if (p / "skills" / "final-bundle-quality" / "skill.yaml").is_file()
        )
        checkpoint_data = ckpt.new_checkpoint(1)
        checkpoint_data["runtime_contract"] = {
            "skill_name": "final-bundle-quality",
            "skills_root": str(repo_root),
            "artifact_refs": (f"artifact:final_bundle:{final_bundle.id}",),
            "objective": "Evaluate a final_bundle through its v2 skill package.",
            "literal_inputs": {"mode": "quality_scan"},
            "run_id": "run.final_bundle_quality.auto",
        }

        result = _execute_stage_tools(
            db=db,
            svc=svc,
            topic_id=1,
            stage="build",
            checkpoint_data=checkpoint_data,
        )

        assert result["runtime_gate"]["passed"] is True
        assert result["errors"] == []
        assert result["tool_results"][0]["tool"] == "final-bundle-quality"
        assert result["tool_results"][0]["success"] is True
        report_id = result["tool_results"][0]["output"]["artifact_id"]
        report = ArtifactManager(db).get(report_id)
        assert report is not None
        assert report.artifact_type == "final_bundle_quality_report"
        assert report.payload["source_artifact_id"] == final_bundle.id
        materialized = checkpoint_data["runtime_contract"]
        assert materialized["execute_skill"] is True
        assert materialized["capability_manifest"]["name"] == "final-bundle-quality"
        assert materialized["run_spec"]["run_id"] == "run.final_bundle_quality.auto"
        assert materialized["run_spec"]["required_outputs"] == [
            "final_bundle_quality_report"
        ]


class TestCheckpointAtomicity:
    def test_atomic_write_produces_valid_json(self, tmp_path):
        path = tmp_path / "atomic_test.json"
        cp = new_checkpoint(1)
        save_checkpoint(path, cp)
        loaded = load_checkpoint(path)
        assert loaded is not None
        assert loaded["topic_id"] == 1

    def test_no_partial_write_on_disk(self, tmp_path):
        """Verify no .tmp files remain after successful write."""
        import glob

        path = tmp_path / "atomic_test2.json"
        cp = new_checkpoint(1)
        save_checkpoint(path, cp)
        tmp_files = glob.glob(str(tmp_path / "*.tmp"))
        assert len(tmp_files) == 0


class TestBudgetWallClockResume:
    def test_cumulative_elapsed_persists(self):
        from research_harness.auto_runner.budget import BudgetLimits, BudgetMonitor

        monitor = BudgetMonitor(BudgetLimits(max_wall_time_min=60))
        monitor._cumulative_elapsed_min = 30.0
        data = monitor.to_dict()
        assert data["cumulative_elapsed_min"] >= 30.0

        restored = BudgetMonitor.from_checkpoint(
            data, BudgetLimits(max_wall_time_min=60)
        )
        assert restored._cumulative_elapsed_min >= 30.0

    def test_budget_sync_from_provenance(self, tmp_path):
        from research_harness.auto_runner.budget import BudgetMonitor
        from research_harness.storage.db import Database

        db = Database(tmp_path / "budget.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO topics (name, description) VALUES ('t', 't')",
            )
            conn.execute(
                """INSERT INTO provenance_records
                   (primitive, started_at, finished_at, backend, model_used,
                    topic_id, success, cost_usd, input_hash, output_hash)
                   VALUES ('test_prim', datetime('now'), datetime('now'), 'test', 'test',
                    1, 1, 0.05, 'h1', 'h2')""",
            )
            conn.commit()
        finally:
            conn.close()

        monitor = BudgetMonitor()
        monitor.sync_from_provenance(db, topic_id=1)
        assert monitor.state.total_cost_usd == 0.05
        assert monitor.state.total_tool_calls == 1


class TestPaperProductionRunnerGates:
    def test_local_only_execute_reports_evidence_gate_instead_of_raw_approval(
        self, tmp_path
    ):
        from research_harness.auto_runner.paper_production_entry import (
            prepare_paper_production_entry,
            run_paper_production_entry,
        )
        from research_harness.storage.db import Database

        db = Database(tmp_path / "paper-production-runner.db")
        db.migrate()
        base_dir = tmp_path / ".research-harness"
        prepared = prepare_paper_production_entry(
            db=db,
            base_dir=base_dir,
            topic="Evidence-grounded AI agents for literature review",
            target_venue="NeurIPS 2026",
            mode="demo",
            local_only=True,
        )

        result = run_paper_production_entry(
            db=db,
            base_dir=base_dir,
            topic=prepared["topic"]["name"],
            target_venue=prepared["topic"]["target_venue"],
            mode="demo",
            dry_run=False,
            auto_approve=True,
            local_only=True,
        )

        runner = result["runner"]
        assert runner["status"] == "blocked"
        assert runner["blocker_code"] == "paper_production_evidence_gate"
        assert runner["current_stage"] == "init"
        assert runner["paper_production_gate"]["next_stage"] == (
            "PW02_EVIDENCE_ACQUISITION_AND_READING"
        )
        assert "insufficient_seed_papers" in runner["paper_production_gate"]["blockers"]
        assert result["external_actions"] == []

    def test_demo_gate_override_advances_analyze_with_required_demo_artifacts(
        self, tmp_path
    ):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_topic
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "paper-production-demo-override.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'p', 'p')"
            )
            conn.commit()
        finally:
            conn.close()

        svc = OrchestratorService(db)
        svc.resume_run(1, mode="demo", force_stage="analyze")
        for artifact_type in (
            "claim_candidate_set",
            "evidence_pack",
            "baseline_matrix",
            "direction_proposal",
        ):
            svc.record_artifact(
                topic_id=1,
                stage="analyze",
                artifact_type=artifact_type,
                title=artifact_type,
                payload={
                    "submission_readiness": "not_submission_ready",
                    "evidence_boundary": "demo_limited_seed_pool",
                },
            )

        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["current_stage"] = "analyze"
        checkpoint_data["paper_production_run_policy"] = {
            "schema_version": "rh.paper_production_run_policy.v1",
            "autonomous_completion": True,
            "mode": "demo",
            "evidence_boundary": "demo_limited_seed_pool",
            "external_actions": [],
        }
        ckpt.save_checkpoint(
            tmp_path / "auto_runner/checkpoints/topic_1.json",
            checkpoint_data,
        )

        def fake_execute_stage(**kwargs):
            stage = str(kwargs.get("stage") or "")
            if stage == "propose":
                return {
                    "status": "needs_human",
                    "stage": "propose",
                    "summary": "stop after demo override",
                }
            return {
                "status": "complete",
                "stage": stage,
                "summary": f"demo {stage} complete",
            }

        with patch(
            "research_harness.auto_runner.runner.execute_stage",
            side_effect=fake_execute_stage,
        ):
            result = run_topic(
                1,
                mode="demo",
                auto_approve=True,
                base_dir=tmp_path,
                db=db,
            )

        assert result["status"] == "paused"
        assert result["current_stage"] == "propose"
        assert svc.get_run(1).current_stage == "propose"
        saved = ckpt.load_checkpoint(tmp_path / "auto_runner/checkpoints/topic_1.json")
        assert saved is not None
        assert any(
            item.get("event") == "paper_production_demo_gate_override"
            for item in saved.get("history", [])
        )


class TestDeferredToolsExclusion:
    """Deferred tools (LLM-constructed args) should not count as 'all failed'."""

    def test_deferred_tools_excluded_from_all_failed(self, tmp_path):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "deferred.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'p', 'p')"
            )
            conn.commit()
        finally:
            conn.close()
        svc = OrchestratorService(db)
        svc.resume_run(1)
        checkpoint_data = ckpt.new_checkpoint(1)

        def fake_dispatch_mixed(**kwargs):
            return {
                "summary": "Stage propose: 1/3 tools succeeded",
                "tool_results": [
                    {"tool": "paper_search", "success": True, "error": ""},
                    {"tool": "adversarial_run", "success": False, "error": "deferred"},
                    {
                        "tool": "adversarial_resolve",
                        "success": False,
                        "error": "deferred",
                    },
                ],
                "errors": [
                    "adversarial_run: deferred",
                    "adversarial_resolve: deferred",
                ],
            }

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_mixed,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        # Should NOT trigger all-failed recovery because non-deferred tools succeeded
        assert result["status"] != "retry"
        assert result["status"] != "fallback_stage"


class TestRetryBoundInRunner:
    """Runner loop must respect max_retries to prevent unbounded loops."""

    def test_retry_limit_enforced(self):
        from research_harness.auto_runner.stage_policy import max_retries

        # build has retry_twice → max 2
        assert max_retries("build") == 2
        # Attempt 3 should exceed limit (attempt > limit + 1)
        # This is verified in runner.py: attempt > limit + 1 → error


class TestCodexScopedByStage:
    """Codex handoff verdict is scoped by stage to prevent cross-stage leakage."""

    def test_verdict_for_different_stage_not_reused(self):
        from research_harness.auto_runner.checkpoint import (
            clear_codex_handoff,
            new_checkpoint,
            set_codex_handoff,
        )

        cp = new_checkpoint(1)
        set_codex_handoff(
            cp,
            stage="propose",
            request_path="/tmp/req.json",
            response_path="/tmp/resp.json",
        )
        clear_codex_handoff(cp, verdict="approve")

        # The verdict is for "propose" — should not match "write"
        handoff = cp["codex_handoff"]
        assert handoff["verdict"] == "approve"
        assert handoff["stage"] == "propose"
        # A different stage check should not match
        assert not (handoff.get("verdict") and handoff.get("stage") == "write")


class TestCodexReviseVerdictBlocks:
    """Codex 'revise' verdict on required stages must block advancement."""

    def test_revise_on_required_stage_returns_needs_human(self, tmp_path):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "codex_revise.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'p', 'p')"
            )
            conn.commit()
        finally:
            conn.close()
        svc = OrchestratorService(db)
        svc.resume_run(1)
        checkpoint_data = ckpt.new_checkpoint(1)

        # Record a fake artifact so codex has something to review
        ckpt.record_artifact(
            checkpoint_data,
            stage="propose",
            artifact_type="direction_proposal",
            artifact_id=42,
        )

        def fake_dispatch_ok(**kwargs):
            return {
                "summary": "Stage propose: 2/2 tools succeeded",
                "tool_results": [
                    {"tool": "paper_search", "success": True, "error": ""},
                    {
                        "tool": "orchestrator_record_artifact",
                        "success": True,
                        "error": "",
                    },
                ],
                "errors": [],
            }

        fake_review = {
            "success": True,
            "verdict": "revise",
            "issues": [
                {
                    "severity": "major",
                    "category": "novelty",
                    "target": "method",
                    "reasoning": "not novel enough",
                }
            ],
            "scores": {"novelty": 3.0},
            "notes": "needs more work",
        }

        with (
            patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                side_effect=fake_dispatch_ok,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.run_codex_review",
                return_value=fake_review,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.save_handoff_request",
            ),
            patch(
                "research_harness.auto_runner.stage_executor.save_handoff_response",
            ),
            patch(
                "research_harness.auto_runner.stage_executor.load_handoff_response",
                return_value=None,
            ),
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        # Codex returned "revise" on required stage → must block
        assert result["status"] == "needs_human"
        assert (
            "revision" in result["summary"].lower()
            or "revise" in result["summary"].lower()
        )
        assert len(result.get("codex_issues", [])) == 1

    def test_paper_production_demo_revise_records_revision_and_continues(
        self, tmp_path
    ):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "codex_revise_auto.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'p', 'p')"
            )
            conn.commit()
        finally:
            conn.close()
        svc = OrchestratorService(db)
        svc.resume_run(1)
        original = svc.record_artifact(
            topic_id=1,
            stage="propose",
            artifact_type="direction_proposal",
            title="Runoff diagnostics",
            payload={
                "direction": "Map Noah-MP VIC runoff code paths to diagnostics.",
                "research_question": "Can runoff diagnostics be reconstructed?",
                "study_spec": "Compare reconstructed diagnostics against baselines.",
            },
        )
        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["paper_production_run_policy"] = {
            "schema_version": "rh.paper_production_run_policy.v1",
            "autonomous_completion": True,
            "mode": "demo",
            "evidence_boundary": "demo_limited_seed_pool",
            "external_actions": [],
        }
        ckpt.record_artifact(
            checkpoint_data,
            stage="propose",
            artifact_type="direction_proposal",
            artifact_id=original.id,
        )

        def fake_dispatch_ok(**kwargs):
            return {
                "summary": "Stage propose: tools succeeded",
                "tool_results": [
                    {"tool": "paper_search", "success": True, "error": ""}
                ],
                "errors": [],
            }

        fake_review = {
            "success": True,
            "verdict": "revise",
            "issues": [
                {
                    "severity": "critical",
                    "category": "method_validity",
                    "target": "required inputs",
                    "reasoning": "define reconstructible and non-reconstructible cases",
                    "suggested_fix": "Add required inputs and failure conditions.",
                },
                {
                    "severity": "major",
                    "category": "falsifiability",
                    "target": "acceptance criteria",
                    "reasoning": "no measurable success criteria",
                    "suggested_fix": "Add tolerance-based acceptance criteria.",
                },
            ],
            "scores": {"method_validity": 2.0},
            "notes": "revise before approval",
        }

        with (
            patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                side_effect=fake_dispatch_ok,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.run_codex_review",
                return_value=fake_review,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.save_handoff_request",
            ),
            patch(
                "research_harness.auto_runner.stage_executor.save_handoff_response",
            ),
            patch(
                "research_harness.auto_runner.stage_executor.load_handoff_response",
                return_value=None,
            ),
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                mode="demo",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        assert result["status"] == "complete"
        latest_proposal = svc.get_latest_artifact(1, "propose", "direction_proposal")
        assert latest_proposal is not None
        assert latest_proposal.id != original.id
        assert latest_proposal.parent_artifact_id == original.id
        assert latest_proposal.payload["codex_revision"]["verdict"] == "revise"
        assert latest_proposal.payload["revision_plan"][0]["category"] == (
            "method_validity"
        )
        revision_record = svc.get_latest_artifact(1, "propose", "codex_revision")
        assert revision_record is not None
        assert revision_record.payload["superseded_artifact_id"] == original.id
        assert (
            checkpoint_data["artifacts"]["propose"]["direction_proposal"]["artifact_id"]
            == latest_proposal.id
        )
        assert any(
            event["event"] == "codex_revision_applied" and "issues=2" in event["detail"]
            for event in checkpoint_data["history"]
        )

    def test_codex_review_receives_materialized_artifact_payload(self, tmp_path):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "codex_payload.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'p', 'p')"
            )
            conn.commit()
        finally:
            conn.close()
        svc = OrchestratorService(db)
        svc.resume_run(1)
        artifact = svc.record_artifact(
            topic_id=1,
            stage="analyze",
            artifact_type="direction_proposal",
            title="Sparse-evidence runoff diagnostics",
            payload={
                "research_question": "Can runoff diagnostics be reconstructed?",
                "methodology": "Compare VIC and Noah-MP diagnostic traces.",
            },
        )
        checkpoint_data = ckpt.new_checkpoint(1)
        ckpt.record_artifact(
            checkpoint_data,
            stage="analyze",
            artifact_type="direction_proposal",
            artifact_id=artifact.id,
        )
        captured: dict[str, str] = {}

        def fake_dispatch_ok(**kwargs):
            return {
                "summary": "Stage propose: tools succeeded",
                "tool_results": [
                    {"tool": "paper_search", "success": True, "error": ""}
                ],
                "errors": [],
            }

        def fake_run_codex_review(**kwargs):
            captured["artifact_path"] = str(kwargs["artifact_path"])
            captured["evidence_summary"] = kwargs["evidence_summary"]
            return {
                "success": True,
                "verdict": "approve",
                "issues": [],
                "scores": {},
                "notes": "visible artifact payload",
            }

        with (
            patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                side_effect=fake_dispatch_ok,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.run_codex_review",
                side_effect=fake_run_codex_review,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.load_handoff_response",
                return_value=None,
            ),
        ):
            execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        assert captured["artifact_path"] == f"artifact:{artifact.id}"
        assert "Sparse-evidence runoff diagnostics" in captured["evidence_summary"]
        assert (
            "Can runoff diagnostics be reconstructed?" in captured["evidence_summary"]
        )
        assert (
            "Compare VIC and Noah-MP diagnostic traces" in captured["evidence_summary"]
        )

    def test_approve_on_required_stage_continues(self, tmp_path):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "codex_approve.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'p', 'p')"
            )
            conn.commit()
        finally:
            conn.close()
        svc = OrchestratorService(db)
        svc.resume_run(1)
        checkpoint_data = ckpt.new_checkpoint(1)

        ckpt.record_artifact(
            checkpoint_data,
            stage="propose",
            artifact_type="direction_proposal",
            artifact_id=42,
        )

        def fake_dispatch_ok(**kwargs):
            return {
                "summary": "Stage propose: 2/2 tools succeeded",
                "tool_results": [
                    {"tool": "paper_search", "success": True, "error": ""},
                ],
                "errors": [],
            }

        fake_review = {
            "success": True,
            "verdict": "approve",
            "issues": [],
            "scores": {"novelty": 8.0},
            "notes": "looks good",
        }

        with (
            patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                side_effect=fake_dispatch_ok,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.run_codex_review",
                return_value=fake_review,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.save_handoff_request",
            ),
            patch(
                "research_harness.auto_runner.stage_executor.save_handoff_response",
            ),
            patch(
                "research_harness.auto_runner.stage_executor.load_handoff_response",
                return_value=None,
            ),
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        # Codex approved on required stage → propose has human_checkpoint=always → needs_human
        assert result["status"] == "needs_human"


class TestStaleDemoPolicyGuards:
    """A demo policy left by a smoke run must not govern a formal resume.

    Topic 38 (EchoFormer/AAAI) incident: checkpoint mode was synced to
    strict but paper_production_run_policy.mode stayed "demo", so a formal
    rerun inherited demo gate overrides and demo-scoped skip artifacts.
    """

    def _db_with_topic(self, tmp_path, name):
        from research_harness.storage.db import Database

        db = Database(tmp_path / f"{name}.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) "
                "VALUES (1, 'p', 'p')"
            )
            conn.commit()
        finally:
            conn.close()
        return db

    def _demo_policy(self, schema="rh.paper_production_run_policy.v1"):
        return {
            "schema_version": schema,
            "autonomous_completion": True,
            "stop_on_gate_failure": True,
            "mode": "demo",
            "evidence_boundary": "demo_limited_seed_pool",
            "external_actions": [],
        }

    def test_sync_clears_stale_demo_policy_for_strict_run(self, tmp_path):
        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import (
            _sync_checkpoint_with_orchestrator,
        )
        from research_harness.orchestrator.service import OrchestratorService

        db = self._db_with_topic(tmp_path, "stale-demo-strict")
        svc = OrchestratorService(db)
        svc.resume_run(1, mode="strict", force_stage="write")

        checkpoint_data = ckpt.new_checkpoint(1, mode="strict")
        checkpoint_data["current_stage"] = "write"
        checkpoint_data["paper_production_run_policy"] = self._demo_policy()
        checkpoint_data.setdefault("stage_context", {})[
            "paper_production_run_policy"
        ] = self._demo_policy()

        changed = _sync_checkpoint_with_orchestrator(
            checkpoint_data=checkpoint_data, svc=svc, topic_id=1
        )

        assert changed is True
        assert "paper_production_run_policy" not in checkpoint_data
        assert "paper_production_run_policy" not in checkpoint_data["stage_context"]
        assert any(
            item.get("event") == "stale_demo_policy_cleared"
            for item in checkpoint_data.get("history", [])
        )

    def test_sync_keeps_demo_policy_for_demo_run(self, tmp_path):
        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import (
            _sync_checkpoint_with_orchestrator,
        )
        from research_harness.orchestrator.service import OrchestratorService

        db = self._db_with_topic(tmp_path, "stale-demo-demo")
        svc = OrchestratorService(db)
        svc.resume_run(1, mode="demo", force_stage="write")

        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["current_stage"] = "write"
        checkpoint_data["paper_production_run_policy"] = self._demo_policy()

        _sync_checkpoint_with_orchestrator(
            checkpoint_data=checkpoint_data, svc=svc, topic_id=1
        )

        assert checkpoint_data["paper_production_run_policy"]["mode"] == "demo"

    def test_demo_override_refused_when_checkpoint_mode_not_demo(self, tmp_path):
        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import (
            _paper_production_demo_gate_override,
        )
        from research_harness.orchestrator.service import OrchestratorService

        db = self._db_with_topic(tmp_path, "override-ckpt-strict")
        svc = OrchestratorService(db)
        svc.resume_run(1, mode="demo", force_stage="analyze")

        checkpoint_data = ckpt.new_checkpoint(1, mode="strict")
        checkpoint_data["paper_production_run_policy"] = self._demo_policy()

        override = _paper_production_demo_gate_override(
            svc=svc,
            topic_id=1,
            stage="analyze",
            gate_decision="fail",
            checkpoint_data=checkpoint_data,
        )

        assert override is None

    def test_demo_override_refused_when_run_mode_not_demo(self, tmp_path):
        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import (
            _paper_production_demo_gate_override,
        )
        from research_harness.orchestrator.service import OrchestratorService

        db = self._db_with_topic(tmp_path, "override-run-strict")
        svc = OrchestratorService(db)
        svc.resume_run(1, mode="strict", force_stage="analyze")

        checkpoint_data = ckpt.new_checkpoint(1, mode="demo")
        checkpoint_data["paper_production_run_policy"] = self._demo_policy()

        override = _paper_production_demo_gate_override(
            svc=svc,
            topic_id=1,
            stage="analyze",
            gate_decision="fail",
            checkpoint_data=checkpoint_data,
        )

        assert override is None

    def test_paper_production_policy_accepts_v2_schema(self):
        from research_harness.auto_runner.runner import _paper_production_policy

        checkpoint_data = {
            "paper_production_run_policy": self._demo_policy(
                schema="rh.paper_production_run_policy.v2"
            )
        }
        assert _paper_production_policy(checkpoint_data)["mode"] == "demo"
