from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from research_harness._core.storage.db import Database, MIGRATIONS_DIR


TOPIC_KNOWLEDGE_TABLES = {
    "semantic_atoms",
    "semantic_edges",
    "topic_knowledge_snapshots",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA index_list({table})")}


def _apply_migrations_before_topic_knowledge(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name.startswith("069_topic_knowledge_layer"):
                continue
            version = int(path.name.split("_", 1)[0])
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, path.stem),
            )
            conn.commit()
    finally:
        conn.close()


def _seed_canonical_rows(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'topic knowledge')")
    conn.execute(
        """
        INSERT INTO papers
            (id, title, doi, arxiv_id, s2_id, compiled_summary, compiled_from_hash)
        VALUES
            (1, 'Paper A', '10.test/tk', '2501.00001', 's2_tk', '{"methods":["M"]}', 'hash-paper')
        """
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
    )
    conn.execute(
        """
        INSERT INTO paper_artifacts (id, paper_id, artifact_type, path, metadata)
        VALUES (1, 1, 'paperindex_card', '/tmp/card.json', '{"source_hash":"card-hash"}')
        """
    )
    conn.execute(
        """
        INSERT INTO paper_annotations
            (id, paper_id, section, content, source, confidence, extractor_version)
        VALUES (1, 1, 'paper_card', 'method M on dataset D', 'test', 0.9, 'test-v1')
        """
    )
    conn.execute(
        """
        INSERT INTO normalized_claims
            (id, topic_id, paper_id, claim_text, method, dataset, metric, task, value, confidence)
        VALUES
            (1, 1, 1, 'M improves CTR on D', 'M', 'D', 'CTR', 'ad ranking', '+2%', 0.8)
        """
    )
    conn.execute(
        """
        INSERT INTO gaps
            (id, topic_id, description, gap_type, severity, focus, confidence)
        VALUES
            (1, 1, 'Missing long-horizon validation', 'evidence', 'medium', 'validation', 0.6)
        """
    )
    conn.execute(
        """
        INSERT INTO method_atoms
            (id, topic_id, source_paper_id, atom_type, name, description, reuse_risk)
        VALUES
            (1, 1, 1, 'micro_block', 'M', 'Method M', 'low')
        """
    )
    conn.commit()


def test_topic_knowledge_tables_exist_on_fresh_migration(tmp_path: Path) -> None:
    db = Database(tmp_path / "fresh-topic-knowledge.db")
    db.migrate()

    conn = db.connect()
    try:
        assert TOPIC_KNOWLEDGE_TABLES <= _table_names(conn)

        assert {
            "id",
            "topic_id",
            "atom_type",
            "normalized_key",
            "source_type",
            "source_id",
            "paper_id",
            "source_hash",
            "extractor_version",
            "metadata_json",
        } <= _column_names(conn, "semantic_atoms")
        assert {
            "id",
            "topic_id",
            "edge_type",
            "from_atom_id",
            "to_atom_id",
            "source_type",
            "source_id",
            "source_hash",
            "metadata_json",
        } <= _column_names(conn, "semantic_edges")
        assert {
            "id",
            "topic_id",
            "artifact_id",
            "status",
            "snapshot_version",
            "source_hash",
            "source_manifest_json",
            "coverage_json",
        } <= _column_names(conn, "topic_knowledge_snapshots")

        assert {
            "idx_semantic_atoms_topic_type",
            "idx_semantic_atoms_paper",
            "idx_semantic_edges_topic_type",
            "idx_topic_knowledge_snapshots_topic_status",
        } <= (
            _index_names(conn, "semantic_atoms")
            | _index_names(conn, "semantic_edges")
            | _index_names(conn, "topic_knowledge_snapshots")
        )
    finally:
        conn.close()


def test_topic_knowledge_migration_preserves_existing_canonical_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "existing-topic-knowledge.db"
    _apply_migrations_before_topic_knowledge(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        _seed_canonical_rows(conn)
    finally:
        conn.close()

    db = Database(db_path)
    db.migrate()

    conn = db.connect()
    try:
        assert TOPIC_KNOWLEDGE_TABLES <= _table_names(conn)
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM paper_artifacts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM paper_annotations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM normalized_claims").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM gaps").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM method_atoms").fetchone()[0] == 1
    finally:
        conn.close()


def test_topic_knowledge_unique_constraints_prevent_duplicate_derivations(
    db: Database,
) -> None:
    conn = db.connect()
    try:
        _seed_canonical_rows(conn)
        conn.execute(
            """
            INSERT INTO semantic_atoms
                (id, topic_id, atom_type, normalized_key, label, source_type,
                 source_id, paper_id, source_section, snippet, confidence,
                 source_hash, extractor_version)
            VALUES
                (1, 1, 'method', 'm', 'M', 'method_atoms', '1', 1,
                 'method_atoms.name', 'Method M', 0.9, 'source-hash', 'tk-v1')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO semantic_atoms
                    (topic_id, atom_type, normalized_key, label, source_type,
                     source_id, paper_id, source_section, snippet, confidence,
                     source_hash, extractor_version)
                VALUES
                    (1, 'method', 'm', 'M again', 'method_atoms', '1', 1,
                     'method_atoms.name', 'Method M', 0.9, 'source-hash', 'tk-v1')
                """
            )

        conn.execute(
            """
            INSERT INTO semantic_atoms
                (id, topic_id, atom_type, normalized_key, label, source_type,
                 source_id, paper_id, source_section, snippet, confidence,
                 source_hash, extractor_version)
            VALUES
                (2, 1, 'dataset', 'd', 'D', 'normalized_claims', '1', 1,
                 'dataset', 'Dataset D', 0.8, 'claim-hash', 'tk-v1')
            """
        )
        conn.execute(
            """
            INSERT INTO semantic_edges
                (id, topic_id, edge_type, from_atom_id, to_atom_id, source_type,
                 source_id, confidence, source_hash)
            VALUES
                (1, 1, 'uses_dataset', 1, 2, 'normalized_claims', '1', 0.8, 'edge-hash')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO semantic_edges
                    (topic_id, edge_type, from_atom_id, to_atom_id, source_type,
                     source_id, confidence, source_hash)
                VALUES
                    (1, 'uses_dataset', 1, 2, 'normalized_claims', '1', 0.8, 'edge-hash')
                """
            )

        conn.execute(
            """
            INSERT INTO project_artifacts
                (id, topic_id, stage, artifact_type, title, payload_json)
            VALUES
                (1, 1, 'analysis', 'topic_knowledge_snapshot', 'Snapshot', '{}')
            """
        )
        conn.execute(
            """
            INSERT INTO topic_knowledge_snapshots
                (id, topic_id, artifact_id, status, snapshot_version, source_hash)
            VALUES
                (1, 1, 1, 'active', 'topic_knowledge_v1', 'snapshot-hash')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO topic_knowledge_snapshots
                    (topic_id, artifact_id, status, snapshot_version, source_hash)
                VALUES
                    (1, 1, 'active', 'topic_knowledge_v1', 'snapshot-hash')
                """
            )
    finally:
        conn.close()
