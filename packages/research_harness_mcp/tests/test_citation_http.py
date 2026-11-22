"""Focused HTTP tests for citation export and contradiction endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from research_harness.storage.db import Database


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "citations.db"
    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'citations')")
        conn.execute(
            """
            INSERT INTO papers
                (id, title, authors, year, venue, doi, arxiv_id)
            VALUES
                (?, ?, ?, ?, ?, ?, ?),
                (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Alpha Retrieval",
                json.dumps(["Ada Lovelace"]),
                2024,
                "ICLR",
                "10.1000/alpha",
                "2401.00001",
                2,
                "Beta Systems",
                json.dumps([{"name": "Grace Hopper"}]),
                2025,
                "NeurIPS",
                "",
                "2501.00001",
            ),
        )
        conn.execute(
            """
            INSERT INTO paper_topics (paper_id, topic_id)
            VALUES (1, 1), (2, 1)
            """
        )
        conn.execute(
            """
            INSERT INTO bib_entries (paper_id, bibtex_key, bibtex, source)
            VALUES (?, ?, ?, ?)
            """,
            (
                1,
                "alpha2024",
                "@inproceedings{alpha2024,\n"
                "  title={Alpha Retrieval},\n"
                "  author={Lovelace, Ada},\n"
                "  year={2024}\n"
                "}",
                "dblp",
            ),
        )
        conn.execute(
            """
            INSERT INTO normalized_claims
                (id, topic_id, paper_id, claim_text, method, dataset, metric, task)
            VALUES
                (1, 1, 1, 'Alpha improves recall', 'Alpha', 'ORB',
                 'recall@20', 'retrieval'),
                (2, 1, 2, 'Alpha does not improve recall', 'Alpha', 'ORB',
                 'recall@20', 'retrieval')
            """
        )
        conn.execute(
            """
            INSERT INTO contradictions
                (id, topic_id, claim_a_id, claim_b_id, same_task, same_dataset,
                 same_metric, confidence, conflict_reason, status)
            VALUES (7, 1, 1, 2, 1, 1, 1, 0.75, 'opposite direction', 'candidate')
            """
        )
        conn.commit()
    finally:
        conn.close()

    from research_harness_mcp import http_api

    original = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        yield TestClient(http_api.app)
    finally:
        http_api.DB_PATH = original


def test_topic_bibtex_exports_stored_and_synthesized_entries(client: TestClient):
    response = client.get("/api/topics/1/bibtex")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "@inproceedings{alpha2024," in body
    assert "author={Lovelace, Ada}" in body
    assert "@misc{hopper-2025-beta," in body
    assert "title={Beta Systems}" in body
    assert "author={Grace Hopper}" in body
    assert "archivePrefix={arXiv}" in body
    assert body.endswith("\n")


def test_contradictions_hydrate_claim_details(client: TestClient):
    response = client.get("/api/topics/1/contradictions")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["topic_id"] == 1
    assert payload["contradictions"] == [
        {
            "id": 7,
            "topic_id": 1,
            "claim_a_id": 1,
            "claim_b_id": 2,
            "conflict_reason": "opposite direction",
            "status": "candidate",
            "confidence": 0.75,
            "created_at": payload["contradictions"][0]["created_at"],
            "claim_a": {
                "id": 1,
                "claim_text": "Alpha improves recall",
                "paper_id": 1,
                "modality": "text",
                "dataset": "ORB",
                "metric": "recall@20",
                "task": "retrieval",
            },
            "claim_b": {
                "id": 2,
                "claim_text": "Alpha does not improve recall",
                "paper_id": 2,
                "modality": "text",
                "dataset": "ORB",
                "metric": "recall@20",
                "task": "retrieval",
            },
        }
    ]
