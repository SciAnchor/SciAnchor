"""Shape-lock tests for the split CLI provenance command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_provenance import register


def test_cli_provenance_module_exports_register() -> None:
    assert callable(register)
    assert "provenance" in main.commands


def test_provenance_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "list": ["--topic", "--primitive", "--backend", "--limit"],
        "summary": ["--topic", "--backend"],
        "show": ["RECORD_ID"],
        "token-report": ["--topic"],
        "export": ["--topic", "--format", "--output"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["provenance", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output
