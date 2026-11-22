"""Shape-lock tests for the split CLI orchestrator module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_orchestrator import register


ORCHESTRATOR_COMMANDS = [
    "init",
    "status",
    "artifacts",
    "advance",
    "gate-check",
    "adversarial-run",
    "adversarial-resolve",
    "adversarial-status",
    "review-bundle",
    "review-add-issue",
    "review-issues",
    "review-respond",
    "review-resolve",
    "review-status",
    "integrity-check",
    "finalize",
]


def test_cli_orchestrator_module_exports_register() -> None:
    assert callable(register)
    assert "orchestrator" in main.commands
    orchestrator = main.commands["orchestrator"]
    assert list(orchestrator.commands) == ORCHESTRATOR_COMMANDS


def test_orchestrator_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        ("init",): ["--topic", "--mode"],
        ("status",): ["--topic"],
        ("artifacts",): ["--topic", "--stage", "--type"],
        ("advance",): ["--topic", "--actor"],
        ("gate-check",): ["--topic", "--stage"],
        ("adversarial-run",): ["--topic", "--artifact-id", "--proposal"],
        ("adversarial-resolve",): ["--topic", "--round-artifact-id", "--scores"],
        ("adversarial-status",): ["--topic"],
        ("review-bundle",): ["--topic", "--integrity-artifact-id"],
        ("review-add-issue",): ["--topic", "--review-type", "--severity"],
        ("review-issues",): ["--topic", "--status", "--blocking-only"],
        ("review-respond",): ["--topic", "--issue-id", "--response-type"],
        ("review-resolve",): ["--topic", "--issue-id", "--status"],
        ("review-status",): ["--topic"],
        ("integrity-check",): ["--topic", "--findings"],
        ("finalize",): ["--topic"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["orchestrator", *command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_orchestrator_group_keeps_existing_top_level_registration_order() -> None:
    commands = list(main.commands)

    assert commands.index("provenance") < commands.index("orchestrator")
    assert commands.index("orchestrator") < commands.index("doctor")


def test_artifacts_command_exposes_active_and_lineage_options() -> None:
    result = CliRunner().invoke(main, ["orchestrator", "artifacts", "--help"])
    assert result.exit_code == 0, result.output
    for fragment in ("--active", "--lineage", "Topic name or id"):
        assert fragment in result.output
