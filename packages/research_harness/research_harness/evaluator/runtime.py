"""Runtime for internal promoted evaluators.

Evaluators are replay-gated capability candidates managed by the
self-evolution loop. They are not user-facing workflow skills; those live under
the repository's top-level ``skills/`` directory.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..orchestrator.artifacts import ArtifactManager
from ..orchestrator.service import OrchestratorService
from ..runtime import (
    CapabilityManifest,
    RUNTIME_TRACE_GRADE_SCHEMA,
    RunSpec,
    RunTrace,
    RunVisibleInputs,
    TraceStep,
    grade_run_trace,
)
from ..evolution.harness import scan_pdf_quality_bundle
from ..storage.db import Database


FINAL_BUNDLE_QUALITY_REPORT_SCHEMA = "rh.schema.artifact.final_bundle_quality_report.v0"
PUBLICATION_PACK_SCHEMA = "rh.schema.artifact.publication_pack.v0"

_RECOMPILE_REPAIRABLE_CATEGORIES = {
    "invalid_utf8",
    "latex_error",
    "malformed_latex_command",
    "missing_pdf",
    "missing_tex",
    "undefined_citation",
    "undefined_control_sequence",
}
_LAYOUT_CATEGORIES = {"overfull_hbox", "underfull_hbox"}
_ENCODING_CATEGORIES = {"invalid_utf8"}


@dataclass(frozen=True)
class EvaluatorResult:
    """Result of running one promoted evaluator."""

    skill_name: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""


Evaluator = Callable[..., EvaluatorResult]


def supported_evaluators() -> tuple[str, ...]:
    """Return promoted evaluators supported by this runtime."""

    return tuple(sorted(_EVALUATOR_REGISTRY))


def register_evaluator(
    skill_name: str,
    runner: Evaluator,
    *,
    replace: bool = False,
) -> None:
    """Register one evaluator runner.

    Core evaluators are registered in this module. The function exists so tests
    and future plugin loaders can add evaluators without editing the dispatcher.
    """

    if not skill_name:
        raise ValueError("evaluator name is required")
    if skill_name in _EVALUATOR_REGISTRY and not replace:
        raise ValueError(f"evaluator already registered: {skill_name}")
    _EVALUATOR_REGISTRY[skill_name] = runner


def run_evaluator(
    skill_name: str,
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    capability_manifest: CapabilityManifest | dict[str, Any],
    run_spec: RunSpec | dict[str, Any],
    guardrail_results: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
) -> EvaluatorResult:
    """Run a promoted evaluator and record its durable output artifact."""

    capability = _coerce_capability_manifest(capability_manifest)
    spec = _coerce_run_spec(run_spec)
    if capability.name != skill_name:
        return EvaluatorResult(
            skill_name=skill_name,
            success=False,
            error=(
                f"skill_name {skill_name!r} does not match capability "
                f"{capability.name!r}"
            ),
        )

    runner = _EVALUATOR_REGISTRY.get(skill_name)
    if runner is None:
        return EvaluatorResult(
            skill_name=skill_name,
            success=False,
            output={"supported_evaluators": supported_evaluators()},
            error=f"Unsupported evaluator: {skill_name}",
        )

    normalized_guardrails = tuple(dict(item) for item in guardrail_results)
    result = runner(
        db=db,
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        capability=capability,
        spec=spec,
        guardrail_results=normalized_guardrails,
    )
    return _record_skill_run_trace(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        capability=capability,
        spec=spec,
        result=result,
        guardrail_results=normalized_guardrails,
    )


def _run_final_bundle_quality(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    capability: CapabilityManifest,
    spec: RunSpec,
    guardrail_results: tuple[dict[str, Any], ...],
) -> EvaluatorResult:
    artifact_manager = ArtifactManager(db)
    source_artifact_id = _final_bundle_artifact_id(spec)
    if source_artifact_id <= 0:
        return EvaluatorResult(
            skill_name=capability.name,
            success=False,
            error="RunSpec must include artifact:final_bundle:<id>.",
        )

    source = artifact_manager.get(source_artifact_id)
    if source is None:
        return EvaluatorResult(
            skill_name=capability.name,
            success=False,
            error=f"final_bundle artifact not found: {source_artifact_id}",
        )
    if source.artifact_type != "final_bundle":
        return EvaluatorResult(
            skill_name=capability.name,
            success=False,
            error=(
                f"artifact {source_artifact_id} is {source.artifact_type!r}, "
                "expected 'final_bundle'"
            ),
        )
    if source.topic_id != topic_id or spec.topic_id != topic_id:
        return EvaluatorResult(
            skill_name=capability.name,
            success=False,
            error=(
                "final_bundle topic does not match evaluator topic: "
                f"artifact={source.topic_id}, spec={spec.topic_id}, call={topic_id}"
            ),
        )

    literal_inputs = spec.visible_inputs.literal_inputs
    target_profile = str(
        literal_inputs.get("target_profile")
        or source.payload.get("target_profile")
        or ""
    )
    mode = str(literal_inputs.get("mode") or "quality_scan")
    paths = _final_bundle_paths(
        source.payload,
        literal_bundle_paths=literal_inputs.get("bundle_paths"),
    )
    missing_path_keys = [
        key for key in ("tex_path", "pdf_path") if not str(paths.get(key) or "")
    ]
    if missing_path_keys:
        return EvaluatorResult(
            skill_name=capability.name,
            success=False,
            error=(
                "final_bundle payload missing required path(s): "
                + ", ".join(missing_path_keys)
            ),
        )

    signal = scan_pdf_quality_bundle(
        tex_path=paths["tex_path"],
        pdf_path=paths["pdf_path"],
        log_path=paths["log_path"],
        topic_id=topic_id,
        target_profile=target_profile,
        artifact_id=source_artifact_id,
    )
    payload = _final_bundle_quality_report_payload(
        capability=capability,
        spec=spec,
        source_artifact_id=source_artifact_id,
        mode=mode,
        target_profile=target_profile,
        paths=paths,
        signal=signal,
        source_payload=source.payload,
        guardrail_results=guardrail_results,
    )
    report = svc.record_artifact(
        topic_id=topic_id,
        stage=stage,
        artifact_type="final_bundle_quality_report",
        title=f"Final bundle quality report for artifact #{source_artifact_id}",
        payload=payload,
        metadata={
            "schema_version": FINAL_BUNDLE_QUALITY_REPORT_SCHEMA,
            "skill_name": capability.name,
            "run_id": spec.run_id,
            "source_artifact_id": source_artifact_id,
        },
        dependency_artifact_ids=[source_artifact_id],
    )
    return EvaluatorResult(
        skill_name=capability.name,
        success=True,
        output={
            "artifact_type": "final_bundle_quality_report",
            "artifact_id": report.id,
            "source_artifact_id": source_artifact_id,
            "issue_counts": payload["issue_counts"],
            "promotion_decision": payload["promotion_decision"],
            "payload": payload,
        },
    )


def _run_publication_pack(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    capability: CapabilityManifest,
    spec: RunSpec,
    guardrail_results: tuple[dict[str, Any], ...],
) -> EvaluatorResult:
    del svc, stage, guardrail_results
    artifact_manager = ArtifactManager(db)
    required_artifacts = _required_artifact_ids_by_type(
        spec,
        required_types=("draft_pack", "evidence_pack"),
    )
    missing_refs = [
        artifact_type
        for artifact_type, artifact_id in required_artifacts.items()
        if artifact_id <= 0
    ]
    if missing_refs:
        return EvaluatorResult(
            skill_name=capability.name,
            success=False,
            error=(
                "RunSpec must include required publication-pack artifact refs: "
                + ", ".join(missing_refs)
            ),
        )

    for artifact_type, artifact_id in required_artifacts.items():
        artifact = artifact_manager.get(artifact_id)
        if artifact is None:
            return EvaluatorResult(
                skill_name=capability.name,
                success=False,
                error=f"{artifact_type} artifact not found: {artifact_id}",
            )
        if artifact.artifact_type != artifact_type:
            return EvaluatorResult(
                skill_name=capability.name,
                success=False,
                error=(
                    f"artifact {artifact_id} is {artifact.artifact_type!r}, "
                    f"expected {artifact_type!r}"
                ),
            )
        if artifact.topic_id != topic_id or spec.topic_id != topic_id:
            return EvaluatorResult(
                skill_name=capability.name,
                success=False,
                error=(
                    f"{artifact_type} topic does not match evaluator topic: "
                    f"artifact={artifact.topic_id}, spec={spec.topic_id}, call={topic_id}"
                ),
            )
        if artifact.status != "active" or artifact.stale:
            return EvaluatorResult(
                skill_name=capability.name,
                success=False,
                error=(
                    f"{artifact_type} artifact must be active and non-stale: "
                    f"{artifact_id}"
                ),
            )

    literal_inputs = spec.visible_inputs.literal_inputs
    target_profile = str(literal_inputs.get("target_profile") or "high-impact-general")

    from ..primitives.writing_impls import publication_pack_generate

    output = publication_pack_generate(
        db=db,
        topic_id=topic_id,
        target_profile=target_profile,
        record_artifact=True,
    )
    artifact_id = _int_value(getattr(output, "publication_pack_artifact_id", 0))
    if artifact_id <= 0:
        return EvaluatorResult(
            skill_name=capability.name,
            success=False,
            error="publication_pack_generate did not record a publication_pack artifact.",
        )
    artifact = artifact_manager.get(artifact_id)
    payload = (
        dict(artifact.payload) if artifact is not None else dataclasses.asdict(output)
    )
    payload.setdefault("schema_version", PUBLICATION_PACK_SCHEMA)
    payload.setdefault("skill_name", capability.name)
    payload.setdefault("skill_version", capability.version)
    payload.setdefault("run_id", spec.run_id)
    _update_artifact_payload(db, artifact_id, payload)

    return EvaluatorResult(
        skill_name=capability.name,
        success=True,
        output={
            "artifact_type": "publication_pack",
            "artifact_id": artifact_id,
            "target_profile": target_profile,
            "ready_for_review": bool(getattr(output, "ready_for_review", False)),
            "submission_ready": bool(getattr(output, "submission_ready", False)),
            "missing_required": list(getattr(output, "missing_required", ())),
            "missing_optional": list(getattr(output, "missing_optional", ())),
            "payload": payload,
        },
    )


def _record_skill_run_trace(
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    capability: CapabilityManifest,
    spec: RunSpec,
    result: EvaluatorResult,
    guardrail_results: tuple[dict[str, Any], ...],
) -> EvaluatorResult:
    output_artifact_id = _int_value(result.output.get("artifact_id"))
    status = "success" if result.success else "failed"
    now = _utc_now()
    steps = [
        TraceStep(
            step_id="guardrails.runtime_contract",
            kind="guardrail",
            status="success",
            started_at=now,
            finished_at=now,
            metadata={
                "skill_name": capability.name,
                "guardrail_results": list(guardrail_results),
            },
        ),
        TraceStep(
            step_id=f"skill.{capability.name}",
            kind="tool_call",
            status=status,
            started_at=now,
            finished_at=now,
            input_ref=f"run_spec:{spec.stable_hash()}",
            output_ref=(
                f"project_artifacts:{output_artifact_id}"
                if output_artifact_id
                else None
            ),
            metadata={
                "skill_name": capability.name,
                "capability_type": str(capability.capability_type.value),
                "allowed_tools": list(capability.allowed_tools),
            },
        ),
    ]
    if result.success and output_artifact_id:
        steps.append(
            TraceStep(
                step_id="artifact.write",
                kind="artifact_write",
                status="success",
                started_at=now,
                finished_at=now,
                output_ref=f"project_artifacts:{output_artifact_id}",
                metadata={
                    "artifact_type": str(result.output.get("artifact_type") or ""),
                    "artifact_id": output_artifact_id,
                },
            )
        )

    trace = RunTrace.from_spec(
        spec,
        task_id=f"skill:{capability.name}",
        status=status,
        steps=tuple(steps),
        output_artifact_ids=(
            (output_artifact_id,) if result.success and output_artifact_id else ()
        ),
        errors=(
            ()
            if result.success
            else ({"skill_name": capability.name, "error": result.error},)
        ),
    )
    trace_artifact = svc.record_artifact(
        topic_id=topic_id,
        stage=stage,
        artifact_type="run_trace",
        title=f"Run trace for {capability.name}",
        payload=trace.to_dict(),
        metadata={
            "schema_version": trace.schema_version,
            "skill_name": capability.name,
            "run_id": spec.run_id,
        },
        dependency_artifact_ids=(
            _artifact_ids_from_refs(spec.visible_inputs.artifact_refs)
            + ([output_artifact_id] if output_artifact_id else [])
        ),
    )
    output_artifact_type = str(result.output.get("artifact_type") or "")
    trace_grade = grade_run_trace(
        trace,
        spec=spec,
        capability_manifest=capability,
        output_artifact_types=((output_artifact_type,) if output_artifact_type else ()),
    )
    trace_grade["run_trace_artifact_id"] = trace_artifact.id
    grade_artifact = svc.record_artifact(
        topic_id=topic_id,
        stage=stage,
        artifact_type="runtime_trace_grade",
        title=f"Runtime trace grade for {capability.name}",
        payload=trace_grade,
        metadata={
            "schema_version": RUNTIME_TRACE_GRADE_SCHEMA,
            "skill_name": capability.name,
            "run_id": spec.run_id,
            "run_trace_artifact_id": trace_artifact.id,
        },
        dependency_artifact_ids=(
            [trace_artifact.id] + ([output_artifact_id] if output_artifact_id else [])
        ),
    )
    output = {
        **result.output,
        "run_trace_artifact_id": trace_artifact.id,
        "run_trace": trace.to_dict(),
        "runtime_trace_grade_artifact_id": grade_artifact.id,
        "runtime_trace_grade": trace_grade,
    }
    return EvaluatorResult(
        skill_name=result.skill_name,
        success=result.success,
        output=output,
        error=result.error,
    )


def _final_bundle_quality_report_payload(
    *,
    capability: CapabilityManifest,
    spec: RunSpec,
    source_artifact_id: int,
    mode: str,
    target_profile: str,
    paths: dict[str, str],
    signal: Any,
    source_payload: dict[str, Any],
    guardrail_results: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    issues = tuple(_issue_to_dict(issue) for issue in signal.issues)
    issue_groups = _issue_groups(issues)
    issue_counts = {
        "blocking": int(signal.metadata.get("blocking_issue_count", 0)),
        "recompile_repairable": int(
            signal.metadata.get("recompile_repairable_issue_count", 0)
        ),
        "layout_only": int(signal.metadata.get("layout_issue_count", 0)),
        "encoding": int(signal.metadata.get("encoding_issue_count", 0)),
    }
    finality = _finality_summary(source_payload)
    promotion_decision = _promotion_decision(
        mode=mode,
        issue_counts=issue_counts,
        finality=finality,
    )
    replay_decision = {
        "source_trajectory_passed": False,
        "held_out_replay_passed": False,
        "target_profile_match": "none",
        "promotion_strength": "none",
    }

    return {
        "schema_version": FINAL_BUNDLE_QUALITY_REPORT_SCHEMA,
        "skill_name": capability.name,
        "skill_version": capability.version,
        "run_id": spec.run_id,
        "source_artifact_id": source_artifact_id,
        "mode": mode,
        "target_profile": target_profile,
        "bundle_paths": paths,
        "summary": (
            "final_bundle_quality scan found "
            f"{issue_counts['blocking']} blocking, "
            f"{issue_counts['recompile_repairable']} recompile-repairable, "
            f"{issue_counts['layout_only']} layout, and "
            f"{issue_counts['encoding']} encoding issue(s)."
        ),
        "issue_counts": issue_counts,
        "issue_groups": issue_groups,
        "issues": list(issues),
        "replay_decision": replay_decision,
        "promotion_decision": promotion_decision,
        "finality": finality,
        "guardrail_results": list(guardrail_results),
        "artifact_refs": {
            "source_final_bundle": f"project_artifacts:{source_artifact_id}",
        },
        "telemetry": dict(signal.metadata),
    }


def _promotion_decision(
    *,
    mode: str,
    issue_counts: dict[str, int],
    finality: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    if issue_counts["blocking"] > 0:
        reasons.append("blocking PDF/LaTeX issues are present")
    if issue_counts["recompile_repairable"] > 0:
        reasons.append("recompile-repairable issues must be fixed before promotion")
    if finality.get("blocks_final_promotion") is True:
        reasons.append(str(finality["reason"]))

    if reasons:
        return {"action": "refine", "reasons": reasons}

    if mode == "quality_scan":
        return {
            "action": "evaluate",
            "reasons": [
                "quality scan is clean; held-out replay is still required for promotion"
            ],
        }

    return {
        "action": "evaluate",
        "reasons": ["promotion evidence was not evaluated by this scan-only runner"],
    }


def _finality_summary(source_payload: dict[str, Any]) -> dict[str, Any]:
    evidence = source_payload.get("reference_pool_evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    finality_status = str(source_payload.get("finality_status") or "")
    is_interim = source_payload.get("is_interim") is True
    boundary = source_payload.get("interim_boundary")
    boundary_present = isinstance(boundary, dict) and bool(
        str(boundary.get("statement") or "").strip()
    )
    reference_passed = evidence.get("passed") is True
    minimum = int(evidence.get("minimum_required") or 0)
    usable = int(evidence.get("usable_screened_paper_count") or 0)
    blocks = (
        bool(evidence)
        and not reference_passed
        and not (is_interim and finality_status == "interim_ready" and boundary_present)
    )
    reason = ""
    if blocks:
        reason = (
            f"reference pool has {usable} usable screened paper(s), below the "
            f"final-PDF threshold of {minimum}; this bundle cannot be promoted as final"
        )
    return {
        "finality_status": finality_status,
        "is_interim": is_interim,
        "interim_boundary_present": boundary_present,
        "reference_pool_evidence": evidence,
        "blocks_final_promotion": blocks,
        "reason": reason,
    }


def _issue_groups(
    issues: tuple[dict[str, Any], ...],
) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "blocking": [],
        "recompile_repairable": [],
        "layout_only": [],
        "encoding": [],
    }
    for issue in issues:
        category = str(issue.get("category") or "")
        severity = str(issue.get("severity") or "")
        if severity in {"critical", "high"}:
            groups["blocking"].append(issue)
        if category in _RECOMPILE_REPAIRABLE_CATEGORIES:
            groups["recompile_repairable"].append(issue)
        if category in _LAYOUT_CATEGORIES:
            groups["layout_only"].append(issue)
        if category in _ENCODING_CATEGORIES:
            groups["encoding"].append(issue)
    return groups


def _issue_to_dict(issue: Any) -> dict[str, Any]:
    if dataclasses.is_dataclass(issue) and not isinstance(issue, type):
        return dataclasses.asdict(issue)
    if isinstance(issue, dict):
        return dict(issue)
    return {"message": str(issue)}


def _final_bundle_artifact_id(spec: RunSpec) -> int:
    for ref in spec.visible_inputs.artifact_refs:
        parsed = _parse_artifact_ref(ref)
        if parsed.get("artifact_type") == "final_bundle" and parsed.get("artifact_id"):
            return int(parsed["artifact_id"])
    return 0


def _required_artifact_ids_by_type(
    spec: RunSpec,
    *,
    required_types: tuple[str, ...],
) -> dict[str, int]:
    out = {artifact_type: 0 for artifact_type in required_types}
    for ref in spec.visible_inputs.artifact_refs:
        parsed = _parse_artifact_ref(ref)
        artifact_type = str(parsed.get("artifact_type") or "")
        if artifact_type in out and parsed.get("artifact_id"):
            out[artifact_type] = int(parsed["artifact_id"])
    return out


def _artifact_ids_from_refs(refs: tuple[str, ...]) -> list[int]:
    artifact_ids: list[int] = []
    for ref in refs:
        artifact_id = _int_value(_parse_artifact_ref(ref).get("artifact_id"))
        if artifact_id:
            artifact_ids.append(artifact_id)
    return artifact_ids


def _parse_artifact_ref(ref: str) -> dict[str, Any]:
    parts = [part for part in str(ref).split(":") if part]
    if len(parts) >= 3 and parts[0] == "artifact":
        return {"artifact_type": parts[1], "artifact_id": _int_value(parts[2])}
    if len(parts) >= 2 and parts[0] == "project_artifacts":
        return {
            "artifact_type": parts[2] if len(parts) >= 3 else "",
            "artifact_id": _int_value(parts[1]),
        }
    return {"artifact_type": ref, "artifact_id": 0}


def _final_bundle_paths(
    payload: dict[str, Any],
    *,
    literal_bundle_paths: Any = None,
) -> dict[str, str]:
    literal_paths = (
        literal_bundle_paths if isinstance(literal_bundle_paths, dict) else {}
    )
    paper_finalize = payload.get("paper_finalize")
    if not isinstance(paper_finalize, dict):
        paper_finalize = {}

    output_dir = str(literal_paths.get("output_dir") or payload.get("output_dir") or "")
    tex_path = str(
        literal_paths.get("tex_path")
        or payload.get("tex_path")
        or paper_finalize.get("tex_path")
        or ""
    )
    pdf_path = str(
        literal_paths.get("pdf_path")
        or payload.get("compiled_pdf_path")
        or payload.get("pdf_path")
        or paper_finalize.get("pdf_path")
        or ""
    )
    log_path = str(
        literal_paths.get("log_path")
        or payload.get("log_path")
        or paper_finalize.get("log_path")
        or ""
    )

    if not tex_path and output_dir:
        tex_path = _first_existing(
            output_dir, ("paper.tex", "main.tex", "manuscript.tex")
        )
    if not pdf_path and output_dir:
        pdf_path = _first_existing(
            output_dir, ("paper.pdf", "main.pdf", "manuscript.pdf")
        )
    if not log_path:
        if output_dir:
            log_path = str(Path(output_dir) / "paper.log")
        elif tex_path:
            log_path = str(Path(tex_path).with_suffix(".log"))

    return {
        "tex_path": tex_path,
        "pdf_path": pdf_path,
        "log_path": log_path,
        "output_dir": output_dir,
    }


def _first_existing(output_dir: str, names: tuple[str, ...]) -> str:
    root = Path(output_dir)
    for name in names:
        candidate = root / name
        if candidate.exists():
            return str(candidate)
    return ""


def _coerce_capability_manifest(
    value: CapabilityManifest | dict[str, Any],
) -> CapabilityManifest:
    if isinstance(value, CapabilityManifest):
        return value
    return CapabilityManifest(**dict(value))


def _coerce_run_spec(value: RunSpec | dict[str, Any]) -> RunSpec:
    if isinstance(value, RunSpec):
        return value
    data = dict(value)
    visible_inputs = data.get("visible_inputs")
    if isinstance(visible_inputs, dict):
        data["visible_inputs"] = RunVisibleInputs(**visible_inputs)
    return RunSpec(**data)


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _update_artifact_payload(
    db: Database, artifact_id: int, payload: dict[str, Any]
) -> None:
    import json

    conn = db.connect()
    try:
        conn.execute(
            """
            UPDATE project_artifacts
            SET payload_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (json.dumps(payload, ensure_ascii=False), artifact_id),
        )
        conn.commit()
    finally:
        conn.close()


_EVALUATOR_REGISTRY: dict[str, Evaluator] = {
    "final-bundle-quality": _run_final_bundle_quality,
    "publication-pack": _run_publication_pack,
}
