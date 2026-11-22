from __future__ import annotations

import json
import os

from research_harness.cli import main
from research_harness.storage.db import Database


def _db_from_runner_env() -> Database:
    db_path = os.environ["RESEARCH_HUB_DB_PATH"]
    db = Database(db_path)
    db.migrate()
    return db


def _seed_topic(conn) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'knowledge status topic')")
    conn.execute(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
        VALUES (1, 'Knowledge Status Paper', '10.test/status', '2601.01010',
                's2_status')
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
            (1, 1, 1, 'Hybrid evidence improves inspection', 'Hybrid evidence',
             'RH', 'inspection_score', 'status inspection', '+1', 'higher', 0.81,
             '[{"section":"results","text":"inspection improves"}]')
        """
    )
    conn.commit()


def _artifact_count(conn, *, topic_id: int | None = 1) -> int:
    topic_clause = "" if topic_id is None else "AND topic_id = ?"
    params = () if topic_id is None else (topic_id,)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM project_artifacts
        WHERE artifact_type = 'topic_knowledge_snapshot'
        {topic_clause}
        """,
        params,
    ).fetchone()
    return int(row["count"])


def test_topic_knowledge_refresh_cli_builds_snapshot_for_one_topic(runner):
    db = _db_from_runner_env()
    conn = db.connect()
    try:
        _seed_topic(conn)

        result = runner.invoke(
            main, ["topic", "knowledge-refresh", "--topic-id", "1", "--json"]
        )

        assert result.exit_code == 0, result.output
        assert _artifact_count(conn) == 1
    finally:
        conn.close()

    payload = json.loads(result.output)
    assert payload["status"] == "refreshed"
    assert payload["topic_id"] == 1
    assert payload["artifact_id"]
    assert payload["snapshot_id"]
    assert payload["source_hash"]
    assert payload["error"] == ""


def test_topic_knowledge_refresh_cli_refreshes_all_topics(runner):
    db = _db_from_runner_env()
    conn = db.connect()
    try:
        _seed_topic(conn)
        conn.execute("INSERT INTO topics (id, name) VALUES (2, 'second topic')")
        conn.execute(
            """
            INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
            VALUES (2, 'Second Knowledge Paper', '10.test/status-2',
                    '2601.01011', 's2_status_2')
            """
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 2, 'medium')"
        )
        conn.commit()

        result = runner.invoke(main, ["topic", "knowledge-refresh", "--all", "--json"])

        assert result.exit_code == 0, result.output
        assert _artifact_count(conn, topic_id=None) == 2
    finally:
        conn.close()

    payload = json.loads(result.output)
    assert payload["topic_count"] == 2
    assert payload["counts"]["refreshed"] == 2
    assert payload["counts"]["reused"] == 0
    assert payload["counts"]["failed"] == 0
    assert payload["counts"]["skipped"] == 0
    assert payload["failed_topic_ids"] == []
    assert [item["topic_id"] for item in payload["results"]] == [1, 2]


def test_topic_knowledge_status_cli_outputs_public_safe_json_without_writes(runner):
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    db = _db_from_runner_env()
    conn = db.connect()
    try:
        _seed_topic(conn)
        snapshot = build_topic_knowledge_snapshot(db, topic_id=1)
        before_count = _artifact_count(conn)

        result = runner.invoke(
            main, ["topic", "knowledge-status", "--topic-id", "1", "--json"]
        )

        assert result.exit_code == 0, result.output
        assert _artifact_count(conn) == before_count
    finally:
        conn.close()

    payload = json.loads(result.output)
    assert payload["schema_version"] == "knowledge_status.v1"
    assert payload["topic_id"] == 1
    assert payload["status"] == "ready"
    assert payload["snapshot"]["artifact_ref"] == (
        f"artifact:topic_knowledge_snapshot:{snapshot.artifact_id}"
    )
    assert payload["wiki"]["page_count"] > 0
    assert payload["next_actions"]

    encoded = json.dumps(payload, sort_keys=True)
    for fragment in (
        ".research-harness",
        "SELECT ",
        "hidden_gold",
        "vendor_request",
        "OPENAI_API_KEY",
        "paper_ingest",
    ):
        assert fragment not in encoded


def test_topic_knowledge_status_cli_reports_stale_snapshot_as_status(runner):
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    db = _db_from_runner_env()
    conn = db.connect()
    try:
        _seed_topic(conn)
        build_topic_knowledge_snapshot(db, topic_id=1)
        conn.execute(
            "UPDATE normalized_claims SET claim_text = 'Changed status evidence' WHERE id = 1"
        )
        conn.commit()

        result = runner.invoke(
            main, ["topic", "knowledge-status", "--topic-id", "1", "--json"]
        )
    finally:
        conn.close()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "stale"
    assert payload["readiness_status"] == "stale"
    assert payload["snapshot"]["is_current"] is False
    assert "snapshot_stale" in payload["warnings"]


def test_topic_knowledge_status_cli_returns_json_error_for_missing_snapshot(runner):
    db = _db_from_runner_env()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'missing snapshot')")
        conn.commit()

        result = runner.invoke(
            main, ["topic", "knowledge-status", "--topic-id", "1", "--json"]
        )
    finally:
        conn.close()

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload == {
        "error": {
            "code": "knowledge_status_unavailable",
            "message": "knowledge status is unavailable for topic 1",
        }
    }
    assert ".research-harness" not in result.output
    assert "SELECT " not in result.output


def test_topic_knowledge_status_cli_validates_positive_topic_id_as_json(runner):
    result = runner.invoke(
        main, ["topic", "knowledge-status", "--topic-id", "0", "--json"]
    )

    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "error": {
            "code": "invalid_topic_id",
            "message": "topic_id must be a positive integer",
        }
    }
