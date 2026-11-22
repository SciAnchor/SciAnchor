from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from research_harness.service import ResearchService


SERVICE_BACKED_PUBLIC_COMMANDS = [
    "topic_list",
    "topic_show",
    "topic_state",
    "paper_list",
    "provenance_summary",
    "provenance_export",
    "orchestrator_status",
    "resource_ready_get",
    "orchestrator_gate_check",
    "orchestrator_resume",
    "orchestrator_advance",
    "orchestrator_record_artifact",
    "paper_commit_version",
    "paper_task_intake",
    "topic_init",
    "paper_production_start",
    "paper_production_pending_decisions",
    "paper_production_decide",
    "paper_production_status",
    "paper_production_resume",
    "paper_production_mode",
    "paper_production_set_mode",
    "paper_production_export",
    "adversarial_review",
    "advisory_check",
    "zotero_sync",
    "paperindex_search",
    "skill_list",
    "skill_get",
    "productization_boundary",
    "topic_knowledge_status",
    "topic_knowledge_refresh",
    "cross_topic_atlas",
]

PUBLIC_PRIMITIVE_COMMANDS = [
    "paper_search",
    "paper_ingest",
    "paper_summarize",
    "claim_extract",
    "evidence_link",
    "gap_detect",
    "baseline_identify",
    "section_draft",
    "figure_generate",
    "consistency_check",
    "exemplar_curate",
    "exemplar_retrieve",
    "exemplar_plan",
    "exemplar_generate",
    "exemplar_critique",
    "figure_suite_plan",
    "figure_suite_render",
    "figure_package",
    "manuscript_review",
    "manuscript_polish",
]

ROUTED_PUBLIC_PRIMITIVE_COMMANDS = [
    "paper_search",
    "paper_ingest",
    "paper_summarize",
    "claim_extract",
    "evidence_link",
    "gap_detect",
    "baseline_identify",
    "section_draft",
    "figure_generate",
    "consistency_check",
    "exemplar_curate",
    "exemplar_retrieve",
    "exemplar_plan",
    "exemplar_generate",
    "exemplar_critique",
    "figure_suite_plan",
    "figure_suite_render",
    "figure_package",
    "manuscript_review",
    "manuscript_polish",
]

REGISTERED_ONLY_PUBLIC_PRIMITIVE_COMMANDS = [
    name
    for name in PUBLIC_PRIMITIVE_COMMANDS
    if name not in ROUTED_PUBLIC_PRIMITIVE_COMMANDS
]

REGISTERED_ONLY_ARGUMENTS = {
    "paper_ingest": {"source": "10.1000/test"},
    "claim_extract": {"paper_ids": [1], "topic_id": 1},
    "evidence_link": {"claim_id": "c1", "source_type": "paper", "source_id": "1"},
    "gap_detect": {"topic_id": 1},
    "baseline_identify": {"topic_id": 1},
    "section_draft": {"topic_id": 1, "section": "related_work"},
}


def _passing_fine_logic_audit_report() -> dict[str, object]:
    return {
        "schema_version": "rh.manuscript.fine_logic_audit_report.v1",
        "status": "pass",
        "blockers": [],
    }


def _assert_json_schema_value(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str = "payload",
) -> None:
    if "const" in schema:
        assert value == schema["const"], f"{path} must equal {schema['const']!r}"

    expected_type = schema.get("type")
    if expected_type is not None:
        assert _matches_json_schema_type(value, expected_type), (
            f"{path} must be {expected_type!r}; got {type(value).__name__}"
        )

    enum_values = schema.get("enum")
    if enum_values is not None:
        assert value in enum_values, f"{path} must be one of {enum_values!r}"

    minimum = schema.get("minimum")
    if minimum is not None:
        assert value >= minimum, f"{path} must be >= {minimum!r}"

    if expected_type == "object":
        assert isinstance(value, Mapping), f"{path} must be object"
        properties = schema.get("properties") or {}
        for name in schema.get("required") or []:
            assert name in value, f"{path}.{name} is required"
        for name, property_schema in properties.items():
            if name in value:
                _assert_json_schema_value(
                    value[name],
                    property_schema,
                    path=f"{path}.{name}",
                )
        additional_properties = schema.get("additionalProperties", True)
        if additional_properties is False:
            assert set(value).issubset(properties), (
                f"{path} has unexpected keys: {sorted(set(value) - set(properties))}"
            )
        elif isinstance(additional_properties, Mapping):
            for name, item in value.items():
                if name in properties:
                    continue
                _assert_json_schema_value(
                    item,
                    additional_properties,
                    path=f"{path}.{name}",
                )

    if expected_type == "array":
        assert isinstance(value, list), f"{path} must be array"
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _assert_json_schema_value(item, item_schema, path=f"{path}[{index}]")


def _matches_json_schema_type(value: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_json_schema_type(value, item) for item in expected_type)
    if expected_type == "object":
        return isinstance(value, Mapping)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _seed_topic(conn, name: str = "rh-selfdev") -> int:
    cur = conn.execute(
        "INSERT INTO topics (name, description, status) VALUES (?, ?, ?)",
        (name, "Self-development topic", "active"),
    )
    return int(cur.lastrowid)


def _seed_paper(conn, *, topic_id: int | None = None) -> int:
    cur = conn.execute(
        """
        INSERT INTO papers
            (title, authors, year, venue, url, affiliations, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "Service Dispatcher Contracts",
            json.dumps(["Ada Lovelace"]),
            2026,
            "ICSE",
            "https://example.test/service",
            json.dumps(["Analytical Engine Lab"]),
            "meta_only",
        ),
    )
    paper_id = int(cur.lastrowid)
    if topic_id is not None:
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
            (paper_id, topic_id, "high"),
        )
    return paper_id


def _record_provenance(db, *, topic_id: int | None = None) -> int:
    from research_harness.primitives.types import PrimitiveResult
    from research_harness.provenance.recorder import ProvenanceRecorder

    return ProvenanceRecorder(db).record(
        PrimitiveResult(
            primitive="paper_ingest",
            success=True,
            output={"paper_id": 1},
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:01+00:00",
            backend="local",
            model_used="",
            cost_usd=0.25,
            prompt_tokens=11,
            completion_tokens=7,
        ),
        input_kwargs={"source": "10.1000/test"},
        topic_id=topic_id,
    )


def _seed_topic_project(conn, name: str = "orch-topic") -> int:
    cur = conn.execute(
        "INSERT INTO topics (name, description, status) VALUES (?, ?, ?)",
        (name, "Orchestrator topic", "active"),
    )
    topic_id = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO projects (id, topic_id, name, description) VALUES (?, ?, ?, ?)",
        (topic_id, topic_id, "stub", "stub"),
    )
    return topic_id


def test_research_service_lists_registered_public_commands(db):
    service = ResearchService(db=db)

    commands = service.list_commands(visibility="public_mcp")

    assert [command.name for command in commands] == (
        SERVICE_BACKED_PUBLIC_COMMANDS + PUBLIC_PRIMITIVE_COMMANDS
    )
    assert all(command.input_schema["type"] == "object" for command in commands)


def test_wiki_context_pack_service_is_cli_python_only_not_public_mcp(db):
    service = ResearchService(db=db)
    commands = {command.name: command for command in service.list_commands()}

    command = commands["wiki_context_pack"]

    assert command.visibility == ("python", "cli")
    assert "public_mcp" not in command.visibility
    assert command.validation_policy == "strict"


def test_delivery_snapshot_service_is_python_only_not_public_mcp(db):
    service = ResearchService(db=db)
    commands = {command.name: command for command in service.list_commands()}

    command = commands["delivery_paper_production_snapshot"]

    assert command.visibility == ("python",)
    assert "public_mcp" not in command.visibility
    assert command.validation_policy == "strict"


def test_delivery_snapshot_service_command_contract_names_boundaries(db):
    service = ResearchService(db=db)
    commands = {command.name: command for command in service.list_commands()}

    command = commands["delivery_paper_production_snapshot"]
    description = command.description.lower()

    assert "rh.delivery.paper_production_snapshot.v1" in command.description
    assert "python-only" in description
    assert "dry-run" in description
    assert "no artifact writes" in description
    assert "no stage advancement" in description
    assert "orchestrator_record_artifact" in command.description
    assert "no mcp" in description
    assert "no cli" in description
    assert "no http" in description

    input_schema = command.input_schema
    assert input_schema["type"] == "object"
    assert input_schema["additionalProperties"] is False
    assert set(input_schema["properties"]) == {
        "topic_id",
        "artifact_states",
        "payloads",
    }
    assert "required" not in input_schema
    assert "optional" in input_schema["properties"]["topic_id"]["description"].lower()
    assert "read-only" in input_schema["properties"]["topic_id"]["description"].lower()
    assert (
        "override"
        in input_schema["properties"]["artifact_states"]["description"].lower()
    )
    assert (
        "payload content"
        in input_schema["properties"]["payloads"]["description"].lower()
    )


def test_delivery_snapshot_service_rejects_unregistered_input_fields(db):
    service = ResearchService(db=db)

    result = service.invoke(
        "delivery_paper_production_snapshot",
        {"topic_id": 1, "transport": "mcp"},
    )

    assert result.status == "error"
    assert result.error == {
        "code": "INVALID_ARGUMENT",
        "message": (
            "Invalid arguments for delivery_paper_production_snapshot: "
            "unexpected argument: transport"
        ),
    }


def test_delivery_snapshot_service_rejects_invalid_topic_id(db):
    service = ResearchService(db=db)

    result = service.invoke("delivery_paper_production_snapshot", {"topic_id": 0})

    assert result.status == "error"
    assert result.error == {
        "code": "INVALID_ARGUMENT",
        "message": (
            "Invalid arguments for delivery_paper_production_snapshot: "
            "topic_id must be >= 1"
        ),
    }


def test_delivery_snapshot_service_output_schema_contract(db):
    service = ResearchService(db=db)
    commands = {command.name: command for command in service.list_commands()}

    output_schema = commands["delivery_paper_production_snapshot"].output_schema

    assert output_schema["type"] == "object"
    assert output_schema["additionalProperties"] is False
    assert set(output_schema["required"]) == {
        "schema_version",
        "status",
        "next_artifact",
        "next_action",
        "summary",
        "records",
        "blockers",
        "dry_run",
        "inputs",
    }
    assert output_schema["properties"]["schema_version"]["const"] == (
        "rh.delivery.paper_production_snapshot.v1"
    )
    assert output_schema["properties"]["status"]["enum"] == [
        "not_started",
        "in_progress",
        "complete",
        "blocked",
    ]
    assert output_schema["properties"]["dry_run"]["const"] is True
    assert set(output_schema["properties"]["summary"]["required"]) == {
        "total",
        "satisfied",
        "ready_to_advance",
        "blocked",
    }
    assert output_schema["properties"]["records"]["type"] == "array"
    assert output_schema["properties"]["blockers"]["type"] == "array"
    assert output_schema["properties"]["inputs"]["type"] == "object"


def test_delivery_snapshot_service_records_schema_contract(db):
    service = ResearchService(db=db)
    commands = {command.name: command for command in service.list_commands()}

    records_schema = commands["delivery_paper_production_snapshot"].output_schema[
        "properties"
    ]["records"]
    item_schema = records_schema["items"]

    assert item_schema["type"] == "object"
    assert item_schema["additionalProperties"] is False
    assert set(item_schema["required"]) == {
        "entry_mode",
        "request",
        "artifact",
        "stage",
        "gate",
        "owner_skill",
        "recording_surface",
        "action",
        "status",
        "validation_status",
        "promotion_status",
        "blockers",
    }
    assert item_schema["properties"]["status"]["enum"] == [
        "satisfied",
        "ready_to_advance",
        "blocked",
    ]
    assert item_schema["properties"]["validation_status"]["type"] == "string"
    assert item_schema["properties"]["promotion_status"]["type"] == "string"
    assert item_schema["properties"]["blockers"]["type"] == "array"


def test_delivery_snapshot_service_inputs_schema_contract(db):
    service = ResearchService(db=db)
    commands = {command.name: command for command in service.list_commands()}

    inputs_schema = commands["delivery_paper_production_snapshot"].output_schema[
        "properties"
    ]["inputs"]

    assert inputs_schema["type"] == "object"
    assert inputs_schema["additionalProperties"] is False
    assert set(inputs_schema["required"]) == {
        "topic_id",
        "artifact_states",
        "payloads",
        "counts",
    }
    assert inputs_schema["properties"]["topic_id"]["type"] == ["integer", "null"]

    artifact_states_schema = inputs_schema["properties"]["artifact_states"]
    assert artifact_states_schema["type"] == "object"
    assert artifact_states_schema["additionalProperties"] is False
    assert set(artifact_states_schema["required"]) == {
        "topic",
        "explicit",
        "resolved",
        "sources",
    }
    assert artifact_states_schema["properties"]["topic"]["items"]["type"] == "string"
    assert artifact_states_schema["properties"]["explicit"]["items"]["type"] == (
        "string"
    )
    assert artifact_states_schema["properties"]["resolved"]["items"]["type"] == (
        "string"
    )
    assert artifact_states_schema["properties"]["sources"]["additionalProperties"] == {
        "type": "string"
    }

    assert inputs_schema["properties"]["payloads"]["items"]["type"] == "string"
    counts_schema = inputs_schema["properties"]["counts"]
    assert counts_schema["type"] == "object"
    assert counts_schema["additionalProperties"] is False
    assert set(counts_schema["required"]) == {
        "topic_artifact_states",
        "explicit_artifact_states",
        "resolved_artifact_states",
        "payloads",
    }


def test_delivery_snapshot_runtime_output_matches_registered_schema(db):
    service = ResearchService(db=db)
    commands = {command.name: command for command in service.list_commands()}

    result = service.invoke(
        "delivery_paper_production_snapshot",
        {
            "artifact_states": {"RESEARCH_BRIEF": "active"},
            "payloads": {
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
        },
    )

    assert result.status == "success"
    _assert_json_schema_value(
        result.output,
        commands["delivery_paper_production_snapshot"].output_schema,
    )


def test_public_primitive_commands_are_registered_or_routed_by_slice(db):
    service = ResearchService(db=db)
    commands = {command.name: command for command in service.list_commands()}

    for name in PUBLIC_PRIMITIVE_COMMANDS:
        command = commands[name]
        assert command.requires_db is True
        assert "public_mcp" in command.visibility

    for name in REGISTERED_ONLY_PUBLIC_PRIMITIVE_COMMANDS:
        result = service.invoke(name, REGISTERED_ONLY_ARGUMENTS[name])

        assert result.status == "error"
        assert result.command == name
        assert result.error == {
            "code": "COMMAND_NOT_ROUTED",
            "message": (
                "Primitive service command is registered but execution remains on "
                "the existing primitive transport path."
            ),
        }
        assert result.output["registered_only"] is True


def test_research_service_routes_paper_search_through_tracked_primitive(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import (
        PaperRef,
        PaperSearchOutput,
        PrimitiveResult,
    )

    conn = db.connect()
    try:
        topic_id = _seed_topic(conn, name="paper-search-topic")
        conn.commit()
    finally:
        conn.close()

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=PaperSearchOutput(
                papers=[PaperRef(title="Service Routed Search", year=2026)],
                provider="local",
                total_before_filter=1,
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:02+00:00",
            backend="local",
            model_used="",
            cost_usd=0.12,
            prompt_tokens=3,
            completion_tokens=5,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "paper_search",
        {"query": "service routing", "topic_id": topic_id},
    )
    payload = result.to_dict()

    assert calls == [
        ("paper_search", {"query": "service routing", "topic_id": topic_id})
    ]
    assert result.status == "success"
    assert payload["summary"] == "Found 1 papers via local"
    assert payload["output"]["papers"][0]["title"] == "Service Routed Search"
    assert payload["metadata"]["provenance_recorded_by"] == "TrackedBackend"
    assert payload["metadata"]["cost_usd"] == 0.12

    conn = db.connect()
    try:
        topic = conn.execute(
            "SELECT last_search_at FROM topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
        query = conn.execute(
            """
            SELECT last_searched_at FROM search_query_registry
            WHERE topic_id = ? AND query = ?
            """,
            (topic_id, "service routing"),
        ).fetchone()
    finally:
        conn.close()

    assert topic["last_search_at"]
    assert query["last_searched_at"]


def test_research_service_does_not_add_survey_first_public_arguments(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import (
        PaperSearchOutput,
        PrimitiveResult,
    )

    captured_arguments: list[dict] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        captured_arguments.append(dict(arguments))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=PaperSearchOutput(provider="local"),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:02+00:00",
            backend="local",
            model_used="",
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke("paper_search", {"query": "internal policy"})

    assert result.status == "success"
    assert captured_arguments == [{"query": "internal policy"}]
    payload = result.to_dict()
    assert "survey_first" not in payload["output"]
    assert "survey_first" not in payload["metadata"]


def test_research_service_reports_paper_search_freshness_update_failure(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import (
        PaperRef,
        PaperSearchOutput,
        PrimitiveResult,
    )

    class FailingFreshnessConnection:
        def execute(self, query, params=()):
            del query, params
            raise RuntimeError("freshness write unavailable")

        def commit(self):
            raise AssertionError("commit should not run after freshness failure")

        def close(self):
            pass

    class FailingFreshnessDb:
        def connect(self):
            return FailingFreshnessConnection()

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=PaperSearchOutput(
                papers=[PaperRef(title="Freshness Observable", year=2026)],
                provider="local",
                total_before_filter=1,
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:02+00:00",
            backend="local",
            model_used="",
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    monkeypatch.setattr(db, "connect", FailingFreshnessDb().connect)
    result = service.invoke(
        "paper_search",
        {"query": "freshness failure", "topic_id": 123},
    )

    assert result.status == "success"
    assert result.error is None
    assert result.output.papers[0].title == "Freshness Observable"
    assert result.metadata["freshness_update_status"] == "failed"
    assert result.metadata["freshness_update_error"] == (
        "paper_search freshness update failed"
    )


def test_research_service_routes_paper_ingest_through_tracked_primitive(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import PaperIngestOutput, PrimitiveResult

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=PaperIngestOutput(
                paper_id=42,
                title="Service Routed Ingest",
                status="new",
                merged_fields=["metadata_incomplete"],
                enriched_fields={"venue": "ICSE"},
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:04+00:00",
            backend="local",
            model_used="",
            cost_usd=0.02,
            prompt_tokens=0,
            completion_tokens=0,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "paper_ingest",
        {"source": "10.1000/service-route", "topic_id": 3, "relevance": "high"},
    )
    payload = result.to_dict()

    assert calls == [
        (
            "paper_ingest",
            {"source": "10.1000/service-route", "topic_id": 3, "relevance": "high"},
        )
    ]
    assert result.status == "success"
    assert payload["summary"] == (
        "Ingested: Service Routed Ingest (status=new), "
        "merged: metadata_incomplete, enriched: venue"
    )
    assert payload["output"] == {
        "paper_id": 42,
        "title": "Service Routed Ingest",
        "status": "new",
        "merged_fields": ["metadata_incomplete"],
        "enriched_fields": {"venue": "ICSE"},
        "duplicate_candidates": [],
        "html_ingest": {},
        "knowledge_refresh": {},
    }
    assert payload["next_actions"] == [
        "paper_acquire — download PDF and annotate the ingested paper",
        "paper_summarize — generate structured summary of the ingested paper",
    ]
    assert payload["artifacts"] == ["paper:42"]
    assert payload["metadata"]["provenance_recorded_by"] == "TrackedBackend"
    assert payload["metadata"]["backend"] == "local"
    assert payload["metadata"]["cost_usd"] == 0.02


def test_research_service_routes_paper_summarize_through_tracked_primitive(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import PrimitiveResult, SummaryOutput

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=SummaryOutput(
                paper_id=7,
                summary="Service routed summary",
                focus="method",
                confidence=0.91,
                model_used="local-test",
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:03+00:00",
            backend="local",
            model_used="local-test",
            cost_usd=0.03,
            prompt_tokens=13,
            completion_tokens=17,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "paper_summarize",
        {"paper_id": 7, "focus": "method"},
    )
    payload = result.to_dict()

    assert calls == [("paper_summarize", {"paper_id": 7, "focus": "method"})]
    assert result.status == "success"
    assert payload["output"] == {
        "paper_id": 7,
        "summary": "Service routed summary",
        "focus": "method",
        "confidence": 0.91,
        "model_used": "local-test",
    }
    assert payload["metadata"]["provenance_recorded_by"] == "TrackedBackend"
    assert payload["metadata"]["backend"] == "local"
    assert payload["metadata"]["cost_usd"] == 0.03


def test_research_service_routes_claim_extract_through_tracked_primitive(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import (
        Claim,
        ClaimExtractOutput,
        EvidenceSpan,
        PrimitiveResult,
    )

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=ClaimExtractOutput(
                claims=[
                    Claim(
                        claim_id="claim-service-route",
                        content="Service routing preserves claim evidence.",
                        paper_ids=[7],
                        evidence_type="finding",
                        confidence=0.88,
                        source_section="results",
                        evidence_spans=[
                            EvidenceSpan(
                                paper_id=7,
                                section="results",
                                snippet="service route evidence",
                            )
                        ],
                    )
                ],
                papers_processed=1,
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:05+00:00",
            backend="local",
            model_used="local-test",
            cost_usd=0.07,
            prompt_tokens=29,
            completion_tokens=31,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "claim_extract",
        {"paper_ids": [7], "topic_id": 3, "focus": "method"},
    )
    payload = result.to_dict()

    assert calls == [
        (
            "claim_extract",
            {"paper_ids": [7], "topic_id": 3, "focus": "method"},
        )
    ]
    assert result.status == "success"
    assert payload["output"]["papers_processed"] == 1
    assert payload["output"]["claims"][0]["claim_id"] == "claim-service-route"
    assert payload["output"]["claims"][0]["paper_ids"] == [7]
    assert payload["output"]["claims"][0]["evidence_spans"][0]["snippet"] == (
        "service route evidence"
    )
    assert payload["metadata"]["provenance_recorded_by"] == "TrackedBackend"
    assert payload["metadata"]["backend"] == "local"
    assert payload["metadata"]["cost_usd"] == 0.07


def test_research_service_routes_evidence_link_through_tracked_primitive(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import (
        EvidenceLink,
        EvidenceLinkOutput,
        EvidenceSpan,
        PrimitiveResult,
    )

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=EvidenceLinkOutput(
                link=EvidenceLink(
                    claim_id="claim-service-route",
                    source_type="paper",
                    source_id="42",
                    strength="strong",
                    support_status="supports",
                    evidence_span=EvidenceSpan(
                        paper_id=42,
                        section="results",
                        snippet="service route evidence",
                    ),
                ),
                created=True,
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:03+00:00",
            backend="local",
            model_used="local-test",
            cost_usd=0.04,
            prompt_tokens=17,
            completion_tokens=19,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "evidence_link",
        {
            "claim_id": "claim-service-route",
            "source_type": "paper",
            "source_id": "42",
            "strength": "strong",
            "support_status": "supports",
        },
    )
    payload = result.to_dict()

    assert calls == [
        (
            "evidence_link",
            {
                "claim_id": "claim-service-route",
                "source_type": "paper",
                "source_id": "42",
                "strength": "strong",
                "support_status": "supports",
            },
        )
    ]
    assert result.status == "success"
    assert payload["summary"] == "evidence_link completed (link, created)"
    assert payload["output"]["created"] is True
    assert payload["output"]["link"]["claim_id"] == "claim-service-route"
    assert payload["output"]["link"]["source_id"] == "42"
    assert payload["output"]["link"]["evidence_span"]["snippet"] == (
        "service route evidence"
    )
    assert payload["artifacts"] == ["evidence_link:claim-service-route→42"]
    assert payload["metadata"]["provenance_recorded_by"] == "TrackedBackend"
    assert payload["metadata"]["backend"] == "local"
    assert payload["metadata"]["cost_usd"] == 0.04


def test_research_service_routes_gap_detect_through_tracked_primitive(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import Gap, GapDetectOutput, PrimitiveResult

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=GapDetectOutput(
                gaps=[
                    Gap(
                        gap_id="gap-service-route",
                        description="Evaluation lacks longitudinal evidence.",
                        gap_type="evaluation",
                        severity="high",
                        related_paper_ids=[4, 5],
                        confidence=0.82,
                    )
                ],
                papers_analyzed=4,
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:05+00:00",
            backend="local",
            model_used="local-test",
            cost_usd=0.06,
            prompt_tokens=23,
            completion_tokens=29,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke("gap_detect", {"topic_id": 3, "focus": "evaluation"})
    payload = result.to_dict()

    assert calls == [("gap_detect", {"topic_id": 3, "focus": "evaluation"})]
    assert result.status == "success"
    assert payload["summary"] == "Found 1 gaps in 4 papers (1 high)"
    assert payload["output"]["papers_analyzed"] == 4
    assert payload["output"]["gaps"][0]["gap_id"] == "gap-service-route"
    assert payload["next_actions"] == [
        "paper_search targeting high-severity gaps — fill critical gaps first",
        "baseline_identify — identify baselines before addressing gaps",
    ]
    assert payload["artifacts"] == ["gap:gap-service-route"]
    assert payload["metadata"]["provenance_recorded_by"] == "TrackedBackend"
    assert payload["metadata"]["backend"] == "local"
    assert payload["metadata"]["cost_usd"] == 0.06


def test_research_service_routes_baseline_identify_through_tracked_primitive(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import (
        Baseline,
        BaselineIdentifyOutput,
        PrimitiveResult,
    )

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=BaselineIdentifyOutput(
                baselines=[
                    Baseline(
                        name="Service Baseline",
                        baseline_id="service-baseline",
                        method_family="retrieval",
                        facets=["ranking", "evidence"],
                        relationship_to_proposal="standard comparison",
                        paper_ids=[4, 5],
                        source_paper_ids=[4, 5],
                        metrics={"nDCG": "reported"},
                        notes="Use for service routing comparison.",
                    )
                ]
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:06+00:00",
            backend="local",
            model_used="local-test",
            cost_usd=0.09,
            prompt_tokens=37,
            completion_tokens=41,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "baseline_identify",
        {"topic_id": 3, "focus": "comparison"},
    )
    payload = result.to_dict()

    assert calls == [("baseline_identify", {"topic_id": 3, "focus": "comparison"})]
    assert result.status == "success"
    assert payload["output"]["baselines"][0]["baseline_id"] == "service-baseline"
    assert payload["output"]["baselines"][0]["facets"] == ["ranking", "evidence"]
    assert payload["output"]["baselines"][0]["metrics"] == {"nDCG": "reported"}
    assert payload["metadata"]["provenance_recorded_by"] == "TrackedBackend"
    assert payload["metadata"]["backend"] == "local"
    assert payload["metadata"]["cost_usd"] == 0.09


def test_research_service_routes_section_draft_through_tracked_primitive(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import (
        DraftText,
        EvidenceMapping,
        PrimitiveResult,
        SectionDraftOutput,
    )

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=SectionDraftOutput(
                draft=DraftText(
                    section="related_work",
                    content="Service routed draft cites prior work.",
                    citations_used=[4, 5],
                    evidence_ids=["claim:service-route"],
                    word_count=7,
                ),
                evidence_map=[
                    EvidenceMapping(
                        sentence_index=0,
                        sentence_text="Service routed draft cites prior work.",
                        source_paper_id=4,
                        relation_type="compression",
                        source_span="results",
                        confidence=0.87,
                    )
                ],
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:07+00:00",
            backend="local",
            model_used="local-test",
            cost_usd=0.11,
            prompt_tokens=43,
            completion_tokens=59,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "section_draft",
        {
            "topic_id": 3,
            "section": "related_work",
            "evidence_ids": ["claim:service-route"],
            # All sections are gated now; supply a passing plan so routing is
            # exercised (the gate consumes & strips paper_plan before the
            # primitive call, so `calls` below stays paper_plan-free).
            "paper_plan": {
                "manuscript_logic_gate_report": {
                    "schema_version": "rh.manuscript.logic_gate_report.v1",
                    "status": "pass",
                    "blockers": [],
                },
                "fine_logic_audit_report": _passing_fine_logic_audit_report(),
            },
        },
    )
    payload = result.to_dict()

    assert calls == [
        (
            "section_draft",
            {
                "topic_id": 3,
                "section": "related_work",
                "evidence_ids": ["claim:service-route"],
            },
        )
    ]
    assert result.status == "success"
    assert payload["summary"] == (
        "Drafted 'related_work' section — 7 words, 2 citations"
    )
    assert payload["output"]["draft"]["section"] == "related_work"
    assert payload["output"]["draft"]["citations_used"] == [4, 5]
    assert payload["output"]["evidence_map"][0]["relation_type"] == "compression"
    assert payload["next_actions"] == [
        "consistency_check — verify cross-section consistency"
    ]
    assert payload["artifacts"] == ["draft:related_work"]
    assert payload["metadata"]["provenance_recorded_by"] == "TrackedBackend"
    assert payload["metadata"]["backend"] == "local"
    assert payload["metadata"]["cost_usd"] == 0.11


def test_research_service_blocks_introduction_draft_without_logic_gate(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        del ctx
        calls.append((name, dict(arguments)))
        raise AssertionError(
            "section_draft should be blocked before primitive execution"
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "section_draft",
        {
            "topic_id": 3,
            "section": "introduction",
        },
    )
    payload = result.to_dict()

    assert calls == []
    assert result.status == "error"
    assert result.error == {
        "code": "MANUSCRIPT_LOGIC_GATE_REQUIRED",
        "message": (
            "section_draft introduction requires a passing "
            "manuscript_logic_gate_report in PAPER_PLAN before drafting"
        ),
    }
    assert payload["output"]["required_artifact"] == "PAPER_PLAN"
    assert payload["output"]["required_report"] == "manuscript_logic_gate_report"
    assert payload["output"]["gate_status"] == "missing"
    assert payload["metadata"]["provenance_recorded_by"] == "not_started"


def test_research_service_blocks_introduction_draft_with_failed_logic_gate(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        del ctx
        calls.append((name, dict(arguments)))
        raise AssertionError(
            "section_draft should be blocked before primitive execution"
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "section_draft",
        {
            "topic_id": 3,
            "section": "introduction",
            "paper_plan": {
                "manuscript_logic_gate_report": {
                    "status": "block",
                    "blockers": ["missing:argument_tree.root_claim"],
                }
            },
        },
    )
    payload = result.to_dict()

    assert calls == []
    assert result.status == "error"
    assert result.error["code"] == "MANUSCRIPT_LOGIC_GATE_REQUIRED"
    assert payload["output"]["gate_status"] == "block"
    assert payload["output"]["blockers"] == ["missing:argument_tree.root_claim"]


def test_research_service_blocks_introduction_draft_without_fine_logic_audit(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        del ctx
        calls.append((name, dict(arguments)))
        raise AssertionError(
            "section_draft should be blocked before primitive execution"
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "section_draft",
        {
            "topic_id": 3,
            "section": "introduction",
            "paper_plan": {
                "manuscript_logic_gate_report": {
                    "schema_version": "rh.manuscript.logic_gate_report.v1",
                    "status": "pass",
                    "blockers": [],
                }
            },
        },
    )
    payload = result.to_dict()

    assert calls == []
    assert result.status == "error"
    assert result.error["code"] == "MANUSCRIPT_LOGIC_GATE_REQUIRED"
    assert payload["output"]["required_report"] == "fine_logic_audit_report"
    assert payload["output"]["gate_status"] == "missing"


def test_research_service_allows_introduction_draft_with_passing_logic_gate(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import (
        DraftText,
        PrimitiveResult,
        SectionDraftOutput,
    )

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=SectionDraftOutput(
                draft=DraftText(
                    section="introduction",
                    content="Service routed introduction follows the paper plan.",
                    citations_used=[1],
                    evidence_ids=["claim:core"],
                    word_count=7,
                )
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:07+00:00",
            backend="local",
            model_used="local-test",
            cost_usd=0.11,
            prompt_tokens=43,
            completion_tokens=59,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "section_draft",
        {
            "topic_id": 3,
            "section": "introduction",
            "paper_plan": {
                "manuscript_logic_gate_report": {
                    "schema_version": "rh.manuscript.logic_gate_report.v1",
                    "status": "pass",
                    "blockers": [],
                },
                "fine_logic_audit_report": _passing_fine_logic_audit_report(),
            },
        },
    )

    assert calls == [
        (
            "section_draft",
            {
                "topic_id": 3,
                "section": "introduction",
            },
        )
    ]
    assert result.status == "success"
    assert result.output.draft.section == "introduction"
    assert result.metadata["provenance_recorded_by"] == "TrackedBackend"


def test_research_service_allows_introduction_draft_with_active_paper_plan_artifact(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.orchestrator import OrchestratorService
    from research_harness.primitives.types import (
        DraftText,
        PrimitiveResult,
        SectionDraftOutput,
    )

    conn = db.connect()
    try:
        topic_id = _seed_topic_project(conn, name="paper-plan-topic")
        conn.commit()
    finally:
        conn.close()

    OrchestratorService(db).record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="PAPER_PLAN",
        title="Paper plan with passing manuscript logic gate",
        payload={
            "manuscript_logic_gate_report": {
                "schema_version": "rh.manuscript.logic_gate_report.v1",
                "status": "pass",
                "blockers": [],
            },
            "fine_logic_audit_report": _passing_fine_logic_audit_report(),
        },
    )

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=SectionDraftOutput(
                draft=DraftText(
                    section="abstract",
                    content="Service routed abstract follows the active paper plan.",
                    citations_used=[],
                    evidence_ids=["claim:core"],
                    word_count=8,
                )
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:07+00:00",
            backend="local",
            model_used="local-test",
            cost_usd=0.11,
            prompt_tokens=43,
            completion_tokens=59,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "section_draft",
        {
            "topic_id": topic_id,
            "section": "abstract",
        },
    )

    assert calls == [("section_draft", {"topic_id": topic_id, "section": "abstract"})]
    assert result.status == "success"
    assert result.output.draft.section == "abstract"
    assert result.metadata["provenance_recorded_by"] == "TrackedBackend"


def test_research_service_routes_consistency_check_through_tracked_primitive(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import (
        ConsistencyCheckOutput,
        ConsistencyIssue,
        PrimitiveResult,
    )

    calls: list[tuple[str, dict]] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        assert ctx.db is db
        calls.append((name, dict(arguments)))
        return PrimitiveResult(
            primitive=name,
            success=True,
            output=ConsistencyCheckOutput(
                issues=[
                    ConsistencyIssue(
                        issue_type="terminology",
                        severity="medium",
                        location="related_work",
                        description="Method naming is inconsistent.",
                        suggestion="Use one method name throughout.",
                    )
                ],
                sections_checked=["intro", "related_work"],
            ),
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:04+00:00",
            backend="local",
            model_used="local-test",
            cost_usd=0.05,
            prompt_tokens=19,
            completion_tokens=23,
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "consistency_check",
        {"topic_id": 3, "sections": ["intro", "related_work"]},
    )
    payload = result.to_dict()

    assert calls == [
        (
            "consistency_check",
            {"topic_id": 3, "sections": ["intro", "related_work"]},
        )
    ]
    assert result.status == "success"
    assert payload["output"] == {
        "issues": [
            {
                "issue_type": "terminology",
                "severity": "medium",
                "location": "related_work",
                "description": "Method naming is inconsistent.",
                "suggestion": "Use one method name throughout.",
                "source": "manuscript",
            }
        ],
        "sections_checked": ["intro", "related_work"],
    }
    assert payload["metadata"]["provenance_recorded_by"] == "TrackedBackend"
    assert payload["metadata"]["backend"] == "local"
    assert payload["metadata"]["cost_usd"] == 0.05


def test_research_service_invokes_topic_list(db):
    conn = db.connect()
    try:
        topic_id = _seed_topic(conn)
        conn.commit()
    finally:
        conn.close()

    service = ResearchService(db=db)
    result = service.invoke("topic_list", {})

    assert result.status == "success"
    assert result.command == "topic_list"
    assert result.error is None
    [topic] = result.output["topics"]
    assert topic["id"] == topic_id
    assert topic["name"] == "rh-selfdev"
    assert topic["description"] == "Self-development topic"
    assert topic["status"] == "active"
    assert topic["paper_count"] == 0
    assert "created_at" in topic


def test_research_service_invokes_topic_show_and_paper_list(db):
    conn = db.connect()
    try:
        topic_id = _seed_topic(conn)
        paper_id = _seed_paper(conn, topic_id=topic_id)
        conn.commit()
    finally:
        conn.close()

    service = ResearchService(db=db)
    topic = service.invoke("topic_show", {"name": "rh-selfdev"})
    papers = service.invoke("paper_list", {"topic": "rh-selfdev"})

    assert topic.status == "success"
    assert topic.output["name"] == "rh-selfdev"
    assert topic.output["freshness_status"] == "never_searched"
    assert papers.status == "success"
    assert papers.output["papers"][0]["id"] == paper_id
    assert papers.output["papers"][0]["title"] == "Service Dispatcher Contracts"
    assert papers.output["papers"][0]["year"] == 2026
    assert papers.output["papers"][0]["venue"] == "ICSE"
    assert papers.output["papers"][0]["url"] == "https://example.test/service"
    assert papers.output["papers"][0]["affiliations"] == ["Analytical Engine Lab"]
    assert papers.output["papers"][0]["relevance"] == "high"
    assert papers.output["papers"][0]["status"] == "meta_only"
    assert "created_at" in papers.output["papers"][0]


def test_research_service_invokes_provenance_summary_and_export(db):
    conn = db.connect()
    try:
        topic_id = _seed_topic(conn, name="prov-topic")
        conn.commit()
    finally:
        conn.close()

    _record_provenance(db, topic_id=topic_id)

    service = ResearchService(db=db)
    summary = service.invoke("provenance_summary", {"topic_id": topic_id})
    exported = service.invoke(
        "provenance_export",
        {"topic_id": topic_id, "format": "json"},
    )

    assert summary.status == "success"
    assert summary.output["total_operations"] == 1
    assert summary.output["total_cost_usd"] == 0.25
    assert summary.output["operations_by_backend"] == {"local": 1}
    assert summary.output["operations_by_primitive"] == {"paper_ingest": 1}
    assert summary.output["total_prompt_tokens"] == 11
    assert summary.output["total_completion_tokens"] == 7

    assert exported.status == "success"
    assert exported.output["format"] == "json"
    assert len(exported.output["records"]) == 1
    assert exported.output["records"][0]["primitive"] == "paper_ingest"
    assert exported.output["records"][0]["topic_id"] == topic_id
    assert exported.output["records"][0]["prompt_tokens"] == 11


def test_research_service_invokes_orchestrator_read_commands(db):
    from research_harness.orchestrator import OrchestratorService

    conn = db.connect()
    try:
        topic_id = _seed_topic_project(conn)
        conn.commit()
    finally:
        conn.close()

    OrchestratorService(db).init_run(topic_id=topic_id)

    service = ResearchService(db=db)
    status = service.invoke("orchestrator_status", {"topic_id": topic_id})
    gate = service.invoke("orchestrator_gate_check", {"topic_id": topic_id})

    assert status.status == "success"
    assert status.output["run"]["topic_id"] == topic_id
    assert status.output["run"]["current_stage"] == "init"
    assert "db_path" not in status.output
    assert gate.status == "success"
    assert gate.output["gate_decision"] == "needs_approval"
    assert gate.output["can_advance"] is False
    assert "reasons" in gate.output
    assert "recovery_actions" in gate.output


def test_research_service_normalizes_handler_exceptions(db, monkeypatch):
    import research_harness.service.dispatcher as dispatcher_module

    def broken_handler(_ctx, _arguments):
        raise RuntimeError("handler exploded")

    command = dispatcher_module.COMMANDS_BY_NAME["topic_list"]
    monkeypatch.setitem(
        dispatcher_module.COMMANDS_BY_NAME,
        "topic_list",
        replace(command, handler=broken_handler),
    )

    result = ResearchService(db=db).invoke("topic_list", {})

    assert result.status == "error"
    assert result.error == {
        "code": "COMMAND_FAILED",
        "message": "topic_list failed during service execution",
    }
    assert result.output == {"exception_type": "RuntimeError"}


def test_research_service_routes_orchestrator_resume_preserving_raw_output(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.orchestrator.models import OrchestratorRun

    calls: list[tuple[str, object]] = []

    class FakeOrchestratorService:
        def __init__(self, service_db) -> None:
            calls.append(("init", service_db))

        def resume_run(
            self,
            *,
            topic_id: int,
            mode: str,
            force_stage: str | None,
            stop_before: str | None,
        ) -> OrchestratorRun:
            calls.append(
                (
                    "resume_run",
                    {
                        "topic_id": topic_id,
                        "mode": mode,
                        "force_stage": force_stage,
                        "stop_before": stop_before,
                    },
                )
            )
            return OrchestratorRun(
                id=11,
                topic_id=topic_id,
                mode=mode,
                current_stage=force_stage or "init",
                stage_status="in_progress",
                gate_status="pending",
                stop_before=stop_before or "",
            )

        def infer_stage_from_artifacts(self, topic_id: int) -> str:
            calls.append(("infer_stage_from_artifacts", topic_id))
            return "analyze"

    monkeypatch.setattr(
        handlers_module,
        "OrchestratorService",
        FakeOrchestratorService,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "orchestrator_resume",
        {
            "topic_id": 3,
            "mode": "strict",
            "force_stage": "literature_mapping",
            "stop_before": "draft_preparation",
        },
    )

    assert calls == [
        ("init", db),
        (
            "resume_run",
            {
                "topic_id": 3,
                "mode": "strict",
                "force_stage": "build",
                "stop_before": "write",
            },
        ),
        ("infer_stage_from_artifacts", 3),
    ]
    assert result.status == "success"
    assert result.output == {
        "success": True,
        "run_id": 11,
        "topic_id": 3,
        "current_stage": "build",
        "inferred_stage": "analyze",
        "stage_status": "in_progress",
        "stop_before": "write",
    }


def test_research_service_routes_orchestrator_record_artifact_preserving_raw_output(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module

    calls: list[tuple[str, object]] = []

    class FakeOrchestratorService:
        def __init__(self, service_db) -> None:
            calls.append(("init", service_db))

        def record_artifact(self, **kwargs):
            calls.append(("record_artifact", kwargs))
            return SimpleNamespace(
                id=31,
                version=2,
                stage=kwargs["stage"],
                artifact_type=kwargs["artifact_type"],
            )

    monkeypatch.setattr(
        handlers_module,
        "OrchestratorService",
        FakeOrchestratorService,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "orchestrator_record_artifact",
        {
            "topic_id": 3,
            "stage": "build",
            "artifact_type": "literature_map",
            "title": "Map",
            "payload": {"v": 1},
            "dependency_artifact_ids": [7],
            "dependency_type": "derived_from",
        },
    )

    assert calls == [
        ("init", db),
        (
            "record_artifact",
            {
                "topic_id": 3,
                "stage": "build",
                "artifact_type": "literature_map",
                "title": "Map",
                "payload": {"v": 1},
                "dependency_artifact_ids": [7],
                "dependency_type": "derived_from",
            },
        ),
    ]
    assert result.status == "success"
    assert result.output == {
        "success": True,
        "artifact_id": 31,
        "version": 2,
        "stage": "build",
        "type": "literature_map",
    }


def test_research_service_routes_paper_task_intake_to_durable_entry(db):
    service = ResearchService(db=db)

    result = service.invoke(
        "paper_task_intake",
        {
            "task": "Evidence-grounded AI agents for literature review",
            "target_venue": "NeurIPS 2026",
            "mode": "demo",
        },
    )

    assert result.status == "success"
    assert result.output["action"] == "prepared"
    assert result.output["topic"]["id"] == 1
    assert result.output["run"]["sync_status"] == "RH_SYNCED"
    assert result.output["rh_state"]["sync_status"] == "RH_SYNCED"
    assert result.output["rh_state"]["artifact_ids"] == [
        result.output["run"]["active_paper_plan_artifact_id"]
    ]


def test_research_service_routes_orchestrator_advance_preserving_raw_output(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module

    calls: list[tuple[str, object]] = []

    class FakeOrchestratorService:
        def __init__(self, service_db) -> None:
            calls.append(("init", service_db))

        def advance(self, topic_id: int, *, actor: str):
            calls.append(("advance", {"topic_id": topic_id, "actor": actor}))
            return {"success": True, "from_stage": "build", "to_stage": "analyze"}

    monkeypatch.setattr(
        handlers_module,
        "OrchestratorService",
        FakeOrchestratorService,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "orchestrator_advance",
        {"topic_id": 3, "actor": "codex"},
    )

    assert calls == [
        ("init", db),
        ("advance", {"topic_id": 3, "actor": "codex"}),
    ]
    assert result.status == "success"
    assert result.output == {
        "success": True,
        "from_stage": "build",
        "to_stage": "analyze",
    }


def test_research_service_routes_adversarial_review_with_mocked_reviewer(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module

    calls: list[tuple[str, object]] = []
    artifact = SimpleNamespace(
        id=9,
        path="",
        payload={"claim": "service routing"},
        artifact_type="research_proposal",
        stage="propose",
        title="Proposal",
    )

    class FakeOrchestratorService:
        def __init__(self, service_db) -> None:
            calls.append(("init", service_db))
            self._artifact_manager = SimpleNamespace(get=lambda artifact_id: artifact)

        def get_run(self, topic_id: int):
            calls.append(("get_run", topic_id))
            return SimpleNamespace(current_stage="propose")

        def run_adversarial_round(self, **kwargs):
            calls.append(("run_adversarial_round", kwargs))
            return {"success": True, "artifact_id": 41}

        def resolve_adversarial_round(self, **kwargs):
            calls.append(("resolve_adversarial_round", kwargs))
            return {"success": True, "artifact_id": 42}

    def fake_run_codex_review(**kwargs):
        calls.append(("run_codex_review", kwargs))
        return {
            "success": True,
            "verdict": "revise",
            "issues": [{"severity": "critical", "category": "validity"}],
            "scores": {"novelty": 0.4},
            "notes": "Needs stronger evidence.",
            "backend": "mock",
            "model": "mock-reviewer",
        }

    def fake_codex_issues_to_objections(issues):
        calls.append(("codex_issues_to_objections", issues))
        return [
            {
                "category": "validity",
                "severity": "critical",
                "target": "claim",
                "reasoning": "Evidence is thin.",
                "suggested_fix": "Add ablation.",
            }
        ]

    monkeypatch.setattr(
        handlers_module,
        "OrchestratorService",
        FakeOrchestratorService,
    )
    monkeypatch.setattr(
        handlers_module,
        "run_codex_review",
        fake_run_codex_review,
        raising=False,
    )
    monkeypatch.setattr(
        handlers_module,
        "codex_issues_to_objections",
        fake_codex_issues_to_objections,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "adversarial_review",
        {"topic_id": 3, "artifact_id": 9, "focus": "validity"},
    )

    assert calls[0] == ("init", db)
    assert ("get_run", 3) in calls
    assert result.status == "success"
    assert result.output["verdict"] == "revise"
    assert result.output["issues_count"] == 1
    assert result.output["critical_count"] == 1
    assert result.output["round_artifact_id"] == 41
    assert result.output["resolution_artifact_id"] == 42
    assert result.output["backend"] == "mock"
    assert result.output["stage"] == "propose"


def test_research_service_routes_zotero_sync_dry_run_without_zotero_client(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module

    calls: list[tuple[str, object]] = []

    class FakeZoteroSyncService:
        def __init__(self, *, db_path, client, library_id, library_type) -> None:
            calls.append(
                (
                    "init",
                    {
                        "db_path": db_path,
                        "client": client,
                        "library_id": library_id,
                        "library_type": library_type,
                    },
                )
            )

        def sync_topic(self, topic, **kwargs):
            calls.append(("sync_topic", {"topic": topic, **kwargs}))
            return SimpleNamespace(
                to_dict=lambda: {"planned_count": 1, "records": [{"title": "Paper"}]}
            )

    def fail_zotero_client(**kwargs):
        raise AssertionError(f"dry-run push must not create Zotero client: {kwargs}")

    monkeypatch.setattr(
        handlers_module,
        "ZoteroSyncService",
        FakeZoteroSyncService,
        raising=False,
    )
    monkeypatch.setattr(
        handlers_module,
        "zotero_resource",
        SimpleNamespace(create_zotero_resource_from_env=fail_zotero_client),
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "zotero_sync",
        {"topic": "demo-topic", "direction": "push", "dry_run": True, "limit": 1},
    )

    assert result.status == "success"
    assert result.output == {
        "topic": "demo-topic",
        "direction": "push",
        "dry_run": True,
        "push": {"planned_count": 1, "records": [{"title": "Paper"}]},
        "pull": None,
    }
    assert calls[0][0] == "init"
    assert calls[1] == (
        "sync_topic",
        {
            "topic": "demo-topic",
            "root_collection": "Research Harness",
            "include_notes": True,
            "dry_run": True,
            "limit": 1,
            "force": False,
        },
    )


def test_research_service_defers_pull_and_both_dry_run_without_zotero_client(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module

    def fail_zotero_client(**kwargs):
        raise AssertionError(
            f"deferred dry-run must not create Zotero client: {kwargs}"
        )

    class FailingZoteroSyncService:
        def __init__(self, **kwargs) -> None:
            raise AssertionError(f"deferred dry-run must not create service: {kwargs}")

    monkeypatch.setattr(
        handlers_module,
        "ZoteroSyncService",
        FailingZoteroSyncService,
        raising=False,
    )
    monkeypatch.setattr(
        handlers_module,
        "zotero_resource",
        SimpleNamespace(create_zotero_resource_from_env=fail_zotero_client),
        raising=False,
    )

    service = ResearchService(db=db)
    for direction in ("pull", "both"):
        result = service.invoke(
            "zotero_sync",
            {"topic": "demo-topic", "direction": direction, "dry_run": True},
        )

        assert result.status == "error"
        assert result.error == {
            "code": "COMMAND_FAILED",
            "message": (
                "stable Zotero dry-run only supports direction=push; "
                f"{direction} dry-run requires Zotero read access and remains deferred"
            ),
        }


def test_research_service_zotero_sync_validates_direction(db):
    service = ResearchService(db=db)
    result = service.invoke(
        "zotero_sync",
        {"topic": "demo-topic", "direction": "sideways", "dry_run": True},
    )

    assert result.status == "error"
    assert result.error == {
        "code": "COMMAND_FAILED",
        "message": "direction must be one of: push, pull, both",
    }


def test_research_service_runs_advisory_check(db, monkeypatch):
    import research_harness.service.handlers as handlers_module
    from research_harness.advisory.models import Advisory

    calls: list[tuple[str, object]] = []

    class FakeAdvisoryEngine:
        def __init__(self, engine_db) -> None:
            calls.append(("init", engine_db))

        def run(self, topic_id: int) -> list[Advisory]:
            calls.append(("run", topic_id))
            return [
                Advisory(
                    id=7,
                    topic_id=topic_id,
                    level="info",
                    category="coverage_low",
                    message="Topic has only 1 papers.",
                    details={"paper_count": 1},
                    created_at="2026-04-03T00:00:00",
                )
            ]

    monkeypatch.setattr(handlers_module, "AdvisoryEngine", FakeAdvisoryEngine)

    service = ResearchService(db=db)
    result = service.invoke("advisory_check", {"topic_id": 3})

    assert calls == [("init", db), ("run", 3)]
    assert result.status == "success"
    assert result.summary == "advisory_check completed successfully."
    assert result.output == {
        "advisories": [
            {
                "id": 7,
                "topic_id": 3,
                "level": "info",
                "category": "coverage_low",
                "message": "Topic has only 1 papers.",
                "details": {"paper_count": 1},
                "created_at": "2026-04-03T00:00:00",
                "acknowledged": False,
                "acknowledged_at": None,
                "auto_resolved": False,
            }
        ],
        "count": 1,
    }


def test_research_service_validates_provenance_export_format(db):
    service = ResearchService(db=db)

    result = service.invoke("provenance_export", {"format": "csv"})

    assert result.status == "error"
    assert result.error == {
        "code": "INVALID_ARGUMENT",
        "message": (
            "Invalid arguments for provenance_export: format must be one of: json"
        ),
    }


def test_research_service_validates_argument_type(db):
    service = ResearchService(db=db)

    result = service.invoke("paper_search", {"query": "ok", "max_results": "50"})

    assert result.status == "error"
    assert result.error == {
        "code": "INVALID_ARGUMENT",
        "message": ("Invalid arguments for paper_search: max_results must be integer"),
    }


def test_research_service_v0_validator_enforces_numeric_bounds(db, monkeypatch):
    import research_harness.service.dispatcher as dispatcher_module
    from research_harness.service.types import ServiceCommand

    bounded_command = ServiceCommand(
        name="bounded_test_command",
        description="temporary bounded validator command",
        input_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 5}},
        },
        output_schema={"type": "object", "properties": {}},
        visibility=("internal",),
        handler=lambda ctx, arguments: {"limit": arguments["limit"]},
        requires_db=False,
    )
    monkeypatch.setitem(
        dispatcher_module.COMMANDS_BY_NAME,
        bounded_command.name,
        bounded_command,
    )
    service = ResearchService(db=db)
    low = service.invoke("bounded_test_command", {"limit": 0})
    high = service.invoke("bounded_test_command", {"limit": 6})

    assert low.status == "error"
    assert low.error == {
        "code": "INVALID_ARGUMENT",
        "message": ("Invalid arguments for bounded_test_command: limit must be >= 1"),
    }
    assert high.status == "error"
    assert high.error == {
        "code": "INVALID_ARGUMENT",
        "message": ("Invalid arguments for bounded_test_command: limit must be <= 5"),
    }


def test_research_service_allows_unknown_arguments_for_adapter_compatibility(
    db,
    monkeypatch,
):
    import research_harness.service.handlers as handlers_module
    from research_harness.primitives.types import PrimitiveResult, SummaryOutput

    calls: list[dict] = []

    def fake_execute_tracked_primitive(ctx, name: str, arguments: dict):
        del ctx, name
        calls.append(dict(arguments))
        return PrimitiveResult(
            primitive="paper_summarize",
            success=True,
            output=SummaryOutput(
                paper_id=7,
                summary="Compatible payload",
                focus=None,
                confidence=1.0,
            ),
            backend="local",
            model_used="",
        )

    monkeypatch.setattr(
        handlers_module,
        "_execute_tracked_primitive",
        fake_execute_tracked_primitive,
        raising=False,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "paper_summarize",
        {"paper_id": 7, "adapter_passthrough": True},
    )

    assert result.status == "success"
    assert calls == [{"paper_id": 7, "adapter_passthrough": True}]


def test_research_service_default_compat_policy_ignores_strict_schema_keywords(
    db,
    monkeypatch,
):
    import research_harness.service.dispatcher as dispatcher_module
    from research_harness.service.types import ServiceCommand

    compat_command = ServiceCommand(
        name="compat_validation_test_command",
        description="temporary compat validator command",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {
                    "type": "string",
                    "minLength": 3,
                    "maxLength": 5,
                    "pattern": "^[a-z]+$",
                    "format": "uri",
                },
                "metadata": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"label": {"type": "string", "minLength": 3}},
                },
            },
        },
        output_schema={"type": "object", "properties": {}},
        visibility=("internal",),
        handler=lambda ctx, arguments: dict(arguments),
        requires_db=False,
    )
    monkeypatch.setitem(
        dispatcher_module.COMMANDS_BY_NAME,
        compat_command.name,
        compat_command,
    )

    service = ResearchService(db=db)
    result = service.invoke(
        "compat_validation_test_command",
        {
            "title": "x",
            "metadata": {"label": "y", "extra_nested": True},
            "adapter_passthrough": True,
        },
    )

    assert result.status == "success"
    assert result.output == {
        "title": "x",
        "metadata": {"label": "y", "extra_nested": True},
        "adapter_passthrough": True,
    }


def test_research_service_strict_policy_rejects_unknown_arguments(db, monkeypatch):
    import research_harness.service.dispatcher as dispatcher_module
    from research_harness.service.types import ServiceCommand

    strict_command = ServiceCommand(
        name="strict_unknown_test_command",
        description="temporary strict validator command",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
        output_schema={"type": "object", "properties": {}},
        visibility=("internal",),
        handler=lambda ctx, arguments: dict(arguments),
        requires_db=False,
        validation_policy="strict",
    )
    monkeypatch.setitem(
        dispatcher_module.COMMANDS_BY_NAME,
        strict_command.name,
        strict_command,
    )

    service = ResearchService(db=db)
    result = service.invoke("strict_unknown_test_command", {"name": "ok", "extra": 1})

    assert result.status == "error"
    assert result.error == {
        "code": "INVALID_ARGUMENT",
        "message": (
            "Invalid arguments for strict_unknown_test_command: "
            "unexpected argument: extra"
        ),
    }


def test_research_service_strict_policy_enforces_string_and_format_keywords(
    db,
    monkeypatch,
):
    import research_harness.service.dispatcher as dispatcher_module
    from research_harness.service.types import ServiceCommand

    strict_command = ServiceCommand(
        name="strict_string_test_command",
        description="temporary strict string validator command",
        input_schema={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "minLength": 3,
                    "maxLength": 8,
                    "pattern": "^[a-z][a-z0-9-]+$",
                },
                "homepage": {"type": "string", "format": "uri"},
            },
            "required": ["slug", "homepage"],
        },
        output_schema={"type": "object", "properties": {}},
        visibility=("internal",),
        handler=lambda ctx, arguments: dict(arguments),
        requires_db=False,
        validation_policy="strict",
    )
    monkeypatch.setitem(
        dispatcher_module.COMMANDS_BY_NAME,
        strict_command.name,
        strict_command,
    )
    service = ResearchService(db=db)

    too_short = service.invoke(
        "strict_string_test_command",
        {"slug": "ab", "homepage": "https://example.test"},
    )
    too_long = service.invoke(
        "strict_string_test_command",
        {"slug": "abcdefghi", "homepage": "https://example.test"},
    )
    bad_pattern = service.invoke(
        "strict_string_test_command",
        {"slug": "Bad Slug", "homepage": "https://example.test"},
    )
    bad_format = service.invoke(
        "strict_string_test_command",
        {"slug": "ok-slug", "homepage": "not a uri"},
    )

    assert too_short.error == {
        "code": "INVALID_ARGUMENT",
        "message": "Invalid arguments for strict_string_test_command: slug length must be >= 3",
    }
    assert too_long.error == {
        "code": "INVALID_ARGUMENT",
        "message": "Invalid arguments for strict_string_test_command: slug length must be <= 8",
    }
    assert bad_pattern.error == {
        "code": "INVALID_ARGUMENT",
        "message": (
            "Invalid arguments for strict_string_test_command: "
            "slug must match pattern: ^[a-z][a-z0-9-]+$"
        ),
    }
    assert bad_format.error == {
        "code": "INVALID_ARGUMENT",
        "message": (
            "Invalid arguments for strict_string_test_command: "
            "homepage must be valid uri"
        ),
    }


def test_research_service_strict_policy_enforces_nested_constraints(
    db,
    monkeypatch,
):
    import research_harness.service.dispatcher as dispatcher_module
    from research_harness.service.types import ServiceCommand

    strict_command = ServiceCommand(
        name="strict_nested_test_command",
        description="temporary strict nested validator command",
        input_schema={
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "labels": {
                            "type": "array",
                            "minItems": 2,
                            "items": {
                                "type": "string",
                                "pattern": "^[a-z]+$",
                            },
                        },
                    },
                },
            },
        },
        output_schema={"type": "object", "properties": {}},
        visibility=("internal",),
        handler=lambda ctx, arguments: dict(arguments),
        requires_db=False,
        validation_policy="strict",
    )
    monkeypatch.setitem(
        dispatcher_module.COMMANDS_BY_NAME,
        strict_command.name,
        strict_command,
    )
    service = ResearchService(db=db)

    nested_unknown = service.invoke(
        "strict_nested_test_command",
        {"config": {"labels": ["alpha", "beta"], "extra": True}},
    )
    too_few_items = service.invoke(
        "strict_nested_test_command",
        {"config": {"labels": ["alpha"]}},
    )
    invalid_item = service.invoke(
        "strict_nested_test_command",
        {"config": {"labels": ["alpha", "Beta"]}},
    )

    assert nested_unknown.error == {
        "code": "INVALID_ARGUMENT",
        "message": (
            "Invalid arguments for strict_nested_test_command: "
            "unexpected argument: config.extra"
        ),
    }
    assert too_few_items.error == {
        "code": "INVALID_ARGUMENT",
        "message": (
            "Invalid arguments for strict_nested_test_command: "
            "config.labels must contain at least 2 items"
        ),
    }
    assert invalid_item.error == {
        "code": "INVALID_ARGUMENT",
        "message": (
            "Invalid arguments for strict_nested_test_command: "
            "config.labels[1] must match pattern: ^[a-z]+$"
        ),
    }


def test_public_service_commands_preserve_compat(db):
    service = ResearchService(db=db)

    commands = service.list_commands(visibility="public_mcp")

    assert commands
    assert {command.validation_policy for command in commands} == {"compat"}


def test_research_service_returns_structured_error_for_unknown_command(db):
    service = ResearchService(db=db)

    result = service.invoke("does_not_exist", {})

    assert result.status == "error"
    assert result.error == {
        "code": "UNKNOWN_COMMAND",
        "message": "Unknown service command: does_not_exist",
    }
    assert result.to_dict()["error"]["code"] == "UNKNOWN_COMMAND"


def test_research_service_allows_empty_error_field_as_success_payload(
    tmp_path,
    monkeypatch,
):
    import research_harness.service.dispatcher as dispatcher_module
    from research_harness.service import ServiceCommand

    def handler(ctx, arguments):
        assert ctx.db is not None
        return {"status": "ok", "error": "", "value": arguments["value"]}

    command = ServiceCommand(
        name="empty_error_payload",
        description="Exercise compatibility payloads with empty error fields.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        output_schema={"type": "object"},
        visibility=("python",),
        handler=handler,
    )
    commands_by_name = {
        **dispatcher_module.COMMANDS_BY_NAME,
        command.name: command,
    }
    monkeypatch.setattr(dispatcher_module, "COMMANDS_BY_NAME", commands_by_name)

    result = dispatcher_module.ResearchService(db=tmp_path / "test.db").invoke(
        "empty_error_payload",
        {"value": "kept"},
    )

    assert result.status == "success"
    assert result.error is None
    assert result.output == {"status": "ok", "error": "", "value": "kept"}


def test_research_service_validates_required_arguments(db):
    service = ResearchService(db=db)

    result = service.invoke("topic_show", {})

    assert result.status == "error"
    assert result.error == {
        "code": "INVALID_ARGUMENT",
        "message": "Invalid arguments for topic_show: missing required argument: name",
    }


def test_research_service_invokes_db_less_skill_command_without_initializing_db(
    monkeypatch,
    tmp_path,
):
    import research_harness.service.dispatcher as dispatcher_module

    class ExplodingDatabase:
        def __init__(self, path):
            raise AssertionError(f"DB should not initialize for skill_list: {path}")

    monkeypatch.setattr(dispatcher_module, "Database", ExplodingDatabase)

    service = dispatcher_module.ResearchService(db=tmp_path / "unused.db")
    result = service.invoke("skill_list", {})

    assert result.status == "success"
    assert result.output["schema_version"] == "1.0"
    assert any(skill["name"] == "paper-writing" for skill in result.output["skills"])


def test_research_service_invokes_db_less_paperindex_search(monkeypatch, tmp_path):
    import research_harness.service.handlers as handlers_module

    monkeypatch.setattr(handlers_module, "find_workspace_root", lambda: tmp_path)

    service = ResearchService(db=tmp_path / "unused.db")

    result = service.invoke("paperindex_search", {"query": "missing", "limit": 1})

    assert result.status == "success"
    assert result.output == {"results": []}


def test_research_service_invokes_db_less_productization_boundary_without_initializing_db(
    monkeypatch,
    tmp_path,
):
    import research_harness.service.dispatcher as dispatcher_module

    class ExplodingDatabase:
        def __init__(self, path):
            raise AssertionError(
                f"DB should not initialize for productization_boundary: {path}"
            )

    monkeypatch.setattr(dispatcher_module, "Database", ExplodingDatabase)

    service = dispatcher_module.ResearchService(db=tmp_path / "unused.db")
    result = service.invoke(
        "productization_boundary",
        {"experimental_lg10": True},
    )

    assert result.status == "success"
    assert result.command == "productization_boundary"
    assert result.output["boundary_id"] == "lg10-public-productization-boundary"
    assert result.output["schema_version"] == "lg10_productization_boundary.v1"
    assert result.output["scope"] == "public-mcp-opt-in-preview"


def test_primitive_service_contract_preserves_tracking_metadata():
    from research_harness.primitives.types import (
        PaperRef,
        PaperSearchOutput,
        PrimitiveResult,
    )
    from research_harness.service import primitive_result_to_service_result

    primitive = PrimitiveResult(
        primitive="paper_search",
        success=True,
        output=PaperSearchOutput(
            papers=[PaperRef(title="Contract Paper", year=2026)],
            provider="local",
            total_before_filter=1,
        ),
        started_at="2026-04-03T00:00:00+00:00",
        finished_at="2026-04-03T00:00:02+00:00",
        backend="local",
        model_used="",
        cost_usd=0.25,
        prompt_tokens=11,
        completion_tokens=7,
    )

    result = primitive_result_to_service_result(primitive)
    payload = result.to_dict()

    assert result.command == "paper_search"
    assert result.status == "success"
    assert result.error is None
    assert payload["summary"] == "Found 1 papers via local"
    assert payload["output"]["papers"][0]["title"] == "Contract Paper"
    assert payload["next_actions"] == [
        "paper_ingest top results — add high-relevance papers to pool"
    ]
    assert payload["recovery_hint"] == ""
    assert payload["metadata"] == {
        "primitive": "paper_search",
        "backend": "local",
        "model_used": "",
        "cost_usd": 0.25,
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "duration_seconds": 2.0,
        "provenance_recorded_by": "TrackedBackend",
    }


def test_primitive_service_contract_preserves_error_and_recovery_hint():
    from research_harness.primitives.types import PrimitiveResult
    from research_harness.service import primitive_result_to_service_result

    primitive = PrimitiveResult(
        primitive="claim_extract",
        success=False,
        output={"partial": True},
        error="No API key configured",
        backend="local",
        model_used="",
    )

    result = primitive_result_to_service_result(primitive)
    payload = result.to_dict()

    assert result.status == "error"
    assert result.error == {
        "code": "PRIMITIVE_FAILED",
        "message": "No API key configured",
    }
    assert payload["summary"] == "claim_extract failed: No API key configured"
    assert payload["output"] == {"partial": True}
    assert "Set KIMI_API_KEY" in payload["recovery_hint"]
    assert payload["metadata"]["primitive"] == "claim_extract"


def test_research_service_resolves_numeric_topic_ids(db):
    """topic list shows numeric IDs; topic_show/paper_list must accept them."""
    conn = db.connect()
    try:
        topic_id = _seed_topic(conn)
        paper_id = _seed_paper(conn, topic_id=topic_id)
        conn.commit()
    finally:
        conn.close()

    service = ResearchService(db=db)
    topic = service.invoke("topic_show", {"name": str(topic_id)})
    papers = service.invoke("paper_list", {"topic": str(topic_id)})

    assert topic.status == "success"
    assert topic.output["name"] == "rh-selfdev"
    assert papers.status == "success"
    assert [p["id"] for p in papers.output["papers"]] == [paper_id]


def test_research_service_paper_list_errors_on_unknown_topic(db):
    """Unknown topics must error, not silently return an empty pool."""
    service = ResearchService(db=db)

    result = service.invoke("paper_list", {"topic": "no-such-topic"})

    assert result.status == "error"
    assert result.error is not None
    assert "Topic not found" in result.error["message"]


def test_commit_gate_blocks_on_blocked_manuscript_polish(db):
    """A blocked manuscript_polish_report must block a manuscript commit."""
    from research_harness.orchestrator import OrchestratorService

    conn = db.connect()
    try:
        topic_id = _seed_topic_project(conn, name="polish-gate-blocked")
        conn.commit()
    finally:
        conn.close()
    svc = OrchestratorService(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="manuscript_polish_report",
        title="polish blocked",
        payload={"submission_readiness": "blocked", "n_high": 3},
    )
    findings = svc._manuscript_commit_gate_findings(
        topic_id=topic_id,
        stage="write",
        tex_path="",
        report={},
        writing_mode="main",
    )
    assert "manuscript_polish_blocked" in {f["check"] for f in findings}


def test_commit_gate_allows_when_manuscript_polish_ready(db):
    """A ready manuscript_polish_report adds no polish gate finding."""
    from research_harness.orchestrator import OrchestratorService

    conn = db.connect()
    try:
        topic_id = _seed_topic_project(conn, name="polish-gate-ready")
        conn.commit()
    finally:
        conn.close()
    svc = OrchestratorService(db)
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="manuscript_polish_report",
        title="polish ready",
        payload={"submission_readiness": "ready", "n_high": 0},
    )
    findings = svc._manuscript_commit_gate_findings(
        topic_id=topic_id,
        stage="write",
        tex_path="",
        report={},
        writing_mode="main",
    )
    assert "manuscript_polish_blocked" not in {f["check"] for f in findings}
