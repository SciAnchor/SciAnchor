from __future__ import annotations

import json

import pytest

from research_harness.runtime import (
    ArtifactEnvelope,
    ArtifactLineage,
    ArtifactValidation,
    CapabilityManifest,
    GuardrailResult,
    RunSpec,
    RunTrace,
    RunVisibleInputs,
    TraceStep,
)


def test_runtime_contracts_are_core_canonical_and_public_path_reexports() -> None:
    from research_harness._core.runtime import CapabilityManifest as CoreCapability
    from research_harness._core.runtime import RunSpec as CoreRunSpec
    from research_harness._core.runtime import grade_run_trace as core_grade_run_trace
    from research_harness.runtime import CapabilityManifest as PublicCapability
    from research_harness.runtime import RunSpec as PublicRunSpec
    from research_harness.runtime import grade_run_trace as public_grade_run_trace

    assert PublicCapability is CoreCapability
    assert PublicRunSpec is CoreRunSpec
    assert public_grade_run_trace is core_grade_run_trace


def test_run_spec_is_jsonable_and_hashes_visible_contract() -> None:
    spec = RunSpec(
        run_id="run.write.001",
        task_type="writing",
        topic_id=7,
        objective="Draft a grounded manuscript section.",
        visible_inputs=RunVisibleInputs(
            literal_inputs={
                "method_card": {"core_idea": "Use retrieval before writing."},
                "result_card": {"main_result": "No unsupported numbers."},
            },
            artifact_refs=("artifact:evidence_pack:12",),
        ),
        forbidden_inputs=("hidden_gold", "original_target_sections"),
        required_outputs=("draft_pack", "claim_ledger"),
    )

    payload = spec.to_dict()

    assert payload["schema_version"] == "rh.run.v0"
    assert payload["task_type"] == "writing"
    assert payload["visible_inputs"]["artifact_refs"] == ["artifact:evidence_pack:12"]
    assert len(spec.stable_hash()) == 64
    json.dumps(payload)


def test_run_spec_rejects_forbidden_visible_inputs() -> None:
    with pytest.raises(ValueError, match="forbidden visible input"):
        RunSpec(
            run_id="run.leaky",
            task_type="writing",
            topic_id=7,
            objective="Leak hidden gold.",
            visible_inputs=RunVisibleInputs(
                literal_inputs={"hidden_gold": {"section": "gold abstract"}}
            ),
            forbidden_inputs=("hidden_gold",),
        )


def test_guardrail_result_trips_blocking_failures() -> None:
    warning = GuardrailResult(
        name="citation_density",
        scope="output",
        passed=False,
        severity="warning",
    )
    blocking = GuardrailResult(
        name="no_hidden_gold",
        scope="input",
        passed=False,
        severity="blocking",
    )

    assert warning.tripwire_triggered is False
    assert blocking.tripwire_triggered is True
    assert blocking.to_dict()["scope"] == "input"


def test_external_capability_manifest_requires_license_and_attribution() -> None:
    with pytest.raises(ValueError, match="source_url"):
        CapabilityManifest(
            name="paperqa2.grounded_qa",
            version="0.1.0",
            capability_type="adapter",
            owner="external",
            license="Apache-2.0",
            input_schema="rh.schema.input.grounded_qa.v0",
            output_schema="rh.schema.artifact.evidence_pack.v0",
        )

    with pytest.raises(ValueError, match="license"):
        CapabilityManifest(
            name="storm.outline",
            version="0.1.0",
            capability_type="adapter",
            owner="external",
            license="unknown",
            source_url="https://github.com/stanford-oval/storm",
            input_schema="rh.schema.input.outline.v0",
            output_schema="rh.schema.artifact.outline.v0",
        )

    manifest = CapabilityManifest(
        name="paperqa2.grounded_qa",
        version="0.1.0",
        capability_type="adapter",
        owner="external",
        license="Apache-2.0",
        source_url="https://github.com/Future-House/paper-qa",
        source_commit="abc123",
        input_schema="rh.schema.input.grounded_qa.v0",
        output_schema="rh.schema.artifact.evidence_pack.v0",
    )

    assert manifest.to_dict()["source_commit"] == "abc123"


def test_capability_manifest_accepts_evaluator_capability_type() -> None:
    manifest = CapabilityManifest(
        name="final-bundle-quality",
        version="0.1.2",
        capability_type="evaluator",
        owner="core",
        license="MIT",
        input_schema="rh.schema.input.final_bundle_quality.v0",
        output_schema="rh.schema.artifact.final_bundle_quality_report.v0",
    )

    assert manifest.to_dict()["capability_type"] == "evaluator"


def test_capability_manifest_validates_run_spec_policy_contract() -> None:
    manifest = CapabilityManifest(
        name="final-bundle-quality",
        version="0.1.2",
        capability_type="evaluator",
        owner="core",
        license="MIT",
        input_schema="rh.schema.input.final_bundle_quality.v0",
        output_schema="rh.schema.artifact.final_bundle_quality_report.v0",
        allowed_tools=("artifact.read", "pdf.scan_quality_bundle"),
        forbidden_tools=("external.publish",),
        required_artifacts=("final_bundle",),
        produced_artifacts=("final_bundle_quality_report",),
        guardrails=("active_final_bundle_required", "issue_classes_present"),
    )
    spec = RunSpec(
        run_id="run.final_bundle_quality.001",
        task_type="evaluation",
        topic_id=8,
        objective="Evaluate the active final_bundle.",
        visible_inputs=RunVisibleInputs(
            artifact_refs=("artifact:final_bundle:716",),
        ),
        required_outputs=("final_bundle_quality_report",),
        capability_policy={
            "allowed_capabilities": ("final-bundle-quality",),
            "allowed_tools": ("artifact.read", "pdf.scan_quality_bundle"),
            "denied_tools": ("external.publish",),
        },
        guardrails={
            "input": ("active_final_bundle_required",),
            "output": ("issue_classes_present",),
        },
    )

    results = manifest.validate_run_spec(spec)

    assert all(result.passed for result in results)
    assert {result.name for result in results} == {
        "capability_allowed",
        "capability_allowed_tools",
        "capability_forbidden_tools",
        "capability_required_artifacts",
        "capability_required_outputs",
        "capability_required_guardrails",
    }


def test_capability_manifest_blocks_run_spec_policy_drift() -> None:
    manifest = CapabilityManifest(
        name="final-bundle-quality",
        version="0.1.2",
        capability_type="evaluator",
        owner="core",
        license="MIT",
        input_schema="rh.schema.input.final_bundle_quality.v0",
        output_schema="rh.schema.artifact.final_bundle_quality_report.v0",
        allowed_tools=("artifact.read",),
        forbidden_tools=("external.publish",),
        required_artifacts=("final_bundle",),
        produced_artifacts=("final_bundle_quality_report",),
        guardrails=("active_final_bundle_required",),
    )
    spec = RunSpec(
        run_id="run.final_bundle_quality.bad",
        task_type="evaluation",
        topic_id=8,
        objective="Try to bypass the evaluator contract.",
        visible_inputs=RunVisibleInputs(
            artifact_refs=("artifact:publication_pack:44",),
        ),
        required_outputs=("unrelated_report",),
        capability_policy={
            "allowed_capabilities": ("other-capability",),
            "allowed_tools": ("artifact.read", "external.publish"),
        },
        guardrails={"input": ()},
    )

    results = manifest.validate_run_spec(spec)
    failures = {result.name: result for result in results if not result.passed}

    assert failures["capability_allowed"].tripwire_triggered is True
    assert failures["capability_allowed_tools"].diagnostics[0]["extra"] == (
        "external.publish",
    )
    assert failures["capability_forbidden_tools"].diagnostics[0]["forbidden"] == (
        "external.publish",
    )
    assert failures["capability_required_artifacts"].diagnostics[0]["missing"] == (
        "final_bundle",
    )
    assert failures["capability_required_outputs"].diagnostics[0]["missing"] == (
        "final_bundle_quality_report",
    )
    assert failures["capability_required_guardrails"].diagnostics[0]["missing"] == (
        "active_final_bundle_required",
    )


def test_capability_manifest_can_validate_actual_requested_tools() -> None:
    manifest = CapabilityManifest(
        name="tool-gated-capability",
        version="0.1.0",
        capability_type="evaluator",
        owner="core",
        license="MIT",
        input_schema="rh.schema.input.tool_gated.v0",
        output_schema="rh.schema.artifact.tool_gated_report.v0",
        allowed_tools=("paper_list",),
    )
    spec = RunSpec(
        run_id="run.tool_gate",
        task_type="evaluation",
        topic_id=1,
        objective="Validate the actual dispatch tool list.",
        capability_policy={
            "allowed_capabilities": ("tool-gated-capability",),
            "allowed_tools": ("paper_list",),
        },
    )

    results = manifest.validate_run_spec(
        spec,
        requested_tools=("paper_list", "external.publish"),
    )
    failure = next(
        result for result in results if result.name == "capability_allowed_tools"
    )

    assert failure.passed is False
    assert failure.diagnostics[0]["extra"] == ("external.publish",)


def test_artifact_envelope_records_lineage_and_validation() -> None:
    artifact = ArtifactEnvelope(
        artifact_id=22,
        artifact_type="draft_pack",
        schema_version="rh.schema.artifact.draft_pack.v0",
        topic_id=7,
        run_id="run.write.001",
        payload={"sections": {"abstract": "A grounded abstract."}},
        lineage=ArtifactLineage(
            source_artifact_ids=(10, 11),
            source_paper_ids=(101,),
            source_claim_ids=("claim.a",),
        ),
        validation=ArtifactValidation(
            schema_valid=True,
            guardrail_results=(
                GuardrailResult(
                    name="draft_pack_schema",
                    scope="output",
                    passed=True,
                    severity="info",
                ),
            ),
        ),
    )

    payload = artifact.to_dict()

    assert payload["lineage"]["source_artifact_ids"] == [10, 11]
    assert payload["validation"]["guardrail_results"][0]["name"] == "draft_pack_schema"
    json.dumps(payload)


def test_run_trace_binds_to_run_spec_hash_and_costs() -> None:
    spec = RunSpec(
        run_id="run.trace.001",
        task_type="evaluation",
        topic_id=3,
        objective="Replay one writing task.",
    )
    trace = RunTrace.from_spec(
        spec,
        task_id="rhbench.writing.001",
        trial_id="trial.1",
        status="success",
        steps=(
            TraceStep(
                step_id="step.guardrail.input",
                kind="guardrail",
                status="success",
                cost_usd=0.0,
            ),
            TraceStep(
                step_id="step.writer",
                kind="llm_call",
                status="success",
                cost_usd=0.42,
                model="test-model",
            ),
        ),
        output_artifact_ids=(22,),
    )

    payload = trace.to_dict()

    assert payload["inputs"]["run_spec_hash"] == spec.stable_hash()
    assert payload["costs"]["total_usd"] == 0.42
    assert payload["outputs"]["artifact_ids"] == [22]
    assert payload["steps"][1]["kind"] == "llm_call"


def test_runtime_trace_grade_passes_valid_skill_trace() -> None:
    from research_harness.runtime import grade_run_trace

    capability = CapabilityManifest(
        name="final-bundle-quality",
        version="0.1.2",
        capability_type="evaluator",
        owner="core",
        license="MIT",
        input_schema="rh.schema.input.final_bundle_quality.v0",
        output_schema="rh.schema.artifact.final_bundle_quality_report.v0",
        allowed_tools=("artifact.read", "pdf.scan_quality_bundle"),
        produced_artifacts=("final_bundle_quality_report",),
    )
    spec = RunSpec(
        run_id="run.trace.grade.pass",
        task_type="evaluation",
        topic_id=1,
        objective="Grade one skill trace.",
        visible_inputs=RunVisibleInputs(artifact_refs=("artifact:final_bundle:10",)),
        required_outputs=("final_bundle_quality_report",),
    )
    trace = RunTrace.from_spec(
        spec,
        task_id="skill:final-bundle-quality",
        status="success",
        steps=(
            TraceStep(
                step_id="guardrails.runtime_contract",
                kind="guardrail",
                status="success",
            ),
            TraceStep(
                step_id="skill.final-bundle-quality",
                kind="tool_call",
                status="success",
                metadata={
                    "skill_name": "final-bundle-quality",
                    "allowed_tools": ["artifact.read", "pdf.scan_quality_bundle"],
                },
            ),
            TraceStep(
                step_id="artifact.write",
                kind="artifact_write",
                status="success",
                output_ref="project_artifacts:22",
                metadata={
                    "artifact_id": 22,
                    "artifact_type": "final_bundle_quality_report",
                },
            ),
        ),
        output_artifact_ids=(22,),
    )

    grade = grade_run_trace(
        trace,
        spec=spec,
        capability_manifest=capability,
        output_artifact_types=("final_bundle_quality_report",),
    )

    assert grade["schema_version"] == "rh.schema.artifact.runtime_trace_grade.v0"
    assert grade["decision"] == "pass"
    assert all(check["passed"] for check in grade["checks"])


def test_runtime_trace_grade_fails_when_trace_hash_drifts() -> None:
    from research_harness.runtime import grade_run_trace

    capability = CapabilityManifest(
        name="final-bundle-quality",
        version="0.1.2",
        capability_type="evaluator",
        owner="core",
        license="MIT",
        input_schema="rh.schema.input.final_bundle_quality.v0",
        output_schema="rh.schema.artifact.final_bundle_quality_report.v0",
        produced_artifacts=("final_bundle_quality_report",),
    )
    spec = RunSpec(
        run_id="run.trace.grade.fail",
        task_type="evaluation",
        topic_id=1,
        objective="Grade one tampered trace.",
    )
    trace_payload = RunTrace.from_spec(
        spec,
        task_id="skill:final-bundle-quality",
        status="success",
        steps=(
            TraceStep(
                step_id="guardrails.runtime_contract",
                kind="guardrail",
                status="success",
            ),
            TraceStep(
                step_id="skill.final-bundle-quality",
                kind="tool_call",
                status="success",
                metadata={"skill_name": "final-bundle-quality"},
            ),
            TraceStep(
                step_id="artifact.write",
                kind="artifact_write",
                status="success",
                metadata={"artifact_type": "final_bundle_quality_report"},
            ),
        ),
        output_artifact_ids=(22,),
    ).to_dict()
    trace_payload["inputs"]["run_spec_hash"] = "tampered"

    grade = grade_run_trace(
        trace_payload,
        spec=spec,
        capability_manifest=capability,
        output_artifact_types=("final_bundle_quality_report",),
    )

    assert grade["decision"] == "fail"
    failures = {
        check["name"]: check for check in grade["checks"] if not check["passed"]
    }
    assert failures["run_spec_hash_match"]["severity"] == "blocking"
