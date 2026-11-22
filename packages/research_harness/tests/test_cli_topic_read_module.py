"""Shape-lock tests for the split CLI topic read module."""

from __future__ import annotations

import json

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_topic_read import register


def test_cli_topic_read_module_exports_register() -> None:
    assert callable(register)
    topic_group = main.commands["topic"]
    assert "list" in topic_group.commands
    assert "show" in topic_group.commands


def test_topic_read_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "list": [],
        "show": ["TOPIC_NAME"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["topic", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_topic_read_commands_keep_existing_registration_order() -> None:
    topic_commands = list(main.commands["topic"].commands)

    assert topic_commands.index("workspace") < topic_commands.index("list")
    assert topic_commands.index("list") < topic_commands.index("show")
    assert topic_commands.index("show") < topic_commands.index("knowledge-status")


def test_topic_list_json_still_uses_topic_read_module(runner) -> None:
    create = runner.invoke(main, ["topic", "init", "topic-read-a"])
    assert create.exit_code == 0, create.output
    create = runner.invoke(main, ["topic", "init", "topic-read-b"])
    assert create.exit_code == 0, create.output

    result = runner.invoke(main, ["--json", "topic", "list"])

    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert [row["name"] for row in rows] == ["topic-read-b", "topic-read-a"]
