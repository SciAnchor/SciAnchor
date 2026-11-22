from __future__ import annotations

from pathlib import Path


def test_python_facade_paper_methods_route_through_research_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.api as api_module
    from research_harness.service import ServiceResult

    calls: list[tuple[str, dict, object]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments), self.db))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={"command": name, "arguments": dict(arguments)},
            )

    monkeypatch.setattr(api_module, "ResearchService", FakeService)

    api = api_module.ResearchAPI(db_path=tmp_path / "facade.db")

    assert api.paper_search("service query", topic_id=7) == {
        "command": "paper_search",
        "arguments": {"query": "service query", "topic_id": 7},
    }
    assert api.paper_ingest("10.1000/service", relevance="high") == {
        "command": "paper_ingest",
        "arguments": {"source": "10.1000/service", "relevance": "high"},
    }

    assert [call[0] for call in calls] == ["paper_search", "paper_ingest"]
    assert all(call[2] is api.db for call in calls)


def test_python_facade_execute_primitive_routes_public_actions_through_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.api as api_module
    from research_harness.service import ServiceResult

    calls: list[tuple[str, dict]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={"service_output": name},
            )

    monkeypatch.setattr(api_module, "ResearchService", FakeService)

    api = api_module.ResearchAPI(db_path=tmp_path / "execute.db")

    arguments = {
        "topic_id": 2,
        "paper_id": 1,
        "paper_ids": [1],
        "claim_id": "c1",
        "source_type": "paper",
        "source_id": "1",
    }
    for primitive in sorted(api_module._SERVICE_ROUTED_PRIMITIVES):
        assert api.execute_primitive(primitive, **arguments) == {
            "service_output": primitive
        }

    assert calls == [
        (primitive, arguments)
        for primitive in sorted(api_module._SERVICE_ROUTED_PRIMITIVES)
    ]


def test_python_facade_record_artifact_routes_through_research_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.api as api_module
    from research_harness.service import ServiceResult

    calls: list[tuple[str, dict]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={
                    "success": True,
                    "artifact_id": 123,
                    "version": 1,
                    "stage": arguments["stage"],
                    "type": arguments["artifact_type"],
                },
            )

    monkeypatch.setattr(api_module, "ResearchService", FakeService)

    api = api_module.ResearchAPI(db_path=tmp_path / "artifact.db")

    assert api.record_artifact(
        topic_id=5,
        stage="build",
        artifact_type="topic_brief",
        title="Brief",
        payload={"ok": True},
        dependency_artifact_ids=[10],
    ) == {
        "success": True,
        "artifact_id": 123,
        "version": 1,
        "stage": "build",
        "type": "topic_brief",
    }
    assert calls == [
        (
            "orchestrator_record_artifact",
            {
                "topic_id": 5,
                "stage": "build",
                "artifact_type": "topic_brief",
                "title": "Brief",
                "payload": {"ok": True},
                "dependency_artifact_ids": [10],
                "dependency_type": "consumed_by",
            },
        )
    ]


def test_python_facade_wiki_context_pack_routes_through_research_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.api as api_module
    from research_harness.service import ServiceResult

    calls: list[tuple[str, dict, object]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments), self.db))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={
                    "schema_version": "wiki_context_pack.v1",
                    "paper_wiki_status": "loaded",
                    "topic_id": arguments["topic_id"],
                },
            )

    monkeypatch.setattr(api_module, "ResearchService", FakeService)

    api = api_module.ResearchAPI(db_path=tmp_path / "wiki-context.db")

    assert api.wiki_context_pack(
        topic_id=7,
        query="hybrid retrieval",
        action_name="paper_writing",
        max_pages=4,
    ) == {
        "schema_version": "wiki_context_pack.v1",
        "paper_wiki_status": "loaded",
        "topic_id": 7,
    }
    assert calls == [
        (
            "wiki_context_pack",
            {
                "topic_id": 7,
                "query": "hybrid retrieval",
                "action_name": "paper_writing",
                "max_pages": 4,
            },
            api.db,
        )
    ]


def test_python_facade_wiki_context_pack_can_infer_workspace_topic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.api as api_module
    from research_harness.service import ServiceResult

    workspace = tmp_path / "rh-workspace" / "demo-topic"
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text(
        "# Demo\n\nCanonical Research Harness topic: `demo` (topic id: 12).\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={
                    "schema_version": "wiki_context_pack.v1",
                    "paper_wiki_status": "loaded",
                    "topic_id": arguments["topic_id"],
                },
            )

    monkeypatch.setattr(api_module, "ResearchService", FakeService)

    api = api_module.ResearchAPI(db_path=tmp_path / "wiki-context.db")

    payload = api.wiki_context_pack(
        workspace_path=workspace,
        action_name="method_improvement",
    )

    assert payload["topic_id"] == 12
    assert calls == [
        (
            "wiki_context_pack",
            {"action_name": "method_improvement", "topic_id": 12},
        )
    ]


def test_python_facade_wiki_context_pack_reports_not_triggered_without_topic(
    tmp_path: Path,
) -> None:
    import research_harness.api as api_module

    workspace = tmp_path / "rh-workspace" / "missing-topic"
    workspace.mkdir(parents=True)
    api = api_module.ResearchAPI(db_path=tmp_path / "wiki-context.db")

    assert api.wiki_context_pack(workspace_path=workspace) == {
        "schema_version": "wiki_context_pack.v1",
        "topic_id": None,
        "paper_wiki_status": "not_triggered",
        "status_reason": "topic_id_not_resolved",
        "unavailable_reasons": [
            "no topic_id was provided and no RH topic id was found in the requested workspace"
        ],
        "warnings": [],
        "preflight": {
            "priority_evidence_layer": "",
            "fallback_allowed": True,
            "fallback_must_be_declared": True,
        },
        "pages": [],
    }


def test_python_facade_delivery_snapshot_routes_through_research_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.api as api_module
    from research_harness.service import ServiceResult

    calls: list[tuple[str, dict, object]] = []

    class FakeService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments), self.db))
            return ServiceResult(
                command=name,
                status="success",
                summary="ok",
                output={
                    "schema_version": "rh.delivery.paper_production_snapshot.v1",
                    "status": "blocked",
                    "next_artifact": "",
                    "next_action": "none",
                    "summary": {
                        "total": 13,
                        "satisfied": 0,
                        "ready_to_advance": 0,
                        "blocked": 13,
                    },
                    "records": [],
                    "blockers": ["missing_payload:RESEARCH_BRIEF"],
                    "dry_run": True,
                },
            )

    monkeypatch.setattr(api_module, "ResearchService", FakeService)

    api = api_module.ResearchAPI(db_path=tmp_path / "delivery-service.db")
    payload = api.delivery_paper_production_snapshot(
        topic_id=2,
        artifact_states={"RESEARCH_BRIEF": "active"},
        payloads={"IDEA_REPORT": {"schema_version": "rh.delivery.idea_report.v1"}},
    )

    assert payload["schema_version"] == "rh.delivery.paper_production_snapshot.v1"
    assert calls == [
        (
            "delivery_paper_production_snapshot",
            {
                "topic_id": 2,
                "artifact_states": {"RESEARCH_BRIEF": "active"},
                "payloads": {
                    "IDEA_REPORT": {"schema_version": "rh.delivery.idea_report.v1"}
                },
            },
            api.db,
        )
    ]


def test_python_facade_delivery_snapshot_docstring_names_boundary_contract() -> None:
    import research_harness.api as api_module

    docstring = api_module.ResearchAPI.delivery_paper_production_snapshot.__doc__
    assert docstring is not None
    normalized = " ".join(docstring.split())

    assert "rh.delivery.paper_production_snapshot.v1" in normalized
    assert "topic_id" in normalized
    assert "artifact_states" in normalized
    assert "payloads" in normalized
    assert "dry_run" in normalized
    assert "does not call orchestrator_record_artifact" in normalized
    assert "does not advance stages" in normalized
    assert "does not write artifacts" in normalized
    assert "does not expose MCP, CLI, or HTTP transport" in normalized


def test_python_facade_delivery_snapshot_returns_shape_locked_dry_run_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.api as api_module
    import research_harness.service.handlers as handlers_module

    artifact_write_calls: list[dict] = []

    def fake_record_artifact(ctx, arguments: dict):
        artifact_write_calls.append(dict(arguments))
        raise AssertionError("delivery snapshot must not invoke artifact writes")

    monkeypatch.setattr(
        handlers_module,
        "orchestrator_record_artifact",
        fake_record_artifact,
    )
    api = api_module.ResearchAPI(db_path=tmp_path / "delivery.db")
    before_count = _project_artifact_count(api.db, topic_id=1)
    snapshot = api.delivery_paper_production_snapshot(
        artifact_states={"RESEARCH_BRIEF": "active"},
        payloads={
            "IDEA_REPORT": {
                "schema_version": "rh.delivery.idea_report.v1",
                "recording_surface": "orchestrator_record_artifact",
                "public_surface": "none",
                "runtime_dependency": "none",
                "observed_problem": "Paper production can drift from evidence.",
                "candidate_opportunity": "Protocol-bound paper production.",
                "in_domain_evidence": ["paper:p1"],
                "cross_topic_analogies": [],
                "novelty_risks": ["needs stronger baseline positioning"],
                "evidence_anchors": ["paper:p1"],
                "support_status": "seeded",
                "missing_evidence_warnings": [],
                "promotion_blockers": [],
            }
        },
    )

    assert snapshot["schema_version"] == "rh.delivery.paper_production_snapshot.v1"
    assert snapshot["status"] == "in_progress"
    assert snapshot["next_artifact"] == "IDEA_REPORT"
    assert snapshot["next_action"] == "record_artifact_intent"
    assert snapshot["summary"] == {
        "total": 13,
        "satisfied": 1,
        "ready_to_advance": 1,
        "blocked": 11,
    }
    assert snapshot["records"][0]["artifact"] == "RESEARCH_BRIEF"
    assert snapshot["records"][1]["artifact"] == "IDEA_REPORT"
    assert snapshot["blockers"] == []
    assert snapshot["dry_run"] is True
    assert artifact_write_calls == []
    assert _project_artifact_count(api.db, topic_id=1) == before_count


def test_python_facade_delivery_snapshot_surfaces_invalid_payload_blocker(
    tmp_path: Path,
) -> None:
    import research_harness.api as api_module

    api = api_module.ResearchAPI(db_path=tmp_path / "delivery-invalid.db")
    snapshot = api.delivery_paper_production_snapshot(
        artifact_states={"RESEARCH_BRIEF": "active"},
        payloads={
            "IDEA_REPORT": {
                "schema_version": "rh.delivery.idea_report.v1",
                "recording_surface": "orchestrator_record_artifact",
                "public_surface": "none",
                "runtime_dependency": "external_runtime",
            }
        },
    )

    assert snapshot["schema_version"] == "rh.delivery.paper_production_snapshot.v1"
    assert snapshot["status"] == "blocked"
    assert snapshot["next_action"] == "repair_payload"
    assert "boundary:runtime_dependency" in snapshot["blockers"]
    assert snapshot["records"][1]["status"] == "blocked"
    assert snapshot["dry_run"] is True


def test_python_facade_delivery_snapshot_can_read_topic_artifact_state(
    tmp_path: Path,
) -> None:
    import research_harness.api as api_module

    api = api_module.ResearchAPI(db_path=tmp_path / "delivery-topic.db")
    _seed_topic_bridge(api.db, topic_id=1)
    api.record_artifact(
        topic_id=1,
        stage="init",
        artifact_type="RESEARCH_BRIEF",
        title="Recorded brief",
        payload={"topic_statement": "Protocol-bound paper production"},
    )
    before_count = _project_artifact_count(api.db, topic_id=1)

    snapshot = api.delivery_paper_production_snapshot(topic_id=1)

    assert snapshot["schema_version"] == "rh.delivery.paper_production_snapshot.v1"
    assert snapshot["records"][0]["artifact"] == "RESEARCH_BRIEF"
    assert snapshot["records"][0]["status"] == "satisfied"
    assert snapshot["summary"]["satisfied"] == 1
    assert snapshot["next_action"] == "provide_payload"
    assert "missing_payload:IDEA_REPORT" in snapshot["blockers"]
    assert _project_artifact_count(api.db, topic_id=1) == before_count


def test_python_facade_delivery_snapshot_does_not_satisfy_stale_topic_artifact(
    tmp_path: Path,
) -> None:
    import research_harness.api as api_module

    api = api_module.ResearchAPI(db_path=tmp_path / "delivery-stale-topic.db")
    _seed_topic_bridge(api.db, topic_id=1)
    artifact = api.record_artifact(
        topic_id=1,
        stage="init",
        artifact_type="research_brief",
        title="Stale brief",
        payload={"topic_statement": "Stale protocol state"},
    )
    api.mark_artifact_stale(artifact["artifact_id"], reason="test stale")

    snapshot = api.delivery_paper_production_snapshot(topic_id=1)

    assert snapshot["records"][0]["artifact"] == "RESEARCH_BRIEF"
    assert snapshot["records"][0]["status"] == "blocked"
    assert "stale:RESEARCH_BRIEF" in snapshot["records"][0]["blockers"]
    assert "stale:RESEARCH_BRIEF" in snapshot["blockers"]


def test_python_facade_delivery_snapshot_explicit_state_overrides_topic_state(
    tmp_path: Path,
) -> None:
    import research_harness.api as api_module

    api = api_module.ResearchAPI(db_path=tmp_path / "delivery-override.db")
    _seed_topic_bridge(api.db, topic_id=1)
    artifact = api.record_artifact(
        topic_id=1,
        stage="init",
        artifact_type="research-brief",
        title="Recorded brief",
        payload={"topic_statement": "Protocol-bound paper production"},
    )
    api.mark_artifact_stale(artifact["artifact_id"], reason="test stale")

    snapshot = api.delivery_paper_production_snapshot(
        topic_id=1,
        artifact_states={"RESEARCH_BRIEF": "active"},
    )

    assert snapshot["records"][0]["artifact"] == "RESEARCH_BRIEF"
    assert snapshot["records"][0]["status"] == "satisfied"
    assert "stale:RESEARCH_BRIEF" not in snapshot["blockers"]
    assert snapshot["inputs"] == {
        "topic_id": 1,
        "artifact_states": {
            "topic": ["RESEARCH_BRIEF"],
            "explicit": ["RESEARCH_BRIEF"],
            "resolved": ["RESEARCH_BRIEF"],
            "sources": {"RESEARCH_BRIEF": "explicit"},
        },
        "payloads": [],
        "counts": {
            "topic_artifact_states": 1,
            "explicit_artifact_states": 1,
            "resolved_artifact_states": 1,
            "payloads": 0,
        },
    }


def test_python_facade_delivery_snapshot_inputs_do_not_expose_payload_contents(
    tmp_path: Path,
) -> None:
    import research_harness.api as api_module

    api = api_module.ResearchAPI(db_path=tmp_path / "delivery-redaction.db")
    sentinel = "PAYLOAD_SECRET_SENTINEL_SHOULD_NOT_LEAK"

    snapshot = api.delivery_paper_production_snapshot(
        artifact_states={"RESEARCH_BRIEF": "active"},
        payloads={
            "IDEA_REPORT": {
                "schema_version": "rh.delivery.idea_report.v1",
                "recording_surface": "orchestrator_record_artifact",
                "public_surface": "none",
                "runtime_dependency": "none",
                "observed_problem": sentinel,
                "candidate_opportunity": "Protocol-bound paper production.",
                "in_domain_evidence": ["paper:p1"],
                "cross_topic_analogies": [],
                "novelty_risks": [],
                "evidence_anchors": ["paper:p1"],
                "support_status": "seeded",
                "missing_evidence_warnings": [],
                "promotion_blockers": [],
            }
        },
    )

    assert snapshot["inputs"]["payloads"] == ["IDEA_REPORT"]
    assert snapshot["inputs"]["counts"]["payloads"] == 1
    assert sentinel not in repr(snapshot["inputs"])


def _seed_topic_bridge(db, *, topic_id: int) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description) VALUES (?, ?, ?)",
            (topic_id, f"topic-{topic_id}", "Delivery facade test topic"),
        )
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (?, ?, ?, ?)",
            (topic_id, topic_id, f"project-{topic_id}", "Delivery facade test"),
        )
        conn.commit()
    finally:
        conn.close()


def _project_artifact_count(db, *, topic_id: int) -> int:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM project_artifacts WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        return int(row["count"])
    finally:
        conn.close()


def test_facade_does_not_send_an_unset_keyword_as_null(tmp_path, monkeypatch):
    """Every facade call routes through _invoke_service_output; a keyword left at None is omitted,
    since the strict service contract rejects an explicit null for an optional property."""
    from research_harness import api as api_module

    seen = {}

    class Service:
        def __init__(self, db):
            pass

        def invoke(self, name, arguments):
            seen[name] = dict(arguments)

            class Result:
                status, output, error, summary = "success", {"ok": True}, None, ""

            return Result()

    monkeypatch.setattr(api_module, "ResearchService", Service)
    facade = api_module.ResearchAPI.__new__(api_module.ResearchAPI)
    facade._db = None
    facade.delivery_paper_production_snapshot(
        topic_id=None, artifact_states=None, payloads=None
    )
    assert seen["delivery_paper_production_snapshot"] == {}
    facade.wiki_context_pack(topic_id=7, anchor_paper_id=None)
    assert "anchor_paper_id" not in seen["wiki_context_pack"]
