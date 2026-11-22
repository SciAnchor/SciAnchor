"""Focused HTTP tests for domain trends routes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "trends-http.db"
    from research_harness.storage.db import Database

    Database(db_path).migrate()
    from research_harness_mcp import http_api

    original = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        yield TestClient(http_api.app)
    finally:
        http_api.DB_PATH = original


def _seed_domain_trends() -> None:
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        conn.execute(
            """
            INSERT INTO domain_trends
                (name, description, velocity_yoy, citation_median, top_venues,
                 publishability_score, why, seed_papers, tier, scope)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Top trend",
                "Highest-scoring trend",
                12.5,
                21.0,
                json.dumps(["NeurIPS", "ICML"]),
                9.2,
                "because",
                json.dumps([{"id": 1, "title": "Paper One"}]),
                "standard",
                "domain:7",
                "Lower trend",
                "Lower-scoring trend",
                3.0,
                5.0,
                json.dumps(["ACL"]),
                4.1,
                "lower",
                json.dumps([{"id": 2, "title": "Paper Two"}]),
                "standard",
                "domain:7",
            ),
        )
        conn.commit()


def _seed_yearly_scope() -> None:
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        conn.execute("INSERT INTO domains (id, name) VALUES (?, ?)", (7, "Systems"))
        conn.execute(
            "INSERT INTO topics (id, name, domain_id) VALUES (?, ?, ?)",
            (70, "systems-topic", 7),
        )
        conn.execute(
            """
            INSERT INTO papers
                (id, title, year, venue, citation_count, doi, arxiv_id, s2_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?),
                   (?, ?, ?, ?, ?, ?, ?, ?),
                   (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Paper 2024",
                2024,
                "OSDI",
                10,
                "10.0/1",
                "2401.00001",
                "s2-1",
                2,
                "Paper 2025",
                2025,
                "SOSP",
                30,
                "10.0/2",
                "2501.00002",
                "s2-2",
                3,
                "Outside Paper",
                2025,
                "CHI",
                90,
                "10.0/3",
                "2501.00003",
                "s2-3",
            ),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?), (?, ?)",
            (1, 70, 2, 70),
        )
        conn.commit()


def test_domain_trends_reads_db_rows_and_parses_json_fields(client: TestClient):
    _seed_domain_trends()

    response = client.get("/api/domains/trends?tier=standard&scope=domain:7&limit=1")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "id": 1,
            "name": "Top trend",
            "description": "Highest-scoring trend",
            "velocity_yoy": 12.5,
            "citation_median": 21,
            "top_venues": ["NeurIPS", "ICML"],
            "publishability_score": 9.2,
            "why": "because",
            "seed_papers": [{"id": 1, "title": "Paper One"}],
            "tier": "standard",
            "generated_at": response.json()[0]["generated_at"],
            "scope": "domain:7",
            "source": "computed",
            "paper_count": 1,
        }
    ]


def test_domain_trends_rejects_malformed_scope(client: TestClient):
    response = client.get("/api/domains/trends?scope=domain:not-a-number")

    assert response.status_code == 400
    assert "expects an integer" in response.json()["detail"]


def test_trends_yearly_aggregates_requested_scope(client: TestClient):
    _seed_yearly_scope()

    response = client.get("/api/trends/yearly?scope=domain:7&years=5")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "scope": "domain:7",
        "years": 5,
        "rows": [
            {
                "year": 2024,
                "paper_count": 1,
                "median_citations": 10.0,
                "top_venue_count": 1,
            },
            {
                "year": 2025,
                "paper_count": 1,
                "median_citations": 30.0,
                "top_venue_count": 1,
            },
        ],
    }


def test_domain_trends_refresh_dry_run_preserves_response_shape(client: TestClient):
    response = client.post(
        "/api/domains/trends/refresh",
        json={"tier": "standard", "scope": "domain:7", "dry_run": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["tier"] == "standard"
    assert payload["scope"] == "domain:7"
    assert payload["dry_run"] is True
    assert payload["cluster_count"] == len(payload["clusters"])
    assert payload["clusters"]
    assert set(payload["clusters"][0]) == {
        "name",
        "publishability_score",
        "velocity_yoy",
        "paper_count",
    }
