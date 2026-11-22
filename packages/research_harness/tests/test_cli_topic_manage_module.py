"""Shape-lock tests for the split CLI topic management module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_topic_manage import register_update


def test_cli_topic_manage_module_exports_register_update() -> None:
    assert callable(register_update)
    topic_group = main.commands["topic"]
    assert "update" in topic_group.commands


def test_topic_update_command_still_registered_from_split_module() -> None:
    result = CliRunner().invoke(main, ["topic", "update", "--help"])

    assert result.exit_code == 0, result.output
    for fragment in ("TOPIC_NAME", "--new-name", "--description", "--status"):
        assert fragment in result.output


def test_topic_update_command_keeps_existing_registration_order() -> None:
    topic_commands = list(main.commands["topic"].commands)

    assert topic_commands.index("cross-topic-atlas") < topic_commands.index("update")
    assert topic_commands.index("update") < topic_commands.index("overview")


def test_topic_summary_refresh_registered_and_help() -> None:
    topic_group = main.commands["topic"]
    assert "summary-refresh" in topic_group.commands
    result = CliRunner().invoke(main, ["topic", "summary-refresh", "--help"])
    assert result.exit_code == 0, result.output
    assert "TOPIC_ID" in result.output
