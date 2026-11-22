from __future__ import annotations

import json
import os
from typing import Any

from research_harness.cli import main
from research_harness.storage.db import Database


def _db_from_runner_env() -> Database:
    db_path = os.environ["RESEARCH_HUB_DB_PATH"]
    db = Database(db_path)
    db.migrate()
    return db


def _seed_cross_topic_pair(conn) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'audit topic')")
    conn.execute("INSERT INTO topics (id, name) VALUES (2, 'literature topic')")
    conn.execute(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
        VALUES
            (1, 'Audit Checkpoints', '10.test/audit', '2601.02001', 's2_audit'),
            (2, 'Literature Agents', '10.test/lit', '2601.02002', 's2_lit')
        """
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 2, 'high')"
    )
    conn.execute(
        """
        INSERT INTO normalized_claims
            (id, topic_id, paper_id, claim_text, method, dataset, metric, task,
             value, direction, confidence, source_section, evidence_spans_json)
        VALUES
            (1, 1, 1, 'Source-hash checkpoints reduce audit drift',
             'source-hash checkpoint ledger', 'audit ledgers',
             'trace consistency', 'financial audit automation', '+1',
             'higher', 0.84, 'results',
             '[{"section":"results","text":"source hashes bind audit steps"}]')
        """
    )
    conn.execute(
        """
        INSERT INTO gaps
            (id, topic_id, description, gap_type, severity, related_paper_ids,
             focus, confidence, cross_verified, cross_check_runs)
        VALUES
            (1, 2, 'Evidence provenance drift in long literature agent runs',
             'evidence_gap', 'high', '[2]', '', 0.67, 0, 0)
        """
    )
    conn.commit()


def _artifact_count(conn) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM project_artifacts
        WHERE artifact_type = 'topic_knowledge_snapshot'
        """
    ).fetchone()
    return int(row["count"])


def test_cross_topic_atlas_cli_outputs_public_safe_json_without_writes(runner):
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    db = _db_from_runner_env()
    conn = db.connect()
    try:
        _seed_cross_topic_pair(conn)
        build_topic_knowledge_snapshot(db, topic_id=1)
        build_topic_knowledge_snapshot(db, topic_id=2)
        before_count = _artifact_count(conn)

        result = runner.invoke(
            main,
            [
                "topic",
                "cross-topic-atlas",
                "--topic-id",
                "1",
                "--topic-id",
                "2",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        assert _artifact_count(conn) == before_count
    finally:
        conn.close()

    payload = json.loads(result.output)
    assert payload["schema_version"] == "cross_topic_knowledge_atlas.v1"
    assert payload["topic_ids"] == [1, 2]
    assert payload["link_count"] > 0
    assert payload["links"][0]["link_type"] == "method_transfers_to_gap"
    assert payload["links"][0]["source_topic_id"] == 1
    assert payload["links"][0]["target_topic_id"] == 2

    encoded = json.dumps(payload, sort_keys=True)
    for fragment in (
        ".research-harness",
        "SELECT ",
        "hidden_gold",
        "vendor_request",
        "OPENAI_API_KEY",
        "RESEARCH_HUB_DB_PATH",
        "paper_ingest",
    ):
        assert fragment not in encoded


def test_cross_topic_atlas_cli_supports_query_ranking(runner):
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    db = _db_from_runner_env()
    conn = db.connect()
    try:
        _seed_cross_topic_pair(conn)
        build_topic_knowledge_snapshot(db, topic_id=1)
        build_topic_knowledge_snapshot(db, topic_id=2)

        result = runner.invoke(
            main,
            [
                "topic",
                "cross-topic-atlas",
                "--topic-id",
                "1",
                "--topic-id",
                "2",
                "--query",
                "provenance drift",
                "--max-results",
                "1",
                "--json",
            ],
        )
    finally:
        conn.close()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["query"] == "provenance drift"
    assert payload["link_count"] == 1
    assert "provenance" in json.dumps(payload["links"][0], sort_keys=True).lower()


def test_cross_topic_atlas_cli_invokes_service(runner, monkeypatch):
    from research_harness import cli_topic_knowledge
    from research_harness.service.types import ServiceResult

    calls: list[dict[str, Any]] = []

    class FakeService:
        def __init__(self, *, db):
            calls.append({"db": db})

        def invoke(self, command_name: str, arguments: dict[str, Any]) -> ServiceResult:
            calls.append({"command_name": command_name, "arguments": arguments})
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={
                    "schema_version": "cross_topic_knowledge_atlas.v1",
                    "topic_ids": arguments["topic_ids"],
                    "query": arguments["query"],
                    "link_count": 0,
                    "links": [],
                    "warnings": [],
                },
            )

    monkeypatch.setattr(cli_topic_knowledge, "ResearchService", FakeService)

    result = runner.invoke(
        main,
        [
            "topic",
            "cross-topic-atlas",
            "--topic-id",
            "3",
            "--topic-id",
            "3",
            "--topic-id",
            "4",
            "--query",
            "  provenance audit  ",
            "--max-results",
            "7",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls[1] == {
        "command_name": "cross_topic_atlas",
        "arguments": {
            "topic_ids": [3, 4],
            "query": "provenance audit",
            "max_results": 7,
        },
    }
    assert json.loads(result.output)["topic_ids"] == [3, 4]


def test_cross_topic_atlas_cli_returns_json_error_for_missing_snapshot(runner):
    db = _db_from_runner_env()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'one')")
        conn.execute("INSERT INTO topics (id, name) VALUES (2, 'two')")
        conn.commit()

        result = runner.invoke(
            main,
            [
                "topic",
                "cross-topic-atlas",
                "--topic-id",
                "1",
                "--topic-id",
                "2",
                "--json",
            ],
        )
    finally:
        conn.close()

    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "error": {
            "code": "cross_topic_atlas_unavailable",
            "message": "cross-topic atlas is unavailable for topic ids: 1, 2",
        }
    }
    assert ".research-harness" not in result.output
    assert "SELECT " not in result.output


def test_cross_topic_atlas_cli_validates_topic_ids_as_json(runner):
    invalid = runner.invoke(
        main,
        [
            "topic",
            "cross-topic-atlas",
            "--topic-id",
            "0",
            "--topic-id",
            "2",
            "--json",
        ],
    )
    duplicate = runner.invoke(
        main,
        [
            "topic",
            "cross-topic-atlas",
            "--topic-id",
            "2",
            "--topic-id",
            "2",
            "--json",
        ],
    )

    assert invalid.exit_code == 2
    assert json.loads(invalid.output) == {
        "error": {
            "code": "invalid_topic_id",
            "message": "topic_id must be a positive integer",
        }
    }
    assert duplicate.exit_code == 2
    assert json.loads(duplicate.output) == {
        "error": {
            "code": "invalid_topic_ids",
            "message": "at least two distinct topic ids are required",
        }
    }


def test_cross_topic_atlas_cli_rejects_excessive_max_results(runner):
    result = runner.invoke(
        main,
        [
            "topic",
            "cross-topic-atlas",
            "--topic-id",
            "1",
            "--topic-id",
            "2",
            "--max-results",
            "21",
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "error": {
            "code": "invalid_max_results",
            "message": "max_results must be between 1 and 20",
        }
    }
