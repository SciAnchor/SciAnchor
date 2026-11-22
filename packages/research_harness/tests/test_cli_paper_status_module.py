"""Shape-lock tests for the split CLI paper status module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_paper_status import register


def test_cli_paper_status_module_exports_register() -> None:
    assert callable(register)
    paper_group = main.commands["paper"]
    assert "status" in paper_group.commands
    assert "queue" in paper_group.commands


def test_paper_status_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "status": ["PAPER_ID"],
        "queue": ["--topic", "--limit", "--only-actionable"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["paper", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output
