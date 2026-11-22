"""Shape-lock tests for the split CLI topic lifecycle module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_topic_lifecycle import (
    register_export,
    register_init_workspace,
)


def test_cli_topic_lifecycle_module_exports_register_functions() -> None:
    assert callable(register_init_workspace)
    assert callable(register_export)
    topic_group = main.commands["topic"]
    assert "init" in topic_group.commands
    assert "workspace" in topic_group.commands
    assert "export" in topic_group.commands


def test_topic_lifecycle_commands_still_registered_from_split_module() -> None:
    runner = CliRunner()

    commands = {
        "init": ["NAME", "--description", "--venue", "--deadline", "--domain"],
        "workspace": ["TOPIC_NAME", "--workspace-root", "--workspace-domain", "--slug"],
        "export": ["NAME", "--output"],
    }
    for command, expected_fragments in commands.items():
        result = runner.invoke(main, ["topic", command, "--help"])

        assert result.exit_code == 0, result.output
        for fragment in expected_fragments:
            assert fragment in result.output


def test_topic_lifecycle_commands_keep_existing_registration_order() -> None:
    topic_commands = list(main.commands["topic"].commands)

    assert topic_commands.index("init") < topic_commands.index("workspace")
    assert topic_commands.index("workspace") < topic_commands.index("list")
    assert topic_commands.index("overview") < topic_commands.index("export")
