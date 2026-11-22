"""CLI registration for public productization previews."""

from __future__ import annotations

import json
from typing import Any

import click

from .boundary import build_lg10_productization_boundary_payload


def _json_requested(ctx: click.Context, command_json: bool) -> bool:
    return bool(command_json or ctx.obj.get("json"))


def _exit_with_json_error(
    ctx: click.Context,
    *,
    code: str,
    message: str,
    exit_code: int,
    command_json: bool,
) -> None:
    if _json_requested(ctx, command_json):
        click.echo(
            json.dumps(
                {"error": {"code": code, "message": message}},
                ensure_ascii=False,
            )
        )
        ctx.exit(exit_code)
    raise click.ClickException(message)


def register(root: click.Group) -> None:
    @root.group("productization")
    def productization_group() -> None:
        """Public productization previews."""

    @productization_group.command("boundary")
    @click.option(
        "--experimental-lg10",
        is_flag=True,
        default=False,
        help="Opt in to the LG10 public-productization boundary preview.",
    )
    @click.option("--json", "command_json", is_flag=True, default=False)
    @click.pass_context
    def boundary(
        ctx: click.Context,
        experimental_lg10: bool,
        command_json: bool,
    ) -> None:
        """Show the LG10 public-productization boundary."""
        if not experimental_lg10:
            _exit_with_json_error(
                ctx,
                code="lg10_opt_in_required",
                message="pass --experimental-lg10 to view the LG10 boundary",
                exit_code=2,
                command_json=command_json,
            )
            return

        payload: dict[str, Any] = build_lg10_productization_boundary_payload()
        if _json_requested(ctx, command_json):
            click.echo(json.dumps(payload, ensure_ascii=False, default=str))
            return

        click.echo(f"Boundary: {payload['boundary_id']}")
        click.echo(f"LG10: {payload['lg10_status']}")
        click.echo(f"Allowed future pattern: {payload['allowed_future_pattern']}")
