"""Shape-lock tests for the split CLI paper move module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_paper_move import register


def test_cli_paper_move_module_exports_register() -> None:
    assert callable(register)
    paper_group = main.commands["paper"]
    assert "move" in paper_group.commands
    assert "bulk-update" in paper_group.commands


def test_paper_move_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        ("move",): ["PAPER_IDS", "--from-topic", "--to-topic", "--relevance"],
        ("bulk-update",): [
            "PAPER_IDS",
            "--relevance",
            "--topic",
            "--screening-status",
            "--evidence-role",
            "--manuscript-eligible",
            "--paper-status",
        ],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["paper", *command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_paper_move_commands_keep_existing_registration_order() -> None:
    paper_commands = list(main.commands["paper"].commands)

    assert paper_commands.index("resolve-pdfs") < paper_commands.index("move")
    assert paper_commands.index("move") < paper_commands.index("bulk-update")
