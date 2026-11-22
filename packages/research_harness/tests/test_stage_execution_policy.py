"""Tests for v2 Step 3.1 — pre-execution planner and stage budget wiring.

Covers:
- should_execute() returns should_run=True when stage hasn't run yet
- should_execute() returns skip for fresh_artifact_present
- should_execute() returns skip for resumed_past_stage
- check_stage_budget() respects DEFAULT_STAGE_BUDGETS without DB config
- check_stage_budget() picks up stage_budgets rows when present
"""

from __future__ import annotations

import pytest

from research_harness.auto_runner.stage_policy import (
    ExecutionDecision,
    _STAGE_REQUIRED_ARTIFACTS,
    get_policy,
    should_execute,
    should_pause_human,
)
from research_harness.orchestrator.stages import STAGE_REGISTRY
from research_harness.storage.db import Database
from research_harness.token_accounting import (
    DEFAULT_STAGE_BUDGETS,
    check_stage_budget,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.migrate()
    # Point the token_accounting module-level DB to this test DB.
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    return db


@pytest.fixture
def topic_id(db):
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("test-topic", "Test topic"),
        )
        tid = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (?, ?, ?, ?)",
            (tid, tid, "stub", "stub"),
        )
        conn.commit()
        return tid
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# should_execute
# ---------------------------------------------------------------------------


def test_should_execute_runs_when_stage_fresh(db, topic_id):
    """No artifacts yet -> should run."""
    decision = should_execute(db=db, topic_id=topic_id, stage="analyze")
    assert isinstance(decision, ExecutionDecision)
    assert decision.should_run is True
    assert decision.reason == "run"


def test_should_execute_skips_when_required_artifacts_fresh(db, topic_id):
    """init stage requires topic_brief; if present and non-stale, skip."""
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO project_artifacts
              (topic_id, stage, artifact_type, title, payload_json, status, stale)
            VALUES (?, 'init', 'topic_brief', 'Test', '{"scope":"x"}', 'active', 0)
            """,
            (topic_id,),
        )
        conn.commit()
    finally:
        conn.close()

    decision = should_execute(db=db, topic_id=topic_id, stage="init")
    assert decision.should_run is False
    assert decision.reason == "fresh_artifact_present"


def test_stage_required_artifacts_match_orchestrator_contract():
    """Pre-execution skip checks must use the same contract as gates."""
    expected = {
        stage: tuple(meta.required_artifacts)
        for stage, meta in STAGE_REGISTRY.items()
        if meta.required_artifacts
    }
    assert _STAGE_REQUIRED_ARTIFACTS == expected


def test_write_should_execute_until_final_outputs_exist(db, topic_id):
    """Write skip policy follows the orchestrator write gate contract."""
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO project_artifacts
              (topic_id, stage, artifact_type, title, payload_json, status, stale)
            VALUES (?, 'write', 'draft_pack', 'Draft', '{"sections":{"intro":"x"}}', 'active', 0)
            """,
            (topic_id,),
        )
        conn.commit()
    finally:
        conn.close()

    decision = should_execute(db=db, topic_id=topic_id, stage="write")
    assert decision.should_run is True
    assert decision.reason == "run"

    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO project_artifacts
              (topic_id, stage, artifact_type, title, payload_json, status, stale)
            VALUES (?, 'write', 'final_bundle', 'Final Bundle',
                    '{"compiled_pdf_path":"/tmp/paper.pdf"}', 'active', 0)
            """,
            (topic_id,),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
              (topic_id, stage, artifact_type, title, payload_json, status, stale)
            VALUES (?, 'write', 'process_summary', 'Process Summary',
                    '{"summary":"complete"}', 'active', 0)
            """,
            (topic_id,),
        )
        conn.commit()
    finally:
        conn.close()

    decision = should_execute(db=db, topic_id=topic_id, stage="write")
    assert decision.should_run is False
    assert decision.reason == "fresh_artifact_present"


def test_write_policy_includes_publication_closure_tools():
    policy = get_policy("write")

    assert policy is not None
    assert "figure_suite_plan" in policy.tools
    assert "figure_suite_render" in policy.tools
    assert policy.tools.index("figure_suite_plan") < policy.tools.index("figure_plan")
    assert policy.tools.index("figure_plan") < policy.tools.index("figure_suite_render")
    assert policy.tools.index("figure_suite_render") < policy.tools.index(
        "figure_generate"
    )
    assert "latex_compile" in policy.tools
    assert "publication_pack_backfill" in policy.tools
    assert "publication_run" in policy.tools
    assert policy.tools.index("publication_pack_backfill") > policy.tools.index(
        "latex_compile"
    )
    assert policy.tools.index("publication_run") > policy.tools.index(
        "publication_pack_backfill"
    )


def test_should_execute_skips_when_gate_already_passed(db, topic_id, monkeypatch):
    """GateEvaluator.evaluate returns a string decision; pass should skip."""

    class PassingGateEvaluator:
        def __init__(self, db):
            self.db = db

        def evaluate(self, topic_id, stage):
            return "pass"

    monkeypatch.setattr(
        "research_harness.orchestrator.transitions.GateEvaluator",
        PassingGateEvaluator,
    )

    decision = should_execute(db=db, topic_id=topic_id, stage="analyze")

    assert decision.should_run is False
    assert decision.reason == "gate_already_passed"


def test_should_execute_does_not_skip_when_artifact_stale(db, topic_id):
    """Stale artifact means the stage needs re-execution."""
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO project_artifacts
              (topic_id, stage, artifact_type, title, payload_json, status, stale, stale_reason)
            VALUES (?, 'init', 'topic_brief', 'Test', '{"scope":"x"}', 'active', 1, 'test')
            """,
            (topic_id,),
        )
        conn.commit()
    finally:
        conn.close()

    decision = should_execute(db=db, topic_id=topic_id, stage="init")
    assert decision.should_run is True


def test_should_execute_resumed_past_stage(db, topic_id):
    """If checkpoint is already at a later stage, skip earlier ones."""
    decision = should_execute(
        db=db,
        topic_id=topic_id,
        stage="init",
        current_checkpoint_stage="analyze",
    )
    assert decision.should_run is False
    assert decision.reason == "resumed_past_stage"


def test_should_execute_unknown_stage_defaults_to_run(db, topic_id):
    """Unknown stage names pass through as run."""
    decision = should_execute(db=db, topic_id=topic_id, stage="nonexistent")
    assert decision.should_run is True


def test_high_risk_human_required_stage_pauses_even_in_autonomous_mode():
    assert should_pause_human("propose", mode="autonomous", autonomy="autonomous")
    assert should_pause_human("write", mode="autonomous", autonomy="autonomous")


# ---------------------------------------------------------------------------
# check_stage_budget
# ---------------------------------------------------------------------------


def test_check_stage_budget_default_budgets_no_spend(db, topic_id):
    """No spend recorded -> ok with no warning."""
    # migration 049 creates stage_budgets; budget lookup misses, defaults apply
    result = check_stage_budget(topic_id=topic_id, stage="gap_detect")
    assert result.ok is True
    assert result.warning is None
    soft, hard = DEFAULT_STAGE_BUDGETS["gap_detect"]
    assert result.soft_warn_tokens == soft
    assert result.hard_cap_tokens == hard


def test_check_stage_budget_unknown_stage(db, topic_id):
    """Stage with no default and no DB row -> ok, untracked."""
    result = check_stage_budget(topic_id=topic_id, stage="totally_unknown")
    assert result.ok is True
    assert result.warning is None


def test_check_stage_budget_db_override(db, topic_id):
    """stage_budgets row overrides the defaults."""
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO stage_budgets (stage, topic_id, soft_warn_tokens, hard_cap_tokens)
            VALUES (?, ?, ?, ?)
            """,
            ("gap_detect", topic_id, 100, 200),
        )
        conn.commit()
    finally:
        conn.close()

    result = check_stage_budget(topic_id=topic_id, stage="gap_detect")
    assert result.soft_warn_tokens == 100
    assert result.hard_cap_tokens == 200


# ---------------------------------------------------------------------------
# demo-scoped artifacts must not satisfy freshness for non-demo runs
# ---------------------------------------------------------------------------


def _insert_run(db, topic_id, mode):
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO orchestrator_runs "
            "(project_id, topic_id, mode, current_stage, stage_status, gate_status) "
            "VALUES (?, ?, ?, 'write', 'in_progress', 'not_evaluated')",
            (topic_id, topic_id, mode),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_demo_write_artifacts(db, topic_id):
    """Insert write-stage artifacts stamped with demo smoke markers."""
    demo_payload = (
        '{"readiness_scope": "demo_pdf_smoke", '
        '"evidence_boundary": "demo_limited_seed_pool"}'
    )
    conn = db.connect()
    try:
        for art_type in _STAGE_REQUIRED_ARTIFACTS.get("write", ()):
            conn.execute(
                """
                INSERT INTO project_artifacts
                  (topic_id, stage, artifact_type, title, payload_json,
                   status, stale)
                VALUES (?, 'write', ?, 'Demo', ?, 'active', 0)
                """,
                (topic_id, art_type, demo_payload),
            )
        conn.commit()
    finally:
        conn.close()


def test_demo_artifacts_do_not_skip_write_for_strict_run(db, topic_id):
    """The EchoFormer leak: a strict rerun skipped the write stage because
    the demo smoke final_bundle counted as fresh."""
    _insert_run(db, topic_id, "strict")
    _insert_demo_write_artifacts(db, topic_id)

    decision = should_execute(db=db, topic_id=topic_id, stage="write")

    assert decision.should_run is True
    assert any("demo-scoped" in note for note in decision.advisory_notes)


def test_demo_artifacts_still_skip_write_for_demo_run(db, topic_id):
    _insert_run(db, topic_id, "demo")
    _insert_demo_write_artifacts(db, topic_id)

    decision = should_execute(db=db, topic_id=topic_id, stage="write")

    assert decision.should_run is False
    assert decision.reason == "fresh_artifact_present"


def test_skip_withdrawal_is_recorded_once_per_stage():
    """A gate refusal after a freshness skip must let the stage re-run once.

    Freshness tracks `required_artifacts`; a gate may demand more (the analyze
    gate wants baseline governance, which is not in that tuple). Trusting the
    skip when the gate refuses stranded runs in a state that could neither
    regenerate the missing artifact nor advance.
    """
    from research_harness.auto_runner.runner import (
        _mark_skip_withdrawn,
        _skip_withdrawn,
    )

    checkpoint: dict = {}
    assert _skip_withdrawn(checkpoint, "analyze") is False

    _mark_skip_withdrawn(checkpoint, "analyze")
    assert _skip_withdrawn(checkpoint, "analyze") is True
    # Other stages are unaffected; the retry budget is per stage.
    assert _skip_withdrawn(checkpoint, "write") is False

    # Marking twice must not grant a second retry.
    _mark_skip_withdrawn(checkpoint, "analyze")
    assert checkpoint["pre_execute_skip_withdrawn_stages"] == ["analyze"]
