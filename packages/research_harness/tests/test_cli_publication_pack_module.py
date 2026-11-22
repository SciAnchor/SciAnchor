"""Shape-lock tests for the split CLI publication-pack command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_publication_pack import register


def test_cli_publication_pack_module_exports_register() -> None:
    assert callable(register)
    assert "publication-pack" in main.commands


def test_publication_pack_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "generate": ["--topic", "--target-profile", "--record-artifact"],
        "venue-check": [
            "--topic",
            "--target-profile",
            "--compiled-pdf-path",
            "--page-count",
            "--anonymous",
            "--record-artifact",
        ],
        "backfill": ["--topic", "--target-profile", "--component", "--record-artifact"],
        "run": ["--topic", "--target-profile", "--component", "--record-artifact"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["publication-pack", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output
