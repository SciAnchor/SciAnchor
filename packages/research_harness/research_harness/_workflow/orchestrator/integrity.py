"""Final integrity verification: 5-phase protocol and finalize logic.

Phases:
1. References — verify all citations are traceable to the paper pool
2. Citation context — check citations are used in proper context
3. Statistical data — flag unsubstantiated numerical claims
4. Originality — detect overclaiming or scope creep
5. Claims — verify every claim has linked evidence

Also handles finalize stage: produces final_bundle and process_summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from research_harness.storage.db import Database
from research_harness.verification import CitationSanitizeResult
from research_harness.verification import SourceRegistry
from research_harness.verification import record_hallucinated_citations
from research_harness.verification import sanitize_citations
from .artifacts import ArtifactManager
from .citation_governance import record_citation_verification
from .review import ReviewManager


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTEGRITY_PHASES: tuple[str, ...] = (
    "references",
    "citation_context",
    "statistical_data",
    "originality",
    "claims",
)

PHASE_DESCRIPTIONS: dict[str, str] = {
    "references": "Verify all citations are traceable to ingested papers",
    "citation_context": "Check citations are used in proper context, not misrepresented",
    "statistical_data": "Flag numerical claims without source or methodology",
    "originality": "Detect overclaiming, scope creep, or unoriginal contribution framing",
    "claims": "Verify every claim has linked evidence in the evidence pack",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IntegrityFinding:
    """A single finding from one integrity phase."""

    phase: str
    severity: str  # critical, high, medium, low
    category: str
    summary: str
    details: str = ""
    affected_artifact_type: str = ""
    affected_artifact_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "severity": self.severity,
            "category": self.category,
            "summary": self.summary,
            "details": self.details,
            "affected_artifact_type": self.affected_artifact_type,
            "affected_artifact_id": self.affected_artifact_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IntegrityFinding:
        return cls(
            phase=d.get("phase", ""),
            severity=d.get("severity", "medium"),
            category=d.get("category", ""),
            summary=d.get("summary", ""),
            details=d.get("details", ""),
            affected_artifact_type=d.get("affected_artifact_type", ""),
            affected_artifact_id=d.get("affected_artifact_id", ""),
        )


@dataclass
class IntegrityReport:
    """Result of the 5-phase integrity verification."""

    phases_completed: list[str] = field(default_factory=list)
    findings: list[IntegrityFinding] = field(default_factory=list)
    passed: bool = True
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "phases_completed": self.phases_completed,
            "findings": [f.to_dict() for f in self.findings],
            "passed": self.passed,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
        }

    @classmethod
    def from_payload(cls, p: dict[str, Any]) -> IntegrityReport:
        findings = [IntegrityFinding.from_dict(f) for f in p.get("findings", [])]
        return cls(
            phases_completed=p.get("phases_completed", []),
            findings=findings,
            passed=p.get("passed", True),
            critical_count=p.get("critical_count", 0),
            high_count=p.get("high_count", 0),
            medium_count=p.get("medium_count", 0),
            low_count=p.get("low_count", 0),
        )


# ---------------------------------------------------------------------------
# IntegrityVerifier
# ---------------------------------------------------------------------------


class IntegrityVerifier:
    """Runs the 5-phase integrity verification protocol."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._artifact_manager = ArtifactManager(db)
        self._review_manager = ReviewManager(db)

    def run_check(
        self,
        topic_id: int,
        stage: str,
        findings: list[dict[str, Any]] | None = None,
    ) -> IntegrityReport:
        """Run integrity verification and persist as artifact.

        Findings can be supplied externally (e.g. from an LLM agent) or
        auto-checked against the database (references and claims phases).

        Returns the IntegrityReport.
        """
        report = IntegrityReport()
        external_findings = [IntegrityFinding.from_dict(f) for f in (findings or [])]

        # Phase 1: References — check citation papers exist in pool
        phase1_findings = self._check_references(topic_id, stage)
        report.phases_completed.append("references")

        # Phase 2: Citation context — from external findings
        phase2_findings = [
            f for f in external_findings if f.phase == "citation_context"
        ]
        report.phases_completed.append("citation_context")

        # Phase 3: Statistical data — from external findings
        phase3_findings = [
            f for f in external_findings if f.phase == "statistical_data"
        ]
        report.phases_completed.append("statistical_data")

        # Phase 4: Originality — from external findings
        phase4_findings = [f for f in external_findings if f.phase == "originality"]
        report.phases_completed.append("originality")

        # Phase 5: Claims — check evidence links exist
        phase5_findings = self._check_claims(topic_id, stage)
        report.phases_completed.append("claims")

        # Combine all findings
        all_findings = (
            phase1_findings
            + phase2_findings
            + phase3_findings
            + phase4_findings
            + phase5_findings
        )
        # Also include any external findings not matched to specific phases
        matched_phases = {"citation_context", "statistical_data", "originality"}
        for f in external_findings:
            if f.phase not in matched_phases:
                all_findings.append(f)

        report.findings = all_findings

        # Count by severity
        for f in all_findings:
            if f.severity == "critical":
                report.critical_count += 1
            elif f.severity == "high":
                report.high_count += 1
            elif f.severity == "medium":
                report.medium_count += 1
            else:
                report.low_count += 1

        report.passed = report.critical_count == 0

        # Persist as artifact
        self._artifact_manager.record(
            topic_id=topic_id,
            stage=stage,
            artifact_type="final_integrity_report",
            title="Final Integrity Report",
            payload=report.to_payload(),
            metadata={
                "phases": len(report.phases_completed),
                "total_findings": len(report.findings),
                "passed": report.passed,
            },
        )

        # Explode critical findings into review_issues
        for f in all_findings:
            if f.severity in ("critical", "high"):
                self._review_manager.add_issue(
                    topic_id=topic_id,
                    stage=stage,
                    review_type="integrity",
                    severity=f.severity,
                    category=f.category or f.phase,
                    summary=f.summary,
                    details=f.details,
                    blocking=True,
                    affected_object_type=f.affected_artifact_type,
                    affected_object_id=f.affected_artifact_id,
                )

        return report

    def _check_references(
        self,
        topic_id: int,
        stage: str,
    ) -> list[IntegrityFinding]:
        """Phase 1: Check draft citations against paper pool."""
        findings: list[IntegrityFinding] = []
        verification_records: list[dict[str, Any]] = []
        draft_artifact_id = ""
        payload: dict[str, Any] = {}
        conn = self._db.connect()
        try:
            # Get draft artifact for this project
            draft = conn.execute(
                """
                SELECT id, payload_json FROM project_artifacts
                WHERE topic_id = ? AND artifact_type = 'draft_pack' AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if draft is None:
                return findings

            draft_artifact_id = str(draft["id"])
            payload = json.loads(draft["payload_json"] or "{}")
            cited_ids = payload.get("cited_paper_ids", [])

            # Check each cited paper exists in the topic-scoped paper pool.
            for paper_id in cited_ids:
                row = conn.execute(
                    """
                    SELECT 1 FROM papers p
                    JOIN paper_topics pt ON pt.paper_id = p.id
                    WHERE p.id = ? AND pt.topic_id = ?
                    """,
                    (paper_id, topic_id),
                ).fetchone()
                if row is None:
                    paper = conn.execute(
                        """
                        SELECT title, doi
                        FROM papers
                        WHERE id = ?
                        """,
                        (paper_id,),
                    ).fetchone()
                    exists = paper is not None
                    summary = (
                        f"Cited paper ID {paper_id} is not linked to this topic paper pool"
                        if exists
                        else f"Cited paper ID {paper_id} not found in paper pool"
                    )
                    verification_records.append(
                        {
                            "title": paper["title"] if paper else f"paper:{paper_id}",
                            "status": "cross_topic" if exists else "not_found",
                            "matched_title": paper["title"] if paper else "",
                            "matched_doi": paper["doi"] if paper else "",
                        }
                    )
                    findings.append(
                        IntegrityFinding(
                            phase="references",
                            severity="critical",
                            category="citation",
                            summary=summary,
                            affected_artifact_type="paper",
                            affected_artifact_id=str(paper_id),
                        )
                    )
        finally:
            conn.close()

        for record in verification_records:
            record_citation_verification(
                self._db,
                topic_id=topic_id,
                title=record["title"],
                status=record["status"],
                confidence=0.0,
                matched_title=record["matched_title"],
                matched_doi=record["matched_doi"],
                source="integrity_check:topic_scope",
            )

        findings.extend(
            self._check_draft_citation_registry(
                topic_id=topic_id,
                stage=stage,
                draft_artifact_id=draft_artifact_id,
                payload=payload,
            )
        )
        return findings

    def _check_draft_citation_registry(
        self,
        *,
        topic_id: int,
        stage: str,
        draft_artifact_id: str,
        payload: dict[str, Any],
    ) -> list[IntegrityFinding]:
        """Run deterministic source-registry sanitization on draft text."""

        chunks = _iter_draft_text_chunks(payload)
        if not chunks:
            return []

        registry = SourceRegistry.from_topic(self._db, topic_id)
        reports: list[dict[str, Any]] = []
        findings: list[IntegrityFinding] = []
        total_valid = 0
        total_removed = 0
        total_repaired = 0
        total_recorded = 0

        for label, text in chunks:
            result = sanitize_citations(text, registry)
            if (
                result.valid_count == 0
                and result.removed_count == 0
                and result.repaired_count == 0
            ):
                continue

            recorded = record_hallucinated_citations(
                self._db,
                topic_id,
                result.removed_citations,
                source="integrity_check:citation_sanitize",
            )
            reports.append(_citation_sanitization_payload(label, result, recorded))
            total_valid += result.valid_count
            total_removed += result.removed_count
            total_repaired += result.repaired_count
            total_recorded += recorded

            for removed in result.removed_citations:
                is_hallucinated = removed.reason == "not_in_source_registry"
                findings.append(
                    IntegrityFinding(
                        phase="references",
                        severity="critical" if is_hallucinated else "low",
                        category=(
                            "citation_hallucination"
                            if is_hallucinated
                            else "citation_deduplicated"
                        ),
                        summary=(
                            f"Unsupported citation [{removed.original_number}] "
                            f"removed from {label}"
                            if is_hallucinated
                            else f"Duplicate citation [{removed.original_number}] "
                            f"deduplicated in {label}"
                        ),
                        details=removed.ref_text,
                        affected_artifact_type="draft_pack",
                        affected_artifact_id=draft_artifact_id,
                    )
                )

        if reports:
            self._artifact_manager.record(
                topic_id=topic_id,
                stage=stage,
                artifact_type="citation_sanitization_report",
                title="Citation Sanitization Report",
                payload={
                    "draft_artifact_id": draft_artifact_id,
                    "valid_count": total_valid,
                    "removed_count": total_removed,
                    "repaired_count": total_repaired,
                    "hallucinated_recorded": total_recorded,
                    "sanitized_text": "\n\n".join(
                        report["sanitized_text"].rstrip() for report in reports
                    ).rstrip()
                    + "\n",
                    "sections": reports,
                },
                metadata={
                    "valid_count": total_valid,
                    "removed_count": total_removed,
                    "repaired_count": total_repaired,
                    "hallucinated_recorded": total_recorded,
                },
            )

        return findings

    def _check_claims(
        self,
        topic_id: int,
        stage: str,
    ) -> list[IntegrityFinding]:
        """Phase 5: Check claims have evidence links."""
        findings: list[IntegrityFinding] = []
        conn = self._db.connect()
        try:
            # Get evidence_pack artifact
            evidence = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = ? AND artifact_type = 'evidence_pack' AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if evidence is None:
                return findings

            import json

            payload = json.loads(evidence["payload_json"] or "{}")
            claims = payload.get("claims", [])

            for claim in claims:
                if not isinstance(claim, dict):
                    continue
                claim_id = claim.get("claim_id", claim.get("content", "")[:50])
                evidence_links = claim.get("evidence_links", [])
                if not evidence_links:
                    findings.append(
                        IntegrityFinding(
                            phase="claims",
                            severity="high",
                            category="evidence",
                            summary=f"Claim has no evidence links: {claim_id}",
                            affected_artifact_type="claim",
                            affected_artifact_id=str(claim_id),
                        )
                    )
        finally:
            conn.close()
        return findings


def _citation_sanitization_payload(
    section: str,
    result: CitationSanitizeResult,
    hallucinated_recorded: int,
) -> dict[str, Any]:
    """Serialize sanitizer output for an orchestrator artifact."""

    items: list[dict[str, Any]] = []
    for item in result.valid_citations:
        items.append(
            {
                "status": "valid",
                "original_number": item.original_number,
                "new_number": item.new_number,
                "source_id": item.source_id,
                "ref_text": item.ref_text,
                "repaired": item.repaired,
            }
        )
    for item in result.removed_citations:
        items.append(
            {
                "status": "removed",
                "original_number": item.original_number,
                "ref_text": item.ref_text,
                "reason": item.reason,
            }
        )

    return {
        "section": section,
        "sanitized_text": result.sanitized_text,
        "valid_count": result.valid_count,
        "removed_count": result.removed_count,
        "repaired_count": result.repaired_count,
        "hallucinated_recorded": hallucinated_recorded,
        "items": items,
    }


def _iter_draft_text_chunks(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract concrete draft text chunks from common draft_pack shapes."""

    chunks: list[tuple[str, str]] = []

    for key in ("text", "markdown", "content", "draft"):
        text = _extract_text(payload.get(key))
        if text:
            chunks.append((key if key != "draft" else "draft", text))

    for container_key in ("sections", "section_drafts", "draft_sections"):
        container = payload.get(container_key)
        if isinstance(container, dict):
            for name, raw in container.items():
                text = _extract_text(raw)
                if text:
                    chunks.append((str(name), text))
        elif isinstance(container, list):
            for index, raw in enumerate(container, start=1):
                text = _extract_text(raw)
                if not text:
                    continue
                label = f"{container_key}:{index}"
                if isinstance(raw, dict):
                    label = str(
                        raw.get("section")
                        or raw.get("name")
                        or raw.get("title")
                        or label
                    )
                chunks.append((label, text))
        else:
            text = _extract_text(container)
            if text:
                chunks.append((container_key, text))

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, text in chunks:
        key = (label, text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, text))
    return deduped


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""

    for key in ("text", "content", "markdown", "body"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()

    draft = value.get("draft")
    if isinstance(draft, dict):
        return _extract_text(draft)
    if isinstance(draft, str) and draft.strip():
        return draft.strip()
    return ""


# ---------------------------------------------------------------------------
# FinalizeManager
# ---------------------------------------------------------------------------


class FinalizeManager:
    """Produces the final bundle and process summary for the finalize stage."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._artifact_manager = ArtifactManager(db)

    def create_final_bundle(
        self,
        topic_id: int,
    ) -> Any:
        """Create the final submission bundle artifact.

        Collects references to all key artifacts produced during the workflow.
        """
        artifacts = self._artifact_manager.list_by_topic(topic_id)
        artifact_index = [
            {
                "id": a.id,
                "stage": a.stage,
                "type": a.artifact_type,
                "version": a.version,
                "title": a.title,
            }
            for a in artifacts
        ]

        payload = {
            "artifact_count": len(artifacts),
            "artifact_index": artifact_index,
            "status": "ready",
        }

        return self._artifact_manager.record(
            topic_id=topic_id,
            stage="finalize",
            artifact_type="final_bundle",
            title="Final Submission Bundle",
            payload=payload,
            metadata={"artifact_count": len(artifacts)},
        )

    def create_process_summary(
        self,
        topic_id: int,
    ) -> Any:
        """Create the process summary artifact.

        Documents the research workflow: stages traversed, review cycles,
        adversarial rounds, and key decisions.
        """
        conn = self._db.connect()
        try:
            # Stage events
            events = conn.execute(
                """
                SELECT from_stage, to_stage, event_type, actor, rationale, created_at
                FROM orchestrator_stage_events
                WHERE topic_id = ?
                ORDER BY id
                """,
                (topic_id,),
            ).fetchall()
            stage_history = [
                {
                    "from": e["from_stage"],
                    "to": e["to_stage"],
                    "type": e["event_type"],
                    "actor": e["actor"],
                    "rationale": e["rationale"],
                    "timestamp": e["created_at"],
                }
                for e in events
            ]

            # Review issue summary
            issue_row = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) as resolved,
                    SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) as critical
                FROM review_issues WHERE topic_id = ?
                """,
                (topic_id,),
            ).fetchone()

            # Artifact count by stage
            artifact_counts = conn.execute(
                """
                SELECT stage, COUNT(*) as cnt
                FROM project_artifacts
                WHERE topic_id = ?
                GROUP BY stage
                """,
                (topic_id,),
            ).fetchall()

            # Provenance cost
            prov_row = conn.execute(
                """
                SELECT COUNT(*) as ops, COALESCE(SUM(cost_usd), 0) as cost
                FROM provenance_records
                WHERE topic_id = ?
                """,
                (topic_id,),
            ).fetchone()
        finally:
            conn.close()

        payload = {
            "stage_history": stage_history,
            "stages_traversed": len(stage_history),
            "review_issues": {
                "total": issue_row["total"] if issue_row else 0,
                "resolved": issue_row["resolved"] if issue_row else 0,
                "critical": issue_row["critical"] if issue_row else 0,
            },
            "artifacts_by_stage": {r["stage"]: r["cnt"] for r in artifact_counts},
            "provenance": {
                "total_operations": prov_row["ops"] if prov_row else 0,
                "total_cost_usd": float(prov_row["cost"]) if prov_row else 0.0,
            },
        }

        return self._artifact_manager.record(
            topic_id=topic_id,
            stage="finalize",
            artifact_type="process_summary",
            title="Research Process Summary",
            payload=payload,
            metadata={"stages_traversed": len(stage_history)},
        )
