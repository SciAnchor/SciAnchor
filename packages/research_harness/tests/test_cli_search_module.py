"""Shape-lock tests for the split CLI search command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_search import register


def test_cli_search_module_exports_register() -> None:
    assert callable(register)
    assert "search" in main.commands


def test_search_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "log": ["--topic", "--query", "--provider", "--result-count"],
        "list": ["--topic", "--provider", "--limit"],
        "providers": [],
        "papers": ["--query", "--topic", "--limit", "--year-from", "--log-run"],
        "pubmed-screen": ["--query", "--limit", "--year-from", "--year-to"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["search", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output
