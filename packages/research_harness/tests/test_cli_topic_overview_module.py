"""Shape-lock tests for the split CLI topic overview module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_topic_overview import register


def test_cli_topic_overview_module_exports_register() -> None:
    assert callable(register)
    topic_group = main.commands["topic"]
    assert "overview" in topic_group.commands


def test_topic_overview_command_still_registered_from_split_module() -> None:
    result = CliRunner().invoke(main, ["topic", "overview", "--help"])

    assert result.exit_code == 0, result.output
    assert "TOPIC_NAME" in result.output


def test_topic_overview_command_keeps_existing_registration_order() -> None:
    topic_commands = list(main.commands["topic"].commands)

    assert topic_commands.index("update") < topic_commands.index("overview")
    assert topic_commands.index("overview") < topic_commands.index("export")
