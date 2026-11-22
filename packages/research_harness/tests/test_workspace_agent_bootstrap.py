from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_workspace import bootstrap_workspace_agents


def test_workspace_bootstrap_agents_materializes_claude_and_codex_guides(tmp_path):
    workspace = tmp_path / "rh-workspace" / "domain" / "topic"
    workspace.mkdir(parents=True)

    payload = bootstrap_workspace_agents(
        workspace,
        agents=["claude-code", "codex"],
        dry_run=False,
    )

    assert payload["ready"] is True
    claude = (workspace / "CLAUDE.md").read_text(encoding="utf-8")
    codex = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    for text in (claude, codex):
        assert "rh-paper-production" in text
        assert "rh-paper-figure-generator" in text
        assert "figure-quality" in text
        assert "rh-self-evolution" in text


def test_workspace_bootstrap_agents_cli_dry_run_reports_outputs(tmp_path):
    workspace = tmp_path / "rh-workspace" / "domain" / "topic"
    workspace.mkdir(parents=True)
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "--json",
            "workspace",
            "bootstrap-agents",
            "--path",
            str(workspace),
            "--agents",
            "claude-code,codex",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "rh.workspace_agent_bootstrap.v1" in result.output
    assert "CLAUDE.md" in result.output
    assert "AGENTS.md" in result.output
