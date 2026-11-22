"""Doctor diagnostics command for the RH CLI."""

from __future__ import annotations

import json
import os
import platform
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from .config import detect_state_trees, find_workspace_root


def _build_state_trees_check(runtime_config: Any, db_path: Path) -> dict[str, object]:
    """Split-brain guard: warn when more than one live state tree is visible."""
    trees = detect_state_trees(runtime_config)
    nonempty = [tree for tree in trees if int(tree.get("pool_db_bytes") or 0) > 0]
    warnings: list[str] = []
    remediation: list[str] = []

    if len(nonempty) > 1:
        listing = ", ".join(
            f"{tree['path']} ({int(tree.get('pool_db_bytes') or 0) // 1024} KB)"
            for tree in nonempty
        )
        warnings.append(
            f"{len(nonempty)} state trees contain a non-empty pool.db: {listing}"
        )
        remediation.append(
            "quarantine stray databases (see docs/state-cleanup.md); keep exactly one"
        )
    if runtime_config.source == "global-default":
        warnings.append(
            "DB resolution fell through to ~/.research-harness — cwd is outside a "
            "Research Harness checkout (likely cwd drift)"
        )
        remediation.append(
            "cd into the checkout, or set RESEARCH_HARNESS_DB_PATH explicitly"
        )
    if (
        runtime_config.workspace_root is not None
        and runtime_config.source == "project-default"
    ):
        warnings.append(
            "project DB is unpinned (no .research-harness/config.json db_path)"
        )
        remediation.append("pin it: rh config init")
    env_db = os.environ.get("RESEARCH_HARNESS_DB_PATH") or os.environ.get(
        "RESEARCH_HUB_DB_PATH"
    )
    if env_db and runtime_config.config_path and runtime_config.config_path.exists():
        try:
            configured = json.loads(runtime_config.config_path.read_text()).get(
                "db_path"
            )
        except (OSError, ValueError):
            configured = None
        if configured:
            pinned = Path(str(configured))
            if not pinned.is_absolute() and runtime_config.workspace_root is not None:
                pinned = runtime_config.workspace_root / pinned
            if pinned.expanduser().resolve() != Path(env_db).expanduser().resolve():
                warnings.append(
                    "RESEARCH_HARNESS_DB_PATH overrides the pinned project config "
                    "and points at a different database"
                )
                remediation.append(
                    "unset RESEARCH_HARNESS_DB_PATH or align it with "
                    ".research-harness/config.json"
                )

    return {
        "check": "state_trees",
        "resolved_db": str(db_path),
        "resolved_source": runtime_config.source,
        "trees": trees,
        "warnings": warnings,
        "remediation": remediation,
        "ok": not warnings,
    }


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _count_records(conn: sqlite3.Connection, table_name: str) -> int:
    if not _table_exists(conn, table_name):
        return 0
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    return int(row["count"] if row is not None else 0)


def _build_llm_check() -> dict[str, object]:
    from llm_router.client import (
        llm_route_can_attempt,
        llm_route_transport,
        resolve_llm_config,
    )
    from llm_router.config import detect_available_provider_details

    config = resolve_llm_config()
    available = detect_available_provider_details()
    # ``ok`` must track real usability: a hardcoded True hid unusable routes and
    # left LLM-backed primitives to fail later without a diagnosis.
    probe_ready = bool(llm_route_can_attempt(config))
    check: dict[str, object] = {
        "check": "llm_config",
        "configured": bool(available),
        "selected_provider": config.provider,
        "selected_model": config.model or "(provider default)",
        "route_kind": llm_route_transport(config),
        "base_url": config.base_url or None,
        "available_providers": [item.provider for item in available],
        "available_routes": [
            {
                "provider": item.provider,
                "route_kind": item.route_kind,
                "source": item.source,
            }
            for item in available
        ],
        "probe_ready": probe_ready,
        "ok": probe_ready,
        "note": (
            "optional for non-LLM flows; required for deep read, claim extraction, "
            "annotation, and other model-backed primitives"
        ),
    }
    if not probe_ready:
        check["warnings"] = [
            f"no usable LLM route: provider '{config.provider}' cannot be probed"
            + ("" if available else " and no provider credentials were detected")
        ]
        check["remediation"] = [
            "set LLM_PROVIDER plus that provider's key/model "
            "(e.g. OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL)",
            "export the values — sourcing a plain KEY=value env file does not "
            "pass them to child processes",
        ]
    return check


def register(
    main: click.Group,
    *,
    get_runtime_config: Callable[[click.Context], Any],
    get_db: Callable[[click.Context], Any],
) -> None:
    """Register the doctor diagnostics command on the root CLI group."""

    @main.command()
    @click.option(
        "--runtime-diagnostics",
        is_flag=True,
        default=False,
        help="Include preview read-only runtime diagnostics.",
    )
    @click.option(
        "--productization-boundary",
        is_flag=True,
        default=False,
        help="Include opt-in LG10 productization boundary preview.",
    )
    @click.pass_context
    def doctor(
        ctx: click.Context,
        runtime_diagnostics: bool,
        productization_boundary: bool,
    ) -> None:
        from .primitives import list_primitives

        checks: list[dict[str, object]] = []
        checks.append(
            {"check": "python", "version": platform.python_version(), "ok": True}
        )
        checks.append(
            {"check": "sqlite3", "version": sqlite3.sqlite_version, "ok": True}
        )
        try:
            import paperindex  # type: ignore

            checks.append(
                {
                    "check": "paperindex",
                    "version": getattr(paperindex, "__version__", "unknown"),
                    "ok": True,
                }
            )
        except ImportError:
            checks.append(
                {
                    "check": "paperindex",
                    "version": "not installed",
                    "ok": True,
                    "note": "optional",
                }
            )
        runtime_config = get_runtime_config(ctx)
        checks.append(
            {
                "check": "config",
                "source": runtime_config.source,
                "workspace_root": str(runtime_config.workspace_root)
                if runtime_config.workspace_root
                else None,
                "config_path": str(runtime_config.config_path)
                if runtime_config.config_path
                else None,
                "execution_backend": runtime_config.execution_backend,
                "ok": True,
            }
        )
        db = get_db(ctx)
        db_size = db.db_path.stat().st_size if db.db_path.exists() else 0
        checks.append(
            {
                "check": "database",
                "path": str(db.db_path),
                "size_kb": db_size // 1024,
                "ok": True,
            }
        )
        checks.append(_build_state_trees_check(runtime_config, db.db_path))
        checks.append(_build_llm_check())
        checks.append(
            {
                "check": "execution_backend",
                "backend": runtime_config.execution_backend,
                "ok": True,
            }
        )
        checks.append(
            {
                "check": "primitives",
                "registered": len(list_primitives()),
                "ok": True,
            }
        )
        from .acquisition.spc_bridge import build_spc_provider_check

        checks.append(build_spc_provider_check())

        from .venue_facts import build_venue_facts_check

        checks.append(build_venue_facts_check())

        # Context drops cannot be reconstructed after a run, so whether the
        # recorder is armed has to be visible BEFORE one starts.
        from .runtime.context_telemetry import telemetry_status

        checks.append(telemetry_status())
        conn = db.connect()
        try:
            provenance_exists = _table_exists(conn, "provenance_records")
            checks.append(
                {
                    "check": "provenance",
                    "table_exists": provenance_exists,
                    "record_count": _count_records(conn, "provenance_records"),
                    "ok": provenance_exists,
                }
            )
        finally:
            conn.close()
        if runtime_diagnostics:
            from .runtime.doctor_diagnostics import (
                build_runtime_diagnostics_preview,
                redact_runtime_diagnostic_output,
            )

            repo_root = (
                runtime_config.workspace_root or find_workspace_root() or Path.cwd()
            )
            checks = redact_runtime_diagnostic_output(
                checks,
                repo_root,
            )
            checks.append(
                build_runtime_diagnostics_preview(
                    checks,
                    repo_root=repo_root,
                    artifact_path=runtime_config.db_path,
                )
            )
        if productization_boundary:
            from ._productization import build_lg10_productization_boundary_payload

            checks.append(
                {
                    "check": "productization_boundary",
                    "preview": True,
                    "ok": True,
                    "origin": "rh doctor --productization-boundary",
                    "note": "preview: gate-bound LG10 productization boundary",
                    "boundary": build_lg10_productization_boundary_payload(
                        scope="public-doctor-opt-in-preview"
                    ),
                }
            )
        if ctx.obj.get("json"):
            click.echo(json.dumps(checks, ensure_ascii=False, default=str))
            return
        for item in checks:
            detail = (
                item.get("version")
                or item.get("path")
                or item.get("resolved_db")
                or item.get("backend")
                or item.get("note")
                or ""
            )
            label = "OK" if item.get("ok", True) else "WARN"
            click.echo(f"[{label}] {item['check']}: {detail}")
            for warning in item.get("warnings") or []:
                click.echo(f"       - {warning}")
            for hint in item.get("remediation") or []:
                click.echo(f"       fix: {hint}")
