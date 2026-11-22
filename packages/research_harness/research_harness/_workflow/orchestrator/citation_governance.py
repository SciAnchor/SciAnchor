"""Replayable governance records for citation-related gate failures."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from research_harness.storage.db import Database
from .artifacts import ArtifactManager
from .invariants import InvariantViolation
from .review import ReviewManager


SCHEMA_VERSION = "citation_gate_governance/v1"
ROLLBACK_EVENT_SCHEMA_VERSION = "rollback_gate_governance/v1"
FAILED_CITATION_STATUSES = frozenset(
    {"hallucinated", "cross_topic", "not_found", "unsupported", "contradicts", "stale"}
)
ROLLBACK_EVENT_INVARIANT_CHECKS = frozenset(
    {
        "stale_artifact",
        "stale_baseline_governance",
    }
)


def record_citation_verification(
    db: Database,
    *,
    topic_id: int,
    title: str,
    status: str,
    confidence: float = 0.0,
    matched_title: str = "",
    matched_doi: str = "",
    source: str,
) -> int | None:
    """Insert or return a deterministic citation verification row."""

    conn = db.connect()
    try:
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(citation_verifications)"
            ).fetchall()
        }
        if not columns:
            return None

        project_row = conn.execute(
            "SELECT id FROM projects WHERE topic_id = ? ORDER BY id LIMIT 1",
            (topic_id,),
        ).fetchone()
        if project_row is None:
            return None
        project_id = int(project_row["id"])

        query = """
            SELECT id FROM citation_verifications
            WHERE project_id = ?
              AND title = ?
              AND status = ?
              AND COALESCE(matched_doi, '') = ?
              AND COALESCE(source, '') = ?
        """
        params: list[Any] = [
            project_id,
            title,
            status,
            matched_doi,
            source,
        ]
        if "topic_id" in columns:
            query += " AND topic_id = ?"
            params.append(topic_id)
        query += " ORDER BY id LIMIT 1"
        existing = conn.execute(query, params).fetchone()
        if existing is not None:
            return int(existing["id"])

        if "topic_id" in columns:
            cur = conn.execute(
                """
                INSERT INTO citation_verifications
                    (project_id, topic_id, title, status, confidence,
                     matched_title, matched_doi, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    topic_id,
                    title,
                    status,
                    confidence,
                    matched_title,
                    matched_doi,
                    source,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO citation_verifications
                    (project_id, title, status, confidence,
                     matched_title, matched_doi, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    title,
                    status,
                    confidence,
                    matched_title,
                    matched_doi,
                    source,
                ),
            )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


class CitationGateGovernanceRecorder:
    """Persist citation gate decisions without duplicating repeated checks."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._artifacts = ArtifactManager(db)
        self._reviews = ReviewManager(db)

    def record_invariant_block(
        self,
        *,
        topic_id: int,
        stage: str,
        violations: list[InvariantViolation],
        decision: str,
    ) -> dict[str, Any]:
        citation_ids: list[int] = []
        issue_ids: list[int] = []

        for violation in violations:
            citation_id = self._ensure_citation_verification(topic_id, violation)
            if citation_id is not None:
                citation_ids.append(citation_id)
            issue_ids.append(self._ensure_review_issue(topic_id, stage, violation))

        gate_artifact_id = self._ensure_gate_decision_artifact(
            topic_id=topic_id,
            stage=stage,
            decision=decision,
            violations=violations,
            citation_verification_ids=citation_ids,
            review_issue_ids=issue_ids,
        )
        result = {
            "gate_decision_artifact_id": gate_artifact_id,
            "citation_verification_ids": citation_ids,
            "review_issue_ids": issue_ids,
        }
        rollback_event_id = self._ensure_rollback_event_artifact(
            topic_id=topic_id,
            stage=stage,
            decision=decision,
            violations=violations,
            gate_decision_artifact_id=gate_artifact_id,
            review_issue_ids=issue_ids,
        )
        if rollback_event_id is not None:
            result["rollback_event_artifact_id"] = rollback_event_id
        return result

    def record_existing_citation_block(
        self,
        *,
        topic_id: int,
        stage: str,
        decision: str,
    ) -> dict[str, Any]:
        """Record gate replay data for citation rows/issues already in storage."""

        citation_rows = self._failed_citation_rows(topic_id)
        issue_ids = self._open_citation_issue_ids(topic_id)
        if citation_rows and not issue_ids:
            issue_ids = [
                self._ensure_review_issue_for_citation_row(topic_id, stage, row)
                for row in citation_rows
            ]
        if not citation_rows and not issue_ids:
            return {}

        citation_ids = [int(row["id"]) for row in citation_rows]
        reason_codes = _unique(
            [f"citation_{row['status']}" for row in citation_rows]
            + (["open_citation_review_issue"] if issue_ids else [])
        )
        gate_artifact_id = self._ensure_citation_state_gate_decision_artifact(
            topic_id=topic_id,
            stage=stage,
            decision=decision,
            reason_codes=reason_codes,
            citation_rows=citation_rows,
            citation_verification_ids=citation_ids,
            review_issue_ids=issue_ids,
        )
        return {
            "gate_decision_artifact_id": gate_artifact_id,
            "citation_verification_ids": citation_ids,
            "review_issue_ids": issue_ids,
        }

    def _ensure_citation_verification(
        self,
        topic_id: int,
        violation: InvariantViolation,
    ) -> int | None:
        if violation.check != "unsupported_evidence_link":
            return None

        metadata = violation.metadata
        candidate = metadata.get("citation_candidate")
        if not isinstance(candidate, dict):
            candidate = {}
        status = str(metadata.get("support_status") or "unsupported").lower()
        title = str(
            candidate.get("title")
            or candidate.get("identifier")
            or metadata.get("source_id")
            or metadata.get("claim_id")
            or "unsupported citation"
        )
        matched_doi = _candidate_doi(candidate)
        return record_citation_verification(
            self._db,
            topic_id=topic_id,
            title=title,
            status=status,
            confidence=0.0,
            matched_title=str(candidate.get("title") or ""),
            matched_doi=matched_doi,
            source=f"orchestrator_gate:{violation.check}",
        )

    def _ensure_review_issue(
        self,
        topic_id: int,
        stage: str,
        violation: InvariantViolation,
    ) -> int:
        fields = _issue_fields(violation)
        existing = self._find_open_issue(
            topic_id=topic_id,
            stage=stage,
            review_type=fields["review_type"],
            category=fields["category"],
            affected_object_type=fields["affected_object_type"],
            affected_object_id=fields["affected_object_id"],
            summary=violation.message,
        )
        if existing is not None:
            return existing

        issue = self._reviews.add_issue(
            topic_id=topic_id,
            stage=stage,
            review_type=fields["review_type"],
            severity=violation.severity,
            category=fields["category"],
            summary=violation.message,
            details=json.dumps(violation.to_dict(), sort_keys=True),
            blocking=True,
            recommended_action=fields["recommended_action"],
            affected_object_type=fields["affected_object_type"],
            affected_object_id=fields["affected_object_id"],
        )
        return int(issue.id)

    def _find_open_issue(
        self,
        *,
        topic_id: int,
        stage: str,
        review_type: str,
        category: str,
        affected_object_type: str,
        affected_object_id: str,
        summary: str,
    ) -> int | None:
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT id FROM review_issues
                WHERE topic_id = ?
                  AND stage = ?
                  AND review_type = ?
                  AND category = ?
                  AND affected_object_type = ?
                  AND affected_object_id = ?
                  AND summary = ?
                  AND status = 'open'
                ORDER BY id LIMIT 1
                """,
                (
                    topic_id,
                    stage,
                    review_type,
                    category,
                    affected_object_type,
                    affected_object_id,
                    summary,
                ),
            ).fetchone()
            return int(row["id"]) if row is not None else None
        finally:
            conn.close()

    def _failed_citation_rows(self, topic_id: int) -> list[dict[str, Any]]:
        conn = self._db.connect()
        try:
            try:
                rows = conn.execute(
                    """
                    SELECT id, title, status, confidence, matched_title,
                           matched_doi, source
                    FROM citation_verifications
                    WHERE topic_id = ?
                    ORDER BY id
                    """,
                    (topic_id,),
                ).fetchall()
            except Exception:
                return []
            return [
                {key: row[key] for key in row.keys()}
                for row in rows
                if str(row["status"] or "").lower() in FAILED_CITATION_STATUSES
            ]
        finally:
            conn.close()

    def _open_citation_issue_ids(self, topic_id: int) -> list[int]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id FROM review_issues
                WHERE topic_id = ?
                  AND status = 'open'
                  AND (
                    review_type = 'citation_governance'
                    OR category = 'citation'
                    OR category LIKE 'citation_%'
                  )
                ORDER BY id
                """,
                (topic_id,),
            ).fetchall()
            return [int(row["id"]) for row in rows]
        finally:
            conn.close()

    def _ensure_review_issue_for_citation_row(
        self,
        topic_id: int,
        stage: str,
        row: dict[str, Any],
    ) -> int:
        status = str(row.get("status") or "failed").lower()
        summary = f"Citation verification {row['id']} is {status}: {row['title']}"
        existing = self._find_open_issue(
            topic_id=topic_id,
            stage=stage,
            review_type="citation_governance",
            category=f"citation_{status}",
            affected_object_type="citation_verification",
            affected_object_id=str(row["id"]),
            summary=summary,
        )
        if existing is not None:
            return existing

        severity = (
            "critical"
            if status in {"hallucinated", "cross_topic", "not_found"}
            else "high"
        )
        issue = self._reviews.add_issue(
            topic_id=topic_id,
            stage=stage,
            review_type="citation_governance",
            severity=severity,
            category=f"citation_{status}",
            summary=summary,
            details=json.dumps(row, sort_keys=True, default=str),
            blocking=True,
            recommended_action=(
                "Resolve or remove the failed citation before advancing the gate."
            ),
            affected_object_type="citation_verification",
            affected_object_id=str(row["id"]),
        )
        return int(issue.id)

    def _ensure_gate_decision_artifact(
        self,
        *,
        topic_id: int,
        stage: str,
        decision: str,
        violations: list[InvariantViolation],
        citation_verification_ids: list[int],
        review_issue_ids: list[int],
    ) -> int:
        dedupe_key = _gate_dedupe_key(stage, decision, violations)
        existing = self._find_active_gate_decision(topic_id, stage, dedupe_key)
        if existing is not None:
            return existing

        payload = {
            "object_type": "gate_decision",
            "schema_version": SCHEMA_VERSION,
            "stage": stage,
            "decision": decision,
            "action": "block",
            "reason_codes": _unique(v.check for v in violations),
            "dedupe_key": dedupe_key,
            "violations": [v.to_dict() for v in violations],
            "citation_verification_ids": citation_verification_ids,
            "review_issue_ids": review_issue_ids,
        }
        artifact = self._artifacts.record(
            topic_id=topic_id,
            stage=stage,
            artifact_type="gate_decision",
            title=f"Gate Decision: {stage}",
            payload=payload,
            metadata={
                "schema_version": SCHEMA_VERSION,
                "decision": decision,
                "dedupe_key": dedupe_key,
            },
        )
        return int(artifact.id)

    def _ensure_citation_state_gate_decision_artifact(
        self,
        *,
        topic_id: int,
        stage: str,
        decision: str,
        reason_codes: list[str],
        citation_rows: list[dict[str, Any]],
        citation_verification_ids: list[int],
        review_issue_ids: list[int],
    ) -> int:
        dedupe_key = _citation_state_dedupe_key(
            stage,
            decision,
            reason_codes,
            citation_rows,
        )
        existing = self._find_active_gate_decision(topic_id, stage, dedupe_key)
        if existing is not None:
            return existing

        payload = {
            "object_type": "gate_decision",
            "schema_version": SCHEMA_VERSION,
            "stage": stage,
            "decision": decision,
            "action": "block",
            "reason_codes": reason_codes,
            "dedupe_key": dedupe_key,
            "violations": [],
            "citation_verifications": citation_rows,
            "citation_verification_ids": citation_verification_ids,
            "review_issue_ids": review_issue_ids,
        }
        artifact = self._artifacts.record(
            topic_id=topic_id,
            stage=stage,
            artifact_type="gate_decision",
            title=f"Gate Decision: {stage}",
            payload=payload,
            metadata={
                "schema_version": SCHEMA_VERSION,
                "decision": decision,
                "dedupe_key": dedupe_key,
            },
        )
        return int(artifact.id)

    def _find_active_gate_decision(
        self,
        topic_id: int,
        stage: str,
        dedupe_key: str,
    ) -> int | None:
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT id, payload_json
                FROM project_artifacts
                WHERE topic_id = ?
                  AND stage = ?
                  AND artifact_type = 'gate_decision'
                  AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id, stage),
            ).fetchone()
            if row is None:
                return None
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, ValueError):
                return None
            if payload.get("dedupe_key") != dedupe_key:
                return None
            return int(row["id"])
        finally:
            conn.close()

    def _ensure_rollback_event_artifact(
        self,
        *,
        topic_id: int,
        stage: str,
        decision: str,
        violations: list[InvariantViolation],
        gate_decision_artifact_id: int,
        review_issue_ids: list[int],
    ) -> int | None:
        stale_violations = [
            v for v in violations if v.check in ROLLBACK_EVENT_INVARIANT_CHECKS
        ]
        if not stale_violations:
            return None

        dedupe_key = _rollback_event_dedupe_key(stage, decision, stale_violations)
        existing = self._find_active_artifact_by_dedupe_key(
            topic_id=topic_id,
            stage=stage,
            artifact_type="rollback_event",
            dedupe_key=dedupe_key,
        )
        if existing is not None:
            return existing

        affected_ids = sorted(
            {int(v.artifact_id) for v in stale_violations if v.artifact_id}
        )
        trigger_ids = _unique_ints(
            artifact_id
            for violation in stale_violations
            for artifact_id in _stale_trigger_artifact_ids(violation)
        )
        if not trigger_ids:
            trigger_ids = affected_ids

        payload = {
            "object_type": "rollback_event",
            "schema_version": ROLLBACK_EVENT_SCHEMA_VERSION,
            "stage": stage,
            "decision": decision,
            "action": "block",
            "reason_codes": _unique(v.check for v in stale_violations),
            "dedupe_key": dedupe_key,
            "trigger_artifact_ids": trigger_ids,
            "affected_artifact_ids": affected_ids,
            "rollback_cone": {
                "trigger_artifact_ids": trigger_ids,
                "affected_artifact_ids": affected_ids,
                "preserved_artifact_ids": [],
            },
            "gate_decision_artifact_id": gate_decision_artifact_id,
            "review_issue_ids": review_issue_ids,
            "violations": [v.to_dict() for v in stale_violations],
        }
        artifact = self._artifacts.record(
            topic_id=topic_id,
            stage=stage,
            artifact_type="rollback_event",
            title=f"Rollback Event: {stage}",
            payload=payload,
            metadata={
                "schema_version": ROLLBACK_EVENT_SCHEMA_VERSION,
                "decision": decision,
                "dedupe_key": dedupe_key,
            },
        )
        return int(artifact.id)

    def _find_active_artifact_by_dedupe_key(
        self,
        *,
        topic_id: int,
        stage: str,
        artifact_type: str,
        dedupe_key: str,
    ) -> int | None:
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT id, payload_json
                FROM project_artifacts
                WHERE topic_id = ?
                  AND stage = ?
                  AND artifact_type = ?
                  AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id, stage, artifact_type),
            ).fetchone()
            if row is None:
                return None
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, ValueError):
                return None
            if payload.get("dedupe_key") != dedupe_key:
                return None
            return int(row["id"])
        finally:
            conn.close()


def _candidate_doi(candidate: dict[str, Any]) -> str:
    doi = candidate.get("doi")
    if doi:
        return str(doi)
    identifier = str(candidate.get("identifier") or "")
    if identifier.lower().startswith("doi:"):
        return identifier.split(":", 1)[1]
    return ""


def _issue_fields(violation: InvariantViolation) -> dict[str, str]:
    if violation.check == "unsupported_evidence_link":
        metadata = violation.metadata
        affected_id = str(
            metadata.get("link_key")
            or f"{metadata.get('claim_id', '')}:{metadata.get('source_id', '')}"
        )
        return {
            "review_type": "citation_governance",
            "category": "unsupported_evidence_link",
            "affected_object_type": "evidence_link",
            "affected_object_id": affected_id,
            "recommended_action": (
                "Replace the citation with a supported evidence link, "
                "downgrade the claim, or remove the unsupported claim."
            ),
        }

    return {
        "review_type": "gate_invariant",
        "category": violation.check,
        "affected_object_type": "project_artifact",
        "affected_object_id": str(violation.artifact_id or ""),
        "recommended_action": "Resolve the blocking invariant before advancing.",
    }


def _gate_dedupe_key(
    stage: str,
    decision: str,
    violations: list[InvariantViolation],
) -> str:
    payload = {
        "stage": stage,
        "decision": decision,
        "violations": [
            {
                "check": v.check,
                "artifact_id": v.artifact_id,
                "metadata": v.metadata,
                "message": v.message,
            }
            for v in violations
        ],
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _citation_state_dedupe_key(
    stage: str,
    decision: str,
    reason_codes: list[str],
    citation_rows: list[dict[str, Any]],
) -> str:
    payload = {
        "stage": stage,
        "decision": decision,
        "reason_codes": reason_codes,
        "citation_rows": [
            {
                "id": row.get("id"),
                "status": row.get("status"),
                "title": row.get("title"),
                "source": row.get("source"),
            }
            for row in citation_rows
        ],
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _rollback_event_dedupe_key(
    stage: str,
    decision: str,
    violations: list[InvariantViolation],
) -> str:
    payload = {
        "stage": stage,
        "decision": decision,
        "violations": [
            {
                "check": v.check,
                "artifact_id": v.artifact_id,
                "metadata": v.metadata,
                "message": v.message,
            }
            for v in violations
        ],
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stale_trigger_artifact_ids(violation: InvariantViolation) -> list[int]:
    reason = str(violation.metadata.get("stale_reason") or "")
    ids = [int(match) for match in re.findall(r"upstream artifact #(\d+)", reason)]
    return ids


def _unique_ints(values) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        item = int(value)
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
