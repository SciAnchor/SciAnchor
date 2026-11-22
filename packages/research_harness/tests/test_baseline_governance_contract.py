from __future__ import annotations

import json

from research_harness.orchestrator import OrchestratorService
from research_harness.orchestrator.invariants import InvariantChecker, is_blocking


def _insert_topic(db) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("baseline-governance-topic", "Baseline governance invariant test"),
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (?, ?, ?, ?)",
            (topic_id, topic_id, "baseline-governance-topic", "stub"),
        )
        conn.commit()
        return topic_id
    finally:
        conn.close()


def _set_stage(db, topic_id: int, stage: str) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE orchestrator_runs SET current_stage = ? WHERE topic_id = ?",
            (stage, topic_id),
        )
        conn.commit()
    finally:
        conn.close()


def _setup_analyze_topic(db) -> tuple[OrchestratorService, int]:
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)
    _set_stage(db, topic_id, "analyze")
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="claim_candidate_set",
        payload={"claims": [{"claim_id": "c1"}]},
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="gap_detect",
        payload={"gaps": [{"id": i, "severity": "high"} for i in range(5)]},
    )
    return svc, topic_id


def _record_baseline_matrix(
    svc: OrchestratorService,
    topic_id: int,
    payload: dict,
) -> int:
    artifact = svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="baseline_matrix",
        title="Baseline Matrix",
        payload=payload,
    )
    return int(artifact.id)


def test_novelty_claim_without_baseline_matrix_blocks_analyze_gate(db) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={
            "research_question": "Can a novel agent workflow improve review quality?",
            "novelty_statement": "This is a novel workflow for scientific review.",
        },
    )

    violations = InvariantChecker(db).check_baseline_governance(topic_id, "analyze")

    assert len(violations) == 1
    assert violations[0].check == "baseline_governance_missing"
    assert violations[0].severity == "high"
    assert is_blocking(violations[0])
    assert svc.check_gate(topic_id, stage="analyze") == "fail"


def test_direction_proposal_without_baseline_matrix_blocks_analyze_gate(db) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={
            "research_question": "Which boundary separates these baseline clusters?",
        },
    )

    violations = InvariantChecker(db).check_baseline_governance(topic_id, "analyze")

    assert len(violations) == 1
    assert violations[0].check == "baseline_governance_missing"
    assert violations[0].severity == "high"
    assert violations[0].metadata["direction_proposal_artifact_id"]
    assert svc.check_gate(topic_id, stage="analyze") == "fail"


def test_baseline_identify_without_matrix_does_not_satisfy_governance_gate(
    db,
) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={"research_question": "Which baseline boundary is valid?"},
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="baseline_identify",
        payload={"baselines": [{"baseline_id": "thin-baseline"}]},
    )

    violations = InvariantChecker(db).check_baseline_governance(topic_id, "analyze")

    assert len(violations) == 1
    assert violations[0].check == "baseline_governance_missing"
    assert svc.check_gate(topic_id, stage="analyze") == "fail"


def test_false_novelty_claim_blocks_with_replayable_gate_governance(db) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={
            "research_question": "Can a novel agent workflow improve review quality?",
            "novelty_statement": "This is a novel workflow for scientific review.",
        },
    )
    _record_baseline_matrix(
        svc,
        topic_id,
        {
            "baselines": [
                {
                    "baseline_id": "prior-agent-review",
                    "name": "Prior Agent Review",
                    "method_family": "agent_review_workflow",
                    "source_paper_ids": [1],
                    "relationship_to_proposal": "close_prior",
                }
            ],
            "coverage": {
                "required_families": ["agent_review_workflow"],
                "covered_families": ["agent_review_workflow"],
            },
            "novelty_decision": {
                "verdict": "too_similar",
                "close_prior_baseline_ids": ["prior-agent-review"],
            },
        },
    )

    assert svc.check_gate(topic_id, stage="analyze") == "fail"

    conn = db.connect()
    try:
        issue_rows = conn.execute(
            """
            SELECT review_type, category, severity, blocking, affected_object_type
            FROM review_issues
            WHERE topic_id = ?
            """,
            (topic_id,),
        ).fetchall()
        gate_rows = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type = 'gate_decision'
              AND status = 'active'
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    assert len(issue_rows) == 1
    assert issue_rows[0]["review_type"] == "gate_invariant"
    assert issue_rows[0]["category"] == "false_novelty_claim"
    assert issue_rows[0]["severity"] == "high"
    assert issue_rows[0]["blocking"] == 1
    assert issue_rows[0]["affected_object_type"] == "project_artifact"

    assert len(gate_rows) == 1
    payload = json.loads(gate_rows[0]["payload_json"])
    assert payload["object_type"] == "gate_decision"
    assert payload["reason_codes"] == ["false_novelty_claim"]
    assert payload["violations"][0]["metadata"]["close_prior_baseline_ids"] == [
        "prior-agent-review"
    ]

    assert svc.check_gate(topic_id, stage="analyze") == "fail"
    conn = db.connect()
    try:
        issue_count = conn.execute(
            "SELECT COUNT(*) AS count FROM review_issues WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()["count"]
        active_gate_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type = 'gate_decision'
              AND status = 'active'
            """,
            (topic_id,),
        ).fetchone()["count"]
    finally:
        conn.close()

    assert issue_count == 1
    assert active_gate_count == 1


def test_baseline_family_coverage_incomplete_blocks_analyze_gate(db) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={"research_question": "Which method family should be tested?"},
    )
    _record_baseline_matrix(
        svc,
        topic_id,
        {
            "baselines": [
                {
                    "baseline_id": "retrieval-only",
                    "method_family": "retrieval",
                    "source_paper_ids": [1],
                }
            ],
            "coverage": {
                "required_families": ["retrieval", "agent_review_workflow"],
                "covered_families": ["retrieval"],
            },
        },
    )

    violations = InvariantChecker(db).check_baseline_governance(topic_id, "analyze")

    assert len(violations) == 1
    assert violations[0].check == "baseline_coverage_incomplete"
    assert violations[0].metadata["missing_families"] == ["agent_review_workflow"]
    assert svc.check_gate(topic_id, stage="analyze") == "fail"


def test_survey_facet_coverage_incomplete_blocks_analyze_gate(db) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={"research_question": "Which survey facets are not covered?"},
    )
    _record_baseline_matrix(
        svc,
        topic_id,
        {
            "baselines": [
                {
                    "baseline_id": "benchmark-survey",
                    "method_family": "survey",
                    "facets": ["benchmark_coverage"],
                    "source_paper_ids": [1],
                }
            ],
            "coverage": {
                "required_families": ["survey"],
                "covered_families": ["survey"],
                "required_facets": ["benchmark_coverage", "human_eval"],
                "covered_facets": ["benchmark_coverage"],
            },
        },
    )

    violations = InvariantChecker(db).check_baseline_governance(topic_id, "analyze")

    assert len(violations) == 1
    assert violations[0].check == "baseline_coverage_incomplete"
    assert violations[0].metadata["missing_facets"] == ["human_eval"]
    assert svc.check_gate(topic_id, stage="analyze") == "fail"


def test_baseline_governance_accepts_supported_incremental_direction(db) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={
            "research_question": "Can we extend agent review workflows?",
            "novelty_statement": "This is an incremental extension of prior work.",
        },
    )
    _record_baseline_matrix(
        svc,
        topic_id,
        {
            "baselines": [
                {
                    "baseline_id": "prior-agent-review",
                    "method_family": "agent_review_workflow",
                    "source_paper_ids": [1],
                    "relationship_to_proposal": "close_prior",
                }
            ],
            "coverage": {
                "required_families": ["agent_review_workflow"],
                "covered_families": ["agent_review_workflow"],
            },
            "novelty_decision": {
                "verdict": "incremental",
                "close_prior_baseline_ids": ["prior-agent-review"],
            },
        },
    )

    assert InvariantChecker(db).check_baseline_governance(topic_id, "analyze") == []
    assert svc.check_gate(topic_id, stage="analyze") == "pass"


def test_baseline_governance_prefers_canonical_baseline_matrix(db) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={"research_question": "Which baseline cluster is valid?"},
    )
    _record_baseline_matrix(
        svc,
        topic_id,
        {
            "baselines": [
                {
                    "baseline_id": "valid-matrix",
                    "method_family": "agent_review_workflow",
                    "source_paper_ids": [1],
                }
            ],
            "coverage": {
                "required_families": ["agent_review_workflow"],
                "covered_families": ["agent_review_workflow"],
            },
        },
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="baseline_identify",
        payload={
            "baselines": [],
            "coverage": {
                "required_families": ["agent_review_workflow"],
                "covered_families": [],
            },
        },
    )

    assert InvariantChecker(db).check_baseline_governance(topic_id, "analyze") == []
    assert svc.check_gate(topic_id, stage="analyze") == "pass"


def test_new_direction_proposal_cannot_reuse_unlinked_older_baseline_matrix(
    db,
) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    _record_baseline_matrix(
        svc,
        topic_id,
        {
            "baselines": [
                {
                    "baseline_id": "old-baseline",
                    "method_family": "agent_review_workflow",
                    "source_paper_ids": [1],
                }
            ],
            "coverage": {
                "required_families": ["agent_review_workflow"],
                "covered_families": ["agent_review_workflow"],
            },
        },
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={"research_question": "A newly changed research question?"},
    )

    violations = InvariantChecker(db).check_baseline_governance(topic_id, "analyze")

    assert len(violations) == 1
    assert violations[0].check == "baseline_governance_unlinked"
    assert svc.check_gate(topic_id, stage="analyze") == "fail"


def test_new_direction_proposal_can_reuse_traced_older_baseline_matrix(db) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    baseline_id = _record_baseline_matrix(
        svc,
        topic_id,
        {
            "baselines": [
                {
                    "baseline_id": "old-baseline",
                    "method_family": "agent_review_workflow",
                    "source_paper_ids": [1],
                }
            ],
            "coverage": {
                "required_families": ["agent_review_workflow"],
                "covered_families": ["agent_review_workflow"],
            },
        },
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={
            "research_question": "A changed but traceable research question?",
            "trace": {"source_artifact_ids": [baseline_id]},
        },
    )

    assert InvariantChecker(db).check_baseline_governance(topic_id, "analyze") == []
    assert svc.check_gate(topic_id, stage="analyze") == "pass"


def test_stale_baseline_matrix_blocks_propose_gate_and_emits_rollback_event(
    db,
) -> None:
    svc, topic_id = _setup_analyze_topic(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        payload={
            "research_question": "Can we extend agent review workflows?",
            "novelty_statement": "This is an incremental extension of prior work.",
        },
    )
    baseline_id = _record_baseline_matrix(
        svc,
        topic_id,
        {
            "baselines": [
                {
                    "baseline_id": "prior-agent-review",
                    "method_family": "agent_review_workflow",
                    "source_paper_ids": [1],
                }
            ],
            "coverage": {
                "required_families": ["agent_review_workflow"],
                "covered_families": ["agent_review_workflow"],
            },
        },
    )
    _set_stage(db, topic_id, "propose")

    svc.mark_artifact_stale(
        baseline_id,
        reason="paper pool changed after baseline governance",
        propagate=False,
    )

    violations = InvariantChecker(db).check_baseline_governance(topic_id, "propose")
    assert len(violations) == 1
    assert violations[0].check == "stale_baseline_governance"
    assert violations[0].artifact_id == baseline_id
    assert svc.check_gate(topic_id, stage="propose") == "fail"

    conn = db.connect()
    try:
        issue_rows = conn.execute(
            """
            SELECT id, category, blocking
            FROM review_issues
            WHERE topic_id = ?
              AND status = 'open'
            """,
            (topic_id,),
        ).fetchall()
        rollback_rows = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type = 'rollback_event'
              AND status = 'active'
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    assert len(issue_rows) == 1
    assert issue_rows[0]["category"] == "stale_baseline_governance"
    assert issue_rows[0]["blocking"] == 1
    assert len(rollback_rows) == 1
    payload = json.loads(rollback_rows[0]["payload_json"])
    assert payload["stage"] == "propose"
    assert payload["reason_codes"] == ["stale_baseline_governance"]
    assert payload["affected_artifact_ids"] == [baseline_id]
    assert payload["trigger_artifact_ids"] == [baseline_id]

    assert svc.check_gate(topic_id, stage="propose") == "fail"
    conn = db.connect()
    try:
        issue_count = conn.execute(
            "SELECT COUNT(*) AS count FROM review_issues WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()["count"]
        rollback_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type = 'rollback_event'
              AND status = 'active'
            """,
            (topic_id,),
        ).fetchone()["count"]
    finally:
        conn.close()

    assert issue_count == 1
    assert rollback_count == 1
