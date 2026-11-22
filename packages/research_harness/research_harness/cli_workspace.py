"""Workspace agent bootstrap commands for RH-backed projects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click


CLAUDE_WORKSPACE_GUIDE = """# Research Harness Workspace Agent Guide

This directory is an RH-backed research workspace.

- For research-paper tasks, use the `rh-paper-production` skill before drafting durable outputs.
- For architecture, method, graphical-abstract, or paper figure tasks, route through `rh-paper-figure-generator` and review with `figure-quality` before accepting the figure as publication-ready.
- Treat reusable human feedback about RH output quality, workflow routing, evidence, figures, or manuscript quality as an `rh-self-evolution` trigger and record it with `rh self-evolution record-human-feedback` when possible.
- Use RH artifacts, provenance, paper pools, and gates as the system of record. Local files are presentation artifacts unless also recorded in RH.
- Verify Claude Code and Codex skills with `rh skill doctor --agent claude-code --agent codex` after setup or updates.
"""

CODEX_WORKSPACE_GUIDE = """# Research Harness Workspace Agent Guide

All RH-backed research-paper tasks in this workspace should default to the `rh-paper-production` skill.

- Use `rh-paper-production` for manuscript, literature, experiment, reference-pool, and authorship work.
- Use `rh-paper-figure-generator` plus `figure-quality` for architecture/method figures.
- Route reusable human feedback through `rh-self-evolution` and `rh self-evolution record-human-feedback`.
- Prefer RH MCP/CLI artifacts, provenance, and gates over ad-hoc local-only state.
"""


def _agent_names(raw_agents: str) -> list[str]:
    names = [item.strip() for item in raw_agents.split(",") if item.strip()]
    return names or ["claude-code", "codex"]


def _write_if_needed(path: Path, content: str, *, dry_run: bool) -> dict[str, Any]:
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if "rh-paper-production" in existing and "rh-self-evolution" in existing:
            return {
                "path": str(path),
                "action": "ok",
                "reason": "already contains RH routing rules",
            }
        action = "would_skip_existing" if dry_run else "skipped_existing"
        return {
            "path": str(path),
            "action": action,
            "reason": "existing file needs manual merge",
        }
    if not dry_run:
        path.write_text(content, encoding="utf-8")
    return {
        "path": str(path),
        "action": "would_create" if dry_run else "created",
        "reason": "missing RH agent guide",
    }


def bootstrap_workspace_agents(
    path: Path, *, agents: list[str], dry_run: bool
) -> dict[str, Any]:
    workspace = path.expanduser().resolve()
    outputs: list[dict[str, Any]] = []
    if "claude-code" in agents or "claude" in agents:
        outputs.append(
            {
                "agent": "claude-code",
                **_write_if_needed(
                    workspace / "CLAUDE.md", CLAUDE_WORKSPACE_GUIDE, dry_run=dry_run
                ),
            }
        )
    if "codex" in agents:
        outputs.append(
            {
                "agent": "codex",
                **_write_if_needed(
                    workspace / "AGENTS.md", CODEX_WORKSPACE_GUIDE, dry_run=dry_run
                ),
            }
        )
    return {
        "schema_version": "rh.workspace_agent_bootstrap.v1",
        "workspace_path": str(workspace),
        "dry_run": dry_run,
        "agents": agents,
        "outputs": outputs,
        "ready": all(
            item["action"] in {"ok", "created", "would_create"} for item in outputs
        ),
    }


def register(main: click.Group) -> None:
    @main.group("workspace")
    def workspace_group() -> None:
        """Manage RH workspace agent integration surfaces."""

    @workspace_group.command("bootstrap-agents")
    @click.option(
        "--path",
        "workspace_path",
        required=True,
        type=click.Path(file_okay=False, path_type=Path),
    )
    @click.option(
        "--agents",
        default="claude-code,codex",
        help="Comma-separated agents to materialize: claude-code,codex",
    )
    @click.option(
        "--dry-run", is_flag=True, help="Report intended writes without changing files."
    )
    @click.pass_context
    def bootstrap_agents(
        ctx: click.Context, workspace_path: Path, agents: str, dry_run: bool
    ) -> None:
        """Materialize Claude/Codex RH routing instructions in a workspace."""

        payload = bootstrap_workspace_agents(
            workspace_path,
            agents=_agent_names(agents),
            dry_run=dry_run,
        )
        if ctx.obj and ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return
        click.echo(
            "RH workspace agent bootstrap "
            + ("ready" if payload["ready"] else "needs manual merge")
        )
        for item in payload["outputs"]:
            click.echo(
                f"  {item['agent']}: {item['action']} {item['path']} ({item['reason']})"
            )
