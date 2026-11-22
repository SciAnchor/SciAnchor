"""Shape-lock tests for the split CLI task command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_task import register


def test_cli_task_module_exports_register() -> None:
    assert callable(register)
    assert "task" in main.commands


def test_task_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "list": ["--topic", "--status"],
        "add": ["--topic", "--title", "--priority", "--description"],
        "generate": ["--topic", "--dry-run"],
        "update": ["TASK_ID", "--status", "--priority"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["task", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output
