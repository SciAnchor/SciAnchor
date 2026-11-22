"""Shape-lock tests for the split CLI paper management module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_paper_manage import register


def test_cli_paper_manage_module_exports_register() -> None:
    assert callable(register)
    paper_group = main.commands["paper"]
    assert "update" in paper_group.commands
    assert "link" in paper_group.commands


def test_paper_manage_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "update": ["PAPER_ID", "--title", "--pdf-path", "--status"],
        "link": ["PAPER_ID", "--topic", "--relevance"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["paper", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output
