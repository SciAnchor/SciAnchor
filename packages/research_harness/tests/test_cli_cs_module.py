"""Shape-lock tests for the split CLI CS command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_cs import register


def test_cli_cs_module_exports_register() -> None:
    assert callable(register)
    assert "cs" in main.commands


def test_cs_harvest_help_still_registered_from_split_module() -> None:
    result = CliRunner().invoke(main, ["cs", "harvest", "--help"])

    assert result.exit_code == 0, result.output
    assert "--year" in result.output
    assert "--per-provider-limit" in result.output
    assert "--classify / --no-classify" in result.output
    assert "--red-ocean / --no-red-ocean" in result.output
