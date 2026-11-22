"""Shape-lock tests for the split CLI paper annotation module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_paper_annotations import register


def test_cli_paper_annotations_module_exports_register() -> None:
    assert callable(register)
    paper_group = main.commands["paper"]
    assert "annotate" in paper_group.commands
    assert "annotations" in paper_group.commands
    assert "note" in paper_group.commands
    note_group = paper_group.commands["note"]
    assert "set" in note_group.commands
    assert "draft" in note_group.commands
    assert "list" in note_group.commands


def test_paper_annotation_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        ("annotate",): ["PAPER_ID", "--pdf", "--section"],
        ("annotations",): ["PAPER_ID", "--section"],
        ("note", "set"): ["--paper-id", "--topic", "--type", "--content"],
        ("note", "draft"): ["--paper-id", "--topic", "--type", "--save"],
        ("note", "list"): ["--paper-id", "--topic", "--type"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["paper", *command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_paper_annotation_commands_keep_existing_registration_order() -> None:
    paper_commands = list(main.commands["paper"].commands)

    assert paper_commands.index("status") < paper_commands.index("annotate")
    assert paper_commands.index("annotate") < paper_commands.index("annotations")
    assert paper_commands.index("annotations") < paper_commands.index("note")
    assert paper_commands.index("note") < paper_commands.index("artifacts")
