"""CLI: rh deposit zenodo — pack topic code/data and mint DOIs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import click


def register(
    main: click.Group,
    *,
    get_db: Callable[..., Any],
    topic_id_or_exit: Callable[..., int],
    echo: Callable[..., None],
) -> None:
    @main.group("deposit")
    def deposit_group() -> None:
        """Deposit supporting code/data packages and mint DOIs."""

    @deposit_group.command("zenodo")
    @click.option("--topic", "topic_ref", default=None, help="Topic id or name.")
    @click.option(
        "--title", default=None, help="Deposit title base (defaults to topic name)."
    )
    @click.option("--creator", default=None, help='Author "Last, First".')
    @click.option(
        "--email", default=None, envvar="ZENODO_EMAIL", help="Zenodo account email."
    )
    @click.option(
        "--password",
        default=None,
        envvar="ZENODO_PASSWORD",
        help="Zenodo password (prefer token; used only to mint a PAT).",
    )
    @click.option(
        "--token",
        default=None,
        envvar="ZENODO_TOKEN",
        help="Zenodo personal access token.",
    )
    @click.option("--code", "code_path", type=click.Path(path_type=Path), default=None)
    @click.option("--data", "data_path", type=click.Path(path_type=Path), default=None)
    @click.option("--deposit-root", type=click.Path(path_type=Path), default=None)
    @click.option("--sandbox", is_flag=True, help="Use sandbox.zenodo.org.")
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Upload drafts only; do not publish / register DOIs.",
    )
    @click.pass_context
    def deposit_zenodo_cli(
        ctx: click.Context,
        topic_ref: str | None,
        title: str | None,
        creator: str | None,
        email: str | None,
        password: str | None,
        token: str | None,
        code_path: Path | None,
        data_path: Path | None,
        deposit_root: Path | None,
        sandbox: bool,
        dry_run: bool,
    ) -> None:
        """Pack code+data for a topic and mint Zenodo DOIs."""
        from research_harness.deposit.zenodo import deposit_code_and_data, lookup_topic

        topic_id: int | None = None
        topic_name: str | None = None
        if topic_ref:
            db = get_db(ctx)
            conn = db.connect()
            try:
                topic_id = topic_id_or_exit(conn, topic_ref)
            finally:
                conn.close()
            tid, tname = lookup_topic(db.path, topic_id=topic_id)
            topic_id, topic_name = tid, tname

        result = deposit_code_and_data(
            topic_id=topic_id,
            topic_name=topic_name or title,
            title=title or topic_name,
            creator=creator,
            email=email,
            password=password,
            token=token,
            code_path=code_path,
            data_path=data_path,
            deposit_root=deposit_root,
            sandbox=sandbox,
            publish=not dry_run,
        )
        payload = result.to_dict()
        summary_lines = [
            f"status: {result.status}",
            f"code_doi: {result.code_doi or '-'}",
            f"data_doi: {result.data_doi or '-'}",
            f"published: {result.published}",
            f"sandbox: {result.sandbox}",
        ]
        if result.error:
            summary_lines.append(f"error: {result.error}")
        echo(ctx, payload, "\n".join(summary_lines))
        if result.status == "error":
            raise SystemExit(1)
