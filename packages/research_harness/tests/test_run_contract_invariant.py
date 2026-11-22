"""run_contract: user run requirements as a first-class, honest artifact.

Repeatedly-stated user instructions (figures in prose / illustration route /
strict EAG) previously lived only in conversation and evaporated at every
stage boundary. A run_contract entry is {key, requirement, enforcement};
the invariant keeps the enforcement boundary honest.
"""

from __future__ import annotations

import pytest

from research_harness._workflow.orchestrator.artifacts import (
    ArtifactManager,
    NON_REGENERABLE_ARTIFACT_TYPES,
    is_regenerable,
)
from research_harness._workflow.orchestrator.invariants import InvariantChecker
from research_harness.storage.db import Database


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        conn.commit()
    return db


def _record_contract(db, entries):
    return ArtifactManager(db).record(
        topic_id=1,
        stage="write",
        artifact_type="run_contract",
        title="Run contract",
        payload={"entries": entries},
    )


def test_valid_contract_passes(db):
    _record_contract(
        db,
        [
            {
                "key": "figures_referenced_in_text",
                "requirement": "every figure cited from the prose",
                "enforcement": "gate",
            },
            {
                "key": "strict_eag",
                "requirement": "all 8 EAG units, locked exemplar",
                "enforcement": "advisory",
            },
        ],
    )
    assert InvariantChecker(db).check_run_contract(1, "write") == []


def test_gate_enforcement_without_backing_gate_is_flagged(db):
    _record_contract(
        db,
        [
            {
                "key": "strict_eag",
                "requirement": "all 8 EAG units",
                "enforcement": "gate",  # no such gate exists yet
            }
        ],
    )
    violations = InvariantChecker(db).check_run_contract(1, "write")
    assert [v.check for v in violations] == ["run_contract_unenforceable_gate"]


def test_unknown_enforcement_level_is_flagged(db):
    _record_contract(db, [{"key": "x", "requirement": "y", "enforcement": "mandatory"}])
    violations = InvariantChecker(db).check_run_contract(1, "write")
    assert [v.check for v in violations] == ["run_contract_schema"]


def test_empty_contract_is_flagged(db):
    _record_contract(db, [])
    violations = InvariantChecker(db).check_run_contract(1, "write")
    assert [v.check for v in violations] == ["run_contract_schema"]


def test_no_contract_is_fine(db):
    assert InvariantChecker(db).check_run_contract(1, "write") == []


def test_review_artifacts_default_to_non_regenerable(db):
    assert not is_regenerable("adversarial_round")
    assert not is_regenerable("final_bundle_quality_report")
    assert is_regenerable("final_bundle")  # rebuildable from tex+data
    assert "adversarial_resolution" in NON_REGENERABLE_ARTIFACT_TYPES

    artifact = ArtifactManager(db).record(
        topic_id=1,
        stage="write",
        artifact_type="adversarial_round",
        title="Round 1",
        payload={"round_number": 1},
    )
    assert artifact.metadata["regenerable"] is False

    bundle = ArtifactManager(db).record(
        topic_id=1,
        stage="write",
        artifact_type="final_bundle",
        title="Bundle",
        payload={},
    )
    assert bundle.metadata["regenerable"] is True
