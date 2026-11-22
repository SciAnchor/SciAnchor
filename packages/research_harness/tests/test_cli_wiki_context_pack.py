from __future__ import annotations

import json
import os

from research_harness.cli import main
from research_harness.storage.db import Database


def _seed_topic(conn) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'wiki topic')")
    conn.execute(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
        VALUES (1, 'Wiki Paper', '10.test/wiki', '2501.02020', 's2_wiki')
        """
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
    )
    conn.execute(
        """
        INSERT INTO normalized_claims
            (id, topic_id, paper_id, claim_text, method, dataset, metric, task,
             value, direction, confidence, source_section, evidence_spans_json)
        VALUES
            (1, 1, 1, 'Reranker improves recall', 'Reranker', 'ORB',
             'recall@20', 'paper retrieval', '+7', 'higher', 0.82, 'results',
             '[{"section":"results","text":"recall improves"}]')
        """
    )
    conn.commit()


def _db_from_runner_env() -> Database:
    db_path = os.environ["RESEARCH_HUB_DB_PATH"]
    db = Database(db_path)
    db.migrate()
    return db


def test_topic_wiki_context_pack_cli_loads_context_pack(runner):
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    db = _db_from_runner_env()
    conn = db.connect()
    try:
        _seed_topic(conn)
        build_topic_knowledge_snapshot(db, topic_id=1)

        result = runner.invoke(
            main,
            [
                "topic",
                "wiki-context-pack",
                "--topic-id",
                "1",
                "--query",
                "reranker recall",
                "--action-name",
                "experiment_design",
                "--json",
            ],
        )
    finally:
        conn.close()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["paper_wiki_status"] == "loaded"
    assert payload["schema_version"] == "wiki_context_pack.v1"
    assert payload["preflight"]["priority_evidence_layer"] == "research_wiki"


def test_topic_wiki_context_pack_cli_infers_topic_from_workspace(
    runner,
    tmp_path,
    monkeypatch,
):
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot

    db = _db_from_runner_env()
    conn = db.connect()
    workspace = tmp_path / "rh-workspace" / "demo-topic"
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text(
        "# Demo\n\nCanonical Research Harness topic: `demo` (topic id: 1).\n",
        encoding="utf-8",
    )
    try:
        _seed_topic(conn)
        build_topic_knowledge_snapshot(db, topic_id=1)
        monkeypatch.chdir(workspace)

        result = runner.invoke(
            main,
            [
                "topic",
                "wiki-context-pack",
                "--query",
                "reranker recall",
                "--json",
            ],
        )
    finally:
        conn.close()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["topic_id"] == 1
    assert payload["paper_wiki_status"] == "loaded"


def test_topic_wiki_context_pack_cli_reports_not_triggered_without_topic(
    runner,
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "rh-workspace" / "unknown-topic"
    workspace.mkdir(parents=True)
    monkeypatch.chdir(workspace)

    result = runner.invoke(
        main,
        ["topic", "wiki-context-pack", "--action-name", "paper_writing", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "schema_version": "wiki_context_pack.v1",
        "topic_id": None,
        "paper_wiki_status": "not_triggered",
        "status_reason": "topic_id_not_resolved",
        "unavailable_reasons": [
            "no --topic-id was provided and no RH topic id was found in the current workspace"
        ],
        "warnings": [],
        "preflight": {
            "priority_evidence_layer": "",
            "fallback_allowed": True,
            "fallback_must_be_declared": True,
        },
        "pages": [],
    }


def test_topic_wiki_context_pack_cli_reports_unavailable_reason(runner):
    db = _db_from_runner_env()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'missing wiki')")
        conn.commit()

        result = runner.invoke(
            main,
            [
                "topic",
                "wiki-context-pack",
                "--topic-id",
                "1",
                "--action-name",
                "paper_writing",
                "--json",
            ],
        )
    finally:
        conn.close()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["paper_wiki_status"] == "unavailable"
    assert payload["status_reason"] == "no_research_wiki_export"
    assert payload["unavailable_reasons"] == [
        "no current or stale Topic Knowledge snapshot; refresh Topic Knowledge from paper cards first"
    ]


def test_topic_wiki_context_pack_cli_invokes_service(runner, monkeypatch):
    from research_harness import cli_topic_knowledge
    from research_harness.service.types import ServiceResult

    calls: list[tuple[str, dict]] = []

    class FakeService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name: str, arguments: dict) -> ServiceResult:
            calls.append((command_name, dict(arguments)))
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={
                    "schema_version": "wiki_context_pack.v1",
                    "topic_id": arguments["topic_id"],
                    "paper_wiki_status": "loaded",
                    "status_reason": "wiki_context_pack_loaded",
                    "page_count": 0,
                    "evidence_anchor_count": 0,
                    "warnings": [],
                    "pages": [],
                    "preflight": {
                        "priority_evidence_layer": "research_wiki",
                        "fallback_allowed": False,
                        "fallback_must_be_declared": True,
                    },
                },
            )

    monkeypatch.setattr(cli_topic_knowledge, "ResearchService", FakeService)

    result = runner.invoke(
        main,
        [
            "topic",
            "wiki-context-pack",
            "--topic-id",
            "7",
            "--query",
            "  hybrid retrieval  ",
            "--action-name",
            "method_improvement",
            "--max-pages",
            "3",
            "--max-anchors",
            "9",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "wiki_context_pack",
            {
                "topic_id": 7,
                "query": "hybrid retrieval",
                "action_name": "method_improvement",
                "max_pages": 3,
                "max_anchors": 9,
            },
        )
    ]
