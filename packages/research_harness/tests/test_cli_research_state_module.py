"""Shape-lock tests for the split CLI research-state command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_research_state import register


def test_cli_research_state_module_exports_register() -> None:
    assert callable(register)
    assert "research-state" in main.commands


def test_research_state_record_still_registered_from_split_module() -> None:
    result = CliRunner().invoke(main, ["research-state", "record", "--help"])

    assert result.exit_code == 0, result.output
    for fragment in (
        "--topic",
        "--stage",
        "--event-type",
        "--title",
        "--summary",
        "--failure",
        "--fix",
        "--contradiction",
        "--review",
        "--next-action",
        "--record-artifact",
    ):
        assert fragment in result.output
