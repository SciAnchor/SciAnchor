"""Shape-lock tests for the split CLI self-evolution command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_self_evolution import register


def test_cli_self_evolution_module_exports_register() -> None:
    assert callable(register)
    assert "self-evolution" in main.commands


def test_self_evolution_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "archive-from-artifacts": ["--topic", "--limit", "--stage"],
        "record-rfb-score-report": [
            "--topic",
            "--score-file",
            "--benchmark-id",
            "--split",
            "--title",
        ],
        "record-rfb-gate-report": ["--topic", "--gate-file", "--title"],
        "record-human-feedback": [
            "--topic",
            "--stage",
            "--section",
            "--feedback-file",
            "--workspace-path",
            "--agent",
            "--trigger-class",
        ],
        "record-note": [
            "--topic",
            "--stage",
            "--section",
            "--note",
            "--note-file",
            "--agent",
            "--trigger-class",
        ],
        "trajectory-list": ["--topic", "--stage", "--limit"],
        "trajectory-show": ["--session", "--limit"],
        "trajectory-diff": ["--session-a", "--session-b"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["self-evolution", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output
