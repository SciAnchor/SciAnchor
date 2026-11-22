from __future__ import annotations

import json
from types import SimpleNamespace

from research_harness.cli import main


def _json_invoke(runner, args: list[str]) -> object:
    result = runner.invoke(main, ["--json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _seed_topic_and_paper(runner) -> None:
    topic = _json_invoke(
        runner,
        [
            "topic",
            "init",
            "transport-demo",
            "--description",
            "CLI transport convergence fixture.",
        ],
    )
    assert topic["id"] == 1
    paper = _json_invoke(
        runner,
        [
            "paper",
            "ingest",
            "--title",
            "Transport Test Paper",
            "--authors",
            "Ada Lovelace",
            "--year",
            "1843",
            "--topic",
            "transport-demo",
        ],
    )
    assert paper["paper_id"] == 1


def test_cli_topic_read_json_shapes_before_service_routing(runner):
    _seed_topic_and_paper(runner)

    topics = _json_invoke(runner, ["topic", "list"])
    assert len(topics) == 1
    assert topics[0]["id"] == 1
    assert topics[0]["name"] == "transport-demo"
    assert topics[0]["description"] == "CLI transport convergence fixture."
    assert topics[0]["status"] == "active"
    assert "created_at" in topics[0]

    topic = _json_invoke(runner, ["topic", "show", "transport-demo"])
    assert topic["id"] == 1
    assert topic["name"] == "transport-demo"
    assert topic["paper_count"] == 1


def test_cli_topic_list_routes_through_research_service(runner, monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(
                status="success",
                output={
                    "topics": [
                        {
                            "id": 77,
                            "name": "from-service",
                            "description": "service row",
                            "status": "active",
                            "target_venue": "",
                            "deadline": "",
                            "created_at": "2026-06-05 00:00:00",
                            "paper_count": 0,
                            "last_search_at": None,
                            "freshness_warn_days": 7,
                            "freshness_stale_days": 30,
                            "domain_id": None,
                            "contributions": "",
                            "target_venue_tier": "B",
                            "quality_tier": "standard",
                            "autonomy_level": "L2",
                            "updated_at": "",
                        }
                    ]
                },
                error=None,
            )

    monkeypatch.setattr(
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )

    payload = _json_invoke(runner, ["topic", "list"])

    assert calls == [("topic_list", {})]
    assert payload[0]["id"] == 77
    assert payload[0]["name"] == "from-service"


def test_cli_topic_show_routes_through_research_service(runner, monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(
                status="success",
                output={
                    "id": 88,
                    "name": "from-service",
                    "description": "service row",
                    "status": "active",
                    "target_venue": "",
                    "deadline": "",
                    "created_at": "2026-06-05 00:00:00",
                    "last_search_at": None,
                    "freshness_warn_days": 7,
                    "freshness_stale_days": 30,
                    "domain_id": None,
                    "contributions": "",
                    "target_venue_tier": "B",
                    "quality_tier": "standard",
                    "autonomy_level": "L2",
                    "updated_at": "",
                    "paper_count": 3,
                },
                error=None,
            )

    monkeypatch.setattr(
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )

    payload = _json_invoke(runner, ["topic", "show", "from-service"])

    assert calls == [("topic_show", {"name": "from-service"})]
    assert payload["id"] == 88
    assert payload["name"] == "from-service"
    assert payload["paper_count"] == 3


def test_cli_paper_list_json_shape_before_service_routing(runner):
    _seed_topic_and_paper(runner)

    papers = _json_invoke(runner, ["paper", "list", "--topic", "transport-demo"])

    assert len(papers) == 1
    assert papers[0]["id"] == 1
    assert papers[0]["title"] == "Transport Test Paper"
    assert papers[0]["status"] == "meta_only"
    assert papers[0]["year"] == 1843


def test_cli_paper_list_routes_through_research_service(runner, monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(
                status="success",
                output={
                    "papers": [
                        {
                            "id": 66,
                            "title": "Service Paper",
                            "status": "active",
                            "year": 2026,
                        }
                    ]
                },
                error=None,
            )

    monkeypatch.setattr(
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )

    payload = _json_invoke(runner, ["paper", "list"])

    assert calls == [("paper_list", {})]
    assert payload == [
        {
            "id": 66,
            "title": "Service Paper",
            "status": "active",
            "year": 2026,
        }
    ]


def test_cli_topic_list_rejects_incomplete_service_shape(runner, monkeypatch):
    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            return SimpleNamespace(
                status="success",
                output={"topics": [{"id": 1, "name": "incomplete"}]},
                error=None,
            )

    monkeypatch.setattr(
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )

    result = runner.invoke(main, ["--json", "topic", "list"])

    assert result.exit_code != 0
    assert "topic_list returned incomplete service topic payload" in result.output


def test_cli_paper_list_status_filter_uses_service_output(runner, monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(
                status="success",
                output={
                    "papers": [
                        {
                            "id": 66,
                            "title": "Service Paper",
                            "status": "deep_read",
                            "year": 2026,
                        },
                        {
                            "id": 67,
                            "title": "Filtered Out",
                            "status": "meta_only",
                            "year": 2025,
                        },
                    ]
                },
                error=None,
            )

    monkeypatch.setattr(
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )

    payload = _json_invoke(runner, ["paper", "list", "--status", "deep_read"])

    assert calls == [("paper_list", {})]
    assert payload == [
        {
            "id": 66,
            "title": "Service Paper",
            "status": "deep_read",
            "year": 2026,
        }
    ]


def test_cli_provenance_summary_json_shape_before_service_routing(runner):
    _seed_topic_and_paper(runner)

    summary = _json_invoke(runner, ["provenance", "summary"])

    assert summary["total_operations"] == 0
    assert summary["total_cost_usd"] == 0.0
    assert summary["operations_by_primitive"] == {}
    assert summary["operations_by_backend"] == {}
    assert summary["success_rate"] == 1.0


def test_cli_provenance_summary_routes_through_research_service(runner, monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(
                status="success",
                output={
                    "total_operations": 2,
                    "successful_operations": 2,
                    "failed_operations": 0,
                    "success_rate": 1.0,
                    "total_cost_usd": 0.03,
                    "total_tokens": {"prompt": 10, "completion": 5},
                    "operations_by_primitive": {"paper_search": 2},
                    "operations_by_backend": {"local": 2},
                    "cost_by_primitive": {"paper_search": 0.03},
                    "cost_by_backend": {"local": 0.03},
                    "tokens_by_primitive": {
                        "paper_search": {"prompt": 10, "completion": 5}
                    },
                    "tokens_by_backend": {"local": {"prompt": 10, "completion": 5}},
                },
                error=None,
            )

    monkeypatch.setattr(
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )

    payload = _json_invoke(runner, ["provenance", "summary", "--topic", "12"])

    assert calls == [("provenance_summary", {"topic_id": 12})]
    assert payload["total_operations"] == 2
    assert payload["operations_by_backend"] == {"local": 2}


def test_cli_provenance_summary_backend_filter_keeps_legacy_path(runner, monkeypatch):
    service_calls: list[tuple[str, dict[str, object]]] = []
    legacy_calls: list[tuple[int | None, str | None]] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            service_calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(status="success", output={}, error=None)

    def fake_legacy_payload(ctx, topic, backend_name):
        del ctx
        legacy_calls.append((topic, backend_name))
        return {
            "total_operations": 1,
            "successful_operations": 1,
            "failed_operations": 0,
            "success_rate": 1.0,
            "total_cost_usd": 0.0,
            "total_tokens": {"prompt": 0, "completion": 0},
            "operations_by_primitive": {"paper_search": 1},
            "operations_by_backend": {"local": 1},
            "cost_by_primitive": {"paper_search": 0.0},
            "cost_by_backend": {"local": 0.0},
            "tokens_by_primitive": {"paper_search": {"prompt": 0, "completion": 0}},
            "tokens_by_backend": {"local": {"prompt": 0, "completion": 0}},
        }

    monkeypatch.setattr(
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )
    monkeypatch.setattr(
        "research_harness.cli._legacy_provenance_summary_payload_for_cli",
        fake_legacy_payload,
        raising=False,
    )

    payload = _json_invoke(
        runner, ["provenance", "summary", "--topic", "12", "--backend", "local"]
    )

    assert service_calls == []
    assert legacy_calls == [(12, "local")]
    assert payload["operations_by_backend"] == {"local": 1}


def test_cli_provenance_export_json_shape_before_service_routing(runner):
    _seed_topic_and_paper(runner)

    records = _json_invoke(runner, ["provenance", "export"])

    assert records == []


def test_cli_provenance_export_routes_through_research_service(runner, monkeypatch):
    _seed_topic_and_paper(runner)
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(
                status="success",
                output={
                    "format": "json",
                    "records": [
                        {
                            "id": 44,
                            "primitive": "paper_search",
                            "backend": "local",
                            "model_used": "",
                            "cost_usd": 0.0,
                            "success": True,
                            "started_at": "2026-06-05T00:00:00+00:00",
                            "finished_at": "2026-06-05T00:00:01+00:00",
                        }
                    ],
                },
                error=None,
            )

    monkeypatch.setattr(
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )

    records = _json_invoke(
        runner, ["provenance", "export", "--topic", "transport-demo"]
    )

    assert calls == [("provenance_export", {"format": "json", "topic_id": 1})]
    assert records[0]["id"] == 44
    assert records[0]["primitive"] == "paper_search"


def test_cli_provenance_export_csv_keeps_legacy_path(runner, monkeypatch):
    service_calls: list[tuple[str, dict[str, object]]] = []
    legacy_calls: list[int | None] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            service_calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(status="success", output={"records": []}, error=None)

    def fake_legacy_records(ctx, topic_id):
        del ctx
        legacy_calls.append(topic_id)
        return [
            {
                "primitive": "paper_search",
                "backend": "local",
                "model_used": "",
                "cost_usd": 0.0,
                "success": True,
                "started_at": "2026-06-05T00:00:00+00:00",
                "finished_at": "2026-06-05T00:00:01+00:00",
            }
        ]

    monkeypatch.setattr(
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )
    monkeypatch.setattr(
        "research_harness.cli._legacy_provenance_export_records_for_cli",
        fake_legacy_records,
        raising=False,
    )

    result = runner.invoke(main, ["provenance", "export", "--format", "csv"])

    assert result.exit_code == 0, result.output
    assert service_calls == []
    assert legacy_calls == [None]
    assert "primitive_name" in result.output
    assert "paper_search" in result.output


def test_cli_orchestrator_read_json_shapes_before_service_routing(runner):
    _seed_topic_and_paper(runner)
    init_result = _json_invoke(
        runner, ["orchestrator", "init", "--topic", "transport-demo"]
    )
    assert init_result["topic_id"] == 1
    assert init_result["current_stage"] == "init"

    status = _json_invoke(
        runner, ["orchestrator", "status", "--topic", "transport-demo"]
    )
    assert status["run"]["topic_id"] == 1
    assert status["run"]["current_stage"] == "init"

    gate = _json_invoke(
        runner, ["orchestrator", "gate-check", "--topic", "transport-demo"]
    )
    assert "gate_decision" in gate
    assert gate["stage"] == "current"


def test_cli_orchestrator_status_routes_through_research_service(runner, monkeypatch):
    _seed_topic_and_paper(runner)
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeResearchService:
        def __init__(self, db):
            self.db = db

        def invoke(self, command_name, arguments=None):
            calls.append((command_name, dict(arguments or {})))
            return SimpleNamespace(
                status="success",
                output={
                    "run": {"topic_id": 1, "current_stage": "init"},
                    "stage": {"missing_artifacts": []},
                    "gate": {"decision": "pass", "can_advance": True},
                    "db_path": "/tmp/internal.db",
                },
                error=None,
            )

    monkeypatch.setattr(
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )

    status = _json_invoke(
        runner, ["orchestrator", "status", "--topic", "transport-demo"]
    )

    assert calls == [("orchestrator_status", {"topic_id": 1})]
    assert status["run"]["topic_id"] == 1
    assert status["run"]["current_stage"] == "init"
    assert "db_path" not in status


def test_cli_orchestrator_gate_check_routes_through_research_service(
    runner, monkeypatch
):
    _seed_topic_and_paper(runner)
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
        "research_harness.cli.ResearchService", FakeResearchService, raising=False
    )

    gate = _json_invoke(
        runner,
        [
            "orchestrator",
            "gate-check",
            "--topic",
            "transport-demo",
            "--stage",
            "topic_framing",
        ],
    )

    assert calls == [
        (
            "orchestrator_gate_check",
            {"topic_id": 1, "stage": "topic_framing"},
        )
    ]
    assert gate == {
        "gate_decision": "needs_approval",
        "stage": "topic_framing",
    }
