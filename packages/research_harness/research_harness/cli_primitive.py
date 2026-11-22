"""Primitive command group for the RH CLI."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import click


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    create_backend: Callable[[click.Context], Any],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register primitive commands on the root CLI group."""

    @main.group()
    def primitive() -> None:
        """Research primitives management."""

    @primitive.command("list")
    @click.pass_context
    def primitive_list(ctx: click.Context) -> None:
        """List all registered research primitives."""
        from .primitives import list_primitives

        specs = list_primitives()
        payload = [
            {
                "name": spec.name,
                "category": spec.category.value,
                "description": spec.description,
                "requires_llm": spec.requires_llm,
            }
            for spec in specs
        ]
        if ctx.obj.get("json"):
            click.echo(json.dumps(payload, ensure_ascii=False))
            return
        for item in payload:
            click.echo(
                f"{item['name']} [{item['category']}] llm={item['requires_llm']} - {item['description']}"
            )

    @primitive.command("exec")
    @click.argument("name")
    @click.option("--args", "json_args", type=str, default="{}")
    @click.option("--topic", type=int, default=None)
    @click.pass_context
    def primitive_exec(
        ctx: click.Context, name: str, json_args: str, topic: int | None
    ) -> None:
        """Execute a research primitive."""
        from .execution.tracked import TrackedBackend
        from .provenance import ProvenanceRecorder

        try:
            kwargs = json.loads(json_args)
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"Invalid JSON args: {exc}") from exc
        if not isinstance(kwargs, dict):
            raise click.ClickException("--args must decode to a JSON object")

        raw_backend = create_backend(ctx)
        backend = TrackedBackend(
            raw_backend, ProvenanceRecorder(get_db(ctx)), default_topic_id=topic
        )
        try:
            result = backend.execute(name, **kwargs)
        except NotImplementedError as exc:
            raise click.ClickException(str(exc)) from exc

        payload = dataclasses.asdict(result)
        echo(ctx, payload, f"{name}: success={result.success}")
