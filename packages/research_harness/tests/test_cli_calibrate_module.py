"""Shape-lock tests for the split CLI calibrate command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_calibrate import register


def test_cli_calibrate_module_exports_register() -> None:
    assert callable(register)
    assert "calibrate" in main.commands


def test_calibrate_run_help_still_registered_from_split_module() -> None:
    result = CliRunner().invoke(main, ["calibrate", "run", "--help"])

    assert result.exit_code == 0, result.output
    assert "--stage" in result.output
    assert "--tier" in result.output
    assert "--venue-tier" in result.output
    assert "--dry-run" in result.output


def test_calibrate_list_empty_db_output_shape(runner: CliRunner) -> None:
    result = runner.invoke(main, ["calibrate", "list"])

    assert result.exit_code == 0, result.output
    assert (
        result.output
        == "No calibrations recorded. Run `rh calibrate all` to seed them.\n"
    )
