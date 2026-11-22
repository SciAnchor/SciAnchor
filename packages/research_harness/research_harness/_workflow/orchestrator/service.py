"""OrchestratorService: high-level orchestration API.

Used by CLI, MCP, and local API clients.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from research_harness.config import load_runtime_config
from research_harness.storage.db import Database
from .adversarial import AdversarialLoop, Objection
from .artifacts import ArtifactManager
from .integrity import FinalizeManager, IntegrityVerifier
from .models import (
    MAX_EVIDENCE_LOOPBACKS,
    MAX_EXPERIMENT_LOOPBACKS,
    MAX_GAP_LOOPBACKS,
    STAGE_GRAPH,
    SUBSTEP_TO_STAGE,
    GateDecision,
    OrchestratorRun,
    ProjectArtifact,
    StageName,
    WorkflowMode,
)
from .review import ReviewManager
from .stages import (
    ARTIFACT_STAGE_ALIASES,
    STAGE_ORDER,
    get_required_artifacts,
    next_stage,
    resolve_stage,
)
from .transitions import GateEvaluator, TransitionValidator

logger = logging.getLogger(__name__)


class OrchestratorService:
    """Service layer for orchestrator state management."""

    def __init__(self, db: Database | None = None):
        self._db = db or Database(load_runtime_config().db_path)
        self._validator = TransitionValidator(self._db)
        self._gate_evaluator = GateEvaluator(self._db)
        self._artifact_manager = ArtifactManager(self._db)
        self._adversarial = AdversarialLoop(self._db)
        self._review = ReviewManager(self._db)
        self._integrity = IntegrityVerifier(self._db)
        self._finalize = FinalizeManager(self._db)

    # -----------------------------------------------------------------------
    # Run lifecycle
    # -----------------------------------------------------------------------

    def init_run(
        self,
        topic_id: int,
        mode: WorkflowMode = "standard",
    ) -> OrchestratorRun:
        """Create a new orchestrator run for a topic."""
        conn = self._db.connect()
        try:
            project_row = conn.execute(
                "SELECT id FROM projects WHERE topic_id = ? ORDER BY id LIMIT 1",
                (topic_id,),
            ).fetchone()
            project_id = int(project_row["id"]) if project_row is not None else None
            cur = conn.execute(
                """
                INSERT INTO orchestrator_runs
                (project_id, topic_id, mode, current_stage, stage_status)
                VALUES (?, ?, ?, 'init', 'in_progress')
                """,
                (project_id, topic_id, mode),
            )
            run_id = int(cur.lastrowid)

            # Record initial stage event (single transaction with run insert)
            conn.execute(
                """
                INSERT INTO orchestrator_stage_events
                (run_id, project_id, topic_id, from_stage, to_stage, event_type, status, actor, rationale)
                VALUES (?, ?, ?, '', 'init', 'init', 'in_progress', 'system', 'Orchestrator run initialized')
                """,
                (run_id, project_id, topic_id),
            )
            conn.commit()

            return self.get_run(topic_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def infer_stage_from_artifacts(self, topic_id: int) -> str:
        """Return the furthest V2 stage the topic has actually completed.

        A stage is considered "completed" only if:

        1. All of its ``required_artifacts`` are present, AND
        2. Its gate evaluates to ``pass`` (i.e. the gate has been satisfied).

        The function returns the first stage in canonical order that has NOT
        completed — i.e. the stage the run should resume at. If a later stage
        has partial artifacts but an earlier stage's gate has not passed, we
        resume at the earlier stage to avoid silently skipping unresolved
        blockers.

        Falls back to ``init`` if no artifacts exist at all.
        """
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT stage, artifact_type FROM project_artifacts WHERE topic_id = ?",
                (topic_id,),
            ).fetchall()
        finally:
            conn.close()

        covered_stages: set[str] = set()
        for row in rows:
            stage = row["stage"]
            artifact_type = row["artifact_type"]
            resolved = resolve_stage(stage)
            if resolved in STAGE_ORDER:
                covered_stages.add(resolved)
            substep_mapped = SUBSTEP_TO_STAGE.get(stage)
            if substep_mapped:
                covered_stages.add(substep_mapped)
            alias_mapped = ARTIFACT_STAGE_ALIASES.get(artifact_type)
            if alias_mapped:
                covered_stages.add(alias_mapped)

        if not covered_stages:
            return "init"

        # Walk forward through stages. For each stage that has any coverage,
        # verify required artifacts AND gate status. Stop at the first stage
        # that is incomplete — that's where we resume.
        for stage in STAGE_ORDER:
            if stage not in covered_stages:
                return stage
            artifacts_ok = all(
                self._validator.check_artifacts_for_stage(topic_id, stage).values()
            )
            if not artifacts_ok:
                return stage
            try:
                gate_decision = self._gate_evaluator.evaluate(topic_id, stage)
            except Exception:
                logger.debug(
                    "Gate evaluation failed during infer_stage for topic %s at %s",
                    topic_id,
                    stage,
                    exc_info=True,
                )
                return stage
            if gate_decision != "pass":
                return stage

        # All stages completed — resume at the final stage (write).
        return STAGE_ORDER[-1]

    def resume_run(
        self,
        topic_id: int,
        mode: WorkflowMode = "standard",
        force_stage: str | None = None,
        stop_before: str | None = None,
    ) -> OrchestratorRun:
        """Resume (or create) an orchestrator run, inferring the current stage
        from existing artifacts instead of always starting at ``topic_framing``.

        If a run already exists for ``topic_id``, returns it unchanged unless
        ``force_stage`` is given, in which case the stage is overwritten.

        If no run exists, creates one at the inferred stage (or ``force_stage``).
        """
        if force_stage:
            force_stage = resolve_stage(force_stage)
        if stop_before:
            stop_before = resolve_stage(stop_before)
        existing = self.get_run(topic_id)
        if existing is not None:
            # Update stop_before if provided
            stop_before_changed = False
            if stop_before is not None:
                conn = self._db.connect()
                try:
                    conn.execute(
                        "UPDATE orchestrator_runs SET stop_before = ? WHERE topic_id = ?",
                        (stop_before, topic_id),
                    )
                    conn.commit()
                    stop_before_changed = True
                except Exception:
                    logger.warning(
                        "Failed to persist stop_before for topic %s",
                        topic_id,
                        exc_info=True,
                    )
                finally:
                    conn.close()
            mode_changed = mode != existing.mode
            stage_changed = bool(force_stage and force_stage != existing.current_stage)
            if stage_changed or mode_changed:
                conn = self._db.connect()
                try:
                    next_stage = (
                        force_stage if stage_changed else existing.current_stage
                    )
                    conn.execute(
                        """
                        UPDATE orchestrator_runs
                        SET current_stage = ?, mode = ?, stage_status = 'in_progress',
                            updated_at = datetime('now')
                        WHERE topic_id = ?
                        """,
                        (next_stage, mode, topic_id),
                    )
                    rationale_bits = []
                    if stage_changed:
                        rationale_bits.append(f"stage overridden to {next_stage}")
                    if mode_changed:
                        rationale_bits.append(f"mode synchronized to {mode}")
                    conn.execute(
                        """
                        INSERT INTO orchestrator_stage_events
                        (run_id, project_id, topic_id, from_stage, to_stage,
                         event_type, status, actor, rationale)
                        VALUES (?, ?, ?, ?, ?, 'resume', 'in_progress', 'system', ?)
                        """,
                        (
                            existing.id,
                            topic_id,
                            topic_id,
                            existing.current_stage,
                            next_stage,
                            "; ".join(rationale_bits),
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
                return self.get_run(topic_id)
            if stop_before_changed:
                # Refresh so the returned run reflects the new stop_before.
                return self.get_run(topic_id)
            return existing

        inferred = force_stage or self.infer_stage_from_artifacts(topic_id)
        conn = self._db.connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO orchestrator_runs
                (topic_id, mode, current_stage, stage_status, stop_before)
                VALUES (?, ?, ?, 'in_progress', ?)
                """,
                (topic_id, mode, inferred, stop_before or ""),
            )
            run_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO orchestrator_stage_events
                (run_id, topic_id, from_stage, to_stage,
                 event_type, status, actor, rationale)
                VALUES (?, ?, '', ?, 'init', 'in_progress', 'system', ?)
                """,
                (
                    run_id,
                    topic_id,
                    inferred,
                    f"Run resumed at inferred stage: {inferred}",
                ),
            )
            conn.commit()
            return self.get_run(topic_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_run(self, topic_id: int) -> OrchestratorRun | None:
        """Fetch the current orchestrator run for a topic."""
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM orchestrator_runs WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_run(row)
        finally:
            conn.close()

    def get_status(self, topic_id: int) -> dict[str, Any]:
        """Return a rich status dict for a topic."""
        run = self.get_run(topic_id)
        if run is None:
            return {"error": "No orchestrator run found for this topic"}

        # Check required artifacts for current stage
        artifacts_check = self._validator.check_artifacts_for_stage(
            topic_id, run.current_stage
        )

        # Evaluate gate
        gate_details = self._gate_evaluator.evaluate_details(
            topic_id,
            run.current_stage,
        )
        gate_decision = str(gate_details["gate_decision"])

        # Count active artifacts
        conn = self._db.connect()
        try:
            artifact_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM project_artifacts WHERE topic_id = ? AND status = 'active'",
                (topic_id,),
            ).fetchone()["cnt"]

            issue_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS open_count,
                    SUM(CASE WHEN blocking = 1 THEN 1 ELSE 0 END) AS blocking_count
                FROM review_issues
                WHERE topic_id = ? AND status = 'open'
                """,
                (topic_id,),
            ).fetchone()
            issue_count = int(issue_row["open_count"] or 0)
            blocking_issue_count = int(issue_row["blocking_count"] or 0)
        finally:
            conn.close()

        missing_artifacts = [
            art for art, exists in artifacts_check.items() if not exists
        ]

        result: dict[str, Any] = {
            "run": {
                "id": run.id,
                "topic_id": run.topic_id,
                "mode": run.mode,
                "current_stage": run.current_stage,
                "stage_status": run.stage_status,
                "gate_status": (
                    run.gate_status
                    if run.stage_status == "blocked" and run.gate_status
                    else gate_decision
                ),
                "blocking_issue_count": blocking_issue_count,
                "unresolved_issue_count": issue_count,
            },
            "stage": {
                "required_artifacts": list(get_required_artifacts(run.current_stage)),
                "artifacts_present": artifacts_check,
                "missing_artifacts": missing_artifacts,
            },
            "gate": {
                "decision": gate_decision,
                "can_advance": (
                    bool(gate_details.get("can_advance"))
                    and gate_decision == "pass"
                    and not missing_artifacts
                ),
                "reasons": list(gate_details.get("reasons") or []),
                "recovery_actions": list(gate_details.get("recovery_actions") or []),
            },
            "summary": {
                "total_artifacts": artifact_count,
                "open_issues": issue_count,
            },
        }
        if gate_details.get("paper_pool_audit"):
            result["gate"]["paper_pool_audit"] = gate_details["paper_pool_audit"]
            result["gate"]["coverage"] = self._build_coverage_status(gate_details)
        if gate_details.get("demo_evidence_boundary"):
            result["gate"]["demo_evidence_boundary"] = gate_details[
                "demo_evidence_boundary"
            ]
        return result

    @staticmethod
    def _build_coverage_status(gate_details: dict[str, Any]) -> dict[str, Any]:
        audit = dict(gate_details.get("paper_pool_audit") or {})
        counts = dict(audit.get("counts") or {})
        reasons = list(gate_details.get("reasons") or [])
        insufficient = next(
            (
                reason
                for reason in reasons
                if reason.get("code") == "insufficient_coverage_eligible_papers"
            ),
            {},
        )
        annotated_pdf_count = int(counts.get("coverage_eligible") or 0)
        required_count = int(insufficient.get("minimum") or annotated_pdf_count)
        return {
            "linked_paper_count": int(counts.get("total_linked") or 0),
            "annotated_pdf_count": annotated_pdf_count,
            "coverage_eligible_count": annotated_pdf_count,
            "required_count": required_count,
            "failed_check": (
                "annotated_pdf_count" if annotated_pdf_count < required_count else None
            ),
            "missing_roles": list(audit.get("missing_roles") or []),
            "recovery_actions": list(gate_details.get("recovery_actions") or []),
        }

    # -----------------------------------------------------------------------
    # Artifact management
    # -----------------------------------------------------------------------

    def record_artifact(
        self,
        topic_id: int,
        stage: StageName,
        artifact_type: str,
        title: str = "",
        path: str = "",
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_artifact_id: int | None = None,
        provenance_record_id: int | None = None,
        dependency_artifact_ids: list[int] | None = None,
        dependency_type: str = "consumed_by",
        propagate_stale_from_previous: bool = True,
        supersede_previous: bool = True,
    ) -> ProjectArtifact:
        """Record a new artifact for a stage."""
        previous = self._artifact_manager.get_latest(topic_id, stage, artifact_type)
        artifact = self._artifact_manager.record(
            topic_id=topic_id,
            stage=stage,
            artifact_type=artifact_type,
            title=title,
            path=path,
            payload=payload,
            metadata=metadata,
            parent_artifact_id=parent_artifact_id,
            provenance_record_id=provenance_record_id,
            supersede_previous=supersede_previous,
        )
        for upstream_id in dependency_artifact_ids or []:
            self._artifact_manager.add_dependency(
                from_artifact_id=self._resolve_active_dependency(upstream_id),
                to_artifact_id=artifact.id,
                dependency_type=dependency_type,
            )
        if (
            previous is not None
            and previous.id != artifact.id
            and propagate_stale_from_previous
            and supersede_previous
        ):
            self._artifact_manager.mark_stale(
                previous.id,
                reason=(
                    f"artifact superseded by newer {artifact_type} "
                    f"version {artifact.version} (artifact #{artifact.id})"
                ),
                propagate=True,
            )
        return artifact

    def _resolve_active_dependency(self, upstream_id: int) -> int:
        """Point a new dependency edge at the upstream's current active version.

        BUG-005: regenerated artifacts sometimes reuse a cached upstream id that
        has since been superseded. Wiring the edge to that superseded row makes
        the freshly-created artifact depend on — and get stale-cascaded from — a
        dead version, blocking it the instant it is born. Redirect to the active
        sibling of the same (topic, stage, artifact_type).
        """
        upstream = self._artifact_manager.get(upstream_id)
        if upstream is None or upstream.status != "superseded":
            return upstream_id
        active = self._artifact_manager.get_latest(
            upstream.topic_id, upstream.stage, upstream.artifact_type
        )
        if (
            active is not None
            and active.status == "active"
            and active.id != upstream_id
        ):
            return active.id
        return upstream_id

    def _manuscript_commit_gate_findings(
        self,
        *,
        topic_id: int,
        stage: StageName,
        tex_path: str,
        report: dict[str, Any],
        writing_mode: str,
    ) -> list[dict[str, Any]]:
        """Deterministic findings that block a manuscript commit.

        A committed final bundle must not ride over a failed stage gate, must
        not be a dream-marked bundle (dream firewall), and must
        not ship an ILLUSTRATION_PENDING figure fallback while a real provider
        is ready. Without this, commit_manuscript_version bypassed the
        write-gate invariants entirely: a caller-supplied quality report was
        recorded verbatim and became the topic's active final bundle
        unchecked.
        """
        from .invariants import (
            InvariantChecker,
            figure_pending_provider_ready_findings,
            venue_template_findings,
        )

        findings: list[dict[str, Any]] = []

        run = self.get_run(topic_id)
        if run is not None and str(run.gate_status or "") == "fail":
            findings.append(
                {
                    "check": "stage_gate_status",
                    "severity": "high",
                    "message": (
                        f"orchestrator run for topic {topic_id} has "
                        f"gate_status=fail at stage {run.current_stage}; "
                        "re-evaluate the failed gate before committing a "
                        "final bundle"
                    ),
                }
            )

        figure_plan = self.get_latest_artifact(topic_id, stage, "figure_plan")

        for violation in InvariantChecker.dream_firewall_findings(
            0, {"writing_mode": writing_mode}
        ):
            findings.append(
                {
                    "check": violation.check,
                    "severity": violation.severity,
                    "message": violation.message,
                }
            )

        target_venue = self._topic_target_venue(topic_id)
        if target_venue:
            from pathlib import Path as _Path

            try:
                tex_source = _Path(tex_path).read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                tex_source = ""
            if tex_source:
                findings.extend(
                    venue_template_findings(
                        target_venue, tex_source, _Path(tex_path).parent
                    )
                )

        pending_sources: dict[str, dict[str, Any]] = {}
        if report:
            pending_sources["quality_report"] = report
        if figure_plan is not None and isinstance(figure_plan.payload, dict):
            pending_sources["figure_plan"] = figure_plan.payload
        for source, payload in pending_sources.items():
            for finding in figure_pending_provider_ready_findings(payload):
                findings.append(
                    {
                        "check": "figure_provider_pending_with_ready_provider",
                        "severity": "high",
                        "message": (
                            f"{source} carries an ILLUSTRATION_PENDING fallback "
                            "marker while an illustration backend is "
                            "configured: generate the real figure via "
                            "figure_generate before committing"
                        ),
                        "source": source,
                        **finding,
                    }
                )

        # Final-draft polish gate: a recorded manuscript_polish_report whose
        # submission_readiness is "blocked" (unresolved high-severity reviewer
        # findings) must not ride into a committed final bundle. Only fires when
        # polish has actually been run (no report -> no finding -> no regression).
        polish = self.get_latest_artifact(topic_id, stage, "manuscript_polish_report")
        if polish is not None and isinstance(polish.payload, dict):
            if str(polish.payload.get("submission_readiness", "")) == "blocked":
                findings.append(
                    {
                        "check": "manuscript_polish_blocked",
                        "severity": "high",
                        "message": (
                            f"final-draft polish is blocked: manuscript_polish_report "
                            f"#{polish.id} has submission_readiness=blocked with "
                            f"{int(polish.payload.get('n_high', 0) or 0)} high-severity "
                            "finding(s); resolve them (rh polish run) before committing a "
                            "final bundle, or pass force_reason to record an audited override"
                        ),
                    }
                )

        findings.extend(
            self._ungrounded_number_findings(topic_id=topic_id, tex_path=tex_path)
        )

        return findings

    def _ungrounded_number_findings(
        self, *, topic_id: int, tex_path: str
    ) -> list[dict[str, Any]]:
        """Numbers in strict sections must trace to the verified registry.

        This is the consumer for the number-grounding verdict: the detector
        (verify_paper_numbers) previously ran only as an advisory tool whose
        result nothing read, so a fabricated Results number sailed through
        every gate. Fires ONLY when the topic has verified_numbers rows — a
        survey or position paper that never ran the experiment stage has an
        empty registry and must not be blocked for it. Sections are classified
        from the manuscript's own \\section headers, never from caller input.
        """
        from pathlib import Path as _Path

        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT number_original, source FROM verified_numbers"
                " WHERE topic_id = ?",
                (topic_id,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return []

        try:
            tex_source = _Path(tex_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        if not tex_source:
            return []

        import re as _re

        from research_harness.experiment.paper_verifier import (
            _classify_section,
            verify_paper_numbers,
        )
        from research_harness.experiment.verified_registry import VerifiedRegistry

        registry = VerifiedRegistry()
        for row in rows:
            registry.add_value(row["number_original"], row["source"])

        # Split the manuscript into (section title, body) pairs on \section
        # boundaries and verify only the strict ones (Results, Experiments,
        # Ablation, ...). Preamble and non-strict sections stay out of scope:
        # this gate exists for fabricated result numbers, not compile hygiene.
        pieces = _re.split(
            r"\\section\*?\{([^}]*)\}", tex_source.split("\\begin{document}", 1)[-1]
        )
        findings: list[dict[str, Any]] = []
        total_unverified = 0
        offenders: list[str] = []
        for i in range(1, len(pieces) - 1, 2):
            title, body = pieces[i], pieces[i + 1]
            if _classify_section(title) != "strict":
                continue
            result = verify_paper_numbers(body, registry, section=title)
            errors = [x for x in result.issues if x.severity == "error"]
            if errors:
                total_unverified += len(errors)
                sample = ", ".join(x.raw_text for x in errors[:5])
                offenders.append(f"{title} ({len(errors)}: {sample})")
        if total_unverified:
            findings.append(
                {
                    "check": "ungrounded_numbers_in_strict_sections",
                    "severity": "high",
                    "message": (
                        f"{total_unverified} number(s) in strict sections do not "
                        f"trace to any verified experiment metric: "
                        f"{'; '.join(offenders)}. Every result number must come "
                        "from a recorded run (verified_registry_build after "
                        "experiment_run). Re-run the analysis and update the "
                        "manuscript, or pass force_reason to record an audited "
                        "override"
                    ),
                }
            )
        return findings

    def _topic_target_venue(self, topic_id: int) -> str:
        conn = self._db.connect()
        try:
            try:
                row = conn.execute(
                    "SELECT target_venue FROM topics WHERE id = ?",
                    (topic_id,),
                ).fetchone()
            except Exception:  # noqa: BLE001 - legacy DBs may lack the column
                return ""
        finally:
            conn.close()
        if row is None:
            return ""
        return str(row["target_venue"] or "").strip()

    def commit_manuscript_version(
        self,
        topic_id: int,
        tex_path: str,
        pdf_path: str = "",
        stage: StageName = "write",
        title: str = "",
        quality_report: dict[str, Any] | None = None,
        dependency_artifact_ids: list[int] | None = None,
        notes: str = "",
        force_reason: str = "",
    ) -> dict[str, Any]:
        """Commit one manuscript version as an atomic artifact trio.

        Hashes the TeX (and PDF) files, records draft_pack → final_bundle →
        final_bundle_quality_report with lineage wired between them, and
        rejects the commit up front if any declared dependency is missing or
        no longer active — the manual per-file shasum + three separate
        record calls this replaces let a superseded dependency slip through.

        The commit is also gated: a failed stage gate, a dream-marked bundle
        (dream firewall), and pending figure
        fallbacks with a ready illustration backend all reject the commit
        unless ``force_reason`` records an audited human override.
        """
        import hashlib
        from pathlib import Path as _Path

        def _sha256(path_str: str) -> str:
            return hashlib.sha256(_Path(path_str).read_bytes()).hexdigest()

        tex_file = _Path(tex_path)
        if not tex_file.is_file():
            return {"success": False, "error": f"tex file not found: {tex_path}"}
        if pdf_path and not _Path(pdf_path).is_file():
            return {"success": False, "error": f"pdf file not found: {pdf_path}"}

        invalid: list[dict[str, Any]] = []
        for dep_id in dependency_artifact_ids or []:
            dep = self._artifact_manager.get(dep_id)
            if dep is None:
                invalid.append({"artifact_id": dep_id, "status": "missing"})
            elif dep.status != "active":
                invalid.append(
                    {
                        "artifact_id": dep_id,
                        "status": dep.status,
                        "type": dep.artifact_type,
                        "version": dep.version,
                    }
                )
        if invalid:
            return {
                "success": False,
                "error": "dependencies are not active; commit rejected",
                "invalid_dependencies": invalid,
            }

        report_dict = quality_report if isinstance(quality_report, dict) else {}
        writing_mode = str(
            report_dict.get("writing_mode") or report_dict.get("mode") or ""
        )
        gate_findings = self._manuscript_commit_gate_findings(
            topic_id=topic_id,
            stage=stage,
            tex_path=str(tex_file),
            report=report_dict,
            writing_mode=writing_mode,
        )
        forced = bool(str(force_reason or "").strip())
        if gate_findings and not forced:
            return {
                "success": False,
                "error": (
                    "manuscript commit blocked by gate findings; resolve them "
                    "or pass force_reason to record an audited override"
                ),
                "gate_findings": gate_findings,
            }

        commit_metadata: dict[str, Any] = {}
        if gate_findings:
            commit_metadata["gate_findings"] = gate_findings
            commit_metadata["force_reason"] = str(force_reason).strip()

        tex_sha = _sha256(tex_path)
        pdf_sha = _sha256(pdf_path) if pdf_path else ""

        draft = self.record_artifact(
            topic_id=topic_id,
            stage=stage,
            artifact_type="draft_pack",
            title=title or tex_file.name,
            path=str(tex_file),
            payload={"sha256": tex_sha, "notes": notes},
            dependency_artifact_ids=dependency_artifact_ids,
        )
        result: dict[str, Any] = {
            "success": True,
            "tex_sha256": tex_sha,
            "draft_pack": {"artifact_id": draft.id, "version": draft.version},
        }
        if gate_findings:
            result["forced"] = True
            result["gate_findings"] = gate_findings
            try:
                self.record_decision(
                    topic_id=topic_id,
                    stage=stage,
                    checkpoint="manuscript_commit_gate",
                    choice="force_commit",
                    reasoning=str(force_reason).strip()[:500],
                    actor="manuscript_commit",
                    origin="human",
                )
            except Exception:  # noqa: BLE001 - audit trail must not block commit
                pass

        if pdf_path:
            bundle_payload: dict[str, Any] = {
                "sha256": pdf_sha,
                "tex_sha256": tex_sha,
                "tex_path": str(tex_file),
                "files": {"tex": str(tex_file), "pdf": pdf_path},
                "draft_pack_artifact_id": draft.id,
                "notes": notes,
            }
            if writing_mode:
                bundle_payload["writing_mode"] = writing_mode
            # Carry declared figure provenance onto the bundle so later
            # write-gate evaluations see it (figure_provider_provenance).
            report_figures = report_dict.get("figures")
            if isinstance(report_figures, list) and report_figures:
                bundle_payload["figures"] = report_figures
            bundle = self.record_artifact(
                topic_id=topic_id,
                stage=stage,
                artifact_type="final_bundle",
                title=title or _Path(pdf_path).name,
                path=pdf_path,
                payload=bundle_payload,
                metadata=commit_metadata or None,
                dependency_artifact_ids=[draft.id],
                dependency_type="derived_from",
            )
            result["pdf_sha256"] = pdf_sha
            result["final_bundle"] = {
                "artifact_id": bundle.id,
                "version": bundle.version,
            }
            if quality_report is not None:
                report = self.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="final_bundle_quality_report",
                    title=title or f"quality report for {_Path(pdf_path).name}",
                    payload={
                        "final_bundle_artifact_id": bundle.id,
                        "report": quality_report,
                    },
                    metadata={"origin": "caller_reported", **commit_metadata},
                    dependency_artifact_ids=[bundle.id],
                    dependency_type="derived_from",
                )
                result["final_bundle_quality_report"] = {
                    "artifact_id": report.id,
                    "version": report.version,
                }
        return result

    def list_artifacts(
        self,
        topic_id: int,
        stage: StageName | None = None,
        artifact_type: str | None = None,
    ) -> list[ProjectArtifact]:
        """List artifacts for a topic."""
        return self._artifact_manager.list_by_topic(
            topic_id=topic_id,
            stage=stage,
            artifact_type=artifact_type,
        )

    def get_latest_artifact(
        self,
        topic_id: int,
        stage: StageName,
        artifact_type: str,
    ) -> ProjectArtifact | None:
        """Get the latest artifact of a given type."""
        return self._artifact_manager.get_latest(topic_id, stage, artifact_type)

    def add_artifact_dependency(
        self,
        from_artifact_id: int,
        to_artifact_id: int,
        dependency_type: str = "consumed_by",
    ) -> dict[str, Any]:
        """Declare that one artifact depends on another."""
        upstream = self._artifact_manager.get(from_artifact_id)
        downstream = self._artifact_manager.get(to_artifact_id)
        if upstream is None:
            return {
                "success": False,
                "error": f"Artifact not found: {from_artifact_id}",
            }
        if downstream is None:
            return {"success": False, "error": f"Artifact not found: {to_artifact_id}"}
        self._artifact_manager.add_dependency(
            from_artifact_id=from_artifact_id,
            to_artifact_id=to_artifact_id,
            dependency_type=dependency_type,
        )
        return {
            "success": True,
            "from_artifact_id": from_artifact_id,
            "to_artifact_id": to_artifact_id,
            "dependency_type": dependency_type,
        }

    def mark_artifact_stale(
        self,
        artifact_id: int,
        reason: str = "",
        propagate: bool = True,
    ) -> dict[str, Any]:
        """Mark an artifact stale and optionally propagate to dependents."""
        artifact = self._artifact_manager.get(artifact_id)
        if artifact is None:
            return {"success": False, "error": f"Artifact not found: {artifact_id}"}
        stale_ids = self._artifact_manager.mark_stale(
            artifact_id=artifact_id,
            reason=reason,
            propagate=propagate,
        )
        return {
            "success": True,
            "artifact_id": artifact_id,
            "propagate": propagate,
            "stale_ids": stale_ids,
        }

    def clear_artifact_stale(self, artifact_id: int) -> dict[str, Any]:
        """Clear stale state for an artifact."""
        artifact = self._artifact_manager.get(artifact_id)
        if artifact is None:
            return {"success": False, "error": f"Artifact not found: {artifact_id}"}
        self._artifact_manager.clear_stale(artifact_id)
        return {"success": True, "artifact_id": artifact_id}

    def list_stale_artifacts(self, topic_id: int) -> list[ProjectArtifact]:
        """List active stale artifacts for a topic."""
        return self._artifact_manager.list_stale(topic_id)

    # -----------------------------------------------------------------------
    # Stage advancement
    # -----------------------------------------------------------------------

    def advance(
        self,
        topic_id: int,
        actor: str = "system",
        auto_run_gates: bool = True,
    ) -> dict[str, Any]:
        """Attempt to advance the topic to the next stage."""
        run = self.get_run(topic_id)
        if run is None:
            bootstrap = self.resume_run(topic_id)
            if not bootstrap.get("success"):
                return {
                    "success": False,
                    "error": "No orchestrator run found and auto-bootstrap failed",
                }
            run = self.get_run(topic_id)
            if run is None:
                return {"success": False, "error": "No orchestrator run found"}

        current = run.current_stage

        # 1. Check if there's a next stage
        nxt = next_stage(current)
        if nxt is None:
            return {
                "success": False,
                "error": "No next stage (already at finalize)",
                "stage": current,
            }

        # 1b. Check stop_before gate
        if run.stop_before and nxt == run.stop_before:
            return {
                "success": False,
                "error": (
                    f"Hard stop: stop_before='{run.stop_before}' is set. "
                    f"Stage '{current}' is complete but advance to '{nxt}' is blocked. "
                    f"Use orchestrator_resume with stop_before='' to clear, "
                    f"or review the output of '{current}' before proceeding."
                ),
                "stage": current,
                "stop_before": run.stop_before,
                "completed_stage": current,
            }

        # 2. Check required artifacts exist
        allowed, reason, advisories = self._validator.can_advance(
            topic_id, current, nxt
        )
        if not allowed:
            return {
                "success": False,
                "error": reason,
                "stage": current,
            }

        # 3. Check gate
        if auto_run_gates:
            gate_decision = self._gate_evaluator.evaluate(topic_id, current)
            loopback_result = self._try_auto_loopback(
                run, current, gate_decision, actor
            )
            if loopback_result is not None:
                return loopback_result
            if gate_decision != "pass":
                if (
                    resolve_stage(current) == "build"
                    and gate_decision == "needs_coverage"
                ):
                    gate_details = self._gate_evaluator.evaluate_details(
                        topic_id,
                        current,
                        decision=gate_decision,
                    )
                    return self._mark_build_gate_blocked(
                        run=run,
                        gate_decision=gate_decision,
                        gate_details=gate_details,
                        actor=actor,
                    )
                gate_details = self._gate_evaluator.evaluate_details(
                    topic_id,
                    current,
                    decision=gate_decision,
                )
                return self._mark_gate_blocked(
                    run=run,
                    gate_decision=gate_decision,
                    gate_details=gate_details,
                    actor=actor,
                )

        # Perform transition
        conn = self._db.connect()
        try:
            conn.execute(
                """
                UPDATE orchestrator_runs
                SET current_stage = ?, stage_status = 'in_progress', updated_at = datetime('now')
                WHERE topic_id = ?
                """,
                (nxt, topic_id),
            )
            conn.execute(
                """
                INSERT INTO orchestrator_stage_events
                (run_id, project_id, topic_id, from_stage, to_stage, event_type, status, actor, rationale)
                VALUES (?, ?, ?, ?, ?, 'advance', 'in_progress', ?, ?)
                """,
                (
                    run.id,
                    topic_id,
                    run.topic_id,
                    current,
                    nxt,
                    actor,
                    f"Advanced from {current} to {nxt}",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # Auto-extract lessons from the completed stage
        self._auto_extract_lessons(current, run.topic_id)

        # Auto-housekeeping: promote draft strategies, check stale, patch
        self._auto_housekeeping()

        result: dict[str, Any] = {
            "success": True,
            "from_stage": current,
            "to_stage": nxt,
            "gate_decision": "pass" if auto_run_gates else "skipped",
        }
        if advisories:
            result["advisories"] = advisories
        return result

    MAX_GAP_LOOPBACKS = MAX_GAP_LOOPBACKS

    # (from_stage, gate_decision) → (target_stage, max_rounds, reason, checkpoint)
    #
    # Each entry declares: "when the gate at ``from_stage`` returns
    # ``gate_decision``, automatically loop back to ``target_stage`` up to
    # ``max_rounds`` times before surfacing the gate failure to the caller."
    AUTO_LOOPBACK_RULES: dict[tuple[str, str], tuple[str, int, str, str]] = {
        ("analyze", "needs_expansion"): (
            "build",
            MAX_GAP_LOOPBACKS,
            "insufficient research gaps detected — expanding paper pool",
            "gap_expansion_loopback",
        ),
        ("propose", "needs_coverage"): (
            "build",
            MAX_EVIDENCE_LOOPBACKS,
            "proposal lacks method-layer evidence — expanding paper pool",
            "evidence_expansion_loopback",
        ),
        ("propose", "needs_expansion"): (
            "analyze",
            MAX_EVIDENCE_LOOPBACKS,
            "proposal lacks claim support — re-running analysis",
            "claim_expansion_loopback",
        ),
        ("experiment", "needs_experiment"): (
            "propose",
            MAX_EXPERIMENT_LOOPBACKS,
            "experiment incomplete — revisiting study design",
            "experiment_redesign_loopback",
        ),
        ("write", "needs_review"): (
            "experiment",
            MAX_EXPERIMENT_LOOPBACKS,
            "write-stage review failed integrity checks — rerunning experiments",
            "write_integrity_loopback",
        ),
    }

    def _try_auto_loopback(
        self,
        run: OrchestratorRun,
        current: str,
        gate_decision: str,
        actor: str,
    ) -> dict[str, Any] | None:
        """Attempt a stage-appropriate auto-loopback.

        Returns a result dict if a loopback was performed (or exhausted),
        or None to fall through to the normal gate-failure path.
        """
        if gate_decision == "pass":
            return None

        rule = self.AUTO_LOOPBACK_RULES.get((current, gate_decision))
        if rule is None:
            return None

        target_stage, max_rounds, reason_text, checkpoint = rule

        # Respect stop_before guard for the loopback target.
        if run.stop_before and target_stage == run.stop_before:
            return None

        conn = self._db.connect()
        try:
            loopback_count = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM orchestrator_stage_events
                WHERE topic_id = ? AND from_stage = ? AND to_stage = ?
                      AND event_type = 'transition'
                """,
                (run.topic_id, current, target_stage),
            ).fetchone()["cnt"]
        finally:
            conn.close()

        if loopback_count >= max_rounds:
            logger.info(
                "Auto loopback %s→%s exhausted for topic %d (%d/%d)",
                current,
                target_stage,
                run.topic_id,
                loopback_count,
                max_rounds,
            )
            return None

        rationale = (
            f"Auto loopback {current}→{target_stage} "
            f"(round {loopback_count + 1}/{max_rounds}, "
            f"gate={gate_decision}): {reason_text}"
        )
        result = self.transition_to(
            run.topic_id,
            target_stage,
            rationale=rationale,
            actor=actor,
        )
        if not result.get("success"):
            return None

        self.record_decision(
            topic_id=run.topic_id,
            stage=current,
            checkpoint=checkpoint,
            choice=f"loopback_round_{loopback_count + 1}",
            reasoning=rationale,
        )

        logger.info(
            "Auto loopback %s→%s for topic %d (round %d)",
            current,
            target_stage,
            run.topic_id,
            loopback_count + 1,
        )
        return {
            "success": True,
            "loopback": True,
            "from_stage": current,
            "to_stage": target_stage,
            "round": loopback_count + 1,
            "max_rounds": max_rounds,
            "gate_decision": gate_decision,
        }

    def _auto_housekeeping(self) -> None:
        """Run housekeeping: promote draft strategies, check/patch stale ones."""
        try:
            from ..evolution.topic.patcher import StrategyPatcher

            patcher = StrategyPatcher(self._db)

            # 1. Promote draft strategies that passed probation
            promoted = patcher.check_promotions()
            if promoted:
                logger.info(
                    "Auto-promoted %d strategies from draft to active", len(promoted)
                )

            # 2. Check stale strategies and auto-patch
            conn = self._db.connect()
            try:
                active_rows = conn.execute(
                    "SELECT id FROM strategies WHERE status = 'active'"
                ).fetchall()
            finally:
                conn.close()

            for row in active_rows:
                stale = patcher.check_stale(row["id"])
                if stale.is_stale:
                    logger.info(
                        "Strategy %d is stale (%s), attempting patch",
                        row["id"],
                        stale.reason,
                    )
                    # Patch is LLM-powered — only attempt if stale
                    # (actual patching deferred to explicit strategy_patch call
                    #  to avoid surprise LLM costs during advance)
                    pass  # Log only; explicit patch via MCP tool

        except Exception:
            logger.debug("Auto-housekeeping failed", exc_info=True)

    def _auto_extract_lessons(
        self,
        stage: str,
        topic_id: int,
    ) -> None:
        """Auto-extract lessons from a completed stage (best-effort, non-blocking)."""
        try:
            from ..evolution.topic.store import DBLessonStore, Lesson

            # Build a minimal summary from recent provenance
            conn = self._db.connect()
            try:
                rows = conn.execute(
                    """SELECT primitive, success, COUNT(*) as cnt,
                              SUM(cost_usd) as cost
                       FROM provenance_records
                       WHERE stage = ? AND topic_id = ?
                       GROUP BY primitive, success
                       ORDER BY cnt DESC LIMIT 10""",
                    (stage, topic_id),
                ).fetchall()
            finally:
                conn.close()

            if not rows:
                return

            # Build issues from failed primitives
            issues: list[str] = []
            summary_parts: list[str] = []
            for r in rows:
                if r["success"]:
                    summary_parts.append(
                        f"{r['primitive']}: {r['cnt']} calls, ${r['cost'] or 0:.4f}"
                    )
                else:
                    issues.append(f"{r['primitive']} failed {r['cnt']} times")

            stage_summary = f"Stage {stage} completed. " + "; ".join(summary_parts[:5])

            # Store lessons directly (stub-level, no LLM call to avoid blocking)
            store = DBLessonStore(self._db)
            for issue in issues:
                store.append(
                    Lesson(
                        stage=stage, content=issue, lesson_type="failure", tags=[stage]
                    ),
                    source="auto_extracted",
                    topic_id=topic_id,
                )
            if stage_summary:
                store.append(
                    Lesson(
                        stage=stage,
                        content=stage_summary,
                        lesson_type="observation",
                        tags=[stage],
                    ),
                    source="auto_extracted",
                    topic_id=topic_id,
                )

            logger.info(
                "Auto-extracted %d lessons from stage %s", len(issues) + 1, stage
            )
        except Exception:
            logger.debug(
                "Auto lesson extraction failed for stage %s", stage, exc_info=True
            )

    def transition_to(
        self,
        topic_id: int,
        target_stage: StageName,
        *,
        rationale: str = "",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Transition to any stage allowed by STAGE_GRAPH (including loopbacks).

        Unlike advance() which only moves linearly, this allows jumps
        defined in STAGE_GRAPH — e.g. propose → build, write → experiment.
        """
        run = self.get_run(topic_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}

        current = run.current_stage
        valid_targets = STAGE_GRAPH.get(current, frozenset())
        if target_stage not in valid_targets:
            return {
                "success": False,
                "error": (
                    f"Invalid transition: {current} → {target_stage}. "
                    f"Valid targets: {sorted(valid_targets)}"
                ),
                "stage": current,
            }

        conn = self._db.connect()
        try:
            conn.execute(
                """
                UPDATE orchestrator_runs
                SET current_stage = ?, stage_status = 'in_progress', updated_at = datetime('now')
                WHERE topic_id = ?
                """,
                (target_stage, topic_id),
            )
            conn.execute(
                """
                INSERT INTO orchestrator_stage_events
                (run_id, project_id, topic_id, from_stage, to_stage, event_type, status, actor, rationale)
                VALUES (?, ?, ?, ?, ?, 'transition', 'in_progress', ?, ?)
                """,
                (
                    run.id,
                    topic_id,
                    run.topic_id,
                    current,
                    target_stage,
                    actor,
                    rationale or f"Transition from {current} to {target_stage}",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "success": True,
            "from_stage": current,
            "to_stage": target_stage,
            "transition_type": "loopback"
            if target_stage != next_stage(current)
            else "linear",
        }

    def check_gate(self, topic_id: int, stage: StageName | None = None) -> GateDecision:
        """Evaluate the gate for a stage (defaults to current stage)."""
        if stage is None:
            run = self.get_run(topic_id)
            if run is None:
                return "fail"
            stage = run.current_stage
        return self._gate_evaluator.evaluate(topic_id, stage)

    def check_gate_details(
        self,
        topic_id: int,
        stage: StageName | None = None,
    ) -> dict[str, Any]:
        """Evaluate a gate and return structured diagnostics."""
        if stage is None:
            run = self.get_run(topic_id)
            if run is None:
                return {
                    "gate_decision": "fail",
                    "can_advance": False,
                    "reasons": [
                        {
                            "code": "missing_orchestrator_run",
                            "message": "No orchestrator run found for this topic.",
                        }
                    ],
                    "recovery_actions": ["run orchestrator_resume for the topic"],
                }
            stage = run.current_stage
        return dict(self._gate_evaluator.evaluate_details(topic_id, stage))

    def _mark_gate_blocked(
        self,
        *,
        run: OrchestratorRun,
        gate_decision: str,
        gate_details: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        gate_status = str(gate_decision or "blocked")
        recovery_actions = list(gate_details.get("recovery_actions") or [])
        payload = {
            "gate_decision": gate_decision,
            "gate_status": gate_status,
            "stage_status": "blocked",
            "gate_details": gate_details,
            "recovery_actions": recovery_actions,
        }

        conn = self._db.connect()
        try:
            conn.execute(
                """
                UPDATE orchestrator_runs
                SET stage_status = 'blocked',
                    gate_status = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (gate_status, run.id),
            )
            conn.execute(
                """
                INSERT INTO orchestrator_stage_events
                (run_id, project_id, topic_id, from_stage, to_stage, event_type,
                 status, gate_type, actor, rationale, payload_json)
                VALUES (?, ?, ?, ?, ?, 'gate_blocked', 'blocked',
                        'stage_gate', ?, ?, ?)
                """,
                (
                    run.id,
                    run.topic_id,
                    run.topic_id,
                    run.current_stage,
                    run.current_stage,
                    actor,
                    f"Gate blocked: {gate_decision}",
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return {
            "success": False,
            "error": f"Gate check failed: {gate_decision}",
            "gate_decision": gate_decision,
            "gate_status": gate_status,
            "stage_status": "blocked",
            "stage": run.current_stage,
            "gate_details": gate_details,
            "recovery_actions": recovery_actions,
        }

    def _mark_build_gate_blocked(
        self,
        *,
        run: OrchestratorRun,
        gate_decision: str,
        gate_details: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        gate_status = "needs_screening"
        recovery_actions = list(gate_details.get("recovery_actions") or [])
        payload = {
            "gate_decision": gate_decision,
            "gate_status": gate_status,
            "stage_status": "blocked",
            "gate_details": gate_details,
            "recovery_actions": recovery_actions,
        }

        conn = self._db.connect()
        try:
            conn.execute(
                """
                UPDATE orchestrator_runs
                SET stage_status = 'blocked',
                    gate_status = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (gate_status, run.id),
            )
            conn.execute(
                """
                INSERT INTO orchestrator_stage_events
                (run_id, project_id, topic_id, from_stage, to_stage, event_type,
                 status, gate_type, actor, rationale, payload_json)
                VALUES (?, ?, ?, ?, ?, 'gate_blocked', 'blocked',
                        'coverage_gate', ?, ?, ?)
                """,
                (
                    run.id,
                    run.topic_id,
                    run.topic_id,
                    run.current_stage,
                    run.current_stage,
                    actor,
                    (
                        "Gate blocked: needs_screening after build coverage "
                        "audit found unscreened or insufficient evidence."
                    ),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return {
            "success": False,
            "error": "Gate check failed: needs_coverage; screening required",
            "gate_decision": gate_decision,
            "gate_status": gate_status,
            "stage_status": "blocked",
            "stage": run.current_stage,
            "gate_details": gate_details,
            "recovery_actions": recovery_actions,
        }

    # -----------------------------------------------------------------------
    # Adversarial optimization
    # -----------------------------------------------------------------------

    def run_adversarial_round(
        self,
        topic_id: int,
        target_artifact_id: int,
        proposal_snapshot: dict[str, Any],
        objections: list[dict[str, Any]],
        proposer_responses: list[dict[str, Any]] | None = None,
        resolver_notes: str = "",
        actor: str = "system",
        focus: str = "",
    ) -> dict[str, Any]:
        """Run one adversarial round and record it as an artifact."""
        run = self.get_run(topic_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}

        # Convert dict objections to Objection objects
        objection_objs = [
            Objection(
                category=o.get("category", ""),
                severity=o.get("severity", "minor"),
                target=o.get("target", ""),
                reasoning=o.get("reasoning", ""),
                suggested_fix=o.get("suggested_fix", ""),
            )
            for o in objections
        ]

        # Count existing rounds
        round_count = self._adversarial._count_rounds(topic_id, run.current_stage)
        round_number = round_count + 1

        try:
            result = self._adversarial.run_round(
                topic_id=topic_id,
                target_artifact_id=target_artifact_id,
                target_stage=run.current_stage,
                round_number=round_number,
                proposal_snapshot=proposal_snapshot,
                objections=objection_objs,
                proposer_responses=proposer_responses or [],
                resolver_notes=resolver_notes,
                focus=focus,
            )
        except ValueError as exc:
            # Loop-contract violation (e.g. round 2+ without proposer
            # responses). Surface it to the caller instead of recording a
            # round that can never converge.
            return {"success": False, "error": str(exc)}

        return {
            "success": True,
            "artifact_id": result["artifact_id"],
            "round_number": round_number,
            "stage": run.current_stage,
        }

    def resolve_adversarial_round(
        self,
        topic_id: int,
        round_artifact_id: int,
        scores: dict[str, float] | None = None,
        notes: str = "",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Resolve an adversarial round and determine outcome."""
        run = self.get_run(topic_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}

        # Get round number from artifact
        round_artifact = self._artifact_manager.get(round_artifact_id)
        if round_artifact is None:
            return {
                "success": False,
                "error": f"Round artifact {round_artifact_id} not found",
            }

        round_number = round_artifact.metadata.get("round_number", 1)

        result = self._adversarial.resolve_round(
            topic_id=topic_id,
            target_stage=run.current_stage,
            round_number=round_number,
            round_artifact_id=round_artifact_id,
            scores=scores or {},
            notes=notes,
        )

        resolution = result["resolution"]

        return {
            "success": True,
            "artifact_id": result["artifact_id"],
            "outcome": resolution["outcome"],
            "mean_score": resolution["mean_score"],
            "critical_unresolved": resolution["critical_unresolved"],
            "major_unresolved": resolution["major_unresolved"],
            "should_repeat": resolution["outcome"] == "revise_and_repeat",
            "stage": run.current_stage,
        }

    def check_adversarial_status(self, topic_id: int) -> dict[str, Any]:
        """Check current adversarial status for the topic."""
        run = self.get_run(topic_id)
        if run is None:
            return {"error": "No orchestrator run found"}

        # Get latest resolution
        resolution_artifact = self._adversarial._artifact_manager.get_latest(
            topic_id, run.current_stage, "adversarial_resolution"
        )

        if resolution_artifact is None:
            # Check if there are any rounds
            round_count = self._adversarial._count_rounds(topic_id, run.current_stage)
            return {
                "has_resolution": False,
                "round_count": round_count,
                "stage": run.current_stage,
                "status": "no_resolution_yet",
            }

        from .adversarial import AdversarialResolution

        resolution = AdversarialResolution.from_payload(resolution_artifact.payload)

        should_repeat, reason = self._adversarial.should_repeat(
            topic_id, run.current_stage, run.mode
        )

        return {
            "has_resolution": True,
            "outcome": resolution.outcome,
            "mean_score": resolution.mean_score,
            "critical_unresolved": resolution.critical_unresolved,
            "major_unresolved": resolution.major_unresolved,
            "round_number": resolution.round_number,
            "should_repeat": should_repeat,
            "reason": reason,
            "stage": run.current_stage,
        }

    # -----------------------------------------------------------------------
    # Review management
    # -----------------------------------------------------------------------

    def create_review_bundle(
        self,
        topic_id: int,
        integrity_artifact_id: int | None = None,
        scholarly_artifact_id: int | None = None,
    ) -> dict[str, Any]:
        """Create a review bundle linking review report artifacts."""
        run = self.get_run(topic_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}
        bundle = self._review.create_bundle(
            topic_id,
            run.current_stage,
            integrity_artifact_id,
            scholarly_artifact_id,
        )
        return {
            "success": True,
            "artifact_id": bundle.id,
            "stage": run.current_stage,
            "cycle_number": bundle.metadata.get("cycle_number", 1),
        }

    def add_review_issue(
        self,
        topic_id: int,
        review_type: str,
        severity: str,
        category: str,
        summary: str,
        details: str = "",
        blocking: bool = False,
        recommended_action: str = "",
        review_artifact_id: int | None = None,
    ) -> dict[str, Any]:
        """Add a review finding as an issue."""
        run = self.get_run(topic_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}
        issue = self._review.add_issue(
            topic_id=topic_id,
            stage=run.current_stage,
            review_type=review_type,
            severity=severity,
            category=category,
            summary=summary,
            details=details,
            blocking=blocking,
            recommended_action=recommended_action,
            review_artifact_id=review_artifact_id,
        )
        return {
            "success": True,
            "issue_id": issue.id,
            "severity": issue.severity,
            "blocking": issue.blocking,
            "stage": run.current_stage,
        }

    def respond_to_issue(
        self,
        issue_id: int,
        topic_id: int,
        response_type: str,
        response_text: str,
        artifact_id: int | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a response to a review issue."""
        response = self._review.add_response(
            issue_id=issue_id,
            topic_id=topic_id,
            response_type=response_type,
            response_text=response_text,
            artifact_id=artifact_id,
            evidence=evidence,
        )
        return {
            "success": True,
            "response_id": response.id,
            "response_type": response.response_type,
        }

    def resolve_review_issue(
        self,
        issue_id: int,
        resolution_status: str = "resolved",
    ) -> dict[str, Any]:
        """Mark a review issue as resolved or wontfix."""
        issue = self._review.resolve_issue(issue_id, resolution_status)
        return {
            "success": True,
            "issue_id": issue.id,
            "status": issue.status,
        }

    def list_review_issues(
        self,
        topic_id: int,
        stage: str | None = None,
        status: str | None = None,
        blocking_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List review issues with optional filters."""
        issues = self._review.list_issues(
            topic_id=topic_id,
            stage=stage,
            status=status,
            blocking_only=blocking_only,
        )
        return [
            {
                "id": i.id,
                "severity": i.severity,
                "category": i.category,
                "summary": i.summary,
                "status": i.status,
                "blocking": i.blocking,
                "review_type": i.review_type,
                "stage": i.stage,
            }
            for i in issues
        ]

    def get_review_status(self, topic_id: int) -> dict[str, Any]:
        """Get review summary for a topic."""
        run = self.get_run(topic_id)
        if run is None:
            return {"error": "No orchestrator run found"}
        return self._review.get_review_summary(topic_id, run.current_stage)

    # -----------------------------------------------------------------------
    # Integrity verification & finalize
    # -----------------------------------------------------------------------

    def run_integrity_check(
        self,
        topic_id: int,
        findings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run 5-phase integrity verification and persist report."""
        run = self.get_run(topic_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}
        report = self._integrity.run_check(
            topic_id=topic_id,
            stage=run.current_stage,
            findings=findings,
        )
        return {
            "success": True,
            "passed": report.passed,
            "phases_completed": report.phases_completed,
            "critical_count": report.critical_count,
            "high_count": report.high_count,
            "medium_count": report.medium_count,
            "low_count": report.low_count,
            "total_findings": len(report.findings),
            "stage": run.current_stage,
        }

    def finalize(
        self,
        topic_id: int,
    ) -> dict[str, Any]:
        """Create final_bundle and process_summary artifacts."""
        run = self.get_run(topic_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}
        bundle = self._finalize.create_final_bundle(topic_id)
        summary = self._finalize.create_process_summary(topic_id)
        return {
            "success": True,
            "bundle_artifact_id": bundle.id,
            "summary_artifact_id": summary.id,
            "artifact_count": bundle.payload.get("artifact_count", 0),
            "stages_traversed": summary.payload.get("stages_traversed", 0),
            "stage": run.current_stage,
        }

    def record_experiment_run(
        self,
        topic_id: int,
        *,
        iteration: int = 1,
        code_hash: str = "",
        primary_metric_name: str = "",
        primary_metric_value: float = 0.0,
        metrics: dict | None = None,
        kept: bool = True,
    ) -> None:
        """Insert an experiment_runs row (public API for auto_runner)."""
        import json as _json

        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT id FROM projects WHERE topic_id = ? ORDER BY id LIMIT 1",
                (topic_id,),
            ).fetchone()
            project_id = int(row["id"]) if row is not None else None
            conn.execute(
                """INSERT INTO experiment_runs
                   (project_id, topic_id, iteration, code_hash, primary_metric_name,
                    primary_metric_value, all_metrics_json, kept)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    topic_id,
                    iteration,
                    code_hash,
                    primary_metric_name,
                    primary_metric_value,
                    _json.dumps(metrics or {}),
                    1 if kept else 0,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Decision log
    # -----------------------------------------------------------------------

    def record_decision(
        self,
        topic_id: int,
        stage: str,
        checkpoint: str,
        choice: str,
        reasoning: str = "",
        params: dict[str, Any] | None = None,
        actor: str | None = None,
        origin: str | None = None,
    ) -> dict[str, Any]:
        """Record a human (or auto) decision at a checkpoint.

        ``actor`` (who triggered this: user/orchestrator/auto_runner/...) and
        ``origin`` (user/auto/loopback/rollback/retry) back the drilldown UI
        added in migration 055. Both default to NULL for legacy callers.
        """
        import json as _json

        conn = self._db.connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO decision_log
                (project_id, topic_id, stage, checkpoint, choice, reasoning,
                 params_snapshot, actor, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic_id,
                    topic_id,
                    resolve_stage(stage),
                    checkpoint,
                    choice,
                    reasoning,
                    _json.dumps(params or {}, ensure_ascii=False),
                    actor,
                    origin,
                ),
            )
            conn.commit()
            return {
                "success": True,
                "decision_id": cur.lastrowid,
                "stage": resolve_stage(stage),
                "checkpoint": checkpoint,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_decisions(
        self,
        topic_id: int,
        stage: str | None = None,
    ) -> list[dict[str, Any]]:
        """List decision log entries for a topic."""
        conn = self._db.connect()
        try:
            if stage:
                rows = conn.execute(
                    "SELECT * FROM decision_log WHERE topic_id = ? AND stage = ? ORDER BY created_at",
                    (topic_id, resolve_stage(stage)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM decision_log WHERE topic_id = ? ORDER BY created_at",
                    (topic_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _row_to_run(row: Any) -> OrchestratorRun:
        # stop_before may not exist in older DBs before migration 027
        try:
            stop_before = row["stop_before"] or ""
        except (IndexError, KeyError):
            stop_before = ""
        return OrchestratorRun(
            id=row["id"],
            topic_id=row["topic_id"],
            mode=row["mode"],
            current_stage=row["current_stage"],
            stage_status=row["stage_status"],
            gate_status=row["gate_status"],
            blocking_issue_count=row["blocking_issue_count"],
            unresolved_issue_count=row["unresolved_issue_count"],
            latest_plan_artifact_id=row["latest_plan_artifact_id"],
            latest_draft_artifact_id=row["latest_draft_artifact_id"],
            stop_before=stop_before,
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )
