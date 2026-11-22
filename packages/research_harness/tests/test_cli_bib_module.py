"""Shape-lock tests for the split CLI BibTeX command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_bib import register


def test_cli_bib_module_exports_register() -> None:
    assert callable(register)
    assert "bib" in main.commands


def test_bib_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    set_result = runner.invoke(main, ["bib", "set", "--help"])
    show_result = runner.invoke(main, ["bib", "show", "--help"])
    export_result = runner.invoke(main, ["bib", "export", "--help"])

    assert set_result.exit_code == 0, set_result.output
    assert "--paper-id" in set_result.output
    assert "--verified-by" in set_result.output
    assert show_result.exit_code == 0, show_result.output
    assert "PAPER_ID" in show_result.output
    assert export_result.exit_code == 0, export_result.output
    assert "--topic" in export_result.output
    assert "--output" in export_result.output
