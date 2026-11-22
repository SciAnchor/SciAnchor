"""V2 Self-Evolution: unified experience ingestion pipeline.

All experience sources (human_edit, self_review, gold_comparison, auto_extracted)
flow through ExperienceStore.ingest() into the experience_records table.
Each ingest also bridges to V1 DBLessonStore.append() for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .store import DBLessonStore, Lesson

logger = logging.getLogger(__name__)

SOURCE_KINDS = frozenset(
    {"human_edit", "self_review", "gold_comparison", "auto_extracted"}
)

_SOURCE_TO_LESSON_TYPE = {
    "human_edit": "tip",
    "self_review": "failure",
    "gold_comparison": "observation",
    "auto_extracted": "observation",
}

_ABLATION_MEMORY_STAGE = "algorithm_candidate_generate"
_ABLATION_INTERPRETATIONS = {
    "helped": "risky_or_redundant",
    "hurt": "beneficial",
    "inconclusive": "inconclusive",
}
_PROVENANCE_TAGS = frozenset({"borrowed", "modified", "novel"})


@dataclass
class ExperienceRecord:
    source_kind: str
    stage: str
    section: str = ""
    before_text: str = ""
    after_text: str = ""
    diff_summary: str = ""
    quality_delta: float = 0.0
    topic_id: int | None = None
    paper_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    gate_verdict: str = "pending"
    gate_score: float | None = None
    lesson_id: int | None = None
    id: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.source_kind not in SOURCE_KINDS:
            raise ValueError(
                f"source_kind must be one of {sorted(SOURCE_KINDS)}, got {self.source_kind!r}"
            )


class ExperienceStore:
    """Unified experience ingestion with V1 lesson bridge."""

    def __init__(self, db: Any, gate: Any | None = None) -> None:
        self._db = db
        self._lesson_store = DBLessonStore(db)
        self._gate = gate

    def ingest(self, record: ExperienceRecord) -> int:
        conn = self._db.connect()
        try:
            cursor = conn.execute(
                """INSERT INTO experience_records
                   (source_kind, stage, section, before_text, after_text,
                    diff_summary, quality_delta, topic_id, project_id, paper_id,
                    metadata, gate_verdict, gate_score, lesson_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.source_kind,
                    record.stage,
                    record.section,
                    record.before_text,
                    record.after_text,
                    record.diff_summary,
                    record.quality_delta,
                    record.topic_id,
                    record.topic_id,  # write topic_id to project_id column for compat
                    record.paper_id,
                    json.dumps(record.metadata, ensure_ascii=False),
                    record.gate_verdict,
                    record.gate_score,
                    None,
                ),
            )
            conn.commit()
            record_id = int(cursor.lastrowid)
        finally:
            conn.close()

        # Gate evaluation (if gate is configured)
        gate_passed = True
        if self._gate is not None:
            try:
                stored = self.get(record_id)
                if stored is not None:
                    verdict = self._gate.evaluate_tier1(stored)
                    self.update_gate(
                        record_id, verdict=verdict.verdict, score=verdict.score
                    )
                    gate_passed = verdict.verdict != "rejected"
            except Exception as exc:
                logger.debug("Gate evaluation failed for record %d: %s", record_id, exc)

        # V1 bridge: only for non-rejected records
        if gate_passed:
            try:
                lesson_id = self._bridge_to_v1(record)
                conn = self._db.connect()
                try:
                    conn.execute(
                        "UPDATE experience_records SET lesson_id = ? WHERE id = ?",
                        (lesson_id, record_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as exc:
                logger.debug("V1 bridge failed for record %d: %s", record_id, exc)

        return record_id

    def get(self, record_id: int) -> ExperienceRecord | None:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM experience_records WHERE id = ?", (record_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_record(row)
        finally:
            conn.close()

    def query(
        self,
        *,
        topic_id: int | None = None,
        source_kind: str | None = None,
        stage: str | None = None,
        gate_verdict: str | None = None,
        limit: int = 50,
    ) -> list[ExperienceRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if topic_id is not None:
            clauses.append("topic_id = ?")
            params.append(topic_id)
        if source_kind is not None:
            clauses.append("source_kind = ?")
            params.append(source_kind)
        if stage is not None:
            clauses.append("stage = ?")
            params.append(stage)
        if gate_verdict is not None:
            clauses.append("gate_verdict = ?")
            params.append(gate_verdict)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM experience_records{where} ORDER BY id DESC LIMIT ?"
        params.append(limit)

        conn = self._db.connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            conn.close()

    def count(
        self,
        *,
        topic_id: int | None = None,
        source_kind: str | None = None,
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []
        if topic_id is not None:
            clauses.append("topic_id = ?")
            params.append(topic_id)
        if source_kind is not None:
            clauses.append("source_kind = ?")
            params.append(source_kind)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = self._db.connect()
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM experience_records{where}", params
            ).fetchone()
            return int(row[0])
        finally:
            conn.close()

    def update_gate(
        self, record_id: int, *, verdict: str, score: float | None = None
    ) -> None:
        conn = self._db.connect()
        try:
            conn.execute(
                "UPDATE experience_records SET gate_verdict = ?, gate_score = ? WHERE id = ?",
                (verdict, score, record_id),
            )
            conn.commit()
        finally:
            conn.close()

    def sync_ablation_memory(self, topic_id: int) -> int:
        """Persist valid active experiment ablations as symbolic-memory priors."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT id, payload_json FROM project_artifacts
                   WHERE topic_id = ? AND artifact_type = 'experiment_result'
                     AND status = 'active' AND COALESCE(stale, 0) = 0
                   ORDER BY id""",
                (topic_id,),
            ).fetchall()
            existing_rows = conn.execute(
                """SELECT metadata FROM experience_records
                   WHERE topic_id = ? AND source_kind = 'auto_extracted'
                     AND stage = ?""",
                (topic_id, _ABLATION_MEMORY_STAGE),
            ).fetchall()
        finally:
            conn.close()

        existing = set()
        for row in existing_rows:
            try:
                metadata = json.loads(row["metadata"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if metadata.get("memory_kind") == "ablation_symbolic":
                existing.add(
                    (
                        metadata.get("source_artifact_id"),
                        metadata.get("component_family"),
                    )
                )

        created = 0
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            records = _ablation_memory_records(
                payload,
                topic_id=topic_id,
                source_artifact_id=int(row["id"]),
            )
            for record in records:
                key = (
                    record.metadata["source_artifact_id"],
                    record.metadata["component_family"],
                )
                if key in existing:
                    continue
                self.ingest(record)
                existing.add(key)
                created += 1
        return created

    def build_ablation_memory_overlay(self, topic_id: int, *, top_k: int = 20) -> str:
        """Render topic-scoped symbolic ablation memory for an ideation prompt."""
        conn = self._db.connect()
        try:
            active_artifact_ids = {
                int(row["id"])
                for row in conn.execute(
                    """SELECT id FROM project_artifacts
                       WHERE topic_id = ? AND artifact_type = 'experiment_result'
                         AND status = 'active' AND COALESCE(stale, 0) = 0""",
                    (topic_id,),
                ).fetchall()
            }
        finally:
            conn.close()
        records = self.query(
            topic_id=topic_id,
            source_kind="auto_extracted",
            stage=_ABLATION_MEMORY_STAGE,
            limit=max(top_k, 1),
        )
        records = [
            record
            for record in records
            if record.gate_verdict != "rejected"
            and record.metadata.get("memory_kind") == "ablation_symbolic"
            and record.metadata.get("source_artifact_id") in active_artifact_ids
            and all(
                key in record.metadata
                for key in (
                    "component_family",
                    "interpretation",
                    "removal_effect",
                    "provenance_tag",
                )
            )
        ]
        if not records:
            return ""

        records.sort(
            key=lambda record: (
                -int(record.metadata.get("source_artifact_id") or 0),
                int(record.metadata.get("component_index") or 0),
            )
        )
        lines = []
        for record in records[:top_k]:
            metadata = record.metadata
            source_paper_id = metadata.get("source_paper_id")
            source = "none" if source_paper_id is None else str(source_paper_id)
            family = json.dumps(str(metadata["component_family"]), ensure_ascii=False)
            lines.append(
                f"- {family}: {metadata['interpretation']} "
                f"(removal={metadata['removal_effect']}; "
                f"provenance={metadata['provenance_tag']}; "
                f"source_paper_id={source})"
            )
        lines.append(
            "Use this only as an advisory prior: current evidence and provenance "
            "constraints remain authoritative, and inconclusive evidence must not "
            "dominate scoring."
        )
        return "\n".join(lines)

    def _bridge_to_v1(self, record: ExperienceRecord) -> int:
        content = record.diff_summary or record.after_text or record.before_text
        if not content:
            content = f"[{record.source_kind}] {record.stage}/{record.section}"
        lesson = Lesson(
            stage=record.stage,
            content=content,
            lesson_type=_SOURCE_TO_LESSON_TYPE.get(record.source_kind, "observation"),
            tags=[record.source_kind, record.section]
            if record.section
            else [record.source_kind],
        )
        return self._lesson_store.append(
            lesson,
            source=f"experience_v2:{record.source_kind}",
            source_topic_id=record.topic_id,
            topic_id=record.topic_id,
        )

    @staticmethod
    def _row_to_record(row: Any) -> ExperienceRecord:
        keys = row.keys() if hasattr(row, "keys") else []
        metadata_raw = row["metadata"] if "metadata" in keys else "{}"
        try:
            metadata = json.loads(metadata_raw) if metadata_raw else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return ExperienceRecord(
            id=row["id"],
            source_kind=row["source_kind"],
            stage=row["stage"],
            section=row["section"] or "",
            before_text=row["before_text"] or "",
            after_text=row["after_text"] or "",
            diff_summary=row["diff_summary"] or "",
            quality_delta=row["quality_delta"] or 0.0,
            topic_id=row["topic_id"],
            paper_id=row["paper_id"],
            metadata=metadata,
            gate_verdict=row["gate_verdict"] or "pending",
            gate_score=row["gate_score"],
            lesson_id=row["lesson_id"],
            created_at=row["created_at"] or "",
        )


def _ablation_memory_records(
    payload: Any,
    *,
    topic_id: int,
    source_artifact_id: int,
) -> list[ExperienceRecord]:
    """Convert one complete, evidence-bound ablation payload into memories."""
    if not isinstance(payload, dict):
        return []
    from research_harness.experiment.coverage_gate import evaluate_ablation_payload

    gate = evaluate_ablation_payload(payload)
    outcomes = payload.get("ablation_outcomes")
    canonical = payload.get("canonical_components")
    if (
        gate is None
        or gate.get("verdict") != "pass"
        or not isinstance(outcomes, list)
        or not isinstance(canonical, list)
        or len(outcomes) != len(canonical)
    ):
        return []

    normalized = []
    for index, (component, outcome) in enumerate(zip(canonical, outcomes, strict=True)):
        if not isinstance(outcome, dict):
            return []
        family = outcome.get("component_family")
        effect = outcome.get("removal_effect")
        provenance = outcome.get("provenance_tag")
        source_paper_id = outcome.get("source_paper_id")
        evidence = outcome.get("evidence")
        valid_source = (provenance == "novel" and source_paper_id is None) or (
            provenance in {"borrowed", "modified"}
            and type(source_paper_id) is int
            and source_paper_id > 0
        )
        if (
            family != component
            or effect not in _ABLATION_INTERPRETATIONS
            or provenance not in _PROVENANCE_TAGS
            or not valid_source
            or not isinstance(evidence, str)
            or not evidence.strip()
        ):
            return []
        normalized.append(
            (
                index,
                family,
                effect,
                provenance,
                source_paper_id,
                evidence.strip(),
            )
        )

    records = []
    for index, family, effect, provenance, source_paper_id, evidence in normalized:
        interpretation = _ABLATION_INTERPRETATIONS[effect]
        records.append(
            ExperienceRecord(
                source_kind="auto_extracted",
                stage=_ABLATION_MEMORY_STAGE,
                section="ablation_symbolic_memory",
                diff_summary=(
                    f"Removing {family} {effect}; interpret as {interpretation}. "
                    f"Evidence: {evidence}"
                ),
                topic_id=topic_id,
                paper_id=source_paper_id,
                metadata={
                    "memory_kind": "ablation_symbolic",
                    "source_artifact_id": source_artifact_id,
                    "component_index": index,
                    "component_family": family,
                    "removal_effect": effect,
                    "interpretation": interpretation,
                    "provenance_tag": provenance,
                    "source_paper_id": source_paper_id,
                    "evidence": evidence,
                },
                gate_verdict="accepted",
            )
        )
    return records
