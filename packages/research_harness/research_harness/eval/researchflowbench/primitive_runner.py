"""ResearchFlowBench runner for real RH primitives."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from research_harness.primitives import get_primitive_impl
from research_harness.storage.db import Database

from .baseline import (
    EXTERNAL_PREDICTIONS_SCHEMA_VERSION,
    MAX_EXTERNAL_AGENT_ITERATIONS,
    BaselineRunResult,
    _build_autoresearchbench_candidate_source,
)
from .contract import SCORE_REPORT_SCHEMA_VERSION
from .litsearch_adapter import LitSearchAdapter, LitSearchTask
from .validators import validate_external_task_pack


PRIMITIVE_PAPER_SEARCH_LOCAL_BM25 = "paper_search_local_bm25"
PRIMITIVE_AUTORESEARCHBENCH_RH_CODEX_AGENT = "autoresearchbench_rh_codex_agent"
SUPPORTED_PRIMITIVE_RUNNERS = (PRIMITIVE_PAPER_SEARCH_LOCAL_BM25,)
SUPPORTED_AGENT_RUNNERS = (PRIMITIVE_AUTORESEARCHBENCH_RH_CODEX_AGENT, "fake_agent")


def run_external_task_pack_primitive(
    task_pack_root: str | Path,
    *,
    runner_id: str = PRIMITIVE_PAPER_SEARCH_LOCAL_BM25,
    allow_invalid: bool = False,
    evidence_state: str = "fixture_or_local_gold",
    data_root: str | Path | None = None,
) -> BaselineRunResult:
    """Score an adapter-generated external pack through real RH primitives."""

    if runner_id not in SUPPORTED_PRIMITIVE_RUNNERS:
        raise ValueError(f"unsupported external primitive runner: {runner_id}")

    root = Path(task_pack_root)
    validation = validate_external_task_pack(root, allow_local_gold=True)
    if not validation.is_valid and not allow_invalid:
        issue_codes = ", ".join(issue.code for issue in validation.issues[:5])
        raise ValueError(
            "external ResearchFlowBench task pack validation failed before scoring"
            + (f": {issue_codes}" if issue_codes else "")
        )

    manifest = _load_json(root / "adapter_manifest.json")
    benchmark_id = str(manifest.get("benchmark_id") or "")
    if benchmark_id != "litsearch":
        raise ValueError(f"{runner_id} is currently supported only for LitSearch")
    if data_root is None:
        raise ValueError(f"{runner_id} requires --data with a LitSearch export root")

    with tempfile.TemporaryDirectory(prefix="rh-rfb-primitive-") as tmpdir:
        db = _build_litsearch_local_db(Path(data_root), Path(tmpdir) / "pool.db")
        scores = tuple(
            _score_litsearch_task_with_paper_search(
                db,
                root,
                task_id,
                runner_id=runner_id,
                evidence_state=evidence_state,
            )
            for task_id in manifest.get("task_ids", [])
            if isinstance(task_id, str)
        )

    blocked_scores = tuple(
        score
        for score in scores
        if str(score.get("evidence_state") or "").startswith("blocked")
    )
    report = {
        "schema_version": SCORE_REPORT_SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "adapter_contract": str(manifest.get("adapter_contract") or ""),
        "split": _common_split(scores),
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "baseline_kind": "rh_primitive_replay",
        "scores": list(scores),
        "metrics": _aggregate_external_metrics(scores),
        "rh_axis_ids": list(
            dict.fromkeys(
                axis
                for score in scores
                for axis in score.get("rh_axis_ids", [])
                if isinstance(axis, str) and axis
            )
        ),
        "artifact_refs": [f"task_pack:{root}"],
        "model_execution_performed": False,
        "validation": {
            "is_valid": validation.is_valid,
            "checked_task_count": validation.checked_task_count,
            "checked_file_count": validation.checked_file_count,
            "issue_count": len(validation.issues),
        },
        "metadata": {
            "runner": "researchflowbench.external_rh_primitive_replay.v0.1",
            "task_count": len(scores),
            "blocked_score_count": len(blocked_scores),
            "data_root": str(data_root),
            "automatic_mutation_enabled": False,
        },
    }
    return BaselineRunResult(report=report, validation_report=validation)


def run_external_task_pack_agent(
    task_pack_root: str | Path,
    *,
    predictions_file: str | Path,
    runner_id: str = PRIMITIVE_AUTORESEARCHBENCH_RH_CODEX_AGENT,
    allow_invalid: bool = False,
    max_agent_iterations: int = MAX_EXTERNAL_AGENT_ITERATIONS,
    max_retrieval_iterations: int = MAX_EXTERNAL_AGENT_ITERATIONS,
    task_ids: tuple[str, ...] = (),
    candidate_source: str | Path | None = None,
    fake_predictions_file: str | Path | None = None,
    codex_bin: str = "codex",
    model: str | None = None,
    task_timeout_sec: int = 1800,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Run a gold-blind AutoResearchBench RH/Codex agent and write predictions."""

    _validate_agent_iteration_limit(max_agent_iterations, "max_agent_iterations")
    _validate_agent_iteration_limit(
        max_retrieval_iterations,
        "max_retrieval_iterations",
    )
    if runner_id not in SUPPORTED_AGENT_RUNNERS:
        raise ValueError(f"unsupported external agent runner: {runner_id}")

    root = Path(task_pack_root)
    validation = validate_external_task_pack(root, allow_local_gold=True)
    if not validation.is_valid and not allow_invalid:
        issue_codes = ", ".join(issue.code for issue in validation.issues[:5])
        raise ValueError(
            "external ResearchFlowBench task pack validation failed before agent run"
            + (f": {issue_codes}" if issue_codes else "")
        )

    manifest = _load_json(root / "adapter_manifest.json")
    benchmark_id = str(manifest.get("benchmark_id") or "")
    if benchmark_id != "autoresearchbench":
        raise ValueError(
            "external agent runner is currently supported only for AutoResearchBench"
        )
    if candidate_source is not None:
        _build_autoresearchbench_candidate_source(Path(candidate_source))

    manifest_task_ids = tuple(
        str(task_id)
        for task_id in manifest.get("task_ids", [])
        if isinstance(task_id, str)
    )
    selected_task_ids = tuple(task_ids) if task_ids else manifest_task_ids
    missing = sorted(set(selected_task_ids) - set(manifest_task_ids))
    if missing:
        raise ValueError(f"task IDs not found in task pack: {missing}")

    predictions_path = Path(predictions_file)
    if fake_predictions_file is not None:
        payload = _fake_agent_prediction_payload(
            Path(fake_predictions_file),
            root=root,
            manifest=manifest,
            runner_id=runner_id,
            selected_task_ids=selected_task_ids,
            max_agent_iterations=max_agent_iterations,
            max_retrieval_iterations=max_retrieval_iterations,
        )
    else:
        payload = _run_codex_agent_predictions(
            root=root,
            manifest=manifest,
            runner_id=runner_id,
            selected_task_ids=selected_task_ids,
            max_agent_iterations=max_agent_iterations,
            max_retrieval_iterations=max_retrieval_iterations,
            candidate_source=Path(candidate_source) if candidate_source else None,
            codex_bin=codex_bin,
            model=model,
            task_timeout_sec=task_timeout_sec,
            reasoning_effort=reasoning_effort,
        )

    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    predictions_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload | {"prediction_file": str(predictions_path)}


@contextlib.contextmanager
def prepare_autoresearchbench_agent_workspace(
    task_pack_root: str | Path,
    task_id: str,
    *,
    candidate_source: str | Path | None = None,
) -> Any:
    """Create a temporary gold-blind workspace for one AutoResearchBench task."""

    root = Path(task_pack_root)
    task_dir = root / "tasks" / task_id
    visible = _load_json(task_dir / "input.json")
    if (task_dir / "gold.json").exists():
        # The file may exist for local judge scoring, but it is intentionally not
        # copied into the agent workspace.
        pass

    with tempfile.TemporaryDirectory(prefix="rh-arb-agent-") as tmpdir:
        workspace = Path(tmpdir)
        task_out = workspace / "task"
        task_out.mkdir(parents=True, exist_ok=True)
        (task_out / "input.json").write_text(
            json.dumps(visible, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _write_codex_workspace_config(workspace)
        if candidate_source is not None:
            candidate_root = Path(candidate_source)
            candidate_manifest = _build_autoresearchbench_candidate_source(
                candidate_root
            ).manifest
            candidate_out = workspace / "candidate_source"
            candidate_out.mkdir()
            records_file = str(candidate_manifest.get("records_file") or "")
            if not records_file:
                raise ValueError("candidate source manifest is missing records_file")
            for relative_file in ("candidate_manifest.json", records_file):
                shutil.copyfile(
                    candidate_root / relative_file,
                    candidate_out / relative_file,
                )
            (candidate_out / "README.md").write_text(
                "This directory is a gold-blind copy of the non-gold "
                "AutoResearchBench candidate source for the current agent run.\n",
                encoding="utf-8",
            )
        yield workspace


def build_autoresearchbench_agent_prompt(
    *,
    task_id: str,
    visible_task: dict[str, Any],
    max_agent_iterations: int,
    max_retrieval_iterations: int,
    candidate_source: str | Path | None = None,
) -> str:
    """Build a gold-blind AutoResearchBench prompt from visible input only."""

    _validate_agent_iteration_limit(max_agent_iterations, "max_agent_iterations")
    _validate_agent_iteration_limit(
        max_retrieval_iterations,
        "max_retrieval_iterations",
    )
    candidate_hint = ""
    trace_shape = "{}"
    if candidate_source is not None:
        candidate_hint = (
            "\nA non-gold candidate-source manifest and corpus copy are available "
            "in `candidate_source/`. Inspect `candidate_source/candidate_manifest.json` "
            "and `candidate_source/candidate_corpus.jsonl` when using candidate "
            "evidence, but do not use any official benchmark answer material. "
            "In `runner_output.retrieval_trace`, include `candidate_source_used`, "
            "`candidate_source_files`, `candidate_ids`, `retrieval_trace_complete`, "
            "and `trace_status`; if you did not use the candidate source, set "
            "`candidate_source_used` to false, `candidate_ids` to [], "
            "`retrieval_trace_complete` to false, and `trace_status` to "
            "`candidate_source_not_used`."
        )
        trace_shape = (
            '{"candidate_source_available":true,'
            '"candidate_source_used":true,'
            '"candidate_source_files":["candidate_manifest.json",'
            '"candidate_corpus.jsonl"],"candidate_ids":["..."],'
            '"retrieval_trace_complete":true,'
            '"trace_status":"agent_reported_candidate_source_trace"}'
        )
    return (
        "You are running one AutoResearchBench task inside ResearchFlowBench.\n"
        "Use available Research Harness, web, and shell tools as needed. Keep the "
        f"research loop to at most {max_agent_iterations} agent iterations and "
        f"at most {max_retrieval_iterations} retrieval iterations.\n"
        "Use only the visible task input below and public/non-gold sources. Do not "
        "open, request, infer from, or search for local gold/official answer files. "
        "Do not use the original decrypted benchmark rows.\n"
        "Return strict JSON matching this shape: "
        '{"prediction":{"predicted_titles":["..."],'
        '"predicted_arxiv_ids":["..."]},"runner_output":'
        '{"iterations_used":1,"retrieval_iterations_used":1,'
        f'"retrieval_trace":{trace_shape},"notes":"..."}}.\n'
        "For Deep Research tasks, prioritize predicted_titles. For Wide Research "
        "tasks, prioritize predicted_arxiv_ids.\n"
        f"Task id: {task_id}\n"
        "Visible task JSON:\n"
        f"{json.dumps(_agent_prompt_visible_task(visible_task), sort_keys=True, ensure_ascii=False)}"
        f"{candidate_hint}"
    )


def _agent_prompt_visible_task(visible_task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(visible_task.get("task_id") or ""),
        "task_type": str(visible_task.get("task_type") or ""),
        "question": str(
            visible_task.get("question")
            or (visible_task.get("input") or {}).get("question")
            or ""
        ),
        "expected_rh_axes": list(visible_task.get("expected_rh_axes") or []),
    }


def _fake_agent_prediction_payload(
    fake_predictions_file: Path,
    *,
    root: Path,
    manifest: dict[str, Any],
    runner_id: str,
    selected_task_ids: tuple[str, ...],
    max_agent_iterations: int,
    max_retrieval_iterations: int,
) -> dict[str, Any]:
    payload = _load_json(fake_predictions_file)
    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("fake prediction file must contain a predictions list")
    selected = set(selected_task_ids)
    filtered = [
        dict(entry)
        for entry in predictions
        if isinstance(entry, dict) and str(entry.get("task_id") or "") in selected
    ]
    return {
        "schema_version": EXTERNAL_PREDICTIONS_SCHEMA_VERSION,
        "benchmark_id": "autoresearchbench",
        "adapter_contract": str(manifest.get("adapter_contract") or ""),
        "runner_id": runner_id,
        "model_execution_performed": payload.get("model_execution_performed") is True,
        "execution_limits": {
            "max_agent_iterations": max_agent_iterations,
            "max_retrieval_iterations": max_retrieval_iterations,
        },
        "predictions": filtered,
        "artifact_refs": [
            f"task_pack:{root}",
            f"fake_predictions:{fake_predictions_file}",
        ],
        "metadata": {
            "runner": "researchflowbench.autoresearchbench_agent_fake_replay.v0.1",
            "gold_blind_workspace": True,
            "task_count": len(filtered),
        },
    }


def _run_codex_agent_predictions(
    *,
    root: Path,
    manifest: dict[str, Any],
    runner_id: str,
    selected_task_ids: tuple[str, ...],
    max_agent_iterations: int,
    max_retrieval_iterations: int,
    candidate_source: Path | None,
    codex_bin: str,
    model: str | None,
    task_timeout_sec: int,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    predictions: list[dict[str, Any]] = []
    for task_id in selected_task_ids:
        task_visible = _load_json(root / "tasks" / task_id / "input.json")
        with prepare_autoresearchbench_agent_workspace(
            root,
            task_id,
            candidate_source=candidate_source,
        ) as workspace:
            output_schema = workspace / "prediction_schema.json"
            output_file = workspace / "last_message.json"
            output_schema.write_text(
                json.dumps(
                    _codex_prediction_schema(
                        candidate_source_available=candidate_source is not None
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            prompt = build_autoresearchbench_agent_prompt(
                task_id=task_id,
                visible_task=task_visible,
                max_agent_iterations=max_agent_iterations,
                max_retrieval_iterations=max_retrieval_iterations,
                candidate_source=candidate_source,
            )
            command = [
                codex_bin,
                "exec",
                "-C",
                str(workspace),
                "--skip-git-repo-check",
                "--ephemeral",
                "--disable",
                "hooks",
                "--ignore-rules",
                "--sandbox",
                "read-only",
                "--output-schema",
                str(output_schema),
                "--output-last-message",
                str(output_file),
            ]
            if model:
                command.extend(["--model", model])
            if reasoning_effort:
                command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
            command.append(prompt)
            try:
                completed = _run_codex_subprocess(
                    command,
                    timeout=task_timeout_sec,
                )
            except subprocess.TimeoutExpired as exc:
                predictions.append(
                    _invalid_agent_prediction(
                        task_id,
                        reason="codex_exec_timeout",
                        stderr=str(exc),
                        runner_id=runner_id,
                        candidate_source=candidate_source,
                    )
                )
                continue
            if completed.returncode != 0 or not output_file.exists():
                predictions.append(
                    _invalid_agent_prediction(
                        task_id,
                        reason="codex_exec_failed",
                        stderr=completed.stderr,
                        runner_id=runner_id,
                        candidate_source=candidate_source,
                    )
                )
                continue
            try:
                parsed = json.loads(output_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                predictions.append(
                    _invalid_agent_prediction(
                        task_id,
                        reason="codex_output_not_strict_json",
                        runner_id=runner_id,
                        candidate_source=candidate_source,
                    )
                )
                continue
            if not isinstance(parsed, dict) or not isinstance(
                parsed.get("prediction"),
                dict,
            ):
                predictions.append(
                    _invalid_agent_prediction(
                        task_id,
                        reason="codex_output_schema_invalid",
                        runner_id=runner_id,
                        candidate_source=candidate_source,
                    )
                )
                continue
            predictions.append(
                {
                    "task_id": task_id,
                    "prediction": dict(parsed["prediction"]),
                    "runner_output": _normalize_codex_runner_output(
                        (
                            dict(parsed.get("runner_output"))
                            if isinstance(parsed.get("runner_output"), dict)
                            else {}
                        ),
                        task_id=task_id,
                        runner_id=runner_id,
                        candidate_source=candidate_source,
                    ),
                }
            )

    return {
        "schema_version": EXTERNAL_PREDICTIONS_SCHEMA_VERSION,
        "benchmark_id": "autoresearchbench",
        "adapter_contract": str(manifest.get("adapter_contract") or ""),
        "runner_id": runner_id,
        "model_execution_performed": True,
        "execution_limits": {
            "max_agent_iterations": max_agent_iterations,
            "max_retrieval_iterations": max_retrieval_iterations,
        },
        "predictions": predictions,
        "artifact_refs": [f"task_pack:{root}"],
        "metadata": {
            "runner": "researchflowbench.autoresearchbench_rh_codex_agent.v0.1",
            "gold_blind_workspace": True,
            "strict_json": True,
            "task_count": len(predictions),
            "candidate_source": str(candidate_source or ""),
            "reasoning_effort": str(reasoning_effort or ""),
        },
    }


def _run_codex_subprocess(
    command: list[str],
    *,
    timeout: int | float,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=_supports_process_group_cleanup(),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = _terminate_timed_out_process(process)
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=timeout,
            output=stdout,
            stderr=stderr,
        ) from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _terminate_timed_out_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        _signal_process_tree(process, signal.SIGTERM)
    try:
        return process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            _signal_process_tree(process, signal.SIGKILL)
        return process.communicate(timeout=2)


def _signal_process_tree(process: subprocess.Popen[str], sig: int) -> None:
    if _supports_process_group_cleanup():
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, sig)
        return
    if sig == signal.SIGTERM:
        process.terminate()
        return
    process.kill()


def _supports_process_group_cleanup() -> bool:
    return hasattr(os, "killpg")


def _normalize_codex_runner_output(
    runner_output: dict[str, Any],
    *,
    task_id: str,
    runner_id: str,
    candidate_source: Path | None,
) -> dict[str, Any]:
    normalized = dict(runner_output)
    trace = normalized.get("retrieval_trace")
    normalized["retrieval_trace"] = (
        _normalize_codex_candidate_source_trace(
            dict(trace) if isinstance(trace, dict) else {},
            task_id=task_id,
            runner_id=runner_id,
            candidate_source=candidate_source,
        )
        if candidate_source is not None
        else (dict(trace) if isinstance(trace, dict) else {})
    )
    return normalized


def _normalize_codex_candidate_source_trace(
    trace: dict[str, Any],
    *,
    task_id: str,
    runner_id: str,
    candidate_source: Path,
) -> dict[str, Any]:
    source = _build_autoresearchbench_candidate_source(candidate_source)
    manifest = source.manifest
    records_file = str(manifest.get("records_file") or "")
    candidate_source_files = ["candidate_manifest.json"]
    if records_file:
        candidate_source_files.append(records_file)

    normalized = {
        "schema_version": "researchflowbench.autoresearchbench_codex_trace.v0.1",
        "task_id": task_id,
        "runner_id": runner_id,
        "candidate_source_available": True,
        "candidate_source_files": candidate_source_files,
        "candidate_source_schema_version": str(manifest.get("schema_version") or ""),
        "candidate_source_records_file": records_file,
        "candidate_source_record_count": len(source.records_by_id),
        **trace,
    }
    has_trace_details = _codex_trace_has_candidate_details(normalized)
    normalized.setdefault("candidate_source_used", has_trace_details)
    normalized.setdefault("candidate_ids", [])
    normalized.setdefault("retrieval_trace_complete", has_trace_details)
    normalized.setdefault(
        "trace_status",
        (
            "agent_reported_candidate_source_trace"
            if has_trace_details
            else "missing_candidate_source_trace"
        ),
    )
    return normalized


def _codex_trace_has_candidate_details(trace: dict[str, Any]) -> bool:
    if trace.get("candidate_source_used") is True:
        return True
    for key in ("candidate_ids", "candidate_set", "retrieval_tool_calls"):
        value = trace.get(key)
        if isinstance(value, list) and value:
            return True
    for key in ("query", "query_used"):
        if str(trace.get(key) or "").strip():
            return True
    return False


def _invalid_agent_prediction(
    task_id: str,
    *,
    reason: str,
    stderr: str = "",
    runner_id: str = "",
    candidate_source: Path | None = None,
) -> dict[str, Any]:
    runner_output = {
        "iterations_used": 0,
        "retrieval_iterations_used": 0,
        "error": reason,
        "stderr_tail": stderr[-2000:],
    }
    return {
        "task_id": task_id,
        "runner_output": _normalize_codex_runner_output(
            runner_output,
            task_id=task_id,
            runner_id=runner_id,
            candidate_source=candidate_source,
        ),
    }


def _codex_prediction_schema(
    *,
    candidate_source_available: bool = False,
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["prediction", "runner_output"],
        "properties": {
            "prediction": {
                "type": "object",
                "additionalProperties": False,
                "required": ["predicted_titles", "predicted_arxiv_ids"],
                "properties": {
                    "predicted_titles": {"type": "array", "items": {"type": "string"}},
                    "predicted_arxiv_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "runner_output": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "iterations_used",
                    "retrieval_iterations_used",
                    "retrieval_trace",
                    "notes",
                ],
                "properties": {
                    "iterations_used": {"type": "integer", "minimum": 0, "maximum": 5},
                    "retrieval_iterations_used": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 5,
                    },
                    "retrieval_trace": {
                        "type": "object",
                        "additionalProperties": False,
                        **_codex_retrieval_trace_schema(
                            candidate_source_available=candidate_source_available,
                        ),
                    },
                    "notes": {"type": "string"},
                },
            },
        },
    }


def _codex_retrieval_trace_schema(
    *,
    candidate_source_available: bool,
) -> dict[str, Any]:
    if not candidate_source_available:
        return {"properties": {}}
    required = [
        "candidate_source_available",
        "candidate_source_used",
        "candidate_source_files",
        "candidate_ids",
        "retrieval_trace_complete",
        "trace_status",
    ]
    return {
        "required": required,
        "properties": {
            "candidate_source_available": {"type": "boolean"},
            "candidate_source_used": {"type": "boolean"},
            "candidate_source_files": {
                "type": "array",
                "items": {"type": "string"},
            },
            "candidate_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "retrieval_trace_complete": {"type": "boolean"},
            "trace_status": {"type": "string"},
        },
    }


def _write_codex_workspace_config(workspace: Path) -> None:
    repo = _repo_root()
    if repo is None:
        return
    script = repo / "scripts" / "rh-mcp-keychain.sh"
    if not script.exists():
        return
    config_dir = workspace / ".codex"
    config_dir.mkdir(exist_ok=True)
    config = (
        "# Auto-generated gold-blind ResearchFlowBench agent workspace.\n"
        "[mcp_servers.research-harness]\n"
        'command = "bash"\n'
        "args = [\n"
        '  "-lc",\n'
        f'  "export RESEARCH_HARNESS_ROOT={json.dumps(str(repo))}; '
        f"export RESEARCH_HARNESS_DB_PATH={json.dumps(str(repo / '.research-harness' / 'pool.db'))}; "
        f'exec {json.dumps(str(script))}",\n'
        "]\n"
        "startup_timeout_sec = 30\n"
        "tool_timeout_sec = 300\n"
    )
    (config_dir / "config.toml").write_text(config, encoding="utf-8")


def _repo_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts" / "rh-mcp-keychain.sh").exists():
            return parent
    return None


def _validate_agent_iteration_limit(value: int, name: str) -> None:
    if value < 1 or value > MAX_EXTERNAL_AGENT_ITERATIONS:
        raise ValueError(
            f"{name} must be between 1 and {MAX_EXTERNAL_AGENT_ITERATIONS}"
        )


def _build_litsearch_local_db(data_root: Path, db_path: Path) -> Database:
    corpus_path = data_root / "corpus_clean" / "corpus.jsonl"
    if not corpus_path.exists():
        raise ValueError(f"LitSearch corpus file is required: {corpus_path}")

    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        records: list[tuple[str, str, str | None, None, None]] = []
        with corpus_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    continue
                doc_id = str(
                    record.get("corpusid")
                    or record.get("corpus_id")
                    or record.get("paper_id")
                    or ""
                ).strip()
                if not doc_id:
                    continue
                records.append(
                    (
                        str(record.get("title") or ""),
                        str(record.get("abstract") or ""),
                        doc_id,
                        None,
                        None,
                    )
                )
        conn.executemany(
            """
            INSERT INTO papers (title, abstract, s2_id, doi, arxiv_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _score_litsearch_task_with_paper_search(
    db: Database,
    root: Path,
    task_id: str,
    *,
    runner_id: str,
    evidence_state: str,
) -> dict[str, Any]:
    task_dir = root / "tasks" / task_id
    visible = _load_json(task_dir / "input.json")
    gold_path = task_dir / "gold.json"
    if not gold_path.exists():
        return {
            "task_id": task_id,
            "split": str(visible.get("split") or "mutate_dev"),
            "metrics": {},
            "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
            "baseline_id": runner_id,
            "model_execution_performed": False,
            "evidence_state": "blocked_missing_local_gold",
            "blockers": ["external_gold_file_missing"],
        }

    gold = _load_json(gold_path)
    task = LitSearchTask(
        task_id=task_id,
        query_id=str(visible.get("query_id") or task_id),
        query=str(visible.get("query") or ""),
        gold_paper_ids=tuple(str(item) for item in gold.get("gold_paper_ids") or ()),
        corpus_paper_ids=tuple(
            str(item) for item in visible.get("corpus_paper_ids") or ()
        ),
        split=str(visible.get("split") or "mutate_dev"),
        metadata=dict(visible.get("metadata") or {}),
    )

    paper_search = get_primitive_impl("paper_search")
    if paper_search is None:
        raise RuntimeError("paper_search primitive not registered")
    output = paper_search(
        db=db,
        query=task.query,
        max_results=20,
        local_only=True,
        local_index_cache=True,
        auto_ingest=False,
    )
    retrieved = tuple(
        paper.s2_id for paper in output.papers if getattr(paper, "s2_id", "")
    )

    score = LitSearchAdapter.score_retrieval(task, retrieved)
    payload = score.to_dict()
    payload["split"] = task.split
    payload["metrics"] = {
        "retrieval_recall": payload["recall_at_k"],
        "rerank_quality": payload["mrr"],
        "hit_at_k": payload["hit_at_k"],
    }
    payload["rh_axis_ids"] = list(visible.get("expected_rh_axes") or [])
    payload["baseline_id"] = runner_id
    payload["runner_id"] = runner_id
    payload["model_execution_performed"] = False
    payload["evidence_state"] = evidence_state
    payload["retrieved_paper_ids"] = list(retrieved[:20])
    payload["primitive_trace"] = {
        "primitive": "paper_search",
        "local_only": True,
        "local_index_cache": True,
        "retrieval_backend": getattr(output, "retrieval_backend", ""),
        "providers_queried": list(getattr(output, "providers_queried", [])),
    }
    payload["retrieval_trace"] = _external_litsearch_retrieval_trace(
        task=task,
        runner_id=runner_id,
        output=output,
        max_results=20,
    )
    return payload


def _external_litsearch_retrieval_trace(
    *,
    task: LitSearchTask,
    runner_id: str,
    output: Any,
    max_results: int,
) -> dict[str, Any]:
    """Build a replay trace with query, source, rank, and candidate evidence."""

    retrieval_backend = str(getattr(output, "retrieval_backend", "") or "")
    candidates = [
        {
            "candidate_id": _paper_candidate_id(paper),
            "rank": rank,
            "source": f"paper_search.{retrieval_backend or 'unknown'}",
            "title": str(getattr(paper, "title", "") or ""),
            "s2_id": str(getattr(paper, "s2_id", "") or ""),
            "arxiv_id": str(getattr(paper, "arxiv_id", "") or ""),
            "doi": str(getattr(paper, "doi", "") or ""),
            "relevance_score": float(getattr(paper, "relevance_score", 0.0) or 0.0),
        }
        for rank, paper in enumerate(getattr(output, "papers", []) or [], 1)
    ]
    candidate_ids = [
        str(candidate["candidate_id"])
        for candidate in candidates
        if candidate.get("candidate_id")
    ]
    query_used = str(getattr(output, "query_used", "") or task.query)
    return {
        "schema_version": "researchflowbench.external_retrieval_trace.v0.1",
        "task_id": task.task_id,
        "runner_id": runner_id,
        "primitive": "paper_search",
        "query": task.query,
        "query_used": query_used,
        "max_results": max_results,
        "retrieval_backend": retrieval_backend,
        "providers_queried": list(getattr(output, "providers_queried", [])),
        "provider_errors": list(getattr(output, "provider_errors", [])),
        "total_before_filter": int(getattr(output, "total_before_filter", 0) or 0),
        "retrieval_tool_calls": [
            {
                "tool_name": "paper_search",
                "call_mode": "local_only",
                "local_index_cache": True,
                "max_results": max_results,
            }
        ],
        "candidate_set": candidates,
        "candidate_ids": candidate_ids,
        "retrieval_trace_complete": bool(query_used),
    }


def _paper_candidate_id(paper: Any) -> str:
    for field_name in ("s2_id", "arxiv_id", "doi", "title"):
        value = str(getattr(paper, field_name, "") or "").strip()
        if value:
            return value
    return ""


def _aggregate_external_metrics(scores: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    metric_names = tuple(
        dict.fromkeys(
            metric
            for score in scores
            for metric in (score.get("metrics") or {})
            if isinstance(metric, str)
        )
    )
    aggregates: dict[str, Any] = {
        "score_count": len(scores),
        "blocked_score_count": sum(
            1
            for score in scores
            if str(score.get("evidence_state") or "").startswith("blocked")
        ),
    }
    for metric in metric_names:
        aggregates[f"mean_{metric}"] = _mean_metric(scores, metric)
    return aggregates


def _mean_metric(scores: tuple[dict[str, Any], ...], metric_name: str) -> float:
    values = [
        float((score.get("metrics") or {}).get(metric_name) or 0.0) for score in scores
    ]
    return round(sum(values) / len(values), 6) if values else 0.0


def _common_split(scores: tuple[dict[str, Any], ...]) -> str:
    splits = tuple(dict.fromkeys(str(score.get("split") or "") for score in scores))
    if len(splits) == 1:
        return splits[0]
    return "mixed"


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data
