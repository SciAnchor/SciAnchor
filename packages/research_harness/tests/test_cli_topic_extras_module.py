"""Shape-lock tests for the split CLI topic extras module."""

from __future__ import annotations

import json

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_topic_extras import register


def test_cli_topic_extras_module_exports_register() -> None:
    assert callable(register)
    topic_group = main.commands["topic"]
    assert "stats" in topic_group.commands
    assert "get-contributions" in topic_group.commands
    assert "set-contributions" in topic_group.commands


def test_topic_extras_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "stats": ["TOPIC_NAME"],
        "get-contributions": ["TOPIC_NAME"],
        "set-contributions": ["TOPIC_NAME", "TEXT"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["topic", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_topic_contributions_round_trip_still_uses_topic_extras_module(runner) -> None:
    create = runner.invoke(main, ["topic", "init", "contrib-topic"])
    assert create.exit_code == 0, create.output

    set_result = runner.invoke(
        main,
        [
            "--json",
            "topic",
            "set-contributions",
            "contrib-topic",
            "We contribute a deterministic CLI split.",
        ],
    )
    assert set_result.exit_code == 0, set_result.output
    assert json.loads(set_result.output) == {
        "topic": "contrib-topic",
        "contributions": "We contribute a deterministic CLI split.",
        "updated": True,
    }

    get_result = runner.invoke(
        main,
        ["--json", "topic", "get-contributions", "contrib-topic"],
    )
    assert get_result.exit_code == 0, get_result.output
    assert json.loads(get_result.output) == {
        "topic": "contrib-topic",
        "contributions": "We contribute a deterministic CLI split.",
    }
