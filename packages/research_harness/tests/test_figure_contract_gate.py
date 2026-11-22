"""Write/finalize figure-contract gate (default ON; env 0 disables)."""

from __future__ import annotations

import json

from research_harness.orchestrator.invariants import InvariantChecker


def _seed_topic(db) -> int:
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO topics (name, status) VALUES ('t', 'active')")
        tid = cur.lastrowid
        conn.commit()
        return tid
    finally:
        conn.close()


def _add_artifact(db, topic_id, atype, payload, stage="write"):
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO project_artifacts (topic_id, stage, artifact_type, status, "
            "payload_json, created_at) VALUES (?, ?, ?, 'active', ?, datetime('now'))",
            (topic_id, stage, atype, json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def _complete_plan(**extra):
    payload = {
        "matrix_coverage": {
            "verdict": "complete",
            "unfeedable_panels": [],
            "unfed_experiments": [],
        },
        "target_venue": "IPM",
        "venue_figure_grammar": {"style_profile": "stem_conference"},
        "figure_modules": {"results": "figure_suite_render"},
    }
    payload.update(extra)
    return payload


def _gate(db, topic_id, stage="write"):
    return [v for v in InvariantChecker(db).check_figure_contract_gate(topic_id, stage)]


def test_gate_on_by_default(db, monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", raising=False)
    topic_id = _seed_topic(db)
    _add_artifact(db, topic_id, "experiment_result", {"rows": [{"dataset": "D"}]})
    violations = _gate(db, topic_id)
    assert len(violations) == 1
    assert "no figure_suite_plan" in violations[0].message


def test_gate_off_when_disabled(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "0")
    topic_id = _seed_topic(db)
    _add_artifact(db, topic_id, "experiment_result", {"rows": [{"dataset": "D"}]})
    assert _gate(db, topic_id) == []


def test_gate_on_blocks_missing_plan(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "1")
    topic_id = _seed_topic(db)
    _add_artifact(db, topic_id, "experiment_result", {"rows": [{"dataset": "D"}]})
    violations = _gate(db, topic_id)
    assert len(violations) == 1
    assert violations[0].check == "figure_contract_gate"
    assert violations[0].severity == "high"
    assert "no figure_suite_plan" in violations[0].message


def test_gate_on_blocks_coverage_gaps(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "1")
    topic_id = _seed_topic(db)
    _add_artifact(db, topic_id, "experiment_result", {"rows": [{"dataset": "D"}]})
    _add_artifact(
        db,
        topic_id,
        "figure_suite_plan",
        _complete_plan(
            matrix_coverage={
                "verdict": "gaps_found",
                "unfeedable_panels": [{"panel": "fig:x/a"}],
                "unfed_experiments": ["ablation"],
            }
        ),
    )
    violations = _gate(db, topic_id)
    assert len(violations) == 1
    assert "coverage gaps" in violations[0].message
    assert violations[0].metadata["unfed_experiments"] == 1


def test_gate_on_blocks_missing_predraw_fields(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "1")
    topic_id = _seed_topic(db)
    _add_artifact(db, topic_id, "experiment_result", {"rows": [{"dataset": "D"}]})
    _add_artifact(
        db,
        topic_id,
        "figure_suite_plan",
        {
            "matrix_coverage": {
                "verdict": "complete",
                "unfeedable_panels": [],
                "unfed_experiments": [],
            }
        },
    )
    violations = _gate(db, topic_id)
    assert len(violations) == 1
    assert "pre-draw fields" in violations[0].message


def test_gate_on_passes_complete_plan(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "1")
    topic_id = _seed_topic(db)
    _add_artifact(db, topic_id, "experiment_result", {"rows": [{"dataset": "D"}]})
    _add_artifact(db, topic_id, "figure_suite_plan", _complete_plan())
    assert _gate(db, topic_id) == []


def test_gate_on_ignores_topic_without_experiment_basis(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "1")
    topic_id = _seed_topic(db)
    # no experiment_result / goal_pool → survey/position paper, not gated
    assert _gate(db, topic_id) == []


def test_gate_only_at_write_gate_stages(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "1")
    topic_id = _seed_topic(db)
    _add_artifact(db, topic_id, "experiment_result", {"rows": [{"dataset": "D"}]})
    assert _gate(db, topic_id, stage="analyze") == []
    assert len(_gate(db, topic_id, stage="write")) == 1


def test_gate_registered_in_check_all(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "1")
    topic_id = _seed_topic(db)
    _add_artifact(db, topic_id, "experiment_result", {"rows": [{"dataset": "D"}]})
    all_checks = {v.check for v in InvariantChecker(db).check_all(topic_id, "write")}
    assert "figure_contract_gate" in all_checks


def test_gate_blocks_unrouted_includegraphics(db, tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "1")
    topic_id = _seed_topic(db)
    tex = tmp_path / "main.tex"
    tex.write_text(r"\includegraphics{claude_drew.png}")
    _add_artifact(db, topic_id, "final_bundle", {"files": {"tex": str(tex)}})
    violations = _gate(db, topic_id)
    assert len(violations) == 1
    assert "includegraphics" in violations[0].message
    assert "claude_drew.png" in violations[0].message


def test_gate_passes_routed_includegraphics(db, tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_CONTRACT_GATE", "1")
    topic_id = _seed_topic(db)
    tex = tmp_path / "main.tex"
    tex.write_text(r"\includegraphics{figures/experiment_main.png}")
    _add_artifact(db, topic_id, "final_bundle", {"files": {"tex": str(tex)}})
    _add_artifact(
        db,
        topic_id,
        "figure_suite_render",
        {"figures": [{"paths": {"png": "/tmp/experiment_main.png"}}]},
    )
    assert _gate(db, topic_id) == []
