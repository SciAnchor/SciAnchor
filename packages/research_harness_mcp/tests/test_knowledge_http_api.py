from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "knowledge-http.db"
    from research_harness.storage.db import Database

    Database(db_path).migrate()
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.delenv("RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN", raising=False)

    from research_harness_mcp import http_api

    original = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        yield TestClient(http_api.app)
    finally:
        http_api.DB_PATH = original


@pytest.fixture()
def db_path(client: TestClient) -> Path:
    from research_harness_mcp import http_api

    return http_api.DB_PATH


def _seed_knowledge_status_topic(conn) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'knowledge http')")
    conn.execute(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
        VALUES (1, 'Knowledge HTTP Paper', '10.test/http-status',
                '2601.03010', 's2_http_status')
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
            (1, 1, 1, 'HTTP knowledge improves inspection', 'HTTP evidence',
             'RH', 'inspection_score', 'status inspection', '+1', 'higher', 0.82,
             '[{"section":"results","text":"HTTP inspection improves"}]')
        """
    )
    conn.commit()


def _seed_cross_topic_pair(conn) -> None:
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'audit http')")
    conn.execute("INSERT INTO topics (id, name) VALUES (2, 'literature http')")
    conn.execute(
        """
        INSERT INTO papers (id, title, doi, arxiv_id, s2_id)
        VALUES
            (1, 'HTTP Audit Checkpoints', '10.test/http-audit',
             '2601.03001', 's2_http_audit'),
            (2, 'HTTP Literature Agents', '10.test/http-lit',
             '2601.03002', 's2_http_lit')
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


def test_knowledge_status_http_outputs_public_safe_json_without_writes(
    client: TestClient, db_path: Path
):
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.storage.db import Database

    db = Database(db_path)
    conn = db.connect()
    try:
        _seed_knowledge_status_topic(conn)
        snapshot = build_topic_knowledge_snapshot(db, topic_id=1)
        before_count = _artifact_count(conn)

        response = client.get("/api/topics/1/knowledge-status")

        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert _artifact_count(conn) == before_count
    finally:
        conn.close()

    payload = response.json()
    assert payload["schema_version"] == "knowledge_status.v1"
    assert payload["topic_id"] == 1
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
        "RESEARCH_HARNESS_DB_PATH",
        "paper_ingest",
    ):
        assert fragment not in encoded


def test_knowledge_status_http_success_includes_allowed_cors_and_no_store(
    client: TestClient,
    db_path: Path,
):
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.storage.db import Database

    db = Database(db_path)
    conn = db.connect()
    try:
        _seed_knowledge_status_topic(conn)
        build_topic_knowledge_snapshot(db, topic_id=1)

        allowed = client.get(
            "/api/topics/1/knowledge-status",
            headers={"Origin": "http://localhost:3000"},
        )
        disallowed = client.get(
            "/api/topics/1/knowledge-status",
            headers={"Origin": "http://example.test"},
        )
    finally:
        conn.close()

    assert allowed.status_code == 200
    assert allowed.headers["cache-control"] == "private, no-store"
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert allowed.headers["access-control-allow-credentials"] == "true"

    assert disallowed.status_code == 200
    assert disallowed.headers["cache-control"] == "private, no-store"
    assert "access-control-allow-origin" not in disallowed.headers


def test_knowledge_status_http_returns_public_error_for_missing_snapshot(
    client: TestClient,
):
    response = client.get("/api/topics/1/knowledge-status")

    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "error": {
            "code": "knowledge_status_unavailable",
            "message": "knowledge status is unavailable for topic 1",
        }
    }


def test_topic_knowledge_refresh_http_builds_snapshot(
    client: TestClient, db_path: Path
):
    from research_harness.storage.db import Database

    db = Database(db_path)
    conn = db.connect()
    try:
        _seed_knowledge_status_topic(conn)
        before_count = _artifact_count(conn)

        response = client.post("/api/topics/1/knowledge-refresh")

        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert _artifact_count(conn) == before_count + 1
    finally:
        conn.close()

    payload = response.json()
    assert payload["status"] == "refreshed"
    assert payload["topic_id"] == 1
    assert payload["artifact_id"]
    assert payload["snapshot_id"]
    assert payload["source_hash"]
    assert payload["error"] == ""


def test_topic_knowledge_refresh_http_returns_public_error_for_missing_topic(
    client: TestClient,
):
    response = client.post("/api/topics/999/knowledge-refresh")

    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "error": {
            "code": "topic_not_found",
            "message": "topic 999 not found",
        }
    }


def test_topic_knowledge_refresh_http_validates_topic_id(client: TestClient):
    response = client.post("/api/topics/not-an-int/knowledge-refresh")

    assert response.status_code == 400
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "error": {
            "code": "invalid_topic_id",
            "message": "topic_id must be a positive integer",
        }
    }


def test_topic_knowledge_refresh_http_returns_public_safe_failure(
    client: TestClient,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness.service import ServiceResult
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db = Database(db_path)
    conn = db.connect()
    try:
        _seed_knowledge_status_topic(conn)
    finally:
        conn.close()

    class FailingService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            assert name == "topic_knowledge_refresh"
            assert arguments == {"topic_id": 1}
            return ServiceResult(
                command=name,
                status="error",
                summary="topic knowledge refresh failed for topic 1",
                output={
                    "status": "failed",
                    "topic_id": 1,
                    "paper_id": None,
                    "artifact_id": None,
                    "snapshot_id": None,
                    "source_hash": "",
                    "error": "topic knowledge refresh failed",
                    "error_code": "topic_knowledge_refresh_failed",
                },
                error={
                    "code": "topic_knowledge_refresh_failed",
                    "message": "topic knowledge refresh failed for topic 1",
                },
            )

    monkeypatch.setattr(http_api, "ResearchService", FailingService)

    response = client.post("/api/topics/1/knowledge-refresh")

    assert response.status_code == 500
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "error": {
            "code": "topic_knowledge_refresh_failed",
            "message": "topic knowledge refresh failed for topic 1",
        }
    }
    assert ".research-harness" not in response.text
    assert "internal builder exploded" not in response.text


def test_topic_knowledge_refresh_all_http_refreshes_every_topic(
    client: TestClient, db_path: Path
):
    from research_harness.storage.db import Database

    db = Database(db_path)
    conn = db.connect()
    try:
        _seed_cross_topic_pair(conn)

        response = client.post("/api/topics/knowledge-refresh-all")

        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert _artifact_count(conn) == 2
    finally:
        conn.close()

    payload = response.json()
    assert payload["topic_count"] == 2
    assert payload["counts"]["refreshed"] == 2
    assert payload["counts"]["failed"] == 0
    assert payload["failed_topic_ids"] == []


def test_cross_topic_atlas_http_outputs_public_safe_json_without_writes(
    client: TestClient, db_path: Path
):
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.storage.db import Database

    db = Database(db_path)
    conn = db.connect()
    try:
        _seed_cross_topic_pair(conn)
        build_topic_knowledge_snapshot(db, topic_id=1)
        build_topic_knowledge_snapshot(db, topic_id=2)
        before_count = _artifact_count(conn)

        response = client.get(
            "/api/topics/cross-topic-atlas",
            params=[("topic_id", "1"), ("topic_id", "2")],
        )

        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert _artifact_count(conn) == before_count
    finally:
        conn.close()

    payload = response.json()
    assert payload["schema_version"] == "cross_topic_knowledge_atlas.v1"
    assert payload["topic_ids"] == [1, 2]
    assert payload["link_count"] > 0
    assert payload["links"][0]["link_type"] == "method_transfers_to_gap"

    encoded = json.dumps(payload, sort_keys=True)
    for fragment in (
        ".research-harness",
        "SELECT ",
        "hidden_gold",
        "vendor_request",
        "OPENAI_API_KEY",
        "RESEARCH_HARNESS_DB_PATH",
        "paper_ingest",
    ):
        assert fragment not in encoded


def test_cross_topic_atlas_http_supports_query_ranking(
    client: TestClient, db_path: Path
):
    from research_harness.knowledge.topic_layer import build_topic_knowledge_snapshot
    from research_harness.storage.db import Database

    db = Database(db_path)
    conn = db.connect()
    try:
        _seed_cross_topic_pair(conn)
        build_topic_knowledge_snapshot(db, topic_id=1)
        build_topic_knowledge_snapshot(db, topic_id=2)
    finally:
        conn.close()

    response = client.get(
        "/api/topics/cross-topic-atlas",
        params=[
            ("topic_id", "1"),
            ("topic_id", "2"),
            ("query", "provenance drift"),
            ("max_results", "1"),
        ],
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["query"] == "provenance drift"
    assert payload["link_count"] == 1
    assert "provenance" in json.dumps(payload["links"][0], sort_keys=True).lower()


def test_cross_topic_atlas_http_validates_distinct_positive_topic_ids(
    client: TestClient,
):
    invalid = client.get(
        "/api/topics/cross-topic-atlas",
        params=[("topic_id", "0"), ("topic_id", "2")],
    )
    duplicate = client.get(
        "/api/topics/cross-topic-atlas",
        params=[("topic_id", "2"), ("topic_id", "2")],
    )

    assert invalid.status_code == 400
    assert invalid.headers["cache-control"] == "private, no-store"
    assert invalid.json() == {
        "error": {
            "code": "invalid_topic_id",
            "message": "topic_id must be a positive integer",
        }
    }
    assert duplicate.status_code == 400
    assert duplicate.headers["cache-control"] == "private, no-store"
    assert duplicate.json() == {
        "error": {
            "code": "invalid_topic_ids",
            "message": "at least two distinct topic ids are required",
        }
    }


def test_cross_topic_atlas_http_rejects_excessive_max_results(client: TestClient):
    response = client.get(
        "/api/topics/cross-topic-atlas",
        params=[
            ("topic_id", "1"),
            ("topic_id", "2"),
            ("max_results", "21"),
        ],
    )

    assert response.status_code == 400
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "error": {
            "code": "invalid_max_results",
            "message": "max_results must be between 1 and 20",
        }
    }


def test_cross_topic_atlas_http_deduplicates_topic_ids_before_service_call(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    captured_topic_ids: list[tuple[int, ...]] = []

    class FakeResearchService:
        def __init__(self, *, db):
            self.db = db

        def invoke(self, command_name, arguments):
            from research_harness.service.types import ServiceResult

            assert command_name == "cross_topic_atlas"
            captured_topic_ids.append(tuple(arguments["topic_ids"]))
            return ServiceResult(
                command=command_name,
                status="success",
                summary="ok",
                output={
                    "schema_version": "cross_topic_knowledge_atlas.v1",
                    "topic_ids": list(arguments["topic_ids"]),
                    "query": arguments["query"],
                    "link_count": 0,
                    "links": [],
                    "warnings": [],
                },
            )

    monkeypatch.setattr(http_api, "ResearchService", FakeResearchService)

    response = client.get(
        "/api/topics/cross-topic-atlas",
        params=[("topic_id", "1"), ("topic_id", "1"), ("topic_id", "2")],
    )

    assert response.status_code == 200
    assert captured_topic_ids == [(1, 2)]
    assert response.json()["topic_ids"] == [1, 2]


def test_knowledge_status_http_maps_non_integer_topic_id_to_public_error(
    client: TestClient,
):
    response = client.get("/api/topics/not-an-int/knowledge-status")

    assert response.status_code == 400
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "error": {
            "code": "invalid_topic_id",
            "message": "topic_id must be a positive integer",
        }
    }


def test_cross_topic_atlas_http_maps_non_integer_topic_id_to_public_error(
    client: TestClient,
):
    response = client.get(
        "/api/topics/cross-topic-atlas",
        params=[("topic_id", "1"), ("topic_id", "not-an-int")],
    )

    assert response.status_code == 400
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "error": {
            "code": "invalid_topic_id",
            "message": "topic_id must be a positive integer",
        }
    }


def test_cross_topic_atlas_http_returns_public_error_for_missing_snapshot(
    client: TestClient,
):
    response = client.get(
        "/api/topics/cross-topic-atlas",
        params=[("topic_id", "1"), ("topic_id", "2")],
    )

    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "error": {
            "code": "cross_topic_atlas_unavailable",
            "message": "cross-topic atlas is unavailable for topic ids: 1, 2",
        }
    }


def test_knowledge_http_beta_token_gate_when_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN", "beta-secret")

    missing = client.get("/api/topics/1/knowledge-status")
    wrong = client.get(
        "/api/topics/1/knowledge-status",
        headers={"X-RH-Knowledge-Token": "wrong-secret"},
    )
    header_authorized = client.get(
        "/api/topics/1/knowledge-status",
        headers={"X-RH-Knowledge-Token": "beta-secret"},
    )
    bearer_authorized = client.get(
        "/api/topics/cross-topic-atlas",
        params=[("topic_id", "1"), ("topic_id", "2")],
        headers={"Authorization": "Bearer beta-secret"},
    )

    expected_error = {
        "error": {
            "code": "knowledge_api_token_required",
            "message": "knowledge API beta token required",
        }
    }
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.headers["cache-control"] == "private, no-store"
    assert wrong.headers["cache-control"] == "private, no-store"
    assert missing.json() == expected_error
    assert wrong.json() == expected_error

    assert header_authorized.status_code == 404
    assert header_authorized.json()["error"]["code"] == "knowledge_status_unavailable"
    assert bearer_authorized.status_code == 404
    assert bearer_authorized.json()["error"]["code"] == "cross_topic_atlas_unavailable"


def test_knowledge_http_beta_token_errors_include_cors_for_allowed_origin(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN", "beta-secret")

    missing = client.get(
        "/api/topics/1/knowledge-status",
        headers={"Origin": "http://localhost:3000"},
    )
    wrong = client.get(
        "/api/topics/1/knowledge-status",
        headers={
            "Origin": "http://localhost:3000",
            "X-RH-Knowledge-Token": "wrong-secret",
        },
    )
    disallowed_origin = client.get(
        "/api/topics/1/knowledge-status",
        headers={"Origin": "http://example.test"},
    )

    for response in (missing, wrong):
        assert response.status_code == 401
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["access-control-allow-origin"] == (
            "http://localhost:3000"
        )
        assert response.headers["access-control-allow-credentials"] == "true"
        assert response.json() == {
            "error": {
                "code": "knowledge_api_token_required",
                "message": "knowledge API beta token required",
            }
        }
    assert disallowed_origin.status_code == 401
    assert "access-control-allow-origin" not in disallowed_origin.headers


def test_knowledge_http_error_responses_are_no_store(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    responses = [
        client.get("/api/topics/not-an-int/knowledge-status"),
        client.get("/api/topics/0/knowledge-status"),
        client.get("/api/topics/1/knowledge-status"),
        client.get(
            "/api/topics/cross-topic-atlas",
            params=[("topic_id", "1"), ("topic_id", "not-an-int")],
        ),
        client.get(
            "/api/topics/cross-topic-atlas",
            params=[("topic_id", "0"), ("topic_id", "2")],
        ),
        client.get(
            "/api/topics/cross-topic-atlas",
            params=[("topic_id", "2"), ("topic_id", "2")],
        ),
        client.get(
            "/api/topics/cross-topic-atlas",
            params=[("topic_id", "1"), ("topic_id", "2")],
        ),
    ]

    monkeypatch.setenv("RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN", "beta-secret")
    responses.append(client.get("/api/topics/1/knowledge-status"))

    for response in responses:
        assert response.headers["cache-control"] == "private, no-store"
        assert "error" in response.json()


def test_knowledge_http_docs_cover_local_stable_release_boundary():
    # Resolve from the repo root; the suite runs from the package directory.
    docs_path = Path(__file__).resolve().parents[3] / "docs" / "knowledge-http-api.md"

    assert docs_path.exists()
    text = docs_path.read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())

    for required in (
        "Status: stable local/internal HTTP bridge",
        "stable for local dashboards and internal automation",
        "GET /api/topics/{topic_id}/knowledge-status",
        "GET /api/topics/cross-topic-atlas",
        "RESEARCH_HARNESS_KNOWLEDGE_API_TOKEN",
        "X-RH-Knowledge-Token",
        "Authorization: Bearer",
        "RESEARCH_HARNESS_CORS_ORIGINS",
        "Cache-Control: private, no-store",
        "Token failures also return the public JSON error envelope",
        "CORS response headers are only emitted for origins listed in",
        "read-only",
        "does not build snapshots",
        "does not write artifacts",
        "stable external API release is not approved",
        "public internet deployment remains out of scope",
        "legacy beta-token compatibility",
    ):
        assert required in normalized_text

    for forbidden in (
        "Status: controlled beta",
        "controlled beta integrations",
        "set a beta token",
        "## Beta Boundary",
    ):
        assert forbidden not in text
