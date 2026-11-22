"""EAG-Ladder batch 2: L2 paragraph craft + claim-logic tree (opt-in).

All LLM surfaces are faked; tests are deterministic.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import research_harness._workflow.execution.llm_primitives as LP
import research_harness.primitives.logic_impls as LOGIC
from research_harness._selfdev.writing_ab_eval import CONDITIONS
from research_harness._workflow.execution.writing_checks import (
    check_logic_obligation_coverage,
)
from research_harness.auto_runner.tool_dispatch import (
    _maybe_auto_exemplar_paragraph_moves_plan,
    _maybe_auto_logic_tree,
)
from research_harness.orchestrator.service import OrchestratorService
from research_harness.primitives import exemplar_impls as EAG
from research_harness.primitives.logic_impls import (
    obligations_for_section,
    render_obligations_block,
)
from research_harness.primitives.registry import _EXEMPLAR_UNIT_TYPES

from .test_paper_production_defaults import _create_topic
from .test_eag_section_arcs import _PASSING_PLAN, _capture_draft_prompts


def test_paragraph_moves_unit_registered():
    assert "paragraph_moves" in EAG._CURATE_PROMPTS
    assert "paragraph_moves" in EAG._PLAN_PROMPTS
    assert "paragraph_moves" in _EXEMPLAR_UNIT_TYPES
    for unit in ("related_work_arc", "method_arc", "experiment_arc", "discussion_arc"):
        assert unit in _EXEMPLAR_UNIT_TYPES, unit


def test_conditions_ladder_is_cumulative_and_fully_pinned():
    assert list(CONDITIONS) == ["C0", "C1", "C2", "C3", "C4"]
    for name, env in CONDITIONS.items():
        assert len(env) == 4, name  # every switch pinned, no ambient leakage
    assert CONDITIONS["C0"]["RESEARCH_HARNESS_EAG_LOGIC_TREE"] == "0"
    assert CONDITIONS["C3"]["RESEARCH_HARNESS_EAG_PARAGRAPH_MOVES"] == "1"
    assert CONDITIONS["C3"]["RESEARCH_HARNESS_EAG_LOGIC_TREE"] == "0"
    assert CONDITIONS["C4"]["RESEARCH_HARNESS_EAG_LOGIC_TREE"] == "1"


# ---------------------------------------------------------------------------
# logic_tree_build
# ---------------------------------------------------------------------------

_TREE_JSON = json.dumps(
    {
        "tree": {
            "root_id": "n1",
            "nodes": [
                {
                    "node_id": "n1",
                    "claim": "Core claim about the estimator",
                    "parent_id": "",
                    "section_hint": "introduction",
                    "evidence_paper_ids": [],
                    "obligation": "state the claim",
                },
                {
                    "node_id": "n2",
                    "claim": "Graph encoder captures event structure",
                    "parent_id": "n1",
                    "section_hint": "method",
                    "evidence_paper_ids": [999],
                    "obligation": "derive the encoder",
                },
                {
                    "node_id": "n3",
                    "claim": "Orphan with unknown parent",
                    "parent_id": "nope",
                    "section_hint": "results",
                    "evidence_paper_ids": [],
                    "obligation": "measure it",
                },
                {
                    "node_id": "n4",
                    "claim": "Bad section hint gets blanked",
                    "parent_id": "n1",
                    "section_hint": "appendix-z",
                    "evidence_paper_ids": [],
                    "obligation": "defend it",
                },
            ],
        }
    }
)


def test_logic_tree_build_validates_deterministically(monkeypatch):
    monkeypatch.setattr(LOGIC, "_chat", lambda client, prompt: _TREE_JSON)

    out = LOGIC.logic_tree_build(
        db=None, topic_id=None, target_content="contributions..."
    )

    ids = [n.node_id for n in out.nodes]
    assert ids == ["n1", "n2", "n4"]  # orphan n3 dropped
    assert out.root_id == "n1"
    assert out.n_nodes == 3
    n2 = next(n for n in out.nodes if n.node_id == "n2")
    assert n2.evidence_paper_ids == []  # 999 not in the (empty) valid id set
    n4 = next(n for n in out.nodes if n.node_id == "n4")
    assert n4.section_hint == ""  # invalid hint blanked
    assert out.sections_covered == ["introduction", "method"]


def test_logic_tree_build_without_target_is_noop():
    out = LOGIC.logic_tree_build(db=None, topic_id=None, target_content="")
    assert out.n_nodes == 0 and out.nodes == []


# ---------------------------------------------------------------------------
# deterministic consumers
# ---------------------------------------------------------------------------

_TREE_PAYLOAD = {
    "nodes": [
        {
            "node_id": "n1",
            "claim": "Estimator beats naive pooling",
            "section_hint": "method",
            "evidence_paper_ids": [7],
            "obligation": "derive the estimator formally",
        },
        {
            "node_id": "n2",
            "claim": "Calibration transfers across cities",
            "section_hint": "results",
            "evidence_paper_ids": [],
            "obligation": "measure transfer error",
        },
    ]
}


def test_obligations_selection_and_rendering():
    method = obligations_for_section(_TREE_PAYLOAD, "method")
    assert [n["node_id"] for n in method] == ["n1"]
    block = render_obligations_block(method)
    assert "LOGIC OBLIGATIONS" in block
    assert "derive the estimator" in block
    assert "[evidence papers: [7]]" in block
    assert render_obligations_block([]) == ""


def test_check_logic_obligation_coverage():
    obligations = obligations_for_section(_TREE_PAYLOAD, "method")
    covered = check_logic_obligation_coverage(
        "We derive the estimator and show pooling comparisons.", obligations
    )
    assert covered.passed, covered.details
    uncovered = check_logic_obligation_coverage(
        "This paragraph discusses unrelated weather patterns.", obligations
    )
    assert not uncovered.passed
    assert uncovered.items_found and uncovered.items_found[0].startswith("n1")


# ---------------------------------------------------------------------------
# producers (tool_dispatch)
# ---------------------------------------------------------------------------


def test_logic_tree_producer_gated_and_records(db, monkeypatch):
    from research_harness.primitives.types import LogicTreeNode, LogicTreeOutput

    topic_id = _create_topic(db, "logic-tree-topic")
    svc = OrchestratorService(db)
    fake_out = LogicTreeOutput(
        nodes=[LogicTreeNode(node_id="n1", claim="c", section_hint="method")],
        root_id="n1",
        n_nodes=1,
        sections_covered=["method"],
        model_used="fake",
    )
    calls: list[int] = []

    def fake_build(**kwargs):
        calls.append(1)
        return fake_out

    monkeypatch.setattr(
        "research_harness.primitives.logic_impls.logic_tree_build", fake_build
    )

    monkeypatch.delenv("RESEARCH_HARNESS_EAG_LOGIC_TREE", raising=False)
    _maybe_auto_logic_tree(
        db=db, svc=svc, topic_id=topic_id, context={"title": "T"}, results=[]
    )
    assert calls == []

    monkeypatch.setenv("RESEARCH_HARNESS_EAG_LOGIC_TREE", "1")
    results: list[Any] = []
    _maybe_auto_logic_tree(
        db=db, svc=svc, topic_id=topic_id, context={"title": "T"}, results=results
    )
    artifact = svc.get_latest_artifact(topic_id, "write", "logic_tree")
    assert artifact is not None
    assert artifact.payload["n_nodes"] == 1
    assert [r.tool for r in results] == ["logic_tree_build"]

    # Idempotent.
    _maybe_auto_logic_tree(
        db=db, svc=svc, topic_id=topic_id, context={}, results=results
    )
    assert calls == [1]


def test_paragraph_moves_producer_gated(db, monkeypatch):
    topic_id = _create_topic(db, "paragraph-moves-topic")
    svc = OrchestratorService(db)
    calls: list[str] = []

    def fake_curate(*, unit_type: str, **kwargs):
        calls.append(unit_type)
        return SimpleNamespace(
            unit_type=unit_type, units=[SimpleNamespace(source_paper_id=1)]
        )

    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_curate", fake_curate
    )
    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_retrieve",
        lambda **k: SimpleNamespace(ranked=k.get("units") or []),
    )
    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_plan",
        lambda **k: SimpleNamespace(
            plan={"templates": [{"role": "claim-development"}]},
            exemplar_ids=[1],
            form_only=True,
        ),
    )

    monkeypatch.delenv("RESEARCH_HARNESS_EAG_PARAGRAPH_MOVES", raising=False)
    _maybe_auto_exemplar_paragraph_moves_plan(
        db=db, svc=svc, topic_id=topic_id, context={}, results=[]
    )
    assert calls == []

    monkeypatch.setenv("RESEARCH_HARNESS_EAG_PARAGRAPH_MOVES", "1")
    _maybe_auto_exemplar_paragraph_moves_plan(
        db=db, svc=svc, topic_id=topic_id, context={"title": "T"}, results=[]
    )
    artifact = svc.get_latest_artifact(
        topic_id, "write", "exemplar_plan_paragraph_moves"
    )
    assert artifact is not None
    assert calls == ["paragraph_moves"]


# ---------------------------------------------------------------------------
# consumer (section_draft guidance blocks)
# ---------------------------------------------------------------------------


def _seed_batch2_artifacts(db, topic_id: int) -> None:
    svc = OrchestratorService(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="exemplar_plan_paragraph_moves",
        title="paragraph craft",
        payload={
            "unit_type": "paragraph_moves",
            "plan": {
                "templates": [
                    {
                        "role": "PARA-MARKER-role",
                        "move_seq": ["topic-claim", "evidence"],
                    }
                ],
                "transition_directive": "semantic echo",
            },
        },
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="logic_tree",
        title="tree",
        payload={
            "nodes": [
                {
                    "node_id": "n1",
                    "claim": "OBLIG-MARKER estimator dominates",
                    "section_hint": "method",
                    "evidence_paper_ids": [],
                    "obligation": "derive it",
                }
            ]
        },
    )


def test_section_draft_injects_batch2_blocks_when_enabled(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_PARAGRAPH_MOVES", "1")
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_LOGIC_TREE", "1")
    topic_id = _create_topic(db, "batch2-consume-on")
    _seed_batch2_artifacts(db, topic_id)
    captured = _capture_draft_prompts(monkeypatch)

    LP.section_draft(
        db=db, section="method", topic_id=topic_id, paper_plan=_PASSING_PLAN
    )

    joined = "\n".join(captured)
    assert "PARA-MARKER-role" in joined
    assert "OBLIG-MARKER" in joined
    assert "LOGIC OBLIGATIONS" in joined


def test_section_draft_ignores_batch2_blocks_by_default(db, monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_EAG_PARAGRAPH_MOVES", raising=False)
    monkeypatch.delenv("RESEARCH_HARNESS_EAG_LOGIC_TREE", raising=False)
    topic_id = _create_topic(db, "batch2-consume-off")
    _seed_batch2_artifacts(db, topic_id)
    captured = _capture_draft_prompts(monkeypatch)

    LP.section_draft(
        db=db, section="method", topic_id=topic_id, paper_plan=_PASSING_PLAN
    )

    joined = "\n".join(captured)
    assert "PARA-MARKER-role" not in joined
    assert "OBLIG-MARKER" not in joined
