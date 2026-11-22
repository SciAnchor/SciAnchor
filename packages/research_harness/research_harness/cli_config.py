"""Config command group for the RH CLI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from .config import find_workspace_root, init_project_config, load_runtime_config


def register(
    main: click.Group,
    *,
    get_runtime_config: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register config commands on the root CLI group."""

    @main.group()
    def config() -> None:
        """Manage runtime config."""

    @config.command("show")
    @click.pass_context
    def config_show(ctx: click.Context) -> None:
        runtime_config = get_runtime_config(ctx)
        payload = {
            "db_path": str(runtime_config.db_path),
            "source": runtime_config.source,
            "workspace_root": str(runtime_config.workspace_root)
            if runtime_config.workspace_root
            else None,
            "config_path": str(runtime_config.config_path)
            if runtime_config.config_path
            else None,
            "execution_backend": runtime_config.execution_backend,
            "research_workspace_root": str(runtime_config.research_workspace_root)
            if runtime_config.research_workspace_root
            else None,
        }
        echo(ctx, payload, f"DB: {payload['db_path']} ({payload['source']})")

    @config.command("init")
    @click.option(
        "--db-path",
        default=None,
        help="Store a project-local DB path in .research-harness/config.json",
    )
    @click.option(
        "--research-workspace-root",
        default=None,
        help="Directory where topic workspaces should be materialized.",
    )
    @click.pass_context
    def config_init(
        ctx: click.Context, db_path: str | None, research_workspace_root: str | None
    ) -> None:
        workspace_root = find_workspace_root() or Path.cwd()
        config_path = init_project_config(
            workspace_root,
            db_path=db_path,
            research_workspace_root=research_workspace_root,
        )
        ctx.obj["runtime_config"] = load_runtime_config(
            ctx.obj.get("db_path"), cwd=workspace_root
        )
        payload = {
            "config_path": str(config_path),
            "workspace_root": str(workspace_root),
            "db_path": str(get_runtime_config(ctx).db_path),
            "source": get_runtime_config(ctx).source,
            "execution_backend": get_runtime_config(ctx).execution_backend,
            "research_workspace_root": str(
                get_runtime_config(ctx).research_workspace_root
            )
            if get_runtime_config(ctx).research_workspace_root
            else None,
        }
        echo(ctx, payload, f"Initialized project config at {config_path}")
