#!/usr/bin/env python3
"""Run or plan a resumable AutoResearchBench RH/Codex evaluation.

The filename is retained from the original smoke-test harness, but the script is
batch-safe: it writes a cumulative predictions file after every task so a long
AutoResearchBench run can be resumed without rerunning completed tasks.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from research_harness.eval.researchflowbench import (
    EXTERNAL_PREDICTIONS_SCHEMA_VERSION,
    run_external_task_pack_agent,
    run_external_task_pack_predictions,
    validate_external_task_pack,
    write_score_report,
)
from research_harness.eval.researchflowbench.baseline import (
    _build_autoresearchbench_candidate_source,
)


SCHEMA_VERSION = "researchflowbench.autoresearchbench_full_eval_run.v0.1"
RESUME_CONFIG_SCHEMA_VERSION = (
    "researchflowbench.autoresearchbench_resume_config.v0.1"
)
RUNNER_ID = "autoresearchbench_rh_codex_agent"


def build_full_eval_plan(
    *,
    task_pack_root: str | Path,
    candidate_source: str | Path | None,
    out_dir: str | Path,
    task_ids: tuple[str, ...] = (),
    limit: int | None = None,
    task_timeout_deep_sec: int = 900,
    task_timeout_wide_sec: int = 2400,
    max_agent_iterations: int = 1,
    max_retrieval_iterations: int = 1,
    reasoning_effort: str | None = "low",
    model: str | None = None,
    codex_bin: str = "codex",
) -> dict[str, Any]:
    """Return a machine-readable readiness and resume plan."""

    root = Path(task_pack_root)
    out = Path(out_dir)
    manifest = _load_json(root / "adapter_manifest.json")
    manifest_task_ids = tuple(
        str(task_id)
        for task_id in manifest.get("task_ids", [])
        if isinstance(task_id, str)
    )
    selected_task_ids = _selected_task_ids(
        manifest_task_ids,
        task_ids=task_ids,
        limit=limit,
    )
    task_records = tuple(_task_record(root, task_id) for task_id in selected_task_ids)
    task_type_counts = _task_type_counts(task_records)
    completed_task_ids = _completed_task_ids(
        _predictions_file(out),
        selected_task_ids=selected_task_ids,
    )
    completed_set = set(completed_task_ids)
    pending_task_ids = tuple(
        task_id for task_id in selected_task_ids if task_id not in completed_set
    )
    validation = validate_external_task_pack(root, allow_local_gold=True)
    missing_selected = sorted(set(task_ids) - set(manifest_task_ids))
    candidate_status = _candidate_source_status(candidate_source)
    resume_config = _resume_config(
        candidate_source=candidate_source,
        task_timeout_deep_sec=task_timeout_deep_sec,
        task_timeout_wide_sec=task_timeout_wide_sec,
        max_agent_iterations=max_agent_iterations,
        max_retrieval_iterations=max_retrieval_iterations,
        reasoning_effort=reasoning_effort,
        model=model,
        codex_bin=codex_bin,
    )
    resume_config_status = _resume_config_compatibility(
        _predictions_file(out),
        expected=resume_config,
    )
    gold_file_count = sum(1 for record in task_records if record["gold_exists"])
    blockers = _plan_blockers(
        benchmark_id=str(manifest.get("benchmark_id") or ""),
        validation_is_valid=validation.is_valid,
        validation_issue_count=len(validation.issues),
        missing_selected=missing_selected,
        candidate_status=candidate_status,
        resume_config_status=resume_config_status,
        gold_file_count=gold_file_count,
        selected_task_count=len(selected_task_ids),
    )
    ready = not blockers
    status = "ready" if ready else "blocked"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "ready_for_full_run": ready,
        "benchmark_id": str(manifest.get("benchmark_id") or ""),
        "adapter_contract": str(manifest.get("adapter_contract") or ""),
        "task_pack": str(root),
        "candidate_source": candidate_status,
        "output_dir": str(out),
        "output_files": {
            "predictions": str(_predictions_file(out)),
            "score_report": str(_score_file(out)),
            "run_manifest": str(_run_manifest_file(out)),
        },
        "task_count": len(selected_task_ids),
        "total_task_count": len(manifest_task_ids),
        "task_type_counts": task_type_counts,
        "gold_file_count": gold_file_count,
        "completed_task_count": len(completed_task_ids),
        "pending_task_count": len(pending_task_ids),
        "completed_task_ids": list(completed_task_ids),
        "pending_task_ids": list(pending_task_ids),
        "selected_task_ids": list(selected_task_ids),
        "timeout_policy": {
            "deep": task_timeout_deep_sec,
            "unknown": task_timeout_deep_sec,
            "wide": task_timeout_wide_sec,
        },
        "execution_limits": {
            "max_agent_iterations": max_agent_iterations,
            "max_retrieval_iterations": max_retrieval_iterations,
            "reasoning_effort": reasoning_effort or "",
            "model": model or "",
            "codex_bin": codex_bin,
        },
        "resume_config": resume_config_status,
        "validation": {
            "is_valid": validation.is_valid,
            "checked_task_count": validation.checked_task_count,
            "checked_file_count": validation.checked_file_count,
            "issue_count": len(validation.issues),
            "issues": [issue.to_dict() for issue in validation.issues[:10]],
        },
        "blockers": blockers,
    }


def run_full_eval(
    *,
    task_pack_root: str | Path,
    candidate_source: str | Path | None,
    out_dir: str | Path,
    task_ids: tuple[str, ...] = (),
    limit: int | None = None,
    fake_predictions_file: str | Path | None = None,
    task_timeout_deep_sec: int = 900,
    task_timeout_wide_sec: int = 2400,
    max_agent_iterations: int = 1,
    max_retrieval_iterations: int = 1,
    reasoning_effort: str | None = "low",
    model: str | None = None,
    codex_bin: str = "codex",
) -> dict[str, Any]:
    """Run pending tasks and write cumulative predictions plus a score report."""

    plan = build_full_eval_plan(
        task_pack_root=task_pack_root,
        candidate_source=candidate_source,
        out_dir=out_dir,
        task_ids=task_ids,
        limit=limit,
        task_timeout_deep_sec=task_timeout_deep_sec,
        task_timeout_wide_sec=task_timeout_wide_sec,
        max_agent_iterations=max_agent_iterations,
        max_retrieval_iterations=max_retrieval_iterations,
        reasoning_effort=reasoning_effort,
        model=model,
        codex_bin=codex_bin,
    )
    if plan["blockers"]:
        raise ValueError(
            "AutoResearchBench full-eval preflight blocked: "
            + ", ".join(plan["blockers"])
        )

    root = Path(task_pack_root)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cumulative_path = _predictions_file(out)
    cumulative = _load_or_create_prediction_payload(
        cumulative_path,
        root=root,
        adapter_contract=plan["adapter_contract"],
        max_agent_iterations=max_agent_iterations,
        max_retrieval_iterations=max_retrieval_iterations,
        candidate_source=candidate_source,
        reasoning_effort=reasoning_effort,
        resume_config=plan["resume_config"]["expected"],
        model_execution_performed=fake_predictions_file is None,
    )
    cumulative, backfilled_legacy_diagnostics = (
        _backfill_legacy_prediction_diagnostics(
            cumulative,
            root=root,
            selected_task_ids=tuple(plan["selected_task_ids"]),
            task_timeout_deep_sec=task_timeout_deep_sec,
            task_timeout_wide_sec=task_timeout_wide_sec,
            candidate_source=candidate_source,
        )
    )
    predictions_by_task = _prediction_map(cumulative)
    if backfilled_legacy_diagnostics:
        cumulative = _merged_prediction_payload(
            cumulative,
            new_payload=cumulative,
            selected_task_ids=tuple(plan["selected_task_ids"]),
            predictions_by_task=predictions_by_task,
            candidate_source=candidate_source,
            reasoning_effort=reasoning_effort,
            resume_config=plan["resume_config"]["expected"],
        )
        predictions_by_task = _prediction_map(cumulative)
        _write_json(cumulative_path, cumulative)

    for task_id in plan["pending_task_ids"]:
        task_type = _task_record(root, task_id)["task_type"]
        timeout = _task_timeout_sec(
            task_type,
            task_timeout_deep_sec=task_timeout_deep_sec,
            task_timeout_wide_sec=task_timeout_wide_sec,
        )
        single_path = _single_prediction_file(out, task_id)
        started_at = _utc_now_iso()
        started_monotonic = time.monotonic()
        single_payload = run_external_task_pack_agent(
            root,
            predictions_file=single_path,
            runner_id=RUNNER_ID,
            max_agent_iterations=max_agent_iterations,
            max_retrieval_iterations=max_retrieval_iterations,
            task_ids=(task_id,),
            candidate_source=candidate_source,
            fake_predictions_file=fake_predictions_file,
            codex_bin=codex_bin,
            model=model,
            task_timeout_sec=timeout,
            reasoning_effort=reasoning_effort,
        )
        elapsed_sec = time.monotonic() - started_monotonic
        finished_at = _utc_now_iso()
        for entry in single_payload.get("predictions", []):
            if isinstance(entry, dict):
                predictions_by_task[str(entry.get("task_id") or "")] = (
                    _with_task_diagnostics(
                        entry,
                        task_type=task_type,
                        timeout_sec=timeout,
                        started_at=started_at,
                        finished_at=finished_at,
                        elapsed_sec=elapsed_sec,
                        candidate_source=candidate_source,
                    )
                )
        cumulative = _merged_prediction_payload(
            cumulative,
            new_payload=single_payload,
            selected_task_ids=tuple(plan["selected_task_ids"]),
            predictions_by_task=predictions_by_task,
            candidate_source=candidate_source,
            reasoning_effort=reasoning_effort,
            resume_config=plan["resume_config"]["expected"],
        )
        _write_json(cumulative_path, cumulative)

    score_result = run_external_task_pack_predictions(
        root,
        cumulative_path,
        evidence_state="real_data",
        max_agent_iterations=max_agent_iterations,
        max_retrieval_iterations=max_retrieval_iterations,
        task_ids=tuple(plan["selected_task_ids"]),
    )
    write_score_report(score_result.report, _score_file(out))
    final_plan = build_full_eval_plan(
        task_pack_root=root,
        candidate_source=candidate_source,
        out_dir=out,
        task_ids=tuple(plan["selected_task_ids"]),
        task_timeout_deep_sec=task_timeout_deep_sec,
        task_timeout_wide_sec=task_timeout_wide_sec,
        max_agent_iterations=max_agent_iterations,
        max_retrieval_iterations=max_retrieval_iterations,
        reasoning_effort=reasoning_effort,
        model=model,
        codex_bin=codex_bin,
    )
    final_plan["score_report"] = {
        "score_count": len(score_result.report["scores"]),
        "blocked_score_count": score_result.report["metadata"]["blocked_score_count"],
        "metrics": score_result.report["metrics"],
    }
    final_plan["task_diagnostics"] = _task_diagnostics_summary(cumulative)
    final_plan["status"] = (
        "complete" if final_plan["pending_task_count"] == 0 else "in_progress"
    )
    _write_json(_run_manifest_file(out), final_plan)
    return final_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-pack", required=True, type=Path)
    parser.add_argument("--candidate-source", type=Path, default=None)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--fake-predictions", type=Path, default=None)
    parser.add_argument("--task-timeout-deep-sec", type=int, default=900)
    parser.add_argument("--task-timeout-wide-sec", type=int, default=2400)
    parser.add_argument("--max-agent-iterations", type=int, default=1)
    parser.add_argument("--max-retrieval-iterations", type=int, default=1)
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--model", default=None)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    kwargs = {
        "task_pack_root": args.task_pack,
        "candidate_source": args.candidate_source,
        "out_dir": args.out_dir,
        "task_ids": tuple(args.task_id),
        "limit": args.limit,
        "task_timeout_deep_sec": args.task_timeout_deep_sec,
        "task_timeout_wide_sec": args.task_timeout_wide_sec,
        "max_agent_iterations": args.max_agent_iterations,
        "max_retrieval_iterations": args.max_retrieval_iterations,
        "reasoning_effort": args.reasoning_effort,
        "model": args.model,
        "codex_bin": args.codex_bin,
    }
    payload = (
        build_full_eval_plan(**kwargs)
        if args.dry_run
        else run_full_eval(**kwargs, fake_predictions_file=args.fake_predictions)
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _selected_task_ids(
    manifest_task_ids: tuple[str, ...],
    *,
    task_ids: tuple[str, ...],
    limit: int | None,
) -> tuple[str, ...]:
    selected = tuple(task_ids) if task_ids else manifest_task_ids
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        selected = selected[:limit]
    return selected


def _task_record(root: Path, task_id: str) -> dict[str, Any]:
    input_path = root / "tasks" / task_id / "input.json"
    visible = _load_json(input_path)
    return {
        "task_id": task_id,
        "task_type": str(visible.get("task_type") or "unknown"),
        "gold_exists": (root / "tasks" / task_id / "gold.json").exists(),
    }


def _task_type_counts(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        task_type = str(record.get("task_type") or "unknown")
        counts[task_type] = counts.get(task_type, 0) + 1
    return dict(sorted(counts.items()))


def _candidate_source_status(candidate_source: str | Path | None) -> dict[str, Any]:
    if candidate_source is None:
        return {"status": "blocked", "path": "", "record_count": 0}
    root = Path(candidate_source)
    try:
        source = _build_autoresearchbench_candidate_source(root)
    except (OSError, ValueError) as exc:
        return {
            "status": "blocked",
            "path": str(root),
            "record_count": 0,
            "error": str(exc),
        }
    return {
        "status": "ready",
        "path": str(root),
        "record_count": len(source.records_by_id),
        "schema_version": str(source.manifest.get("schema_version") or ""),
        "records_file": str(source.manifest.get("records_file") or ""),
    }


def _plan_blockers(
    *,
    benchmark_id: str,
    validation_is_valid: bool,
    validation_issue_count: int,
    missing_selected: list[str],
    candidate_status: dict[str, Any],
    resume_config_status: dict[str, Any],
    gold_file_count: int,
    selected_task_count: int,
) -> list[str]:
    blockers: list[str] = []
    if benchmark_id != "autoresearchbench":
        blockers.append(f"unsupported_benchmark:{benchmark_id or 'missing'}")
    if not validation_is_valid:
        blockers.append(f"task_pack_validation_failed:{validation_issue_count}")
    if missing_selected:
        blockers.append("missing_selected_task_ids:" + ",".join(missing_selected))
    if candidate_status.get("status") != "ready":
        blockers.append("candidate_source_not_ready")
    if resume_config_status.get("status") == "blocked":
        mismatches = [
            str(item)
            for item in resume_config_status.get("mismatches", [])
            if str(item)
        ]
        blockers.append(
            "resume_config_incompatible:"
            + (",".join(mismatches) if mismatches else "unknown")
        )
    if selected_task_count == 0:
        blockers.append("no_tasks_selected")
    if gold_file_count != selected_task_count:
        blockers.append("local_judge_gold_incomplete")
    return blockers


def _load_or_create_prediction_payload(
    path: Path,
    *,
    root: Path,
    adapter_contract: str,
    max_agent_iterations: int,
    max_retrieval_iterations: int,
    candidate_source: str | Path | None,
    reasoning_effort: str | None,
    resume_config: dict[str, Any],
    model_execution_performed: bool,
) -> dict[str, Any]:
    if path.exists():
        payload = _load_json(path)
        if (
            str(payload.get("schema_version") or "")
            != EXTERNAL_PREDICTIONS_SCHEMA_VERSION
        ):
            raise ValueError(
                f"existing predictions file has unsupported schema: {path}"
            )
        _validate_resume_config(path, payload, expected=resume_config)
        return payload
    return {
        "schema_version": EXTERNAL_PREDICTIONS_SCHEMA_VERSION,
        "benchmark_id": "autoresearchbench",
        "adapter_contract": adapter_contract,
        "runner_id": RUNNER_ID,
        "model_execution_performed": model_execution_performed,
        "execution_limits": {
            "max_agent_iterations": max_agent_iterations,
            "max_retrieval_iterations": max_retrieval_iterations,
        },
        "predictions": [],
        "artifact_refs": [f"task_pack:{root}"],
        "metadata": {
            "runner": "researchflowbench.autoresearchbench_full_eval_runner.v0.1",
            "gold_blind_workspace": True,
            "resume_supported": True,
            "candidate_source": str(candidate_source or ""),
            "reasoning_effort": str(reasoning_effort or ""),
            "resume_config": resume_config,
            "task_count": 0,
        },
    }


def _merged_prediction_payload(
    existing: dict[str, Any],
    *,
    new_payload: dict[str, Any],
    selected_task_ids: tuple[str, ...],
    predictions_by_task: dict[str, dict[str, Any]],
    candidate_source: str | Path | None,
    reasoning_effort: str | None,
    resume_config: dict[str, Any],
) -> dict[str, Any]:
    ordered_predictions = [
        predictions_by_task[task_id]
        for task_id in selected_task_ids
        if task_id in predictions_by_task
    ]
    metadata = dict(existing.get("metadata") or {})
    metadata.update(
        {
            "runner": "researchflowbench.autoresearchbench_full_eval_runner.v0.1",
            "gold_blind_workspace": True,
            "resume_supported": True,
            "candidate_source": str(candidate_source or ""),
            "reasoning_effort": str(reasoning_effort or ""),
            "resume_config": resume_config,
            "task_count": len(ordered_predictions),
        }
    )
    return {
        **existing,
        "runner_id": str(
            new_payload.get("runner_id") or existing.get("runner_id") or RUNNER_ID
        ),
        "model_execution_performed": (
            existing.get("model_execution_performed") is True
            or new_payload.get("model_execution_performed") is True
        ),
        "predictions": ordered_predictions,
        "metadata": metadata,
    }


def _resume_config(
    *,
    candidate_source: str | Path | None,
    task_timeout_deep_sec: int,
    task_timeout_wide_sec: int,
    max_agent_iterations: int,
    max_retrieval_iterations: int,
    reasoning_effort: str | None,
    model: str | None,
    codex_bin: str,
) -> dict[str, Any]:
    return {
        "schema_version": RESUME_CONFIG_SCHEMA_VERSION,
        "candidate_source": str(candidate_source or ""),
        "timeout_policy": {
            "deep": task_timeout_deep_sec,
            "unknown": task_timeout_deep_sec,
            "wide": task_timeout_wide_sec,
        },
        "execution_limits": {
            "max_agent_iterations": max_agent_iterations,
            "max_retrieval_iterations": max_retrieval_iterations,
            "reasoning_effort": reasoning_effort or "",
            "model": model or "",
            "codex_bin": codex_bin,
        },
    }


def _resume_config_compatibility(
    predictions_file: Path,
    *,
    expected: dict[str, Any],
) -> dict[str, Any]:
    if not predictions_file.exists():
        return {
            "status": "not_applicable",
            "path": str(predictions_file),
            "expected": expected,
            "actual": {},
            "mismatches": [],
        }
    payload = _load_json(predictions_file)
    if str(payload.get("schema_version") or "") != EXTERNAL_PREDICTIONS_SCHEMA_VERSION:
        return {
            "status": "blocked",
            "path": str(predictions_file),
            "expected": expected,
            "actual": {},
            "mismatches": ["schema_version"],
        }
    actual = _payload_resume_config(payload)
    mismatches = _resume_config_mismatches(actual, expected)
    return {
        "status": "ready" if not mismatches else "blocked",
        "path": str(predictions_file),
        "expected": expected,
        "actual": actual if isinstance(actual, dict) else {},
        "mismatches": mismatches,
    }


def _validate_resume_config(
    path: Path,
    payload: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> None:
    actual = _payload_resume_config(payload)
    mismatches = _resume_config_mismatches(actual, expected)
    if mismatches:
        raise ValueError(
            f"existing predictions file has incompatible resume config: {path}; "
            f"mismatches={','.join(mismatches)}"
        )


def _payload_resume_config(payload: dict[str, Any]) -> dict[str, Any] | None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return None
    resume_config = metadata.get("resume_config")
    return resume_config if isinstance(resume_config, dict) else None


def _resume_config_mismatches(
    actual: dict[str, Any] | None,
    expected: dict[str, Any],
) -> list[str]:
    if actual is None:
        return ["missing_resume_config"]
    mismatches: list[str] = []
    for key in (
        "schema_version",
        "candidate_source",
        "execution_limits",
        "timeout_policy",
    ):
        if actual.get(key) != expected.get(key):
            mismatches.append(key)
    return mismatches


def _with_task_diagnostics(
    entry: dict[str, Any],
    *,
    task_type: str,
    timeout_sec: int,
    started_at: str,
    finished_at: str,
    elapsed_sec: float,
    candidate_source: str | Path | None,
) -> dict[str, Any]:
    enriched = dict(entry)
    runner_output = (
        dict(enriched.get("runner_output"))
        if isinstance(enriched.get("runner_output"), dict)
        else {}
    )
    trace = (
        dict(runner_output.get("retrieval_trace"))
        if isinstance(runner_output.get("retrieval_trace"), dict)
        else {}
    )
    rounded_elapsed = round(max(elapsed_sec, 0.0), 6)
    runner_output["task_diagnostics"] = {
        "schema_version": "researchflowbench.autoresearchbench_task_diagnostics.v0.1",
        "task_id": str(entry.get("task_id") or ""),
        "task_type": task_type,
        "timeout_sec": timeout_sec,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_sec": rounded_elapsed,
        "timeout_overrun_sec": round(max(0.0, rounded_elapsed - timeout_sec), 6),
        "status": _task_diagnostic_status(runner_output),
        "candidate_source_configured": candidate_source is not None,
        "candidate_source": str(candidate_source or ""),
        "candidate_source_trace_status": str(
            trace.get("trace_status") or "not_reported"
        ),
    }
    enriched["runner_output"] = runner_output
    return enriched


def _backfill_legacy_prediction_diagnostics(
    payload: dict[str, Any],
    *,
    root: Path,
    selected_task_ids: tuple[str, ...],
    task_timeout_deep_sec: int,
    task_timeout_wide_sec: int,
    candidate_source: str | Path | None,
) -> tuple[dict[str, Any], bool]:
    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        return payload, False

    selected = set(selected_task_ids)
    changed = False
    updated_predictions: list[Any] = []
    for entry in predictions:
        if not isinstance(entry, dict):
            updated_predictions.append(entry)
            continue
        task_id = str(entry.get("task_id") or "")
        if task_id not in selected:
            updated_predictions.append(entry)
            continue
        runner_output = entry.get("runner_output")
        if isinstance(runner_output, dict) and isinstance(
            runner_output.get("task_diagnostics"), dict
        ):
            updated_predictions.append(entry)
            continue

        task_type = _task_record(root, task_id)["task_type"]
        updated_predictions.append(
            _with_task_diagnostics(
                entry,
                task_type=task_type,
                timeout_sec=_task_timeout_sec(
                    task_type,
                    task_timeout_deep_sec=task_timeout_deep_sec,
                    task_timeout_wide_sec=task_timeout_wide_sec,
                ),
                started_at="",
                finished_at="",
                elapsed_sec=0.0,
                candidate_source=candidate_source,
            )
        )
        changed = True

    if not changed:
        return payload, False
    return {**payload, "predictions": updated_predictions}, True


def _task_timeout_sec(
    task_type: str,
    *,
    task_timeout_deep_sec: int,
    task_timeout_wide_sec: int,
) -> int:
    return task_timeout_wide_sec if task_type == "wide" else task_timeout_deep_sec


def _task_diagnostic_status(runner_output: dict[str, Any]) -> str:
    error = str(runner_output.get("error") or "")
    if error == "codex_exec_timeout":
        return "timeout"
    if error:
        return "error"
    return "completed"


def _task_diagnostics_summary(prediction_payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    for entry in prediction_payload.get("predictions", []):
        if not isinstance(entry, dict):
            continue
        runner_output = entry.get("runner_output")
        if not isinstance(runner_output, dict):
            continue
        diagnostic = runner_output.get("task_diagnostics")
        if isinstance(diagnostic, dict):
            diagnostics.append(diagnostic)

    status_counts: dict[str, int] = {}
    for diagnostic in diagnostics:
        status = str(diagnostic.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    elapsed_values = [
        float(diagnostic.get("elapsed_sec") or 0.0) for diagnostic in diagnostics
    ]
    return {
        "schema_version": "researchflowbench.autoresearchbench_task_diagnostics_summary.v0.1",
        "task_count": len(diagnostics),
        "status_counts": dict(sorted(status_counts.items())),
        "max_elapsed_sec": round(max(elapsed_values), 6) if elapsed_values else 0.0,
        "timeout_overrun_count": sum(
            1 for diagnostic in diagnostics if float(diagnostic.get("timeout_overrun_sec") or 0.0) > 0
        ),
        "candidate_source_missing_trace_count": sum(
            1
            for diagnostic in diagnostics
            if diagnostic.get("candidate_source_configured") is True
            and diagnostic.get("candidate_source_trace_status")
            in {"not_reported", "missing_candidate_source_trace"}
        ),
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _prediction_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        return {}
    return {
        str(entry.get("task_id") or ""): dict(entry)
        for entry in predictions
        if isinstance(entry, dict) and str(entry.get("task_id") or "")
    }


def _completed_task_ids(
    predictions_file: Path,
    *,
    selected_task_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if not predictions_file.exists():
        return ()
    payload = _load_json(predictions_file)
    prediction_ids = set(_prediction_map(payload))
    return tuple(task_id for task_id in selected_task_ids if task_id in prediction_ids)


def _predictions_file(out_dir: Path) -> Path:
    return out_dir / "predictions.json"


def _score_file(out_dir: Path) -> Path:
    return out_dir / "score_report.json"


def _run_manifest_file(out_dir: Path) -> Path:
    return out_dir / "run_manifest.json"


def _single_prediction_file(out_dir: Path, task_id: str) -> Path:
    return out_dir / "task_predictions" / f"{_safe_task_file_name(task_id)}.json"


def _safe_task_file_name(task_id: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_" for char in task_id
    )


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
