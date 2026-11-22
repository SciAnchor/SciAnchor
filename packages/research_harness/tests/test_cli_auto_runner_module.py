"""Shape-lock tests for the split CLI auto-runner command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_auto_runner import register


def test_cli_auto_runner_module_exports_register() -> None:
    assert callable(register)
    assert "auto-runner" in main.commands


def test_auto_runner_start_help_still_registered_from_split_module() -> None:
    result = CliRunner().invoke(main, ["auto-runner", "start", "--help"])

    assert result.exit_code == 0, result.output
    assert "--topic-id" in result.output
    assert "--direction" in result.output
    assert "--mode" in result.output
    assert "--session-command" in result.output
    assert "--auto-approve" in result.output
    assert "--dry-run" in result.output


def test_auto_runner_start_preserves_runner_arguments(
    runner: CliRunner, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_topic(
        topic_id: int,
        *,
        direction: str,
        mode: str,
        session_command: list[str],
        auto_approve: bool,
        dry_run: bool,
    ) -> dict[str, object]:
        calls.append(
            {
                "topic_id": topic_id,
                "direction": direction,
                "mode": mode,
                "session_command": session_command,
                "auto_approve": auto_approve,
                "dry_run": dry_run,
            }
        )
        return {"summary": "planned run", "status": "ok"}

    monkeypatch.setattr("research_harness.auto_runner.runner.run_topic", fake_run_topic)

    result = runner.invoke(
        main,
        [
            "auto-runner",
            "start",
            "--topic-id",
            "7",
            "--direction",
            "agent evidence",
            "--mode",
            "demo",
            "--session-command",
            "codex exec",
            "--auto-approve",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output == "planned run\n"
    assert calls == [
        {
            "topic_id": 7,
            "direction": "agent evidence",
            "mode": "demo",
            "session_command": ["codex", "exec"],
            "auto_approve": True,
            "dry_run": True,
        }
    ]
