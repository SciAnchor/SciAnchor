"""S5: the figure_contract advisory rule (artifact-driven, advisory-only)."""

from __future__ import annotations

import json

from research_harness.advisory.rules import AdvisoryEngine


def _seed_topic(db) -> int:
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO topics (name, status) VALUES ('t', 'active')")
        topic_id = cur.lastrowid
        conn.commit()
        return topic_id
    finally:
        conn.close()


def _set_stage(db, topic_id: int, stage: str) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO projects (topic_id, name) VALUES (?, 'p')", (topic_id,)
        )
        project_id = conn.execute(
            "SELECT id FROM projects WHERE topic_id = ? ORDER BY id DESC LIMIT 1",
            (topic_id,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO orchestrator_runs (project_id, topic_id, current_stage) "
            "VALUES (?, ?, ?)",
            (project_id, topic_id, stage),
        )
        conn.commit()
    finally:
        conn.close()


def _add_artifact(
    db, topic_id: int, atype: str, payload: dict, stage: str = "experiment"
) -> None:
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


def _figure_advisories(db, topic_id):
    return [
        a for a in AdvisoryEngine(db).run(topic_id) if a.category == "figure_contract"
    ]


def test_no_advisory_before_experiment_stage(db):
    topic_id = _seed_topic(db)
    _set_stage(db, topic_id, "analyze")
    _add_artifact(db, topic_id, "experiment_result", {"rows": []})
    assert _figure_advisories(db, topic_id) == []


def test_no_advisory_without_results_or_goals(db):
    topic_id = _seed_topic(db)
    _set_stage(db, topic_id, "write")
    # no experiment_result, no goal_pool → nothing to plan figures from
    assert _figure_advisories(db, topic_id) == []


def test_advises_missing_plan_when_results_exist(db):
    topic_id = _seed_topic(db)
    _set_stage(db, topic_id, "write")
    _add_artifact(db, topic_id, "experiment_result", {"rows": [{"dataset": "D"}]})
    advs = _figure_advisories(db, topic_id)
    assert len(advs) == 1
    assert advs[0].level == "info"
    assert "no figure_suite_plan" in advs[0].message


def test_advises_coverage_gaps_when_plan_has_them(db):
    topic_id = _seed_topic(db)
    _set_stage(db, topic_id, "write")
    _add_artifact(db, topic_id, "experiment_result", {"rows": [{"dataset": "D"}]})
    _add_artifact(
        db,
        topic_id,
        "figure_suite_plan",
        {
            "matrix_coverage": {
                "verdict": "gaps_found",
                "unfeedable_panels": [
                    {"panel": "fig:main/b", "reason": "no_matching_records"}
                ],
                "unfed_experiments": ["ablation"],
            }
        },
        stage="write",
    )
    advs = _figure_advisories(db, topic_id)
    assert len(advs) == 1
    assert advs[0].level == "warning"
    assert "coverage gaps" in advs[0].message
    assert advs[0].details["unfed_experiments"] == ["ablation"]


def test_no_advisory_when_plan_is_complete(db):
    topic_id = _seed_topic(db)
    _set_stage(db, topic_id, "write")
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
        stage="write",
    )
    assert _figure_advisories(db, topic_id) == []
