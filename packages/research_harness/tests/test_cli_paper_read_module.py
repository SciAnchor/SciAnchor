"""Shape-lock tests for the split CLI paper read module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_paper_read import (
    register_artifacts_card,
    register_list_show,
)


def test_cli_paper_read_module_exports_register_functions() -> None:
    assert callable(register_list_show)
    assert callable(register_artifacts_card)
    paper_group = main.commands["paper"]
    assert "list" in paper_group.commands
    assert "show" in paper_group.commands
    assert "artifacts" in paper_group.commands
    assert "card" in paper_group.commands


def test_paper_read_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "list": ["--topic", "--status"],
        "show": ["PAPER_ID"],
        "artifacts": ["PAPER_ID"],
        "card": ["PAPER_ID", "--output"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["paper", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_paper_read_commands_keep_existing_registration_order() -> None:
    paper_commands = list(main.commands["paper"].commands)

    assert paper_commands.index("ingest") < paper_commands.index("list")
    assert paper_commands.index("list") < paper_commands.index("show")
    assert paper_commands.index("show") < paper_commands.index("update")
    assert paper_commands.index("note") < paper_commands.index("artifacts")
    assert paper_commands.index("artifacts") < paper_commands.index("card")
    assert paper_commands.index("card") < paper_commands.index("acquire")
