"""Tests for algorithm design subsystem primitives."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _offline_prior_art(monkeypatch):
    """The originality judge retrieves method neighbours; here every lane answers empty."""
    from research_harness.primitives import impls
    from research_harness.primitives.types import PaperSearchOutput

    from research_harness.primitives.types import PaperRef

    monkeypatch.setattr(
        impls,
        "paper_search",
        lambda **kwargs: PaperSearchOutput(
            papers=[
                PaperRef(
                    "A retrieved method neighbour",
                    doi="10.1/neighbour",
                    abstract="Neighbour abstract",
                )
            ],
            providers_queried=["local", "crossref"],
        ),
    )


def _insert_paper(conn, pid, title, **extra):
    cols = {
        "id": pid,
        "title": title,
        "s2_id": f"s2_{pid}",
        "arxiv_id": f"arxiv_{pid}",
        "doi": f"10.test/{pid}",
    }
    cols.update(extra)
    keys = ", ".join(cols.keys())
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO papers ({keys}) VALUES ({placeholders})", list(cols.values())
    )


def _seed_topic(conn, topic_id=1, name="test"):
    conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (topic_id, name))


def _seed_topic_summary(conn, topic_id=1, paper_ids=None):
    ids = list(paper_ids or [])
    conn.execute(
        """INSERT OR REPLACE INTO topic_summaries
           (topic_id, summary, paper_count, paper_ids_json, compiled_at)
           VALUES (?, ?, ?, ?, datetime('now'))""",
        (
            topic_id,
            "Cached topic summary for algorithm design tests",
            len(ids),
            json.dumps(ids),
        ),
    )


def _seed_gap(conn, topic_id, description, severity="medium", gap_type="technique"):
    conn.execute(
        "INSERT INTO gaps (topic_id, description, severity, gap_type) VALUES (?, ?, ?, ?)",
        (topic_id, description, severity, gap_type),
    )


def _seed_taxonomy_node(conn, topic_id, name, description="", paper_id=None):
    conn.execute(
        "INSERT INTO taxonomy_nodes (topic_id, name, description) VALUES (?, ?, ?)",
        (topic_id, name, description),
    )
    node_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if paper_id is not None:
        conn.execute(
            """INSERT INTO taxonomy_assignments
               (paper_id, node_id, confidence, evidence)
               VALUES (?, ?, 0.8, 'test evidence')""",
            (paper_id, node_id),
        )


def _seed_real_design_context(conn, topic_id=1):
    _insert_paper(
        conn,
        1,
        "Graph calibration for budget pacing",
        year=2025,
        compiled_summary=json.dumps(
            {
                "problem": "budget pacing",
                "method": "GraphCalibrator",
                "findings": ["stable pacing"],
            }
        ),
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, ?, 'high')",
        (topic_id,),
    )
    _seed_topic_summary(conn, topic_id, paper_ids=[1])
    conn.execute(
        """INSERT INTO taxonomy_nodes
           (id, topic_id, name, description, aliases)
           VALUES (10, ?, 'GraphCalibrator', 'Calibrates pacing with a graph encoder', '["GCN pacing"]')""",
        (topic_id,),
    )
    conn.execute(
        """INSERT INTO taxonomy_assignments
           (paper_id, node_id, confidence, evidence)
           VALUES (1, 10, 0.9, 'method section')"""
    )
    conn.execute(
        """INSERT INTO method_atoms
           (topic_id, source_paper_id, atom_type, name, description, deps, reported_gain, reuse_risk)
           VALUES (?, 1, 'micro_block', 'pacing residual gate',
                   'Residual gate for stable budget pacing', '[]', '+3.1% ROI', 'low')""",
        (topic_id,),
    )
    conn.execute(
        """INSERT INTO semantic_atoms
           (topic_id, atom_type, normalized_key, label, description, source_type,
            source_id, paper_id, source_section, snippet, confidence, source_hash,
            extractor_version, metadata_json)
           VALUES (?, 'method', 'graphcalibrator', 'GraphCalibrator',
                   'Semantic method atom for graph pacing calibration',
                   'taxonomy_nodes', '10', 1, 'taxonomy_nodes.name',
                   'GraphCalibrator improves pacing stability', 0.91,
                   'ctx-hash', 'test', '{}')""",
        (topic_id,),
    )
    snapshot_payload = {
        "schema_version": "topic_knowledge_snapshot.v1",
        "covered": {
            "methods": ["GraphCalibrator", "pacing residual gate"],
            "datasets": ["auction logs"],
            "metrics": ["ROI"],
            "gaps": ["cold-start pacing"],
        },
        "weak_spots": {
            "unverified_gaps": ["calibration coverage weak"],
        },
        "research_state": {
            "method_map_summary": {
                "method_count": 2,
                "dataset_count": 1,
                "metric_count": 1,
            },
            "baseline_readiness": {
                "has_baselines": False,
                "has_metrics": True,
                "has_datasets": True,
            },
            "open_gaps": ["cold-start pacing"],
        },
        "next_actions": ["deep_read paper 1"],
    }
    conn.execute(
        """INSERT INTO project_artifacts
           (id, project_id, topic_id, stage, artifact_type, status, title, path,
            payload_json, metadata_json, stale)
           VALUES (20, NULL, ?, 'topic_knowledge', 'topic_knowledge_snapshot',
                   'active', 'Topic knowledge snapshot', 'snapshot.json', ?, '{}', 0)""",
        (topic_id, json.dumps(snapshot_payload)),
    )
    conn.execute(
        """INSERT INTO topic_knowledge_snapshots
           (topic_id, artifact_id, status, snapshot_version, source_hash,
            source_manifest_json, coverage_json)
           VALUES (?, 20, 'active', 'test', 'ctx-hash', '{}',
                   '{"semantic_atoms": 1, "method_atoms": 1, "taxonomy_nodes": 1}')""",
        (topic_id,),
    )


# ---------------------------------------------------------------------------
# design_brief_expand
# ---------------------------------------------------------------------------


class TestDesignBriefExpand:
    def test_basic_expansion(self, db, conn):
        _seed_topic(conn)
        _seed_gap(conn, 1, "No scalable budget allocation method", severity="high")
        _seed_taxonomy_node(conn, 1, "PPO", description="RL policy method")
        _seed_taxonomy_node(conn, 1, "DQN", description="RL value method")
        conn.commit()

        mock_response = json.dumps(
            {
                "problem_definition": "Given a set of campaigns C...",
                "constraints": ["Real-time inference <50ms", "Budget monotonicity"],
                "method_slots": [
                    {
                        "name": "policy_backbone",
                        "role": "Generates bidding actions",
                        "candidates": ["PPO", "SAC"],
                        "status": "open",
                    },
                    {
                        "name": "budget_allocator",
                        "role": "Distributes budget across campaigns",
                        "candidates": ["LP", "DP"],
                        "status": "open",
                    },
                    {
                        "name": "state_encoder",
                        "role": "Encodes market state",
                        "candidates": ["Transformer", "GRU"],
                        "status": "open",
                    },
                ],
                "blocking_questions": ["What is the action space dimensionality?"],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import design_brief_expand

            result = design_brief_expand(
                db=db, topic_id=1, direction="Scalable RL for budget allocation"
            )

        assert result.problem_definition.startswith("Given")
        assert len(result.method_slots) == 3
        assert len(result.constraints) == 2
        assert len(result.blocking_questions) == 1
        assert result.model_used == "test-model"

    def test_with_constraints(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "problem_definition": "Test problem",
                "constraints": ["Constraint A", "Must work on GPU"],
                "method_slots": [
                    {
                        "name": "encoder",
                        "role": "encode",
                        "candidates": ["X"],
                        "status": "open",
                    }
                ],
                "blocking_questions": [],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import design_brief_expand

            result = design_brief_expand(
                db=db,
                topic_id=1,
                direction="Test direction",
                constraints=["Must run on GPU", "Latency < 10ms"],
            )

        assert result.problem_definition == "Test problem"
        assert len(result.method_slots) == 1

    def test_empty_topic(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "problem_definition": "Empty topic problem",
                "constraints": [],
                "method_slots": [],
                "blocking_questions": ["Need more papers"],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import design_brief_expand

            result = design_brief_expand(db=db, topic_id=1, direction="Test")

        assert result.problem_definition
        assert len(result.blocking_questions) >= 1

    def test_malformed_response_graceful(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "problem_definition": "OK",
                "method_slots": [
                    "not a dict",
                    42,
                    {"name": "valid", "role": "r", "candidates": [], "status": "open"},
                ],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import design_brief_expand

            result = design_brief_expand(db=db, topic_id=1, direction="Test")

        assert len(result.method_slots) == 1

    def test_uses_real_schema_method_context(self, db, conn):
        _seed_topic(conn)
        _seed_gap(conn, 1, "Cold-start pacing remains unresolved", severity="high")
        _seed_real_design_context(conn)
        conn.commit()

        captured_prompts = []
        mock_response = json.dumps(
            {
                "problem_definition": "Use real RH context",
                "constraints": [],
                "method_slots": [],
                "blocking_questions": [],
            }
        )

        def mock_chat(_client, prompt):
            captured_prompts.append(prompt)
            return mock_response

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import design_brief_expand

            design_brief_expand(db=db, topic_id=1, direction="Test")

        user_prompt = next(
            prompt[1]
            for prompt in captured_prompts
            if "## Research Direction" in prompt[1]
        )
        assert "GraphCalibrator" in user_prompt
        assert "pacing residual gate" in user_prompt
        assert "calibration coverage weak" in user_prompt
        assert "semantic_atoms" in user_prompt


# ---------------------------------------------------------------------------
# design_gap_probe
# ---------------------------------------------------------------------------


class TestDesignGapProbe:
    def test_basic_probe(self, db, conn):
        _seed_topic(conn)
        _insert_paper(conn, 1, "Transformer for TS", year=2024)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        _seed_taxonomy_node(conn, 1, "Transformer", description="encoder", paper_id=1)
        _seed_topic_summary(conn, 1, paper_ids=[1])
        conn.commit()

        brief = {
            "problem_definition": "Budget allocation under uncertainty",
            "method_slots": [
                {
                    "name": "encoder",
                    "role": "encode state",
                    "candidates": ["Transformer", "GRU"],
                    "status": "open",
                },
                {
                    "name": "decoder",
                    "role": "decode action",
                    "candidates": [],
                    "status": "blocked",
                },
            ],
        }

        mock_response = json.dumps(
            {
                "knowledge_gaps": [
                    {
                        "slot": "decoder",
                        "gap_type": "technique_unknown",
                        "severity": "critical",
                        "search_query": "action decoder RL bidding",
                        "candidate_paper_ids": [1],
                    },
                ],
                "recommended_actions": ["Search for action decoder methods in RL"],
                "deep_read_targets": [1],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import design_gap_probe

            result = design_gap_probe(db=db, topic_id=1, brief=brief)

        assert len(result.knowledge_gaps) == 1
        assert result.knowledge_gaps[0]["severity"] == "critical"
        assert len(result.recommended_actions) == 1
        assert 1 in result.deep_read_targets
        assert result.model_used == "test-model"

    def test_no_gaps(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "knowledge_gaps": [],
                "recommended_actions": [],
                "deep_read_targets": [],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import design_gap_probe

            result = design_gap_probe(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Test", "method_slots": []},
            )

        assert len(result.knowledge_gaps) == 0
        assert len(result.deep_read_targets) == 0

    def test_with_method_inventory_override(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "knowledge_gaps": [
                    {
                        "slot": "planner",
                        "gap_type": "performance_unclear",
                        "severity": "moderate",
                        "search_query": "planning under uncertainty",
                        "candidate_paper_ids": [],
                    },
                ],
                "recommended_actions": ["Check planning benchmarks"],
                "deep_read_targets": [],
            }
        )

        inventory = [
            {"method_name": "MCTS", "category": "planning"},
            {"method_name": "A*", "category": "planning"},
        ]

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import design_gap_probe

            result = design_gap_probe(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Test", "method_slots": []},
                method_inventory=inventory,
            )

        assert len(result.knowledge_gaps) == 1
        assert result.knowledge_gaps[0]["gap_type"] == "performance_unclear"

    def test_deep_read_targets_coerced_to_int(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "knowledge_gaps": [],
                "recommended_actions": [],
                "deep_read_targets": [1, 2.0, "not_an_int", 5],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import design_gap_probe

            result = design_gap_probe(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Test", "method_slots": []},
            )

        assert result.deep_read_targets == [1, 2, 5]

    def test_real_schema_method_inventory_reaches_prompt(self, db, conn):
        _seed_topic(conn)
        _seed_real_design_context(conn)
        conn.commit()

        captured_prompts = []
        mock_response = json.dumps(
            {
                "knowledge_gaps": [],
                "recommended_actions": [],
                "deep_read_targets": [],
            }
        )

        def mock_chat(_client, prompt):
            captured_prompts.append(prompt)
            return mock_response

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import design_gap_probe

            design_gap_probe(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Test", "method_slots": []},
            )

        user_prompt = next(
            prompt[1]
            for prompt in captured_prompts
            if "## Method Inventory" in prompt[1]
        )
        assert "GraphCalibrator" in user_prompt
        assert "pacing residual gate" in user_prompt
        assert "Graph calibration for budget pacing" in user_prompt


# ---------------------------------------------------------------------------
# algorithm_candidate_generate
# ---------------------------------------------------------------------------


class TestAlgorithmCandidateGenerate:
    def test_generates_candidates(self, db, conn):
        _seed_topic(conn)
        _seed_taxonomy_node(conn, 1, "PPO", description="RL policy method")
        conn.commit()

        mock_response = json.dumps(
            {
                "candidates": [
                    {
                        "name": "AdaptiveBidNet",
                        "architecture_description": "A dual-stream network combining...",
                        "components": [
                            {
                                "name": "state_encoder",
                                "role": "encode market state",
                                "provenance_tag": "borrowed",
                                "source_paper_id": 1,
                                "details": "From paper 1",
                            },
                            {
                                "name": "action_decoder",
                                "role": "decode bidding action",
                                "provenance_tag": "novel",
                                "source_paper_id": None,
                                "details": "New design",
                            },
                        ],
                        "novelty_statement": "Novel action decoder with attention-based allocation",
                        "feasibility_notes": "Moderate compute, needs GPU training",
                    },
                    {
                        "name": "BudgetPlanner",
                        "architecture_description": "A planning-based approach...",
                        "components": [
                            {
                                "name": "planner",
                                "role": "plan budget allocation",
                                "provenance_tag": "modified",
                                "source_paper_id": 2,
                                "details": "Modified from paper 2",
                            },
                        ],
                        "novelty_statement": "Modified planning with real-time constraints",
                        "feasibility_notes": "Lightweight, CPU-friendly",
                    },
                ],
                "method_inventory_used": 3,
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                algorithm_candidate_generate,
            )

            result = algorithm_candidate_generate(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Budget allocation", "method_slots": []},
            )

        assert len(result.candidates) == 2
        assert result.candidates[0].name == "AdaptiveBidNet"
        assert len(result.candidates[0].components) == 2
        assert result.candidates[0].provenance_tags == ["borrowed", "novel"]
        assert result.method_inventory_used == 3
        assert result.model_used == "test-model"

    def test_with_deep_read_notes(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "candidates": [
                    {
                        "name": "TestAlg",
                        "architecture_description": "Test arch",
                        "components": [],
                        "novelty_statement": "Novel",
                        "feasibility_notes": "OK",
                    },
                ],
                "method_inventory_used": 1,
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                algorithm_candidate_generate,
            )

            result = algorithm_candidate_generate(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Test", "method_slots": []},
                deep_read_notes=[
                    {"paper_id": 1, "title": "Paper 1", "summary": "Key finding"}
                ],
            )

        assert len(result.candidates) == 1

    def test_malformed_candidates_filtered(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "candidates": [
                    "not_a_dict",
                    {
                        "name": "ValidAlg",
                        "architecture_description": "OK",
                        "components": [
                            {"name": "c1", "role": "r", "provenance_tag": "novel"}
                        ],
                        "novelty_statement": "Novel",
                        "feasibility_notes": "OK",
                    },
                ],
                "method_inventory_used": 0,
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                algorithm_candidate_generate,
            )

            result = algorithm_candidate_generate(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Test", "method_slots": []},
            )

        assert len(result.candidates) == 1
        assert result.candidates[0].name == "ValidAlg"

    def test_analysis_substrate_reaches_candidate_prompt(self, db, conn):
        _seed_topic(conn)
        conn.commit()
        captured_prompts = []

        def mock_chat(_client, prompt):
            captured_prompts.append(prompt)
            return '{"candidates": [], "method_inventory_used": 0}'

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                algorithm_candidate_generate,
            )

            result = algorithm_candidate_generate(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Test", "method_slots": []},
                analysis_substrate={
                    "schema_version": "analysis_substrate.v1",
                    "agenda": {
                        "main_problem_axis": "survey-defined retrieval robustness",
                        "survey_derived": True,
                    },
                    "authority_hierarchy": {
                        "capsules_blocked_from_axis_redefinition": True,
                    },
                },
            )

        assert result.candidates == []
        user_prompt = next(
            prompt[1]
            for prompt in captured_prompts
            if "## Analysis Substrate" in prompt[1]
        )
        assert "survey-defined retrieval robustness" in user_prompt
        assert "capsules_blocked_from_axis_redefinition" in user_prompt

    def test_real_schema_method_inventory_reaches_prompt(self, db, conn):
        _seed_topic(conn)
        _seed_real_design_context(conn)
        conn.commit()

        captured_prompts = []
        mock_response = json.dumps(
            {
                "candidates": [
                    {
                        "name": "SchemaAwareAlg",
                        "architecture_description": "Uses real context",
                        "components": [],
                        "novelty_statement": "Novel",
                        "feasibility_notes": "OK",
                    }
                ],
                "method_inventory_used": 2,
            }
        )

        def mock_chat(_client, prompt):
            captured_prompts.append(prompt)
            return mock_response

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                algorithm_candidate_generate,
            )

            algorithm_candidate_generate(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Test", "method_slots": []},
            )

        user_prompt = next(
            prompt[1]
            for prompt in captured_prompts
            if "## Method Inventory" in prompt[1]
        )
        assert "GraphCalibrator" in user_prompt
        assert "pacing residual gate" in user_prompt
        assert "method_map_summary" in user_prompt

    def test_topic_ablation_memory_reaches_candidate_prompt(self, db, conn):
        _seed_topic(conn)
        conn.commit()
        from research_harness.orchestrator.artifacts import ArtifactManager

        ArtifactManager(db).record(
            topic_id=1,
            stage="experiment",
            artifact_type="experiment_result",
            payload={
                "canonical_components": ["retriever"],
                "ablation_components": ["retriever"],
                "repeats": 3,
                "variance_estimates": [0.01],
                "acceptance_criteria": [],
                "evidence_kind": "final",
                "component_provenance": [
                    {
                        "component_family": "retriever",
                        "provenance_tag": "borrowed",
                        "source_paper_id": 9,
                    }
                ],
                "metric_direction": "maximize",
                "ablation_outcomes": [
                    {
                        "component_family": "retriever",
                        "removal_effect": "helped",
                        "provenance_tag": "borrowed",
                        "source_paper_id": 9,
                        "evidence": (
                            "observed accuracy: full=0.9, without_1=0.95, "
                            "direction=maximize, noise_bound=0.1"
                        ),
                    }
                ],
            },
        )
        captured_prompts = []

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=lambda _client, prompt: (
                    captured_prompts.append(prompt)
                    or '{"candidates": [], "method_inventory_used": 0}'
                ),
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                algorithm_candidate_generate,
            )

            algorithm_candidate_generate(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Test", "method_slots": []},
            )

        user_prompt = captured_prompts[0][1]
        assert "## Ablation Symbolic Memory" in user_prompt
        assert "retriever" in user_prompt
        assert "risky_or_redundant" in user_prompt
        assert "source_paper_id=9" in user_prompt
        assert "full=0.9" not in user_prompt

    def test_observed_experiment_run_reaches_candidate_prompt(self, db, conn):
        _seed_topic(conn)
        conn.commit()
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.primitives.experiment_impls import experiment_run

        run = experiment_run(
            code=(
                'print("condition=full accuracy: 0.9")\n'
                'print("condition=without_1 accuracy: 0.85")\n'
            ),
            primary_metric="accuracy",
            canonical_components=["retriever"],
            ablation_components=["retriever"],
            repeats=3,
            variance_estimates=[0.0001],
            acceptance_criteria=[],
            evidence_kind="final",
            component_provenance=[
                {
                    "component_family": "retriever",
                    "provenance_tag": "borrowed",
                    "source_paper_id": 9,
                }
            ],
        )
        output = {
            "metrics": run.metrics,
            "canonical_components": run.canonical_components,
            "ablation_components": run.ablation_components,
            "repeats": run.repeats,
            "variance_estimates": run.variance_estimates,
            "acceptance_criteria": run.acceptance_criteria,
            "evidence_kind": run.evidence_kind,
            "component_provenance": run.component_provenance,
            "metric_direction": run.metric_direction,
            "ablation_outcomes": run.ablation_outcomes,
        }
        _record_auto_artifacts(
            svc=OrchestratorService(db),
            topic_id=1,
            stage="experiment",
            context={"_output_experiment_run": output},
            results=[ToolResult(tool="experiment_run", success=True, output=output)],
            errors=[],
        )
        captured_prompts = []
        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=lambda _client, prompt: (
                    captured_prompts.append(prompt)
                    or '{"candidates": [], "method_inventory_used": 0}'
                ),
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                algorithm_candidate_generate,
            )

            algorithm_candidate_generate(
                db=db,
                topic_id=1,
                brief={"problem_definition": "Test", "method_slots": []},
            )

        assert "retriever" in captured_prompts[0][1]
        assert "beneficial" in captured_prompts[0][1]


# ---------------------------------------------------------------------------
# algorithm design context observability
# ---------------------------------------------------------------------------


class TestAlgorithmDesignContextObservability:
    def test_missing_derived_context_table_logs_warning(self, conn, caplog):
        _seed_topic(conn)
        conn.execute("DROP TABLE semantic_edges")
        conn.execute("DROP TABLE semantic_atoms")

        from research_harness.execution.llm_primitives import _load_semantic_atom_lines

        with caplog.at_level(
            logging.WARNING,
            logger="research_harness._workflow.execution.llm_primitives",
        ):
            lines = _load_semantic_atom_lines(
                conn,
                1,
                task_type="algorithm_candidate_generate",
                limit=5,
            )

        assert lines == []
        assert "semantic_atoms" in caplog.text
        assert "algorithm_candidate_generate" in caplog.text


# ---------------------------------------------------------------------------
# originality_boundary_check
# ---------------------------------------------------------------------------


class TestOriginalityBoundaryCheck:
    def test_novel_verdict(self, db, conn):
        _seed_topic(conn)
        _insert_paper(
            conn,
            1,
            "Existing Method Paper",
            year=2024,
            compiled_summary="Uses DQN for bidding",
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()

        mock_response = json.dumps(
            {
                "candidate_name": "AdaptiveBidNet",
                "near_matches": [
                    {
                        "paper_id": 1,
                        "title": "Existing Method Paper",
                        "overlap_areas": ["Uses RL"],
                        "differentiation": ["Novel attention decoder"],
                    },
                ],
                "novelty_verdict": "novel",
                "novelty_score": 0.78,
                "recommended_modifications": [],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                originality_boundary_check,
            )

            result = originality_boundary_check(
                db=db,
                topic_id=1,
                candidate={
                    "name": "AdaptiveBidNet",
                    "architecture_description": "Novel attention-based...",
                },
            )

        assert result.novelty_verdict == "novel"
        assert result.novelty_score == 0.78
        assert len(result.near_matches) == 1
        assert len(result.recommended_modifications) == 0

    def test_too_similar_verdict(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "candidate_name": "CopyAlg",
                "near_matches": [
                    {
                        "paper_id": 5,
                        "title": "Very Similar Paper",
                        "overlap_areas": ["Same architecture", "Same loss"],
                        "differentiation": ["Minor parameter change"],
                    },
                ],
                "novelty_verdict": "too_similar",
                "novelty_score": 0.15,
                "recommended_modifications": [
                    "Replace the decoder with a novel attention mechanism",
                    "Add a budget constraint module",
                ],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                originality_boundary_check,
            )

            result = originality_boundary_check(
                db=db,
                topic_id=1,
                candidate={
                    "name": "CopyAlg",
                    "architecture_description": "Same as paper 5",
                },
            )

        assert result.novelty_verdict == "too_similar"
        assert result.novelty_score < 0.3
        assert len(result.recommended_modifications) == 2

    def test_incremental_verdict(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "candidate_name": "IncrementalAlg",
                "near_matches": [
                    {
                        "title": "A retrieved method neighbour",
                        "overlap_areas": ["the same gating module"],
                    }
                ],
                "novelty_verdict": "incremental",
                "novelty_score": 0.45,
                "recommended_modifications": ["Add a unique component"],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                originality_boundary_check,
            )

            result = originality_boundary_check(
                db=db,
                topic_id=1,
                candidate={
                    "name": "IncrementalAlg",
                    "architecture_description": "Minor extension",
                },
            )

        assert result.novelty_verdict == "incremental"
        assert 0.3 <= result.novelty_score <= 0.6

    def test_empty_paper_pool_is_unclear_not_novel(self, db, conn, monkeypatch):
        """No method neighbours at all is too little coverage to call anything novel."""
        from research_harness.primitives import impls
        from research_harness.primitives.types import PaperSearchOutput

        monkeypatch.setattr(
            impls,
            "paper_search",
            lambda **kwargs: PaperSearchOutput(
                papers=[], providers_queried=["local", "crossref"]
            ),
        )
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "candidate_name": "NovelAlg",
                "near_matches": [],
                "novelty_verdict": "novel",
                "novelty_score": 0.9,
                "recommended_modifications": [],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                originality_boundary_check,
            )

            result = originality_boundary_check(
                db=db,
                topic_id=1,
                candidate={"name": "NovelAlg", "architecture_description": "Brand new"},
            )

        assert result.novelty_verdict == "unclear"
        assert result.novelty_score >= 0.6
        assert "coverage cannot support novel" in result.coverage_note


# ---------------------------------------------------------------------------
# Type dataclass tests
# ---------------------------------------------------------------------------


class TestDesignTypes:
    def test_design_brief_output_frozen(self):
        from research_harness.primitives.types import DesignBriefOutput

        out = DesignBriefOutput(problem_definition="test")
        with pytest.raises(AttributeError):
            out.problem_definition = "changed"

    def test_algorithm_candidate_frozen(self):
        from research_harness.primitives.types import AlgorithmCandidate

        c = AlgorithmCandidate(name="test", novelty_statement="novel")
        assert c.name == "test"
        with pytest.raises(AttributeError):
            c.name = "changed"

    def test_design_loop_output_defaults(self):
        from research_harness.primitives.types import AlgorithmDesignLoopOutput

        out = AlgorithmDesignLoopOutput()
        assert out.final_proposal is None
        assert out.rounds_completed == 0
        assert out.convergence_reason == ""
        assert out.papers_read_during_loop == 0

    def test_originality_output_fields(self):
        from research_harness.primitives.types import OriginalityBoundaryCheckOutput

        out = OriginalityBoundaryCheckOutput(
            candidate_name="TestAlg",
            novelty_verdict="novel",
            novelty_score=0.85,
        )
        assert out.novelty_verdict == "novel"
        assert out.novelty_score == 0.85


# ---------------------------------------------------------------------------
# Prompt function tests
# ---------------------------------------------------------------------------


class TestDesignPrompts:
    def test_brief_expand_prompt_returns_tuple(self):
        from research_harness.execution.prompts import design_brief_expand_prompt

        system, user = design_brief_expand_prompt("Test direction")
        assert "algorithm designer" in system.lower()
        assert "Test direction" in user
        assert "Theory constraint" in system

    def test_gap_probe_prompt_returns_tuple(self):
        from research_harness.execution.prompts import design_gap_probe_prompt

        system, user = design_gap_probe_prompt("brief text")
        assert "gap analyst" in system.lower()
        assert "brief text" in user

    def test_candidate_generate_prompt_includes_theory_constraint(self):
        from research_harness.execution.prompts import (
            algorithm_candidate_generate_prompt,
        )

        system, user = algorithm_candidate_generate_prompt("brief text")
        assert "Theory constraint" in system
        assert "provenance" in system.lower()
        assert "untrusted historical evidence" not in system

    def test_candidate_generate_prompt_accepts_optional_ablation_memory(self):
        from research_harness.execution.prompts import (
            algorithm_candidate_generate_prompt,
        )

        system, user = algorithm_candidate_generate_prompt(
            "brief text",
            ablation_memory="- retriever: beneficial",
        )
        assert "untrusted historical evidence" in system
        assert "## Ablation Symbolic Memory" in user
        assert "retriever: beneficial" in user

        _system, user_without_memory = algorithm_candidate_generate_prompt("brief text")
        assert "## Ablation Symbolic Memory" not in user_without_memory

    def test_originality_prompt_has_verdict_options(self):
        from research_harness.execution.prompts import originality_boundary_check_prompt

        system, user = originality_boundary_check_prompt("candidate text")
        assert "novel" in system
        assert "incremental" in system
        assert "too_similar" in system

    def test_candidate_generate_prompt_accepts_analysis_substrate(self):
        from research_harness.execution.prompts import (
            algorithm_candidate_generate_prompt,
        )

        system, user = algorithm_candidate_generate_prompt(
            "brief text",
            analysis_substrate='{"agenda":{"survey_derived":true}}',
        )
        assert "survey defines the agenda" in system.lower()
        assert "paper capsules" in system.lower()
        assert "## Analysis Substrate" in user
        assert '"survey_derived":true' in user

    def test_refine_prompt_includes_theory_constraint(self):
        from research_harness.execution.prompts import algorithm_design_refine_prompt

        system, user = algorithm_design_refine_prompt("candidate text")
        assert "Theory constraint" in system
        assert "proposal" in system.lower()

    def test_refine_calibrates_a_novel_draft_and_revises_a_refused_one(self):
        """A calibrator cannot answer a novelty refusal, and the gate asks it to.

        The refined proposal must clear the originality floor, while this prompt
        told the stage not to invent a new primary mechanism and to preserve the
        idea unchanged when nothing is broken. Under a non-novel verdict those
        are the same instruction as "restate it", which is what came back.
        """
        from research_harness.execution.prompts import algorithm_design_refine_prompt

        calibration, _ = algorithm_design_refine_prompt("candidate text")
        assert "1.0" in calibration and "calibrator" in calibration.lower()

        revision, _ = algorithm_design_refine_prompt(
            "candidate text", novelty_verdict="incremental"
        )
        assert "calibrator" not in revision.lower()
        assert "preserved_unchanged" in revision
        assert "recommended_modifications" in revision

    def test_prompts_handle_empty_optional_args(self):
        from research_harness.execution.prompts import (
            design_brief_expand_prompt,
            design_gap_probe_prompt,
            algorithm_candidate_generate_prompt,
            originality_boundary_check_prompt,
            algorithm_design_refine_prompt,
        )

        for fn in [
            design_brief_expand_prompt,
            design_gap_probe_prompt,
            algorithm_candidate_generate_prompt,
            originality_boundary_check_prompt,
            algorithm_design_refine_prompt,
        ]:
            system, user = fn("test")
            assert isinstance(system, str)
            assert isinstance(user, str)
            assert len(system) > 0
            assert len(user) > 0


# ---------------------------------------------------------------------------
# algorithm_design_refine
# ---------------------------------------------------------------------------


class TestAlgorithmDesignRefine:
    def test_basic_refine(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "proposal_title": "AdaptiveBidNet: Attention-Based Budget Allocation",
                "problem_formulation": "Given campaigns C = {c1..cn} with budgets B...",
                "algorithm_description": "A dual-stream network that...",
                "components": [
                    {
                        "name": "state_encoder",
                        "role": "encode",
                        "provenance_tag": "borrowed",
                        "source_paper_id": 1,
                        "details": "Transformer from paper 1",
                    },
                    {
                        "name": "action_decoder",
                        "role": "decode",
                        "provenance_tag": "novel",
                        "source_paper_id": None,
                        "details": "Novel attention decoder",
                    },
                ],
                "novelty_statement": "Unlike prior work, our method uses attention-based allocation",
                "experiment_hooks": [
                    "Compare vs PPO baseline",
                    "Ablate attention module",
                ],
                "provenance_summary": [
                    {
                        "component": "state_encoder",
                        "origin": "borrowed",
                        "source": "Paper 1",
                    },
                    {
                        "component": "action_decoder",
                        "origin": "novel",
                        "source": "This work",
                    },
                ],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                algorithm_design_refine,
            )

            result = algorithm_design_refine(
                db=db,
                topic_id=1,
                candidate={
                    "name": "AdaptiveBidNet",
                    "architecture_description": "A dual-stream...",
                },
                originality_result={"novelty_verdict": "novel", "novelty_score": 0.8},
            )

        assert (
            result.proposal_title == "AdaptiveBidNet: Attention-Based Budget Allocation"
        )
        assert len(result.components) == 2
        assert len(result.experiment_hooks) == 2
        assert len(result.provenance_summary) == 2
        assert result.model_used == "test-model"

    def test_refine_with_feedback_and_constraints(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "proposal_title": "Refined Proposal",
                "problem_formulation": "Revised formulation...",
                "algorithm_description": "Improved algorithm...",
                "components": [],
                "novelty_statement": "Stronger novelty after revision",
                "experiment_hooks": ["Test A"],
                "provenance_summary": [],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                algorithm_design_refine,
            )

            result = algorithm_design_refine(
                db=db,
                topic_id=1,
                candidate={"name": "TestAlg"},
                feedback="Increase novelty in decoder",
                constraints=["Must run on CPU", "Latency < 50ms"],
            )

        assert result.proposal_title == "Refined Proposal"
        assert result.novelty_statement.startswith("Stronger")

    def test_refine_malformed_components_filtered(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        mock_response = json.dumps(
            {
                "proposal_title": "Test",
                "problem_formulation": "Test",
                "algorithm_description": "Test",
                "components": ["not_a_dict", {"name": "valid", "role": "r"}],
                "novelty_statement": "Novel",
                "experiment_hooks": [],
                "provenance_summary": [42, {"component": "x", "origin": "novel"}],
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import (
                algorithm_design_refine,
            )

            result = algorithm_design_refine(
                db=db,
                topic_id=1,
                candidate={"name": "Test"},
            )

        assert len(result.components) == 1
        assert len(result.provenance_summary) == 1

    def test_refine_output_frozen(self):
        from research_harness.primitives.types import AlgorithmDesignRefineOutput

        out = AlgorithmDesignRefineOutput(proposal_title="test")
        with pytest.raises(AttributeError):
            out.proposal_title = "changed"


# ---------------------------------------------------------------------------
# algorithm_design_loop
# ---------------------------------------------------------------------------


def _make_brief_response():
    return json.dumps(
        {
            "problem_definition": "Budget allocation under uncertainty",
            "constraints": ["Real-time"],
            "method_slots": [
                {
                    "name": "encoder",
                    "role": "encode",
                    "candidates": ["T"],
                    "status": "open",
                }
            ],
            "blocking_questions": [],
        }
    )


def _make_gap_response(has_critical=False):
    gaps = []
    if has_critical:
        gaps.append(
            {
                "slot": "encoder",
                "gap_type": "technique_unknown",
                "severity": "critical",
                "search_query": "encoder methods",
            }
        )
    return json.dumps(
        {
            "knowledge_gaps": gaps,
            "recommended_actions": [],
            "deep_read_targets": [],
        }
    )


def _make_candidate_response(name="TestAlg"):
    return json.dumps(
        {
            "candidates": [
                {
                    "name": name,
                    "architecture_description": "Test arch",
                    "components": [
                        {"name": "c1", "role": "r", "provenance_tag": "novel"}
                    ],
                    "novelty_statement": "Novel approach",
                    "feasibility_notes": "OK",
                    "exhaustion_test": {
                        "cheapest_reimplementation": "lightweight_baseline",
                        "what_it_reproduces": "the marginal ranking",
                        "gap_it_leaves": "requires learned policy",
                    },
                    "irreducible_components": ["a policy solved end to end"],
                }
            ],
            "method_inventory_used": 1,
        }
    )


def _make_originality_response(verdict="novel", score=0.8):
    return json.dumps(
        {
            "candidate_name": "TestAlg",
            "near_matches": [],
            "novelty_verdict": verdict,
            "novelty_score": score,
            "recommended_modifications": []
            if verdict == "novel"
            else ["Add unique component"],
        }
    )


def _make_refine_response():
    return json.dumps(
        {
            "proposal_title": "Final Proposal",
            "problem_formulation": "Formal problem...",
            "algorithm_description": "End-to-end algorithm...",
            "components": [{"name": "c1", "role": "r", "provenance_tag": "novel"}],
            "novelty_statement": "Unlike prior work, this is novel",
            "experiment_hooks": ["Test vs baseline"],
            "provenance_summary": [
                {"component": "c1", "origin": "novel", "source": "This work"}
            ],
        }
    )


class TestAlgorithmDesignLoop:
    def test_converges_in_one_round(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        responses = [
            _make_brief_response(),
            _make_gap_response(has_critical=False),
            _make_candidate_response(),
            _make_originality_response(verdict="novel", score=0.85),
            _make_refine_response(),
        ]
        call_idx = {"i": 0}
        captured_prompts = []

        def mock_chat(_client, prompt):
            captured_prompts.append(prompt)
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[idx]

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import algorithm_design_loop

            result = algorithm_design_loop(
                db=db,
                topic_id=1,
                project_id=1,
                direction="Test direction",
            )

        assert result.convergence_reason == "novel_and_no_critical_gaps"
        assert result.rounds_completed == 1
        assert result.final_proposal is not None
        assert result.final_proposal.proposal_title == "Final Proposal"
        assert len(result.briefs) == 1
        assert len(result.gap_probes) == 1
        assert len(result.candidates_history) == 1
        assert len(result.originality_checks) == 1
        assert (
            result.candidates_history[0].candidates[0].exhaustion_test["gap_it_leaves"]
            == "requires learned policy"
        )
        assert result.candidates_history[0].candidates[0].irreducible_components == [
            "a policy solved end to end"
        ]
        assert '"gap_it_leaves": "requires learned policy"' in captured_prompts[3][1]
        assert (
            '"irreducible_components": [\n    "a policy solved end to end"'
            in captured_prompts[3][1]
        )
        assert '"gap_it_leaves": "requires learned policy"' in captured_prompts[4][1]

    def test_converges_after_refinement(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        # Round 1: incremental → refine → Round 2: novel → done
        responses = [
            # Round 1
            _make_brief_response(),
            _make_gap_response(has_critical=False),
            _make_candidate_response("AlgV1"),
            _make_originality_response(verdict="incremental", score=0.45),
            _make_refine_response(),  # intermediate refine
            # Round 2
            _make_brief_response(),
            _make_gap_response(has_critical=False),
            _make_candidate_response("AlgV2"),
            _make_originality_response(verdict="novel", score=0.82),
            _make_refine_response(),  # final refine
        ]
        call_idx = {"i": 0}

        def mock_chat(*args, **kwargs):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[idx]

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import algorithm_design_loop

            result = algorithm_design_loop(
                db=db,
                topic_id=1,
                project_id=1,
                direction="Test direction",
                max_rounds=3,
            )

        assert result.convergence_reason == "novel_and_no_critical_gaps"
        assert result.rounds_completed == 2
        assert len(result.briefs) == 2
        assert len(result.originality_checks) == 2

    def test_max_rounds_hit(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        # Every round returns incremental — never converges
        round_responses = [
            _make_brief_response(),
            _make_gap_response(has_critical=False),
            _make_candidate_response(),
            _make_originality_response(verdict="incremental", score=0.4),
            _make_refine_response(),
        ]
        all_responses = round_responses * 2  # 2 rounds
        call_idx = {"i": 0}

        def mock_chat(*args, **kwargs):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return all_responses[idx]

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import algorithm_design_loop

            result = algorithm_design_loop(
                db=db,
                topic_id=1,
                project_id=1,
                direction="Test",
                max_rounds=2,
            )

        assert result.convergence_reason == "max_rounds_reached"
        assert result.rounds_completed == 2
        assert result.final_proposal is not None

    def test_no_candidates_early_stop(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        responses = [
            _make_brief_response(),
            _make_gap_response(has_critical=False),
            json.dumps(
                {"candidates": [], "method_inventory_used": 0}
            ),  # empty candidates
        ]
        call_idx = {"i": 0}

        def mock_chat(*args, **kwargs):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[idx]

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import algorithm_design_loop

            result = algorithm_design_loop(
                db=db,
                topic_id=1,
                project_id=1,
                direction="Test",
            )

        assert result.convergence_reason == "no_candidates_generated"
        assert result.final_proposal is None

    def test_critical_gaps_prevent_convergence(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        # Round 1: novel but critical gaps → doesn't converge
        # Round 2: novel and no gaps → converges
        responses = [
            # Round 1
            _make_brief_response(),
            _make_gap_response(has_critical=True),
            _make_candidate_response(),
            _make_originality_response(verdict="novel", score=0.85),
            _make_refine_response(),
            # Round 2
            _make_brief_response(),
            _make_gap_response(has_critical=False),
            _make_candidate_response(),
            _make_originality_response(verdict="novel", score=0.88),
            _make_refine_response(),
        ]
        call_idx = {"i": 0}

        def mock_chat(*args, **kwargs):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[idx]

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import algorithm_design_loop

            result = algorithm_design_loop(
                db=db,
                topic_id=1,
                project_id=1,
                direction="Test",
                max_rounds=3,
            )

        assert result.convergence_reason == "novel_and_no_critical_gaps"
        assert result.rounds_completed == 2

    def test_loop_with_constraints(self, db, conn):
        _seed_topic(conn)
        conn.commit()

        responses = [
            _make_brief_response(),
            _make_gap_response(),
            _make_candidate_response(),
            _make_originality_response(),
            _make_refine_response(),
        ]
        call_idx = {"i": 0}

        def mock_chat(*args, **kwargs):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[idx]

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import algorithm_design_loop

            result = algorithm_design_loop(
                db=db,
                topic_id=1,
                project_id=1,
                direction="Test direction",
                constraints=["Must run on GPU", "Latency < 100ms"],
            )

        assert result.convergence_reason == "novel_and_no_critical_gaps"
        assert result.final_proposal is not None

    def test_deep_reading_annotation_content_reaches_candidate_prompt(self, db, conn):
        _seed_topic(conn)
        _insert_paper(
            conn,
            1,
            "Deep read target",
            year=2025,
            compiled_summary=json.dumps(
                {
                    "problem": "budget pacing",
                    "method": "deep read target method",
                    "findings": ["requires deep read"],
                }
            ),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        _seed_topic_summary(conn, 1, paper_ids=[1])
        conn.execute(
            """INSERT INTO paper_annotations (paper_id, section, content)
               VALUES (1, 'deep_reading', ?)""",
            (
                json.dumps(
                    {
                        "algorithm_walkthrough": "Deep graph pacing walkthrough",
                        "critical_assessment": "Critical failure mode in sparse auctions",
                        "research_implications": ["Use conservative residual gates"],
                    }
                ),
            ),
        )
        conn.commit()

        responses = [
            _make_brief_response(),
            json.dumps(
                {
                    "knowledge_gaps": [],
                    "recommended_actions": ["deep-read paper 1"],
                    "deep_read_targets": [1],
                }
            ),
            _make_candidate_response(),
            _make_originality_response(verdict="novel", score=0.85),
            _make_refine_response(),
        ]
        captured_prompts = []
        call_idx = {"i": 0}

        def mock_chat(_client, prompt):
            captured_prompts.append(prompt)
            idx = call_idx["i"]
            call_idx["i"] += 1
            return responses[idx]

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                side_effect=mock_chat,
            ),
        ):
            mock_client.return_value = MagicMock(model="test-model")
            from research_harness.execution.llm_primitives import algorithm_design_loop

            result = algorithm_design_loop(
                db=db,
                topic_id=1,
                direction="Test",
                max_rounds=1,
            )

        assert result.papers_read_during_loop == 1
        candidate_prompt = captured_prompts[2][1]
        assert "Deep graph pacing walkthrough" in candidate_prompt
        assert "Critical failure mode in sparse auctions" in candidate_prompt
        assert "Use conservative residual gates" in candidate_prompt


# ---------------------------------------------------------------------------
# Harness actions integration
# ---------------------------------------------------------------------------


class TestDesignHarnessActions:
    def test_static_next_actions_registered(self):
        from research_harness.execution.harness_actions import STATIC_NEXT_ACTIONS

        assert "design_brief_expand" in STATIC_NEXT_ACTIONS
        assert "design_gap_probe" in STATIC_NEXT_ACTIONS
        assert "algorithm_candidate_generate" in STATIC_NEXT_ACTIONS
        assert "originality_boundary_check" in STATIC_NEXT_ACTIONS
        assert "algorithm_design_refine" in STATIC_NEXT_ACTIONS
        assert "algorithm_design_loop" in STATIC_NEXT_ACTIONS

    def test_design_actions_chain_correctly(self):
        from research_harness.execution.harness_actions import STATIC_NEXT_ACTIONS

        assert "design_gap_probe" in STATIC_NEXT_ACTIONS["design_brief_expand"][0]
        assert (
            "algorithm_candidate_generate" in STATIC_NEXT_ACTIONS["design_gap_probe"][0]
        )
        assert (
            "originality_boundary_check"
            in STATIC_NEXT_ACTIONS["algorithm_candidate_generate"][0]
        )
        assert (
            "algorithm_design_refine"
            in STATIC_NEXT_ACTIONS["originality_boundary_check"][0]
        )


# ---------------------------------------------------------------------------
# Orchestrator + MCP integration
# ---------------------------------------------------------------------------


class TestDesignIntegration:
    def test_algorithm_proposal_artifact_alias(self):
        from research_harness.orchestrator.stages import ARTIFACT_STAGE_ALIASES

        assert ARTIFACT_STAGE_ALIASES["algorithm_proposal"] == "propose"

    def test_propose_soft_prerequisites_mention_algorithm(self):
        from research_harness.orchestrator.stages import get_soft_prerequisites

        prereqs = get_soft_prerequisites("propose")
        assert any("algorithm" in p.lower() for p in prereqs)

    def test_all_design_primitives_in_registry(self):
        from research_harness.primitives.registry import PRIMITIVE_REGISTRY

        design_primitives = [
            "design_brief_expand",
            "design_gap_probe",
            "algorithm_candidate_generate",
            "originality_boundary_check",
            "algorithm_design_refine",
            "algorithm_design_loop",
        ]
        for name in design_primitives:
            assert name in PRIMITIVE_REGISTRY, f"{name} missing from registry"

    def test_harness_backend_supports_all_design_primitives(self, db):
        from research_harness.execution.harness import ResearchHarnessBackend

        backend = ResearchHarnessBackend(db=db)
        design_primitives = [
            "design_brief_expand",
            "design_gap_probe",
            "algorithm_candidate_generate",
            "originality_boundary_check",
            "algorithm_design_refine",
            "algorithm_design_loop",
        ]
        for name in design_primitives:
            assert backend.supports(name), f"Backend doesn't support {name}"
