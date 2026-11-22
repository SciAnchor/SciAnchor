from __future__ import annotations

import json

from paperindex.cards.schema import PaperCard
from research_harness.storage.db import Database


def _seed_topic(conn) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'snapshot topic')")
    conn.execute(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
        VALUES (1, 'Snapshot Paper', '10.test/snapshot', '2501.01010', 's2_snapshot')
        """
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
    )
    conn.execute(
        """
        INSERT INTO normalized_claims
            (id, topic_id, paper_id, claim_text, method, dataset, metric, task,
             value, direction, confidence, evidence_spans_json)
        VALUES
            (1, 1, 1, 'Reranker improves recall', 'Reranker', 'ORB',
             'recall@20', 'paper retrieval', '+7', 'higher', 0.82,
             '[{"section":"results","text":"recall improves"}]')
        """
    )
    conn.commit()


def test_build_topic_knowledge_snapshot_writes_private_artifact_and_read_model(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    _seed_topic(conn)

    result = build_topic_knowledge_snapshot(db, topic_id=1)

    artifact = conn.execute(
        "SELECT * FROM project_artifacts WHERE id = ?", (result.artifact_id,)
    ).fetchone()
    assert artifact["artifact_type"] == "topic_knowledge_snapshot"
    assert artifact["status"] == "active"
    assert artifact["stale"] == 0
    payload = json.loads(artifact["payload_json"])
    assert payload["schema_version"] == "topic_knowledge_snapshot.v1"
    assert payload["topic_id"] == 1
    assert payload["source_hash"] == result.source_hash
    assert payload["coverage"]["normalized_claims"] == 1
    assert "paper_summarize" in payload["next_actions"]

    snapshot = conn.execute(
        "SELECT * FROM topic_knowledge_snapshots WHERE artifact_id = ?",
        (result.artifact_id,),
    ).fetchone()
    assert snapshot["status"] == "active"
    assert snapshot["source_hash"] == result.source_hash
    assert json.loads(snapshot["coverage_json"])["semantic_atoms"] >= 1
    assert conn.execute("SELECT COUNT(*) FROM semantic_atoms").fetchone()[0] >= 1
    assert conn.execute("SELECT COUNT(*) FROM semantic_edges").fetchone()[0] >= 1


def test_build_topic_knowledge_snapshot_is_idempotent_for_same_source_hash(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    _seed_topic(conn)

    first = build_topic_knowledge_snapshot(db, topic_id=1)
    second = build_topic_knowledge_snapshot(db, topic_id=1)

    assert second.artifact_id == first.artifact_id
    assert second.snapshot_id == first.snapshot_id
    assert second.source_hash == first.source_hash
    assert (
        conn.execute(
            """
            SELECT COUNT(*)
            FROM topic_knowledge_snapshots
            WHERE topic_id = 1 AND status = 'active'
            """
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            """
            SELECT COUNT(*)
            FROM project_artifacts
            WHERE topic_id = 1 AND artifact_type = 'topic_knowledge_snapshot'
            """
        ).fetchone()[0]
        == 1
    )


def test_build_topic_knowledge_snapshot_marks_changed_sources_stale(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    _seed_topic(conn)
    first = build_topic_knowledge_snapshot(db, topic_id=1)

    conn.execute(
        "UPDATE normalized_claims SET claim_text = 'Changed claim' WHERE id = 1"
    )
    conn.commit()

    second = build_topic_knowledge_snapshot(db, topic_id=1)

    assert second.artifact_id != first.artifact_id
    assert second.source_hash != first.source_hash
    old_snapshot = conn.execute(
        "SELECT status FROM topic_knowledge_snapshots WHERE id = ?",
        (first.snapshot_id,),
    ).fetchone()
    old_artifact = conn.execute(
        "SELECT status, stale, stale_reason FROM project_artifacts WHERE id = ?",
        (first.artifact_id,),
    ).fetchone()
    assert old_snapshot["status"] == "stale"
    assert old_artifact["status"] == "stale"
    assert old_artifact["stale"] == 1
    assert "sources changed" in old_artifact["stale_reason"]


def test_build_topic_knowledge_snapshot_supersedes_same_source_old_version(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    _seed_topic(conn)
    first = build_topic_knowledge_snapshot(
        db, topic_id=1, snapshot_version="topic_knowledge_v1"
    )
    second = build_topic_knowledge_snapshot(
        db, topic_id=1, snapshot_version="topic_knowledge_v1_1"
    )

    assert second.artifact_id != first.artifact_id
    assert second.source_hash == first.source_hash
    old_snapshot = conn.execute(
        "SELECT status FROM topic_knowledge_snapshots WHERE id = ?",
        (first.snapshot_id,),
    ).fetchone()
    old_artifact = conn.execute(
        "SELECT status, stale, stale_reason FROM project_artifacts WHERE id = ?",
        (first.artifact_id,),
    ).fetchone()
    assert old_snapshot["status"] == "superseded"
    assert old_artifact["status"] == "superseded"
    assert old_artifact["stale"] == 1
    assert "superseded" in old_artifact["stale_reason"]


def test_build_topic_knowledge_snapshot_reuses_existing_snapshot_when_sources_revert(
    db: Database,
    conn,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    _seed_topic(conn)
    original = build_topic_knowledge_snapshot(db, topic_id=1)

    conn.execute(
        "UPDATE normalized_claims SET claim_text = 'Changed claim' WHERE id = 1"
    )
    conn.commit()
    changed = build_topic_knowledge_snapshot(db, topic_id=1)

    conn.execute(
        "UPDATE normalized_claims SET claim_text = 'Reranker improves recall' WHERE id = 1"
    )
    conn.commit()
    reverted = build_topic_knowledge_snapshot(db, topic_id=1)

    assert reverted.artifact_id == original.artifact_id
    assert reverted.snapshot_id == original.snapshot_id
    assert reverted.source_hash == original.source_hash
    assert reverted.reused is True

    original_snapshot = conn.execute(
        "SELECT status FROM topic_knowledge_snapshots WHERE id = ?",
        (original.snapshot_id,),
    ).fetchone()
    changed_snapshot = conn.execute(
        "SELECT status FROM topic_knowledge_snapshots WHERE id = ?",
        (changed.snapshot_id,),
    ).fetchone()
    original_artifact = conn.execute(
        "SELECT status, stale, stale_reason FROM project_artifacts WHERE id = ?",
        (original.artifact_id,),
    ).fetchone()
    assert original_snapshot["status"] == "active"
    assert changed_snapshot["status"] == "stale"
    assert original_artifact["status"] == "active"
    assert original_artifact["stale"] == 0
    assert original_artifact["stale_reason"] is None


def test_build_topic_knowledge_snapshot_tracks_empty_card_sources(
    db: Database,
    conn,
    tmp_path,
) -> None:
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    card_path = tmp_path / "empty-card.json"
    card_path.write_text(
        json.dumps(PaperCard(paper_id="1", title="Empty Card").to_dict()),
        encoding="utf-8",
    )
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'empty card topic')")
    conn.execute(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
        VALUES (1, 'Empty Card Paper', '10.test/empty-card', '2501.03030',
                's2_empty_card')
        """
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
    )
    conn.execute(
        """
        INSERT INTO paper_artifacts (id, paper_id, artifact_type, path, metadata)
        VALUES (1, 1, 'paperindex_card', ?, '{}')
        """,
        (str(card_path),),
    )
    conn.commit()

    first = build_topic_knowledge_snapshot(db, topic_id=1)

    manifest = first.payload["source_manifest"]
    assert manifest["paper_ids"] == [1]
    card_source = next(
        source
        for source in manifest["sources"]
        if source["source_type"] == "paperindex_card"
    )
    assert card_source["paper_id"] == 1
    assert card_source["atom_count"] == 0

    card_path.write_text(
        json.dumps(PaperCard(paper_id="1", title="Retitled Empty Card").to_dict()),
        encoding="utf-8",
    )
    second = build_topic_knowledge_snapshot(db, topic_id=1)

    assert second.source_hash != first.source_hash
    old_snapshot = conn.execute(
        "SELECT status FROM topic_knowledge_snapshots WHERE id = ?",
        (first.snapshot_id,),
    ).fetchone()
    assert old_snapshot["status"] == "stale"
