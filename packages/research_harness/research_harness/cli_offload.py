"""Semi-automatic offload commands for RH batch workers."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from . import offload


def register(
    main: click.Group,
    *,
    get_runtime_config: Callable[[click.Context], Any],
) -> None:
    """Register the offload command group on the root CLI."""

    @main.group(name="offload")
    def offload_group() -> None:
        """Prepare and exchange retryable offload task packs."""

    @offload_group.command("doctor")
    @click.option(
        "--host",
        envvar="RH_OFFLOAD_HOST",
        help="SSH host alias. Can also be set with RH_OFFLOAD_HOST.",
    )
    @click.option(
        "--remote-root",
        default=str(offload.DEFAULT_REMOTE_ROOT),
        envvar="RH_OFFLOAD_REMOTE_ROOT",
        show_default=True,
        help="Remote offload root. Can also be set with RH_OFFLOAD_REMOTE_ROOT.",
    )
    @click.option(
        "--skip-ssh",
        is_flag=True,
        default=False,
        help="Do not attempt SSH; print local read-only checks only.",
    )
    @click.option(
        "--timeout-seconds",
        default=30,
        show_default=True,
        type=int,
        help="SSH probe timeout for read-only doctor checks.",
    )
    @click.pass_context
    def doctor_cmd(
        ctx: click.Context,
        host: str | None,
        remote_root: str,
        skip_ssh: bool,
        timeout_seconds: int,
    ) -> None:
        payload = _call_offload(
            offload.doctor,
            host=host,
            remote_root=remote_root,
            skip_ssh=skip_ssh,
            timeout_seconds=timeout_seconds,
        )
        host_label = payload["host"] or "unconfigured host"
        _emit(ctx, payload, f"offload doctor for {host_label}: read-only")

    @offload_group.command("prepare")
    @click.option(
        "--type",
        "task_type",
        required=True,
        type=click.Choice(sorted(offload.TASK_TYPES)),
        help="Offload task type.",
    )
    @click.option("--topic", required=True, help="Topic id or name.")
    @click.option(
        "--out",
        "out_dir",
        required=True,
        type=click.Path(path_type=Path),
        help="Local task package directory.",
    )
    @click.option(
        "--library-snapshot",
        type=click.Path(path_type=Path),
        help="Optional redacted remote-library snapshot JSON created by remote-library-scan.",
    )
    @click.option(
        "--include-pdf-files",
        is_flag=True,
        default=False,
        help=(
            "For paper_text_extraction_batch only, explicitly copy safe local "
            "PDF files into the task pack."
        ),
    )
    @click.option(
        "--max-pdf-bytes",
        default=offload.PAPER_TEXT_PDF_MAX_BYTES,
        show_default=True,
        type=int,
        help="Maximum bytes per explicitly packaged PDF.",
    )
    @click.pass_context
    def prepare_cmd(
        ctx: click.Context,
        task_type: str,
        topic: str,
        out_dir: Path,
        library_snapshot: Path | None,
        include_pdf_files: bool,
        max_pdf_bytes: int,
    ) -> None:
        runtime_config = get_runtime_config(ctx)
        task_dir = _call_offload(
            offload.prepare_task,
            task_type=task_type,
            topic=topic,
            out_dir=out_dir,
            db_path=runtime_config.db_path,
            library_snapshot=library_snapshot,
            include_pdf_files=include_pdf_files,
            max_pdf_bytes=max_pdf_bytes,
        )
        manifest = offload.load_task_manifest(task_dir)
        payload = {
            "task_id": manifest["task_id"],
            "task_type": manifest["task_type"],
            "status": manifest["status"],
            "path": str(task_dir),
        }
        _emit(ctx, payload, f"prepared {manifest['task_id']} at {task_dir}")

    @offload_group.command("remote-library-scan")
    @click.option(
        "--host",
        envvar="RH_OFFLOAD_HOST",
        help="SSH host alias. Can also be set with RH_OFFLOAD_HOST.",
    )
    @click.option(
        "--library-root",
        required=True,
        help="Remote library root to scan read-only.",
    )
    @click.option(
        "--query",
        required=True,
        help="Query terms used only to sample matching remote filenames.",
    )
    @click.option(
        "--out",
        "out_path",
        required=True,
        type=click.Path(path_type=Path),
        help="Local redacted snapshot JSON path.",
    )
    @click.option(
        "--limit",
        default=25,
        show_default=True,
        type=int,
        help="Maximum sample count to include in the snapshot.",
    )
    @click.option(
        "--max-files",
        default=5000,
        show_default=True,
        type=int,
        help="Maximum matching file candidates to scan remotely.",
    )
    @click.option(
        "--timeout-seconds",
        default=30,
        show_default=True,
        type=int,
        help="SSH scan timeout for large remote libraries.",
    )
    @click.pass_context
    def remote_library_scan_cmd(
        ctx: click.Context,
        host: str | None,
        library_root: str,
        query: str,
        out_path: Path,
        limit: int,
        max_files: int,
        timeout_seconds: int,
    ) -> None:
        snapshot_path = _call_offload(
            offload.scan_remote_library,
            host=host,
            library_root=library_root,
            query=query,
            out_path=out_path,
            limit=limit,
            max_files=max_files,
            timeout_seconds=timeout_seconds,
        )
        payload = json.loads(snapshot_path.read_text())
        _emit(
            ctx,
            {"path": str(snapshot_path), **payload},
            f"remote library snapshot: {payload['matched_file_count']} matched file(s)",
        )

    @offload_group.command("upload")
    @click.argument("task", type=click.Path(path_type=Path))
    @click.option(
        "--host",
        envvar="RH_OFFLOAD_HOST",
        help="SSH host alias. Required unless --local-copy is used.",
    )
    @click.option(
        "--remote-root",
        default=str(offload.DEFAULT_REMOTE_ROOT),
        envvar="RH_OFFLOAD_REMOTE_ROOT",
        show_default=True,
        help="Remote offload root. Can also be set with RH_OFFLOAD_REMOTE_ROOT.",
    )
    @click.option(
        "--local-copy",
        is_flag=True,
        default=False,
        hidden=True,
        help="Use a local fake remote instead of rsync.",
    )
    @click.pass_context
    def upload_cmd(
        ctx: click.Context,
        task: Path,
        host: str | None,
        remote_root: str,
        local_copy: bool,
    ) -> None:
        payload = _call_offload(
            offload.upload_task,
            task,
            remote_root=remote_root,
            host=host,
            execute=not local_copy,
        )
        _emit(
            ctx, payload, f"uploaded {payload['task_id']} to {payload['remote_path']}"
        )

    @offload_group.command("command")
    @click.argument("task_id")
    @click.option(
        "--host",
        envvar="RH_OFFLOAD_HOST",
        help="SSH host alias. Can also be set with RH_OFFLOAD_HOST.",
    )
    @click.option(
        "--remote-root",
        default=str(offload.DEFAULT_REMOTE_ROOT),
        envvar="RH_OFFLOAD_REMOTE_ROOT",
        show_default=True,
        help="Remote offload root. Can also be set with RH_OFFLOAD_REMOTE_ROOT.",
    )
    def command_cmd(task_id: str, host: str | None, remote_root: str) -> None:
        command = _call_offload(
            offload.build_runner_command,
            task_id,
            host=host,
            remote_root=remote_root,
        )
        click.echo(command)

    @offload_group.command("fetch")
    @click.argument("task_id")
    @click.option(
        "--host",
        envvar="RH_OFFLOAD_HOST",
        help="SSH host alias. Required unless --local-copy is used.",
    )
    @click.option(
        "--remote-root",
        default=str(offload.DEFAULT_REMOTE_ROOT),
        envvar="RH_OFFLOAD_REMOTE_ROOT",
        show_default=True,
        help="Remote offload root. Can also be set with RH_OFFLOAD_REMOTE_ROOT.",
    )
    @click.option(
        "--local-root",
        default=str(offload.DEFAULT_LOCAL_ROOT),
        show_default=True,
        help="Local result root.",
    )
    @click.option(
        "--local-copy",
        is_flag=True,
        default=False,
        hidden=True,
        help="Use a local fake remote instead of rsync.",
    )
    @click.pass_context
    def fetch_cmd(
        ctx: click.Context,
        task_id: str,
        host: str | None,
        remote_root: str,
        local_root: str,
        local_copy: bool,
    ) -> None:
        payload = _call_offload(
            offload.fetch_task,
            task_id,
            local_root=local_root,
            remote_root=remote_root,
            host=host,
            execute=not local_copy,
        )
        _emit(ctx, payload, f"fetched {task_id} to {payload['local_path']}")

    @offload_group.command("remote-status")
    @click.option(
        "--host",
        envvar="RH_OFFLOAD_HOST",
        help="SSH host alias. Required unless --local is used.",
    )
    @click.option(
        "--remote-root",
        default=str(offload.DEFAULT_REMOTE_ROOT),
        envvar="RH_OFFLOAD_REMOTE_ROOT",
        show_default=True,
        help="Remote offload root. Can also be set with RH_OFFLOAD_REMOTE_ROOT.",
    )
    @click.option(
        "--local",
        is_flag=True,
        default=False,
        hidden=True,
        help="Inspect a local fake remote instead of SSH.",
    )
    @click.pass_context
    def remote_status_cmd(
        ctx: click.Context,
        host: str | None,
        remote_root: str,
        local: bool,
    ) -> None:
        payload = _call_offload(
            offload.remote_status,
            remote_root=remote_root,
            host=host,
            execute=not local,
        )
        _emit(ctx, payload, f"remote status: {payload['total_size_bytes']} bytes")

    @offload_group.command("remote-cleanup")
    @click.option(
        "--host",
        envvar="RH_OFFLOAD_HOST",
        help="SSH host alias. Required unless --local is used.",
    )
    @click.option(
        "--remote-root",
        default=str(offload.DEFAULT_REMOTE_ROOT),
        envvar="RH_OFFLOAD_REMOTE_ROOT",
        show_default=True,
        help="Remote offload root. Can also be set with RH_OFFLOAD_REMOTE_ROOT.",
    )
    @click.option(
        "--task-id",
        "task_ids",
        multiple=True,
        help="Task id to clean from selected sections. May be repeated.",
    )
    @click.option(
        "--section",
        "sections",
        multiple=True,
        type=click.Choice(["incoming", "runs", "results", "cache"]),
        help="Remote section to inspect. Defaults to incoming/runs/results.",
    )
    @click.option(
        "--older-than-days",
        type=int,
        default=None,
        help="Only include entries at least this many days old.",
    )
    @click.option(
        "--execute",
        is_flag=True,
        default=False,
        help="Actually delete candidates. Omit for dry-run.",
    )
    @click.option(
        "--local",
        is_flag=True,
        default=False,
        hidden=True,
        help="Clean a local fake remote instead of SSH.",
    )
    @click.pass_context
    def remote_cleanup_cmd(
        ctx: click.Context,
        host: str | None,
        remote_root: str,
        task_ids: tuple[str, ...],
        sections: tuple[str, ...],
        older_than_days: int | None,
        execute: bool,
        local: bool,
    ) -> None:
        payload = _call_offload(
            offload.remote_cleanup,
            remote_root=remote_root,
            host=host,
            task_ids=task_ids,
            sections=sections or None,
            older_than_days=older_than_days,
            dry_run=not execute,
            execute=not local,
        )
        action = "deleted" if execute else "would delete"
        _emit(ctx, payload, f"{action} {payload['candidate_count']} remote item(s)")

    @offload_group.command("run-local", hidden=True)
    @click.argument("task_id")
    @click.option(
        "--remote-root",
        default=str(offload.DEFAULT_REMOTE_ROOT),
        envvar="RH_OFFLOAD_REMOTE_ROOT",
        show_default=True,
        help="Local fake remote root. Can also be set with RH_OFFLOAD_REMOTE_ROOT.",
    )
    @click.pass_context
    def run_local_cmd(ctx: click.Context, task_id: str, remote_root: str) -> None:
        payload = _call_offload(
            offload.run_local_task,
            task_id,
            remote_root=remote_root,
        )
        _emit(ctx, payload, f"ran {task_id}: {payload['status']}")

    @offload_group.command("import")
    @click.argument("result", type=click.Path(path_type=Path))
    @click.option("--topic", required=True, help="Topic id or name.")
    @click.pass_context
    def import_cmd(ctx: click.Context, result: Path, topic: str) -> None:
        runtime_config = get_runtime_config(ctx)
        payload = _call_offload(
            offload.import_task_result,
            result,
            db_path=runtime_config.db_path,
            topic=topic,
        )
        _emit(
            ctx,
            payload,
            f"recorded {payload['artifact_type']} artifact {payload['artifact_id']}",
        )

    @offload_group.command("status")
    @click.argument("target")
    @click.option(
        "--local-root",
        default=str(offload.DEFAULT_LOCAL_ROOT),
        show_default=True,
        help="Local result root for task-id lookup.",
    )
    @click.pass_context
    def status_cmd(ctx: click.Context, target: str, local_root: str) -> None:
        payload = _call_offload(offload.status_payload, target, local_root=local_root)
        _emit(ctx, payload, f"{payload['task_id']}: {payload['status']}")

    @offload_group.command("batch-plan")
    @click.argument("items", nargs=-1, required=True, type=click.Path(path_type=Path))
    @click.option(
        "--out",
        "out_path",
        required=True,
        type=click.Path(path_type=Path),
        help="Local batch plan JSON path.",
    )
    @click.option(
        "--host",
        envvar="RH_OFFLOAD_HOST",
        help="SSH host alias. Can also be set with RH_OFFLOAD_HOST.",
    )
    @click.option(
        "--remote-root",
        default=str(offload.DEFAULT_REMOTE_ROOT),
        envvar="RH_OFFLOAD_REMOTE_ROOT",
        show_default=True,
        help="Remote offload root. Can also be set with RH_OFFLOAD_REMOTE_ROOT.",
    )
    @click.option(
        "--concurrency",
        default=1,
        show_default=True,
        type=int,
        help="Maximum number of tasks to run at once.",
    )
    @click.pass_context
    def batch_plan_cmd(
        ctx: click.Context,
        items: tuple[Path, ...],
        out_path: Path,
        host: str | None,
        remote_root: str,
        concurrency: int,
    ) -> None:
        plan_path = _call_offload(
            offload.create_batch_plan,
            items,
            out_path=out_path,
            host=host,
            remote_root=remote_root,
            concurrency=concurrency,
        )
        plan = json.loads(plan_path.read_text())
        payload = {
            "path": str(plan_path),
            "item_count": len(plan["items"]),
            "concurrency": plan["concurrency"],
            "remote_root": plan["remote_root"],
        }
        _emit(ctx, payload, f"planned {payload['item_count']} offload item(s)")

    @offload_group.command("batch-status")
    @click.argument("plan", type=click.Path(path_type=Path))
    @click.pass_context
    def batch_status_cmd(ctx: click.Context, plan: Path) -> None:
        payload = _call_offload(offload.status_batch_plan, plan)
        _emit(ctx, payload, f"{payload['total']} offload item(s) in batch")

    @offload_group.command("batch-reconcile")
    @click.argument("plan", type=click.Path(path_type=Path))
    @click.pass_context
    def batch_reconcile_cmd(ctx: click.Context, plan: Path) -> None:
        payload = _call_offload(offload.reconcile_batch_plan, plan)
        _emit(
            ctx,
            payload,
            (f"{payload['total']} offload item(s), {payload['drift_count']} drifted"),
        )

    @offload_group.command("queue-create")
    @click.argument("items", nargs=-1, type=click.Path(path_type=Path), required=True)
    @click.option(
        "--out",
        "out_path",
        required=True,
        type=click.Path(path_type=Path),
        help="Local offload queue JSON path.",
    )
    @click.option(
        "--host",
        envvar="RH_OFFLOAD_HOST",
        help="SSH host alias. Can also be set with RH_OFFLOAD_HOST.",
    )
    @click.option(
        "--remote-root",
        default=str(offload.DEFAULT_REMOTE_ROOT),
        envvar="RH_OFFLOAD_REMOTE_ROOT",
        show_default=True,
        help="Remote offload root. Can also be set with RH_OFFLOAD_REMOTE_ROOT.",
    )
    @click.option(
        "--local-root",
        default=str(offload.DEFAULT_LOCAL_ROOT),
        show_default=True,
        help="Local result root for queue fetch steps.",
    )
    @click.pass_context
    def queue_create_cmd(
        ctx: click.Context,
        items: tuple[Path, ...],
        out_path: Path,
        host: str | None,
        remote_root: str,
        local_root: str,
    ) -> None:
        queue_path = _call_offload(
            offload.create_offload_queue,
            items,
            out_path=out_path,
            host=host,
            remote_root=remote_root,
            local_root=local_root,
        )
        queue = json.loads(queue_path.read_text())
        payload = {
            "path": str(queue_path),
            "item_count": len(queue["items"]),
            "remote_root": queue["remote_root"],
            "local_root": queue["local_root"],
        }
        _emit(ctx, payload, f"queued {payload['item_count']} offload item(s)")

    @offload_group.command("queue-status")
    @click.argument("queue", type=click.Path(path_type=Path))
    @click.pass_context
    def queue_status_cmd(ctx: click.Context, queue: Path) -> None:
        payload = _call_offload(offload.status_offload_queue, queue)
        _emit(ctx, payload, f"{payload['total']} offload queue item(s)")

    @offload_group.command("queue-step")
    @click.argument("queue", type=click.Path(path_type=Path))
    @click.option(
        "--local-copy",
        is_flag=True,
        default=False,
        hidden=True,
        help="Use a local fake remote instead of rsync.",
    )
    @click.pass_context
    def queue_step_cmd(
        ctx: click.Context,
        queue: Path,
        local_copy: bool,
    ) -> None:
        payload = _call_offload(
            offload.run_offload_queue_once,
            queue,
            local_copy=local_copy,
        )
        action = payload.get("action") or "idle"
        _emit(ctx, payload, f"queue step {action}: {payload['status']}")

    @offload_group.command("batch-preflight")
    @click.argument("plan", type=click.Path(path_type=Path))
    @click.option(
        "--capabilities",
        type=click.Path(path_type=Path),
        help="Local worker capabilities JSON file. This is not fetched remotely.",
    )
    @click.pass_context
    def batch_preflight_cmd(
        ctx: click.Context,
        plan: Path,
        capabilities: Path | None,
    ) -> None:
        capability_payload = None
        if capabilities is not None:
            capability_payload = _read_local_json(capabilities)
        payload = _call_offload(
            offload.preflight_batch_plan,
            plan,
            capabilities=capability_payload,
        )
        _emit(
            ctx,
            payload,
            f"{payload['allowed_count']} allowed, {payload['blocked_count']} blocked",
        )


def _call_offload(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except offload.OffloadError as exc:
        raise click.ClickException(str(exc)) from exc


def _read_local_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except OSError as exc:
        raise click.ClickException(f"cannot read capabilities file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"invalid capabilities JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise click.ClickException(f"capabilities JSON must be an object: {path}")
    return payload


def _emit(ctx: click.Context, payload: dict[str, Any], text: str) -> None:
    if ctx.obj.get("json"):
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    click.echo(text)
