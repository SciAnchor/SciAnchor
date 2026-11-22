"""Backend command group for the RH CLI."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import click


def register(
    main: click.Group,
    *,
    create_backend: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register backend commands on the root CLI group."""

    @main.group()
    def backend() -> None:
        """Execution backend management."""

    @backend.command("list")
    @click.pass_context
    def backend_list(ctx: click.Context) -> None:
        """List available backends."""
        from .execution import get_backend_names

        names = get_backend_names()
        if ctx.obj.get("json"):
            click.echo(json.dumps(names, ensure_ascii=False))
            return
        for name in names:
            click.echo(name)

    @backend.command("info")
    @click.pass_context
    def backend_info(ctx: click.Context) -> None:
        """Show current backend info and capabilities."""
        info = create_backend(ctx).get_info()
        payload = dataclasses.asdict(info)
        echo(ctx, payload, f"{info.name}: {info.description}")

    @backend.command("primitives")
    @click.pass_context
    def backend_primitives(ctx: click.Context) -> None:
        """List primitives supported by current backend."""
        info = create_backend(ctx).get_info()
        if ctx.obj.get("json"):
            click.echo(json.dumps(info.supported_primitives, ensure_ascii=False))
            return
        for primitive_name in info.supported_primitives:
            click.echo(primitive_name)
