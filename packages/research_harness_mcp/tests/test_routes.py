"""Regression tests for HTTP route ordering bugs.

Some literal sub-paths under /api/domains were being swallowed by the
{domain_id:int} parameterized route because they were declared after it
in the file. Pin them down here so they don't regress.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from research_harness.service import ServiceResult


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "routes.db"
    from research_harness.storage.db import Database

    Database(db_path).migrate()
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))

    from research_harness_mcp import http_api

    original = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        yield TestClient(http_api.app)
    finally:
        http_api.DB_PATH = original


def test_domain_trends_get_not_swallowed_by_domain_id(client: TestClient):
    """GET /api/domains/trends must hit the trends endpoint, not be parsed as
    domain_id="trends" (which would 422)."""
    r = client.get("/api/domains/trends")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_domain_trends_with_query_params(client: TestClient):
    r = client.get("/api/domains/trends?tier=standard&limit=5")
    assert r.status_code == 200, r.text


def test_domain_id_route_still_works_for_real_ids(client: TestClient):
    """Sanity: parameterized route is intact for real numeric ids."""
    r = client.get("/api/domains/999999")
    # 404 is expected (domain doesn't exist) — what matters is NOT 422.
    assert r.status_code == 404, r.text


def test_topics_list_routes_through_research_service_preserving_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        conn.execute(
            "INSERT INTO domains (id, name, description) VALUES (?, ?, ?)",
            (7, "Systems", "Systems research"),
        )
        conn.execute(
            "INSERT INTO domains (id, name, description) VALUES (?, ?, ?)",
            (8, "Theory", "Theory research"),
        )
        conn.execute(
            """
            INSERT INTO topics
                (id, name, description, status, target_venue, deadline, created_at,
                 domain_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                42,
                "http-topic",
                "HTTP topic route",
                "active",
                "OSDI",
                "2026-09-01",
                "2026-06-05T10:00:00Z",
                7,
            ),
        )
        conn.execute(
            """
            INSERT INTO topics
                (id, name, description, status, target_venue, deadline, created_at,
                 domain_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                43,
                "filtered-topic",
                "Filtered topic",
                "active",
                "FOCS",
                "2026-10-01",
                "2026-06-05T11:00:00Z",
                8,
            ),
        )
        conn.execute(
            """
            INSERT INTO papers (id, title, status)
            VALUES (?, ?, ?), (?, ?, ?)
            """,
            (1, "Paper One", "meta_only", 2, "Paper Two", "meta_only"),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?), (?, ?)",
            (1, 42, 2, 42),
        )
        conn.execute(
            """
            INSERT INTO orchestrator_runs
                (topic_id, mode, current_stage, stage_status)
            VALUES (?, ?, ?, ?)
            """,
            (42, "standard", "analyze", "in_progress"),
        )
        conn.commit()

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            calls.append((command_name, arguments))
            if command_name == "orchestrator_status":
                return ServiceResult(
                    command=command_name,
                    status="success",
                    summary="ok",
                    output={
                        "run": {
                            "topic_id": 42,
                            "current_stage": "analyze",
                            "stage_status": "waiting",
                            "gate_status": "service-gate-status-is-not-http-source",
                            "mode": "standard",
                            "blocking_issue_count": 2,
                            "unresolved_issue_count": 3,
                        }
                    },
                )
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={
                    "topics": [
                        {
                            "id": 42,
                            "name": "http-topic",
                            "description": "HTTP topic route",
                            "status": "active",
                        },
                        {
                            "id": 43,
                            "name": "filtered-topic",
                            "description": "Filtered topic",
                            "status": "active",
                        },
                    ]
                },
            )

    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService, raising=False)

    response = client.get("/api/topics?domain_id=7")

    assert response.status_code == 200, response.text
    assert calls == [("topic_list", {})]
    assert response.json() == [
        {
            "id": 42,
            "name": "http-topic",
            "description": "HTTP topic route",
            "status": "active",
            "target_venue": "OSDI",
            "deadline": "2026-09-01",
            "created_at": "2026-06-05T10:00:00Z",
            "paper_count": 2,
            "domain_id": 7,
            "domain_name": "Systems",
            "current_stage": "analyze",
            "stage_status": "in_progress",
        }
    ]


def test_provenance_summary_routes_through_research_service_preserving_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (42, "prov"))
        conn.execute("INSERT INTO topics (id, name) VALUES (?, ?)", (43, "other"))
        conn.execute(
            """
            INSERT INTO provenance_records
                (id, primitive, category, started_at, finished_at, backend,
                 model_used, topic_id, stage, input_hash, output_hash, cost_usd,
                 success, error, created_at, prompt_tokens, completion_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "paper_ingest",
                "paper",
                "2026-06-05T10:00:00Z",
                "2026-06-05T10:00:01Z",
                "local",
                "gpt-test",
                42,
                "ingest",
                "input-hash",
                "output-hash",
                0.25,
                1,
                "",
                "2026-06-05T10:00:02Z",
                11,
                7,
            ),
        )
        conn.execute(
            """
            INSERT INTO provenance_records
                (id, primitive, category, started_at, finished_at, backend,
                 model_used, topic_id, stage, input_hash, output_hash, cost_usd,
                 success, error, created_at, prompt_tokens, completion_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                2,
                "claim_extract",
                "analysis",
                "2026-06-05T10:01:00Z",
                "2026-06-05T10:01:01Z",
                "remote",
                "other-model",
                43,
                "analyze",
                "input-hash-2",
                "output-hash-2",
                0.75,
                0,
                "failed",
                "2026-06-05T10:01:02Z",
                19,
                13,
            ),
        )
        conn.commit()

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            calls.append((command_name, arguments))
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={
                    "total_operations": 1,
                    "total_cost_usd": 0.25,
                    "total_prompt_tokens": 11,
                    "total_completion_tokens": 7,
                },
            )

    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)

    response = client.get("/api/provenance/summary?topic_id=42")

    assert response.status_code == 200, response.text
    assert calls == [("provenance_summary", {"topic_id": 42})]
    assert response.json() == {
        "total_records": 1,
        "total_cost_usd": 0.25,
        "total_prompt_tokens": 11,
        "total_completion_tokens": 7,
        "by_backend": [
            {
                "backend": "local",
                "model_used": "gpt-test",
                "call_count": 1,
                "total_cost": 0.25,
                "prompt_tokens": 11,
                "completion_tokens": 7,
            }
        ],
        "by_primitive": [
            {
                "primitive": "paper_ingest",
                "call_count": 1,
                "total_cost": 0.25,
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "success_count": 1,
                "failure_count": 0,
            }
        ],
        "recent_records": [
            {
                "id": 1,
                "primitive": "paper_ingest",
                "backend": "local",
                "model_used": "gpt-test",
                "cost_usd": 0.25,
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "success": 1,
                "created_at": "2026-06-05T10:00:02Z",
            }
        ],
    }


def test_provenance_summary_does_not_mask_database_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={"total_operations": 0},
            )

    class BrokenContext:
        def __enter__(self):
            raise sqlite3.OperationalError("provenance table unavailable")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)
    monkeypatch.setattr(http_api, "get_db", lambda: BrokenContext())

    response = client.get("/api/provenance/summary")

    assert response.status_code == 500
    assert response.json()["detail"] == "provenance summary query failed"


def _seed_deferred_http_shape_topic() -> None:
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        conn.execute(
            """
            INSERT INTO domains (id, name, description, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (7, "Systems", "Systems research", "active", "2026-06-05T08:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO topics
                (id, name, description, status, target_venue, deadline, created_at,
                 domain_id, contributions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                42,
                "shape-topic",
                "Topic shape lock",
                "active",
                "OSDI",
                "2026-09-01",
                "2026-06-05T10:00:00Z",
                7,
                "human: review",
            ),
        )
        conn.execute(
            """
            INSERT INTO papers
                (id, title, authors, year, venue, doi, arxiv_id, s2_id, url,
                 abstract, citation_count, status, created_at, deep_read)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Alpha Paper",
                '["Ada", "Ben"]',
                2024,
                "ICLR",
                "10.1/alpha",
                "2401.00001",
                "s2-alpha",
                "https://example.test/alpha",
                "Alpha abstract",
                12,
                "deep_read",
                "2026-06-01T09:00:00Z",
                1,
                2,
                "Beta Paper",
                '["Cy"]',
                2023,
                "NeurIPS",
                "10.1/beta",
                "2401.00002",
                "s2-beta",
                "https://example.test/beta",
                "Beta abstract",
                5,
                "meta_only",
                "2026-06-02T09:00:00Z",
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO paper_topics (paper_id, topic_id, relevance, created_at)
            VALUES (?, ?, ?, ?), (?, ?, ?, ?)
            """,
            (
                1,
                42,
                "high",
                "2026-06-03T09:00:00Z",
                2,
                42,
                "medium",
                "2026-06-03T10:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO paper_annotations
                (paper_id, section, content, source, confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "method",
                '{"note":"strong"}',
                "manual",
                0.9,
                "2026-06-04T09:00:00Z",
                "2026-06-04T09:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO orchestrator_runs
                (topic_id, mode, current_stage, stage_status, gate_status,
                 blocking_issue_count, unresolved_issue_count, stop_before,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                42,
                "standard",
                "analyze",
                "waiting",
                "needs_review",
                2,
                3,
                "write",
                "2026-06-05T10:10:00Z",
                "2026-06-05T10:20:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (topic_id, stage, artifact_type, status, version, title,
                 payload_json, metadata_json, created_at, updated_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?),
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                42,
                "analyze",
                "evidence_pack",
                "active",
                1,
                "Evidence",
                "{}",
                "{}",
                "2026-06-05T10:30:00Z",
                "2026-06-05T10:30:00Z",
                42,
                "write",
                "draft_pack",
                "active",
                1,
                "Draft",
                "{}",
                "{}",
                "2026-06-05T10:40:00Z",
                "2026-06-05T10:40:00Z",
            ),
        )
        # get_status recomputes issue counts from open review_issues rows,
        # so seed 3 open issues (2 blocking) to match the stored run counts.
        conn.executemany(
            """
            INSERT INTO review_issues
                (topic_id, stage, review_type, severity, category,
                 blocking, status, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (42, "analyze", "internal", "high", "evidence", 1, "open", "i1"),
                (42, "analyze", "internal", "high", "evidence", 1, "open", "i2"),
                (42, "write", "internal", "medium", "style", 0, "open", "i3"),
            ],
        )
        conn.commit()


def test_topic_detail_deferred_shape_is_locked(client: TestClient):
    _seed_deferred_http_shape_topic()

    response = client.get("/api/topics/42")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": 42,
        "name": "shape-topic",
        "description": "Topic shape lock",
        "status": "active",
        "target_venue": "OSDI",
        "deadline": "2026-09-01",
        "created_at": "2026-06-05T10:00:00Z",
        "paper_count": 2,
        "annotation_count": 1,
        "domain_id": 7,
        "domain_name": "Systems",
        "current_stage": "analyze",
        "stage_status": "waiting",
        "gate_status": "needs_review",
        "contributions": "human: review",
        "mode": "standard",
        "stop_before": "write",
        "blocking_issue_count": 2,
        "unresolved_issue_count": 3,
        "artifact_counts": {"analyze": 1, "write": 1},
    }


def test_topic_detail_routes_through_research_service_preserving_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    _seed_deferred_http_shape_topic()
    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            calls.append((command_name, arguments))
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={
                    "id": 42,
                    "name": "shape-topic",
                    "description": "Topic shape lock",
                    "status": "active",
                },
            )

    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)

    response = client.get("/api/topics/42")

    assert response.status_code == 200, response.text
    assert calls == [
        ("topic_show", {"name": "shape-topic"}),
        ("orchestrator_status", {"topic_id": 42}),
    ]
    assert response.json() == {
        "id": 42,
        "name": "shape-topic",
        "description": "Topic shape lock",
        "status": "active",
        "target_venue": "OSDI",
        "deadline": "2026-09-01",
        "created_at": "2026-06-05T10:00:00Z",
        "paper_count": 2,
        "annotation_count": 1,
        "domain_id": 7,
        "domain_name": "Systems",
        "current_stage": "analyze",
        "stage_status": "waiting",
        "gate_status": "needs_review",
        "contributions": "human: review",
        "mode": "standard",
        "stop_before": "write",
        "blocking_issue_count": 2,
        "unresolved_issue_count": 3,
        "artifact_counts": {"analyze": 1, "write": 1},
    }


def test_papers_topic_filter_deferred_shape_is_locked(client: TestClient):
    _seed_deferred_http_shape_topic()

    response = client.get(
        "/api/papers?topic_id=42&status=deep_read&sort=title&order=asc"
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "data": [
            {
                "id": 1,
                "title": "Alpha Paper",
                "authors": ["Ada", "Ben"],
                "year": 2024,
                "venue": "ICLR",
                "doi": "10.1/alpha",
                "arxiv_id": "2401.00001",
                "s2_id": "s2-alpha",
                "pmid": None,
                "pmcid": None,
                "pdf_path": "",
                "pdf_hash": "",
                "status": "deep_read",
                "created_at": "2026-06-01T09:00:00Z",
                "url": "https://example.test/alpha",
                "abstract": "Alpha abstract",
                "bibtex_auto": "",
                "concepts_json": "",
                "citation_count": 12,
                "affiliations": "[]",
                "compiled_summary": "",
                "compiled_from_hash": "",
                "deep_read": 1,
                "relevance": "high",
            }
        ],
        "pagination": {"page": 1, "per_page": 50, "total": 1, "total_pages": 1},
    }


def test_papers_topic_filter_routes_through_research_service_preserving_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    _seed_deferred_http_shape_topic()
    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            calls.append((command_name, arguments))
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={
                    "papers": [
                        {
                            "id": 1,
                            "title": "Alpha Paper",
                            "year": 2024,
                            "venue": "ICLR",
                            "url": "https://example.test/alpha",
                            "affiliations": "[]",
                            "relevance": "high",
                        }
                    ]
                },
            )

    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)

    response = client.get(
        "/api/papers?topic_id=42&status=deep_read&sort=title&order=asc"
    )

    assert response.status_code == 200, response.text
    assert calls == [("paper_list", {"topic": "shape-topic"})]
    assert response.json() == {
        "data": [
            {
                "id": 1,
                "title": "Alpha Paper",
                "authors": ["Ada", "Ben"],
                "year": 2024,
                "venue": "ICLR",
                "doi": "10.1/alpha",
                "arxiv_id": "2401.00001",
                "s2_id": "s2-alpha",
                "pmid": None,
                "pmcid": None,
                "pdf_path": "",
                "pdf_hash": "",
                "status": "deep_read",
                "created_at": "2026-06-01T09:00:00Z",
                "url": "https://example.test/alpha",
                "abstract": "Alpha abstract",
                "bibtex_auto": "",
                "concepts_json": "",
                "citation_count": 12,
                "affiliations": "[]",
                "compiled_summary": "",
                "compiled_from_hash": "",
                "deep_read": 1,
                "relevance": "high",
            }
        ],
        "pagination": {"page": 1, "per_page": 50, "total": 1, "total_pages": 1},
    }


def test_topic_gate_routes_through_research_service_preserving_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            calls.append((command_name, arguments))
            return ServiceResult(
                command=command_name,
                status="success",
                summary="service summary is transport-internal",
                output={"gate_decision": "fail"},
            )

    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)

    response = client.get("/api/topics/42/gate")

    assert response.status_code == 200, response.text
    assert calls == [("orchestrator_gate_check", {"topic_id": 42})]
    assert response.json() == {
        "status": "success",
        "summary": "Gate decision: fail",
        "output": {"gate_decision": "fail"},
        "next_actions": ["orchestrator_status — check what's missing"],
        "artifacts": [],
        "recovery_hint": "",
        "primitive": "orchestrator_gate_check",
        "backend": "orchestrator",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": "",
    }


def test_discover_weekly_sample_endpoint(client: TestClient):
    r = client.get("/api/discover/weekly?sample=true&generated_at=2026-05-10")

    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["product"] == "RH Discover"
    assert payload["generated_at"] == "2026-05-10"
    assert len(payload["briefs"]) >= 3
    assert payload["briefs"][0]["rh_handoff"]["initial_queries"]


def test_discover_sources_endpoint(client: TestClient):
    r = client.get("/api/discover/sources")

    assert r.status_code == 200, r.text
    payload = r.json()
    families = {source["family"] for source in payload}
    assert {"papers", "blogs", "repos_models", "social"} <= families


def test_discover_issue_archive_and_latest_endpoint(client: TestClient):
    archive = client.get("/api/discover/issues?cadence=weekly")
    latest = client.get("/api/discover/issues/latest?cadence=weekly")
    weekly = client.get("/api/discover/weekly?sample=false")

    assert archive.status_code == 200, archive.text
    issues = archive.json()
    assert any(issue["issue_id"] == "demo-weekly" for issue in issues)

    assert latest.status_code == 200, latest.text
    assert latest.json()["issue_id"] == issues[0]["issue_id"]
    assert latest.json()["briefs"][0]["rh_handoff"]["initial_queries"]

    assert weekly.status_code == 200, weekly.text
    assert weekly.json()["issue_id"] == latest.json()["issue_id"]


def test_create_topic_materializes_configured_workspace(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    workspace_root = tmp_path / "rh-workspace"
    monkeypatch.delenv(
        "RESEARCH_HARNESS_DISABLE_WORKSPACE_MATERIALIZATION", raising=False
    )
    monkeypatch.setenv("RESEARCH_HARNESS_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setattr(
        http_api,
        "_run_tool",
        lambda name, args: {"tool": name, "args": args, "status": "ok"},
    )

    response = client.post(
        "/api/topics",
        json={"name": "workspace-topic", "description": "HTTP workspace topic."},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    topic_workspace = workspace_root / "workspace-topic"
    assert payload["workspace_path"] == str(topic_workspace)
    assert (topic_workspace / "README.md").exists()
    assert (topic_workspace / "00-task-framing" / "topic-brief-v0.md").exists()


def test_publication_pack_endpoint_generates_pack(client: TestClient):
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("pack-topic", "Publication pack route test"),
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) VALUES (?, ?, ?)",
            (topic_id, "pack-project", "Publication pack route test"),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
              (topic_id, stage, artifact_type, title, payload_json, status, stale)
            VALUES (?, 'analyze', 'evidence_pack', 'Evidence',
                    '{"claims":[{"claim_id":"c1","paper_ids":[1]}]}', 'active', 0)
            """,
            (topic_id,),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
              (topic_id, stage, artifact_type, title, payload_json, status, stale)
            VALUES (?, 'write', 'draft_pack', 'Draft',
                    '{"sections":{"intro":"Evidence-backed text [paper:1]."}}',
                    'active', 0)
            """,
            (topic_id,),
        )
        conn.commit()

    response = client.post(
        f"/api/topics/{topic_id}/publication-pack",
        json={"target_profile": "neurips", "record_artifact": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    output = payload["output"]
    assert output["target_profile"] == "neurips"
    assert output["ready_for_review"] is True
    assert output["submission_ready"] is False
    assert output["next_actions"][0]["component"] == "citation_integrity"
    assert output["publication_pack_artifact_id"] > 0


def test_publication_pack_endpoint_rejects_oversized_profile(client: TestClient):
    response = client.post(
        "/api/topics/1/publication-pack",
        json={"target_profile": "x" * 121},
    )

    assert response.status_code == 422, response.text


def test_publication_pack_backfill_endpoint_records_safe_artifacts(client: TestClient):
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("pack-backfill-topic", "Publication pack backfill route test"),
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO project_artifacts
              (topic_id, stage, artifact_type, title, payload_json, status, stale)
            VALUES (?, 'analyze', 'evidence_pack', 'Evidence',
                    '{"claims":[{"claim_id":"c1","paper_ids":[1]}]}', 'active', 0)
            """,
            (topic_id,),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
              (topic_id, stage, artifact_type, title, payload_json, status, stale)
            VALUES (?, 'write', 'draft_pack', 'Draft',
                    '{"sections":{"intro":"Evidence-backed text without citations."}}',
                    'active', 0)
            """,
            (topic_id,),
        )
        conn.commit()

    response = client.post(
        f"/api/topics/{topic_id}/publication-pack/backfill",
        json={"target_profile": "neurips", "record_artifact": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    output = payload["output"]
    assert output["created_count"] == 4
    assert {item["artifact_type"] for item in output["created_artifacts"]} == {
        "citation_sanitization_report",
        "process_summary",
        "final_bundle",
        "publication_pack",
    }
    assert output["ready_for_review"] is True
    assert output["submission_ready"] is False


def test_publication_pack_backfill_endpoint_rejects_too_many_components(
    client: TestClient,
):
    response = client.post(
        "/api/topics/1/publication-pack/backfill",
        json={"components": [f"component-{i}" for i in range(21)]},
    )

    assert response.status_code == 422, response.text


def test_discover_opportunities_list_detail_and_handoff(client: TestClient):
    opportunities = client.get("/api/discover/opportunities?sample=true")

    assert opportunities.status_code == 200, opportunities.text
    payload = opportunities.json()
    assert payload["issue_id"].startswith("sample-weekly-")
    assert payload["opportunities"]
    first = payload["opportunities"][0]
    assert first["slug"]
    assert first["readiness"]["goalability"] >= 0.0
    assert first["goal_previews"]

    detail = client.get(f"/api/discover/opportunities/{first['slug']}?sample=true")
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert detail_payload["slug"] == first["slug"]
    assert detail_payload["brief"]["rh_handoff"]["initial_queries"]

    handoff = client.post(
        f"/api/discover/opportunities/{first['slug']}/handoff?sample=true",
        json={
            "user_profile": {
                "level": "masters",
                "compute_budget": "cpu_only",
                "deadline_days": 90,
            },
            "selected_goal_preview_ids": [first["goal_previews"][0]["id"]],
        },
    )
    assert handoff.status_code == 200, handoff.text
    handoff_payload = handoff.json()
    assert handoff_payload["created"] is True
    assert handoff_payload["topic_id"] > 0
    assert handoff_payload["topic_name"] == first["rh_handoff"]["topic_name"]
    assert handoff_payload["goal_seeds"][0]["id"] == first["goal_previews"][0]["id"]
    assert handoff_payload["next_url"] == f"/topics/{handoff_payload['topic_id']}"

    topic = client.get(f"/api/topics/{handoff_payload['topic_id']}")
    assert topic.status_code == 200, topic.text
    assert "RH Discovery handoff" in topic.json()["description"]
