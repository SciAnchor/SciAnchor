"""Shape-lock tests for the split CLI primitive command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_primitive import register


def test_cli_primitive_module_exports_register() -> None:
    assert callable(register)
    assert "primitive" in main.commands


def test_primitive_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    list_result = runner.invoke(main, ["primitive", "list", "--help"])
    exec_result = runner.invoke(main, ["primitive", "exec", "--help"])

    assert list_result.exit_code == 0, list_result.output
    assert exec_result.exit_code == 0, exec_result.output
    assert "--args" in exec_result.output
    assert "--topic" in exec_result.output
    assert "NAME" in exec_result.output
