from __future__ import annotations

from types import SimpleNamespace

from research_harness.api import ResearchAPI
from research_harness.storage.db import Database


def test_api_artifact_dependency_and_stale(tmp_path):
    db_path = tmp_path / "api.db"
    db = Database(db_path)
    db.migrate()

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description) VALUES (1, ?, ?)",
            ("api-topic", "API topic"),
        )
        # Bridge row: project_artifacts.project_id FK still references projects(id)
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, ?, ?)",
            ("api-topic", "API topic"),
        )
        conn.commit()
    finally:
        conn.close()

    api = ResearchAPI(db_path=db_path)
    upstream = api.record_artifact(
        topic_id=1,
        stage="build",
        artifact_type="literature_map",
        payload={"v": 1},
    )
    downstream = api.record_artifact(
        topic_id=1,
        stage="analyze",
        artifact_type="gap_analysis",
        payload={"v": 1},
        dependency_artifact_ids=[upstream["artifact_id"]],
    )

    api.record_artifact(
        topic_id=1,
        stage="build",
        artifact_type="literature_map",
        payload={"v": 2},
    )

    stale = api.list_stale_artifacts(1)
    assert any(item["id"] == downstream["artifact_id"] for item in stale)

    cleared = api.clear_artifact_stale(downstream["artifact_id"])
    assert cleared["success"] is True


def test_api_orchestrator_status_routes_through_research_service(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(
                status="success",
                output={
                    "run": {"topic_id": 7, "current_stage": "init"},
                    "stage": {"missing_artifacts": []},
                    "gate": {"decision": "pass", "can_advance": True},
                    "db_path": str(db_path),
                },
                error=None,
            )

    monkeypatch.setattr(
        "research_harness.api.ResearchService", FakeResearchService, raising=False
    )

    api = ResearchAPI(db_path=db_path)
    status = api.orchestrator_status(topic_id=7)

    assert calls == [("orchestrator_status", {"topic_id": 7})]
    assert status["run"]["topic_id"] == 7
    assert status["run"]["current_stage"] == "init"
    assert status["db_path"] == str(db_path)


def test_api_gate_check_routes_through_research_service(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(
                status="success",
                output={"gate_decision": "needs_approval"},
                error=None,
            )

    monkeypatch.setattr(
        "research_harness.api.ResearchService", FakeResearchService, raising=False
    )

    api = ResearchAPI(db_path=db_path)
    decision = api.gate_check(topic_id=7, stage="topic_framing")

    assert calls == [
        (
            "orchestrator_gate_check",
            {"topic_id": 7, "stage": "topic_framing"},
        )
    ]
    assert decision == {"gate_decision": "needs_approval"}
