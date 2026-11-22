"""Stage transition validator and artifact gate checker."""

from __future__ import annotations

import json

from research_harness.paper_pool_audit import (
    ROLE_PATTERNS,
    audit_topic_paper_pool,
    build_coverage_gate_details,
)

from . import stages
from .models import (
    DEFAULT_MIN_PAPER_COUNT,
    MIN_EVIDENCE_COVERAGE,
    MIN_GAP_COUNT,
    MIN_SEED_PAPER_COUNT,
    MIN_YEAR_SPAN,
    GateDecision,
    StageName,
)
from .citation_governance import CitationGateGovernanceRecorder
from .invariants import InvariantChecker, is_blocking


def _hallucinated_citation_count(conn, topic_id: int) -> int:
    """Return the number of hallucinated citations for a topic.

    Returns 0 if the ``citation_verifications`` table does not exist (e.g. pre-
    migration DB) or the topic has no records. Never raises.
    """
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM citation_verifications
            WHERE topic_id = ? AND status = 'hallucinated'
            """,
            (topic_id,),
        ).fetchone()
        return int(row["cnt"]) if row else 0
    except Exception:
        return 0


def _paper_production_demo_evidence_boundary(
    conn,
    *,
    topic_id: int,
    stage_names: tuple[str, ...] | list[str],
) -> dict[str, object]:
    """Return whether build can pass as an explicitly evidence-limited demo.

    This does not relax the normal build coverage gate. It only applies when
    the build artifacts themselves declare the paper-production demo boundary
    and carry at least ``MIN_SEED_PAPER_COUNT`` linked seed papers. Downstream
    paper-production artifacts must keep the same not-submission-ready boundary.
    """

    placeholders = ",".join("?" * len(stage_names))
    row = conn.execute(
        f"""
        SELECT payload_json FROM project_artifacts
        WHERE topic_id = ? AND stage IN ({placeholders})
              AND artifact_type = 'paper_pool_snapshot'
              AND status = 'active'
        ORDER BY version DESC LIMIT 1
        """,
        (topic_id, *stage_names),
    ).fetchone()
    if row is None:
        return {"allowed": False, "reason": "missing_paper_pool_snapshot"}
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError):
        return {"allowed": False, "reason": "invalid_paper_pool_snapshot"}
    if payload.get("evidence_boundary") != "demo_limited_seed_pool":
        return {"allowed": False, "reason": "not_demo_boundary"}
    if payload.get("submission_readiness") != "not_submission_ready":
        return {"allowed": False, "reason": "missing_submission_boundary"}
    try:
        paper_count = int(payload.get("paper_count") or 0)
    except (TypeError, ValueError):
        paper_count = 0
    if paper_count < MIN_SEED_PAPER_COUNT:
        return {"allowed": False, "reason": "insufficient_demo_seed_papers"}

    seed_count = conn.execute(
        """
        SELECT COUNT(DISTINCT pt.paper_id) AS cnt
        FROM paper_topics pt
        WHERE pt.topic_id = ?
          AND pt.relevance != 'dismissed'
        """,
        (topic_id,),
    ).fetchone()["cnt"]
    if int(seed_count or 0) < MIN_SEED_PAPER_COUNT:
        return {"allowed": False, "reason": "insufficient_linked_seed_papers"}

    return {"allowed": True, "reason": "demo_limited_seed_pool"}


def _build_gate_required_roles(
    conn,
    *,
    topic_id: int,
) -> tuple[str, ...]:
    """Evidence roles the build gate must see covered, from the active plan.

    An explicit ``domain_profile.required_evidence_roles`` list on the paper
    plan wins, so topic-specific evidence portfolios (e.g. sports-event
    consumption) live in the plan rather than in gate code. Without it, a
    topic-agnostic default is derived from discipline/study design.

    When a topic has no usable profile we return an empty tuple — the gate then
    requires *no* specific evidence roles. It must NOT fall back to auditing
    every known role: doing so demanded topic-irrelevant evidence (GIS, causal
    inference, sports-event consumption) from unrelated topics like ceramics
    education (BUG-004). ``None`` still means "audit every role" at the standalone
    audit primitive, but the gate never emits it.
    """
    row = conn.execute(
        """
        SELECT payload_json FROM project_artifacts
        WHERE topic_id = ? AND artifact_type = 'paper_plan'
              AND status = 'active'
        ORDER BY version DESC LIMIT 1
        """,
        (topic_id,),
    ).fetchone()
    if row is None:
        return ()
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError):
        return ()
    domain_profile = payload.get("domain_profile")
    if not isinstance(domain_profile, dict):
        return ()
    explicit = domain_profile.get("required_evidence_roles")
    if isinstance(explicit, (list, tuple)):
        roles = tuple(
            str(item).strip() for item in explicit if str(item).strip() in ROLE_PATTERNS
        )
        if roles:
            return roles
    discipline = str(domain_profile.get("discipline") or "").strip().lower()
    study_design = str(domain_profile.get("study_design") or "").strip().lower()
    if discipline == "social_science" and study_design == "observational":
        return (
            "dataset_source",
            "causal_identification",
            "baseline_evaluation",
        )
    return ()


class TransitionValidator:
    """Validates whether a project can advance from one stage to another."""

    def __init__(self, db):
        self._db = db

    def can_advance(
        self,
        topic_id: int,
        from_stage: StageName,
        to_stage: StageName,
    ) -> tuple[bool, str, list[str]]:
        """Return (allowed, reason, advisories) for a proposed transition.

        advisories: list of soft prerequisite warnings (non-blocking).
        """
        # 1. Check graph validity
        if not stages.is_valid_transition(from_stage, to_stage):
            return False, f"Invalid transition: {from_stage} -> {to_stage}", []

        # 2. Check required artifacts exist for the *current* stage
        required = stages.get_required_artifacts(from_stage)
        if required:
            stage_names = stages.stage_names_for_query(from_stage)
            placeholders = ",".join("?" * len(stage_names))
            conn = self._db.connect()
            try:
                for artifact_type in required:
                    row = conn.execute(
                        f"""
                        SELECT 1 FROM project_artifacts
                        WHERE topic_id = ? AND stage IN ({placeholders})
                              AND artifact_type = ? AND status = 'active'
                        LIMIT 1
                        """,
                        (topic_id, *stage_names, artifact_type),
                    ).fetchone()
                    if row is None:
                        return (
                            False,
                            (
                                f"Missing required artifact '{artifact_type}' "
                                f"for stage '{from_stage}'"
                            ),
                            [],
                        )
            finally:
                conn.close()

        # 3. Check soft prerequisites (advisory, not blocking)
        advisories: list[str] = []
        soft_prereqs = stages.get_soft_prerequisites(to_stage)
        if soft_prereqs:
            advisories = list(soft_prereqs)

        return True, "", advisories

    def check_artifacts_for_stage(
        self,
        topic_id: int,
        stage: StageName,
    ) -> dict[str, bool]:
        """Return a map of required artifact -> exists for a stage."""
        required = stages.get_required_artifacts(stage)
        if not required:
            return {}

        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        result: dict[str, bool] = {art: False for art in required}
        conn = self._db.connect()
        try:
            for artifact_type in required:
                row = conn.execute(
                    f"""
                    SELECT 1 FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (topic_id, *stage_names, artifact_type),
                ).fetchone()
                result[artifact_type] = row is not None
        finally:
            conn.close()
        return result


class GateEvaluator:
    """Gate evaluator with enhanced checks for V2 stages."""

    def __init__(self, db):
        self._db = db
        self._invariant_checker = InvariantChecker(db)
        self._citation_governance = CitationGateGovernanceRecorder(db)

    def evaluate(self, topic_id: int, stage: StageName) -> GateDecision:
        """Evaluate the gate for a stage and return a decision."""
        # Deterministic invariant pre-checks
        violations = self._invariant_checker.check_all(topic_id, stage)
        blocking = [v for v in violations if is_blocking(v)]
        if blocking:
            import logging

            logger = logging.getLogger(__name__)
            for v in blocking:
                logger.warning("Invariant violation: %s", v.message)
            self._citation_governance.record_invariant_block(
                topic_id=topic_id,
                stage=stage,
                violations=blocking,
                decision="fail",
            )
            return "fail"

        gate_type = stages.get_gate_type(stage)

        if gate_type == "approval_gate":
            return self._evaluate_approval_gate(topic_id, stage)
        if gate_type == "coverage_gate":
            return self._evaluate_coverage_gate(topic_id, stage)
        if gate_type == "adversarial_gate":
            return self._evaluate_adversarial_gate(topic_id, stage)
        if gate_type == "review_gate":
            decision = self._evaluate_review_gate(topic_id)
            if decision != "pass":
                self._citation_governance.record_existing_citation_block(
                    topic_id=topic_id,
                    stage=stage,
                    decision=decision,
                )
            return decision
        if gate_type == "integrity_gate":
            decision = self._evaluate_integrity_gate(topic_id)
            if decision != "pass":
                self._citation_governance.record_existing_citation_block(
                    topic_id=topic_id,
                    stage=stage,
                    decision=decision,
                )
            return decision
        if gate_type == "experiment_gate":
            return self._evaluate_experiment_gate(topic_id, stage)
        return "pass"

    def evaluate_details(
        self,
        topic_id: int,
        stage: StageName,
        *,
        decision: GateDecision | None = None,
    ) -> dict[str, object]:
        """Return an additive, structured diagnostic payload for a gate."""

        gate_decision = decision or self.evaluate(topic_id, stage)
        if stages.resolve_stage(stage) != "build":
            return self._approval_gate_details(
                topic_id,
                stage,
                gate_decision=gate_decision,
            )

        required = stages.get_required_artifacts(stage)
        stage_names = stages.stage_names_for_query(stage)
        missing_required: list[str] = []
        missing_citation_expansion = False
        placeholders = ",".join("?" * len(stage_names))
        conn = self._db.connect()
        try:
            required_roles = _build_gate_required_roles(conn, topic_id=topic_id)
            for artifact_type in required:
                row = conn.execute(
                    f"""
                    SELECT 1 FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (topic_id, *stage_names, artifact_type),
                ).fetchone()
                if row is None:
                    missing_required.append(artifact_type)
            demo_boundary = _paper_production_demo_evidence_boundary(
                conn,
                topic_id=topic_id,
                stage_names=stage_names,
            )
            if demo_boundary["allowed"] and not missing_required:
                return {
                    "schema_version": "rh.build_coverage_gate_details.v1",
                    "gate_decision": "pass",
                    "can_advance": True,
                    "reasons": [],
                    "recovery_actions": [],
                    "paper_pool_audit": audit_topic_paper_pool(
                        self._db,
                        topic_id,
                        required_roles=required_roles,
                    ),
                    "demo_evidence_boundary": demo_boundary,
                }
            cit_row = conn.execute(
                f"""
                SELECT 1 FROM project_artifacts
                WHERE topic_id = ? AND stage IN ({placeholders})
                      AND artifact_type = 'citation_expansion_report'
                      AND status = 'active'
                LIMIT 1
                """,
                (topic_id, *stage_names),
            ).fetchone()
            missing_citation_expansion = cit_row is None
        finally:
            conn.close()

        audit = audit_topic_paper_pool(
            self._db,
            topic_id,
            required_roles=required_roles,
        )
        details = build_coverage_gate_details(
            audit=audit,
            min_coverage_eligible=DEFAULT_MIN_PAPER_COUNT,
            min_year_span=MIN_YEAR_SPAN,
            missing_required_artifacts=missing_required,
            missing_citation_expansion=missing_citation_expansion,
        )
        if gate_decision == "fail":
            details["gate_decision"] = "fail"
            details["can_advance"] = False
        return details

    MIN_GAP_COUNT = MIN_GAP_COUNT

    def _approval_gate_details(
        self,
        topic_id: int,
        stage: StageName,
        *,
        gate_decision: GateDecision,
    ) -> dict[str, object]:
        resolved = stages.resolve_stage(stage)
        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        reasons: list[dict[str, object]] = []
        recovery_actions: list[str] = []
        conn = self._db.connect()
        try:
            for artifact_type in stages.get_required_artifacts(stage):
                row = conn.execute(
                    f"""
                    SELECT 1 FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (topic_id, *stage_names, artifact_type),
                ).fetchone()
                if row is None:
                    reasons.append(
                        {
                            "code": "missing_required_artifact",
                            "artifact_type": artifact_type,
                            "message": f"Missing required {artifact_type} artifact for {resolved}.",
                        }
                    )
                    recovery_actions.append(
                        f"record {artifact_type} before advancing {resolved}"
                    )

            if resolved == "init":
                brief_row = conn.execute(
                    f"""
                    SELECT payload_json FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type = 'topic_brief'
                          AND status = 'active'
                    ORDER BY version DESC LIMIT 1
                    """,
                    (topic_id, *stage_names),
                ).fetchone()
                if brief_row is not None:
                    try:
                        brief = json.loads(brief_row["payload_json"] or "{}")
                    except (TypeError, ValueError):
                        brief = {}
                    scope_raw = (
                        brief.get("scope", "") if isinstance(brief, dict) else ""
                    )
                    scope_ok = bool(
                        scope_raw if isinstance(scope_raw, str) else scope_raw
                    )
                    has_exclusion = isinstance(brief, dict) and any(
                        brief.get(k)
                        for k in (
                            "exclusion_criteria",
                            "exclusions",
                            "out_of_scope",
                            "scope_boundaries",
                        )
                    )
                    if not scope_ok:
                        reasons.append(
                            {
                                "code": "topic_brief_missing_scope",
                                "message": "Topic brief must define a non-empty scope.",
                            }
                        )
                        recovery_actions.append(
                            "revise topic_brief with explicit scope"
                        )
                    if not has_exclusion:
                        reasons.append(
                            {
                                "code": "topic_brief_missing_exclusions",
                                "message": "Topic brief must define exclusion criteria or scope boundaries.",
                            }
                        )
                        recovery_actions.append(
                            "revise topic_brief with exclusions or out-of-scope boundaries"
                        )
                seed_count = conn.execute(
                    """
                    SELECT COUNT(DISTINCT pt.paper_id) AS cnt
                    FROM paper_topics pt
                    WHERE pt.topic_id = ?
                      AND pt.relevance != 'dismissed'
                    """,
                    (topic_id,),
                ).fetchone()["cnt"]
                if seed_count < MIN_SEED_PAPER_COUNT:
                    reasons.append(
                        {
                            "code": "insufficient_seed_papers",
                            "message": f"{seed_count}/{MIN_SEED_PAPER_COUNT} non-dismissed seed papers are linked to the topic.",
                            "observed": int(seed_count),
                            "minimum": MIN_SEED_PAPER_COUNT,
                        }
                    )
                    recovery_actions.append(
                        "ingest or link screened seed papers before advancing init"
                    )

            if resolved == "analyze" and gate_decision == "needs_expansion":
                reasons.append(
                    {
                        "code": "analysis_needs_expansion",
                        "message": "Analyze gate requires additional gaps or evidence coverage before advancing.",
                    }
                )
                recovery_actions.append(
                    "run gap detection and evidence coverage repair before advancing analyze"
                )

            if resolved == "write" and gate_decision in ("needs_review", "fail"):
                issue_rows = conn.execute(
                    """
                    SELECT id, stage, severity, category, summary, blocking
                    FROM review_issues
                    WHERE topic_id = ? AND status = 'open'
                      AND (blocking = 1 OR severity = 'critical')
                    ORDER BY id
                    LIMIT 10
                    """,
                    (topic_id,),
                ).fetchall()
                for row in issue_rows:
                    reasons.append(
                        {
                            "code": "open_review_issue",
                            "issue_id": int(row["id"]),
                            "stage": row["stage"],
                            "severity": row["severity"],
                            "category": row["category"],
                            "blocking": bool(row["blocking"]),
                            "message": row["summary"],
                        }
                    )
                if issue_rows:
                    recovery_actions.append(
                        "resolve open blocking or critical review issues before advancing write"
                    )
        finally:
            conn.close()
        return {
            "gate_decision": gate_decision,
            "can_advance": gate_decision == "pass" and not reasons,
            "reasons": reasons,
            "recovery_actions": recovery_actions,
        }

    def _evaluate_approval_gate(self, topic_id: int, stage: StageName) -> GateDecision:
        """Check if required artifacts exist.

        For the 'init' stage, also verifies that a topic_brief has scope /
        exclusion fields defined and at least ``MIN_SEED_PAPER_COUNT`` seed
        papers were ingested under the topic.

        For the 'analyze' stage, also verifies that gap_detect produced
        enough gaps (>= MIN_GAP_COUNT) to warrant advancing. If not,
        returns 'needs_expansion' to trigger an automatic loopback.
        """
        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        conn = self._db.connect()
        try:
            required = stages.get_required_artifacts(stage)
            for artifact_type in required:
                row = conn.execute(
                    f"""
                    SELECT 1 FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (topic_id, *stage_names, artifact_type),
                ).fetchone()
                if row is None:
                    return "needs_approval"

            resolved = stages.resolve_stage(stage)

            if resolved == "init":
                # Inspect topic_brief payload: scope must be non-empty and
                # at least one exclusion-style field should exist.
                brief_row = conn.execute(
                    f"""
                    SELECT payload_json FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type = 'topic_brief'
                          AND status = 'active'
                    ORDER BY version DESC LIMIT 1
                    """,
                    (topic_id, *stage_names),
                ).fetchone()
                if brief_row:
                    try:
                        brief = json.loads(brief_row["payload_json"] or "{}")
                    except (TypeError, ValueError):
                        brief = {}
                    scope_raw = brief.get("scope", "")
                    scope_ok = bool(
                        scope_raw if isinstance(scope_raw, str) else scope_raw
                    )
                    has_exclusion = any(
                        brief.get(k)
                        for k in (
                            "exclusion_criteria",
                            "exclusions",
                            "out_of_scope",
                            "scope_boundaries",
                        )
                    )
                    if not scope_ok or not has_exclusion:
                        return "needs_approval"

                # Verify seed paper count.
                seed_count = conn.execute(
                    """
                    SELECT COUNT(DISTINCT pt.paper_id) AS cnt
                    FROM paper_topics pt
                    WHERE pt.topic_id = ?
                      AND pt.relevance != 'dismissed'
                    """,
                    (topic_id,),
                ).fetchone()["cnt"]
                if seed_count < MIN_SEED_PAPER_COUNT:
                    return "needs_approval"

            if resolved == "analyze":
                gap_row = conn.execute(
                    f"""
                    SELECT payload_json FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type IN ('gap_detect', 'gap_analysis')
                          AND status = 'active'
                    ORDER BY version DESC LIMIT 1
                    """,
                    (topic_id, *stage_names),
                ).fetchone()
                if gap_row:
                    try:
                        payload = json.loads(gap_row["payload_json"] or "{}")
                    except (TypeError, ValueError):
                        payload = {}
                    gaps = payload.get("gaps", [])
                    if len(gaps) < self.MIN_GAP_COUNT:
                        return "needs_expansion"

                # Evidence coverage soft-check: if evidence_trace artifact is
                # present, require coverage_ratio >= MIN_EVIDENCE_COVERAGE.
                ev_row = conn.execute(
                    """
                    SELECT payload_json FROM project_artifacts
                    WHERE topic_id = ? AND artifact_type = 'evidence_trace_report'
                          AND status = 'active'
                    ORDER BY version DESC LIMIT 1
                    """,
                    (topic_id,),
                ).fetchone()
                if ev_row:
                    try:
                        ev_payload = json.loads(ev_row["payload_json"] or "{}")
                    except (TypeError, ValueError):
                        ev_payload = {}
                    coverage = float(ev_payload.get("coverage_ratio", 0.0) or 0.0)
                    if coverage < MIN_EVIDENCE_COVERAGE:
                        return "needs_expansion"

            return "pass"
        finally:
            conn.close()

    def _evaluate_coverage_gate(self, topic_id: int, stage: StageName) -> GateDecision:
        """Check required artifacts + minimum corpus quality for Build exit.

        Enhanced checks:
        - Required artifacts exist
        - Minimum strict coverage corpus size from RH_MIN_CORPUS_SIZE
        - Method family diversity (≥3 distinct concept families)
        - Temporal span (≥2 distinct years)
        """
        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        conn = self._db.connect()
        try:
            # 1. Check required artifacts
            required = stages.get_required_artifacts(stage)
            for artifact_type in required:
                row = conn.execute(
                    f"""
                    SELECT 1 FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (topic_id, *stage_names, artifact_type),
                ).fetchone()
                if row is None:
                    return "needs_coverage"

            # 2. Enhanced: check corpus size and diversity (for "build" stage)
            resolved = stages.resolve_stage(stage)
            if resolved == "build":
                demo_boundary = _paper_production_demo_evidence_boundary(
                    conn,
                    topic_id=topic_id,
                    stage_names=stage_names,
                )
                if demo_boundary["allowed"]:
                    return "pass"

                # Retrieval convergence (soft: only enforced when the
                # iterative_retrieval_loop primitive has been invoked).
                # Motivation: prevents advancing while the LLM still has
                # fresh queries that hit mostly-new papers.
                loop_row = conn.execute(
                    f"""
                    SELECT payload_json FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type = 'iterative_retrieval_loop_result'
                          AND status = 'active'
                    ORDER BY version DESC LIMIT 1
                    """,
                    (topic_id, *stage_names),
                ).fetchone()
                if loop_row:
                    try:
                        loop_payload = json.loads(loop_row["payload_json"] or "{}")
                    except (TypeError, ValueError):
                        loop_payload = {}
                    if not bool(loop_payload.get("convergence_reached")):
                        return "needs_coverage"

                # Citation expansion (mandatory): keyword search alone
                # is insufficient — must also traverse the citation
                # graph (forward + backward) from seed papers. Without
                # this, the pool misses seminal and follow-up work that
                # doesn't match keyword queries.
                cit_row = conn.execute(
                    f"""
                    SELECT payload_json FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type = 'citation_expansion_report'
                          AND status = 'active'
                    ORDER BY version DESC LIMIT 1
                    """,
                    (topic_id, *stage_names),
                ).fetchone()

                audit = audit_topic_paper_pool(
                    self._db,
                    topic_id,
                    required_roles=_build_gate_required_roles(
                        conn,
                        topic_id=topic_id,
                    ),
                )
                details = build_coverage_gate_details(
                    audit=audit,
                    min_coverage_eligible=DEFAULT_MIN_PAPER_COUNT,
                    min_year_span=MIN_YEAR_SPAN,
                    missing_required_artifacts=[],
                    missing_citation_expansion=cit_row is None,
                )
                if not details["can_advance"]:
                    return "needs_coverage"

            return "pass"
        finally:
            conn.close()

    def _evaluate_adversarial_gate(
        self, topic_id: int, stage: StageName
    ) -> GateDecision:
        """Check for adversarial resolution with no unresolved fatal flaws."""
        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        conn = self._db.connect()
        try:
            row = conn.execute(
                f"""
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = ? AND stage IN ({placeholders})
                      AND artifact_type = 'adversarial_resolution'
                      AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id, *stage_names),
            ).fetchone()
            if row is None:
                return "needs_adversarial"
            payload = json.loads(row["payload_json"] or "{}")
            outcome = payload.get("outcome", "")
            if outcome in ("approved", "approved_with_conditions"):
                # Enhanced: verify no unresolved critical objections
                critical = payload.get("critical_unresolved", 0)
                if critical > 0:
                    return "needs_adversarial"
                return "pass"
            return "needs_adversarial"
        finally:
            conn.close()

    def _evaluate_review_gate(self, topic_id: int) -> GateDecision:
        """Evaluate the write-stage review gate.

        Blocks when any of the following is true:

        - Any open blocking review issue exists.
        - Any open critical-severity review issue exists.
        - ``final_bundle`` or ``process_summary`` artifact is missing.
        - A ``final_integrity_report`` exists but did not pass (critical>0).
        - Any hallucinated citation was recorded for the topic.
        """
        conn = self._db.connect()
        try:
            # 1. No blocking issues.
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM review_issues
                WHERE topic_id = ? AND status = 'open' AND blocking = 1
                """,
                (topic_id,),
            ).fetchone()
            if row and row["cnt"] > 0:
                return "needs_review"

            # 2. No open critical-severity issues.
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM review_issues
                WHERE topic_id = ? AND status = 'open' AND severity = 'critical'
                """,
                (topic_id,),
            ).fetchone()
            if row and row["cnt"] > 0:
                return "needs_review"

            # 3. final_bundle + process_summary artifacts must exist.
            for artifact_type in ("final_bundle", "process_summary"):
                row = conn.execute(
                    """
                    SELECT 1 FROM project_artifacts
                    WHERE topic_id = ? AND artifact_type = ?
                          AND status = 'active'
                    LIMIT 1
                    """,
                    (topic_id, artifact_type),
                ).fetchone()
                if row is None:
                    return "needs_review"

            # 4. If final_integrity_report was generated, it must be passing.
            fi_row = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = ? AND artifact_type = 'final_integrity_report'
                      AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if fi_row:
                try:
                    fi = json.loads(fi_row["payload_json"] or "{}")
                except (TypeError, ValueError):
                    fi = {}
                if (
                    fi.get("passed") is False
                    or int(fi.get("critical_count", 0) or 0) > 0
                ):
                    return "needs_review"

            # 5. No hallucinated citations.
            if _hallucinated_citation_count(conn, topic_id) > 0:
                return "needs_review"

            return "pass"
        finally:
            conn.close()

    def _evaluate_integrity_gate(self, topic_id: int) -> GateDecision:
        """Evaluate the integrity gate (used by ``final_integrity``).

        Sub-checks:

        1. No open critical review issues.
        2. No hallucinated citations in ``citation_verifications``.
        3. ``final_integrity_report`` exists AND ``passed`` is true.
        4. ``verified_registry`` artifact exists with ``whitelist_size`` > 0.
        5. If an ``evidence_trace_report`` artifact exists, its
           ``coverage_ratio`` must be >= ``MIN_EVIDENCE_COVERAGE``.
        """
        conn = self._db.connect()
        try:
            # 1. No open critical review issues.
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM review_issues
                WHERE topic_id = ? AND status = 'open' AND severity = 'critical'
                """,
                (topic_id,),
            ).fetchone()
            if row and row["cnt"] > 0:
                return "needs_integrity"

            # 2. No hallucinated citations.
            if _hallucinated_citation_count(conn, topic_id) > 0:
                return "needs_integrity"

            # 3. final_integrity_report must exist and pass.
            fi_row = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = ? AND artifact_type = 'final_integrity_report'
                      AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if fi_row is None:
                return "needs_integrity"
            try:
                fi = json.loads(fi_row["payload_json"] or "{}")
            except (TypeError, ValueError):
                fi = {}
            if not fi.get("passed"):
                return "needs_integrity"
            if int(fi.get("critical_count", 0) or 0) > 0:
                return "needs_integrity"

            # 4. verified_registry with non-empty whitelist.
            vr_row = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = ? AND artifact_type = 'verified_registry'
                      AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if vr_row:
                try:
                    vr = json.loads(vr_row["payload_json"] or "{}")
                except (TypeError, ValueError):
                    vr = {}
                if int(vr.get("whitelist_size", 0) or 0) <= 0:
                    return "needs_integrity"

            # 5. Evidence trace coverage (if available).
            ev_row = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = ? AND artifact_type = 'evidence_trace_report'
                      AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if ev_row:
                try:
                    ev = json.loads(ev_row["payload_json"] or "{}")
                except (TypeError, ValueError):
                    ev = {}
                coverage = float(ev.get("coverage_ratio", 0.0) or 0.0)
                if coverage < MIN_EVIDENCE_COVERAGE:
                    return "needs_integrity"

            return "pass"
        finally:
            conn.close()

    def evaluate_with_policy(
        self,
        topic_id: int,
        stage: str,
        auto_resolve: bool = False,
    ) -> tuple[str, bool]:
        """Evaluate gate with optional auto-resolution.

        Returns (decision, was_auto_resolved).
        """
        decision = self.evaluate(topic_id, stage)

        if decision == "pass" or not auto_resolve:
            return decision, False

        # In autonomous mode, auto-resolve non-blocking decisions
        # but NEVER auto-resolve "fail" (invariant violations)
        if decision == "fail":
            return decision, False

        # Check if this stage allows auto-resolution
        from ..auto_runner.stage_policy import get_policy

        policy = get_policy(stage)
        if policy and policy.risk_level == "high":
            # High-risk stages always need human even in autonomous mode
            return decision, False

        import logging

        logger = logging.getLogger(__name__)
        logger.info("Auto-resolving gate for stage %s: %s → pass", stage, decision)
        return "pass", True

    def _evaluate_experiment_gate(
        self, topic_id: int, stage: StageName
    ) -> GateDecision:
        """Check experiment completion: result + verified registry + kept iterations."""
        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        conn = self._db.connect()
        try:
            # Check required artifacts exist
            for artifact_type in ("experiment_result", "verified_registry"):
                row = conn.execute(
                    f"""
                    SELECT 1 FROM project_artifacts
                    WHERE topic_id = ? AND stage IN ({placeholders})
                          AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (topic_id, *stage_names, artifact_type),
                ).fetchone()
                if row is None:
                    return "needs_experiment"

            # Check at least one kept experiment iteration
            try:
                row = conn.execute(
                    """
                    SELECT COUNT(*) as cnt
                    FROM experiment_runs
                    WHERE kept = 1 AND (topic_id = ? OR project_id = ?)
                    """,
                    (topic_id, topic_id),
                ).fetchone()
                if not row or row["cnt"] == 0:
                    return "needs_experiment"
            except Exception as exc:
                # experiment_runs table may not exist yet during migration;
                # surface as a hard fail so the operator notices.
                import logging

                logging.getLogger(__name__).error(
                    "experiment_runs query failed for topic %s: %s. "
                    "Migration 012 may not have been applied.",
                    topic_id,
                    exc,
                )
                return "fail"

            return "pass"
        finally:
            conn.close()
