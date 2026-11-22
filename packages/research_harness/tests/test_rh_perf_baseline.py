from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "scripts").exists() and (p / "AGENTS.md").exists()
)


def load_perf_module():
    script_path = REPO_ROOT / "scripts" / "rh-perf-baseline.py"
    spec = importlib.util.spec_from_file_location("rh_perf_baseline", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_plan_covers_private_lg8_measurements() -> None:
    module = load_perf_module()

    plan = module.build_baseline_plan(
        repo_root=REPO_ROOT,
        python_executable="python3",
        temp_db_path=Path("/tmp/rh-perf-baseline.db"),
    )

    categories = {measurement["category"] for measurement in plan["measurements"]}
    assert {
        "cold_start",
        "read_path",
        "runtime_event",
        "job_resume",
        "verification_matrix",
    } <= categories
    assert plan["private_scope"] is True
    assert plan["claim_policy"] == "no_benchmark_or_public_performance_claim"
    assert "public" in plan["risk_boundary"]

    for measurement in plan["measurements"]:
        assert isinstance(measurement["argv"], list)
        assert all(isinstance(arg, str) for arg in measurement["argv"])
        assert measurement["shell"] is False


def test_plan_can_measure_next_action_recovery_while_ignoring_active_slice() -> None:
    module = load_perf_module()

    plan = module.build_baseline_plan(
        repo_root=REPO_ROOT,
        python_executable="python3",
        temp_db_path=Path("/tmp/rh-perf-baseline.db"),
        ignored_active_slice_ids=("K174_LG8_SELFDEV_NEXT_ACTION_RECOVERY_HOT_PATH",),
    )

    next_action = next(
        measurement
        for measurement in plan["measurements"]
        if measurement["id"] == "selfdev_next_action_recovery"
    )

    assert next_action["argv"] == [
        "python3",
        "scripts/rh-selfdev.py",
        "next-action",
        "--json",
        "--ignore-active-slice",
        "K174_LG8_SELFDEV_NEXT_ACTION_RECOVERY_HOT_PATH",
    ]


def test_runtime_event_append_measurement_uses_prepared_temp_db() -> None:
    module = load_perf_module()

    plan = module.build_baseline_plan(
        repo_root=REPO_ROOT,
        python_executable="python3",
        temp_db_path=Path("/tmp/rh-perf-baseline.db"),
    )
    runtime_event = next(
        measurement
        for measurement in plan["measurements"]
        if measurement["id"] == "runtime_event_append_tempdb"
    )

    assert "db.migrate()" not in "\n".join(runtime_event["argv"])


def test_run_baseline_writes_private_json_and_markdown(tmp_path: Path) -> None:
    module = load_perf_module()
    calls: list[dict[str, Any]] = []
    current_time = 0.0

    def fake_timer() -> float:
        nonlocal current_time
        value = current_time
        current_time += 0.01
        return value

    def fake_runner(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "env": dict(env),
                "timeout": timeout,
                "capture_output": capture_output,
                "text": text,
                "check": check,
            }
        )
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    result = module.run_baseline(
        iterations=2,
        output_dir=tmp_path,
        timestamp="20260611T010203Z",
        runner=fake_runner,
        timer=fake_timer,
    )

    json_path = tmp_path / "rh-performance-baseline-20260611T010203Z.json"
    markdown_path = tmp_path / "rh-performance-baseline-20260611T010203Z.md"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    json_text = json_path.read_text(encoding="utf-8")

    assert result["json_path"] == str(json_path)
    assert result["markdown_path"] == str(markdown_path)
    assert payload["slice_id"] == "K172_LG8_PRIVATE_PERFORMANCE_BASELINE"
    assert payload["private_scope"] is True
    assert payload["iterations"] == 2
    assert len(calls) == len(payload["measurements"]) * 2
    assert all(call["check"] is False for call in calls)
    assert all(call["env"]["RESEARCH_HARNESS_DB_PATH"] for call in calls)
    assert all(
        call["env"]["RESEARCH_HARNESS_DISABLE_WORKSPACE_MATERIALIZATION"] == "1"
        for call in calls
    )
    assert any("verification-matrix" in call["argv"] for call in calls)
    assert any("next-action" in call["argv"] for call in calls)
    assert str(REPO_ROOT) not in json_text
    assert all(
        measurement["summary"]["p50_ms"] == 10.0
        for measurement in payload["measurements"]
    )
    assert "Private baseline only" in markdown
    assert "No benchmark promotion claim" in markdown
