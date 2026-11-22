"""Shape-lock tests for the split CLI Zotero command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_zotero import register


def test_cli_zotero_module_exports_register() -> None:
    assert callable(register)
    assert "zotero" in main.commands


def test_zotero_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "sync": [
            "--topic",
            "--root-collection",
            "--library-id",
            "--adapter",
            "--direction",
            "--dry-run",
        ],
        "push": [
            "--topic",
            "--root-collection",
            "--library-id",
            "--adapter",
            "--direction",
            "--dry-run",
        ],
        "pull": [
            "--topic",
            "--library-id",
            "--library-type",
            "--api-key",
            "--include-rh-generated",
            "--dry-run",
        ],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["zotero", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output
