"""Tests for auto_runner/llm_planner — LLM-driven stage context generation."""

from __future__ import annotations

import json

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


from research_harness.auto_runner.llm_planner import (
    _call_planner_llm,
    _gather_topic_meta,
    _get_paper_count,
    _get_top_papers,
    _plan_analyze,
    _plan_build,
    _plan_experiment,
    _plan_propose,
    _plan_write,
    plan_stage,
)
from research_harness.storage.db import Database


def _make_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "planner_test.db")
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, target_venue) "
            "VALUES ('multimodal-ts', 'Multimodal time series forecasting', 'KDD')"
        )
        # Bridge row for FK on project_artifacts.project_id
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) "
            "VALUES (1, 1, 'proj1', 'test project')"
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _add_papers(db: Database, topic_id: int, n: int = 5) -> list[int]:
    conn = db.connect()
    ids = []
    try:
        for i in range(n):
            cur = conn.execute(
                "INSERT INTO papers (title, year, venue, citation_count, s2_id, doi, arxiv_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"Paper {i}",
                    2024,
                    "NeurIPS",
                    100 - i * 10,
                    f"s2_{topic_id}_{i}",
                    f"10.1234/{topic_id}.{i}",
                    f"2401.{topic_id:02d}{i:03d}",
                ),
            )
            pid = cur.lastrowid
            ids.append(pid)
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
                (pid, topic_id, "high"),
            )
        conn.commit()
    finally:
        conn.close()
    return ids


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


class TestDBHelpers:
    def test_gather_topic_meta(self, tmp_path):
        db = _make_db(tmp_path)
        meta = _gather_topic_meta(db, 1)
        assert meta["name"] == "multimodal-ts"
        assert meta["target_venue"] == "KDD"

    def test_gather_topic_meta_missing(self, tmp_path):
        db = _make_db(tmp_path)
        meta = _gather_topic_meta(db, 999)
        assert meta["name"] == ""

    def test_get_paper_count(self, tmp_path):
        db = _make_db(tmp_path)
        _add_papers(db, 1, n=3)
        assert _get_paper_count(db, 1) == 3
        assert _get_paper_count(db, 999) == 0

    def test_get_top_papers(self, tmp_path):
        db = _make_db(tmp_path)
        _add_papers(db, 1, n=5)
        papers = _get_top_papers(db, 1, limit=3)
        assert len(papers) == 3
        assert papers[0]["citation_count"] >= papers[1]["citation_count"]


# ---------------------------------------------------------------------------
# plan_stage dispatch
# ---------------------------------------------------------------------------


class TestPlanStageDispatch:
    def test_init_returns_topic_meta(self, tmp_path):
        db = _make_db(tmp_path)
        svc = MagicMock()
        result = plan_stage(
            db=db,
            svc=svc,
            topic_id=1,
            stage="init",
            checkpoint_data={},
        )
        assert result["topic_description"]
        assert result["query"]
        assert result["topic_id"] == 1

    def test_unknown_stage_returns_empty(self, tmp_path):
        db = _make_db(tmp_path)
        svc = MagicMock()
        result = plan_stage(
            db=db,
            svc=svc,
            topic_id=1,
            stage="unknown_stage",
            checkpoint_data={},
        )
        assert result == {}

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_planner_failure_preserves_paper_production_context(
        self, mock_llm, tmp_path
    ):
        mock_llm.side_effect = RuntimeError("LLM unavailable")
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = plan_stage(
            db=db,
            svc=svc,
            topic_id=1,
            stage="build",
            checkpoint_data={},
        )
        assert result["topic_id"] == 1
        assert result["target_venue"] == "KDD"
        assert result["query"] == "Multimodal time series forecasting"
        assert result["paper_production_context_status"] == (
            "ready_for_evidence_acquisition"
        )
        assert result["paper_production_runtime_context"]["schema_version"] == (
            "rh.paper_production_runtime_context.v1"
        )

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_paper_production_policy_local_only_controls_planner_context(
        self, mock_llm, tmp_path
    ):
        mock_llm.return_value = {"query": "planner generated query"}
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = plan_stage(
            db=db,
            svc=svc,
            topic_id=1,
            stage="build",
            checkpoint_data={
                "paper_production_run_policy": {
                    "schema_version": "rh.paper_production_run_policy.v1",
                    "local_only": True,
                }
            },
        )

        search_params = result["paper_production_evidence_plan"]["search_parameters"]
        assert result["local_only"] is True
        assert search_params["local_only"] is True
        assert search_params["provider_allowlist"] == []
        assert search_params["provider_denylist"] == ["pasa"]

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_plan_stage_sets_project_id(self, mock_llm, tmp_path):
        mock_llm.return_value = {"query": "test query"}
        db = _make_db(tmp_path)
        svc = MagicMock()
        result = plan_stage(
            db=db,
            svc=svc,
            topic_id=1,
            stage="build",
            checkpoint_data={},
        )
        assert result["topic_id"] == 1


# ---------------------------------------------------------------------------
# Per-stage planners
# ---------------------------------------------------------------------------


class TestPlanBuild:
    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_generates_query(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "query": "multimodal time series forecasting",
            "additional_queries": ["temporal fusion", "cross-modal attention"],
            "auto_ingest": True,
            "max_results": 500,
        }
        db = _make_db(tmp_path)
        result = _plan_build(
            db=db,
            svc=MagicMock(),
            topic_id=1,
            checkpoint_data={},
        )
        assert result["query"] == "multimodal time series forecasting"
        assert result["auto_ingest"] is True
        assert result["max_results"] == 500

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_fallback_on_empty_query(self, mock_llm, tmp_path):
        mock_llm.return_value = {}
        db = _make_db(tmp_path)
        result = _plan_build(
            db=db,
            svc=MagicMock(),
            topic_id=1,
            checkpoint_data={},
        )
        assert result["query"]  # falls back to topic description
        assert result["auto_ingest"] is True
        assert result["seed_top_n"] == 10

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_demo_seed_pool_bounds_build_planner_budget(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "query": "broad planner query",
            "max_results": 500,
            "seed_top_n": 10,
            "forward_limit": 50,
            "backward_limit": 50,
        }
        db = _make_db(tmp_path)

        result = _plan_build(
            db=db,
            svc=MagicMock(),
            topic_id=1,
            checkpoint_data={
                "paper_production_run_policy": {
                    "schema_version": "rh.paper_production_run_policy.v1",
                    "mode": "demo",
                    "evidence_boundary": "demo_limited_seed_pool",
                }
            },
        )

        assert result["max_results"] <= 40
        assert result["seed_top_n"] <= 5
        assert result["forward_limit"] <= 10
        assert result["backward_limit"] <= 10
        assert result["paper_acquire_limit"] <= 12
        assert result["submission_readiness"] == "not_submission_ready"


class TestPlanAnalyze:
    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_selects_papers(self, mock_llm, tmp_path):
        db = _make_db(tmp_path)
        paper_ids = _add_papers(db, 1, n=10)
        mock_llm.return_value = {
            "paper_ids": paper_ids[:5],
            "focus": "cross-modal attention mechanisms",
        }
        result = _plan_analyze(
            db=db,
            svc=MagicMock(),
            topic_id=1,
            checkpoint_data={},
        )
        assert len(result["paper_ids"]) == 5
        assert result["focus"] == "cross-modal attention mechanisms"

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_fallback_on_empty_paper_ids(self, mock_llm, tmp_path):
        db = _make_db(tmp_path)
        _paper_ids = _add_papers(db, 1, n=10)
        mock_llm.return_value = {}
        result = _plan_analyze(
            db=db,
            svc=MagicMock(),
            topic_id=1,
            checkpoint_data={},
        )
        assert len(result["paper_ids"]) > 0


class TestPlanPropose:
    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_reads_artifacts(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "artifact_type": "direction_proposal",
            "artifact_title": "ModalGate: Adaptive Gating",
            "artifact_payload": {"direction": "adaptive gating"},
            "focus": "gating mechanisms",
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_propose(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={},
        )
        assert result["artifact_type"] == "direction_proposal"
        assert result["artifact_title"] == "ModalGate: Adaptive Gating"

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_rejects_topic_drift_and_falls_back_to_analyze_direction(
        self, mock_llm, tmp_path
    ):
        """Propose must not replace a domain-specific analyze direction with an unrelated generic plan."""
        db, svc = _setup_integration_db(tmp_path)
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE topics SET name = ?, description = ?, target_venue = ? WHERE id = 1",
                (
                    "Reconstructing Noah-MP VIC runoff diagnostics from source excerpts and scenario data",
                    "Reconstructing Noah-MP VIC runoff diagnostics from source excerpts and scenario data",
                    "Journal of Hydrometeorology",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        svc.record_artifact(
            topic_id=1,
            stage="analyze",
            artifact_type="direction_proposal",
            title="Noah-MP/VIC diagnostic crosswalk",
            payload={
                "gaps": [
                    {
                        "description": "No source-code-level crosswalk defines how Noah-MP runoff diagnostics correspond to VIC-style runoff components."
                    }
                ],
                "research_question": (
                    "How can Noah-MP source excerpts and scenario data be used "
                    "to reconstruct VIC-style runoff diagnostics?"
                ),
            },
        )
        svc.record_artifact(
            topic_id=1,
            stage="analyze",
            artifact_type="baseline_matrix",
            title="Hydrology baselines",
            payload={
                "baselines": [
                    {"name": "Default Noah-MP"},
                    {"name": "VIC Variable Infiltration Capacity model"},
                ]
            },
        )
        mock_llm.return_value = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Robust Evaluation for Generalizable AI Systems",
            "artifact_payload": {
                "direction": "Improve AI robustness under distribution shift.",
                "research_question": "Which adaptation strategies improve AI reliability?",
            },
            "focus": "AI robustness",
            "study_spec": "Evaluate zero-shot and few-shot baselines on shifted benchmarks.",
        }

        result = _plan_propose(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={},
        )

        payload = result["artifact_payload"]
        combined = json.dumps(result, ensure_ascii=False).lower()
        assert result["artifact_title"].startswith("Reconstructing Noah-MP")
        assert "noah-mp" in combined
        assert "vic" in combined
        assert "runoff" in combined
        assert "ai robustness" not in combined
        assert payload["research_question"].startswith("How can Noah-MP")

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_demo_seed_pool_propose_uses_analyze_direction_without_llm(
        self, mock_llm, tmp_path
    ):
        db, svc = _setup_integration_db(tmp_path)
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE topics SET name = ?, description = ?, target_venue = ? WHERE id = 1",
                (
                    "Reconstructing Noah-MP VIC runoff diagnostics from source excerpts and scenario data",
                    "Reconstructing Noah-MP VIC runoff diagnostics from source excerpts and scenario data",
                    "Journal of Hydrometeorology",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        svc.record_artifact(
            topic_id=1,
            stage="analyze",
            artifact_type="direction_proposal",
            title="Research direction from gap analysis",
            payload={
                "gaps": [
                    {
                        "description": "Noah-MP and VIC runoff diagnostics lack a reproducible source-code-level crosswalk."
                    }
                ],
                "research_question": "How can Noah-MP source excerpts reconstruct VIC-style runoff diagnostics?",
            },
        )
        svc.record_artifact(
            topic_id=1,
            stage="analyze",
            artifact_type="baseline_matrix",
            title="Baseline matrix",
            payload={
                "baselines": [
                    {"name": "Default Noah-MP"},
                    {"name": "VIC Variable Infiltration Capacity model"},
                ]
            },
        )

        result = _plan_propose(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={
                "paper_production_run_policy": {
                    "schema_version": "rh.paper_production_run_policy.v1",
                    "mode": "demo",
                    "evidence_boundary": "demo_limited_seed_pool",
                }
            },
        )

        mock_llm.assert_not_called()
        assert result["planner_fallback_reason"] == "demo_limited_seed_pool"
        combined = json.dumps(result, ensure_ascii=False).lower()
        assert "noah-mp" in combined
        assert "vic" in combined
        assert "runoff" in combined


class TestPlanExperiment:
    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_demo_seed_pool_experiment_uses_deterministic_smoke_plan_without_llm(
        self, mock_llm, tmp_path
    ):
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None

        result = _plan_experiment(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={
                "paper_production_run_policy": {
                    "schema_version": "rh.paper_production_run_policy.v1",
                    "mode": "demo",
                    "evidence_boundary": "demo_limited_seed_pool",
                }
            },
        )

        mock_llm.assert_not_called()
        assert result["primary_metric"] == "execution_success"
        assert result["experiment_execution_mode"] == "deterministic_demo_smoke"
        assert result["submission_readiness"] == "not_submission_ready"
        assert result["claim_strength_limit"] == "evidence_limited_demo"
        assert "demo seed-pool smoke" in result["study_spec"].lower()

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_reads_study_spec(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "study_spec": "Implement ModalGate with 6 experiment groups",
            "primary_metric": "mse",
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_experiment(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={},
        )
        assert result["study_spec"] == "Implement ModalGate with 6 experiment groups"
        assert result["primary_metric"] == "mse"


class TestPlanWrite:
    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_generates_sections(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "venue": "KDD",
            "contributions": "We propose ModalGate...",
            "outline": "1. Intro 2. Related 3. Method 4. Experiments 5. Conclusion",
            "sections_to_draft": [
                "introduction",
                "related_work",
                "method",
                "experiments",
                "conclusion",
            ],
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_write(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={},
        )
        assert result["venue"] == "KDD"
        assert len(result["sections_to_draft"]) == 5
        assert "introduction" in result["sections_to_draft"]

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_fallback_sections(self, mock_llm, tmp_path):
        mock_llm.return_value = {}
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_write(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={},
        )
        assert len(result["sections_to_draft"]) == 5

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_demo_seed_pool_write_uses_deterministic_pdf_smoke_plan_without_llm(
        self, mock_llm, tmp_path
    ):
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None

        result = _plan_write(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={
                "paper_production_run_policy": {
                    "schema_version": "rh.paper_production_run_policy.v1",
                    "mode": "demo",
                    "evidence_boundary": "demo_limited_seed_pool",
                }
            },
        )

        mock_llm.assert_not_called()
        assert result["planner_fallback_reason"] == "demo_limited_seed_pool"
        assert result["paper_production_closure_mode"] == "deterministic_pdf_smoke"
        assert result["submission_readiness"] == "not_submission_ready"
        assert result["sections_to_draft"] == [
            "abstract",
            "method",
            "experiment_summary",
            "limitations",
        ]


# ---------------------------------------------------------------------------
# LLM call wrapper
# ---------------------------------------------------------------------------


class TestCallPlannerLLM:
    @patch(
        "research_harness.execution.llm_primitives._client_chat",
        return_value="This is not JSON at all {{",
    )
    @patch("research_harness.execution.llm_primitives._get_client")
    def test_bad_json_returns_empty(self, mock_get_client, mock_chat):
        """When LLM returns non-JSON, _call_planner_llm returns empty dict."""

        result = _call_planner_llm("test prompt")
        assert result == {}


# ---------------------------------------------------------------------------
# Integration: planner in executor
# ---------------------------------------------------------------------------


class TestPlannerInExecutor:
    def test_planner_enriches_context(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage
        from research_harness.orchestrator.service import OrchestratorService

        db = _make_db(tmp_path)
        svc = OrchestratorService(db)

        cp = ckpt.new_checkpoint(1)
        cp["current_stage"] = "build"

        planner_output = {"query": "test-from-planner", "auto_ingest": True}

        with (
            _patch(
                "research_harness.auto_runner.llm_planner.plan_stage",
                return_value=planner_output,
            ) as mock_plan,
            _patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                return_value={"summary": "ok", "tool_results": [], "errors": []},
            ) as _mock_exec,
        ):
            _result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="build",
                mode="standard",
                checkpoint_data=cp,
                base_dir=tmp_path,
            )

            mock_plan.assert_called_once()
            assert cp["stage_context"]["query"] == "test-from-planner"


# ---------------------------------------------------------------------------
# Multi-section loop in tool_dispatch
# ---------------------------------------------------------------------------


class TestMultiSectionLoop:
    def test_section_draft_called_per_section(self, tmp_path, monkeypatch):
        # Legacy per-tool dispatch path (loop is default ON; opt out here).
        monkeypatch.setenv("RESEARCH_HARNESS_SECTION_LOOP", "0")
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db = _make_db(tmp_path)
        svc = MagicMock()

        context = {
            "sections_to_draft": ["introduction", "method", "conclusion"],
            "outline": "test outline",
            "evidence_ids": [],
        }

        with _patch(
            "research_harness.auto_runner.tool_dispatch.dispatch"
        ) as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                tool="section_draft",
                success=True,
                output={"text": "drafted"},
                error="",
            )

            _result = dispatch_stage_tools(
                db=db,
                svc=svc,
                topic_id=1,
                stage="write",
                tools=("section_draft",),
                context=context,
            )

            assert mock_dispatch.call_count == 3
            assert len(context.get("_drafted_sections", [])) == 3


# ---------------------------------------------------------------------------
# Contract tests for blocking issue fixes (B1–B5)
# ---------------------------------------------------------------------------


class TestB1ProposeMultiArtifact:
    """B1: propose stage records both direction_proposal and study_spec artifacts."""

    def test_propose_records_study_spec_artifact(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db = _make_db(tmp_path)
        svc = MagicMock()

        context = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Test Direction",
            "artifact_payload": {"direction": "test", "research_question": "Why?"},
            "study_spec": "Run experiments on dataset X with metric Y",
            "project_id": 1,
        }

        captured_types: list[str] = []

        def capture_dispatch(tool_name, *, db, svc, topic_id, stage, context):
            captured_types.append(context.get("artifact_type", ""))
            return MagicMock(
                tool="orchestrator_record_artifact",
                success=True,
                output={"artifact_type": context.get("artifact_type")},
                error="",
            )

        with _patch(
            "research_harness.auto_runner.tool_dispatch.dispatch",
            side_effect=capture_dispatch,
        ):
            _result = dispatch_stage_tools(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                tools=("orchestrator_record_artifact",),
                context=context,
            )

            assert len(captured_types) == 2
            assert captured_types[0] == "direction_proposal"
            assert captured_types[1] == "study_spec"

    def test_context_bound_tools_skip_without_polluting_errors(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db = _make_db(tmp_path)
        svc = MagicMock()

        result = dispatch_stage_tools(
            db=db,
            svc=svc,
            topic_id=1,
            stage="analyze",
            tools=("paper_dismiss", "evidence_link", "adversarial_run"),
            context={},
        )

        assert result["errors"] == []
        assert [item["success"] for item in result["tool_results"]] == [
            False,
            False,
            False,
        ]
        assert all(
            item["output"].get("status") == "skipped" for item in result["tool_results"]
        )


class TestB2ExperimentRunContract:
    """B2: experiment_run reads code from files[entry_point], not code field."""

    def test_experiment_run_reads_files_entry_point(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_output_code_generate": {
                "files": {"main.py": "print('hello')", "utils.py": "pass"},
                "entry_point": "main.py",
            },
            "primary_metric": "accuracy",
        }
        params = _build_primitive_params("experiment_run", topic_id=1, context=context)
        assert params["code"] == "print('hello')"
        assert params["primary_metric"] == "accuracy"

    def test_experiment_run_fallback_to_code_field(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_output_code_generate": {"code": "legacy_code()"},
            "primary_metric": "f1",
        }
        params = _build_primitive_params("experiment_run", topic_id=1, context=context)
        assert params["code"] == "legacy_code()"

    def test_experiment_run_receives_ablation_contract(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "canonical_components": ["retriever"],
            "ablation_components": ["retriever"],
            "repeats": 3,
            "variance_estimates": [0.02],
            "acceptance_criteria": ["accuracy improves by 0.5%"],
            "evidence_kind": "final",
        }

        params = _build_primitive_params("experiment_run", topic_id=1, context=context)

        assert all(params[key] == value for key, value in context.items())

    def test_experiment_run_receives_ablation_provenance_contract(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "component_provenance": [
                {
                    "component_family": "retriever",
                    "provenance_tag": "borrowed",
                    "source_paper_id": 9,
                }
            ],
            "metric_direction": "maximize",
        }

        params = _build_primitive_params("experiment_run", topic_id=1, context=context)

        assert params["component_provenance"] == context["component_provenance"]
        assert params["metric_direction"] == "maximize"

    def test_verified_registry_build_reads_metrics(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_output_experiment_run": {
                "metrics": {"accuracy": 0.95, "f1": 0.88},
                "primary_metric_name": "accuracy",
            },
        }
        params = _build_primitive_params(
            "verified_registry_build", topic_id=1, context=context
        )
        assert params["metrics"] == {"accuracy": 0.95, "f1": 0.88}
        assert params["primary_metric_name"] == "accuracy"


class TestB3WriteStageParams:
    """B3: write-stage tools are properly parameterized from prior outputs."""

    def test_section_review_reads_draft(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_drafted_sections": ["introduction", "method"],
            "section": "method",
            "_output_section_draft_method": {"text": "We propose a novel..."},
        }
        params = _build_primitive_params("section_review", topic_id=1, context=context)
        assert params["section"] == "method"
        assert params["content"] == "We propose a novel..."

    def test_section_revise_reads_review(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_drafted_sections": ["introduction"],
            "section": "introduction",
            "_output_section_draft_introduction": {"text": "Draft text"},
            "_output_section_review": {"feedback": "Add more citations"},
        }
        params = _build_primitive_params("section_revise", topic_id=1, context=context)
        assert params["content"] == "Draft text"
        assert params["review_feedback"] == "Add more citations"

    def test_paper_verify_numbers_collects_all_sections(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_drafted_sections": ["method", "experiments"],
            "_output_section_draft_method": {"text": "Method text"},
            "_output_section_draft_experiments": {"text": "Experiments text"},
            "project_id": 1,
        }
        params = _build_primitive_params(
            "paper_verify_numbers", topic_id=1, context=context
        )
        assert "Method text" in params["text"]
        assert "Experiments text" in params["text"]

    def test_latex_compile_assembles_sections(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_drafted_sections": ["introduction", "conclusion"],
            "_output_section_draft_introduction": {"text": "\\section{Introduction}"},
            "_output_section_draft_conclusion": {"text": "\\section{Conclusion}"},
            "venue": "NeurIPS",
            "contributions": "We propose X",
            "project_id": 1,
        }
        params = _build_primitive_params("latex_compile", topic_id=1, context=context)
        assert "introduction" in params["sections"]
        assert "conclusion" in params["sections"]
        assert params["template"] == "neurips"


class TestB5InvariantCompliance:
    """B5: direction_proposal payload always contains research_question."""

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_research_question_present(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Test",
            "artifact_payload": {"direction": "test direction"},
            "focus": "test",
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_propose(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={},
        )
        payload = result["artifact_payload"]
        assert "research_question" in payload
        assert payload["research_question"]  # not empty

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_research_question_preserved_if_provided(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Test",
            "artifact_payload": {
                "direction": "gating",
                "research_question": "How does adaptive gating improve forecasting?",
            },
            "focus": "test",
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_propose(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={},
        )
        assert (
            result["artifact_payload"]["research_question"]
            == "How does adaptive gating improve forecasting?"
        )

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_study_spec_present(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Test",
            "artifact_payload": {"direction": "test"},
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_propose(
            db=db,
            svc=svc,
            topic_id=1,
            checkpoint_data={},
        )
        assert "study_spec" in result


# ---------------------------------------------------------------------------
# Gate advancement integration tests
# ---------------------------------------------------------------------------


def _setup_integration_db(tmp_path: Path):
    """Create DB with topic and orchestrator run for integration tests."""
    from research_harness.orchestrator.service import OrchestratorService

    db = Database(tmp_path / "gate_test.db")
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, target_venue) "
            "VALUES ('test-topic', 'Integration test topic', 'NeurIPS')"
        )
        # Bridge row for FK on project_artifacts.project_id
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) "
            "VALUES (1, 1, 'test-project', 'Integration test project')"
        )
        conn.commit()
    finally:
        conn.close()
    svc = OrchestratorService(db)
    svc.resume_run(1)
    return db, svc


class TestProposeGateAdvancement:
    """Integration: propose stage can pass its gate after auto-artifact recording."""

    def test_propose_gate_passes_with_all_artifacts(self, tmp_path):
        db, svc = _setup_integration_db(tmp_path)

        svc.record_artifact(
            topic_id=1,
            stage="propose",
            artifact_type="direction_proposal",
            title="Test direction",
            payload={"research_question": "Does X improve Y?"},
        )
        svc.record_artifact(
            topic_id=1,
            stage="propose",
            artifact_type="adversarial_resolution",
            title="Auto-approved",
            payload={"outcome": "approved"},
        )
        svc.record_artifact(
            topic_id=1,
            stage="propose",
            artifact_type="study_spec",
            title="Study spec",
            payload={"methodology": "Run 6 experiments on dataset X"},
        )

        from research_harness.orchestrator.transitions import TransitionValidator

        validator = TransitionValidator(db)
        can, reason, _ = validator.can_advance(1, "propose", "experiment")
        assert can, f"Propose gate should pass but failed: {reason}"

    def test_propose_gate_fails_without_adversarial_resolution(self, tmp_path):
        db, svc = _setup_integration_db(tmp_path)

        svc.record_artifact(
            topic_id=1,
            stage="propose",
            artifact_type="direction_proposal",
            title="Test",
            payload={"research_question": "Q?"},
        )
        svc.record_artifact(
            topic_id=1,
            stage="propose",
            artifact_type="study_spec",
            title="Spec",
            payload={"methodology": "M"},
        )

        from research_harness.orchestrator.transitions import TransitionValidator

        validator = TransitionValidator(db)
        can, reason, _ = validator.can_advance(1, "propose", "experiment")
        assert not can
        assert "adversarial_resolution" in reason


class TestExperimentGateAdvancement:
    """Integration: experiment stage can pass its gate after auto-artifact recording."""

    def test_experiment_gate_passes_with_all_artifacts(self, tmp_path):
        db, svc = _setup_integration_db(tmp_path)

        svc.record_artifact(
            topic_id=1,
            stage="experiment",
            artifact_type="experiment_code",
            title="Code",
            payload={"files": ["main.py"], "entry_point": "main.py"},
        )
        svc.record_artifact(
            topic_id=1,
            stage="experiment",
            artifact_type="experiment_result",
            title="Results",
            payload={"metrics": {"accuracy": 0.95}},
        )
        svc.record_artifact(
            topic_id=1,
            stage="experiment",
            artifact_type="verified_registry",
            title="Registry",
            payload={"whitelist_size": 5},
        )

        from research_harness.orchestrator.transitions import TransitionValidator

        validator = TransitionValidator(db)
        can, reason, _ = validator.can_advance(1, "experiment", "write")
        assert can, f"Experiment gate should pass but failed: {reason}"

    def test_experiment_gate_fails_without_verified_registry(self, tmp_path):
        db, svc = _setup_integration_db(tmp_path)

        svc.record_artifact(
            topic_id=1,
            stage="experiment",
            artifact_type="experiment_code",
            title="Code",
            payload={"files": ["main.py"]},
        )
        svc.record_artifact(
            topic_id=1,
            stage="experiment",
            artifact_type="experiment_result",
            title="Results",
            payload={"metrics": {}},
        )

        from research_harness.orchestrator.transitions import TransitionValidator

        validator = TransitionValidator(db)
        can, reason, _ = validator.can_advance(1, "experiment", "write")
        assert not can
        assert "verified_registry" in reason


class TestWriteGateArtifacts:
    """Integration: write stage records draft_pack via auto-artifact recording."""

    def test_write_policy_includes_architecture_and_figure_plan(self):
        from research_harness.auto_runner.stage_policy import get_policy

        policy = get_policy("write")
        assert policy is not None
        assert "writing_architecture" in policy.tools
        assert "figure_plan" in policy.tools
        assert "publication_run" in policy.tools
        assert policy.tools.index("writing_architecture") < policy.tools.index(
            "outline_generate"
        )
        assert policy.tools.index("figure_plan") > policy.tools.index(
            "consistency_check"
        )

    def test_draft_pack_recorded_from_tool_outputs(self, tmp_path, monkeypatch):
        # Legacy per-tool dispatch path (loop is default ON; opt out here).
        monkeypatch.setenv("RESEARCH_HARNESS_SECTION_LOOP", "0")
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db, svc = _setup_integration_db(tmp_path)

        context = {
            "sections_to_draft": ["introduction", "method"],
            "outline": "test",
            "evidence_ids": [],
            "project_id": 1,
        }

        with _patch(
            "research_harness.auto_runner.tool_dispatch.dispatch"
        ) as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                tool="section_draft",
                success=True,
                output={"text": "Section content"},
                error="",
            )

            dispatch_stage_tools(
                db=db,
                svc=svc,
                topic_id=1,
                stage="write",
                tools=("section_draft",),
                context=context,
            )

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM project_artifacts "
                "WHERE topic_id = 1 AND artifact_type = 'draft_pack'"
            ).fetchone()
            assert row is not None, "draft_pack artifact should be recorded"
            payload = json.loads(row["payload_json"])
            assert payload["section_names"] == ["introduction", "method"]
            assert payload["sections"] == {
                "introduction": "Section content",
                "method": "Section content",
            }
        finally:
            conn.close()

    def test_figure_plan_recorded_from_tool_output(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db, svc = _setup_integration_db(tmp_path)

        context = {
            "contributions": "Paper title: Science Discovery Harness",
            "outline": "AAAI-style paper outline",
            "venue": "AAAI",
        }

        with _patch(
            "research_harness.auto_runner.tool_dispatch.dispatch"
        ) as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                tool="figure_plan",
                success=True,
                output={
                    "items": [
                        {
                            "figure_id": "fig:architecture",
                            "kind": "figure",
                            "title": "End-to-end RH architecture",
                            "purpose": "Show the full paper-generation pipeline.",
                            "suggested_layout": "wide architecture diagram",
                        }
                    ],
                    "total_items": 1,
                    "figures_count": 1,
                    "tables_count": 0,
                },
                error="",
            )

            dispatch_stage_tools(
                db=db,
                svc=svc,
                topic_id=1,
                stage="write",
                tools=("figure_plan",),
                context=context,
            )

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM project_artifacts "
                "WHERE topic_id = 1 AND artifact_type = 'figure_plan'"
            ).fetchone()
            assert row is not None, "figure_plan artifact should be recorded"
            payload = json.loads(row["payload_json"])
            assert payload["items"][0]["figure_id"] == "fig:architecture"
            assert payload["figures_count"] == 1
        finally:
            conn.close()


class TestAutoArtifactRecording:
    """Integration: _record_auto_artifacts writes to actual DB."""

    def test_propose_records_adversarial_resolution(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [ToolResult(tool="paper_search", success=True)]
        errors: list[str] = []

        with _patch(
            "research_harness.auto_runner.tool_dispatch._run_automated_adversarial",
            return_value={"verdict": "approved", "issues": [], "summary": "OK"},
        ):
            recorded = _record_auto_artifacts(
                svc=svc,
                topic_id=1,
                stage="propose",
                context={},
                results=results,
                errors=errors,
            )

        assert len(recorded) >= 1
        art_types = [t for t, _ in recorded]
        assert "adversarial_resolution" in art_types
        assert all(aid > 0 for _, aid in recorded)

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM project_artifacts "
                "WHERE project_id = 1 AND artifact_type = 'adversarial_resolution'"
            ).fetchone()
            assert row is not None
            import json as _json

            payload = _json.loads(row["payload_json"])
            assert payload["outcome"] == "approved"
        finally:
            conn.close()

    def test_experiment_records_three_artifacts(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [
            ToolResult(
                tool="code_generate",
                success=True,
                output={"files": {"main.py": "code"}, "entry_point": "main.py"},
            ),
            ToolResult(
                tool="experiment_run", success=True, output={"metrics": {"acc": 0.9}}
            ),
            ToolResult(
                tool="verified_registry_build",
                success=True,
                output={"whitelist_size": 3},
            ),
        ]
        context = {
            "_output_code_generate": results[0].output,
            "_output_experiment_run": results[1].output,
            "_output_verified_registry_build": results[2].output,
        }
        errors: list[str] = []

        recorded = _record_auto_artifacts(
            svc=svc,
            topic_id=1,
            stage="experiment",
            context=context,
            results=results,
            errors=errors,
        )

        assert len(recorded) == 3
        art_types = [t for t, _ in recorded]
        assert "experiment_code" in art_types
        assert "experiment_result" in art_types
        assert "verified_registry" in art_types
        assert all(aid > 0 for _, aid in recorded)

        conn = db.connect()
        try:
            for art_type in (
                "experiment_code",
                "experiment_result",
                "verified_registry",
            ):
                row = conn.execute(
                    "SELECT * FROM project_artifacts WHERE project_id = 1 AND artifact_type = ?",
                    (art_type,),
                ).fetchone()
                assert row is not None, f"Missing artifact: {art_type}"
                if art_type == "experiment_result":
                    assert json.loads(row["payload_json"]) == {"metrics": {"acc": 0.9}}
        finally:
            conn.close()

    def test_experiment_result_preserves_ablation_contract(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        output = {"metrics": {"acc": 0.9}}
        contract = {
            "canonical_components": ["retriever"],
            "ablation_components": ["retriever"],
            "repeats": 3,
            "variance_estimates": [0.02],
            "acceptance_criteria": ["accuracy improves by 0.5%"],
            "evidence_kind": "final",
        }
        results = [ToolResult(tool="experiment_run", success=True, output=output)]

        _record_auto_artifacts(
            svc=svc,
            topic_id=1,
            stage="experiment",
            context={"_output_experiment_run": output, **contract},
            results=results,
            errors=[],
        )

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT payload_json FROM project_artifacts "
                "WHERE project_id = 1 AND artifact_type = 'experiment_result'"
            ).fetchone()
            payload = json.loads(row["payload_json"])
        finally:
            conn.close()
        assert payload == {**output, **contract}

    def test_legacy_experiment_run_keeps_exact_artifact_payload(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
            _to_dict,
        )
        from research_harness.primitives.experiment_impls import experiment_run

        db, svc = _setup_integration_db(tmp_path)
        output = _to_dict(experiment_run(code='print("acc: 0.9")'))

        _record_auto_artifacts(
            svc=svc,
            topic_id=1,
            stage="experiment",
            context={"_output_experiment_run": output},
            results=[ToolResult(tool="experiment_run", success=True, output=output)],
            errors=[],
        )

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT payload_json FROM project_artifacts "
                "WHERE project_id = 1 AND artifact_type = 'experiment_result'"
            ).fetchone()
            payload = json.loads(row["payload_json"])
        finally:
            conn.close()
        assert payload == {"metrics": output["metrics"]}

    def test_xci01_contract_does_not_persist_default_memory_fields(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
            _to_dict,
        )
        from research_harness.primitives.experiment_impls import experiment_run

        db, svc = _setup_integration_db(tmp_path)
        contract = {
            "canonical_components": ["retriever"],
            "ablation_components": ["retriever"],
            "repeats": 3,
            "variance_estimates": [0.02],
            "acceptance_criteria": [],
            "evidence_kind": "final",
        }
        output = _to_dict(experiment_run(code='print("acc: 0.9")', **contract))

        _record_auto_artifacts(
            svc=svc,
            topic_id=1,
            stage="experiment",
            context={"_output_experiment_run": output, **contract},
            results=[ToolResult(tool="experiment_run", success=True, output=output)],
            errors=[],
        )

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT payload_json FROM project_artifacts "
                "WHERE project_id = 1 AND artifact_type = 'experiment_result'"
            ).fetchone()
            payload = json.loads(row["payload_json"])
        finally:
            conn.close()
        assert payload == {"metrics": output["metrics"], **contract}

    def test_experiment_result_preserves_observed_ablation_outcomes(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        output = {
            "metrics": {"full/accuracy": 0.9, "without_1/accuracy": 0.85},
            "ablation_outcomes": [
                {
                    "component_family": "retriever",
                    "removal_effect": "hurt",
                    "provenance_tag": "borrowed",
                    "source_paper_id": 9,
                    "evidence": "observed accuracy: full=0.9, without_1=0.85",
                }
            ],
        }
        results = [ToolResult(tool="experiment_run", success=True, output=output)]

        _record_auto_artifacts(
            svc=svc,
            topic_id=1,
            stage="experiment",
            context={"_output_experiment_run": output},
            results=results,
            errors=[],
        )

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT payload_json FROM project_artifacts "
                "WHERE project_id = 1 AND artifact_type = 'experiment_result'"
            ).fetchone()
            payload = json.loads(row["payload_json"])
        finally:
            conn.close()
        assert payload == output


class TestAutoArtifactCheckpointTracking:
    """Fix 5: auto-artifact IDs flow through to checkpoint_data via stage_executor."""

    def test_auto_artifacts_tracked_in_checkpoint(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc = _setup_integration_db(tmp_path)
        cp = ckpt.new_checkpoint(1)
        cp["current_stage"] = "propose"

        planner_output = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Test",
            "artifact_payload": {"direction": "test", "research_question": "Q?"},
            "study_spec": "spec",
            "project_id": 1,
        }

        tool_results_return = {
            "summary": "ok",
            "tool_results": [],
            "errors": [],
            "auto_artifacts": [
                ("adversarial_resolution", 42),
                ("direction_proposal", 43),
            ],
        }

        with (
            _patch(
                "research_harness.auto_runner.llm_planner.plan_stage",
                return_value=planner_output,
            ),
            _patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                return_value=tool_results_return,
            ),
        ):
            _result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                mode="autonomous",
                checkpoint_data=cp,
                base_dir=tmp_path,
            )

        arts = cp.get("artifacts", {}).get("propose", {})
        assert "adversarial_resolution" in arts
        assert arts["adversarial_resolution"]["artifact_id"] == 42
        assert "direction_proposal" in arts
        assert arts["direction_proposal"]["artifact_id"] == 43

    def test_dispatch_returns_auto_artifacts_in_summary(self, tmp_path, monkeypatch):
        # Legacy per-tool dispatch path (loop is default ON; opt out here).
        monkeypatch.setenv("RESEARCH_HARNESS_SECTION_LOOP", "0")
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db, svc = _setup_integration_db(tmp_path)

        context = {
            "sections_to_draft": ["introduction"],
            "outline": "test",
            "evidence_ids": [],
            "project_id": 1,
        }

        with _patch(
            "research_harness.auto_runner.tool_dispatch.dispatch"
        ) as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                tool="section_draft",
                success=True,
                output={"text": "Section content"},
                error="",
            )

            result = dispatch_stage_tools(
                db=db,
                svc=svc,
                topic_id=1,
                stage="write",
                tools=("section_draft",),
                context=context,
            )

        assert "auto_artifacts" in result
        art_types = [t for t, _ in result["auto_artifacts"]]
        assert "draft_pack" in art_types


class TestInitGateArtifacts:
    """P0-2: init stage records topic_brief artifact."""

    def test_init_records_topic_brief(self, tmp_path):

        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [ToolResult(tool="paper_search", success=True)]
        errors: list[str] = []
        context = {"topic_description": "Multimodal time series forecasting"}

        recorded = _record_auto_artifacts(
            svc=svc,
            topic_id=1,
            stage="init",
            context=context,
            results=results,
            errors=errors,
        )

        assert len(recorded) >= 1
        art_types = [t for t, _ in recorded]
        assert "topic_brief" in art_types

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM project_artifacts "
                "WHERE project_id = 1 AND artifact_type = 'topic_brief'"
            ).fetchone()
            assert row is not None
        finally:
            conn.close()


class TestBuildGateArtifacts:
    """P0-3: build stage records all 4 gate-required artifacts."""

    def test_build_records_all_artifacts(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [
            ToolResult(
                tool="paper_search",
                success=True,
                output={"ingested_count": 50, "query_used": "test"},
            ),
            ToolResult(
                tool="expand_citations", success=True, output={"status": "done"}
            ),
            ToolResult(tool="paper_acquire", success=True, output={"acquired": 30}),
        ]
        context = {
            "_output_paper_search": results[0].output,
            "_output_expand_citations": results[1].output,
            "_output_paper_acquire": results[2].output,
        }
        errors: list[str] = []

        recorded = _record_auto_artifacts(
            svc=svc,
            topic_id=1,
            stage="build",
            context=context,
            results=results,
            errors=errors,
        )

        art_types = [t for t, _ in recorded]
        assert "literature_map" in art_types
        assert "paper_pool_snapshot" in art_types
        assert "citation_expansion_report" in art_types
        assert "acquisition_report" in art_types

    def test_build_records_demo_seed_pool_artifacts_from_existing_linked_papers(
        self, tmp_path
    ):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        svc.resume_run(1, mode="demo")
        _add_papers(db, topic_id=1, n=3)
        results = [
            ToolResult(tool="paper_list", success=True, output={"count": 3}),
        ]
        context = {
            "paper_production_run_policy": {
                "schema_version": "rh.paper_production_run_policy.v1",
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            },
            "paper_production_context_status": "ready_for_evidence_acquisition",
            "target_venue": "Environmental Research Letters",
        }
        errors: list[str] = []

        recorded = _record_auto_artifacts(
            db=db,
            svc=svc,
            topic_id=1,
            stage="build",
            context=context,
            results=results,
            errors=errors,
        )

        art_types = [t for t, _ in recorded]
        assert "literature_map" in art_types
        assert "paper_pool_snapshot" in art_types
        assert "citation_expansion_report" in art_types
        assert "acquisition_report" in art_types
        assert errors == []

        conn = db.connect()
        try:
            row = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = 1 AND artifact_type = 'paper_pool_snapshot'
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            payload = json.loads(row["payload_json"])
            assert payload["paper_count"] == 3
            assert payload["evidence_boundary"] == "demo_limited_seed_pool"
            assert payload["submission_readiness"] == "not_submission_ready"
        finally:
            conn.close()

        assert svc.check_gate(1, "build") == "pass"

    def test_build_demo_seed_boundary_overrides_metadata_only_search_snapshot(
        self, tmp_path
    ):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        svc.resume_run(1, mode="demo")
        _add_papers(db, topic_id=1, n=3)
        results = [
            ToolResult(
                tool="paper_search",
                success=True,
                output={"ingested_count": 23, "query_used": "cloud seeding"},
            ),
            ToolResult(
                tool="expand_citations",
                success=True,
                output={"status": "metadata_only"},
            ),
            ToolResult(
                tool="paper_acquire",
                success=True,
                output={"acquired": 0, "status": "metadata_only"},
            ),
        ]
        context = {
            "_output_paper_search": results[0].output,
            "_output_expand_citations": results[1].output,
            "_output_paper_acquire": results[2].output,
            "paper_production_run_policy": {
                "schema_version": "rh.paper_production_run_policy.v1",
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            },
            "paper_production_context_status": "ready_for_evidence_acquisition",
            "target_venue": "Environmental Research Letters",
        }
        errors: list[str] = []

        _record_auto_artifacts(
            db=db,
            svc=svc,
            topic_id=1,
            stage="build",
            context=context,
            results=results,
            errors=errors,
        )

        assert errors == []
        conn = db.connect()
        try:
            row = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = 1 AND artifact_type = 'paper_pool_snapshot'
                ORDER BY version DESC LIMIT 1
                """
            ).fetchone()
            payload = json.loads(row["payload_json"])
            assert payload["evidence_boundary"] == "demo_limited_seed_pool"
            assert payload["submission_readiness"] == "not_submission_ready"
        finally:
            conn.close()

        assert svc.check_gate(1, "build") == "pass"


class TestAnalyzeGateArtifacts:
    """P0-4: analyze stage records evidence_pack, claim_candidate_set, direction_proposal."""

    def test_analyze_records_all_artifacts(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [
            ToolResult(
                tool="claim_extract",
                success=True,
                output={"claims": [{"id": "c1"}], "papers_processed": 20},
            ),
            ToolResult(
                tool="gap_detect",
                success=True,
                output={"gaps": [{"id": "g1"}], "papers_analyzed": 20},
            ),
            ToolResult(
                tool="baseline_identify",
                success=True,
                output={
                    "coverage": {
                        "required_families": ["agent_review_workflow"],
                        "required_facets": ["human_eval"],
                    },
                    "novelty_decision": {
                        "verdict": "incremental",
                        "close_prior_baseline_ids": [],
                    },
                    "baselines": [
                        {
                            "baseline_id": "prior-agent-review",
                            "name": "Prior Agent Review",
                            "method_family": "agent_review_workflow",
                            "facets": ["human_eval"],
                            "paper_ids": [1],
                        }
                    ],
                },
            ),
        ]
        context = {
            "_output_claim_extract": results[0].output,
            "_output_gap_detect": results[1].output,
            "_output_baseline_identify": results[2].output,
            "focus": "adaptive gating",
        }
        errors: list[str] = []

        recorded = _record_auto_artifacts(
            svc=svc,
            topic_id=1,
            stage="analyze",
            context=context,
            results=results,
            errors=errors,
        )

        art_types = [t for t, _ in recorded]
        assert "claim_candidate_set" in art_types
        assert "evidence_pack" in art_types
        assert "baseline_matrix" in art_types
        assert "direction_proposal" in art_types

        recorded_by_type = dict(recorded)
        baseline_artifact_id = recorded_by_type["baseline_matrix"]
        direction_artifact_id = recorded_by_type["direction_proposal"]
        conn = db.connect()
        try:
            row = conn.execute(
                """
                SELECT payload_json
                FROM project_artifacts
                WHERE id = ?
                """,
                (baseline_artifact_id,),
            ).fetchone()
            dependency_row = conn.execute(
                """
                SELECT 1
                FROM artifact_dependencies
                WHERE from_artifact_id = ?
                  AND to_artifact_id = ?
                """,
                (baseline_artifact_id, direction_artifact_id),
            ).fetchone()
        finally:
            conn.close()
        payload = json.loads(row["payload_json"])
        assert payload["baselines"][0]["baseline_id"] == "prior-agent-review"
        assert payload["baselines"][0]["source_paper_ids"] == [1]
        assert payload["coverage"]["required_families"] == ["agent_review_workflow"]
        assert payload["coverage"]["covered_families"] == ["agent_review_workflow"]
        assert payload["coverage"]["missing_families"] == []
        assert payload["coverage"]["required_facets"] == ["human_eval"]
        assert payload["coverage"]["covered_facets"] == ["human_eval"]
        assert payload["coverage"]["missing_facets"] == []
        assert payload["novelty_decision"]["verdict"] == "incremental"
        assert dependency_row is not None


class TestWriteGateComplete:
    """P0 extension: write stage records draft/final/process/publication artifacts."""

    def test_write_records_all_publication_artifacts(self, tmp_path, monkeypatch):
        # Legacy per-tool dispatch path (loop is default ON; opt out here).
        monkeypatch.setenv("RESEARCH_HARNESS_SECTION_LOOP", "0")
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db, svc = _setup_integration_db(tmp_path)
        svc.record_artifact(
            topic_id=1,
            stage="analyze",
            artifact_type="evidence_pack",
            title="Evidence Pack",
            payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
        )

        context = {
            "sections_to_draft": ["introduction", "method"],
            "outline": "test",
            "evidence_ids": [],
            "project_id": 1,
        }

        with _patch(
            "research_harness.auto_runner.tool_dispatch.dispatch"
        ) as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                tool="section_draft",
                success=True,
                output={"text": "Section content"},
                error="",
            )

            result = dispatch_stage_tools(
                db=db,
                svc=svc,
                topic_id=1,
                stage="write",
                tools=("section_draft",),
                context=context,
            )

        art_types = [t for t, _ in result["auto_artifacts"]]
        assert "draft_pack" in art_types
        assert "final_bundle" in art_types
        assert "process_summary" in art_types
        assert "publication_pack" in art_types
        assert "publication_run" in art_types

        conn = db.connect()
        try:
            row = conn.execute(
                """
                SELECT payload_json
                FROM project_artifacts
                WHERE topic_id = 1 AND artifact_type = 'publication_pack'
                """
            ).fetchone()
            assert row is not None
            payload = json.loads(row["payload_json"])
            assert payload["ready_for_review"] is True
            assert payload["components"]["manuscript_sections"]["status"] == "present"
            assert payload["components"]["evidence_pack"]["status"] == "present"
            run_row = conn.execute(
                """
                SELECT payload_json
                FROM project_artifacts
                WHERE topic_id = 1 AND artifact_type = 'publication_run'
                """
            ).fetchone()
            assert run_row is not None
            run_payload = json.loads(run_row["payload_json"])
            assert run_payload["ready_for_review"] is True
            assert run_payload["publication_run_artifact_id"] > 0
        finally:
            conn.close()


class TestWriteTerminalCompletion:
    """P0-1: runner recognizes write as terminal stage and returns 'completed'."""

    def test_write_completes_without_advance_error(self, tmp_path):
        """Verify the terminal stage check in runner.py by testing the logic directly."""
        from research_harness.orchestrator.stages import next_stage

        assert next_stage("write") is None, "write should be terminal stage"

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_topic

        cp = ckpt.new_checkpoint(1)
        cp["current_stage"] = "write"

        stage_call_count = 0

        def mock_execute_stage(**kwargs):
            nonlocal stage_call_count
            stage_call_count += 1
            return {
                "status": "complete",
                "stage": "write",
                "summary": "write done",
                "tool_results": [],
                "auto_artifacts": [],
            }

        from unittest.mock import MagicMock, patch as _patch

        with (
            _patch(
                "research_harness.auto_runner.runner.execute_stage",
                side_effect=mock_execute_stage,
            ),
            _patch("research_harness.auto_runner.runner.Database") as mock_db_cls,
            _patch(
                "research_harness.auto_runner.runner.OrchestratorService"
            ) as mock_svc_cls,
            _patch(
                "research_harness.auto_runner.runner.default_state_dir",
                return_value=tmp_path,
            ),
            _patch(
                "research_harness.auto_runner.runner.load_runtime_config"
            ) as mock_config,
        ):
            mock_config.return_value = MagicMock(db_path=tmp_path / "test.db")
            db, svc = _setup_integration_db(tmp_path)
            mock_db_cls.return_value = db

            mock_svc = mock_svc_cls.return_value
            run_mock = MagicMock()
            run_mock.topic_id = 1
            run_mock.current_stage = "write"
            mock_svc.get_run.return_value = run_mock
            mock_svc.check_gate.return_value = "pass"

            result = run_topic(
                topic_id=1,
                base_dir=tmp_path,
                auto_approve=True,
            )

        assert result["status"] == "completed"
        assert stage_call_count == 1
        mock_svc.advance.assert_not_called()


# ---------------------------------------------------------------------------
# Output schema normalization tests (P0-5)
# ---------------------------------------------------------------------------


class TestOutputSchemaNormalization:
    """P0-5: output schema normalization handles real primitive output shapes."""

    def test_extract_section_text_real_shape(self):
        from research_harness.auto_runner.tool_dispatch import _extract_section_text

        real_output = {
            "draft": {
                "content": "We propose...",
                "section": "intro",
                "citations_used": [1, 2],
                "word_count": 150,
            }
        }
        assert _extract_section_text(real_output) == "We propose..."

    def test_extract_section_text_legacy_shape(self):
        from research_harness.auto_runner.tool_dispatch import _extract_section_text

        legacy_output = {"text": "Legacy format"}
        assert _extract_section_text(legacy_output) == "Legacy format"

    def test_extract_review_feedback_real_shape(self):
        from research_harness.auto_runner.tool_dispatch import _extract_review_feedback

        real_output = {
            "suggestions": ["Add citations", "Clarify method"],
            "dimensions": [{"dimension": "clarity", "score": 7.0, "comment": "OK"}],
        }
        feedback = _extract_review_feedback(real_output)
        assert "Add citations" in feedback

    def test_extract_review_feedback_from_dimensions(self):
        from research_harness.auto_runner.tool_dispatch import _extract_review_feedback

        dim_output = {
            "suggestions": [],
            "dimensions": [
                {"dimension": "rigor", "score": 5.0, "comment": "Weak stats"}
            ],
        }
        feedback = _extract_review_feedback(dim_output)
        assert "Weak stats" in feedback

    def test_extract_revise_text_real_shape(self):
        from research_harness.auto_runner.tool_dispatch import _extract_revise_text

        real_output = {
            "revised_content": "Revised text here",
            "changes_made": ["Added refs"],
        }
        assert _extract_revise_text(real_output) == "Revised text here"

    def test_extract_revise_text_legacy_shape(self):
        from research_harness.auto_runner.tool_dispatch import _extract_revise_text

        legacy_output = {"text": "Legacy revised"}
        assert _extract_revise_text(legacy_output) == "Legacy revised"


# ---------------------------------------------------------------------------
# P0-2: experiment_runs row insertion
# ---------------------------------------------------------------------------


class TestExperimentRunsInsertion:
    """P0-2: auto_runner inserts experiment_runs(kept=1) so experiment_gate passes."""

    def test_experiment_inserts_kept_run(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [
            ToolResult(
                tool="code_generate",
                success=True,
                output={"files": {"main.py": "print('hi')"}, "entry_point": "main.py"},
            ),
            ToolResult(
                tool="experiment_run",
                success=True,
                output={
                    "metrics": {"accuracy": 0.92},
                    "primary_metric_name": "accuracy",
                    "primary_metric_value": 0.92,
                },
            ),
            ToolResult(
                tool="verified_registry_build",
                success=True,
                output={"whitelist_size": 5},
            ),
        ]
        context = {
            "_output_code_generate": results[0].output,
            "_output_experiment_run": results[1].output,
            "_output_verified_registry_build": results[2].output,
            "primary_metric": "accuracy",
        }
        errors: list[str] = []

        _record_auto_artifacts(
            svc=svc,
            topic_id=1,
            stage="experiment",
            context=context,
            results=results,
            errors=errors,
        )

        # Verify experiment_runs row exists with kept=1
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM experiment_runs WHERE project_id = 1 AND kept = 1"
            ).fetchone()
            assert row is not None, "experiment_runs row with kept=1 not found"
            assert row["primary_metric_name"] == "accuracy"
            assert row["primary_metric_value"] == 0.92
        finally:
            conn.close()

    def test_experiment_gate_passes_with_inserted_run(self, tmp_path):
        """Full gate check: artifacts + experiment_runs row → pass."""
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )
        from research_harness.orchestrator.transitions import GateEvaluator

        db, svc = _setup_integration_db(tmp_path)
        results = [
            ToolResult(
                tool="code_generate",
                success=True,
                output={"files": {"main.py": "x"}, "entry_point": "main.py"},
            ),
            ToolResult(
                tool="experiment_run",
                success=True,
                output={
                    "metrics": {"f1": 0.85},
                    "primary_metric_name": "f1",
                    "primary_metric_value": 0.85,
                },
            ),
            ToolResult(
                tool="verified_registry_build",
                success=True,
                output={"whitelist_size": 3},
            ),
        ]
        context = {
            "_output_code_generate": results[0].output,
            "_output_experiment_run": results[1].output,
            "_output_verified_registry_build": results[2].output,
            "primary_metric": "f1",
        }
        errors: list[str] = []

        _record_auto_artifacts(
            svc=svc,
            topic_id=1,
            stage="experiment",
            context=context,
            results=results,
            errors=errors,
        )

        evaluator = GateEvaluator(db)
        decision = evaluator._evaluate_experiment_gate(1, "experiment")
        assert decision == "pass", f"Expected 'pass', got '{decision}'"


# ---------------------------------------------------------------------------
# P0-3: propose reads direction_proposal fallback
# ---------------------------------------------------------------------------


class TestProposeDirectionFallback:
    """P0-3: _plan_propose falls back to direction_proposal when direction_ranking missing."""

    def test_propose_uses_direction_proposal_fallback(self, tmp_path):
        from unittest.mock import patch

        db, svc = _setup_integration_db(tmp_path)

        # Record a direction_proposal in analyze (which auto-artifacts create),
        # but NO direction_ranking.
        svc.record_artifact(
            topic_id=1,
            stage="analyze",
            artifact_type="direction_proposal",
            title="Direction from gaps",
            payload={"gaps": ["gap1"], "research_question": "How to improve?"},
        )

        from research_harness.auto_runner.llm_planner import _plan_propose

        with patch(
            "research_harness.auto_runner.llm_planner._call_planner_llm"
        ) as mock_llm:
            mock_llm.return_value = {
                "artifact_type": "direction_proposal",
                "artifact_title": "Test direction",
                "artifact_payload": {
                    "direction": "novel approach",
                    "research_question": "RQ1",
                },
                "focus": "test focus",
                "study_spec": "spec from LLM",
            }
            result = _plan_propose(
                db=db,
                svc=svc,
                topic_id=1,
                checkpoint_data={},
            )
        assert result.get("study_spec") == "spec from LLM"
        assert result.get("artifact_type") == "direction_proposal"


# ---------------------------------------------------------------------------
# P0-4: study_spec never empty
# ---------------------------------------------------------------------------


class TestStudySpecNonEmpty:
    """P0-4: study_spec always has substantive content for artifact recording."""

    def test_study_spec_synthesized_when_llm_returns_empty(self, tmp_path):
        from unittest.mock import patch

        db, svc = _setup_integration_db(tmp_path)

        from research_harness.auto_runner.llm_planner import _plan_propose

        with patch(
            "research_harness.auto_runner.llm_planner._call_planner_llm"
        ) as mock_llm:
            mock_llm.return_value = {
                "artifact_type": "direction_proposal",
                "artifact_payload": {
                    "direction": "Novel gating mechanism",
                    "research_question": "How to gate modalities?",
                },
                "focus": "modality gating",
                # study_spec deliberately missing
            }
            result = _plan_propose(
                db=db,
                svc=svc,
                topic_id=1,
                checkpoint_data={},
            )

        assert result.get("study_spec"), "study_spec must not be empty"
        assert "Novel gating mechanism" in result["study_spec"]


# ---------------------------------------------------------------------------
# R6-3: should_pause_human autonomous mode
# ---------------------------------------------------------------------------


class TestAutonomyAllStages:
    """Autonomous mode still respects high-risk human-required gates."""

    def test_only_low_and_medium_risk_stages_skip_pause_in_autonomous(self):
        from research_harness.auto_runner.stage_policy import (
            STAGE_POLICIES,
            should_pause_human,
        )

        for stage_name, policy in STAGE_POLICIES.items():
            result = should_pause_human(
                stage_name, mode="standard", autonomy="autonomous"
            )
            expected = (
                policy.approval_policy == "human_required"
                or policy.risk_level == "high"
                or not policy.autonomous_allowed
            )
            assert result is expected, f"Stage '{stage_name}' autonomy pause drift"

    def test_high_risk_stages_pause_in_supervised(self):
        from research_harness.auto_runner.stage_policy import should_pause_human

        # propose and write are human_checkpoint="always"
        assert (
            should_pause_human("propose", mode="standard", autonomy="supervised")
            is True
        )
        assert (
            should_pause_human("write", mode="standard", autonomy="supervised") is True
        )


# ---------------------------------------------------------------------------
# R6-1: Write terminal gate check
# ---------------------------------------------------------------------------


class TestWriteTerminalGateCheck:
    """Write terminal checks gate before reporting completed."""

    def test_write_pauses_on_blocking_review_issue(self, tmp_path):
        from unittest.mock import MagicMock, patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_topic

        # Setup checkpoint at write stage
        ckpt_dir = tmp_path / "checkpoints"
        ckpt_dir.mkdir()
        cp = ckpt.new_checkpoint(1, mode="standard")
        cp["current_stage"] = "write"

        ckpt_path = ckpt.checkpoint_path(tmp_path, 1)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        ckpt.save_checkpoint(ckpt_path, cp)

        def mock_execute_stage(**kwargs):
            return {
                "status": "complete",
                "stage": "write",
                "summary": "write done",
                "tool_results": [],
                "auto_artifacts": [],
            }

        with (
            _patch(
                "research_harness.auto_runner.runner.execute_stage",
                side_effect=mock_execute_stage,
            ),
            _patch("research_harness.auto_runner.runner.Database") as mock_db_cls,
            _patch(
                "research_harness.auto_runner.runner.OrchestratorService"
            ) as mock_svc_cls,
            _patch(
                "research_harness.auto_runner.runner.default_state_dir",
                return_value=tmp_path,
            ),
            _patch(
                "research_harness.auto_runner.runner.load_runtime_config"
            ) as mock_config,
        ):
            mock_config.return_value = MagicMock(db_path=tmp_path / "test.db")
            db, svc = _setup_integration_db(tmp_path)
            mock_db_cls.return_value = db

            mock_svc = mock_svc_cls.return_value
            run_mock = MagicMock()
            run_mock.topic_id = 1
            run_mock.current_stage = "write"
            mock_svc.get_run.return_value = run_mock
            # Gate returns "needs_review" (blocking review issue)
            mock_svc.check_gate.return_value = "needs_review"

            result = run_topic(
                topic_id=1,
                base_dir=tmp_path,
                auto_approve=False,
            )

        assert result["status"] == "paused"
        assert "needs_review" in result.get(
            "gate_decision", ""
        ) or "needs_review" in result.get("summary", "")

    def test_write_completes_when_gate_passes(self, tmp_path):
        from unittest.mock import MagicMock, patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_topic

        cp = ckpt.new_checkpoint(1, mode="standard")
        cp["current_stage"] = "write"

        ckpt_path = ckpt.checkpoint_path(tmp_path, 1)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        ckpt.save_checkpoint(ckpt_path, cp)

        def mock_execute_stage(**kwargs):
            return {
                "status": "complete",
                "stage": "write",
                "summary": "write done",
                "tool_results": [],
                "auto_artifacts": [],
            }

        with (
            _patch(
                "research_harness.auto_runner.runner.execute_stage",
                side_effect=mock_execute_stage,
            ),
            _patch("research_harness.auto_runner.runner.Database") as mock_db_cls,
            _patch(
                "research_harness.auto_runner.runner.OrchestratorService"
            ) as mock_svc_cls,
            _patch(
                "research_harness.auto_runner.runner.default_state_dir",
                return_value=tmp_path,
            ),
            _patch(
                "research_harness.auto_runner.runner.load_runtime_config"
            ) as mock_config,
        ):
            mock_config.return_value = MagicMock(db_path=tmp_path / "test.db")
            db, svc = _setup_integration_db(tmp_path)
            mock_db_cls.return_value = db

            mock_svc = mock_svc_cls.return_value
            run_mock = MagicMock()
            run_mock.topic_id = 1
            run_mock.current_stage = "write"
            mock_svc.get_run.return_value = run_mock
            mock_svc.check_gate.return_value = "pass"

            result = run_topic(
                topic_id=1,
                base_dir=tmp_path,
                auto_approve=True,
            )

        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# R6-4: code_validate receives code parameter
# ---------------------------------------------------------------------------


class TestCodeValidateParams:
    """code_validate gets code from code_generate output."""

    def test_code_validate_reads_code_generate_output(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_output_code_generate": {
                "files": {"main.py": "import torch\nprint('hello')"},
                "entry_point": "main.py",
            },
        }
        params = _build_primitive_params("code_validate", topic_id=1, context=context)
        assert params["code"] == "import torch\nprint('hello')"


# ---------------------------------------------------------------------------
# Codex bridge fallback tests
# ---------------------------------------------------------------------------


class TestCodexBridgeFallback:
    """Codex timeout / CLI missing falls back to claude -p."""

    def test_parse_codex_output_extracts_json_after_preface(self):
        from research_harness.auto_runner.codex_bridge import _parse_codex_output

        raw = (
            "I will inspect the artifact and return JSON.\n"
            "{\n"
            '  "verdict": "revise",\n'
            '  "issues": [\n'
            "    {\n"
            '      "severity": "critical",\n'
            '      "category": "evidence_coverage",\n'
            '      "target": "artifact",\n'
            '      "reasoning": "Cannot verify the method evidence."\n'
            "    }\n"
            "  ],\n"
            '  "scores": {"evidence_coverage": 1},\n'
            '  "notes": "needs evidence"\n'
            "}"
        )

        parsed = _parse_codex_output(raw)

        assert parsed["verdict"] == "revise"
        assert len(parsed["issues"]) == 1
        assert parsed["issues"][0]["severity"] == "critical"

    def test_codex_exec_allows_non_git_task_directory(self, tmp_path):
        """Codex review should not fail solely because task cwd is not trusted."""
        from types import SimpleNamespace
        from unittest.mock import patch

        from research_harness.auto_runner.codex_bridge import run_codex_review

        captured: dict[str, list[str]] = {}

        def fake_run(cmd, **_kwargs):
            captured["cmd"] = list(cmd)
            out_path = cmd[cmd.index("-o") + 1]
            Path(out_path).write_text(
                json.dumps(
                    {
                        "verdict": "approve",
                        "issues": [],
                        "scores": {},
                        "notes": "ok",
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            patch(
                "research_harness.auto_runner.codex_bridge._find_codex",
                return_value="/usr/bin/codex",
            ),
            patch(
                "research_harness.auto_runner.codex_bridge.subprocess.run",
                side_effect=fake_run,
            ),
            patch(
                "research_harness.auto_runner.codex_bridge._codex_exec_supports",
                return_value=False,
            ),
        ):
            result = run_codex_review(
                artifact_path=tmp_path / "test.json",
                stage="propose",
                focus="test",
                cwd=tmp_path / "non_git_task_dir",
            )

        assert result["success"] is True
        assert result["backend"] == "codex"
        assert "--skip-git-repo-check" in captured["cmd"]

    @pytest.mark.parametrize(
        "codex_bin, run_effect",
        [
            ("/usr/bin/codex", __import__("subprocess").TimeoutExpired("codex", 300)),
            ("/usr/bin/codex", OSError("Permission denied")),
            (None, None),
        ],
        ids=["timeout", "oserror", "no-codex"],
    )
    def test_codex_failure_falls_back_to_claude(self, tmp_path, codex_bin, run_effect):
        from unittest.mock import patch

        from research_harness.auto_runner.codex_bridge import run_codex_review

        with (
            patch(
                "research_harness.auto_runner.codex_bridge._find_codex",
                return_value=codex_bin,
            ),
            patch(
                "research_harness.auto_runner.codex_bridge.subprocess.run",
                side_effect=run_effect,
            ),
            patch(
                "research_harness.auto_runner.codex_bridge._adversarial_via_claude"
            ) as mock_claude,
        ):
            mock_claude.return_value = {
                "success": True,
                "verdict": "approve",
                "issues": [],
                "scores": {},
                "notes": "",
                "raw_output": "",
                "backend": "claude",
            }
            result = run_codex_review(
                artifact_path=tmp_path / "test.json", stage="propose", focus="test"
            )

        assert result["backend"] == "claude"
        mock_claude.assert_called_once()

    def test_claude_backend_runs_isolated_tool_less_cli(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from unittest.mock import patch

        from research_harness.auto_runner.codex_bridge import run_codex_review

        monkeypatch.setenv("RESEARCH_HARNESS_ADVERSARIAL_BACKEND", "claude")
        artifact = tmp_path / "a.tex"
        artifact.write_text("UNIQUE-BODY-MARKER", encoding="utf-8")
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"], captured["input"] = list(cmd), kwargs["input"]
            return SimpleNamespace(
                returncode=0, stdout='{"verdict": "revise", "issues": []}', stderr=""
            )

        with (
            patch(
                "research_harness.auto_runner.codex_bridge.shutil.which",
                return_value="/usr/bin/claude",
            ),
            patch(
                "research_harness.auto_runner.codex_bridge.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            result = run_codex_review(artifact_path=artifact, stage="write", focus="x")

        assert result["success"] is True
        assert result["backend"] == "claude"
        assert result["verdict"] == "revise"
        for flag in ("-p", "--restricted", "--strict-mcp-config"):
            assert flag in captured["cmd"]
        assert captured["cmd"][captured["cmd"].index("--tools") + 1] == ""
        assert "UNIQUE-BODY-MARKER" in captured["input"]

    def test_claude_backend_reports_failure_not_success(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from unittest.mock import patch

        from research_harness.auto_runner.codex_bridge import run_codex_review

        monkeypatch.setenv("RESEARCH_HARNESS_ADVERSARIAL_BACKEND", "claude")
        with (
            patch(
                "research_harness.auto_runner.codex_bridge.shutil.which",
                return_value="/usr/bin/claude",
            ),
            patch(
                "research_harness.auto_runner.codex_bridge.subprocess.run",
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="boom"),
            ),
        ):
            result = run_codex_review(
                artifact_path=tmp_path / "x", stage="s", focus="f"
            )

        assert result["success"] is False
        assert "boom" in result["error"]


# ---------------------------------------------------------------------------
# Budget halt test
# ---------------------------------------------------------------------------


class TestBudgetHalt:
    """Budget exhaustion halts the runner."""

    def test_budget_halt_returns_paused(self, tmp_path):
        from unittest.mock import MagicMock, patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_topic

        cp = ckpt.new_checkpoint(1, mode="standard")
        cp["current_stage"] = "build"

        ckpt_path = ckpt.checkpoint_path(tmp_path, 1)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        ckpt.save_checkpoint(ckpt_path, cp)

        call_count = 0

        def mock_execute_stage(**kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "status": "complete",
                "stage": "build",
                "summary": "done",
                "tool_results": [],
                "auto_artifacts": [],
            }

        with (
            _patch(
                "research_harness.auto_runner.runner.execute_stage",
                side_effect=mock_execute_stage,
            ),
            _patch("research_harness.auto_runner.runner.Database") as mock_db_cls,
            _patch(
                "research_harness.auto_runner.runner.OrchestratorService"
            ) as mock_svc_cls,
            _patch(
                "research_harness.auto_runner.runner.default_state_dir",
                return_value=tmp_path,
            ),
            _patch(
                "research_harness.auto_runner.runner.load_runtime_config"
            ) as mock_config,
        ):
            mock_config.return_value = MagicMock(db_path=tmp_path / "test.db")
            db, svc = _setup_integration_db(tmp_path)
            mock_db_cls.return_value = db

            mock_svc = mock_svc_cls.return_value
            run_mock = MagicMock()
            run_mock.topic_id = 1
            run_mock.current_stage = "build"
            mock_svc.get_run.return_value = run_mock

            from research_harness.auto_runner.budget import BudgetCheckResult

            with _patch(
                "research_harness.auto_runner.budget.BudgetMonitor.check",
                return_value=BudgetCheckResult(action="halt", message="Over budget"),
            ):
                result = run_topic(
                    topic_id=1,
                    base_dir=tmp_path,
                    auto_approve=True,
                )

        assert result["status"] == "paused"
        assert "Budget" in result.get("summary", "") or "budget" in result.get(
            "summary", ""
        )


# ---------------------------------------------------------------------------
# Loopback path test (T1 — runner.py advance returns loopback)
# ---------------------------------------------------------------------------


class TestLoopbackPath:
    """When orchestrator advance returns loopback, runner rewinds to target stage."""

    def test_loopback_rewinds_to_build(self, tmp_path):
        from unittest.mock import MagicMock, patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_topic

        cp = ckpt.new_checkpoint(1, mode="standard")
        cp["current_stage"] = "analyze"

        ckpt_path = ckpt.checkpoint_path(tmp_path, 1)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        ckpt.save_checkpoint(ckpt_path, cp)

        call_stages: list[str] = []

        def mock_execute_stage(**kwargs):
            stage = kwargs["stage"]
            call_stages.append(stage)
            if stage == "build" and call_stages.count("build") > 0:
                return {
                    "status": "needs_human",
                    "stage": stage,
                    "summary": "stopping",
                    "tool_results": [],
                    "auto_artifacts": [],
                }
            return {
                "status": "complete",
                "stage": stage,
                "summary": "done",
                "tool_results": [],
                "auto_artifacts": [],
            }

        advance_calls = [0]

        def mock_advance(*args, **kwargs):
            advance_calls[0] += 1
            if advance_calls[0] == 1:
                return {"success": False, "loopback": True, "to_stage": "build"}
            return {"success": True}

        with (
            _patch(
                "research_harness.auto_runner.runner.execute_stage",
                side_effect=mock_execute_stage,
            ),
            _patch("research_harness.auto_runner.runner.Database") as mock_db_cls,
            _patch(
                "research_harness.auto_runner.runner.OrchestratorService"
            ) as mock_svc_cls,
            _patch(
                "research_harness.auto_runner.runner.default_state_dir",
                return_value=tmp_path,
            ),
            _patch(
                "research_harness.auto_runner.runner.load_runtime_config"
            ) as mock_config,
        ):
            mock_config.return_value = MagicMock(db_path=tmp_path / "test.db")
            mock_db = MagicMock()
            mock_db.migrate = MagicMock()
            mock_db_cls.return_value = mock_db

            mock_svc = mock_svc_cls.return_value
            run_mock = MagicMock()
            run_mock.topic_id = 1
            run_mock.current_stage = "analyze"
            mock_svc.get_run.return_value = run_mock
            mock_svc.advance.side_effect = mock_advance
            mock_svc.check_gate.return_value = "pass"

            result = run_topic(
                topic_id=1,
                base_dir=tmp_path,
            )

        assert "analyze" in call_stages
        assert "build" in call_stages
        assert result["status"] == "paused"


# ---------------------------------------------------------------------------
# Checkpoint stale .tmp cleanup test (R1)
# ---------------------------------------------------------------------------


class TestCheckpointTempCleanup:
    """Stale .tmp files are cleaned up on load_checkpoint."""

    def test_stale_tmp_removed_on_load(self, tmp_path):
        from research_harness.auto_runner import checkpoint as ckpt

        ckpt_dir = tmp_path / "auto_runner" / "checkpoints"
        ckpt_dir.mkdir(parents=True)

        # Create stale .tmp file
        stale = ckpt_dir / "project_1_checkpoint.tmp"
        stale.write_text("stale data")

        # load_checkpoint on non-existent checkpoint cleans up temps
        result = ckpt.load_checkpoint(ckpt_dir / "project_1.json")

        assert result is None
        assert not stale.exists()


class TestBaselineFamilyVocabularyReachesGenerator:
    """The baseline-coverage invariant is only satisfiable if the generator
    is told which families it must cover; the primitive has no family
    parameter, so `focus` is the only channel."""

    def test_required_families_are_named_in_focus(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        params = _build_primitive_params(
            "baseline_identify",
            topic_id=1,
            context={
                "focus": "underwater offloading",
                "required_baseline_families": ["method", "baseline", "evaluation"],
            },
        )
        assert "underwater offloading" in params["focus"]
        for family in ("method", "baseline", "evaluation"):
            assert family in params["focus"]

    def test_focus_unchanged_when_no_families_required(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        params = _build_primitive_params(
            "baseline_identify",
            topic_id=1,
            context={"focus": "comparison"},
        )
        assert params["focus"] == "comparison"

    def test_other_primitives_do_not_get_the_family_requirement(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        params = _build_primitive_params(
            "gap_detect",
            topic_id=1,
            context={
                "focus": "comparison",
                "required_baseline_families": ["method", "baseline"],
            },
        )
        assert params["focus"] == "comparison"


class TestProseParamsAcceptPlannerLists:
    """The planner emits contributions as a list; writing primitives take a
    string and call .strip()/.split() on it. Passing the list through took out
    architecture, outline, figure-plan and compile in one stage."""

    def test_contributions_list_becomes_numbered_prose(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        params = _build_primitive_params(
            "writing_architecture",
            topic_id=1,
            context={"contributions": ["First claim", "Second claim"]},
        )
        assert isinstance(params["contributions"], str)
        assert "1. First claim" in params["contributions"]
        assert "2. Second claim" in params["contributions"]

    def test_single_contribution_is_not_numbered(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        params = _build_primitive_params(
            "figure_plan", topic_id=1, context={"contributions": ["Only one"]}
        )
        assert params["contributions"] == "Only one"

    def test_string_contributions_pass_through_unchanged(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        params = _build_primitive_params(
            "writing_architecture", topic_id=1, context={"contributions": "plain text"}
        )
        assert params["contributions"] == "plain text"

    def test_latex_compile_title_survives_a_list(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        params = _build_primitive_params(
            "latex_compile",
            topic_id=1,
            context={"contributions": ["Headline claim", "Second"]},
        )
        assert params["title"].startswith("1. Headline claim")
