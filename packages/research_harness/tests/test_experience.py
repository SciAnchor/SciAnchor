"""Tests for V2 ExperienceRecord + ExperienceStore (unified experience pipeline)."""

from __future__ import annotations


import pytest

from research_harness.evolution.topic.experience import (
    ExperienceRecord,
    ExperienceStore,
    SOURCE_KINDS,
)
from research_harness.evolution.topic.store import DBLessonStore
from research_harness.orchestrator.artifacts import ArtifactManager


class TestExperienceRecord:
    def test_defaults(self):
        rec = ExperienceRecord(source_kind="human_edit", stage="section_draft")
        assert rec.id == 0
        assert rec.source_kind == "human_edit"
        assert rec.stage == "section_draft"
        assert rec.section == ""
        assert rec.before_text == ""
        assert rec.after_text == ""
        assert rec.diff_summary == ""
        assert rec.quality_delta == 0.0
        assert rec.topic_id is None
        assert rec.paper_id is None
        assert rec.metadata == {}
        assert rec.gate_verdict == "pending"
        assert rec.gate_score is None
        assert rec.lesson_id is None

    def test_all_source_kinds(self):
        for kind in SOURCE_KINDS:
            rec = ExperienceRecord(source_kind=kind, stage="build")
            assert rec.source_kind == kind

    def test_invalid_source_kind_rejected(self):
        with pytest.raises(ValueError, match="source_kind"):
            ExperienceRecord(source_kind="unknown_type", stage="build")

    def test_metadata_dict(self):
        rec = ExperienceRecord(
            source_kind="self_review",
            stage="section_draft",
            metadata={"check_name": "word_count", "threshold": 3000},
        )
        assert rec.metadata["check_name"] == "word_count"


class TestExperienceStore:
    def test_ingest_returns_id(self, db):
        store = ExperienceStore(db)
        rec = ExperienceRecord(
            source_kind="human_edit",
            stage="section_draft",
            section="introduction",
            before_text="Draft v1",
            after_text="Draft v2",
            diff_summary="Added motivation paragraph",
            topic_id=1,
        )
        record_id = store.ingest(rec)
        assert isinstance(record_id, int)
        assert record_id > 0

    def test_ingest_bridges_to_v1_lessons(self, db):
        store = ExperienceStore(db)
        lesson_store = DBLessonStore(db)
        initial_count = lesson_store.count()

        rec = ExperienceRecord(
            source_kind="self_review",
            stage="section_draft",
            section="method",
            diff_summary="Fixed overclaiming in method section",
            topic_id=1,
        )
        record_id = store.ingest(rec)
        assert lesson_store.count() == initial_count + 1

        # Verify bridged lesson content
        retrieved = store.get(record_id)
        assert retrieved is not None
        assert retrieved.lesson_id is not None
        assert retrieved.lesson_id > 0

    def test_ingest_stores_all_fields(self, db):
        store = ExperienceStore(db)
        rec = ExperienceRecord(
            source_kind="gold_comparison",
            stage="section_draft",
            section="experiments",
            before_text="System draft text",
            after_text="Gold standard text",
            diff_summary="Gold paper has better ablation structure",
            quality_delta=0.35,
            topic_id=2,
            paper_id=42,
            metadata={"gold_paper_id": 99, "venue": "NeurIPS"},
        )
        record_id = store.ingest(rec)
        retrieved = store.get(record_id)

        assert retrieved.source_kind == "gold_comparison"
        assert retrieved.section == "experiments"
        assert retrieved.before_text == "System draft text"
        assert retrieved.after_text == "Gold standard text"
        assert retrieved.quality_delta == pytest.approx(0.35)
        assert retrieved.topic_id == 2
        assert retrieved.paper_id == 42
        assert retrieved.metadata["gold_paper_id"] == 99

    def test_query_by_topic(self, db):
        store = ExperienceStore(db)
        store.ingest(
            ExperienceRecord(source_kind="human_edit", stage="build", topic_id=1)
        )
        store.ingest(
            ExperienceRecord(source_kind="human_edit", stage="build", topic_id=2)
        )
        store.ingest(
            ExperienceRecord(source_kind="self_review", stage="build", topic_id=1)
        )

        results = store.query(topic_id=1)
        assert len(results) == 2

    def test_query_by_source_kind(self, db):
        store = ExperienceStore(db)
        store.ingest(
            ExperienceRecord(source_kind="human_edit", stage="build", topic_id=1)
        )
        store.ingest(
            ExperienceRecord(source_kind="self_review", stage="build", topic_id=1)
        )
        store.ingest(
            ExperienceRecord(source_kind="self_review", stage="analyze", topic_id=1)
        )

        results = store.query(source_kind="self_review")
        assert len(results) == 2

    def test_query_by_stage(self, db):
        store = ExperienceStore(db)
        store.ingest(ExperienceRecord(source_kind="human_edit", stage="build"))
        store.ingest(ExperienceRecord(source_kind="human_edit", stage="analyze"))

        results = store.query(stage="build")
        assert len(results) == 1

    def test_query_limit(self, db):
        store = ExperienceStore(db)
        for i in range(10):
            store.ingest(ExperienceRecord(source_kind="auto_extracted", stage="build"))

        results = store.query(limit=3)
        assert len(results) == 3

    def test_query_combined_filters(self, db):
        store = ExperienceStore(db)
        store.ingest(
            ExperienceRecord(source_kind="self_review", stage="build", topic_id=1)
        )
        store.ingest(
            ExperienceRecord(source_kind="self_review", stage="analyze", topic_id=1)
        )
        store.ingest(
            ExperienceRecord(source_kind="human_edit", stage="build", topic_id=1)
        )
        store.ingest(
            ExperienceRecord(source_kind="self_review", stage="build", topic_id=2)
        )

        results = store.query(topic_id=1, source_kind="self_review", stage="build")
        assert len(results) == 1

    def test_count_all(self, db):
        store = ExperienceStore(db)
        assert store.count() == 0
        store.ingest(ExperienceRecord(source_kind="human_edit", stage="build"))
        store.ingest(ExperienceRecord(source_kind="self_review", stage="build"))
        assert store.count() == 2

    def test_count_by_source_kind(self, db):
        store = ExperienceStore(db)
        store.ingest(ExperienceRecord(source_kind="human_edit", stage="build"))
        store.ingest(ExperienceRecord(source_kind="self_review", stage="build"))
        store.ingest(ExperienceRecord(source_kind="self_review", stage="analyze"))
        assert store.count(source_kind="self_review") == 2
        assert store.count(source_kind="human_edit") == 1

    def test_count_by_topic(self, db):
        store = ExperienceStore(db)
        store.ingest(
            ExperienceRecord(source_kind="human_edit", stage="build", topic_id=1)
        )
        store.ingest(
            ExperienceRecord(source_kind="human_edit", stage="build", topic_id=2)
        )
        assert store.count(topic_id=1) == 1

    def test_update_gate_verdict(self, db):
        store = ExperienceStore(db)
        record_id = store.ingest(
            ExperienceRecord(source_kind="human_edit", stage="build")
        )
        store.update_gate(record_id, verdict="accepted", score=0.85)

        retrieved = store.get(record_id)
        assert retrieved.gate_verdict == "accepted"
        assert retrieved.gate_score == pytest.approx(0.85)

    def test_get_nonexistent_returns_none(self, db):
        store = ExperienceStore(db)
        assert store.get(9999) is None

    def test_auto_extracted_source_maps_correctly(self, db):
        """auto_extracted records should bridge to lessons with lesson_type='observation'."""
        store = ExperienceStore(db)
        lesson_store = DBLessonStore(db)

        rec = ExperienceRecord(
            source_kind="auto_extracted",
            stage="build",
            diff_summary="CrossRef returns more results than S2 for this query",
        )
        store.ingest(rec)

        lessons = lesson_store.query(stage="build", top_k=1)
        assert len(lessons) == 1
        assert lessons[0].lesson_type == "observation"

    def test_syncs_three_state_ablation_memory_with_provenance(self, db):
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (id, name) VALUES (1, 'ablation-memory')")
            conn.commit()
        finally:
            conn.close()

        ArtifactManager(db).record(
            topic_id=1,
            stage="experiment",
            artifact_type="experiment_result",
            title="Final ablations",
            payload={
                "canonical_components": ["retriever", "reranker", "router"],
                "ablation_components": ["retriever", "reranker", "router"],
                "repeats": 3,
                "variance_estimates": [0.01, 0.02, 0.03],
                "acceptance_criteria": [],
                "evidence_kind": "final",
                "component_provenance": [
                    {
                        "component_family": "retriever",
                        "provenance_tag": "borrowed",
                        "source_paper_id": 11,
                    },
                    {
                        "component_family": "reranker",
                        "provenance_tag": "modified",
                        "source_paper_id": 12,
                    },
                    {
                        "component_family": "router",
                        "provenance_tag": "novel",
                        "source_paper_id": None,
                    },
                ],
                "metric_direction": "maximize",
                "ablation_outcomes": [
                    {
                        "component_family": "retriever",
                        "removal_effect": "helped",
                        "provenance_tag": "borrowed",
                        "source_paper_id": 11,
                        "evidence": "observed accuracy rose by 0.02",
                    },
                    {
                        "component_family": "reranker",
                        "removal_effect": "hurt",
                        "provenance_tag": "modified",
                        "source_paper_id": 12,
                        "evidence": "observed accuracy fell by 0.04",
                    },
                    {
                        "component_family": "router",
                        "removal_effect": "inconclusive",
                        "provenance_tag": "novel",
                        "source_paper_id": None,
                        "evidence": "observed effect stayed within run variance",
                    },
                ],
            },
        )

        store = ExperienceStore(db)
        assert store.sync_ablation_memory(1) == 3
        assert store.sync_ablation_memory(1) == 0

        records = store.query(
            topic_id=1,
            source_kind="auto_extracted",
            stage="algorithm_candidate_generate",
        )
        by_family = {record.metadata["component_family"]: record for record in records}
        assert by_family["retriever"].metadata["interpretation"] == (
            "risky_or_redundant"
        )
        assert by_family["reranker"].metadata["interpretation"] == "beneficial"
        assert by_family["router"].metadata["interpretation"] == "inconclusive"
        assert by_family["retriever"].metadata["provenance_tag"] == "borrowed"
        assert by_family["retriever"].metadata["source_paper_id"] == 11
        assert by_family["router"].paper_id is None

    def test_ablation_memory_rejects_malformed_and_stays_topic_scoped(self, db):
        conn = db.connect()
        try:
            conn.executemany(
                "INSERT INTO topics (id, name) VALUES (?, ?)",
                [(1, "topic-one"), (2, "topic-two")],
            )
            conn.commit()
        finally:
            conn.close()

        base_payload = {
            "canonical_components": ["retriever"],
            "ablation_components": ["retriever"],
            "repeats": 2,
            "variance_estimates": [0.01],
            "acceptance_criteria": [],
            "evidence_kind": "final",
            "metric_direction": "maximize",
        }
        ArtifactManager(db).record(
            topic_id=1,
            stage="experiment",
            artifact_type="experiment_result",
            payload={
                **base_payload,
                "component_provenance": [
                    {
                        "component_family": "retriever",
                        "provenance_tag": "borrowed",
                        "source_paper_id": None,
                    }
                ],
                "ablation_outcomes": [
                    {
                        "component_family": "retriever",
                        "removal_effect": "helped",
                        "provenance_tag": "borrowed",
                        "source_paper_id": None,
                    }
                ],
            },
        )
        ArtifactManager(db).record(
            topic_id=2,
            stage="experiment",
            artifact_type="experiment_result",
            payload={
                **base_payload,
                "component_provenance": [
                    {
                        "component_family": "retriever",
                        "provenance_tag": "novel",
                        "source_paper_id": None,
                    }
                ],
                "ablation_outcomes": [
                    {
                        "component_family": "retriever",
                        "removal_effect": "hurt",
                        "provenance_tag": "novel",
                        "source_paper_id": None,
                        "evidence": "observed accuracy fell by 0.03",
                    }
                ],
            },
        )

        store = ExperienceStore(db)
        assert store.sync_ablation_memory(1) == 0
        assert store.sync_ablation_memory(2) == 1
        overlay = store.build_ablation_memory_overlay(2)
        assert "beneficial" in overlay
        assert "risky_or_redundant" not in overlay
        assert "provenance=novel" in overlay
        assert "must not dominate scoring" in overlay

    @pytest.mark.parametrize("invalidated_as", ["superseded", "stale"])
    def test_ablation_overlay_ignores_invalidated_or_malformed_memory(
        self, db, invalidated_as
    ):
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (id, name) VALUES (1, 'memory-history')")
            conn.commit()
        finally:
            conn.close()

        payload = {
            "canonical_components": ["router"],
            "ablation_components": ["router"],
            "repeats": 2,
            "variance_estimates": [0.01],
            "acceptance_criteria": [],
            "evidence_kind": "final",
            "component_provenance": [
                {
                    "component_family": "router",
                    "provenance_tag": "novel",
                    "source_paper_id": None,
                }
            ],
            "metric_direction": "maximize",
            "ablation_outcomes": [
                {
                    "component_family": "router",
                    "removal_effect": "hurt",
                    "provenance_tag": "novel",
                    "source_paper_id": None,
                    "evidence": "observed old result",
                }
            ],
        }
        artifacts = ArtifactManager(db)
        artifacts.record(
            topic_id=1,
            stage="experiment",
            artifact_type="experiment_result",
            payload=payload,
        )
        store = ExperienceStore(db)
        assert store.sync_ablation_memory(1) == 1
        if invalidated_as == "superseded":
            artifacts.record(
                topic_id=1,
                stage="experiment",
                artifact_type="experiment_result",
                payload={"metrics": {"accuracy": 0.9}},
            )
        else:
            conn = db.connect()
            try:
                conn.execute(
                    "UPDATE project_artifacts SET stale = 1 WHERE topic_id = 1"
                )
                conn.commit()
            finally:
                conn.close()
        store.ingest(
            ExperienceRecord(
                source_kind="auto_extracted",
                stage="algorithm_candidate_generate",
                topic_id=1,
                metadata={"memory_kind": "ablation_symbolic"},
            )
        )

        assert store.build_ablation_memory_overlay(1) == ""
