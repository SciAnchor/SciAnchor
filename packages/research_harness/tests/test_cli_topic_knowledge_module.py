"""Shape-lock tests for the split CLI topic knowledge module."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_topic_knowledge import register
from research_harness.service import ServiceResult


def test_cli_topic_knowledge_module_exports_register() -> None:
    assert callable(register)
    topic_group = main.commands["topic"]
    assert "knowledge-status" in topic_group.commands
    assert "knowledge-refresh" in topic_group.commands
    assert "cross-topic-atlas" in topic_group.commands


def test_topic_knowledge_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "knowledge-status": ["--topic-id"],
        "knowledge-refresh": ["--topic-id", "--all"],
        "wiki-context-pack": ["--topic-id", "--action-name"],
        "cross-topic-atlas": ["--topic-id", "--max-results"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["topic", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_topic_knowledge_status_cli_routes_through_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import research_harness.cli_topic_knowledge as module

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
                    "schema_version": "knowledge_status.v1",
                    "topic_id": arguments["topic_id"],
                    "status": "ready",
                    "readiness_status": "ready",
                },
            )

    monkeypatch.setattr(module, "ResearchService", FakeService)

    result = CliRunner().invoke(
        main,
        [
            "--db",
            str(tmp_path / "status.db"),
            "topic",
            "knowledge-status",
            "--topic-id",
            "7",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("topic_knowledge_status", {"topic_id": 7})]


def test_topic_knowledge_refresh_cli_routes_through_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import json

    import research_harness.cli_topic_knowledge as module

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
                    "topic_id": arguments["topic_id"],
                    "status": "refreshed",
                    "artifact_id": 11,
                },
            )

    monkeypatch.setattr(module, "ResearchService", FakeService)

    result = CliRunner().invoke(
        main,
        [
            "--db",
            str(tmp_path / "refresh.db"),
            "topic",
            "knowledge-refresh",
            "--topic-id",
            "7",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "refreshed"
    assert calls == [("topic_knowledge_refresh", {"topic_id": 7})]
