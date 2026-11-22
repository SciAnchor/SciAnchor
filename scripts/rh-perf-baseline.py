#!/usr/bin/env python3
"""Private RH performance baseline runner.

This script records local timing evidence for LG8 performance governance. It is
not a benchmark scorer and does not make public performance claims.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SLICE_ID = "K172_LG8_PRIVATE_PERFORMANCE_BASELINE"
REPORT_ID = "rh-private-performance-baseline"
CLAIM_POLICY = "no_benchmark_or_public_performance_claim"

RUNTIME_EVENT_APPEND_SNIPPET = r"""
import os
from pathlib import Path

from research_harness._core.storage.db import Database
from research_harness.runtime.event_normalizer import RuntimeEventRecord
from research_harness.runtime.event_store import _append_runtime_event

db = Database(Path(os.environ["RH_PERF_TMP_DB"]))
iteration = os.environ.get("RH_PERF_ITERATION", "0")
run_id = os.environ.get("RH_PERF_RUN_ID", "run")
record = RuntimeEventRecord(
    event_id=f"rh_perf_baseline:{run_id}:{iteration}:{os.getpid()}",
    trace_id="rh-perf-baseline",
    event_type="perf.baseline.sample",
    created_at="2026-06-11T00:00:00Z",
    origin_surface="private-selfdev",
    actor="codex",
    job_id="K172_LG8_PRIVATE_PERFORMANCE_BASELINE",
    tool_name="rh-perf-baseline",
    payload={"iteration": iteration, "scope": "private"},
)
result = _append_runtime_event(db, record, metadata={"runner": "rh-perf-baseline"})
print(result.status)
raise SystemExit(0 if result.ok else 1)
""".strip()


Runner = Callable[..., subprocess.CompletedProcess[str]]
Timer = Callable[[], float]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _pythonpath(repo_root: Path, existing: str | None) -> str:
    entries = [
        str(repo_root / "packages/research_harness"),
        str(repo_root / "packages/research_harness_mcp"),
    ]
    if existing:
        entries.append(existing)
    return os.pathsep.join(entries)


def _base_env(repo_root: Path, temp_db_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = _pythonpath(repo_root, env.get("PYTHONPATH"))
    env["RESEARCH_HARNESS_DB_PATH"] = str(temp_db_path)
    env["RH_PERF_TMP_DB"] = str(temp_db_path)
    env["RESEARCH_HARNESS_DISABLE_WORKSPACE_MATERIALIZATION"] = "1"
    return env


def _measurement_specs(
    repo_root: Path,
    python_executable: str,
    *,
    ignored_active_slice_ids: Sequence[str] = (),
) -> list[dict[str, Any]]:
    selfdev_script = repo_root / "scripts/rh-selfdev.py"
    next_action_argv = [
        python_executable,
        str(selfdev_script),
        "next-action",
        "--json",
    ]
    for slice_id in ignored_active_slice_ids:
        next_action_argv.extend(["--ignore-active-slice", slice_id])
    return [
        {
            "id": "cold_start_import",
            "category": "cold_start",
            "description": "Import the core research_harness package in a fresh process.",
            "argv": [
                python_executable,
                "-c",
                "import research_harness; print('ok')",
            ],
            "shell": False,
        },
        {
            "id": "runtime_config_read",
            "category": "read_path",
            "description": "Resolve runtime config without materializing workspace state.",
            "argv": [
                python_executable,
                "-c",
                (
                    "from research_harness._core.config import load_runtime_config; "
                    "print(load_runtime_config().source)"
                ),
            ],
            "shell": False,
        },
        {
            "id": "runtime_event_append_tempdb",
            "category": "runtime_event",
            "description": "Append one private runtime event to an isolated temp DB.",
            "argv": [python_executable, "-c", RUNTIME_EVENT_APPEND_SNIPPET],
            "shell": False,
        },
        {
            "id": "selfdev_next_action_recovery",
            "category": "job_resume",
            "description": "Recover the self-dev next action from durable slice state.",
            "argv": next_action_argv,
            "shell": False,
        },
        {
            "id": "selfdev_verification_matrix",
            "category": "verification_matrix",
            "description": "Render the private self-dev verification matrix JSON.",
            "argv": [
                python_executable,
                str(selfdev_script),
                "verification-matrix",
                "--json",
            ],
            "shell": False,
        },
    ]


def _redacted_arg(arg: str, *, repo_root: Path, python_executable: str) -> str:
    if arg == python_executable:
        return Path(arg).name if Path(arg).is_absolute() else arg
    path = Path(arg)
    if path.is_absolute():
        try:
            return str(path.relative_to(repo_root))
        except ValueError:
            return path.name
    return arg


def _redacted_measurements(
    measurements: Sequence[Mapping[str, Any]],
    *,
    repo_root: Path,
    python_executable: str,
) -> list[dict[str, Any]]:
    return [
        {
            **dict(measurement),
            "argv": [
                _redacted_arg(
                    str(arg),
                    repo_root=repo_root,
                    python_executable=python_executable,
                )
                for arg in measurement["argv"]
            ],
        }
        for measurement in measurements
    ]


def build_baseline_plan(
    *,
    repo_root: Path = REPO_ROOT,
    python_executable: str = sys.executable,
    temp_db_path: Path,
    ignored_active_slice_ids: Sequence[str] = (),
) -> dict[str, Any]:
    measurements = _measurement_specs(
        repo_root,
        python_executable,
        ignored_active_slice_ids=ignored_active_slice_ids,
    )
    return {
        "report_id": REPORT_ID,
        "slice_id": SLICE_ID,
        "private_scope": True,
        "claim_policy": CLAIM_POLICY,
        "risk_boundary": (
            "Private local timing evidence only; no public performance claim, "
            "benchmark promotion claim, public surface change, dependency "
            "change, storage/provenance/orchestrator semantic change, external "
            "action, Zotero, HTTP, MCP, RH/ARE, commit, push, PR, release, or "
            "publishing action."
        ),
        "environment_isolation": {
            "temp_db": "RESEARCH_HARNESS_DB_PATH",
            "workspace_materialization": "disabled",
            "private_outputs": ".rh-selfdev/rh-performance-baseline-*",
        },
        "measurements": _redacted_measurements(
            measurements,
            repo_root=repo_root,
            python_executable=python_executable,
        ),
        "temp_db_path_recorded": False,
        "temp_db_path_hint": temp_db_path.name,
    }


def _prepare_temp_db(temp_db_path: Path) -> None:
    from research_harness._core.storage.db import Database

    db = Database(temp_db_path)
    db.migrate()


def _duration_ms(start: float, end: float) -> float:
    return round((end - start) * 1000, 3)


def _percentile(values: Sequence[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil((percentile / 100) * len(ordered)) - 1))
    return ordered[index]


def _summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [float(run["duration_ms"]) for run in runs]
    ok_count = sum(1 for run in runs if run["returncode"] == 0 and not run["timed_out"])
    timed_out_count = sum(1 for run in runs if run["timed_out"])
    return {
        "count": len(runs),
        "ok_count": ok_count,
        "failure_count": len(runs) - ok_count,
        "timed_out_count": timed_out_count,
        "min_ms": min(durations) if durations else 0.0,
        "p50_ms": _percentile(durations, 50),
        "p95_ms": _percentile(durations, 95),
        "max_ms": max(durations) if durations else 0.0,
    }


def _run_once(
    *,
    measurement: Mapping[str, Any],
    iteration: int,
    repo_root: Path,
    env: Mapping[str, str],
    runner: Runner,
    timer: Timer,
    timeout: int,
    run_id: str,
) -> dict[str, Any]:
    command_env = dict(env)
    command_env["RH_PERF_ITERATION"] = str(iteration)
    command_env["RH_PERF_RUN_ID"] = run_id
    start = timer()
    try:
        result = runner(
            list(measurement["argv"]),
            cwd=repo_root,
            env=command_env,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
        end = timer()
        return {
            "iteration": iteration,
            "duration_ms": _duration_ms(start, end),
            "returncode": result.returncode,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        end = timer()
        return {
            "iteration": iteration,
            "duration_ms": _duration_ms(start, end),
            "returncode": None,
            "timed_out": True,
        }


def _render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# RH Private Performance Baseline",
        "",
        f"Created: {report['created_at']}",
        f"Slice: `{report['slice_id']}`",
        "",
        "Private baseline only. No benchmark promotion claim or public performance claim is made.",
        "",
        "## Scope",
        "",
        str(report["risk_boundary"]),
        "",
        "## Measurements",
        "",
        "| ID | Category | p50 ms | p95 ms | ok/total |",
        "|---|---|---:|---:|---:|",
    ]
    for measurement in report["measurements"]:
        summary = measurement["summary"]
        lines.append(
            "| {id} | {category} | {p50} | {p95} | {ok}/{total} |".format(
                id=measurement["id"],
                category=measurement["category"],
                p50=summary["p50_ms"],
                p95=summary["p95_ms"],
                ok=summary["ok_count"],
                total=summary["count"],
            )
        )
    lines.extend(
        [
            "",
            "## Rerun",
            "",
            (
                "`python3 scripts/rh-perf-baseline.py --iterations "
                f"{report['iterations']} --output-dir .rh-selfdev --json`"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_baseline(
    *,
    iterations: int = 3,
    output_dir: Path = REPO_ROOT / ".rh-selfdev",
    timestamp: str | None = None,
    runner: Runner = subprocess.run,
    timer: Timer = perf_counter,
    timeout: int = 60,
    repo_root: Path = REPO_ROOT,
    python_executable: str = sys.executable,
    ignored_active_slice_ids: Sequence[str] = (),
) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    created_at = timestamp or _timestamp()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="rh-perf-baseline-") as temp_dir_name:
        temp_db_path = Path(temp_dir_name) / "pool.db"
        _prepare_temp_db(temp_db_path)
        plan = build_baseline_plan(
            repo_root=repo_root,
            python_executable=python_executable,
            temp_db_path=temp_db_path,
            ignored_active_slice_ids=ignored_active_slice_ids,
        )
        command_measurements = _measurement_specs(
            repo_root,
            python_executable,
            ignored_active_slice_ids=ignored_active_slice_ids,
        )
        env = _base_env(repo_root, temp_db_path)
        measurements: list[dict[str, Any]] = []
        for measurement in command_measurements:
            runs = [
                _run_once(
                    measurement=measurement,
                    iteration=iteration,
                    repo_root=repo_root,
                    env=env,
                    runner=runner,
                    timer=timer,
                    timeout=timeout,
                    run_id=created_at,
                )
                for iteration in range(1, iterations + 1)
            ]
            measurements.append(
                {
                    "id": measurement["id"],
                    "category": measurement["category"],
                    "description": measurement["description"],
                    "argv": _redacted_measurements(
                        [measurement],
                        repo_root=repo_root,
                        python_executable=python_executable,
                    )[0]["argv"],
                    "shell": False,
                    "runs": runs,
                    "summary": _summary(runs),
                }
            )

    report = {
        "report_id": REPORT_ID,
        "slice_id": SLICE_ID,
        "created_at": created_at,
        "iterations": iterations,
        "private_scope": True,
        "claim_policy": CLAIM_POLICY,
        "risk_boundary": plan["risk_boundary"],
        "environment_isolation": plan["environment_isolation"],
        "measurements": measurements,
    }
    report["overall_status"] = (
        "ok"
        if all(
            measurement["summary"]["failure_count"] == 0
            for measurement in report["measurements"]
        )
        else "failed_measurements"
    )

    json_path = output_dir / f"rh-performance-baseline-{created_at}.json"
    markdown_path = output_dir / f"rh-performance-baseline-{created_at}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")

    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "report": report,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / ".rh-selfdev")
    parser.add_argument("--timestamp")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--ignore-active-slice", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_baseline(
            iterations=args.iterations,
            output_dir=args.output_dir,
            timestamp=args.timestamp,
            timeout=args.timeout,
            ignored_active_slice_ids=tuple(args.ignore_active_slice),
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result["report"], indent=2, sort_keys=True))
    else:
        print(result["json_path"])
        print(result["markdown_path"])
    return 0 if result["report"]["overall_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
