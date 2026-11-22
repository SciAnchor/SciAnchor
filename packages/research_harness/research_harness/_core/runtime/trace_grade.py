"""Runtime trace grading utilities."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import CapabilityManifest, RunSpec, RunTrace, RunVisibleInputs


RUNTIME_TRACE_GRADE_SCHEMA = "rh.schema.artifact.runtime_trace_grade.v0"


def grade_run_trace(
    trace: RunTrace | dict[str, Any],
    *,
    spec: RunSpec | dict[str, Any],
    capability_manifest: CapabilityManifest | dict[str, Any],
    output_artifact_types: Iterable[str] = (),
) -> dict[str, Any]:
    """Grade whether a runtime trace satisfies a capability/run contract."""

    runtime_trace = _coerce_trace(trace)
    run_spec = _coerce_run_spec(spec)
    capability = _coerce_capability_manifest(capability_manifest)
    output_types = {str(item) for item in output_artifact_types if str(item)}
    step_kinds = {str(step.kind.value) for step in runtime_trace.steps}
    tool_steps = [
        step for step in runtime_trace.steps if str(step.kind.value) == "tool_call"
    ]
    output_artifact_ids = tuple(
        int(item) for item in runtime_trace.outputs.get("artifact_ids", ())
    )

    checks = [
        _check(
            "run_id_match",
            runtime_trace.run_id == run_spec.run_id,
            "blocking",
            {
                "trace_run_id": runtime_trace.run_id,
                "run_spec_run_id": run_spec.run_id,
            },
        ),
        _check(
            "run_spec_hash_match",
            runtime_trace.inputs.get("run_spec_hash") == run_spec.stable_hash(),
            "blocking",
            {
                "trace_hash": runtime_trace.inputs.get("run_spec_hash"),
                "expected_hash": run_spec.stable_hash(),
            },
        ),
        _check(
            "required_steps_present",
            _required_steps_present(runtime_trace.status.value, step_kinds),
            "blocking",
            {
                "present": sorted(step_kinds),
                "required": _required_step_kinds(runtime_trace.status.value),
            },
        ),
        _check(
            "tool_call_bound_to_capability",
            all(
                str(step.metadata.get("skill_name") or "") == capability.name
                for step in tool_steps
            )
            and bool(tool_steps),
            "blocking",
            {
                "capability": capability.name,
                "tool_step_skill_names": [
                    str(step.metadata.get("skill_name") or "") for step in tool_steps
                ],
            },
        ),
        _check(
            "trace_tool_policy",
            _trace_tool_policy_passed(tool_steps, capability),
            "blocking",
            {
                "allowed_tools": list(capability.allowed_tools),
                "forbidden_tools": list(capability.forbidden_tools),
                "trace_tools": sorted(_trace_declared_tools(tool_steps)),
            },
        ),
        _check(
            "required_outputs_recorded",
            _required_outputs_recorded(
                runtime_trace.status.value,
                capability=capability,
                run_spec=run_spec,
                output_artifact_ids=output_artifact_ids,
                output_artifact_types=output_types,
            ),
            "blocking",
            {
                "required_outputs": list(
                    capability.produced_artifacts or run_spec.required_outputs
                ),
                "output_artifact_ids": list(output_artifact_ids),
                "output_artifact_types": sorted(output_types),
            },
        ),
    ]
    passed = all(check["passed"] for check in checks)
    return {
        "schema_version": RUNTIME_TRACE_GRADE_SCHEMA,
        "run_id": runtime_trace.run_id,
        "task_id": runtime_trace.task_id,
        "capability_name": capability.name,
        "trace_schema_version": runtime_trace.schema_version,
        "decision": "pass" if passed else "fail",
        "passed": passed,
        "checks": checks,
        "summary": (
            "Runtime trace satisfies the run contract."
            if passed
            else "Runtime trace failed one or more blocking checks."
        ),
    }


def _required_step_kinds(status: str) -> list[str]:
    if status == "success":
        return ["guardrail", "tool_call", "artifact_write"]
    return ["guardrail", "tool_call"]


def _required_steps_present(status: str, step_kinds: set[str]) -> bool:
    return set(_required_step_kinds(status)).issubset(step_kinds)


def _trace_tool_policy_passed(
    tool_steps: list[Any],
    capability: CapabilityManifest,
) -> bool:
    trace_tools = _trace_declared_tools(tool_steps)
    if not trace_tools:
        return bool(tool_steps)
    allowed = set(capability.allowed_tools)
    forbidden = set(capability.forbidden_tools)
    if forbidden & trace_tools:
        return False
    if allowed and trace_tools - allowed:
        return False
    return True


def _trace_declared_tools(tool_steps: list[Any]) -> set[str]:
    tools: set[str] = set()
    for step in tool_steps:
        for tool_name in step.metadata.get("allowed_tools") or ():
            if tool_name:
                tools.add(str(tool_name))
    return tools


def _required_outputs_recorded(
    status: str,
    *,
    capability: CapabilityManifest,
    run_spec: RunSpec,
    output_artifact_ids: tuple[int, ...],
    output_artifact_types: set[str],
) -> bool:
    if status != "success":
        return True
    required_outputs = set(capability.produced_artifacts or run_spec.required_outputs)
    if not required_outputs:
        return True
    if not output_artifact_ids:
        return False
    return required_outputs.issubset(output_artifact_types)


def _check(
    name: str,
    passed: bool,
    severity: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "severity": severity,
        "diagnostics": diagnostics,
    }


def _coerce_trace(value: RunTrace | dict[str, Any]) -> RunTrace:
    if isinstance(value, RunTrace):
        return value
    return RunTrace(**dict(value))


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
