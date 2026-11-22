"""Paper-production defaults: the `main` writing mode and its strict evidence
boundary, the public entry's paper_mode contract, and the EAG auto-plan trigger.
The fail-closed dream firewall is covered in test_dream_firewall.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from research_harness.auto_runner.tool_dispatch import (
    _maybe_auto_exemplar_intro_plan,
)
from research_harness.orchestrator.service import OrchestratorService


def _create_topic(db, name: str, venue: str = "") -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            (name, "dream default execution tests", venue),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# EAG auto-plan at the write stage
# ---------------------------------------------------------------------------


def _fake_exemplar_stack(monkeypatch, *, units: list[Any] | None):
    calls: dict[str, int] = {"curate": 0, "retrieve": 0, "plan": 0}

    def fake_curate(**kwargs):
        calls["curate"] += 1
        return SimpleNamespace(unit_type="intro_arc", units=units or [])

    def fake_retrieve(**kwargs):
        calls["retrieve"] += 1
        return SimpleNamespace(unit_type="intro_arc", ranked=units or [])

    def fake_plan(**kwargs):
        calls["plan"] += 1
        return SimpleNamespace(
            unit_type="intro_arc",
            plan={
                "moves": [
                    {"move": "context", "instruction": "open with the domain"},
                    {"move": "gap", "instruction": "state the gap"},
                ]
            },
            exemplar_ids=[1, 2],
            form_only=True,
        )

    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_curate", fake_curate
    )
    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_retrieve",
        fake_retrieve,
    )
    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_plan", fake_plan
    )
    return calls


def test_eag_auto_plan_records_intro_arc_once(db, monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_EAG_AUTOPLAN", raising=False)
    units = [SimpleNamespace(source_paper_id=1), SimpleNamespace(source_paper_id=2)]
    calls = _fake_exemplar_stack(monkeypatch, units=units)
    topic_id = _create_topic(db, "eag-auto-plan-topic")
    svc = OrchestratorService(db)
    results: list[Any] = []

    _maybe_auto_exemplar_intro_plan(
        db=db,
        svc=svc,
        topic_id=topic_id,
        context={"title": "EventGraph"},
        results=results,
    )
    plan = svc.get_latest_artifact(topic_id, "write", "exemplar_plan_intro_arc")
    assert plan is not None
    assert plan.payload["plan"]["moves"]
    assert plan.payload["origin"] == "eag_auto_plan"
    assert [r.tool for r in results] == ["exemplar_auto_plan"]

    # Idempotent: an existing plan short-circuits before any primitive call.
    _maybe_auto_exemplar_intro_plan(
        db=db,
        svc=svc,
        topic_id=topic_id,
        context={},
        results=results,
    )
    assert calls["curate"] == 1
    assert (
        plan.version
        == svc.get_latest_artifact(topic_id, "write", "exemplar_plan_intro_arc").version
    )


def test_eag_auto_plan_graceful_with_empty_pool(db, monkeypatch):
    monkeypatch.delenv("RESEARCH_HARNESS_EAG_AUTOPLAN", raising=False)
    _fake_exemplar_stack(monkeypatch, units=[])
    topic_id = _create_topic(db, "eag-empty-pool-topic")
    svc = OrchestratorService(db)
    results: list[Any] = []

    _maybe_auto_exemplar_intro_plan(
        db=db,
        svc=svc,
        topic_id=topic_id,
        context={},
        results=results,
    )
    assert svc.get_latest_artifact(topic_id, "write", "exemplar_plan_intro_arc") is None
    assert results == []


def test_eag_auto_plan_kill_switch(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_AUTOPLAN", "0")

    def exploding_curate(**kwargs):
        raise AssertionError("curate must not run when the kill switch is set")

    monkeypatch.setattr(
        "research_harness.primitives.exemplar_impls.exemplar_curate",
        exploding_curate,
    )
    topic_id = _create_topic(db, "eag-kill-switch-topic")
    svc = OrchestratorService(db)

    _maybe_auto_exemplar_intro_plan(
        db=db,
        svc=svc,
        topic_id=topic_id,
        context={},
        results=[],
    )
    assert svc.get_latest_artifact(topic_id, "write", "exemplar_plan_intro_arc") is None


def test_main_paper_mode_keeps_the_strict_evidence_boundary(tmp_path):
    import json

    from research_harness.auto_runner import hitl_commands
    from research_harness.storage.db import Database

    db = Database(str(tmp_path / "pool.db"))
    db.migrate()
    topic_id = _create_topic(db, "underwater main mode probe")

    hitl_commands.paper_production_start(
        db,
        topic_id=topic_id,
        target_venue="IEEE Transactions on Vehicular Technology",
        interaction_mode="autonomous",
        paper_mode="main",
        base_dir=tmp_path / "state",
    )
    checkpoints = list((tmp_path / "state").rglob(f"topic_{topic_id}.json"))
    policy = json.loads(checkpoints[0].read_text())["paper_production_run_policy"]
    assert policy["paper_mode"] == "main"
    assert policy["writing_mode"] == "main"
    assert policy["evidence_boundary"] == "strict_evidence_pool"


def test_public_entry_offers_main_paper_mode_only(tmp_path):
    """The public paper-production entry refuses dream mode and writes no checkpoint."""
    from research_harness.auto_runner import hitl_commands
    from research_harness.storage.db import Database

    db = Database(str(tmp_path / "pool.db"))
    db.migrate()
    topic_id = _create_topic(db, "underwater dream refusal probe")

    result = hitl_commands.paper_production_start(
        db,
        topic_id=topic_id,
        target_venue="IEEE Transactions on Vehicular Technology",
        interaction_mode="autonomous",
        paper_mode="dream",
        base_dir=tmp_path / "state",
    )
    assert result["status"] == "error"
    assert "expected 'main'" in result["summary"]
    assert not list((tmp_path / "state").rglob(f"topic_{topic_id}.json"))
