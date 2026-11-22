"""XCI06: idea taste modes + structured fusion calibrator."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


from research_harness.execution import prompts
from research_harness.primitives.types import AlgorithmDesignRefineOutput


MODES = [
    "high_risk_exploration",
    "cross_domain_transfer",
    "conservative_engineering",
    "ambitious_but_implementable",
    "evidence_first",
]


def test_five_modes_inject_distinct_objective_and_operator_bias():
    blocks = {m: prompts.taste_mode_block(m) for m in MODES}
    assert all(blocks.values())
    # each must carry both objective and operator bias text, not a bare adjective
    for m, block in blocks.items():
        assert "Objective bias:" in block
        assert "Operator bias:" in block
        assert "NOT a style adjective" in block
    # pairwise distinct
    vals = list(blocks.values())
    assert len(set(vals)) == 5


def test_unknown_mode_is_noop():
    assert prompts.taste_mode_block("") == ""
    assert prompts.taste_mode_block("made_up_mode") == ""
    assert prompts.normalize_taste_mode("nope") == ""
    assert prompts.normalize_taste_mode("evidence-first") == "evidence_first"


def test_candidate_prompt_carries_mode_prior():
    system, _user = prompts.algorithm_candidate_generate_prompt(
        "brief", taste_mode="evidence_first"
    )
    assert "IDEA TASTE MODE" in system
    assert "evidence-first" in system
    assert "source_paper_id" in system
    system2, _ = prompts.algorithm_candidate_generate_prompt("brief")
    assert "IDEA TASTE MODE" not in system2


def test_refine_prompt_encodes_f7_calibrator_and_fusion_rules():
    system, _ = prompts.algorithm_design_refine_prompt("cand")
    assert "1.0→1.1 calibrator" in system or "1.0" in system
    assert "NOT a 2.0 invention stage" in system
    assert "STRUCTURED FUSION" in system
    assert "preserved_unchanged" in system
    assert "second competing novelty" in system.lower() or "second competing" in system
    assert '"fusion"' in system


def _seed_topic(conn, topic_id=1, name="test"):
    # inline: do not `from tests.test_design` — bare `tests` collides across packages
    conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (topic_id, name))


def test_refine_parses_fusion_metadata(db, conn):
    _seed_topic(conn)
    conn.commit()

    mock_response = json.dumps(
        {
            "proposal_title": "Host Thesis Paper",
            "problem_formulation": "P",
            "algorithm_description": "A",
            "components": [{"name": "core", "role": "novel-core"}],
            "novelty_statement": "One claim only",
            "experiment_hooks": ["e1"],
            "provenance_summary": [],
            "fusion": {
                "host_thesis": "attention-based allocation",
                "selected_components": [{"name": "core", "reason": "supports_thesis"}],
                "rejected_components": [
                    {"name": "rival_head", "reason": "second_novelty_claim"}
                ],
                "conflict_resolutions": [
                    {
                        "conflict": "rival_head claimed separate novelty",
                        "resolution": "dropped; host owns sole claim",
                    }
                ],
                "weak_part_named": "decoder lacked variance reporting",
                "preserved_unchanged": False,
            },
        }
    )

    with (
        patch("research_harness.execution.llm_primitives._get_client") as mock_client,
        patch(
            "research_harness.execution.llm_primitives._client_chat",
            return_value=mock_response,
        ),
    ):
        mock_client.return_value = MagicMock(model="test-model")
        from research_harness.execution.llm_primitives import algorithm_design_refine

        result = algorithm_design_refine(
            db=db,
            topic_id=1,
            candidate={"name": "Host"},
            taste_mode="ambitious_but_implementable",
        )

    assert result.refinement_posture == "calibrator_1_0_to_1_1"
    assert result.taste_mode == "ambitious_but_implementable"
    assert result.fusion["host_thesis"] == "attention-based allocation"
    assert result.fusion["rejected_components"][0]["name"] == "rival_head"
    assert result.fusion["weak_part_named"]
    assert result.fusion["preserved_unchanged"] is False


def test_refine_malformed_fusion_becomes_empty(db, conn):
    _seed_topic(conn)
    conn.commit()
    mock_response = json.dumps(
        {
            "proposal_title": "T",
            "problem_formulation": "P",
            "algorithm_description": "A",
            "components": [],
            "novelty_statement": "N",
            "experiment_hooks": [],
            "provenance_summary": [],
            "fusion": "not-a-dict",
        }
    )
    with (
        patch("research_harness.execution.llm_primitives._get_client") as mock_client,
        patch(
            "research_harness.execution.llm_primitives._client_chat",
            return_value=mock_response,
        ),
    ):
        mock_client.return_value = MagicMock(model="m")
        from research_harness.execution.llm_primitives import algorithm_design_refine

        result = algorithm_design_refine(db=db, topic_id=1, candidate={"name": "X"})
    assert result.fusion == {}
    assert result.refinement_posture == "calibrator_1_0_to_1_1"


def test_refine_output_defaults_preserve_legacy_shape():
    out = AlgorithmDesignRefineOutput(proposal_title="t")
    assert out.fusion == {}
    assert out.taste_mode == ""
    assert out.refinement_posture == "calibrator_1_0_to_1_1"
