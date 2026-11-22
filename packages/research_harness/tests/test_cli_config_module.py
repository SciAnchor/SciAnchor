"""Shape-lock tests for the split CLI config command module."""

from __future__ import annotations

import json

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_config import register


def test_cli_config_module_exports_register() -> None:
    assert callable(register)
    assert "config" in main.commands


def test_config_show_still_registered_from_split_module(runner: CliRunner) -> None:
    result = runner.invoke(main, ["--json", "config", "show"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["db_path"]
    assert payload["execution_backend"] == "local"
