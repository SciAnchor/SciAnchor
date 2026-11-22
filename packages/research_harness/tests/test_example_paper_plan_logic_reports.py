"""Guard the sanitized example PAPER_PLAN against logic-gate contract drift.

``fixtures/writing/example_paper_plan_with_logic_reports.json`` documents a
complete, passing PAPER_PLAN: the raw manuscript-logic bundle inputs, the
flattened fine-logic-audit fields, and the two recorded reports. These tests
prove the example still satisfies the runtime guard and that its embedded
reports match what the real evaluators produce, so the example can be trusted as
the contract reference.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_harness._selfdev.manuscript_logic_gate import (
    FINE_LOGIC_AUDIT_SCHEMA_VERSION,
    evaluate_fine_logic_audit,
    evaluate_manuscript_logic_bundle,
)
from research_harness._selfdev.writing_logic_gate_runtime import (
    _FINE_AUDIT_FIELDS,
    _MANUSCRIPT_BUNDLE_FIELDS,
    MANUSCRIPT_LOGIC_BUNDLE_SCHEMA_VERSION,
    section_draft_logic_gate_block,
)

_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "writing"
    / "example_paper_plan_with_logic_reports.json"
)


def _load_plan() -> dict:
    return json.loads(_FIXTURE.read_text())


def test_example_plan_carries_both_recorded_reports() -> None:
    plan = _load_plan()
    assert plan["manuscript_logic_gate_report"]["status"] == "pass"
    assert plan["fine_logic_audit_report"]["status"] == "pass"
    assert (
        plan["fine_logic_audit_report"]["schema_version"]
        == "rh.manuscript.fine_logic_audit_report.v1"
    )


def test_example_plan_clears_runtime_gate_for_every_section() -> None:
    """The example must satisfy the gate for body sections too, via the
    authoritative recompute path (it ships raw bundle inputs)."""
    plan = _load_plan()
    for section in ("abstract", "introduction", "method", "results", "discussion"):
        assert (
            section_draft_logic_gate_block(
                db=None, section=section, topic_id=1, paper_plan=plan
            )
            is None
        ), section


def test_example_plan_embedded_reports_match_real_evaluators() -> None:
    """Regenerating the reports from the example's raw inputs must reproduce the
    embedded reports exactly — guards against the fixture drifting from the gate."""
    plan = _load_plan()

    bundle = {
        "schema_version": MANUSCRIPT_LOGIC_BUNDLE_SCHEMA_VERSION,
        "fine_logic_audit": {
            "schema_version": FINE_LOGIC_AUDIT_SCHEMA_VERSION,
            **{field: plan.get(field) for field in _FINE_AUDIT_FIELDS},
        },
        **{field: plan[field] for field in _MANUSCRIPT_BUNDLE_FIELDS},
    }

    bundle_report = evaluate_manuscript_logic_bundle(bundle)
    assert bundle_report.to_dict() == plan["manuscript_logic_gate_report"]

    fine_report = evaluate_fine_logic_audit(bundle["fine_logic_audit"])
    assert fine_report.to_dict() == plan["fine_logic_audit_report"]
