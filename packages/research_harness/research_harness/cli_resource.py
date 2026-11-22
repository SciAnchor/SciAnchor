"""`rh resource` command group: SPC workflow_ready exchange (SPC -> RH).

Imports ``spc.workflow-ready.v1`` reports as build-stage ``spc.resource_ready``
artifacts and fetches the single active binding for a (topic, workflow, host)
triple. This is the RH read/import entry the paperfetch loop depends on.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import click


def register(
    main: click.Group,
    *,
    get_db: Callable[[click.Context], Any],
    topic_id_or_exit: Callable[[Any, str], int],
    echo: Callable[[click.Context, object, str | None], None],
) -> None:
    """Register the ``resource`` command group on the root CLI group."""

    @main.group()
    def resource() -> None:
        """SPC resource-ready exchange: import and fetch workflow_ready reports."""

    @resource.command("import-spc-ready")
    @click.option("--topic", "topic_name", required=True, help="Topic name or id")
    @click.option(
        "--file",
        "report_file",
        required=True,
        type=click.Path(exists=True, dir_okay=False),
        help="Path to workflow_ready.json (spc.workflow-ready.v1)",
    )
    @click.option(
        "--no-verify",
        "no_verify",
        is_flag=True,
        default=False,
        help="Skip content_digest verification (not recommended)",
    )
    @click.option(
        "--expect-workflow-ref",
        default=None,
        help="Fail unless the report's workflow_ref equals this value",
    )
    @click.option(
        "--expect-host",
        "expect_host",
        default=None,
        help="Fail unless the report's host_id equals this value",
    )
    @click.pass_context
    def import_spc_ready_cmd(
        ctx: click.Context,
        topic_name: str,
        report_file: str,
        no_verify: bool,
        expect_workflow_ref: str | None,
        expect_host: str | None,
    ) -> None:
        """Import an SPC workflow_ready report and bind it to the topic."""
        from .acquisition.resource_ready import (
            ResourceReadyError,
            import_spc_ready,
            parse_ready_report,
        )

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        raw = Path(report_file).read_text(encoding="utf-8")
        try:
            report = parse_ready_report(raw)
            result = import_spc_ready(
                db,
                topic_id,
                report,
                source_path=report_file,
                verify=not no_verify,
                expected_workflow_ref=expect_workflow_ref,
                expected_host_id=expect_host,
            )
        except ResourceReadyError as exc:
            raise click.ClickException(str(exc)) from exc

        superseded = result["superseded_artifact_ids"]
        message = (
            f"Imported resource-ready [{result['resource_status']}] "
            f"{result['workflow_ref']} @ {result['host_id']} "
            f"-> artifact #{result['artifact_id']} v{result['version']} "
            f"(binding_key={result['binding_key']}"
            + (f", superseded {superseded}" if superseded else "")
            + ")"
        )
        echo(ctx, result, message)

    @resource.command("get-ready")
    @click.option("--topic", "topic_name", required=True, help="Topic name or id")
    @click.option("--workflow-ref", required=True, help="workflow:<name>@<revision>")
    @click.option("--host", "host_id", required=True, help="host:<id>")
    @click.pass_context
    def get_ready_cmd(
        ctx: click.Context,
        topic_name: str,
        workflow_ref: str,
        host_id: str,
    ) -> None:
        """Fetch the single active resource-ready binding for (topic, workflow, host)."""
        from .acquisition.resource_ready import (
            compute_binding_key,
            get_ready,
            ready_status_summary,
        )

        db = get_db(ctx)
        conn = db.connect()
        try:
            topic_id = topic_id_or_exit(conn, topic_name)
        finally:
            conn.close()

        result = get_ready(db, topic_id, workflow_ref, host_id)
        if result is None:
            binding_key = compute_binding_key(topic_id, workflow_ref, host_id)
            payload = {
                "found": False,
                "binding_key": binding_key,
                "workflow_ref": workflow_ref,
                "host_id": host_id,
            }
            echo(
                ctx,
                payload,
                f"No active resource-ready for {workflow_ref} @ {host_id} "
                f"(binding_key={binding_key})",
            )
            ctx.exit(3)

        result = ready_status_summary(result)
        echo(
            ctx,
            result,
            f"artifact #{result['artifact_id']} v{result['version']} "
            f"[{result['resource_status']}] {workflow_ref} @ {host_id}",
        )
