"""Shape-lock tests for the split CLI review command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_review import register


def test_cli_review_module_exports_register() -> None:
    assert callable(register)
    assert "review" in main.commands


def test_review_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    add_result = runner.invoke(main, ["review", "add", "--help"])
    list_result = runner.invoke(main, ["review", "list", "--help"])

    assert add_result.exit_code == 0, add_result.output
    assert "--topic" in add_result.output
    assert "--gate" in add_result.output
    assert "--reviewer" in add_result.output
    assert "--verdict" in add_result.output
    assert "--findings" in add_result.output
    assert list_result.exit_code == 0, list_result.output
    assert "--topic" in list_result.output
