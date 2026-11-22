"""Shared runtime guard for paper-scale section drafting.

The guard keeps manuscript-scale prose generation behind the deterministic
manuscript logic gate regardless of whether callers enter through the service
layer or the direct primitive backend.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from research_harness.orchestrator import OrchestratorService
from research_harness.storage.db import Database

from .manuscript_logic_gate import (
    MANUSCRIPT_LOGIC_BUNDLE_SCHEMA_VERSION,
    evaluate_manuscript_logic_bundle,
)


LOGGER = logging.getLogger(__name__)

# Raw bundle inputs the deterministic validator needs. When a PAPER_PLAN carries
# them, the gate RECOMPUTES the report instead of trusting a self-declared
# ``status`` field — so a hand-written ``{"status": "pass"}`` cannot bypass the
# manuscript logic gate. Report-only plans (no raw inputs) fall back to the
# recorded report.
_MANUSCRIPT_BUNDLE_FIELDS = (
    "core_claim_contract",
    "argument_tree",
    "term_registry",
    "promise_realization_matrix",
    "paragraph_intent_tree",
)
_FINE_AUDIT_FIELDS = (
    "argument_link_map",
    "assumption_warrant_table",
    "claim_certainty_audit",
    "paragraph_flow_audit",
    "intro_logic_map",
    "figure_table_message_audit",
    "writing_defect_log",
)

MANUSCRIPT_LOGIC_GATE_ERROR_CODE = "MANUSCRIPT_LOGIC_GATE_REQUIRED"
MANUSCRIPT_LOGIC_GATE_REPORT = "manuscript_logic_gate_report"
FINE_LOGIC_AUDIT_REPORT = "fine_logic_audit_report"

# The manuscript logic gate now applies to EVERY drafted section (previously it
# was limited to abstract / introduction / full-paper). Every major section must
# sit on a validated argument structure, so method, results, related_work,
# discussion, conclusion, etc. are all gated. Add a section name here only to
# deliberately exempt a non-manuscript drafting use; empty by default = gate all.
MANUSCRIPT_LOGIC_GATE_EXEMPT_SECTIONS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ManuscriptLogicGateBlock:
    section: Any
    topic_id: Any
    required_report: str
    gate_status: str
    blockers: tuple[str, ...]

    @property
    def message(self) -> str:
        return (
            f"section_draft {self.section} requires a passing "
            f"{self.required_report} in PAPER_PLAN before drafting"
        )

    @property
    def recovery_hint(self) -> str:
        if self.required_report == FINE_LOGIC_AUDIT_REPORT:
            return (
                "Run manuscript-logic-gate fine audit to produce ARGUMENT_LINK_MAP, "
                "ASSUMPTION_WARRANT_TABLE, CLAIM_CERTAINTY_AUDIT, "
                "PARAGRAPH_FLOW_AUDIT, INTRO_LOGIC_MAP, "
                "FIGURE_TABLE_MESSAGE_AUDIT, WRITING_DEFECT_LOG, and a passing "
                "fine_logic_audit_report."
            )
        return (
            "Run manuscript-logic-gate to produce CORE_CLAIM_CONTRACT, "
            "ARGUMENT_TREE, TERM_REGISTRY, PROMISE_REALIZATION_MATRIX, "
            "PARAGRAPH_INTENT_TREE, and a passing manuscript_logic_gate_report."
        )

    def output_payload(self) -> dict[str, Any]:
        return {
            "required_artifact": "PAPER_PLAN",
            "required_report": self.required_report,
            "section": self.section,
            "topic_id": self.topic_id,
            "gate_status": self.gate_status,
            "blockers": list(self.blockers),
        }

    def error_payload(self) -> dict[str, str]:
        return {
            "code": MANUSCRIPT_LOGIC_GATE_ERROR_CODE,
            "message": self.message,
        }

    def exception_message(self) -> str:
        return json.dumps(
            {
                "code": MANUSCRIPT_LOGIC_GATE_ERROR_CODE,
                "message": self.message,
                "required_artifact": "PAPER_PLAN",
                "required_report": self.required_report,
                "section": self.section,
                "topic_id": self.topic_id,
                "gate_status": self.gate_status,
                "blockers": list(self.blockers),
                "recovery_hint": self.recovery_hint,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


class ManuscriptLogicGateRequired(RuntimeError):
    """Raised when paper-scale drafting starts before the logic gate passes."""

    def __init__(self, block: ManuscriptLogicGateBlock) -> None:
        super().__init__(block.exception_message())
        self.block = block


def section_draft_logic_gate_block(
    *,
    db: Database | None,
    section: Any,
    topic_id: Any,
    paper_plan: Mapping[str, Any] | None = None,
) -> ManuscriptLogicGateBlock | None:
    """Return a block when manuscript-scale drafting lacks a passing plan."""

    normalized_section = str(section or "").strip().lower()
    if (
        not normalized_section
        or normalized_section in MANUSCRIPT_LOGIC_GATE_EXEMPT_SECTIONS
    ):
        return None

    resolved_plan = paper_plan if isinstance(paper_plan, Mapping) else None
    if resolved_plan is None:
        resolved_plan = _active_paper_plan(db, topic_id)

    # Authoritative path: when the plan supplies the raw logic-bundle inputs,
    # recompute the report deterministically so a self-declared "pass" cannot
    # bypass the gate. ``evaluate_manuscript_logic_bundle`` also folds in the
    # fine-logic audit, so a single recomputed status covers both reports.
    if _plan_carries_logic_bundle(resolved_plan):
        report = evaluate_manuscript_logic_bundle(
            _assemble_manuscript_bundle(resolved_plan)
        )
        if report.status != "pass":
            return ManuscriptLogicGateBlock(
                section=section,
                topic_id=topic_id,
                required_report=MANUSCRIPT_LOGIC_GATE_REPORT,
                gate_status=report.status,
                blockers=tuple(report.blockers),
            )
        return None

    report_map = _report_map(resolved_plan, MANUSCRIPT_LOGIC_GATE_REPORT)
    gate_status = str(report_map.get("status") or "missing")
    if gate_status != "pass":
        return ManuscriptLogicGateBlock(
            section=section,
            topic_id=topic_id,
            required_report=MANUSCRIPT_LOGIC_GATE_REPORT,
            gate_status=gate_status,
            blockers=_string_tuple(report_map.get("blockers")),
        )

    fine_report_map = _report_map(resolved_plan, FINE_LOGIC_AUDIT_REPORT)
    fine_gate_status = str(fine_report_map.get("status") or "missing")
    if fine_gate_status != "pass":
        return ManuscriptLogicGateBlock(
            section=section,
            topic_id=topic_id,
            required_report=FINE_LOGIC_AUDIT_REPORT,
            gate_status=fine_gate_status,
            blockers=_string_tuple(fine_report_map.get("blockers")),
        )

    return None


def _plan_carries_logic_bundle(plan: Mapping[str, Any]) -> bool:
    """True when the plan declares raw validator inputs (not just a report).

    Presence of a bundle KEY (even empty/invalid) triggers recompute: a plan
    that claims to be a full PAPER_PLAN must be validated from its inputs, so an
    empty ``core_claim_contract`` blocks rather than silently trusting a
    self-declared passing report.
    """
    return any(field in plan for field in _MANUSCRIPT_BUNDLE_FIELDS) or any(
        field in plan for field in _FINE_AUDIT_FIELDS
    )


def _assemble_manuscript_bundle(plan: Mapping[str, Any]) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "schema_version": MANUSCRIPT_LOGIC_BUNDLE_SCHEMA_VERSION,
        "fine_logic_audit": {field: plan.get(field) for field in _FINE_AUDIT_FIELDS},
    }
    for field in _MANUSCRIPT_BUNDLE_FIELDS:
        bundle[field] = plan.get(field)
    return bundle


def ensure_section_draft_logic_gate(
    *,
    db: Database | None,
    section: Any,
    topic_id: Any,
    paper_plan: Mapping[str, Any] | None = None,
) -> None:
    block = section_draft_logic_gate_block(
        db=db,
        section=section,
        topic_id=topic_id,
        paper_plan=paper_plan,
    )
    if block is not None:
        raise ManuscriptLogicGateRequired(block)


def _active_paper_plan(db: Database | None, topic_id: Any) -> Mapping[str, Any]:
    if db is None or topic_id is None:
        return {}

    try:
        artifacts = OrchestratorService(db).list_artifacts(int(topic_id))
    except Exception:
        LOGGER.debug(
            "Could not load PAPER_PLAN artifact for section_draft logic gate",
            exc_info=True,
        )
        return {}

    for artifact in artifacts:
        artifact_type = str(artifact.artifact_type or "").strip().lower()
        if artifact_type == "paper_plan":
            return artifact.payload if isinstance(artifact.payload, Mapping) else {}
    return {}


def _report_map(plan: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    report = plan.get(name)
    return report if isinstance(report, Mapping) else {}


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(text for item in value if (text := str(item or "").strip()))
