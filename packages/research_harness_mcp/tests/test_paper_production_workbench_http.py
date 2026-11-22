from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_paper_production_workbench_routes_are_registered() -> None:
    from research_harness_mcp import http_api
    from research_harness_mcp import paper_production_workbench_http

    assert callable(paper_production_workbench_http.register_workbench_routes)
    paths = {route.path for route in http_api.app.routes}
    assert "/api/workbench/topics" in paths
    assert "/api/workbench/topics/{topic_id}/run-snapshot" in paths
    assert "/api/workbench/topics/{topic_id}/hypothesis-tree" in paths
    assert "/api/workbench/topics/{topic_id}/hypotheses/{hypothesis_id}" in paths
    assert "/api/workbench/topics/{topic_id}/experiment-jobs" in paths
    assert "/api/workbench/topics/{topic_id}/pack-status" in paths
    assert "/api/workbench/topics/{topic_id}/venue-compliance" in paths
    assert "/api/workbench/doctor" in paths


def test_workbench_read_endpoints_return_rh_native_state(
    tmp_path: Path,
) -> None:
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "workbench-http.db"
    db = Database(db_path)
    db.migrate()

    hypothesis_tree = {
        "schema_version": "rh.research_hypothesis_tree.v1",
        "topic_id": 1,
        "paper_plan_artifact_id": 10,
        "nodes": [
            {
                "id": "h1",
                "statement": "Evidence ledgers reduce unsupported claims.",
                "rationale": "Claims are checked against recorded evidence.",
                "test": "Compare unsupported claim rate.",
                "status": "supported",
                "stage": "supported",
                "parent_id": None,
                "children": ["h1.1"],
                "plan_artifact_id": 11,
                "experiment_artifact_id": 12,
                "result_artifact_id": 13,
                "report_artifact_id": 14,
                "claim_ids": ["claim-1"],
                "evidence_refs": [{"paper_id": 2}],
                "expanded": True,
            },
            {
                "id": "h1.1",
                "statement": "Citation gates catch missing references.",
                "rationale": "The gate runs before publication pack.",
                "test": "Run gate on draft claims.",
                "status": "untested",
                "stage": "planned",
                "parent_id": "h1",
                "children": [],
                "plan_artifact_id": None,
                "experiment_artifact_id": None,
                "result_artifact_id": None,
                "report_artifact_id": None,
                "claim_ids": [],
                "evidence_refs": [],
                "expanded": False,
            },
        ],
        "stop_policy": {
            "target_supported": 2,
            "max_tested": 8,
            "max_depth": 3,
        },
        "status_summary": {
            "supported": 1,
            "refuted": 0,
            "inconclusive": 0,
            "blocked": 0,
            "untested": 1,
        },
    }
    job_payload = {
        "schema_version": "rh.hypothesis_experiment_job.v1",
        "topic_id": 1,
        "hypothesis_id": "h1",
        "run_id": "run-1",
        "status": "running",
        "effective_config": {"sandbox": "rh-runtime"},
        "attempts": [{"attempt_id": "attempt-1", "status": "running"}],
        "events_ref": {"ledger": "runtime_events", "run_id": "run-1"},
        "result_artifact_id": None,
        "report_artifact_id": None,
    }
    venue_payload = {
        "schema_version": "rh.venue_compliance_report.v1",
        "topic_id": 1,
        "status": "passed",
        "latex_compile_success": True,
        "disallowed_packages": [],
        "disallowed_commands": [],
        "missing_files": [],
        "undefined_citations": [],
        "undefined_references": [],
        "overfull_box_warnings": [],
        "main_text_page_count": 8,
        "page_limit": 9,
        "references_appendix_excluded": True,
        "blockers": [],
    }

    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO topics
                (id, name, description, status, target_venue, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "workbench-topic",
                "Workbench topic",
                "active",
                "NeurIPS",
                "2026-07-01T00:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO orchestrator_runs
                (id, topic_id, mode, current_stage, stage_status, gate_status,
                 blocking_issue_count, unresolved_issue_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                5,
                1,
                "demo",
                "PW04_EXPERIMENT_AND_RESULT_TO_CLAIM",
                "running",
                "needs_review",
                0,
                1,
                "2026-07-01T00:01:00Z",
                "2026-07-01T00:02:00Z",
            ),
        )
        conn.executemany(
            """
            INSERT INTO project_artifacts
                (id, topic_id, stage, artifact_type, status, version, title,
                 payload_json, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    10,
                    1,
                    "PW05_PAPER_PLAN_AND_LOGIC_GATES",
                    "research_hypothesis_tree",
                    "active",
                    1,
                    "Hypothesis Tree",
                    json.dumps(hypothesis_tree),
                    "{}",
                    "2026-07-01T00:03:00Z",
                    "2026-07-01T00:03:00Z",
                ),
                (
                    20,
                    1,
                    "PW04_EXPERIMENT_AND_RESULT_TO_CLAIM",
                    "hypothesis_experiment_job",
                    "active",
                    1,
                    "Hypothesis Job",
                    json.dumps(job_payload),
                    "{}",
                    "2026-07-01T00:04:00Z",
                    "2026-07-01T00:04:00Z",
                ),
                (
                    30,
                    1,
                    "PW08_LATEX_FINAL_BUNDLE_AND_PDF",
                    "final_bundle",
                    "active",
                    1,
                    "Final Bundle",
                    json.dumps({"pdf_path": "paper.pdf", "status": "active"}),
                    "{}",
                    "2026-07-01T00:05:00Z",
                    "2026-07-01T00:05:00Z",
                ),
                (
                    31,
                    1,
                    "PW09_PRESUBMISSION_AUDIT_AND_PUBLICATION_PACK",
                    "publication_pack",
                    "active",
                    1,
                    "Publication Pack",
                    json.dumps({"submission_ready": False}),
                    "{}",
                    "2026-07-01T00:06:00Z",
                    "2026-07-01T00:06:00Z",
                ),
                (
                    32,
                    1,
                    "PW09_PRESUBMISSION_AUDIT_AND_PUBLICATION_PACK",
                    "venue_compliance_report",
                    "active",
                    1,
                    "Venue Compliance",
                    json.dumps(venue_payload),
                    "{}",
                    "2026-07-01T00:07:00Z",
                    "2026-07-01T00:07:00Z",
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO async_jobs
                (id, job_type, status, topic_id, input_params, result,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                99,
                "hypothesis_experiment",
                "running",
                1,
                json.dumps({"hypothesis_id": "h1", "max_attempts": 2}),
                None,
                "2026-07-01T00:08:00Z",
                "2026-07-01T00:08:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO runtime_events
                (event_id, trace_id, event_type, origin_surface, actor, topic_id,
                 job_id, schema_version, payload_json, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                "trace-1",
                "hypothesis_experiment.started",
                "auto_runner",
                "rh",
                1,
                "99",
                "rh.runtime_event.v1",
                json.dumps({"hypothesis_id": "h1"}),
                "{}",
                "2026-07-01T00:09:00Z",
            ),
        )
        conn.commit()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        client = TestClient(http_api.app)
        topics = client.get("/api/workbench/topics")
        runs = client.get("/api/workbench/paper-production-runs")
        snapshot = client.get("/api/workbench/topics/1/run-snapshot")
        tree = client.get("/api/workbench/topics/1/hypothesis-tree")
        detail = client.get("/api/workbench/topics/1/hypotheses/h1")
        jobs = client.get("/api/workbench/topics/1/experiment-jobs")
        pack_status = client.get("/api/workbench/topics/1/pack-status")
        venue = client.get("/api/workbench/topics/1/venue-compliance")
        doctor = client.get("/api/workbench/doctor")
    finally:
        http_api.DB_PATH = original_db_path

    assert topics.status_code == 200, topics.text
    assert topics.json()["topics"][0]["id"] == 1
    assert runs.status_code == 200, runs.text
    assert runs.json()["runs"][0]["current_stage"] == (
        "PW04_EXPERIMENT_AND_RESULT_TO_CLAIM"
    )
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["schema_version"] == "rh.paper_production_run_snapshot.v1"
    assert snapshot.json()["supported"] == 1
    assert snapshot.json()["final_bundle_ready"] is True
    assert snapshot.json()["publication_pack_ready"] is True
    assert snapshot.json()["venue_compliance_ready"] is True
    assert tree.status_code == 200, tree.text
    assert tree.json()["status_summary"]["untested"] == 1
    assert detail.status_code == 200, detail.text
    assert detail.json()["hypothesis"]["id"] == "h1"
    assert jobs.status_code == 200, jobs.text
    assert [job["hypothesis_id"] for job in jobs.json()["jobs"]] == ["h1", "h1"]
    assert pack_status.status_code == 200, pack_status.text
    assert pack_status.json()["final_bundle"]["ready"] is True
    assert pack_status.json()["publication_pack"]["artifact_id"] == 31
    assert venue.status_code == 200, venue.text
    assert venue.json()["status"] == "passed"
    assert doctor.status_code == 200, doctor.text
    assert doctor.json()["status"] == "ok"


def test_workbench_topic_routes_return_404_for_missing_topic(tmp_path: Path) -> None:
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "workbench-http-404.db"
    Database(db_path).migrate()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        response = TestClient(http_api.app).get(
            "/api/workbench/topics/999/run-snapshot"
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert response.status_code == 404
    assert response.json() == {"detail": "Topic 999 not found"}


def test_workbench_normalizes_failing_venue_compliance_report(tmp_path: Path) -> None:
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "workbench-http-venue-fail.db"
    db = Database(db_path)
    db.migrate()
    legacy_payload = {
        "topic_id": 1,
        "target_profile": "AAAI-style",
        "status": "fail",
        "passed": False,
        "blocking_findings": [
            {
                "check": "venue_source_lint",
                "passed": False,
                "finding": "LaTeX source/log lint found missing files.",
            }
        ],
        "checks": [
            {"check": "venue_pdf_compile", "passed": True},
            {"check": "venue_source_lint", "passed": False},
        ],
    }

    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO topics
                (id, name, description, status, target_venue, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "failing-venue-topic",
                "Failing venue topic",
                "active",
                "AAAI",
                "2026-07-01T00:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (id, topic_id, stage, artifact_type, status, version, title,
                 payload_json, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                10,
                1,
                "PW09_PRESUBMISSION_AUDIT_AND_PUBLICATION_PACK",
                "venue_compliance_report",
                "active",
                1,
                "Legacy Venue Compliance",
                json.dumps(legacy_payload),
                "{}",
                "2026-07-01T00:01:00Z",
                "2026-07-01T00:01:00Z",
            ),
        )
        conn.commit()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        client = TestClient(http_api.app)
        venue = client.get("/api/workbench/topics/1/venue-compliance")
        pack_status = client.get("/api/workbench/topics/1/pack-status")
        snapshot = client.get("/api/workbench/topics/1/run-snapshot")
    finally:
        http_api.DB_PATH = original_db_path

    assert venue.status_code == 200, venue.text
    assert venue.json()["schema_version"] == "rh.venue_compliance_report.v1"
    assert venue.json()["status"] == "fail"
    assert venue.json()["latex_compile_success"] is True
    assert venue.json()["blockers"] == ["venue_source_lint:failed"]
    assert pack_status.status_code == 200, pack_status.text
    assert pack_status.json()["venue_compliance"]["ready"] is False
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["venue_compliance_ready"] is False
    assert "venue_compliance:not_ready" in snapshot.json()["blockers"]


def test_workbench_create_topic_creates_topic_and_run(tmp_path: Path) -> None:
    from research_harness.storage.db import Database
    from research_harness_mcp import http_api

    db_path = tmp_path / "workbench-create.db"
    Database(db_path).migrate()

    original_db_path = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        client = TestClient(http_api.app)
        created = client.post(
            "/api/workbench/topics",
            json={
                "name": "web-created-topic",
                "description": "Started from the workbench",
                "target_venue": "NeurIPS",
                "deadline": "2026-09-01",
                "mode": "standard",
            },
        )
        # The new topic and its run must be visible through the read endpoints.
        topics = client.get("/api/workbench/topics")
        runs = client.get("/api/workbench/paper-production-runs")

        # A duplicate name is rejected instead of silently reused.
        duplicate = client.post(
            "/api/workbench/topics", json={"name": "web-created-topic"}
        )
        # An empty name is a client error.
        blank = client.post("/api/workbench/topics", json={"name": "   "})
        # An unknown mode is rejected.
        bad_mode = client.post(
            "/api/workbench/topics",
            json={"name": "another-topic", "mode": "turbo"},
        )
    finally:
        http_api.DB_PATH = original_db_path

    assert created.status_code == 201, created.text
    body = created.json()
    topic_id = int(body["topic"]["id"])
    assert body["topic"]["name"] == "web-created-topic"
    assert body["topic"]["description"] == "Started from the workbench"
    assert body["run"]["id"]

    assert topics.status_code == 200, topics.text
    listed = {row["id"]: row for row in topics.json()["topics"]}
    assert topic_id in listed
    assert listed[topic_id]["target_venue"] == "NeurIPS"
    assert listed[topic_id]["deadline"] == "2026-09-01"

    assert runs.status_code == 200, runs.text
    assert any(run["topic_id"] == topic_id for run in runs.json()["runs"])

    assert duplicate.status_code == 409, duplicate.text
    assert blank.status_code == 422, blank.text
    assert bad_mode.status_code == 422, bad_mode.text
