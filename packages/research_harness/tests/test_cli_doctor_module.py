"""Shape-lock tests for the split CLI doctor command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_doctor import register


def test_cli_doctor_module_exports_register() -> None:
    assert callable(register)
    assert "doctor" in main.commands


def test_doctor_help_still_registered_from_split_module() -> None:
    result = CliRunner().invoke(main, ["doctor", "--help"])

    assert result.exit_code == 0, result.output
    assert "--runtime-diagnostics" in result.output
    assert "--productization-boundary" in result.output
