"""Click commands for ResearchFlowBench task-pack construction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from .baseline import SUPPORTED_BASELINES, run_pilot20_baseline, write_score_report
from .baseline import run_external_task_pack_baseline
from .baseline import run_external_task_pack_predictions
from .baseline import build_autoresearchbench_candidate_source
from .builder import TaskPackBuildError, build_synthetic_pilot20_task_pack
from .autoresearchbench_adapter import AutoResearchBenchAdapter
from .attribution import (
    attribute_score_report_file,
    write_failure_attribution_report,
)
from .external_benchmarks import (
    check_local_benchmark_data,
    export_external_benchmark_registry,
    external_benchmark_registry_payload,
    local_benchmark_data_check_payload,
    local_benchmark_data_registry_payload,
)
from .litsearch_adapter import LitSearchAdapter
from .primitive_runner import (
    SUPPORTED_AGENT_RUNNERS,
    SUPPORTED_PRIMITIVE_RUNNERS,
    run_external_task_pack_agent,
    run_external_task_pack_primitive,
)
from .postsearch_pilot import (
    POSTSEARCH_SUPPORTED_BASELINES,
    SUPPORTED_POSTSEARCH_PRIMITIVE_RUNNERS,
    build_postsearch_pilot5_task_pack,
    run_postsearch_pilot5_baseline,
    run_postsearch_pilot5_predictions,
    run_postsearch_pilot5_primitive,
)
from .release_readiness import (
    run_release_readiness_checks,
    write_release_readiness_report,
)
from .schema_dry_run import run_schema_dry_run
from .score_gate import (
    compare_score_report_files,
    parse_metric_thresholds,
    write_score_comparison_gate,
)
from .validators import validate_external_task_pack


def _emit(ctx: click.Context, payload: dict[str, Any], text: str) -> None:
    if ctx.obj and ctx.obj.get("json"):
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    click.echo(text)


@click.group("researchflowbench")
def researchflowbench_group() -> None:
    """Build and validate ResearchFlowBench task packs."""


@researchflowbench_group.command("build-pilot20")
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for the synthetic Pilot-20 task pack.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Replace an existing non-empty output directory.",
)
@click.option(
    "--no-strict",
    "strict",
    is_flag=True,
    flag_value=False,
    default=True,
    help="Write the pack even if post-build validation reports failures.",
)
@click.option(
    "--schema-dry-run-output",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Optional directory for schema dry-run reports.",
)
@click.pass_context
def build_pilot20_cmd(
    ctx: click.Context,
    out_dir: Path,
    overwrite: bool,
    strict: bool,
    schema_dry_run_output: Path | None,
) -> None:
    """Generate the public-safe synthetic Pilot-20 task pack."""

    try:
        result = build_synthetic_pilot20_task_pack(
            out_dir,
            overwrite=overwrite,
            strict=strict,
        )
    except (FileExistsError, TaskPackBuildError) as exc:
        raise click.ClickException(str(exc)) from exc

    dry_run_summary = None
    if schema_dry_run_output is not None:
        dry_run_summary = run_schema_dry_run(out_dir, schema_dry_run_output)

    payload = {
        "schema_version": "researchflowbench.builder_result.v0.1",
        "root": str(result.root),
        "task_count": result.task_count,
        "validation_pass": result.validation_report.is_valid,
        "validation_issue_count": len(result.validation_report.issues),
        "preflight_pass": all(
            report.get("preflight_pass") for report in result.preflight_reports
        ),
        "leakage_pass": all(
            report.get("independent_audit_pass") for report in result.leakage_reports
        ),
        "schema_dry_run": dry_run_summary,
    }
    status = "PASS" if payload["validation_pass"] else "FAIL"
    text = (
        f"ResearchFlowBench Pilot-20 build {status}: {result.task_count} tasks -> "
        f"{result.root}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("build-postsearch-pilot5")
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for the synthetic post-search Pilot-5 task pack.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Replace an existing non-empty output directory.",
)
@click.option(
    "--include-gold",
    is_flag=True,
    default=False,
    help="Write local synthetic gold files so the pack can be scored immediately.",
)
@click.pass_context
def build_postsearch_pilot5_cmd(
    ctx: click.Context,
    out_dir: Path,
    overwrite: bool,
    include_gold: bool,
) -> None:
    """Generate the synthetic post-search Pilot-5 task pack."""

    try:
        manifest = build_postsearch_pilot5_task_pack(
            out_dir,
            overwrite=overwrite,
            include_gold=include_gold,
        )
    except FileExistsError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "schema_version": "researchflowbench.postsearch_pilot5_builder_result.v0.1",
        "root": str(out_dir),
        "benchmark_id": manifest["benchmark_id"],
        "task_count": manifest["task_count"],
        "gold_written": manifest["gold_written"],
        "model_execution_performed": False,
    }
    text = (
        "ResearchFlowBench post-search Pilot-5 build PASS: "
        f"{payload['task_count']} tasks -> {out_dir}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("run-baseline")
@click.option(
    "--task-pack",
    "task_pack_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="ResearchFlowBench Pilot-20 task-pack root to validate and score.",
)
@click.option(
    "--out",
    "out_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path for the researchflowbench_score_report.",
)
@click.option(
    "--baseline",
    "baseline_id",
    type=click.Choice(SUPPORTED_BASELINES),
    default="stub_zero",
    show_default=True,
    help="Model-free baseline behavior to run.",
)
@click.option(
    "--allow-invalid",
    is_flag=True,
    default=False,
    help="Emit a quarantinable report even when task-pack validation fails.",
)
@click.option(
    "--record-topic",
    default="",
    help="Optional topic name to record the score report as a self-evolution artifact.",
)
@click.option("--title", default="", help="Artifact title when --record-topic is set.")
@click.pass_context
def run_baseline_cmd(
    ctx: click.Context,
    task_pack_root: Path,
    out_file: Path,
    baseline_id: str,
    allow_invalid: bool,
    record_topic: str,
    title: str,
) -> None:
    """Run a model-free baseline and write a score report."""

    try:
        result = run_pilot20_baseline(
            task_pack_root,
            baseline_id=baseline_id,
            allow_invalid=allow_invalid,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    score_file = write_score_report(result.report, out_file)
    recorded_artifact_id = None
    if record_topic:
        recorded_artifact_id = _record_score_report_artifact(
            ctx,
            topic_name=record_topic,
            report=result.report | {"source_file": str(score_file)},
            title=title,
        )

    payload = {
        "schema_version": "researchflowbench.baseline_run_result.v0.1",
        "score_file": str(score_file),
        "benchmark_id": result.report["benchmark_id"],
        "baseline_id": result.report["baseline_id"],
        "score_count": len(result.report["scores"]),
        "validation_pass": result.validation_report.is_valid,
        "model_execution_performed": False,
        "recorded_artifact_id": recorded_artifact_id,
    }
    status = "PASS" if result.validation_report.is_valid else "QUARANTINED"
    text = (
        f"ResearchFlowBench baseline {status}: {payload['score_count']} scores -> "
        f"{score_file}"
    )
    if recorded_artifact_id:
        text += f"\nrecorded researchflowbench_score_report: {recorded_artifact_id}"
    _emit(ctx, payload, text)


@researchflowbench_group.command("run-postsearch-baseline")
@click.option(
    "--task-pack",
    "task_pack_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Post-search Pilot-5 task-pack root to validate and score.",
)
@click.option(
    "--out",
    "out_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path for the researchflowbench_score_report.",
)
@click.option(
    "--baseline",
    "baseline_id",
    type=click.Choice(POSTSEARCH_SUPPORTED_BASELINES),
    default="stub_zero",
    show_default=True,
    help="Model-free post-search baseline behavior to run.",
)
@click.option(
    "--allow-invalid",
    is_flag=True,
    default=False,
    help="Emit a quarantinable report even when task-pack validation fails.",
)
@click.pass_context
def run_postsearch_baseline_cmd(
    ctx: click.Context,
    task_pack_root: Path,
    out_file: Path,
    baseline_id: str,
    allow_invalid: bool,
) -> None:
    """Run a model-free post-search Pilot-5 baseline and write a score report."""

    try:
        result = run_postsearch_pilot5_baseline(
            task_pack_root,
            baseline_id=baseline_id,
            allow_invalid=allow_invalid,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    score_file = write_score_report(result.report, out_file)
    payload = {
        "schema_version": "researchflowbench.postsearch_baseline_run_result.v0.1",
        "score_file": str(score_file),
        "benchmark_id": result.report["benchmark_id"],
        "baseline_id": result.report["baseline_id"],
        "score_count": len(result.report["scores"]),
        "blocked_score_count": result.report["metadata"]["blocked_score_count"],
        "validation_pass": result.validation_report.is_valid,
        "model_execution_performed": False,
    }
    status = "PASS" if result.validation_report.is_valid else "QUARANTINED"
    text = (
        f"ResearchFlowBench post-search baseline {status}: "
        f"{payload['score_count']} scores -> {score_file}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("run-postsearch-primitive")
@click.option(
    "--task-pack",
    "task_pack_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Post-search Pilot-5 task-pack root to validate and replay.",
)
@click.option(
    "--out",
    "out_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path for the researchflowbench_score_report.",
)
@click.option(
    "--runner",
    "runner_id",
    type=click.Choice(SUPPORTED_POSTSEARCH_PRIMITIVE_RUNNERS),
    default="final_bundle_quality_scan",
    show_default=True,
    help="Post-search quality runner to execute.",
)
@click.option(
    "--allow-invalid",
    is_flag=True,
    default=False,
    help="Emit a quarantinable report even when task-pack validation fails.",
)
@click.pass_context
def run_postsearch_primitive_cmd(
    ctx: click.Context,
    task_pack_root: Path,
    out_file: Path,
    runner_id: str,
    allow_invalid: bool,
) -> None:
    """Run a post-search quality runner and write a score report."""

    try:
        result = run_postsearch_pilot5_primitive(
            task_pack_root,
            runner_id=runner_id,
            allow_invalid=allow_invalid,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    score_file = write_score_report(result.report, out_file)
    metrics = result.report["metrics"]
    payload = {
        "schema_version": "researchflowbench.postsearch_primitive_run_result.v0.1",
        "score_file": str(score_file),
        "benchmark_id": result.report["benchmark_id"],
        "runner_id": result.report["runner_id"],
        "score_count": len(result.report["scores"]),
        "blocked_score_count": metrics["blocked_score_count"],
        "skipped_score_count": metrics["skipped_score_count"],
        "supported_score_count": metrics["supported_score_count"],
        "validation_pass": result.validation_report.is_valid,
        "model_execution_performed": False,
    }
    status = "PASS" if result.validation_report.is_valid else "QUARANTINED"
    text = (
        f"ResearchFlowBench post-search quality runner {status}: "
        f"{payload['score_count']} scores -> {score_file}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("score-postsearch-predictions")
@click.option(
    "--task-pack",
    "task_pack_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Post-search Pilot-5 task-pack root to validate and score.",
)
@click.option(
    "--predictions",
    "predictions_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Externally generated post-search prediction JSON file.",
)
@click.option(
    "--out",
    "out_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path for the researchflowbench_score_report.",
)
@click.option(
    "--allow-invalid",
    is_flag=True,
    default=False,
    help="Emit a quarantinable report even when task-pack validation fails.",
)
@click.pass_context
def score_postsearch_predictions_cmd(
    ctx: click.Context,
    task_pack_root: Path,
    predictions_file: Path,
    out_file: Path,
    allow_invalid: bool,
) -> None:
    """Score externally generated post-search Pilot-5 predictions."""

    try:
        result = run_postsearch_pilot5_predictions(
            task_pack_root,
            predictions_file,
            allow_invalid=allow_invalid,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    score_file = write_score_report(result.report, out_file)
    metrics = result.report["metrics"]
    payload = {
        "schema_version": "researchflowbench.postsearch_prediction_score_result.v0.1",
        "score_file": str(score_file),
        "benchmark_id": result.report["benchmark_id"],
        "baseline_id": result.report["baseline_id"],
        "score_count": len(result.report["scores"]),
        "blocked_score_count": metrics["blocked_score_count"],
        "skipped_score_count": metrics["skipped_score_count"],
        "supported_score_count": metrics["supported_score_count"],
        "validation_pass": result.validation_report.is_valid,
        "model_execution_performed": result.report["model_execution_performed"],
    }
    status = "PASS" if result.validation_report.is_valid else "QUARANTINED"
    text = (
        f"ResearchFlowBench post-search prediction scoring {status}: "
        f"{payload['score_count']} scores -> {score_file}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("run-external-baseline")
@click.option(
    "--task-pack",
    "task_pack_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Adapter-generated external task-pack root to validate and score.",
)
@click.option(
    "--out",
    "out_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path for the researchflowbench_score_report.",
)
@click.option(
    "--allow-invalid",
    is_flag=True,
    default=False,
    help="Emit a quarantinable report even when external pack validation fails.",
)
@click.option(
    "--baseline",
    "baseline_id",
    type=click.Choice(
        (
            "stub_zero",
            "lexical_retrieval",
            "bm25_retrieval",
            "autoresearchbench_candidate_bm25",
        )
    ),
    default="stub_zero",
    show_default=True,
    help="Model-free external baseline behavior to run.",
)
@click.option(
    "--data",
    "data_root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help=(
        "Local official data root for LitSearch baselines, or a non-gold "
        "AutoResearchBench candidate-source root."
    ),
)
@click.option(
    "--evidence-state",
    default="fixture_or_local_gold",
    show_default=True,
    help="Evidence state for scored tasks with local gold, for example real_data.",
)
@click.option(
    "--candidate-top-k",
    type=int,
    default=20,
    show_default=True,
    help=(
        "Top-k retrieved candidates for AutoResearchBench candidate BM25. "
        "Ignored by other baselines."
    ),
)
@click.pass_context
def run_external_baseline_cmd(
    ctx: click.Context,
    task_pack_root: Path,
    out_file: Path,
    allow_invalid: bool,
    baseline_id: str,
    data_root: Path | None,
    evidence_state: str,
    candidate_top_k: int,
) -> None:
    """Run a model-free baseline for an external adapter task pack."""

    try:
        result = run_external_task_pack_baseline(
            task_pack_root,
            baseline_id=baseline_id,
            allow_invalid=allow_invalid,
            evidence_state=evidence_state,
            data_root=data_root,
            candidate_top_k=candidate_top_k,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    score_file = write_score_report(result.report, out_file)
    payload = {
        "schema_version": "researchflowbench.external_baseline_run_result.v0.1",
        "score_file": str(score_file),
        "benchmark_id": result.report["benchmark_id"],
        "baseline_id": result.report["baseline_id"],
        "score_count": len(result.report["scores"]),
        "blocked_score_count": result.report["metadata"]["blocked_score_count"],
        "candidate_top_k": result.report["metadata"]["candidate_top_k"],
        "validation_pass": result.validation_report.is_valid,
        "model_execution_performed": False,
    }
    status = "PASS" if result.validation_report.is_valid else "QUARANTINED"
    text = (
        f"ResearchFlowBench external baseline {status}: "
        f"{payload['score_count']} scores -> {score_file}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("run-external-primitive")
@click.option(
    "--task-pack",
    "task_pack_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Adapter-generated external task-pack root to validate and score.",
)
@click.option(
    "--out",
    "out_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path for the researchflowbench_score_report.",
)
@click.option(
    "--allow-invalid",
    is_flag=True,
    default=False,
    help="Emit a quarantinable report even when external pack validation fails.",
)
@click.option(
    "--runner",
    "runner_id",
    type=click.Choice(SUPPORTED_PRIMITIVE_RUNNERS),
    default="paper_search_local_bm25",
    show_default=True,
    help="RH primitive replay runner to execute.",
)
@click.option(
    "--data",
    "data_root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Local official data root required by the primitive replay runner.",
)
@click.option(
    "--evidence-state",
    default="fixture_or_local_gold",
    show_default=True,
    help="Evidence state for scored tasks with local gold, for example real_data.",
)
@click.pass_context
def run_external_primitive_cmd(
    ctx: click.Context,
    task_pack_root: Path,
    out_file: Path,
    allow_invalid: bool,
    runner_id: str,
    data_root: Path,
    evidence_state: str,
) -> None:
    """Run a real RH primitive replay for an external adapter task pack."""

    try:
        result = run_external_task_pack_primitive(
            task_pack_root,
            runner_id=runner_id,
            allow_invalid=allow_invalid,
            evidence_state=evidence_state,
            data_root=data_root,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    score_file = write_score_report(result.report, out_file)
    payload = {
        "schema_version": "researchflowbench.external_primitive_run_result.v0.1",
        "score_file": str(score_file),
        "benchmark_id": result.report["benchmark_id"],
        "runner_id": result.report["runner_id"],
        "score_count": len(result.report["scores"]),
        "blocked_score_count": result.report["metadata"]["blocked_score_count"],
        "validation_pass": result.validation_report.is_valid,
        "model_execution_performed": False,
    }
    status = "PASS" if result.validation_report.is_valid else "QUARANTINED"
    text = (
        f"ResearchFlowBench external primitive {status}: "
        f"{payload['score_count']} scores -> {score_file}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("run-external-agent")
@click.option(
    "--task-pack",
    "task_pack_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Adapter-generated external task-pack root to run gold-blind.",
)
@click.option(
    "--predictions-out",
    "predictions_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path for gold-blind external predictions.",
)
@click.option(
    "--allow-invalid",
    is_flag=True,
    default=False,
    help="Emit predictions even when external pack validation fails.",
)
@click.option(
    "--runner",
    "runner_id",
    type=click.Choice(SUPPORTED_AGENT_RUNNERS),
    default="autoresearchbench_rh_codex_agent",
    show_default=True,
    help="Gold-blind external agent runner to execute.",
)
@click.option(
    "--max-agent-iterations",
    type=int,
    default=5,
    show_default=True,
    help="Hard cap for agent iterations; values above 5 are rejected.",
)
@click.option(
    "--max-retrieval-iterations",
    type=int,
    default=5,
    show_default=True,
    help="Hard cap for retrieval iterations; values above 5 are rejected.",
)
@click.option(
    "--task-id",
    "task_ids",
    multiple=True,
    help="Optional task id to run. May be repeated.",
)
@click.option(
    "--candidate-source",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Optional non-gold AutoResearchBench candidate-source root.",
)
@click.option(
    "--fake-predictions",
    "fake_predictions_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Replay a local predictions file instead of calling Codex.",
)
@click.option(
    "--model",
    default=None,
    help="Optional Codex model override for real agent runs.",
)
@click.option(
    "--task-timeout-sec",
    type=int,
    default=1800,
    show_default=True,
    help="Per-task Codex subprocess timeout in seconds.",
)
@click.option(
    "--reasoning-effort",
    type=click.Choice(("low", "medium", "high", "xhigh")),
    default=None,
    help="Optional Codex model_reasoning_effort override for real agent runs.",
)
@click.pass_context
def run_external_agent_cmd(
    ctx: click.Context,
    task_pack_root: Path,
    predictions_file: Path,
    allow_invalid: bool,
    runner_id: str,
    max_agent_iterations: int,
    max_retrieval_iterations: int,
    task_ids: tuple[str, ...],
    candidate_source: Path | None,
    fake_predictions_file: Path | None,
    model: str | None,
    task_timeout_sec: int,
    reasoning_effort: str | None,
) -> None:
    """Run a gold-blind RH/Codex agent and write predictions first."""

    try:
        payload = run_external_task_pack_agent(
            task_pack_root,
            predictions_file=predictions_file,
            runner_id=runner_id,
            allow_invalid=allow_invalid,
            max_agent_iterations=max_agent_iterations,
            max_retrieval_iterations=max_retrieval_iterations,
            task_ids=tuple(task_ids),
            candidate_source=candidate_source,
            fake_predictions_file=fake_predictions_file,
            model=model,
            task_timeout_sec=task_timeout_sec,
            reasoning_effort=reasoning_effort,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    result_payload = {
        "schema_version": "researchflowbench.external_agent_run_result.v0.1",
        "predictions_file": str(predictions_file),
        "benchmark_id": payload["benchmark_id"],
        "runner_id": payload["runner_id"],
        "prediction_count": len(payload["predictions"]),
        "model_execution_performed": payload["model_execution_performed"],
        "gold_blind_workspace": payload["metadata"]["gold_blind_workspace"],
    }
    text = (
        "ResearchFlowBench external agent wrote "
        f"{result_payload['prediction_count']} predictions -> {predictions_file}"
    )
    _emit(ctx, result_payload, text)


@researchflowbench_group.command("score-external-predictions")
@click.option(
    "--task-pack",
    "task_pack_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Adapter-generated external task-pack root to validate and score.",
)
@click.option(
    "--predictions",
    "predictions_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Externally generated prediction JSON file.",
)
@click.option(
    "--out",
    "out_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path for the researchflowbench_score_report.",
)
@click.option(
    "--allow-invalid",
    is_flag=True,
    default=False,
    help="Emit a quarantinable report even when external pack validation fails.",
)
@click.option(
    "--evidence-state",
    default="prediction_file_scored",
    show_default=True,
    help="Evidence state for scored tasks, for example real_data.",
)
@click.option(
    "--max-agent-iterations",
    type=int,
    default=5,
    show_default=True,
    help="Hard cap for agent iterations; values above 5 are rejected.",
)
@click.option(
    "--max-retrieval-iterations",
    type=int,
    default=5,
    show_default=True,
    help="Hard cap for retrieval iterations; values above 5 are rejected.",
)
@click.option(
    "--task-id",
    "task_ids",
    multiple=True,
    help="Optional task id to score. May be repeated.",
)
@click.pass_context
def score_external_predictions_cmd(
    ctx: click.Context,
    task_pack_root: Path,
    predictions_file: Path,
    out_file: Path,
    allow_invalid: bool,
    evidence_state: str,
    max_agent_iterations: int,
    max_retrieval_iterations: int,
    task_ids: tuple[str, ...],
) -> None:
    """Score external predictions after the gold-blind run has completed."""

    try:
        result = run_external_task_pack_predictions(
            task_pack_root,
            predictions_file,
            allow_invalid=allow_invalid,
            evidence_state=evidence_state,
            max_agent_iterations=max_agent_iterations,
            max_retrieval_iterations=max_retrieval_iterations,
            task_ids=tuple(task_ids),
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    score_file = write_score_report(result.report, out_file)
    payload = {
        "schema_version": "researchflowbench.external_prediction_score_result.v0.1",
        "score_file": str(score_file),
        "benchmark_id": result.report["benchmark_id"],
        "baseline_id": result.report["baseline_id"],
        "score_count": len(result.report["scores"]),
        "blocked_score_count": result.report["metadata"]["blocked_score_count"],
        "validation_pass": result.validation_report.is_valid,
        "model_execution_performed": result.report["model_execution_performed"],
    }
    status = "PASS" if result.validation_report.is_valid else "QUARANTINED"
    text = (
        f"ResearchFlowBench external prediction scoring {status}: "
        f"{payload['score_count']} scores -> {score_file}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("attribute-score-report")
@click.option(
    "--score-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="ResearchFlowBench score report JSON to attribute by RH axis.",
)
@click.option(
    "--out",
    "out_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path for the failure attribution report.",
)
@click.option(
    "--evidence-state",
    default="",
    help="Default evidence state when scores do not specify one.",
)
@click.pass_context
def attribute_score_report_cmd(
    ctx: click.Context,
    score_file: Path,
    out_file: Path,
    evidence_state: str,
) -> None:
    """Group a score report's failures by RH metric axis."""

    try:
        report = attribute_score_report_file(score_file, evidence_state=evidence_state)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    output_path = write_failure_attribution_report(report, out_file)
    payload = {
        "schema_version": "researchflowbench.failure_attribution_result.v0.1",
        "output_file": str(output_path),
        "benchmark_id": report["benchmark_id"],
        "score_count": report["score_count"],
        "axis_count": len(report["axis_attribution"]),
        "evidence_state": report["evidence_state"],
        "automatic_mutation_enabled": False,
    }
    text = (
        "ResearchFlowBench failure attribution wrote "
        f"{payload['axis_count']} axes -> {output_path}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("compare-score-reports")
@click.option(
    "--baseline-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Baseline ResearchFlowBench score report JSON.",
)
@click.option(
    "--candidate-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Candidate ResearchFlowBench score report JSON.",
)
@click.option(
    "--out",
    "out_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output JSON path for the score comparison gate.",
)
@click.option(
    "--metric",
    "required_metrics",
    multiple=True,
    help="Metric key that must pass, for example mean_retrieval_recall.",
)
@click.option(
    "--min-delta",
    "min_delta_items",
    multiple=True,
    help="Required minimum delta as METRIC=VALUE.",
)
@click.option(
    "--max-regression",
    type=float,
    default=0.0,
    show_default=True,
    help="Allowed regression for metrics without an explicit --min-delta.",
)
@click.pass_context
def compare_score_reports_cmd(
    ctx: click.Context,
    baseline_file: Path,
    candidate_file: Path,
    out_file: Path,
    required_metrics: tuple[str, ...],
    min_delta_items: tuple[str, ...],
    max_regression: float,
) -> None:
    """Compare score reports and write a pass/fail optimization gate."""

    try:
        min_deltas = parse_metric_thresholds(min_delta_items)
        report = compare_score_report_files(
            baseline_file,
            candidate_file,
            required_metrics=required_metrics,
            min_deltas=min_deltas,
            max_regression=max_regression,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    gate_file = write_score_comparison_gate(report, out_file)
    payload = {
        "schema_version": report["schema_version"],
        "status": report["status"],
        "gate_file": str(gate_file),
        "benchmark_id": report["benchmark_id"],
        "baseline_id": report["baseline_id"],
        "candidate_id": report["candidate_id"],
        "blockers": report["blockers"],
    }
    text = (
        f"ResearchFlowBench score comparison {report['status'].upper()}: "
        f"{report['candidate_id']} vs {report['baseline_id']} -> {gate_file}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("external-benchmarks")
@click.option(
    "--out",
    "out_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Optional output directory for external_benchmarks.json and .md.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Emit the registry payload as JSON even outside top-level rh --json.",
)
@click.pass_context
def external_benchmarks_cmd(
    ctx: click.Context,
    out_dir: Path | None,
    json_output: bool,
) -> None:
    """List public external benchmarks worth testing RH against."""

    payload = external_benchmark_registry_payload()
    if out_dir is not None:
        export_result = export_external_benchmark_registry(out_dir)
        payload["export"] = export_result.to_dict()

    if json_output or (ctx.obj and ctx.obj.get("json")):
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return

    p0 = ", ".join(payload["recommended_p0_ids"])
    click.echo(
        "ResearchFlowBench external benchmarks: "
        f"{payload['benchmark_count']} tracked; P0 adapters: {p0}"
    )


@researchflowbench_group.command("local-data-registry")
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Emit the local data registry payload as JSON even outside top-level rh --json.",
)
@click.pass_context
def local_data_registry_cmd(
    ctx: click.Context,
    json_output: bool,
) -> None:
    """List local official-data requirements for implemented adapters."""

    payload = local_benchmark_data_registry_payload()
    if json_output or (ctx.obj and ctx.obj.get("json")):
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return

    click.echo(
        "ResearchFlowBench local data registry: "
        f"{payload['benchmark_count']} adapter data contracts tracked"
    )


@researchflowbench_group.command("local-data-check")
@click.option(
    "--benchmark-id",
    type=str,
    default=None,
    help="Optional benchmark id to check, for example litsearch.",
)
@click.option(
    "--root",
    "root_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help=(
        "Optional benchmark data root. Defaults to "
        "RESEARCH_HARNESS_BENCHMARK_DATA, then .research-harness/benchmarks."
    ),
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Emit the preflight result as JSON even outside top-level rh --json.",
)
@click.pass_context
def local_data_check_cmd(
    ctx: click.Context,
    benchmark_id: str | None,
    root_dir: Path | None,
    json_output: bool,
) -> None:
    """Check local official benchmark files before adapting external data."""

    try:
        payload = local_benchmark_data_check_payload(benchmark_id, root=root_dir)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output or (ctx.obj and ctx.obj.get("json")):
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return

    checks = check_local_benchmark_data(benchmark_id, root=root_dir)
    blocked = [check for check in checks if not check.passed]
    status = "PASS" if not blocked else "BLOCKED"
    click.echo(
        "ResearchFlowBench local data check "
        f"{status}: {len(checks) - len(blocked)}/{len(checks)} contracts ready"
    )
    for check in blocked:
        click.echo(f"- {check.benchmark_id}: missing {', '.join(check.missing_files)}")


@researchflowbench_group.command("adapt-litsearch")
@click.option(
    "--data",
    "data_dir",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Local LitSearch export root, or a directory containing query/ and corpus_clean/.",
)
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for RH-formatted LitSearch tasks.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Optional maximum number of queries to adapt.",
)
@click.option(
    "--include-gold",
    is_flag=True,
    default=False,
    help="Write judge-only gold files locally. Do not commit these files.",
)
@click.pass_context
def adapt_litsearch_cmd(
    ctx: click.Context,
    data_dir: Path,
    out_dir: Path,
    limit: int | None,
    include_gold: bool,
) -> None:
    """Convert a local official LitSearch export into RH retrieval tasks."""

    try:
        adapter = LitSearchAdapter.from_directory(data_dir, max_queries=limit)
        manifest = adapter.write_task_pack(out_dir, include_gold=include_gold)
    except (RuntimeError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "schema_version": "researchflowbench.litsearch_adapter_result.v0.1",
        "output_dir": str(out_dir),
        "manifest": manifest,
    }
    text = (
        "ResearchFlowBench LitSearch adapter wrote "
        f"{manifest['task_count']} tasks -> {out_dir}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("adapt-autoresearchbench")
@click.option(
    "--data",
    "data_dir",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Local plaintext AutoResearchBench JSONL export or containing directory.",
)
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for RH-formatted AutoResearchBench tasks.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Optional maximum number of tasks to adapt.",
)
@click.option(
    "--include-gold",
    is_flag=True,
    default=False,
    help="Write judge-only gold files locally. Do not commit these files.",
)
@click.pass_context
def adapt_autoresearchbench_cmd(
    ctx: click.Context,
    data_dir: Path,
    out_dir: Path,
    limit: int | None,
    include_gold: bool,
) -> None:
    """Convert a local official AutoResearchBench export into RH tasks."""

    try:
        adapter = AutoResearchBenchAdapter.from_directory(data_dir, max_tasks=limit)
        manifest = adapter.write_task_pack(out_dir, include_gold=include_gold)
    except (RuntimeError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "schema_version": "researchflowbench.autoresearchbench_adapter_result.v0.1",
        "output_dir": str(out_dir),
        "manifest": manifest,
    }
    text = (
        "ResearchFlowBench AutoResearchBench adapter wrote "
        f"{manifest['task_count']} tasks -> {out_dir}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("build-autoresearchbench-candidate-source")
@click.option(
    "--metadata-jsonl",
    "metadata_jsonl",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Non-gold paper metadata JSONL source.",
)
@click.option(
    "--paper-db",
    "paper_db",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Research Harness pool.db to read paper metadata from.",
)
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for candidate_manifest.json and candidate_corpus.jsonl.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Allow overwriting candidate source files in a non-empty output directory.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Optional maximum source records to read.",
)
@click.option(
    "--source-name",
    default=None,
    help="Optional provenance label for the candidate metadata source.",
)
@click.pass_context
def build_autoresearchbench_candidate_source_cmd(
    ctx: click.Context,
    metadata_jsonl: Path | None,
    paper_db: Path | None,
    out_dir: Path,
    overwrite: bool,
    limit: int | None,
    source_name: str | None,
) -> None:
    """Build a non-gold AutoResearchBench candidate-source root."""

    if (metadata_jsonl is None) == (paper_db is None):
        raise click.ClickException(
            "provide exactly one of --metadata-jsonl or --paper-db"
        )

    source = metadata_jsonl if metadata_jsonl is not None else paper_db
    source_kind = (
        "metadata_jsonl" if metadata_jsonl is not None else "research_harness_paper_db"
    )
    try:
        manifest = build_autoresearchbench_candidate_source(
            source,
            out_dir,
            source_kind=source_kind,
            overwrite=overwrite,
            limit=limit,
            source_name=source_name,
        )
    except (FileExistsError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "schema_version": (
            "researchflowbench.autoresearchbench_candidate_source_build_result.v0.1"
        ),
        "output_dir": str(out_dir),
        "manifest": manifest,
    }
    text = (
        "ResearchFlowBench AutoResearchBench candidate source wrote "
        f"{manifest['record_count']} records -> {out_dir}"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("validate-external-pack")
@click.option(
    "--task-pack",
    "task_pack_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Adapter-generated external task-pack root to validate.",
)
@click.option(
    "--allow-local-gold",
    is_flag=True,
    default=False,
    help="Permit local-only gold.json files during private judge development.",
)
@click.pass_context
def validate_external_pack_cmd(
    ctx: click.Context,
    task_pack_root: Path,
    allow_local_gold: bool,
) -> None:
    """Validate an external adapter task pack before scoring or recording."""

    report = validate_external_task_pack(
        task_pack_root,
        allow_local_gold=allow_local_gold,
    )
    payload = {
        "schema_version": "researchflowbench.external_task_pack_validation.v0.1",
        "report": report.to_dict(),
    }
    status = "PASS" if report.is_valid else "FAIL"
    text = (
        f"ResearchFlowBench external task-pack validation {status}: "
        f"{report.checked_task_count} tasks, {len(report.issues)} issues"
    )
    _emit(ctx, payload, text)


@researchflowbench_group.command("release-check")
@click.option(
    "--task-pack",
    "task_pack_root",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="RH-owned ResearchFlowBench Pilot-20 task-pack root to check.",
)
@click.option(
    "--out",
    "out_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Optional JSON path for the release-readiness report.",
)
@click.option(
    "--schema-dry-run-output",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Optional directory for schema dry-run reports.",
)
@click.option(
    "--rebuild-output",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Optional directory for the reproducibility rebuild.",
)
@click.option(
    "--docs-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("docs/researchflowbench.md"),
    show_default=True,
    help="Documentation file that must describe the release-readiness gate.",
)
@click.pass_context
def release_check_cmd(
    ctx: click.Context,
    task_pack_root: Path,
    out_file: Path | None,
    schema_dry_run_output: Path | None,
    rebuild_output: Path | None,
    docs_path: Path,
) -> None:
    """Run RH-owned v0 dataset release-readiness checks."""

    report = run_release_readiness_checks(
        task_pack_root,
        docs_path=docs_path,
        schema_dry_run_output=schema_dry_run_output,
        reproducibility_output=rebuild_output,
    )
    report_path = None
    if out_file is not None:
        report_path = write_release_readiness_report(report, out_file)

    payload = report.to_dict()
    payload["report_file"] = str(report_path) if report_path else None
    text = (
        "ResearchFlowBench release readiness "
        f"{report.status.upper()}: {payload['check_count']} checks"
    )
    if report_path:
        text += f" -> {report_path}"
    _emit(ctx, payload, text)


def _record_score_report_artifact(
    ctx: click.Context,
    *,
    topic_name: str,
    report: dict[str, Any],
    title: str,
) -> int:
    from research_harness.orchestrator.service import OrchestratorService
    from research_harness.storage.db import Database

    runtime_config = (ctx.obj or {}).get("runtime_config")
    if runtime_config is None:
        raise click.ClickException("runtime config is unavailable")
    db = Database(runtime_config.db_path)
    db.migrate()
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id FROM topics WHERE name = ?",
            (topic_name,),
        ).fetchone()
        if not row:
            raise click.ClickException(f"topic '{topic_name}' not found")
        topic_id = int(row[0])
    finally:
        conn.close()

    artifact = OrchestratorService(db).record_artifact(
        topic_id=topic_id,
        stage="project_self_evolution",
        artifact_type="researchflowbench_score_report",
        title=title or f"ResearchFlowBench baseline score: {report['benchmark_id']}",
        payload=report,
        metadata={
            "source": "researchflowbench",
            "benchmark_id": report["benchmark_id"],
            "baseline_id": report.get("baseline_id", ""),
            "score_count": len(report.get("scores") or []),
        },
    )
    return int(artifact.id)


def register(main_group: click.Group) -> None:
    """Register ResearchFlowBench commands on the top-level RH CLI."""

    main_group.add_command(researchflowbench_group)
