from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from research_harness._core.storage.db import Database
from research_harness.runtime.event_store import (
    _read_runtime_event_by_event_id,
    _read_runtime_events,
)


REPO_ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "scripts").exists() and (p / "AGENTS.md").exists()
)

K122_SLICE_ID = "K122_RUNTIME_EVENT_STORE_SELFDEV_CHECKPOINT_SOURCE"
K123_SLICE_ID = "K123_RUNTIME_EVENT_STORE_SELFDEV_HANDOFF_SOURCE"
K125_SLICE_ID = "K125_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE"
K127_SLICE_ID = "K127_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE"
K129_SLICE_ID = "K129_RUNTIME_EVENT_STORE_SELFDEV_SLICE_STATUS_SOURCE"
K131_SLICE_ID = "K131_RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_SOURCE"
K132_BATCH_GATE_ID = "K132_RUNTIME_EVENT_STORE_SELFDEV_BATCH_SOURCE_GATE"
K133_STATUS_SOURCE_ID = "K133_RUNTIME_EVENT_STORE_SELFDEV_STATUS_SOURCE"
K134_CLOUD_COMMAND_SOURCE_ID = "K134_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_COMMAND_SOURCE"
K135_CODEX_COMMAND_SOURCE_ID = "K135_RUNTIME_EVENT_STORE_SELFDEV_CODEX_COMMAND_SOURCE"
K141_CLOUD_SUBMIT_SOURCE_ID = "K141_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_SOURCE"
K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID = (
    "K142_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_FAILURE_SOURCE"
)
K143_CLOUD_SUBMIT_STARTED_SOURCE_ID = (
    "K143_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STARTED_SOURCE"
)
K144_EXTENDED_BATCH_GATE_ID = (
    "K144_RUNTIME_EVENT_STORE_SELFDEV_EXTENDED_BATCH_SOURCE_GATE"
)
K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID = (
    "K145_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_EVENT_SEQUENCE_HARDENING"
)
K146_CLOUD_SUBMIT_STORE_FAILURE_HARDENING_ID = (
    "K146_RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STORE_FAILURE_HARDENING"
)
K147_REDACTION_GUARD_ID = "K147_RUNTIME_EVENT_STORE_SELFDEV_REDACTION_GUARD"
K148_NEXT_ACTION_EXTENDED_BATCH_RECOVERY_ID = (
    "K148_RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_EXTENDED_BATCH_RECOVERY"
)
K149_EVENT_STORE_CONTRACT_REFRESH_ID = (
    "K149_RUNTIME_EVENT_STORE_SELFDEV_EVENT_STORE_CONTRACT_REFRESH"
)
K150_EXTENDED_BATCH_CLOSEOUT_ID = (
    "K150_RUNTIME_EVENT_STORE_SELFDEV_EXTENDED_BATCH_CLOSEOUT"
)
K151_POST_CLOSEOUT_REVIEW_GATE_ID = "K151_RUNTIME_EVENT_STORE_POST_CLOSEOUT_REVIEW_GATE"
K152_POST_CLOSEOUT_REVIEW_PACKAGE_ID = (
    "K152_RUNTIME_EVENT_STORE_POST_CLOSEOUT_REVIEW_PACKAGE"
)
K153_BROAD_AUTONOMY_POLICY_GATE_ID = "K153_RUNTIME_SHELL_BROAD_AUTONOMY_POLICY_GATE"
K154_INTERNAL_REVIEW_AUDIT_ID = "K154_RUNTIME_EVENT_STORE_INTERNAL_REVIEW_AUDIT"
K155_METADATA_REDACTION_AUDIT_ID = (
    "K155_RUNTIME_EVENT_STORE_SELFDEV_METADATA_REDACTION_AUDIT"
)
K156_POST_AUDIT_NEXT_ACTION_RECOVERY_ID = (
    "K156_RUNTIME_EVENT_STORE_SELFDEV_POST_AUDIT_NEXT_ACTION_RECOVERY"
)
K157_CLOSEOUT_VERIFICATION_SWEEP_ID = (
    "K157_RUNTIME_EVENT_STORE_SELFDEV_CLOSEOUT_VERIFICATION_SWEEP"
)
K159_DIRTY_BUNDLE_REVIEW_MANIFEST_ID = "K159_SELFDEV_DIRTY_BUNDLE_REVIEW_MANIFEST"
K160_VERIFICATION_MATRIX_COMMAND_ID = "K160_SELFDEV_VERIFICATION_MATRIX_COMMAND"
K161_REDACTION_INVARIANT_REFRESH_ID = (
    "K161_SELFDEV_RUNTIME_EVENT_REDACTION_INVARIANT_REFRESH"
)
K162_NEXT_ACTION_RECOVERY_REGRESSION_PACK_ID = (
    "K162_SELFDEV_NEXT_ACTION_RECOVERY_REGRESSION_PACK"
)
K163_FAST_BATCH_LANE_PROTOCOL_ID = "K163_SELFDEV_FAST_BATCH_LANE_PROTOCOL"
K164_BATCH_RUNNER_HELPERS_ID = "K164_SELFDEV_BATCH_RUNNER_HELPERS"
K165_CLOSEOUT_OBJECTIVE_MATRIX_ID = (
    "K165_SELFDEV_RUNTIME_SHELL_CLOSEOUT_OBJECTIVE_MATRIX"
)
K170_RUNTIME_SHELL_FINAL_CLOSEOUT_ID = (
    "K170_SELFDEV_RUNTIME_SHELL_FINAL_CLOSEOUT_REPORT"
)
K171_LONG_GOAL_ACTIVATION_ID = "K171_LG8_LG10_LONG_GOAL_ACTIVATION"
K172_PRIVATE_PERFORMANCE_BASELINE_ID = "K172_LG8_PRIVATE_PERFORMANCE_BASELINE"
K173_LG8_LG9_COMBINED_CONTRACT_ID = "K173_LG8_LG9_COMBINED_EXECUTION_CONTRACT"
K174_NEXT_ACTION_HOT_PATH_ID = "K174_LG8_SELFDEV_NEXT_ACTION_RECOVERY_HOT_PATH"
K175_RUNTIME_EVENT_APPEND_HOT_PATH_ID = "K175_LG8_RUNTIME_EVENT_APPEND_TEMPDB_HOT_PATH"
K176_NEXT_ACTION_COMMAND_HOT_PATH_ID = "K176_LG8_SELFDEV_NEXT_ACTION_COMMAND_HOT_PATH"
K177_LG9_DURABLE_CONTRACT_MATRIX_ID = "K177_LG9_DURABLE_CONTRACT_MATRIX"
K178_LG9_PROVENANCE_ARTIFACT_CONTRACT_ID = (
    "K178_LG9_PROVENANCE_ARTIFACT_LINKAGE_CONTRACT"
)
K179_LG9_ORCHESTRATOR_READONLY_CONTRACT_ID = (
    "K179_LG9_ORCHESTRATOR_READONLY_MAPPING_CONTRACT"
)
K180_LG8_LG9_PRIVATE_CLOSEOUT_ID = "K180_LG8_LG9_PRIVATE_CLOSEOUT_GUARD"
K181_LG10_PUBLIC_PRODUCTIZATION_BOUNDARY_ID = (
    "K181_LG10_PUBLIC_PRODUCTIZATION_GATE_BOUNDARY"
)
K182_LG10_BOUNDARY_PREVIEW_BATCH_GATE_ID = (
    "K182_LG10_BOUNDARY_PREVIEW_PUBLIC_SURFACE_BATCH_GATE"
)
K183_LG10_CLI_BOUNDARY_PREVIEW_ID = "K183_LG10_CLI_BOUNDARY_PREVIEW"
K184_LG10_MCP_BOUNDARY_PREVIEW_ID = "K184_LG10_MCP_BOUNDARY_PREVIEW"
K185_LG10_HTTP_PREVIEW_GATE_ID = "K185_LG10_HTTP_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
K186_LG10_HTTP_BOUNDARY_PREVIEW_ID = "K186_LG10_HTTP_BOUNDARY_PREVIEW"
K187_LG10_PYTHON_FACADE_PREVIEW_GATE_ID = (
    "K187_LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
K188_LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_ID = "K188_LG10_PYTHON_FACADE_BOUNDARY_PREVIEW"
K189_LG10_SKILLS_DOCS_PREVIEW_GATE_ID = (
    "K189_LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
K190_LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_ID = "K190_LG10_SKILLS_DOCS_BOUNDARY_PREVIEW"
K191_LG10_DOCTOR_PREVIEW_GATE_ID = (
    "K191_LG10_DOCTOR_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
K192_LG10_DOCTOR_BOUNDARY_PREVIEW_ID = "K192_LG10_DOCTOR_BOUNDARY_PREVIEW"
K193_LG10_SHOWCASE_PREVIEW_GATE_ID = (
    "K193_LG10_SHOWCASE_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
K194_LG10_SHOWCASE_BOUNDARY_PREVIEW_ID = "K194_LG10_SHOWCASE_BOUNDARY_PREVIEW"
POST_LG10_MAINLINE_CLOSEOUT_ID = "POST_LG10_MAINLINE_ACCEPTANCE_CLOSEOUT"
LG8_PRIVATE_PERFORMANCE_BASELINE_SUFFIX = "LG8_PRIVATE_PERFORMANCE_BASELINE"
LG8_LG9_COMBINED_CONTRACT_SUFFIX = "LG8_LG9_COMBINED_EXECUTION_CONTRACT"
LG8_NEXT_ACTION_HOT_PATH_SUFFIX = "LG8_SELFDEV_NEXT_ACTION_RECOVERY_HOT_PATH"
LG8_RUNTIME_EVENT_APPEND_HOT_PATH_SUFFIX = "LG8_RUNTIME_EVENT_APPEND_TEMPDB_HOT_PATH"
LG8_NEXT_ACTION_COMMAND_HOT_PATH_SUFFIX = "LG8_SELFDEV_NEXT_ACTION_COMMAND_HOT_PATH"
LG9_DURABLE_CONTRACT_MATRIX_SUFFIX = "LG9_DURABLE_CONTRACT_MATRIX"
LG9_PROVENANCE_ARTIFACT_CONTRACT_SUFFIX = "LG9_PROVENANCE_ARTIFACT_LINKAGE_CONTRACT"
LG9_ORCHESTRATOR_READONLY_CONTRACT_SUFFIX = "LG9_ORCHESTRATOR_READONLY_MAPPING_CONTRACT"
LG8_LG9_PRIVATE_CLOSEOUT_SUFFIX = "LG8_LG9_PRIVATE_CLOSEOUT_GUARD"
LG10_PUBLIC_PRODUCTIZATION_BOUNDARY_SUFFIX = "LG10_PUBLIC_PRODUCTIZATION_GATE_BOUNDARY"
LG10_BOUNDARY_PREVIEW_BATCH_GATE_SUFFIX = (
    "LG10_BOUNDARY_PREVIEW_PUBLIC_SURFACE_BATCH_GATE"
)
LG10_CLI_BOUNDARY_PREVIEW_SUFFIX = "LG10_CLI_BOUNDARY_PREVIEW"
LG10_MCP_BOUNDARY_PREVIEW_SUFFIX = "LG10_MCP_BOUNDARY_PREVIEW"
LG10_HTTP_PREVIEW_GATE_SUFFIX = "LG10_HTTP_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
LG10_HTTP_BOUNDARY_PREVIEW_SUFFIX = "LG10_HTTP_BOUNDARY_PREVIEW"
LG10_PYTHON_FACADE_PREVIEW_GATE_SUFFIX = (
    "LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_SUFFIX = "LG10_PYTHON_FACADE_BOUNDARY_PREVIEW"
LG10_SKILLS_DOCS_PREVIEW_GATE_SUFFIX = (
    "LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_SUFFIX = "LG10_SKILLS_DOCS_BOUNDARY_PREVIEW"
LG10_DOCTOR_PREVIEW_GATE_SUFFIX = "LG10_DOCTOR_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
LG10_DOCTOR_BOUNDARY_PREVIEW_SUFFIX = "LG10_DOCTOR_BOUNDARY_PREVIEW"
LG10_SHOWCASE_PREVIEW_GATE_SUFFIX = "LG10_SHOWCASE_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
LG10_SHOWCASE_BOUNDARY_PREVIEW_SUFFIX = "LG10_SHOWCASE_BOUNDARY_PREVIEW"
ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY_ID = (
    "ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY"
)
ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE_ID = "ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE"
ST03_LG10_BOUNDARY_PREVIEW_HARDENING_ID = "ST03_LG10_BOUNDARY_PREVIEW_HARDENING"
ST04_SURVEY_FIRST_RETRIEVAL_POLICY_STABILIZATION_ID = (
    "ST04_SURVEY_FIRST_RETRIEVAL_POLICY_STABILIZATION"
)
ST05_LG9_CONTRACT_GUARD_PRODUCTIZATION_ID = "ST05_LG9_CONTRACT_GUARD_PRODUCTIZATION"
ST06_ZOTERO_SERVICE_DRY_RUN_STABILIZATION_ID = (
    "ST06_ZOTERO_SERVICE_DRY_RUN_STABILIZATION"
)
ST07_RUNTIME_SELFDEV_TOOLING_STABLE_COMPONENTS_ID = (
    "ST07_RUNTIME_SELFDEV_TOOLING_STABLE_COMPONENTS"
)
ST08_NON_BENCHMARK_STABILIZATION_CLOSEOUT_ID = (
    "ST08_NON_BENCHMARK_STABILIZATION_CLOSEOUT"
)
G01_LOCAL_AUTONOMY_CONTROL_PLANE_ID = "G01_LOCAL_AUTONOMY_CONTROL_PLANE"
G02_DURABLE_SEMANTICS_LOCAL_IMPLEMENTATION_ID = (
    "G02_DURABLE_SEMANTICS_LOCAL_IMPLEMENTATION"
)
G03_PRODUCTIZATION_ZOTERO_LOCAL_PRODUCTIZATION_ID = (
    "G03_PRODUCTIZATION_ZOTERO_LOCAL_PRODUCTIZATION"
)
G04_PRIVATE_BENCHMARK_PERFORMANCE_GOVERNANCE_ID = (
    "G04_PRIVATE_BENCHMARK_PERFORMANCE_GOVERNANCE"
)


def load_script_module():
    script_path = REPO_ROOT / "scripts" / "rh-selfdev.py"
    spec = importlib.util.spec_from_file_location("rh_selfdev", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migrated_runtime_event_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "runtime-events.db")
    db.migrate()
    return db


def _write_slice_status_fixture(path: Path, status: str = "todo") -> None:
    path.write_text(
        f"""# RH Self-Development Slices

| Slice ID | Phase | Status | Risk | Parallel | Objective | Allowed files | Tests | Human gate |
|---|---|---|---|---|---|---|---|---|
| K127_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE | P6 | done | high | no | Completed prompt source. | scripts | tests | approved |
| {K129_SLICE_ID} | P6 | {status} | high | no | Route self-dev slice status events. | `scripts/rh-selfdev.py` | `focused tests` | approved |
""",
        encoding="utf-8",
    )


def _runtime_event_store_completed_slices(module, *extra_slice_ids: str):
    slice_ids = (
        "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
        "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
        "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
        "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
        "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
        "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER",
        "K109_RUNTIME_SHELL_P6_DOCTOR_DIAGNOSTICS_GATE",
        "K110_RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI",
        "K112_RUNTIME_EVENT_STORE_SCHEMA_GATE",
        "K113_RUNTIME_EVENT_STORE_SCHEMA_ONLY",
        "K115_RUNTIME_EVENT_WRITER_HELPER_GATE",
        "K116_RUNTIME_EVENT_STORE_WRITER_HELPER",
        "K117_RUNTIME_EVENT_STORE_WRITER_RELIABILITY",
        "K118_RUNTIME_EVENT_STORE_READBACK_HELPER",
        "K119_RUNTIME_EVENT_STORE_HEALTH_AND_CONTRACT",
        "K120_RUNTIME_EVENT_STORE_PUBLIC_SURFACE_GUARD",
        "K121_RUNTIME_EVENT_STORE_FIRST_SOURCE_GATE_PACKAGE",
        K122_SLICE_ID,
        K123_SLICE_ID,
        "K124_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE_GATE",
        K125_SLICE_ID,
        "K126_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE_GATE",
        K127_SLICE_ID,
        "K128_RUNTIME_EVENT_STORE_SELFDEV_SLICE_STATUS_SOURCE_GATE",
        K129_SLICE_ID,
        "K130_RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_SOURCE_GATE",
        K131_SLICE_ID,
        *extra_slice_ids,
    )
    return [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase="P6" if slice_id.startswith(("K109_", "K110_", "K1")) else "P5",
            status="done",
            risk="high" if slice_id.startswith("K1") else "medium",
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in slice_ids
    ]


def _cloud_command_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K134_CLOUD_COMMAND_SOURCE_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Route self-dev cloud-command dry-run events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="covered by K132",
    )


def _codex_command_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K135_CODEX_COMMAND_SOURCE_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Route self-dev codex-command dry-run events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="covered by K132",
    )


def _cloud_submit_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K141_CLOUD_SUBMIT_SOURCE_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Route self-dev cloud-submit events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved by K141",
    )


def _cloud_submit_failure_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Route self-dev cloud-submit failure events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved by K142",
    )


def _cloud_submit_started_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Route self-dev cloud-submit started events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved by K143",
    )


def _cloud_submit_sequence_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Harden self-dev cloud-submit event sequencing.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="covered by K144",
    )


def _cloud_submit_store_failure_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K146_CLOUD_SUBMIT_STORE_FAILURE_HARDENING_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Harden self-dev cloud-submit event-store failures.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="covered by K144",
    )


def _redaction_guard_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K147_REDACTION_GUARD_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Guard self-dev runtime event redaction.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="covered by K144",
    )


def _next_action_extended_batch_recovery_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K148_NEXT_ACTION_EXTENDED_BATCH_RECOVERY_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Harden self-dev extended-batch next-action recovery.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="covered by K144",
    )


def _event_store_contract_refresh_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K149_EVENT_STORE_CONTRACT_REFRESH_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Refresh self-dev event-store contract coverage.",
        allowed_files="runtime event tests",
        tests="focused tests",
        human_gate="covered by K144",
    )


def _extended_batch_closeout_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K150_EXTENDED_BATCH_CLOSEOUT_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Close out the K144 extended batch.",
        allowed_files=".rh-selfdev",
        tests="focused checks",
        human_gate="covered by K144",
    )


def _post_closeout_review_gate_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K151_POST_CLOSEOUT_REVIEW_GATE_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Approve one docs-only post-K150 review package.",
        allowed_files=".rh-selfdev",
        tests="focused tests",
        human_gate="approved by direct user instruction",
    )


def _post_closeout_review_package_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K152_POST_CLOSEOUT_REVIEW_PACKAGE_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Create the post-K150 runtime event store review package.",
        allowed_files=".rh-selfdev",
        tests="focused checks",
        human_gate="covered by K151",
    )


def _broad_autonomy_policy_gate_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K153_BROAD_AUTONOMY_POLICY_GATE_ID,
        phase="P6",
        status=status,
        risk="high",
        parallel="no",
        objective="Approve broad autonomous continuation for non-large-risk work.",
        allowed_files="self-dev policy files",
        tests="focused tests",
        human_gate="approved by direct user instruction",
    )


def _internal_review_audit_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K154_INTERNAL_REVIEW_AUDIT_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Audit the runtime event store internal dirty worktree.",
        allowed_files=".rh-selfdev",
        tests="focused checks",
        human_gate="covered by K153",
    )


def _metadata_redaction_audit_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K155_METADATA_REDACTION_AUDIT_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Harden self-dev metadata redaction.",
        allowed_files="scripts; tests; docs",
        tests="focused tests",
        human_gate="K153 broad autonomy covers private redaction hardening.",
    )


def _post_audit_next_action_recovery_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K156_POST_AUDIT_NEXT_ACTION_RECOVERY_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Recover latest post-audit next-action boundary.",
        allowed_files="scripts; tests; docs",
        tests="focused tests",
        human_gate="K153 broad autonomy covers self-dev recovery.",
    )


def _closeout_verification_sweep_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K157_CLOSEOUT_VERIFICATION_SWEEP_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Closeout verification sweep.",
        allowed_files="docs",
        tests="focused checks",
        human_gate="K153 broad autonomy covers closeout verification.",
    )


def _verification_matrix_command_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K160_VERIFICATION_MATRIX_COMMAND_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Internalize the self-dev verification matrix.",
        allowed_files="scripts; tests; docs",
        tests="focused verification-matrix tests",
        human_gate="K153 broad autonomy covers private self-dev tooling.",
    )


def _redaction_invariant_refresh_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K161_REDACTION_INVARIANT_REFRESH_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Refresh self-dev redaction invariants.",
        allowed_files="scripts; tests; docs",
        tests="focused redaction invariant tests",
        human_gate="K153 broad autonomy covers private redaction hardening.",
    )


def _next_action_recovery_regression_pack_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K162_NEXT_ACTION_RECOVERY_REGRESSION_PACK_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Add broad-autonomy next-action recovery regressions.",
        allowed_files="scripts; tests; docs",
        tests="focused next-action recovery tests",
        human_gate="K153 broad autonomy covers private recovery tests.",
    )


def _fast_batch_lane_protocol_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K163_FAST_BATCH_LANE_PROTOCOL_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Document the private fast batch lane protocol.",
        allowed_files=".rh-selfdev/control-plane.md",
        tests="git diff --check",
        human_gate="K153 broad autonomy covers private protocol docs.",
    )


def _batch_runner_helpers_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K164_BATCH_RUNNER_HELPERS_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Add private self-dev batch summary helpers.",
        allowed_files="scripts/rh-selfdev.py; tests; self-dev docs",
        tests="focused batch-summary tests",
        human_gate="K153 broad autonomy covers private self-dev tooling.",
    )


def _closeout_objective_matrix_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K165_CLOSEOUT_OBJECTIVE_MATRIX_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Encode the self-dev and runtime-shell closeout objective matrix.",
        allowed_files="scripts; tests; self-dev docs",
        tests="focused closeout-matrix tests",
        human_gate="K153 broad autonomy covers private planning tooling.",
    )


def _runtime_shell_final_closeout_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K170_RUNTIME_SHELL_FINAL_CLOSEOUT_ID,
        phase="P6",
        status=status,
        risk="low",
        parallel="no",
        objective="Complete the runtime-shell final internal closeout report.",
        allowed_files="self-dev docs",
        tests="focused closeout checks",
        human_gate="K153 broad autonomy covers private closeout docs.",
    )


def _long_goal_activation_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K171_LONG_GOAL_ACTIVATION_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Activate LG8/LG9/LG10 as the next long-goal sequence.",
        allowed_files="self-dev docs; scripts; tests",
        tests="focused next-action tests",
        human_gate="Direct user instruction selects the next non-large-risk line.",
    )


def _lg8_private_performance_baseline_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K172_PRIVATE_PERFORMANCE_BASELINE_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Create the LG8 private performance baseline runner and report.",
        allowed_files="scripts/rh-perf-baseline.py; self-dev docs; tests",
        tests="focused private performance baseline tests",
        human_gate="No gate for private measurement tooling.",
    )


def _lg8_lg9_combined_contract_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K173_LG8_LG9_COMBINED_CONTRACT_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Bind LG8 performance governance and LG9 durable semantics.",
        allowed_files="self-dev docs; scripts/rh-selfdev.py; tests",
        tests="focused next-action recovery tests",
        human_gate="No gate for private planning and recovery tooling.",
    )


def _lg8_next_action_hot_path_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K174_NEXT_ACTION_HOT_PATH_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Optimize private self-dev next-action recovery hot path.",
        allowed_files="scripts; tests; self-dev docs",
        tests="focused next-action and baseline tests",
        human_gate="No gate for private helper optimization.",
    )


def _lg8_runtime_event_append_hot_path_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K175_RUNTIME_EVENT_APPEND_HOT_PATH_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Optimize private runtime event append temp-DB measurement.",
        allowed_files="scripts/rh-perf-baseline.py; tests; self-dev docs",
        tests="focused private performance baseline tests",
        human_gate="No gate for private measurement-runner optimization.",
    )


def _lg8_next_action_command_hot_path_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K176_NEXT_ACTION_COMMAND_HOT_PATH_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Optimize private self-dev next-action command hot path.",
        allowed_files="scripts; tests; self-dev docs",
        tests="focused next-action command tests",
        human_gate="No gate for private helper optimization.",
    )


def _lg9_durable_contract_matrix_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K177_LG9_DURABLE_CONTRACT_MATRIX_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Create the private LG9 durable contract matrix.",
        allowed_files="scripts/rh-selfdev.py; self-dev docs; tests",
        tests="focused LG9 contract matrix tests",
        human_gate="No gate for private docs/tests/helper contract matrix.",
    )


def _lg9_provenance_artifact_contract_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K178_LG9_PROVENANCE_ARTIFACT_CONTRACT_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Create the private provenance/artifact linkage contract.",
        allowed_files="scripts; tests; self-dev docs",
        tests="focused provenance/artifact contract tests",
        human_gate="No gate for private docs/tests/helper contract.",
    )


def _lg9_orchestrator_readonly_contract_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K179_LG9_ORCHESTRATOR_READONLY_CONTRACT_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Create the private orchestrator read-only mapping contract.",
        allowed_files="scripts; tests; self-dev docs",
        tests="focused orchestrator read-only contract tests",
        human_gate="No gate for private docs/tests/helper contract.",
    )


def _lg8_lg9_private_closeout_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K180_LG8_LG9_PRIVATE_CLOSEOUT_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Close out the private LG8/LG9 program.",
        allowed_files="scripts; tests; self-dev docs",
        tests="focused closeout guard tests",
        human_gate="No gate for private docs/tests/helper closeout.",
    )


def _lg10_public_productization_boundary_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K181_LG10_PUBLIC_PRODUCTIZATION_BOUNDARY_ID,
        phase="P8",
        status=status,
        risk="low",
        parallel="no",
        objective="Define the LG10 public-productization gate boundary.",
        allowed_files="scripts; tests; self-dev docs",
        tests="focused LG10 boundary tests",
        human_gate="No gate for private boundary documentation.",
    )


def _lg10_boundary_preview_batch_gate_slice(module, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=K182_LG10_BOUNDARY_PREVIEW_BATCH_GATE_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Approve the LG10 boundary-preview public-surface batch.",
        allowed_files="self-dev gate docs",
        tests="git diff --check",
        human_gate="Direct user instruction approved long-goal continuation.",
    )


def _lg10_cli_boundary_preview_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K183_LG10_CLI_BOUNDARY_PREVIEW_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Expose the LG10 boundary through an opt-in CLI preview.",
        allowed_files="CLI files; tests; self-dev docs",
        tests="focused CLI boundary preview tests",
        human_gate="Covered by K182.",
    )


def _lg10_mcp_boundary_preview_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K184_LG10_MCP_BOUNDARY_PREVIEW_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Expose the LG10 boundary through an opt-in MCP preview.",
        allowed_files="MCP files; tests; self-dev docs",
        tests="focused MCP boundary preview tests",
        human_gate="Covered by K182.",
    )


def _lg10_http_preview_gate_slice(module, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=K185_LG10_HTTP_PREVIEW_GATE_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Approve the LG10 HTTP boundary-preview public surface.",
        allowed_files="self-dev gate docs",
        tests="focused self-dev recovery tests",
        human_gate="Direct user goal continuation approved HTTP preview.",
    )


def _lg10_http_boundary_preview_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K186_LG10_HTTP_BOUNDARY_PREVIEW_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Expose the LG10 boundary through an opt-in HTTP preview.",
        allowed_files="HTTP files; tests; self-dev docs",
        tests="focused HTTP boundary preview tests",
        human_gate="Covered by K185.",
    )


def _lg10_python_facade_preview_gate_slice(module, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=K187_LG10_PYTHON_FACADE_PREVIEW_GATE_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Approve the LG10 Python facade boundary-preview public surface.",
        allowed_files="self-dev gate docs",
        tests="focused self-dev recovery tests",
        human_gate="Direct user goal continuation approved Python facade preview.",
    )


def _lg10_python_facade_boundary_preview_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K188_LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Expose the LG10 boundary through an opt-in Python facade preview.",
        allowed_files="Python facade files; tests; self-dev docs",
        tests="focused Python facade boundary preview tests",
        human_gate="Covered by K187.",
    )


def _lg10_skills_docs_preview_gate_slice(module, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=K189_LG10_SKILLS_DOCS_PREVIEW_GATE_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Approve the LG10 skills/docs boundary-preview public surface.",
        allowed_files="self-dev gate docs",
        tests="focused self-dev recovery tests",
        human_gate="Direct user goal continuation approved skills/docs preview.",
    )


def _lg10_skills_docs_boundary_preview_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K190_LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Expose the LG10 boundary through an opt-in skills/docs preview.",
        allowed_files="skills/docs files; tests; self-dev docs",
        tests="focused skills/docs boundary preview tests",
        human_gate="Covered by K189.",
    )


def _lg10_doctor_preview_gate_slice(module, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=K191_LG10_DOCTOR_PREVIEW_GATE_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Approve the LG10 doctor boundary-preview public surface.",
        allowed_files="self-dev gate docs",
        tests="focused self-dev recovery tests",
        human_gate="Direct user goal continuation approved doctor preview.",
    )


def _lg10_doctor_boundary_preview_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K192_LG10_DOCTOR_BOUNDARY_PREVIEW_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Expose the LG10 boundary through an opt-in doctor preview.",
        allowed_files="doctor files; tests; self-dev docs",
        tests="focused doctor boundary preview tests",
        human_gate="Covered by K191.",
    )


def _lg10_showcase_preview_gate_slice(module, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=K193_LG10_SHOWCASE_PREVIEW_GATE_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Approve the LG10 showcase boundary-preview public surface.",
        allowed_files="self-dev gate docs",
        tests="focused self-dev recovery tests",
        human_gate="Direct user goal continuation approved showcase preview.",
    )


def _lg10_showcase_boundary_preview_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=K194_LG10_SHOWCASE_BOUNDARY_PREVIEW_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Expose the LG10 boundary through an opt-in showcase preview.",
        allowed_files="showcase files; tests; self-dev docs",
        tests="focused showcase boundary preview tests",
        human_gate="Covered by K193.",
    )


def _post_lg10_mainline_closeout_slice(module, status: str = "todo"):
    return module.SelfDevSlice(
        slice_id=POST_LG10_MAINLINE_CLOSEOUT_ID,
        phase="P8",
        status=status,
        risk="medium",
        parallel="no",
        objective="Close out the post-LG10 mainline acceptance evidence.",
        allowed_files="self-dev docs; scripts/rh-selfdev.py; focused tests",
        tests="focused mainline closeout tests",
        human_gate="No gate for closeout evidence and recovery metadata only.",
    )


def _non_benchmark_stabilization_slice(module, slice_id: str, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=slice_id,
        phase="P11",
        status=status,
        risk="medium",
        parallel="no",
        objective=f"Complete {slice_id}.",
        allowed_files="self-dev docs; focused tests",
        tests="focused stabilization tests",
        human_gate="Covered by direct user non-benchmark stabilization request.",
    )


def _local_autonomy_goal1_slice(module, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=G01_LOCAL_AUTONOMY_CONTROL_PLANE_ID,
        phase="P12",
        status=status,
        risk="high",
        parallel="no",
        objective="Record local autonomy control-plane policy.",
        allowed_files="self-dev docs; scripts/rh-selfdev.py; focused tests",
        tests="focused local autonomy tests",
        human_gate="Covered by direct user local autonomy authorization.",
    )


def _local_autonomy_goal2_slice(module, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=G02_DURABLE_SEMANTICS_LOCAL_IMPLEMENTATION_ID,
        phase="P12",
        status=status,
        risk="high",
        parallel="no",
        objective="Implement executable local durable semantics guards.",
        allowed_files="runtime files; self-dev docs; focused tests",
        tests="focused durable semantics tests",
        human_gate="Covered by direct user local autonomy authorization.",
    )


def _local_autonomy_goal3_slice(module, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=G03_PRODUCTIZATION_ZOTERO_LOCAL_PRODUCTIZATION_ID,
        phase="P12",
        status=status,
        risk="high",
        parallel="no",
        objective="Stabilize productization and Zotero local productization.",
        allowed_files="productization/Zotero files; self-dev docs; focused tests",
        tests="focused productization/Zotero tests",
        human_gate="Covered by direct user local autonomy authorization.",
    )


def _local_autonomy_goal4_slice(module, status: str = "done"):
    return module.SelfDevSlice(
        slice_id=G04_PRIVATE_BENCHMARK_PERFORMANCE_GOVERNANCE_ID,
        phase="P12",
        status=status,
        risk="high",
        parallel="no",
        objective="Stabilize private benchmark/performance governance.",
        allowed_files="private perf docs; self-dev docs; focused tests",
        tests="focused private performance governance tests",
        human_gate="Covered by direct user local autonomy authorization.",
    )


def _lg8_lg9_recovered_slices_through_k177(module) -> list:
    return [
        _long_goal_activation_slice(module, "done"),
        _lg8_private_performance_baseline_slice(module, "done"),
        _lg8_lg9_combined_contract_slice(module, "done"),
        _lg8_next_action_hot_path_slice(module, "done"),
        _lg8_runtime_event_append_hot_path_slice(module, "done"),
        _lg8_next_action_command_hot_path_slice(module, "done"),
        _lg9_durable_contract_matrix_slice(module, "done"),
    ]


def _lg8_lg9_recovered_slices_through_k178(module) -> list:
    return [
        *_lg8_lg9_recovered_slices_through_k177(module),
        _lg9_provenance_artifact_contract_slice(module, "done"),
    ]


def _lg8_lg9_recovered_slices_through_k179(module) -> list:
    return [
        *_lg8_lg9_recovered_slices_through_k178(module),
        _lg9_orchestrator_readonly_contract_slice(module, "done"),
    ]


def _lg8_lg9_recovered_slices_through_k180(module) -> list:
    return [
        *_lg8_lg9_recovered_slices_through_k179(module),
        _lg8_lg9_private_closeout_slice(module, "done"),
    ]


def _lg10_recovered_slices_through_k181(module) -> list:
    return [
        *_lg8_lg9_recovered_slices_through_k180(module),
        _lg10_public_productization_boundary_slice(module, "done"),
    ]


def test_selfdev_verification_matrix_uses_argv_commands() -> None:
    module = load_script_module()

    matrix = module._selfdev_verification_matrix()
    by_id = {entry["id"]: entry for entry in matrix}

    assert by_id["selfdev-normalizer"]["argv"] == (
        ".venv/bin/python",
        "-m",
        "pytest",
        "packages/research_harness/tests/test_rh_selfdev_script.py",
        "packages/research_harness/tests/test_runtime_event_normalizer.py",
        "-q",
    )
    assert by_id["runtime-event-store"]["argv"] == (
        ".venv/bin/python",
        "-m",
        "pytest",
        "packages/research_harness/tests/test_runtime_event_store_contract.py",
        "packages/research_harness/tests/test_runtime_event_store_readback.py",
        "packages/research_harness/tests/test_runtime_event_store_writer.py",
        "-q",
    )
    assert by_id["public-surface-guards"]["argv"] == (
        ".venv/bin/python",
        "-m",
        "pytest",
        "packages/research_harness/tests/test_runtime_event_store_public_surface_guard.py",
        "packages/research_harness/tests/test_mcp_public_surface_guard.py",
        "-q",
    )
    assert by_id["diff-check"]["argv"] == ("git", "diff", "--check")
    assert all(isinstance(entry["argv"], tuple) for entry in matrix)
    assert all("command" not in entry for entry in matrix)


def test_verification_matrix_command_prints_json_argv(capsys) -> None:
    module = load_script_module()

    result = module.main(["verification-matrix", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["matrix_id"] == "runtime-event-selfdev-closeout"
    assert payload["scope"] == "private-rh-selfdev"
    assert payload["public_surface"] == "unchanged"
    assert payload["commands"][0]["argv"] == [
        ".venv/bin/python",
        "-m",
        "pytest",
        "packages/research_harness/tests/test_rh_selfdev_script.py",
        "packages/research_harness/tests/test_runtime_event_normalizer.py",
        "-q",
    ]
    assert all(isinstance(entry["argv"], list) for entry in payload["commands"])
    assert "shell" not in json.dumps(payload).lower()


def test_lg9_durable_contract_matrix_covers_private_contracts() -> None:
    module = load_script_module()

    payload = module._lg9_durable_contract_matrix_payload()
    by_id = {entry["id"]: entry for entry in payload["contracts"]}

    assert payload["matrix_id"] == "lg9-runtime-durable-semantics"
    assert payload["scope"] == "private-rh-selfdev"
    assert payload["public_surface"] == "unchanged"
    assert {
        "runtime-event",
        "job-ledger",
        "tool-boundary",
        "doctor-showcase",
        "provenance-artifact-linkage",
        "orchestrator-read-only-mapping",
    } <= set(by_id)
    assert all(
        entry["migration_status"] == "not_authorized" for entry in payload["contracts"]
    )
    assert all(
        "storage schema" in entry["stop_before"] for entry in payload["contracts"]
    )
    assert by_id["runtime-event"]["evidence_state"] == "tested"
    assert by_id["orchestrator-read-only-mapping"]["evidence_state"] == "docs-only"


def test_lg9_contract_matrix_command_prints_json(capsys) -> None:
    module = load_script_module()

    result = module.main(["lg9-contract-matrix", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["matrix_id"] == "lg9-runtime-durable-semantics"
    assert payload["public_surface"] == "unchanged"
    assert len(payload["contracts"]) == 6
    assert "migration" in json.dumps(payload)


def test_lg9_provenance_artifact_contract_payload_is_gate_bound() -> None:
    module = load_script_module()

    payload = module._lg9_provenance_artifact_contract_payload()
    by_id = {entry["id"]: entry for entry in payload["contract_nodes"]}

    assert payload["contract_id"] == "lg9-provenance-artifact-linkage"
    assert payload["scope"] == "private-rh-selfdev"
    assert payload["public_surface"] == "unchanged"
    assert {
        "artifact-identity",
        "source-hash",
        "provenance-owner",
        "lineage-edge",
    } <= set(by_id)
    assert all(
        entry["implementation_status"] == "contract_only"
        for entry in payload["contract_nodes"]
    )
    assert "storage schema" in payload["stop_before"]
    assert "artifact lineage" in payload["stop_before"]
    assert "public surface" in payload["stop_before"]


def test_lg9_provenance_artifact_contract_command_prints_json(capsys) -> None:
    module = load_script_module()

    result = module.main(["lg9-provenance-artifact-contract", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["contract_id"] == "lg9-provenance-artifact-linkage"
    assert len(payload["contract_nodes"]) == 4
    assert "mutation" in json.dumps(payload)


def test_lg9_orchestrator_readonly_contract_payload_is_gate_bound() -> None:
    module = load_script_module()

    payload = module._lg9_orchestrator_readonly_contract_payload()
    by_id = {entry["id"]: entry for entry in payload["contract_nodes"]}

    assert payload["contract_id"] == "lg9-orchestrator-readonly-mapping"
    assert payload["scope"] == "private-rh-selfdev"
    assert payload["public_surface"] == "unchanged"
    assert {
        "gate-state",
        "transition-map",
        "rollback-boundary",
        "stage-read-model",
    } <= set(by_id)
    assert all(
        entry["implementation_status"] == "contract_only"
        for entry in payload["contract_nodes"]
    )
    assert "orchestrator gate" in payload["stop_before"]
    assert "rollback" in payload["stop_before"]
    assert "public surface" in payload["stop_before"]


def test_lg9_orchestrator_readonly_contract_command_prints_json(capsys) -> None:
    module = load_script_module()

    result = module.main(["lg9-orchestrator-readonly-contract", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["contract_id"] == "lg9-orchestrator-readonly-mapping"
    assert len(payload["contract_nodes"]) == 4
    assert "transition" in json.dumps(payload)


def test_lg9_contract_guard_productization_payload_is_internal_only() -> None:
    module = load_script_module()

    payload = module._lg9_contract_guard_productization_payload()
    guards_by_id = {entry["id"]: entry for entry in payload["guards"]}

    assert payload["guard_id"] == "lg9-contract-guard-productization"
    assert payload["scope"] == "private-rh-selfdev"
    assert payload["public_surface"] == "unchanged"
    assert payload["storage_semantics"] == "unchanged"
    assert payload["provenance_ownership"] == "unchanged"
    assert payload["artifact_lineage_behavior"] == "unchanged"
    assert payload["orchestrator_behavior"] == "unchanged"
    assert payload["status"] == "stable_local_executable_guards"
    assert payload["schema_migration_required"] is False
    assert {
        "durable-contract-matrix",
        "provenance-artifact-linkage",
        "orchestrator-readonly-mapping",
    } <= set(guards_by_id)
    assert all(
        entry["mutation_policy"] == "not_authorized" for entry in payload["guards"]
    )
    assert guards_by_id["durable-contract-matrix"]["classification"] == (
        "stable_internal_guard"
    )
    assert guards_by_id["orchestrator-readonly-mapping"]["classification"] == (
        "stable_internal_read_model_guard"
    )
    assert "storage schema" in payload["stop_before"]
    assert "orchestrator gate" in payload["stop_before"]


def test_lg9_contract_guard_productization_command_prints_json(capsys) -> None:
    module = load_script_module()

    result = module.main(["lg9-contract-guards", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["guard_id"] == "lg9-contract-guard-productization"
    assert payload["status"] == "stable_local_executable_guards"
    assert len(payload["guards"]) == 3
    assert "not_authorized" in json.dumps(payload)


def test_durable_semantics_command_prints_executable_local_checks(capsys) -> None:
    module = load_script_module()

    result = module.main(["durable-semantics", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["slice_id"] == G02_DURABLE_SEMANTICS_LOCAL_IMPLEMENTATION_ID
    assert payload["status"] == "stable_local_executable_guards"
    assert payload["schema_migration_required"] is False
    assert payload["public_surface"] == "unchanged"
    assert payload["provenance_ownership"] == "unchanged"
    assert payload["orchestrator_behavior"] == "unchanged"
    assert {
        "runtime-events-append-only",
        "project-artifact-lineage-columns",
        "artifact-dependency-unique-edge",
        "orchestrator-run-read-model-columns",
        "orchestrator-stage-event-read-model-columns",
    } <= {entry["check_id"] for entry in payload["checks"]}


def test_productization_zotero_local_command_prints_stable_local_status(
    capsys,
) -> None:
    module = load_script_module()

    result = module.main(["productization-zotero-local", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["component_id"] == "productization-zotero-local-productization"
    assert payload["slice_id"] == G03_PRODUCTIZATION_ZOTERO_LOCAL_PRODUCTIZATION_ID
    assert payload["status"] == "stable_local_productization_components"
    assert payload["public_payload_shapes"] == "preserved"
    assert payload["zotero"]["classification"] == (
        "stable_local_dry_run_validation_component"
    )
    assert payload["zotero"]["dry_run_required"] is True
    assert "real_zotero_sync_apply" in payload["zotero"]["deferred_paths"]


def _require_private_performance_reports() -> None:
    """Skip when the developer-local perf baseline reports are absent.

    ``scripts/rh-perf-baseline.py`` writes private timing evidence to
    ``.rh-selfdev/rh-performance-baseline-*.json``; those files are never
    committed, so clean checkouts (CI) cannot reach the stable status.
    """
    if not any((REPO_ROOT / ".rh-selfdev").glob("rh-performance-baseline-*.json")):
        pytest.skip("private rh-performance-baseline reports not present")


def test_private_performance_governance_payload_is_private_no_claim() -> None:
    _require_private_performance_reports()
    module = load_script_module()

    payload = module._private_performance_governance_payload()

    assert payload["governance_id"] == "private-benchmark-performance-governance"
    assert payload["slice_id"] == G04_PRIVATE_BENCHMARK_PERFORMANCE_GOVERNANCE_ID
    assert payload["status"] == "stable_private_performance_governance"
    assert payload["claim_policy"] == "no_benchmark_or_public_performance_claim"
    assert payload["public_claim_status"] == "not_approved"
    assert payload["benchmark_promotion_status"] == "not_approved"
    assert payload["scorer_semantics_changed"] is False
    assert payload["rh_are_boundary_changed"] is False
    assert payload["report_count"] >= 1
    assert payload["latest_report"]["overall_status"] == "ok"
    assert payload["latest_report"]["private_scope"] is True
    assert payload["latest_report"]["failure_count"] == 0
    assert len(payload["hot_path_evidence"]) == 3
    assert "public_benchmark_claims" in payload["deferred"]


def test_private_performance_governance_without_reports_needs_attention() -> None:
    module = load_script_module()
    module._private_performance_report_summaries = lambda: []

    payload = module._private_performance_governance_payload()

    assert payload["status"] == "private_performance_governance_needs_attention"
    assert payload["report_count"] == 0
    assert payload["public_claim_status"] == "not_approved"
    assert payload["benchmark_promotion_status"] == "not_approved"


def test_private_performance_governance_command_prints_json(capsys) -> None:
    _require_private_performance_reports()
    module = load_script_module()

    result = module.main(["private-performance-governance", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["status"] == "stable_private_performance_governance"
    assert payload["public_claim_status"] == "not_approved"
    assert payload["benchmark_promotion_status"] == "not_approved"
    assert payload["latest_report"]["failure_count"] == 0


def test_lg8_lg9_private_closeout_guard_payload_is_complete() -> None:
    module = load_script_module()

    payload = module._lg8_lg9_private_closeout_payload()

    assert payload["report_id"] == "lg8-lg9-private-closeout"
    assert payload["completion_state"] == "combined_private_complete"
    assert payload["public_surface"] == "unchanged"
    assert payload["lg10_status"] == "gate_bound"
    assert payload["claim_policy"] == "no_public_performance_or_benchmark_claim"
    assert len(payload["lg8_hot_path_evidence"]) == 3
    assert len(payload["lg9_contract_evidence"]) == 3
    assert all(
        entry["private_scope"] is True for entry in payload["lg8_hot_path_evidence"]
    )
    assert all(
        entry["implementation_status"] in {"tested", "contract_only"}
        for entry in payload["lg9_contract_evidence"]
    )


def test_lg8_lg9_private_closeout_guard_command_prints_json(capsys) -> None:
    module = load_script_module()

    result = module.main(["lg8-lg9-closeout", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["report_id"] == "lg8-lg9-private-closeout"
    assert payload["completion_state"] == "combined_private_complete"
    assert "gate_bound" in json.dumps(payload)


def test_lg10_public_productization_boundary_payload_is_gate_bound() -> None:
    module = load_script_module()

    payload = module._lg10_public_productization_boundary_payload()

    assert payload["boundary_id"] == "lg10-public-productization-boundary"
    assert payload["scope"] == "private-rh-selfdev-gate-plan"
    assert payload["slice_id"] == K181_LG10_PUBLIC_PRODUCTIZATION_BOUNDARY_ID
    assert payload["lg8_lg9_prerequisite"] == "complete"
    assert payload["lg10_status"] == "gate_bound"
    assert payload["allowed_future_pattern"] == "one_public_surface_per_gate_slice"
    assert payload["public_surfaces"] == [
        "CLI",
        "MCP",
        "HTTP",
        "Python facade",
        "Zotero",
        "doctor",
        "showcase",
        "skills/docs",
    ]
    assert payload["required_pre_implementation_evidence"] == [
        "shape-lock tests",
        "opt-in default",
        "compatibility proof",
        "docs claim review",
        "rollback/fallback plan",
    ]
    assert payload["risk_flags"] == {
        "public_surface_changed": False,
        "storage_or_provenance_changed": False,
        "orchestrator_gate_changed": False,
        "benchmark_claim_changed": False,
        "dependency_changed": False,
    }


def test_lg10_public_productization_boundary_stop_before_covers_large_risks():
    module = load_script_module()

    payload = module._lg10_public_productization_boundary_payload()

    assert payload["stop_before"] == [
        "public surface changes",
        "storage/provenance semantic changes",
        "artifact lineage changes",
        "orchestrator gate/transition/rollback behavior",
        "benchmark or public performance claims",
        "dependency changes",
        "external actions",
        "credential/config mutation",
        "local/private data exposure",
        "compatibility-name removal",
        "Zotero/HTTP/MCP/RH/ARE scope changes",
        "commits",
        "pushes",
        "PRs",
        "releases",
        "publishing",
    ]


def test_lg10_public_productization_boundary_command_prints_json(capsys) -> None:
    module = load_script_module()

    result = module.main(["lg10-productization-boundary", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["boundary_id"] == "lg10-public-productization-boundary"
    assert payload["lg10_status"] == "gate_bound"
    assert "one_public_surface_per_gate_slice" in json.dumps(payload)


def test_selfdev_fast_batch_allows_low_risk_internal_subtasks() -> None:
    module = load_script_module()
    subtasks = [
        {
            "slice_id": "K201_SELFDEV_DOCS_REFRESH",
            "risk": "low",
            "category": "docs",
            "allowed_files": [".rh-selfdev/control-plane.md"],
            "focused_tests": [{"id": "diff-check", "argv": ("git", "diff", "--check")}],
        },
        {
            "slice_id": "K202_SELFDEV_PRIVATE_HELPER_TESTS",
            "risk": "low",
            "category": "private-helper",
            "allowed_files": [
                "scripts/rh-selfdev.py",
                "packages/research_harness/tests/test_rh_selfdev_script.py",
            ],
            "focused_tests": [
                {
                    "id": "selfdev-script",
                    "argv": (
                        ".venv/bin/python",
                        "-m",
                        "pytest",
                        "packages/research_harness/tests/test_rh_selfdev_script.py",
                        "-q",
                    ),
                }
            ],
        },
        {
            "slice_id": "K203_SELFDEV_TEST_ONLY_GUARD",
            "risk": "low",
            "category": "tests",
            "allowed_files": [
                "packages/research_harness/tests/test_rh_selfdev_script.py"
            ],
            "focused_tests": [
                {
                    "id": "selfdev-script",
                    "argv": (
                        ".venv/bin/python",
                        "-m",
                        "pytest",
                        "packages/research_harness/tests/test_rh_selfdev_script.py",
                        "-q",
                    ),
                }
            ],
        },
    ]

    summary = module._selfdev_fast_batch_summary(
        batch_slice_id=K164_BATCH_RUNNER_HELPERS_ID,
        subtasks=subtasks,
    )

    assert [task["slice_id"] for task in summary["subtasks"]] == [
        "K201_SELFDEV_DOCS_REFRESH",
        "K202_SELFDEV_PRIVATE_HELPER_TESTS",
        "K203_SELFDEV_TEST_ONLY_GUARD",
    ]
    assert summary["rejected_subtasks"] == []
    assert summary["batch_size"]["default"] == 6
    assert summary["batch_size"]["max"] == 8


def test_selfdev_fast_batch_rejects_large_risk_subtasks() -> None:
    module = load_script_module()
    subtasks = [
        {
            "slice_id": "K301_SELFDEV_PUBLIC_SURFACE",
            "risk": "low",
            "category": "public-surface",
            "allowed_files": [
                "packages/research_harness_mcp/research_harness_mcp/tools.py"
            ],
            "focused_tests": [],
        },
        {
            "slice_id": "K302_SELFDEV_STORAGE_CHANGE",
            "risk": "low",
            "category": "storage",
            "allowed_files": [
                "packages/research_harness/research_harness/_core/storage/db.py"
            ],
            "focused_tests": [],
        },
        {
            "slice_id": "K303_SELFDEV_PROVENANCE_CHANGE",
            "risk": "low",
            "category": "provenance",
            "allowed_files": [
                "packages/research_harness/research_harness/provenance/export.py"
            ],
            "focused_tests": [],
        },
        {
            "slice_id": "K304_SELFDEV_ORCHESTRATOR_GATE",
            "risk": "low",
            "category": "orchestrator",
            "allowed_files": [
                "packages/research_harness/research_harness/orchestrator/gates.py"
            ],
            "focused_tests": [],
        },
        {
            "slice_id": "K305_SELFDEV_BENCHMARK_PROMOTION",
            "risk": "low",
            "category": "benchmark",
            "allowed_files": [".rh-selfdev/benchmark-promotion.md"],
            "focused_tests": [],
        },
        {
            "slice_id": "K306_SELFDEV_DEPENDENCY",
            "risk": "low",
            "category": "dependency",
            "allowed_files": ["pyproject.toml"],
            "focused_tests": [],
        },
        {
            "slice_id": "K307_SELFDEV_HIGH_RISK_DOC",
            "risk": "high",
            "category": "docs",
            "allowed_files": [".rh-selfdev/control-plane.md"],
            "focused_tests": [],
        },
    ]

    summary = module._selfdev_fast_batch_summary(
        batch_slice_id=K164_BATCH_RUNNER_HELPERS_ID,
        subtasks=subtasks,
    )

    assert summary["subtasks"] == []
    rejected_by_id = {
        task["slice_id"]: task["rejection_reason"]
        for task in summary["rejected_subtasks"]
    }
    assert (
        "forbidden category: public-surface"
        in rejected_by_id["K301_SELFDEV_PUBLIC_SURFACE"]
    )
    assert (
        "storage_or_provenance_changed" in rejected_by_id["K302_SELFDEV_STORAGE_CHANGE"]
    )
    assert (
        "storage_or_provenance_changed"
        in rejected_by_id["K303_SELFDEV_PROVENANCE_CHANGE"]
    )
    assert (
        "orchestrator_gate_changed" in rejected_by_id["K304_SELFDEV_ORCHESTRATOR_GATE"]
    )
    assert (
        "forbidden category: benchmark"
        in rejected_by_id["K305_SELFDEV_BENCHMARK_PROMOTION"]
    )
    assert "forbidden category: dependency" in rejected_by_id["K306_SELFDEV_DEPENDENCY"]
    assert "risk is high" in rejected_by_id["K307_SELFDEV_HIGH_RISK_DOC"]


def test_selfdev_fast_batch_keeps_explicit_empty_batch_empty() -> None:
    module = load_script_module()

    summary = module._selfdev_fast_batch_summary(
        batch_slice_id=K164_BATCH_RUNNER_HELPERS_ID,
        subtasks=[],
    )

    assert summary["subtasks"] == []
    assert summary["rejected_subtasks"] == []
    assert summary["batch_size"]["actual"] == 0


def test_batch_summary_command_prints_json_argv(capsys) -> None:
    module = load_script_module()

    result = module.main(["batch-summary", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["batch_slice_id"] == K164_BATCH_RUNNER_HELPERS_ID
    assert payload["protocol_slice_id"] == K163_FAST_BATCH_LANE_PROTOCOL_ID
    assert payload["subtasks"]
    assert payload["final_matrix_commands"]
    assert all(
        isinstance(test["argv"], list)
        for task in payload["subtasks"]
        for test in task["focused_tests"]
    )
    assert all(
        isinstance(command["argv"], list)
        for command in payload["final_matrix_commands"]
    )
    serialized = json.dumps(payload).lower()
    assert '"shell"' not in serialized
    assert '"command"' not in serialized


def test_closeout_objective_matrix_tracks_two_goal_tracks() -> None:
    module = load_script_module()

    payload = module._selfdev_closeout_matrix_payload()

    assert payload["matrix_id"] == "selfdev-runtime-shell-closeout"
    assert payload["scope"] == "private-rh-selfdev"
    assert payload["public_surface"] == "unchanged"
    assert payload["completion_state"] == "internal-closeout-complete"
    assert [track["id"] for track in payload["tracks"]] == [
        "selfdev-internal-automation",
        "runtime-shell-internal-capabilities",
    ]
    by_track = {track["id"]: track for track in payload["tracks"]}
    assert by_track["selfdev-internal-automation"]["target_percent"] == 100
    assert by_track["selfdev-internal-automation"]["current_percent_estimate"] == 100
    assert by_track["runtime-shell-internal-capabilities"]["target_percent"] == 100
    assert (
        by_track["runtime-shell-internal-capabilities"]["current_percent_estimate"]
        == 100
    )
    assert any(
        requirement["id"] == "fast-batch-lane" and requirement["status"] == "complete"
        for requirement in by_track["selfdev-internal-automation"]["requirements"]
    )
    assert any(
        requirement["id"] == "runtime-event-store"
        and requirement["status"] == "complete"
        for requirement in by_track["runtime-shell-internal-capabilities"][
            "requirements"
        ]
    )
    assert all(
        requirement["status"] != "remaining"
        for track in payload["tracks"]
        for requirement in track["requirements"]
    )
    assert payload["next_low_risk_slices"] == []
    assert payload["gate_boundaries"]


def test_closeout_matrix_command_prints_json_argv(capsys) -> None:
    module = load_script_module()

    result = module.main(["closeout-matrix", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["matrix_id"] == "selfdev-runtime-shell-closeout"
    assert payload["next_low_risk_slices"] == []
    assert all(
        isinstance(command["argv"], list)
        for command in payload["verification_commands"]
    )
    serialized = json.dumps(payload).lower()
    assert '"shell"' not in serialized
    assert '"command"' not in serialized


def test_runtime_selfdev_tooling_stable_components_payload_is_internal_only() -> None:
    module = load_script_module()

    payload = module._runtime_selfdev_tooling_stable_components_payload()
    components_by_id = {entry["id"]: entry for entry in payload["components"]}

    assert payload["component_id"] == "runtime-selfdev-tooling-stable-components"
    assert payload["scope"] == "private-rh-selfdev"
    assert payload["slice_id"] == ST07_RUNTIME_SELFDEV_TOOLING_STABLE_COMPONENTS_ID
    assert payload["status"] == "stable_internal_maintenance_tooling"
    assert payload["public_surface"] == "unchanged"
    assert payload["storage_semantics"] == "unchanged"
    assert payload["provenance_ownership"] == "unchanged"
    assert payload["artifact_lineage_behavior"] == "unchanged"
    assert payload["orchestrator_behavior"] == "unchanged"
    assert {
        "checkpoint-handoff-gate-recovery",
        "next-action-status-control-plane",
        "verification-matrix-argv",
        "fast-batch-lane-summary",
        "redaction-invariant-registry",
        "closeout-objective-matrix",
        "runtime-shell-internal-docs",
    } <= set(components_by_id)
    assert all(
        entry["classification"].startswith("stable_internal")
        for entry in payload["components"]
    )
    assert all(
        entry["mutation_policy"] == "not_authorized" for entry in payload["components"]
    )
    assert components_by_id["verification-matrix-argv"]["source_id"] == (
        "runtime-event-selfdev-closeout"
    )
    assert components_by_id["closeout-objective-matrix"]["source_id"] == (
        "selfdev-runtime-shell-closeout"
    )
    assert "public surface" in payload["stop_before"]
    assert "storage schema" in payload["stop_before"]
    assert "real Zotero" in payload["stop_before"]


def test_runtime_selfdev_tooling_stable_components_command_prints_json(
    capsys,
) -> None:
    module = load_script_module()

    result = module.main(["runtime-selfdev-tooling", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["component_id"] == "runtime-selfdev-tooling-stable-components"
    assert payload["status"] == "stable_internal_maintenance_tooling"
    assert len(payload["components"]) == 7
    assert all(
        isinstance(command["argv"], list)
        for command in payload["verification_commands"]
    )
    serialized = json.dumps(payload).lower()
    assert '"shell"' not in serialized
    assert '"command"' not in serialized


def test_non_benchmark_stabilization_closeout_payload_classifies_all_items() -> None:
    module = load_script_module()

    payload = module._non_benchmark_stabilization_closeout_payload()
    by_slice = {entry["slice_id"]: entry for entry in payload["classifications"]}

    assert payload["report_id"] == "rh-non-benchmark-stabilization-closeout-2026-06-11"
    assert payload["scope"] == "private-rh-selfdev-lg11-closeout"
    assert payload["slice_id"] == ST08_NON_BENCHMARK_STABILIZATION_CLOSEOUT_ID
    assert payload["status"] == "complete"
    assert set(by_slice) == set(module.NON_BENCHMARK_STABILIZATION_SLICE_IDS)
    assert (
        by_slice[ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY_ID]["classification"]
        == "stable_internal_component"
    )
    assert (
        by_slice[ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE_ID]["classification"]
        == "stable_local_internal_bridge"
    )
    assert (
        by_slice[ST05_LG9_CONTRACT_GUARD_PRODUCTIZATION_ID]["classification"]
        == "stable_internal_guard"
    )
    assert (
        by_slice[ST06_ZOTERO_SERVICE_DRY_RUN_STABILIZATION_ID]["classification"]
        == "stable_internal_dry_run_validation"
    )
    assert (
        by_slice[ST07_RUNTIME_SELFDEV_TOOLING_STABLE_COMPONENTS_ID]["classification"]
        == "stable_internal_maintenance_tooling"
    )
    assert all(
        entry["decision"] != "preview" and entry["decision"] != "beta"
        for entry in payload["classifications"]
    )
    assert payload["remaining_implementation_slices"] == []
    assert "benchmark scoring" in payload["excluded_work"]
    assert "real Zotero sync/UI/apply" in payload["excluded_work"]
    assert payload["risk_flags"]["benchmark_claim_changed"] is False
    assert payload["risk_flags"]["dependency_changed"] is False


def test_non_benchmark_stabilization_closeout_command_prints_json(capsys) -> None:
    module = load_script_module()

    result = module.main(["non-benchmark-closeout", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["report_id"] == "rh-non-benchmark-stabilization-closeout-2026-06-11"
    assert payload["status"] == "complete"
    assert len(payload["classifications"]) == 8
    assert all(
        isinstance(command["argv"], list)
        for command in payload["verification_commands"]
    )


def test_selfdev_redaction_invariant_registry_covers_event_families() -> None:
    module = load_script_module()

    families = module._selfdev_redaction_invariant_families()

    assert tuple(entry["family"] for entry in families) == (
        "checkpoint",
        "handoff",
        "gate",
        "status",
        "next-action",
        "cloud-command",
        "codex-command",
        "cloud-submit",
    )
    assert all(entry["scope"] == "private-rh-selfdev" for entry in families)
    assert all(entry["redacts_freeform_values"] is True for entry in families)
    assert all("raw_environment_id" in entry["must_not_persist"] for entry in families)
    assert all("prompt_body" in entry["must_not_persist"] for entry in families)


def test_selfdev_redaction_invariant_surfaces_redact_markers(
    tmp_path: Path,
) -> None:
    module = load_script_module()
    slice_def = _redaction_invariant_refresh_slice(module, status="in_progress")
    sensitive = (
        "prompt body PROMPT_SECRET; stdout body STDOUT_SECRET; "
        "stderr body STDERR_SECRET; env_secret_invariant; "
        "sk-invariant-secret; cloud task output CLOUD_OUTPUT_SECRET; "
        "cloud task submitted task_789"
    )
    expected_families = {
        entry["family"] for entry in module._selfdev_redaction_invariant_families()
    }

    surfaces = {
        "checkpoint": module._checkpoint_event_metadata(
            path=tmp_path / "checkpoint.md",
            slices=[slice_def],
            changed_files=["docs/example.md"],
            notes=[sensitive],
        ),
        "handoff": module._handoff_event_metadata(
            path=tmp_path / "handoff.md",
            slice_def=slice_def,
            changed_files=["docs/example.md"],
            notes=[sensitive],
            status="done",
        ),
        "gate": module._gate_report_event_metadata(
            path=tmp_path / "gate.md",
            slice_def=slice_def,
            task_id="task-789",
            changed_files=["docs/example.md"],
            tests=sensitive,
            recommendation="approve",
        ),
        "status": module._status_event_payload(
            action={
                "action": "wait_for_gate",
                "slice_id": K161_REDACTION_INVARIANT_REFRESH_ID,
                "phase": "P6",
                "risk": "low",
                "reason": sensitive,
                "human_gate": sensitive,
            },
            changed_files=["docs/example.md"],
            risk_flags={key: False for key in module.RISK_KEYS},
        ),
        "next-action": module._redacted_selfdev_mapping(
            {
                "action": "wait_for_gate",
                "slice_id": K161_REDACTION_INVARIANT_REFRESH_ID,
                "phase": "P6",
                "risk": "low",
                "reason": sensitive,
                "human_gate": sensitive,
            }
        ),
        "cloud-command": module._cloud_command_event_context(
            slice_def=slice_def,
            command=["codex", "cloud", "exec"],
            environment_id="env_raw_environment",
            branch=f"selfdev/{sensitive}",
            attempts=2,
        ),
        "codex-command": module._codex_command_event_context(
            slice_def=slice_def,
            command=["codex", "exec"],
            worktree_path=tmp_path / "env_secret_worktree",
            prompt_path=tmp_path / "sk-invariant-prompt.md",
            output_path=tmp_path / "stdout body OUTPUT_SECRET.json",
            model=f"gpt-5.4 {sensitive}",
        ),
        "cloud-submit": [
            module._cloud_submit_started_event_context(
                slice_def=slice_def,
                command=["codex", "cloud", "exec"],
                environment_id="env_raw_submit",
                branch=f"submit/{sensitive}",
                attempts=2,
            ),
            module._cloud_submit_event_context(
                slice_def=slice_def,
                command=["codex", "cloud", "exec"],
                environment_id="env_raw_submit",
                branch=f"submit/{sensitive}",
                attempts=2,
                returncode=0,
            ),
        ],
    }

    assert set(surfaces) == expected_families
    surface_json = json.dumps(surfaces, sort_keys=True)
    for marker in (
        "PROMPT_SECRET",
        "STDOUT_SECRET",
        "STDERR_SECRET",
        "env_secret_invariant",
        "sk-invariant-secret",
        "CLOUD_OUTPUT_SECRET",
        "task_789",
        "env_raw_environment",
        "env_raw_submit",
        "env_secret_worktree",
        "sk-invariant-prompt",
        "OUTPUT_SECRET",
    ):
        assert marker not in surface_json
    assert "[redacted]" in surface_json


def test_recent_artifacts_returns_newest_files_by_mtime(tmp_path: Path) -> None:
    module = load_script_module()
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    older_late_name = artifact_dir / "ZOTERO_OLDER.md"
    newest_early_name = artifact_dir / "K140_NEWEST.md"
    middle_early_name = artifact_dir / "K139_MIDDLE.md"
    readme = artifact_dir / "README.md"
    for path in (older_late_name, newest_early_name, middle_early_name, readme):
        path.write_text(path.name, encoding="utf-8")
    os.utime(older_late_name, (100, 100))
    os.utime(middle_early_name, (200, 200))
    os.utime(newest_early_name, (300, 300))
    os.utime(readme, (400, 400))

    recent = module._recent_artifacts(artifact_dir, limit=2)

    assert recent == [str(newest_early_name), str(middle_early_name)]


def test_selfdev_freeform_runtime_event_metadata_redacts_sensitive_markers(
    tmp_path: Path,
) -> None:
    module = load_script_module()
    slice_def = _redaction_guard_slice(module, status="in_progress")
    sensitive_note = (
        "prompt body PROMPT_SECRET; stdout body STDOUT_SECRET; "
        "stderr body STDERR_SECRET; env_secret_123; sk-live-secret; "
        "cloud task output CLOUD_OUTPUT_SECRET; cloud task submitted task_123"
    )
    checkpoint_metadata = module._checkpoint_event_metadata(
        path=tmp_path / "checkpoint.md",
        slices=[slice_def],
        changed_files=["docs/example.md"],
        notes=[sensitive_note],
    )
    handoff_metadata = module._handoff_event_metadata(
        path=tmp_path / "handoff.md",
        slice_def=slice_def,
        changed_files=["docs/example.md"],
        notes=[sensitive_note],
        status="done",
    )
    gate_metadata = module._gate_report_event_metadata(
        path=tmp_path / "gate.md",
        slice_def=slice_def,
        task_id="task-17",
        changed_files=["docs/example.md"],
        tests=sensitive_note,
        recommendation="approve",
    )

    metadata_json = json.dumps(
        [checkpoint_metadata, handoff_metadata, gate_metadata],
        sort_keys=True,
    )

    for marker in (
        "PROMPT_SECRET",
        "STDOUT_SECRET",
        "STDERR_SECRET",
        "env_secret_123",
        "sk-live-secret",
        "CLOUD_OUTPUT_SECRET",
        "task_123",
    ):
        assert marker not in metadata_json
    assert "[redacted]" in metadata_json


def test_selfdev_command_contexts_redact_freeform_values() -> None:
    module = load_script_module()
    slice_def = _redaction_guard_slice(module, status="in_progress")

    cloud_context = module._cloud_command_event_context(
        slice_def=slice_def,
        command=["codex", "cloud", "exec"],
        environment_id="env_actual_secret",
        branch="selfdev/env_secret_123/sk-live-secret",
        attempts=2,
    )
    submit_context = module._cloud_submit_event_context(
        slice_def=slice_def,
        command=["codex", "cloud", "exec"],
        environment_id="env_actual_secret",
        branch="selfdev/env_secret_submit/sk-submit-secret",
        attempts=2,
        returncode=0,
    )
    started_context = module._cloud_submit_started_event_context(
        slice_def=slice_def,
        command=["codex", "cloud", "exec"],
        environment_id="env_actual_secret",
        branch="selfdev/env_secret_started/sk-started-secret",
        attempts=2,
    )
    codex_context = module._codex_command_event_context(
        slice_def=slice_def,
        command=["codex", "exec"],
        worktree_path=Path("/tmp/env_secret_worktree"),
        prompt_path=Path("/tmp/sk-prompt-secret.md"),
        output_path=Path("/tmp/stdout body OUTPUT_SECRET.json"),
        model="gpt-5.4",
    )

    context_json = json.dumps(
        [cloud_context, submit_context, started_context, codex_context],
        sort_keys=True,
    )

    for marker in (
        "env_secret_123",
        "sk-live-secret",
        "env_secret_submit",
        "sk-submit-secret",
        "env_secret_started",
        "sk-started-secret",
        "env_secret_worktree",
        "sk-prompt-secret",
        "OUTPUT_SECRET",
        "env_actual_secret",
    ):
        assert marker not in context_json
    assert "[redacted]" in context_json
    assert cloud_context["environment_id_present"] is True


def test_status_and_next_action_runtime_events_redact_freeform_text(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    action = {
        "action": "wait_for_gate",
        "slice_id": K147_REDACTION_GUARD_ID,
        "phase": "P6",
        "risk": "high",
        "reason": "prompt body PROMPT_SECRET; env_secret_reason; sk-reason-secret",
        "human_gate": "stdout body STDOUT_SECRET; stderr body STDERR_SECRET",
    }
    risk_flags = {
        "benchmark_claim_changed": False,
        "dependency_changed": False,
        "orchestrator_gate_changed": False,
        "public_surface_changed": False,
        "storage_or_provenance_changed": False,
    }

    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    status_result = module._append_status_runtime_event(
        action=action,
        changed_files=[],
        risk_flags=risk_flags,
        created_at="20260610T164000Z",
    )
    next_action_result = module._append_next_action_runtime_event(
        action=action,
        created_at="20260610T164001Z",
    )

    status_event = _read_runtime_event_by_event_id(
        db,
        f"selfdev_status:{K147_REDACTION_GUARD_ID}:20260610T164000Z",
    )
    next_action_event = _read_runtime_event_by_event_id(
        db,
        (
            f"selfdev_next_action:{K147_REDACTION_GUARD_ID}:wait_for_gate:"
            "20260610T164001Z"
        ),
    )

    assert status_result is not None
    assert next_action_result is not None
    assert status_event is not None
    assert next_action_event is not None

    event_json = json.dumps(
        [
            {
                "metadata": status_event.metadata,
                "payload": status_event.record.payload,
            },
            {
                "metadata": next_action_event.metadata,
                "payload": next_action_event.record.payload,
            },
        ],
        sort_keys=True,
    )

    for marker in (
        "PROMPT_SECRET",
        "STDOUT_SECRET",
        "STDERR_SECRET",
        "env_secret_reason",
        "sk-reason-secret",
    ):
        assert marker not in event_json
    assert "[redacted]" in event_json


def test_load_slices_selects_first_todo_slice(tmp_path):
    module = load_script_module()
    slices_file = tmp_path / "slices.md"
    slices_file.write_text(
        """# RH Self-Development Slices

| Slice ID | Phase | Status | Risk | Parallel | Objective | Allowed files | Tests | Human gate |
|---|---|---|---|---|---|---|---|---|
| S00_CONTROL_PLANE | P0 | done | low | no | Establish control plane. | docs | tests | review |
| S01_SURFACE_GUARD | P0 | todo | low | no | Add public surface guard. | scripts | tests | approve |
""",
        encoding="utf-8",
    )

    slices = module.load_slices(slices_file)

    assert slices[0].slice_id == "S00_CONTROL_PLANE"
    assert slices[0].status == "done"
    assert module.select_next_slice(slices).slice_id == "S01_SURFACE_GUARD"


def test_pending_gate_blocks_next_slice(tmp_path):
    module = load_script_module()
    slices_file = tmp_path / "slices.md"
    slices_file.write_text(
        """# RH Self-Development Slices

| Slice ID | Phase | Status | Risk | Parallel | Objective | Allowed files | Tests | Human gate |
|---|---|---|---|---|---|---|---|---|
| S01_SURFACE_GUARD | P0 | gate | low | no | Add public surface guard. | scripts | tests | approve |
| S02_SERVICE_SKELETON | P0 | todo | medium | no | Add service skeleton. | service | tests | approve |
""",
        encoding="utf-8",
    )

    slices = module.load_slices(slices_file)

    assert module.select_pending_gate(slices).slice_id == "S01_SURFACE_GUARD"
    try:
        module.select_next_slice(slices)
    except module.GatePendingError as exc:
        assert "S01_SURFACE_GUARD" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("gate status should block next slice selection")


def test_active_slice_is_selected_before_next_todo():
    module = load_script_module()
    active_slice = module.SelfDevSlice(
        slice_id="S01_ACTIVE",
        phase="P1",
        status="in_progress",
        risk="low",
        parallel="no",
        objective="Active work.",
        allowed_files="docs",
        tests="tests",
        human_gate="review",
    )
    next_slice = module.SelfDevSlice(
        slice_id="S02_NEXT",
        phase="P1",
        status="todo",
        risk="medium",
        parallel="no",
        objective="Next work.",
        allowed_files="service",
        tests="tests",
        human_gate="review",
    )

    assert module.select_active_slice([active_slice, next_slice]) == active_slice
    checkpoint = module.build_checkpoint_text(
        slices=[active_slice, next_slice],
        changed_files=[],
    )
    assert "Active slice: S01_ACTIVE" in checkpoint
    assert "Next slice: S02_NEXT" not in checkpoint


def test_prompt_next_reports_blocked_when_gate_is_pending(monkeypatch, capsys):
    module = load_script_module()
    gate_slice = module.SelfDevSlice(
        slice_id="S01_SURFACE_GUARD",
        phase="P0",
        status="gate",
        risk="low",
        parallel="no",
        objective="Add public surface guard.",
        allowed_files="scripts",
        tests="tests",
        human_gate="approve",
    )
    next_slice = module.SelfDevSlice(
        slice_id="S02_SERVICE_SKELETON",
        phase="P0",
        status="todo",
        risk="medium",
        parallel="no",
        objective="Add service skeleton.",
        allowed_files="service",
        tests="tests",
        human_gate="approve",
    )
    monkeypatch.setattr(module, "load_slices", lambda: [gate_slice, next_slice])

    result = module.main(["prompt", "next"])

    captured = capsys.readouterr()
    assert result == 3
    assert "BLOCKED" in captured.err
    assert "S01_SURFACE_GUARD" in captured.err


def test_worker_prompt_contains_context_and_scope_guards():
    module = load_script_module()
    slice_def = module.SelfDevSlice(
        slice_id="S01_SURFACE_GUARD",
        phase="P0",
        status="todo",
        risk="low",
        parallel="no",
        objective="Add public surface drift guards.",
        allowed_files="scripts/rh-selfdev.py; packages/research_harness/tests/test_rh_selfdev_script.py",
        tests="python3 -m pytest packages/research_harness/tests/test_rh_selfdev_script.py -q",
        human_gate="surface policy",
    )

    prompt = module.build_worker_prompt(slice_def)

    assert "Do not automatically read docs/agent-guide.md" in prompt
    assert "Do not load or invoke RH research workflow skills" in prompt
    assert "Do not rely on chat-only state" in prompt
    assert "S01_SURFACE_GUARD" in prompt
    assert "scripts/rh-selfdev.py" in prompt
    assert "Stop and write a handoff" in prompt


def test_build_codex_exec_command_uses_argv_not_shell():
    module = load_script_module()
    prompt_path = Path(".tmp/rh-selfdev-prompts/S01.md")
    output_path = Path(".rh-selfdev/handoffs/S01.final.md")
    worktree_path = Path("../rh-selfdev-s01")

    command = module.build_codex_exec_command(
        worktree_path=worktree_path,
        prompt_path=prompt_path,
        output_path=output_path,
        model="gpt-5.4",
    )

    assert isinstance(command, list)
    assert command[:2] == ["codex", "exec"]
    assert "-C" in command
    assert str(worktree_path) in command
    assert command[-1] == "-"
    assert "--ask-for-approval" in command
    assert "never" in command
    assert "--sandbox" in command
    assert "workspace-write" in command
    assert all(";" not in part for part in command)


def test_build_cloud_exec_command_uses_explicit_environment_and_branch():
    module = load_script_module()

    command = module.build_cloud_exec_command(
        environment_id="env_123",
        branch="selfdev/s01-surface-guard",
        prompt="Run slice S01_SURFACE_GUARD.",
        attempts=2,
    )

    assert isinstance(command, list)
    assert command[:3] == ["codex", "cloud", "exec"]
    assert "--env" in command
    assert "env_123" in command
    assert "--branch" in command
    assert "selfdev/s01-surface-guard" in command
    assert "--attempts" in command
    assert "2" in command
    assert command[-1] == "Run slice S01_SURFACE_GUARD."
    assert all(";" not in part for part in command)


def test_risk_flags_detect_human_gate_files():
    module = load_script_module()

    flags = module.detect_risk_flags(
        [
            "packages/research_harness/migrations/070_runtime_events.sql",
            "packages/research_harness/research_harness/storage/db.py",
            "packages/research_harness/research_harness/orchestrator/transitions.py",
            "packages/research_harness/pyproject.toml",
            "docs/researchflowbench-results-autoresearchbench-v0.md",
        ]
    )

    assert flags["storage_or_provenance_changed"] is True
    assert flags["orchestrator_gate_changed"] is True
    assert flags["dependency_changed"] is True
    assert flags["benchmark_claim_changed"] is True


def test_invalid_slice_id_is_rejected():
    module = load_script_module()

    assert module.is_valid_slice_id("S01_SURFACE_GUARD")
    assert not module.is_valid_slice_id("../bad")
    assert not module.is_valid_slice_id("S01; rm -rf /")


def test_build_checkpoint_text_records_resume_state_and_risks():
    module = load_script_module()
    slices = [
        module.SelfDevSlice(
            slice_id="S01_DONE",
            phase="P0",
            status="done",
            risk="low",
            parallel="no",
            objective="Completed slice.",
            allowed_files="docs",
            tests="tests",
            human_gate="approved",
        ),
        module.SelfDevSlice(
            slice_id="S02_NEXT",
            phase="P1",
            status="todo",
            risk="medium",
            parallel="no",
            objective="Continue service migration.",
            allowed_files="service files",
            tests="focused tests",
            human_gate="review",
        ),
    ]

    text = module.build_checkpoint_text(
        slices=slices,
        changed_files=[
            "packages/research_harness/research_harness/storage/db.py",
            ".rh-selfdev/slices.md",
        ],
        notes=["main session clear requested"],
    )

    assert "Next slice: S02_NEXT" in text
    assert "Continue service migration." in text
    assert "`storage_or_provenance_changed`: True" in text
    assert "main session clear requested" in text
    assert "Resume Instructions" in text
    assert "Clear/Compact Protocol" in text


def test_next_action_recommends_existing_todo_slice():
    module = load_script_module()
    next_slice = module.SelfDevSlice(
        slice_id="S22_NEXT",
        phase="P3",
        status="todo",
        risk="low",
        parallel="no",
        objective="Continue automation.",
        allowed_files="scripts",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action([next_slice])

    assert action["action"] == "run_slice"
    assert action["slice_id"] == "S22_NEXT"
    assert action["reason"] == "todo slice is available"


def test_next_action_reports_lg16_existing_system_finalization_complete():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="LG16_EXISTING_SYSTEM_FINALIZATION",
        phase="P17",
        status="done",
        risk="high",
        parallel="no",
        objective="Finalize the existing RH system without new public surface.",
        allowed_files="guards and service-backed adapters",
        tests="focused LG16 suite",
        human_gate="Phase B remains separate.",
    )

    action = module.suggest_next_action([completed_slice])

    assert action["action"] == "complete_existing_system_finalization"
    assert action["slice_id"] == "LG16_EXISTING_SYSTEM_FINALIZATION"
    assert "critical-path coverage" in action["reason"]
    assert "Phase B remains separate" in action["human_gate"]


def test_next_action_after_phase_b_http_gate_recommends_zotero_gate():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id="LG16_EXISTING_SYSTEM_FINALIZATION",
            phase="P17",
            status="done",
            risk="high",
            parallel="no",
            objective="Finalize the existing RH system without new public surface.",
            allowed_files="guards and service-backed adapters",
            tests="focused LG16 suite",
            human_gate="Phase B remains separate.",
        ),
        module.SelfDevSlice(
            slice_id="LG17_PHASE_B_PUBLIC_HTTP_GATE",
            phase="P18",
            status="done",
            risk="high",
            parallel="no",
            objective="Require auth for non-loopback HTTP deployment.",
            allowed_files="HTTP auth and release smoke files",
            tests="focused Phase B HTTP tests",
            human_gate="External public deployment remains excluded.",
        ),
    ]

    action = module.suggest_next_action(completed_slices)

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "LG18_PHASE_B_ZOTERO_REAL_SYNC_GATE"
    assert "Zotero" in action["objective"]


def test_next_action_after_phase_b_zotero_gate_recommends_release_gate():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id="LG17_PHASE_B_PUBLIC_HTTP_GATE",
            phase="P18",
            status="done",
            risk="high",
            parallel="no",
            objective="Require auth for non-loopback HTTP deployment.",
            allowed_files="HTTP auth and release smoke files",
            tests="focused Phase B HTTP tests",
            human_gate="External public deployment remains excluded.",
        ),
        module.SelfDevSlice(
            slice_id="LG18_PHASE_B_ZOTERO_REAL_SYNC_GATE",
            phase="P18",
            status="done",
            risk="high",
            parallel="no",
            objective="Validate Zotero fake/sandbox sync/apply evidence.",
            allowed_files="Zotero files",
            tests="focused Zotero tests",
            human_gate="Real Zotero network sync/apply remains excluded.",
        ),
    ]

    action = module.suggest_next_action(completed_slices)

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "LG19_PHASE_B_RELEASE_DEPENDENCY_GATE"
    assert "release/dependency" in action["objective"]


def test_next_action_after_phase_b_release_gate_reports_phase_b_complete():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id="LG17_PHASE_B_PUBLIC_HTTP_GATE",
            phase="P18",
            status="done",
            risk="high",
            parallel="no",
            objective="Require auth for non-loopback HTTP deployment.",
            allowed_files="HTTP auth and release smoke files",
            tests="focused Phase B HTTP tests",
            human_gate="External public deployment remains excluded.",
        ),
        module.SelfDevSlice(
            slice_id="LG18_PHASE_B_ZOTERO_REAL_SYNC_GATE",
            phase="P18",
            status="done",
            risk="high",
            parallel="no",
            objective="Validate Zotero fake/sandbox sync/apply evidence.",
            allowed_files="Zotero files",
            tests="focused Zotero tests",
            human_gate="Real Zotero network sync/apply remains excluded.",
        ),
        module.SelfDevSlice(
            slice_id="LG19_PHASE_B_RELEASE_DEPENDENCY_GATE",
            phase="P18",
            status="done",
            risk="high",
            parallel="no",
            objective="Close release/dependency publication gates locally.",
            allowed_files="release gate files",
            tests="coverage and dependency audit",
            human_gate="Publishing remains excluded.",
        ),
    ]

    action = module.suggest_next_action(completed_slices)

    assert action["action"] == "complete_phase_b_release_gates"
    assert action["slice_id"] == "LG19_PHASE_B_RELEASE_DEPENDENCY_GATE"
    assert "Phase B local gates are complete" in action["reason"]
    assert "real Zotero network sync/apply" in action["human_gate"]


def test_next_action_recommends_template_when_no_todo_remains():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S21_DONE",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed automation.",
        allowed_files="scripts",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice], transport_coverage_exists=False
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S22_LG2_TRANSPORT_READ_INVENTORY"
    assert action["risk"] == "low"
    assert "ResearchService" in action["objective"]
    assert "compact" in action["stop_rules"]


def test_next_action_advances_after_transport_inventory_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S22_DONE",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed transport inventory.",
        allowed_files="docs",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S23_LG2_CLI_READ_ROUTE_TEST_HARNESS"
    assert action["risk"] == "low"
    assert "CLI" in action["objective"]
    assert "test harness" in action["objective"]
    assert "runtime routing" in action["stop_rules"]


def test_next_action_advances_after_cli_shape_harness_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S24_DONE",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed CLI shape tests.",
        allowed_files="tests",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S25_LG2_CLI_TOPIC_READ_SERVICE_ROUTING"
    assert action["risk"] == "medium"
    assert "topic list" in action["objective"]
    assert "topic show" in action["objective"]
    assert "shape tests" in action["tests"]


def test_next_action_advances_after_cli_topic_routing_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S26_DONE",
        phase="P3",
        status="done",
        risk="medium",
        parallel="no",
        objective="Completed CLI topic routing.",
        allowed_files="cli",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S27_LG2_CLI_PAPER_LIST_SERVICE_ROUTING"
    assert action["risk"] == "medium"
    assert "paper list" in action["objective"]
    assert "JSON output shape" in action["objective"]


def test_next_action_advances_after_cli_paper_list_routing_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S28_DONE",
        phase="P3",
        status="done",
        risk="medium",
        parallel="no",
        objective="Completed CLI paper list routing.",
        allowed_files="cli",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S29_LG2_CLI_PROVENANCE_SUMMARY_SERVICE_ROUTING"
    assert action["risk"] == "medium"
    assert "provenance summary" in action["objective"]
    assert "JSON output shape" in action["objective"]


def test_next_action_advances_after_cli_provenance_summary_routing_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S30_DONE",
        phase="P3",
        status="done",
        risk="medium",
        parallel="no",
        objective="Completed CLI provenance summary routing.",
        allowed_files="cli",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S31_LG2_CLI_PROVENANCE_EXPORT_SERVICE_ROUTING"
    assert action["risk"] == "medium"
    assert "provenance export" in action["objective"]
    assert "JSON output shape" in action["objective"]


def test_next_action_advances_after_cli_provenance_export_routing_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S32_DONE",
        phase="P3",
        status="done",
        risk="medium",
        parallel="no",
        objective="Completed CLI provenance export routing.",
        allowed_files="cli",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S33_LG2_CLI_ORCHESTRATOR_READ_SERVICE_ROUTING"
    assert action["risk"] == "high"
    assert "orchestrator status" in action["objective"]
    assert "orchestrator gate-check" in action["objective"]


def test_next_action_advances_after_cli_orchestrator_routing_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S34_DONE",
        phase="P3",
        status="done",
        risk="high",
        parallel="no",
        objective="Completed CLI orchestrator read routing.",
        allowed_files="cli",
        tests="focused tests",
        human_gate="approved",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S35_LG2_PYTHON_ORCHESTRATOR_READ_SERVICE_ROUTING"
    assert action["risk"] == "high"
    assert "Python facade" in action["objective"]
    assert "orchestrator" in action["objective"]


def test_next_action_advances_after_python_orchestrator_routing_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S36_DONE",
        phase="P3",
        status="done",
        risk="high",
        parallel="no",
        objective="Completed Python facade orchestrator read routing.",
        allowed_files="api",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S37_LG2_HTTP_TOPIC_LIST_SERVICE_ROUTING"
    assert action["risk"] == "medium"
    assert "HTTP topic_list" in action["objective"]


def test_next_action_advances_after_http_topic_list_routing_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S38_DONE",
        phase="P3",
        status="done",
        risk="medium",
        parallel="no",
        objective="Completed HTTP topic-list read routing.",
        allowed_files="http",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S39_LG2_HTTP_PROVENANCE_SUMMARY_SERVICE_ROUTING"
    assert action["risk"] == "medium"
    assert "HTTP provenance_summary" in action["objective"]


def test_next_action_advances_after_http_provenance_summary_routing_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S40_DONE",
        phase="P3",
        status="done",
        risk="medium",
        parallel="no",
        objective="Completed HTTP provenance summary routing.",
        allowed_files="http",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=True,
        http_topic_show_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S41_LG2_HTTP_DEFERRED_SHAPE_TEST_HARNESS"
    assert action["risk"] == "low"
    assert "HTTP read-only response-shape tests" in action["objective"]


def test_next_action_advances_after_http_deferred_shape_harness_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S42_LG2_HTTP_DEFERRED_SHAPE_TEST_HARNESS",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed HTTP deferred-shape harness.",
        allowed_files="tests",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=True,
        http_topic_show_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S43_LG2_HTTP_TOPIC_SHOW_SERVICE_ROUTING"
    assert action["risk"] == "medium"
    assert "HTTP topic_show" in action["objective"]
    assert "topic detail response shape" in action["objective"]


def test_next_action_advances_after_http_topic_show_routing_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S44_LG2_HTTP_TOPIC_SHOW_SERVICE_ROUTING",
        phase="P3",
        status="done",
        risk="medium",
        parallel="no",
        objective="Completed HTTP topic detail routing.",
        allowed_files="http",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=True,
        http_deferred_shape_harness_done=True,
        http_topic_show_service_backed=True,
        http_paper_list_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S45_LG2_HTTP_PAPER_LIST_SERVICE_ROUTING"
    assert action["risk"] == "medium"
    assert "HTTP paper_list" in action["objective"]
    assert "pagination" in action["objective"]


def test_next_action_advances_after_http_paper_list_routing_exists():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S46_LG2_HTTP_PAPER_LIST_SERVICE_ROUTING",
        phase="P3",
        status="done",
        risk="medium",
        parallel="no",
        objective="Completed HTTP paper-list routing.",
        allowed_files="http",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=True,
        http_deferred_shape_harness_done=True,
        http_topic_show_service_backed=True,
        http_paper_list_service_backed=True,
        http_orchestrator_gate_check_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S47_LG2_HTTP_ORCHESTRATOR_GATE_CHECK_SERVICE_ROUTING"
    assert action["risk"] == "high"
    assert "HTTP orchestrator_gate_check" in action["objective"]
    assert "gate pass-through" in action["objective"]


def test_next_action_command_prints_json_when_no_todo(monkeypatch, capsys):
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S21_DONE",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed automation.",
        allowed_files="scripts",
        tests="focused tests",
        human_gate="none",
    )
    monkeypatch.setattr(module, "load_slices", lambda: [completed_slice])
    monkeypatch.setattr(module, "TRANSPORT_COVERAGE_PATH", Path("/missing/matrix.md"))

    result = module.main(["next-action", "--json"])

    captured = capsys.readouterr()
    assert result == 0
    assert '"action": "create_slice"' in captured.out
    assert '"slice_id": "S22_LG2_TRANSPORT_READ_INVENTORY"' in captured.out


def test_next_action_command_appends_selfdev_runtime_event(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    completed_slice = module.SelfDevSlice(
        slice_id="S21_DONE",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed automation.",
        allowed_files="scripts",
        tests="focused tests",
        human_gate="none",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [completed_slice])
    monkeypatch.setattr(module, "TRANSPORT_COVERAGE_PATH", Path("/missing/matrix.md"))
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T051954Z")

    result = module.main(["next-action", "--json"])

    captured = capsys.readouterr()
    action = json.loads(captured.out)
    event_id = (
        "selfdev_next_action:S22_LG2_TRANSPORT_READ_INVENTORY:"
        "create_slice:20260610T051954Z"
    )
    stored = _read_runtime_event_by_event_id(db, event_id)
    by_job = _read_runtime_events(db, job_id="S22_LG2_TRANSPORT_READ_INVENTORY")

    assert result == 0
    assert action["slice_id"] == "S22_LG2_TRANSPORT_READ_INVENTORY"
    assert stored is not None
    assert stored.record.event_id == event_id
    assert stored.record.event_type == "selfdev.next_action_reported"
    assert stored.record.created_at == "20260610T051954Z"
    assert stored.record.origin_surface == "self_dev"
    assert stored.record.job_id == "S22_LG2_TRANSPORT_READ_INVENTORY"
    assert stored.record.artifact_refs == (module._display_path(module.SLICES_FILE),)
    assert stored.record.payload == {
        "action": "create_slice",
        "filename": module.SLICES_FILE.name,
        "human_gate": (
            "No gate unless the slice changes public RH surface or runtime behavior."
        ),
        "phase": "P3",
        "reason": "no todo slice remains and transport inventory is missing",
        "risk": "low",
        "slice_id": "S22_LG2_TRANSPORT_READ_INVENTORY",
    }
    assert [event.record.event_id for event in by_job] == [event_id]
    assert stored.metadata == {
        "action": "create_slice",
        "phase": "P3",
        "risk": "low",
        "slice_id": "S22_LG2_TRANSPORT_READ_INVENTORY",
        "slices_path": module._display_path(module.SLICES_FILE),
    }


def test_next_action_runtime_event_metadata_json_is_stable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    completed_slice = module.SelfDevSlice(
        slice_id="S21_DONE",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed automation.",
        allowed_files="scripts",
        tests="focused tests",
        human_gate="none",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [completed_slice])
    monkeypatch.setattr(module, "TRANSPORT_COVERAGE_PATH", Path("/missing/matrix.md"))
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T051955Z")

    result = module.main(["next-action", "--json"])

    capsys.readouterr()
    assert result == 0
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            (
                "selfdev_next_action:S22_LG2_TRANSPORT_READ_INVENTORY:"
                "create_slice:20260610T051955Z",
            ),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["payload_json"] == json.dumps(
        {
            "action": "create_slice",
            "filename": module.SLICES_FILE.name,
            "human_gate": (
                "No gate unless the slice changes public RH surface or runtime behavior."
            ),
            "phase": "P3",
            "reason": "no todo slice remains and transport inventory is missing",
            "risk": "low",
            "slice_id": "S22_LG2_TRANSPORT_READ_INVENTORY",
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert row["metadata_json"] == json.dumps(
        {
            "action": "create_slice",
            "phase": "P3",
            "risk": "low",
            "slice_id": "S22_LG2_TRANSPORT_READ_INVENTORY",
            "slices_path": module._display_path(module.SLICES_FILE),
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_next_action_runtime_event_duplicate_timestamp_is_nonfatal(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    completed_slice = module.SelfDevSlice(
        slice_id="S21_DONE",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed automation.",
        allowed_files="scripts",
        tests="focused tests",
        human_gate="none",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [completed_slice])
    monkeypatch.setattr(module, "TRANSPORT_COVERAGE_PATH", Path("/missing/matrix.md"))
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T051956Z")

    first = module.main(["next-action", "--json"])
    second = module.main(["next-action", "--json"])

    capsys.readouterr()
    assert first == 0
    assert second == 0
    conn = db.connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM runtime_events
            WHERE event_id = ?
            """,
            (
                "selfdev_next_action:S22_LG2_TRANSPORT_READ_INVENTORY:"
                "create_slice:20260610T051956Z",
            ),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


def test_next_action_command_succeeds_when_runtime_event_store_unavailable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S21_DONE",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed automation.",
        allowed_files="scripts",
        tests="focused tests",
        human_gate="none",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(tmp_path / "unmigrated.db"))
    monkeypatch.setattr(module, "load_slices", lambda: [completed_slice])
    monkeypatch.setattr(module, "TRANSPORT_COVERAGE_PATH", Path("/missing/matrix.md"))
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T051957Z")

    result = module.main(["next-action", "--json"])

    captured = capsys.readouterr()
    action = json.loads(captured.out)
    assert result == 0
    assert action["slice_id"] == "S22_LG2_TRANSPORT_READ_INVENTORY"


def test_next_action_can_ignore_external_active_slice():
    module = load_script_module()
    zotero_slice = module.SelfDevSlice(
        slice_id="ZOTERO_WRITE_AGENT_RUNTIME",
        phase="P3",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Zotero runtime is handled by another session.",
        allowed_files="zotero files",
        tests="zotero tests",
        human_gate="zotero gate",
    )
    completed_gate_check = module.SelfDevSlice(
        slice_id="S48_LG2_HTTP_ORCHESTRATOR_GATE_CHECK_SERVICE_ROUTING",
        phase="P3",
        status="done",
        risk="high",
        parallel="no",
        objective="Completed HTTP gate-check routing.",
        allowed_files="http",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_gate_check, zotero_slice],
        ignored_active_slice_ids={"ZOTERO_WRITE_AGENT_RUNTIME"},
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=True,
        http_deferred_shape_harness_done=True,
        http_topic_show_service_backed=True,
        http_paper_list_service_backed=True,
        http_orchestrator_status_service_backed=False,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S49_LG2_HTTP_ORCHESTRATOR_STATUS_SERVICE_ROUTING"
    assert action["risk"] == "high"
    assert "HTTP orchestrator_status" in action["objective"]


def test_next_action_can_ignore_external_gate_slice():
    module = load_script_module()
    zotero_slice = module.SelfDevSlice(
        slice_id="ZOTERO_WRITE_AGENT_RUNTIME",
        phase="P3",
        status="gate",
        risk="high",
        parallel="no",
        objective="Zotero runtime is handled by another session.",
        allowed_files="zotero files",
        tests="zotero tests",
        human_gate="zotero gate",
    )
    completed_audit = module.SelfDevSlice(
        slice_id="S51_ARCHITECTURE_COMPLETION_AUDIT",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed architecture audit.",
        allowed_files="docs",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_audit, zotero_slice],
        ignored_active_slice_ids={"ZOTERO_WRITE_AGENT_RUNTIME"},
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=True,
        http_deferred_shape_harness_done=True,
        http_topic_show_service_backed=True,
        http_paper_list_service_backed=True,
        http_orchestrator_gate_check_service_backed=True,
        http_orchestrator_status_service_backed=True,
        http_orchestrator_status_routing_done=True,
        lg3_compatibility_lifecycle_guard_done=True,
    )

    assert action["action"] == "complete_architecture_line"
    assert action["slice_id"] == "S51_ARCHITECTURE_COMPLETION_AUDIT"


def test_next_action_advances_to_lg3_after_http_orchestrator_status_routing():
    module = load_script_module()
    completed_status = module.SelfDevSlice(
        slice_id="S49_LG2_HTTP_ORCHESTRATOR_STATUS_SERVICE_ROUTING",
        phase="P3",
        status="done",
        risk="high",
        parallel="no",
        objective="Completed HTTP orchestrator status routing.",
        allowed_files="http",
        tests="focused tests",
        human_gate="none",
    )
    zotero_slice = module.SelfDevSlice(
        slice_id="ZOTERO_WRITE_AGENT_RUNTIME",
        phase="P3",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Zotero runtime is handled by another session.",
        allowed_files="zotero files",
        tests="zotero tests",
        human_gate="zotero gate",
    )

    action = module.suggest_next_action(
        [completed_status, zotero_slice],
        ignored_active_slice_ids={"ZOTERO_WRITE_AGENT_RUNTIME"},
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=True,
        http_deferred_shape_harness_done=True,
        http_topic_show_service_backed=True,
        http_paper_list_service_backed=True,
        http_orchestrator_gate_check_service_backed=True,
        http_orchestrator_status_service_backed=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S50_LG3_COMPATIBILITY_LIFECYCLE_GUARD"
    assert action["risk"] == "low"
    assert "compatibility lifecycle guard" in action["objective"]
    assert "public MCP tool names" in action["stop_rules"]


def test_next_action_advances_to_architecture_audit_after_lg3_guard():
    module = load_script_module()
    completed_status = module.SelfDevSlice(
        slice_id="S49_LG2_HTTP_ORCHESTRATOR_STATUS_SERVICE_ROUTING",
        phase="P3",
        status="done",
        risk="high",
        parallel="no",
        objective="Completed HTTP orchestrator status routing.",
        allowed_files="http",
        tests="focused tests",
        human_gate="none",
    )
    completed_lg3_guard = module.SelfDevSlice(
        slice_id="S50_LG3_COMPATIBILITY_LIFECYCLE_GUARD",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed LG3 compatibility guard.",
        allowed_files="docs",
        tests="focused tests",
        human_gate="none",
    )
    zotero_slice = module.SelfDevSlice(
        slice_id="ZOTERO_WRITE_AGENT_RUNTIME",
        phase="P3",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Zotero runtime is handled by another session.",
        allowed_files="zotero files",
        tests="zotero tests",
        human_gate="zotero gate",
    )

    action = module.suggest_next_action(
        [completed_status, completed_lg3_guard, zotero_slice],
        ignored_active_slice_ids={"ZOTERO_WRITE_AGENT_RUNTIME"},
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=True,
        http_deferred_shape_harness_done=True,
        http_topic_show_service_backed=True,
        http_paper_list_service_backed=True,
        http_orchestrator_gate_check_service_backed=True,
        http_orchestrator_status_service_backed=True,
        http_orchestrator_status_routing_done=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "S51_ARCHITECTURE_COMPLETION_AUDIT"
    assert action["risk"] == "low"
    assert "completion audit" in action["objective"]


def test_next_action_reports_architecture_complete_after_completion_audit():
    module = load_script_module()
    completed_status = module.SelfDevSlice(
        slice_id="S49_LG2_HTTP_ORCHESTRATOR_STATUS_SERVICE_ROUTING",
        phase="P3",
        status="done",
        risk="high",
        parallel="no",
        objective="Completed HTTP orchestrator status routing.",
        allowed_files="http",
        tests="focused tests",
        human_gate="none",
    )
    completed_lg3_guard = module.SelfDevSlice(
        slice_id="S50_LG3_COMPATIBILITY_LIFECYCLE_GUARD",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed LG3 compatibility guard.",
        allowed_files="docs",
        tests="focused tests",
        human_gate="none",
    )
    completed_audit = module.SelfDevSlice(
        slice_id="S51_ARCHITECTURE_COMPLETION_AUDIT",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed architecture audit.",
        allowed_files="docs",
        tests="focused tests",
        human_gate="none",
    )
    zotero_slice = module.SelfDevSlice(
        slice_id="ZOTERO_WRITE_AGENT_RUNTIME",
        phase="P3",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Zotero runtime is handled by another session.",
        allowed_files="zotero files",
        tests="zotero tests",
        human_gate="zotero gate",
    )

    action = module.suggest_next_action(
        [completed_status, completed_lg3_guard, completed_audit, zotero_slice],
        ignored_active_slice_ids={"ZOTERO_WRITE_AGENT_RUNTIME"},
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=True,
        http_deferred_shape_harness_done=True,
        http_topic_show_service_backed=True,
        http_paper_list_service_backed=True,
        http_orchestrator_gate_check_service_backed=True,
        http_orchestrator_status_service_backed=True,
        http_orchestrator_status_routing_done=True,
    )

    assert action["action"] == "complete_architecture_line"
    assert action["slice_id"] == "S51_ARCHITECTURE_COMPLETION_AUDIT"
    assert "LG1, LG2, and LG3 architecture criteria are satisfied" in action["reason"]


def test_next_action_advances_to_topic_knowledge_closeout_after_cross_topic_cli_preview():
    module = load_script_module()
    completed_architecture_audit = module.SelfDevSlice(
        slice_id="S51_ARCHITECTURE_COMPLETION_AUDIT",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed architecture audit.",
        allowed_files="docs",
        tests="focused tests",
        human_gate="none",
    )
    completed_cross_topic_cli = module.SelfDevSlice(
        slice_id="K98_CROSS_TOPIC_ATLAS_LOCAL_CLI_PREVIEW",
        phase="P5",
        status="done",
        risk="medium",
        parallel="no",
        objective="Completed cross-topic local CLI preview.",
        allowed_files="cli and tests",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_architecture_audit, completed_cross_topic_cli],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        cli_topic_reads_service_backed=True,
        cli_paper_list_service_backed=True,
        cli_provenance_summary_service_backed=True,
        cli_provenance_export_service_backed=True,
        cli_orchestrator_reads_service_backed=True,
        python_orchestrator_reads_service_backed=True,
        http_topic_list_service_backed=True,
        http_provenance_summary_service_backed=True,
        http_deferred_shape_harness_done=True,
        http_topic_show_service_backed=True,
        http_paper_list_service_backed=True,
        http_orchestrator_gate_check_service_backed=True,
        http_orchestrator_status_service_backed=True,
        http_orchestrator_status_routing_done=True,
        architecture_completion_audit_done=completed_architecture_audit,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "K99_KNOWLEDGE_LOCAL_PREVIEW_CLOSEOUT"
    assert action["phase"] == "P5"
    assert action["risk"] == "low"
    assert "local CLI previews" in action["objective"]


def test_next_action_reports_topic_knowledge_complete_after_k99_closeout():
    module = load_script_module()
    completed_cross_topic_cli = module.SelfDevSlice(
        slice_id="K98_CROSS_TOPIC_ATLAS_LOCAL_CLI_PREVIEW",
        phase="P5",
        status="done",
        risk="medium",
        parallel="no",
        objective="Completed cross-topic local CLI preview.",
        allowed_files="cli and tests",
        tests="focused tests",
        human_gate="none",
    )
    completed_closeout = module.SelfDevSlice(
        slice_id="K99_KNOWLEDGE_LOCAL_PREVIEW_CLOSEOUT",
        phase="P5",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed Topic Knowledge local preview closeout.",
        allowed_files="docs and selfdev script",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [completed_cross_topic_cli, completed_closeout],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "complete_topic_knowledge_line"
    assert action["slice_id"] == "K99_KNOWLEDGE_LOCAL_PREVIEW_CLOSEOUT"
    assert "Topic Knowledge local preview line is complete" in action["objective"]


def test_next_action_json_reports_latest_topic_knowledge_http_beta_completion(
    monkeypatch,
    capsys,
):
    module = load_script_module()
    completed_local_closeout = module.SelfDevSlice(
        slice_id="K99_KNOWLEDGE_LOCAL_PREVIEW_CLOSEOUT",
        phase="P5",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed Topic Knowledge local preview closeout.",
        allowed_files="docs and selfdev script",
        tests="focused tests",
        human_gate="none",
    )
    completed_docs_closeout = module.SelfDevSlice(
        slice_id="K102E_KNOWLEDGE_CONTROLLED_BETA_DOCS_CLOSEOUT",
        phase="P5",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed controlled beta Topic Knowledge docs closeout.",
        allowed_files="docs and tests",
        tests="focused tests",
        human_gate="none",
    )
    completed_acceptance_repair = module.SelfDevSlice(
        slice_id="K102F_KNOWLEDGE_CONTROLLED_BETA_ACCEPTANCE_REPAIR",
        phase="P5",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed controlled beta Topic Knowledge acceptance repair.",
        allowed_files="HTTP tests and docs",
        tests="focused tests",
        human_gate="none",
    )
    monkeypatch.setattr(
        module,
        "load_slices",
        lambda: [
            completed_local_closeout,
            completed_docs_closeout,
            completed_acceptance_repair,
        ],
    )

    result = module.main(["next-action", "--json"])

    captured = capsys.readouterr()
    action = json.loads(captured.out)
    assert result == 0
    assert action["action"] == "complete_topic_knowledge_line"
    assert action["slice_id"] == "K102F_KNOWLEDGE_CONTROLLED_BETA_ACCEPTANCE_REPAIR"
    assert "controlled beta" in action["objective"]
    assert "K99" not in json.dumps(action, sort_keys=True)


def test_next_action_advances_to_runtime_tool_failure_after_event_and_job_done():
    module = load_script_module()
    event_slice = module.SelfDevSlice(
        slice_id="K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
        phase="P5",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed runtime event read-model.",
        allowed_files="runtime files",
        tests="focused tests",
        human_gate="none",
    )
    job_slice = module.SelfDevSlice(
        slice_id="K104_RUNTIME_JOB_LEDGER_READ_MODEL",
        phase="P5",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed job ledger read-model.",
        allowed_files="runtime files",
        tests="focused tests",
        human_gate="none",
    )
    topic_beta = module.SelfDevSlice(
        slice_id="K102E_KNOWLEDGE_CONTROLLED_BETA_DOCS_CLOSEOUT",
        phase="P5",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed controlled beta Topic Knowledge docs closeout.",
        allowed_files="docs and tests",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [topic_beta, event_slice, job_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER"
    assert action["phase"] == "P5"
    assert action["risk"] == "low"
    assert "typed tool failure" in action["objective"]
    assert "Topic Knowledge" not in action["objective"]


def test_next_action_advances_to_skill_provenance_after_tool_failure_done():
    module = load_script_module()
    event_slice = module.SelfDevSlice(
        slice_id="K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
        phase="P5",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed runtime event read-model.",
        allowed_files="runtime files",
        tests="focused tests",
        human_gate="none",
    )
    job_slice = module.SelfDevSlice(
        slice_id="K104_RUNTIME_JOB_LEDGER_READ_MODEL",
        phase="P5",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed job ledger read-model.",
        allowed_files="runtime files",
        tests="focused tests",
        human_gate="none",
    )
    tool_slice = module.SelfDevSlice(
        slice_id="K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
        phase="P5",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed tool failure and gate normalizer.",
        allowed_files="runtime files",
        tests="focused tests",
        human_gate="none",
    )

    action = module.suggest_next_action(
        [event_slice, job_slice, tool_slice],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "K106_RUNTIME_SKILL_PROVENANCE_SCANNER"
    assert action["phase"] == "P5"
    assert "skill provenance" in action["objective"]


def test_next_action_advances_to_doctor_after_skill_provenance_done():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase="P5",
            status="done",
            risk="low",
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
        )
    ]

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS"
    assert action["phase"] == "P5"
    assert "doctor" in action["objective"]


def test_next_action_advances_to_showcase_after_doctor_done():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase="P5",
            status="done",
            risk="low",
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
            "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
        )
    ]

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER"
    assert action["phase"] == "P5"
    assert "showcase manifest" in action["objective"]


def test_next_action_reports_runtime_shell_p5_complete_after_showcase_done():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase="P5",
            status="done",
            risk="low",
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
            "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
            "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER",
        )
    ]

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "complete_runtime_shell_p5"
    assert action["slice_id"] == "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER"
    assert action["phase"] == "P5"
    assert "P5 read-model" in action["objective"]
    assert "P6" in action["human_gate"]


def test_next_action_reports_runtime_shell_p6a_boundary_after_k110_done():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase="P6" if slice_id.startswith(("K109_", "K110_")) else "P5",
            status="done",
            risk="medium" if slice_id.startswith(("K109_", "K110_")) else "low",
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
            "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
            "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER",
            "K109_RUNTIME_SHELL_P6_DOCTOR_DIAGNOSTICS_GATE",
            "K110_RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI",
        )
    ]

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == "K110_RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI"
    assert action["phase"] == "P6"
    assert "P6A public CLI preview is complete" in action["reason"]
    assert "fresh gate-approved slice" in action["human_gate"]


def test_next_action_reports_runtime_event_store_boundary_after_k113_done():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase=(
                "P6"
                if slice_id.startswith(("K109_", "K110_", "K112_", "K113_"))
                else "P5"
            ),
            status="done",
            risk="high" if slice_id.startswith(("K112_", "K113_")) else "medium",
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
            "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
            "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER",
            "K109_RUNTIME_SHELL_P6_DOCTOR_DIAGNOSTICS_GATE",
            "K110_RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI",
            "K112_RUNTIME_EVENT_STORE_SCHEMA_GATE",
            "K113_RUNTIME_EVENT_STORE_SCHEMA_ONLY",
        )
    ]

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == "K113_RUNTIME_EVENT_STORE_SCHEMA_ONLY"
    assert action["phase"] == "P6"
    assert "runtime event store schema is complete" in action["reason"]
    assert "writer integration" in action["human_gate"]


def test_next_action_reports_first_live_source_boundary_after_k122_done():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase=(
                "P6" if slice_id.startswith(("K109_", "K110_", "K112_", "K1")) else "P5"
            ),
            status="done",
            risk=(
                "high"
                if slice_id.startswith(
                    (
                        "K112_",
                        "K113_",
                        "K115_",
                        "K116_",
                        "K117_",
                        "K118_",
                        "K119_",
                        "K120_",
                        "K121_",
                        "K122_",
                    )
                )
                else "medium"
            ),
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
            "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
            "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER",
            "K109_RUNTIME_SHELL_P6_DOCTOR_DIAGNOSTICS_GATE",
            "K110_RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI",
            "K112_RUNTIME_EVENT_STORE_SCHEMA_GATE",
            "K113_RUNTIME_EVENT_STORE_SCHEMA_ONLY",
            "K115_RUNTIME_EVENT_WRITER_HELPER_GATE",
            "K116_RUNTIME_EVENT_STORE_WRITER_HELPER",
            "K117_RUNTIME_EVENT_STORE_WRITER_RELIABILITY",
            "K118_RUNTIME_EVENT_STORE_READBACK_HELPER",
            "K119_RUNTIME_EVENT_STORE_HEALTH_AND_CONTRACT",
            "K120_RUNTIME_EVENT_STORE_PUBLIC_SURFACE_GUARD",
            "K121_RUNTIME_EVENT_STORE_FIRST_SOURCE_GATE_PACKAGE",
            K122_SLICE_ID,
        )
    ]

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K122_SLICE_ID
    assert action["phase"] == "P6"
    assert "first self-dev checkpoint source is complete" in action["reason"]
    assert "other live source" in action["human_gate"]


def test_next_action_reports_handoff_source_boundary_after_k123_done():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase="P6" if slice_id.startswith(("K109_", "K110_", "K1")) else "P5",
            status="done",
            risk=(
                "high"
                if slice_id.startswith(
                    (
                        "K112_",
                        "K113_",
                        "K115_",
                        "K116_",
                        "K117_",
                        "K118_",
                        "K119_",
                        "K120_",
                        "K121_",
                        "K122_",
                        "K123_",
                    )
                )
                else "medium"
            ),
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
            "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
            "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER",
            "K109_RUNTIME_SHELL_P6_DOCTOR_DIAGNOSTICS_GATE",
            "K110_RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI",
            "K112_RUNTIME_EVENT_STORE_SCHEMA_GATE",
            "K113_RUNTIME_EVENT_STORE_SCHEMA_ONLY",
            "K115_RUNTIME_EVENT_WRITER_HELPER_GATE",
            "K116_RUNTIME_EVENT_STORE_WRITER_HELPER",
            "K117_RUNTIME_EVENT_STORE_WRITER_RELIABILITY",
            "K118_RUNTIME_EVENT_STORE_READBACK_HELPER",
            "K119_RUNTIME_EVENT_STORE_HEALTH_AND_CONTRACT",
            "K120_RUNTIME_EVENT_STORE_PUBLIC_SURFACE_GUARD",
            "K121_RUNTIME_EVENT_STORE_FIRST_SOURCE_GATE_PACKAGE",
            K122_SLICE_ID,
            K123_SLICE_ID,
        )
    ]

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K123_SLICE_ID
    assert action["phase"] == "P6"
    assert "self-dev handoff source is complete" in action["reason"]
    assert "additional live source" in action["human_gate"]


def test_next_action_reports_gate_report_source_boundary_after_k125_done():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase="P6" if slice_id.startswith(("K109_", "K110_", "K1")) else "P5",
            status="done",
            risk=(
                "high"
                if slice_id.startswith(
                    (
                        "K112_",
                        "K113_",
                        "K115_",
                        "K116_",
                        "K117_",
                        "K118_",
                        "K119_",
                        "K120_",
                        "K121_",
                        "K122_",
                        "K123_",
                        "K124_",
                        "K125_",
                    )
                )
                else "medium"
            ),
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
            "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
            "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER",
            "K109_RUNTIME_SHELL_P6_DOCTOR_DIAGNOSTICS_GATE",
            "K110_RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI",
            "K112_RUNTIME_EVENT_STORE_SCHEMA_GATE",
            "K113_RUNTIME_EVENT_STORE_SCHEMA_ONLY",
            "K115_RUNTIME_EVENT_WRITER_HELPER_GATE",
            "K116_RUNTIME_EVENT_STORE_WRITER_HELPER",
            "K117_RUNTIME_EVENT_STORE_WRITER_RELIABILITY",
            "K118_RUNTIME_EVENT_STORE_READBACK_HELPER",
            "K119_RUNTIME_EVENT_STORE_HEALTH_AND_CONTRACT",
            "K120_RUNTIME_EVENT_STORE_PUBLIC_SURFACE_GUARD",
            "K121_RUNTIME_EVENT_STORE_FIRST_SOURCE_GATE_PACKAGE",
            K122_SLICE_ID,
            K123_SLICE_ID,
            "K124_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE_GATE",
            K125_SLICE_ID,
        )
    ]

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K125_SLICE_ID
    assert action["phase"] == "P6"
    assert "gate report source is complete" in action["reason"]
    assert "additional live source" in action["human_gate"]


def test_next_action_reports_prompt_source_boundary_after_k127_done():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase="P6" if slice_id.startswith(("K109_", "K110_", "K1")) else "P5",
            status="done",
            risk=(
                "high"
                if slice_id.startswith(
                    (
                        "K112_",
                        "K113_",
                        "K115_",
                        "K116_",
                        "K117_",
                        "K118_",
                        "K119_",
                        "K120_",
                        "K121_",
                        "K122_",
                        "K123_",
                        "K124_",
                        "K125_",
                        "K126_",
                        "K127_",
                    )
                )
                else "medium"
            ),
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
            "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
            "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER",
            "K109_RUNTIME_SHELL_P6_DOCTOR_DIAGNOSTICS_GATE",
            "K110_RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI",
            "K112_RUNTIME_EVENT_STORE_SCHEMA_GATE",
            "K113_RUNTIME_EVENT_STORE_SCHEMA_ONLY",
            "K115_RUNTIME_EVENT_WRITER_HELPER_GATE",
            "K116_RUNTIME_EVENT_STORE_WRITER_HELPER",
            "K117_RUNTIME_EVENT_STORE_WRITER_RELIABILITY",
            "K118_RUNTIME_EVENT_STORE_READBACK_HELPER",
            "K119_RUNTIME_EVENT_STORE_HEALTH_AND_CONTRACT",
            "K120_RUNTIME_EVENT_STORE_PUBLIC_SURFACE_GUARD",
            "K121_RUNTIME_EVENT_STORE_FIRST_SOURCE_GATE_PACKAGE",
            K122_SLICE_ID,
            K123_SLICE_ID,
            "K124_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE_GATE",
            K125_SLICE_ID,
            "K126_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE_GATE",
            K127_SLICE_ID,
        )
    ]

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K127_SLICE_ID
    assert action["phase"] == "P6"
    assert "prompt source is complete" in action["reason"]
    assert "additional live source" in action["human_gate"]


def test_next_action_reports_next_action_source_boundary_after_k131_done():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase="P6" if slice_id.startswith(("K109_", "K110_", "K1")) else "P5",
            status="done",
            risk=(
                "high"
                if slice_id.startswith(
                    (
                        "K112_",
                        "K113_",
                        "K115_",
                        "K116_",
                        "K117_",
                        "K118_",
                        "K119_",
                        "K120_",
                        "K121_",
                        "K122_",
                        "K123_",
                        "K124_",
                        "K125_",
                        "K126_",
                        "K127_",
                        "K128_",
                        "K129_",
                        "K130_",
                        "K131_",
                    )
                )
                else "medium"
            ),
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
            "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
            "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER",
            "K109_RUNTIME_SHELL_P6_DOCTOR_DIAGNOSTICS_GATE",
            "K110_RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI",
            "K112_RUNTIME_EVENT_STORE_SCHEMA_GATE",
            "K113_RUNTIME_EVENT_STORE_SCHEMA_ONLY",
            "K115_RUNTIME_EVENT_WRITER_HELPER_GATE",
            "K116_RUNTIME_EVENT_STORE_WRITER_HELPER",
            "K117_RUNTIME_EVENT_STORE_WRITER_RELIABILITY",
            "K118_RUNTIME_EVENT_STORE_READBACK_HELPER",
            "K119_RUNTIME_EVENT_STORE_HEALTH_AND_CONTRACT",
            "K120_RUNTIME_EVENT_STORE_PUBLIC_SURFACE_GUARD",
            "K121_RUNTIME_EVENT_STORE_FIRST_SOURCE_GATE_PACKAGE",
            K122_SLICE_ID,
            K123_SLICE_ID,
            "K124_RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE_GATE",
            K125_SLICE_ID,
            "K126_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE_GATE",
            K127_SLICE_ID,
            "K128_RUNTIME_EVENT_STORE_SELFDEV_SLICE_STATUS_SOURCE_GATE",
            K129_SLICE_ID,
            "K130_RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_SOURCE_GATE",
            K131_SLICE_ID,
        )
    ]

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K131_SLICE_ID
    assert action["phase"] == "P6"
    assert "next-action source is complete" in action["reason"]
    assert "additional live source" in action["human_gate"]


def test_next_action_batch_gate_advances_to_status_source_after_k131_done():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == K133_STATUS_SOURCE_ID
    assert action["phase"] == "P6"
    assert action["batch_window_remaining"] == "3"
    assert "batch gate is active" in action["reason"]
    assert "selfdev.status_reported" in action["objective"]


def test_next_action_batch_window_exhaustion_waits_for_gate():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K135_CODEX_COMMAND_SOURCE_ID
    assert "batch window is exhausted" in action["reason"]
    assert "fresh gate" in action["human_gate"]


def test_next_action_batch_excludes_cloud_submit_auto_authorization():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        selfdev_batch_window_size=4,
    )

    assert action["action"] == "wait_for_gate"
    assert "cloud-submit" in action["reason"]
    assert "explicit human approval" in action["human_gate"]


def test_next_action_after_cloud_submit_source_done_references_cloud_submit():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K141_CLOUD_SUBMIT_SOURCE_ID
    assert "cloud-submit source is complete" in action["reason"]
    assert "fresh gate" in action["human_gate"]


def test_next_action_after_cloud_submit_failure_source_done_references_failure_source():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID
    assert "cloud-submit failure source is complete" in action["reason"]
    assert "fresh gate" in action["human_gate"]


def test_next_action_after_cloud_submit_started_source_done_references_started_source():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K143_CLOUD_SUBMIT_STARTED_SOURCE_ID
    assert "cloud-submit started source is complete" in action["reason"]
    assert "fresh gate" in action["human_gate"]


def test_next_action_extended_batch_gate_advances_to_sequence_hardening():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID
    assert action["phase"] == "P6"
    assert action["batch_window_size"] == "6"
    assert action["batch_window_remaining"] == "6"
    assert "K144 extended batch gate is active" in action["reason"]
    assert "cloud-submit runtime event sequence" in action["objective"]


def test_next_action_extended_batch_risk_flags_wait_for_gate():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        selfdev_batch_risk_flags={
            "public_surface_changed": True,
            "storage_or_provenance_changed": False,
            "orchestrator_gate_changed": False,
            "benchmark_claim_changed": False,
            "dependency_changed": False,
        },
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K143_CLOUD_SUBMIT_STARTED_SOURCE_ID
    assert "extended batch risk flags" in action["reason"]
    assert "public_surface_changed" in action["reason"]


def test_next_action_extended_batch_test_failures_wait_for_gate():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        selfdev_batch_failed_test_attempts=2,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K143_CLOUD_SUBMIT_STARTED_SOURCE_ID
    assert "extended batch focused tests failed twice" in action["reason"]


def test_next_action_extended_batch_deduplicates_completed_candidates():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _redaction_guard_slice(module, "done"),
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _cloud_submit_sequence_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == K148_NEXT_ACTION_EXTENDED_BATCH_RECOVERY_ID
    assert action["batch_window_size"] == "6"
    assert action["batch_window_remaining"] == "3"


def test_next_action_extended_batch_risk_flags_reference_latest_candidate():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _redaction_guard_slice(module, "done"),
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        selfdev_batch_risk_flags={
            "public_surface_changed": False,
            "storage_or_provenance_changed": True,
            "orchestrator_gate_changed": False,
            "benchmark_claim_changed": False,
            "dependency_changed": False,
        },
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K147_REDACTION_GUARD_ID
    assert "storage_or_provenance_changed" in action["reason"]


def test_next_action_extended_batch_test_failures_reference_latest_candidate():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _redaction_guard_slice(module, "done"),
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        selfdev_batch_failed_test_attempts=2,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K147_REDACTION_GUARD_ID
    assert "extended batch focused tests failed twice" in action["reason"]


def test_next_action_extended_batch_closeout_exhausts_window():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K150_EXTENDED_BATCH_CLOSEOUT_ID
    assert (
        "extended batch window is exhausted after 6 allowlisted slices"
        in (action["reason"])
    )
    assert "fresh gate" in action["human_gate"]


def test_next_action_post_closeout_gate_advances_to_review_package():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == K152_POST_CLOSEOUT_REVIEW_PACKAGE_ID
    assert action["phase"] == "P6"
    assert action["risk"] == "low"
    assert "K151 post-closeout review gate is active" in action["reason"]
    assert (
        "docs-only post-K150 runtime event store review package"
        in (action["objective"])
    )


def test_next_action_post_closeout_review_package_waits_for_gate():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K152_POST_CLOSEOUT_REVIEW_PACKAGE_ID
    assert "post-K150 review package is complete" in action["reason"]
    assert "fresh gate" in action["human_gate"]


def test_next_action_broad_autonomy_gate_advances_to_internal_review_audit():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == K154_INTERNAL_REVIEW_AUDIT_ID
    assert action["risk"] == "low"
    assert "K153 broad autonomy policy is active" in action["reason"]
    assert "review/audit" in action["objective"]


def test_next_action_internal_review_audit_completion_waits_for_selected_next_line():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K154_INTERNAL_REVIEW_AUDIT_ID
    assert "internal review audit is complete" in action["reason"]
    assert "large-risk" in action["human_gate"]


def test_next_action_after_metadata_redaction_audit_references_latest_followup():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K155_METADATA_REDACTION_AUDIT_ID
    assert "metadata redaction audit is complete" in action["reason"]
    assert "large-risk" in action["human_gate"]


def test_next_action_after_post_audit_recovery_references_recovery_slice():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K156_POST_AUDIT_NEXT_ACTION_RECOVERY_ID
    assert "post-audit next-action recovery is complete" in action["reason"]
    assert "large-risk" in action["human_gate"]


def test_next_action_after_closeout_sweep_uses_latest_low_risk_followup():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
        _closeout_verification_sweep_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K157_CLOSEOUT_VERIFICATION_SWEEP_ID
    assert "closeout verification sweep is complete" in action["reason"]
    assert "large-risk" in action["human_gate"]


def test_latest_broad_autonomy_followup_uses_highest_k_number_not_row_order():
    module = load_script_module()
    audit_slice = _internal_review_audit_slice(module, "done")
    shuffled_followups = [
        audit_slice,
        _verification_matrix_command_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
    ]

    latest = module._runtime_event_store_latest_broad_autonomy_followup(
        shuffled_followups,
        audit_slice,
    )

    assert latest is not None
    assert latest.slice_id == K160_VERIFICATION_MATRIX_COMMAND_ID


def test_latest_broad_autonomy_followup_ignores_unsafe_candidates():
    module = load_script_module()
    audit_slice = _internal_review_audit_slice(module, "done")
    high_risk_candidate = module.SelfDevSlice(
        slice_id="K999_RUNTIME_EVENT_STORE_HIGH_RISK_BACKFILL",
        phase="P6",
        status="done",
        risk="high",
        parallel="no",
        objective="Should not become the broad-autonomy boundary.",
        allowed_files="runtime files",
        tests="focused tests",
        human_gate="requires a fresh gate",
    )
    in_progress_candidate = module.SelfDevSlice(
        slice_id="K998_SELFDEV_IN_PROGRESS",
        phase="P6",
        status="in_progress",
        risk="low",
        parallel="no",
        objective="Should not become the broad-autonomy boundary.",
        allowed_files="scripts",
        tests="focused tests",
        human_gate="covered by K153",
    )
    gate_candidate = module.SelfDevSlice(
        slice_id="K997_SELFDEV_GATE",
        phase="P6",
        status="gate",
        risk="low",
        parallel="no",
        objective="Should not become the broad-autonomy boundary.",
        allowed_files="docs",
        tests="focused checks",
        human_gate="pending gate",
    )
    p7_candidate = module.SelfDevSlice(
        slice_id="K996_TOPIC_RETRIEVAL_BACKLOG",
        phase="P7",
        status="done",
        risk="low",
        parallel="no",
        objective="Should not become the broad-autonomy boundary.",
        allowed_files="research files",
        tests="focused tests",
        human_gate="separate gate",
    )
    backlog_candidate = module.SelfDevSlice(
        slice_id="SURVEY_FIRST_TOPIC_EXPANSION_SEEDING",
        phase="P7",
        status="done",
        risk="low",
        parallel="no",
        objective="Should not become the broad-autonomy boundary.",
        allowed_files="research files",
        tests="focused tests",
        human_gate="separate gate",
    )
    slices = [
        audit_slice,
        _metadata_redaction_audit_slice(module, "done"),
        high_risk_candidate,
        in_progress_candidate,
        gate_candidate,
        p7_candidate,
        backlog_candidate,
    ]

    latest = module._runtime_event_store_latest_broad_autonomy_followup(
        slices,
        audit_slice,
    )

    assert latest is not None
    assert latest.slice_id == K155_METADATA_REDACTION_AUDIT_ID


def test_next_action_after_fast_batch_completion_references_batch_slice():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
        _closeout_verification_sweep_slice(module, "done"),
        _fast_batch_lane_protocol_slice(module, "done"),
        _batch_runner_helpers_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K164_BATCH_RUNNER_HELPERS_ID
    assert "batch runner helpers is complete" in action["reason"]
    assert K163_FAST_BATCH_LANE_PROTOCOL_ID not in action["slice_id"]


def test_next_action_after_long_goal_activation_creates_lg8_baseline_slice():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
        _closeout_verification_sweep_slice(module, "done"),
        _fast_batch_lane_protocol_slice(module, "done"),
        _batch_runner_helpers_slice(module, "done"),
        _closeout_objective_matrix_slice(module, "done"),
        _runtime_shell_final_closeout_slice(module, "done"),
        _long_goal_activation_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG8_PRIVATE_PERFORMANCE_BASELINE_SUFFIX)
    assert action["phase"] == "P8"
    assert action["risk"] == "low"
    assert "private performance baseline" in action["objective"]
    assert "benchmark promotion" in action["human_gate"]
    assert "public surface" in action["stop_rules"]


def test_next_action_after_lg8_private_baseline_creates_combined_contract_slice():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
        _closeout_verification_sweep_slice(module, "done"),
        _fast_batch_lane_protocol_slice(module, "done"),
        _batch_runner_helpers_slice(module, "done"),
        _closeout_objective_matrix_slice(module, "done"),
        _runtime_shell_final_closeout_slice(module, "done"),
        _long_goal_activation_slice(module, "done"),
        _lg8_private_performance_baseline_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG8_LG9_COMBINED_CONTRACT_SUFFIX)
    assert action["phase"] == "P8"
    assert action["risk"] == "low"
    assert (
        "Bind LG8 performance governance and LG9 durable semantics"
        in (action["objective"])
    )
    assert "LG6 runtime-shell" not in action["objective"]
    assert "K172 private performance baseline is complete" in action["reason"]
    assert "combined execution contract" in action["objective"]
    assert "benchmark promotion" in action["human_gate"]


def test_next_action_after_lg8_lg9_contract_creates_first_hot_path_slice():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
        _closeout_verification_sweep_slice(module, "done"),
        _fast_batch_lane_protocol_slice(module, "done"),
        _batch_runner_helpers_slice(module, "done"),
        _closeout_objective_matrix_slice(module, "done"),
        _runtime_shell_final_closeout_slice(module, "done"),
        _long_goal_activation_slice(module, "done"),
        _lg8_private_performance_baseline_slice(module, "done"),
        _lg8_lg9_combined_contract_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG8_NEXT_ACTION_HOT_PATH_SUFFIX)
    assert action["phase"] == "P8"
    assert action["risk"] == "low"
    assert "self-dev next-action recovery" in action["objective"]
    assert "before/after" in action["tests"]
    assert "LG9" in action["reason"]
    assert "public surface" in action["human_gate"]


def test_lg8_lg9_next_action_bypasses_legacy_transport_detection(monkeypatch):
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
        _closeout_verification_sweep_slice(module, "done"),
        _fast_batch_lane_protocol_slice(module, "done"),
        _batch_runner_helpers_slice(module, "done"),
        _closeout_objective_matrix_slice(module, "done"),
        _runtime_shell_final_closeout_slice(module, "done"),
        _long_goal_activation_slice(module, "done"),
        _lg8_private_performance_baseline_slice(module, "done"),
        _lg8_lg9_combined_contract_slice(module, "done"),
    ]

    def fail_legacy_detection() -> bool:
        raise AssertionError("legacy transport detection should not run")

    monkeypatch.setattr(
        module,
        "_cli_topic_reads_are_service_backed",
        fail_legacy_detection,
    )

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["slice_id"].endswith(LG8_NEXT_ACTION_HOT_PATH_SUFFIX)


def test_next_action_after_first_lg8_lg9_hot_path_creates_runtime_event_slice():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
        _closeout_verification_sweep_slice(module, "done"),
        _fast_batch_lane_protocol_slice(module, "done"),
        _batch_runner_helpers_slice(module, "done"),
        _closeout_objective_matrix_slice(module, "done"),
        _runtime_shell_final_closeout_slice(module, "done"),
        _long_goal_activation_slice(module, "done"),
        _lg8_private_performance_baseline_slice(module, "done"),
        _lg8_lg9_combined_contract_slice(module, "done"),
        _lg8_next_action_hot_path_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG8_RUNTIME_EVENT_APPEND_HOT_PATH_SUFFIX)
    assert "runtime event append" in action["objective"]
    assert "K174" in action["reason"]
    assert "storage" in action["human_gate"]


def test_next_action_after_runtime_event_hot_path_creates_command_hot_path_slice():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
        _closeout_verification_sweep_slice(module, "done"),
        _fast_batch_lane_protocol_slice(module, "done"),
        _batch_runner_helpers_slice(module, "done"),
        _closeout_objective_matrix_slice(module, "done"),
        _runtime_shell_final_closeout_slice(module, "done"),
        _long_goal_activation_slice(module, "done"),
        _lg8_private_performance_baseline_slice(module, "done"),
        _lg8_lg9_combined_contract_slice(module, "done"),
        _lg8_next_action_hot_path_slice(module, "done"),
        _lg8_runtime_event_append_hot_path_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG8_NEXT_ACTION_COMMAND_HOT_PATH_SUFFIX)
    assert "next-action command" in action["objective"]
    assert "K175" in action["reason"]
    assert "before/after" in action["tests"]


def test_next_action_command_lg8_lg9_fast_path_skips_git_risk_scan(monkeypatch, capsys):
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
        _closeout_verification_sweep_slice(module, "done"),
        _fast_batch_lane_protocol_slice(module, "done"),
        _batch_runner_helpers_slice(module, "done"),
        _closeout_objective_matrix_slice(module, "done"),
        _runtime_shell_final_closeout_slice(module, "done"),
        _long_goal_activation_slice(module, "done"),
        _lg8_private_performance_baseline_slice(module, "done"),
        _lg8_lg9_combined_contract_slice(module, "done"),
        _lg8_next_action_hot_path_slice(module, "done"),
        _lg8_runtime_event_append_hot_path_slice(module, "done"),
    ]
    monkeypatch.setattr(module, "load_slices", lambda: recovered_slices)
    monkeypatch.setattr(
        module,
        "git_changed_files",
        lambda: (_ for _ in ()).throw(
            AssertionError("LG8/LG9 fast path should not run git status")
        ),
    )
    monkeypatch.setattr(module, "_append_next_action_runtime_event", lambda **_: None)

    result = module.main(["next-action", "--json"])

    captured = capsys.readouterr()
    assert result == 0
    action = json.loads(captured.out)
    assert action["slice_id"].endswith(LG8_NEXT_ACTION_COMMAND_HOT_PATH_SUFFIX)


def test_next_action_command_lg16_completion_preempts_lg8_fast_path(
    monkeypatch, capsys
):
    module = load_script_module()
    completed_slices = [
        _local_autonomy_goal4_slice(module, "done"),
        module.SelfDevSlice(
            slice_id="LG16_EXISTING_SYSTEM_FINALIZATION",
            phase="P17",
            status="done",
            risk="high",
            parallel="no",
            objective="Finalize the existing RH system without new public surface.",
            allowed_files="guards and service-backed adapters",
            tests="focused LG16 suite",
            human_gate="Phase B remains separate.",
        ),
    ]
    monkeypatch.setattr(module, "load_slices", lambda: completed_slices)
    monkeypatch.setattr(
        module,
        "git_changed_files",
        lambda: (_ for _ in ()).throw(
            AssertionError("LG16 completion should not run git status")
        ),
    )
    monkeypatch.setattr(module, "_append_next_action_runtime_event", lambda **_: None)

    result = module.main(["next-action", "--json"])

    captured = capsys.readouterr()
    assert result == 0
    action = json.loads(captured.out)
    assert action["action"] == "complete_existing_system_finalization"
    assert action["slice_id"] == "LG16_EXISTING_SYSTEM_FINALIZATION"


def test_next_action_after_lg8_hot_path_batch_creates_lg9_contract_matrix_slice():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
        K133_STATUS_SOURCE_ID,
        K134_CLOUD_COMMAND_SOURCE_ID,
        K135_CODEX_COMMAND_SOURCE_ID,
        K141_CLOUD_SUBMIT_SOURCE_ID,
        K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
        K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
        K144_EXTENDED_BATCH_GATE_ID,
    )
    recovered_slices = [
        *completed_slices,
        _cloud_submit_sequence_slice(module, "done"),
        _cloud_submit_store_failure_slice(module, "done"),
        _redaction_guard_slice(module, "done"),
        _next_action_extended_batch_recovery_slice(module, "done"),
        _event_store_contract_refresh_slice(module, "done"),
        _extended_batch_closeout_slice(module, "done"),
        _post_closeout_review_gate_slice(module, "done"),
        _post_closeout_review_package_slice(module, "done"),
        _broad_autonomy_policy_gate_slice(module, "done"),
        _internal_review_audit_slice(module, "done"),
        _metadata_redaction_audit_slice(module, "done"),
        _post_audit_next_action_recovery_slice(module, "done"),
        _closeout_verification_sweep_slice(module, "done"),
        _fast_batch_lane_protocol_slice(module, "done"),
        _batch_runner_helpers_slice(module, "done"),
        _closeout_objective_matrix_slice(module, "done"),
        _runtime_shell_final_closeout_slice(module, "done"),
        _long_goal_activation_slice(module, "done"),
        _lg8_private_performance_baseline_slice(module, "done"),
        _lg8_lg9_combined_contract_slice(module, "done"),
        _lg8_next_action_hot_path_slice(module, "done"),
        _lg8_runtime_event_append_hot_path_slice(module, "done"),
        module.SelfDevSlice(
            slice_id="K176_LG8_SELFDEV_NEXT_ACTION_COMMAND_HOT_PATH",
            phase="P8",
            status="done",
            risk="low",
            parallel="no",
            objective="Optimize private self-dev next-action command hot path.",
            allowed_files="scripts; tests; self-dev docs",
            tests="focused next-action command tests",
            human_gate="No gate for private helper optimization.",
        ),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG9_DURABLE_CONTRACT_MATRIX_SUFFIX)
    assert "LG9 durable" in action["objective"]
    assert "K176" in action["reason"]
    assert "public surface" in action["human_gate"]


def test_next_action_after_lg9_contract_matrix_creates_provenance_contract_slice():
    module = load_script_module()

    action = module.suggest_next_action(
        _lg8_lg9_recovered_slices_through_k177(module),
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG9_PROVENANCE_ARTIFACT_CONTRACT_SUFFIX)
    assert "provenance/artifact linkage" in action["objective"]
    assert "K177" in action["reason"]
    assert "artifact lineage" in action["human_gate"]


def test_next_action_after_lg9_provenance_contract_creates_orchestrator_contract_slice():
    module = load_script_module()

    action = module.suggest_next_action(
        _lg8_lg9_recovered_slices_through_k178(module),
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG9_ORCHESTRATOR_READONLY_CONTRACT_SUFFIX)
    assert "orchestrator read-only mapping" in action["objective"]
    assert "K178" in action["reason"]
    assert "rollback" in action["human_gate"]


def test_next_action_after_lg9_orchestrator_contract_waits_on_lg9_boundary():
    module = load_script_module()

    action = module.suggest_next_action(
        _lg8_lg9_recovered_slices_through_k179(module),
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG8_LG9_PRIVATE_CLOSEOUT_SUFFIX)
    assert "closeout" in action["objective"]
    assert "K179" in action["reason"]
    assert "LG10" in action["human_gate"]


def test_next_action_after_lg8_lg9_closeout_creates_lg10_boundary_slice():
    module = load_script_module()

    action = module.suggest_next_action(
        _lg8_lg9_recovered_slices_through_k180(module),
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG10_PUBLIC_PRODUCTIZATION_BOUNDARY_SUFFIX)
    assert action["phase"] == "P8"
    assert action["risk"] == "low"
    assert "LG10 public-productization gate" in action["objective"]
    assert "K180" in action["reason"]
    assert "public implementation" in action["human_gate"]
    assert (
        ".rh-selfdev/rh-lg10-public-productization-boundary-2026-06-11.md"
        in (action["allowed_files"])
    )


def test_next_action_after_lg10_boundary_waits_for_gate():
    module = load_script_module()

    action = module.suggest_next_action(
        _lg10_recovered_slices_through_k181(module),
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K181_LG10_PUBLIC_PRODUCTIZATION_BOUNDARY_ID
    assert action["objective"] == "Define the LG10 public-productization gate boundary."
    assert "fresh gate" in action["reason"]
    assert (
        "Do not create public implementation slices automatically"
        in (action["human_gate"])
    )


def test_next_action_after_lg10_batch_gate_creates_cli_boundary_preview():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG10_CLI_BOUNDARY_PREVIEW_SUFFIX)
    assert action["phase"] == "P8"
    assert action["risk"] == "medium"
    assert "CLI" in action["objective"]
    assert "opt-in" in action["objective"]
    assert "K182" in action["reason"]
    assert "one public surface" in action["human_gate"]


def test_next_action_after_lg10_cli_boundary_preview_creates_mcp_preview():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG10_MCP_BOUNDARY_PREVIEW_SUFFIX)
    assert "MCP" in action["objective"]
    assert "K183" in action["reason"]


def test_next_action_after_lg10_mcp_boundary_preview_waits_for_gate():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K184_LG10_MCP_BOUNDARY_PREVIEW_ID
    assert "fresh gate" in action["reason"]
    assert (
        "Do not create public implementation slices automatically"
        in (action["human_gate"])
    )


def test_next_action_after_lg10_http_gate_creates_http_preview():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG10_HTTP_BOUNDARY_PREVIEW_SUFFIX)
    assert action["phase"] == "P8"
    assert action["risk"] == "medium"
    assert "HTTP" in action["objective"]
    assert "opt-in" in action["objective"]
    assert "K185" in action["reason"]
    assert "one public surface" in action["human_gate"]


def test_next_action_after_lg10_http_preview_waits_for_gate():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K186_LG10_HTTP_BOUNDARY_PREVIEW_ID
    assert "fresh gate" in action["reason"]
    assert (
        "Do not create public implementation slices automatically"
        in (action["human_gate"])
    )


def test_next_action_after_lg10_python_facade_gate_creates_python_facade_preview():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_SUFFIX)
    assert action["phase"] == "P8"
    assert action["risk"] == "medium"
    assert "Python facade" in action["objective"]
    assert "opt-in" in action["objective"]
    assert "K187" in action["reason"]
    assert "one public surface" in action["human_gate"]


def test_next_action_after_lg10_python_facade_preview_waits_for_gate():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K188_LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_ID
    assert "fresh gate" in action["reason"]
    assert (
        "Do not create public implementation slices automatically"
        in (action["human_gate"])
    )


def test_next_action_after_lg10_skills_docs_gate_creates_skills_docs_preview():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_SUFFIX)
    assert action["phase"] == "P8"
    assert action["risk"] == "medium"
    assert "skills/docs" in action["objective"]
    assert "opt-in" in action["objective"]
    assert "K189" in action["reason"]
    assert "one public surface" in action["human_gate"]


def test_next_action_after_lg10_skills_docs_preview_waits_for_gate():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K190_LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_ID
    assert "fresh gate" in action["reason"]
    assert (
        "Do not create public implementation slices automatically"
        in (action["human_gate"])
    )


def test_next_action_after_lg10_doctor_gate_creates_doctor_preview():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG10_DOCTOR_BOUNDARY_PREVIEW_SUFFIX)
    assert action["phase"] == "P8"
    assert action["risk"] == "medium"
    assert "doctor" in action["objective"]
    assert "opt-in" in action["objective"]
    assert "K191" in action["reason"]
    assert "one public surface" in action["human_gate"]


def test_next_action_after_lg10_doctor_preview_waits_for_gate():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "wait_for_gate"
    assert action["slice_id"] == K192_LG10_DOCTOR_BOUNDARY_PREVIEW_ID
    assert "fresh gate" in action["reason"]
    assert (
        "Do not create public implementation slices automatically"
        in (action["human_gate"])
    )


def test_next_action_after_lg10_showcase_gate_creates_showcase_preview():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"].endswith(LG10_SHOWCASE_BOUNDARY_PREVIEW_SUFFIX)
    assert action["phase"] == "P8"
    assert action["risk"] == "medium"
    assert "showcase" in action["objective"]
    assert "opt-in" in action["objective"]
    assert "K193" in action["reason"]
    assert "one public surface" in action["human_gate"]


def test_next_action_after_lg10_showcase_preview_creates_mainline_closeout_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == POST_LG10_MAINLINE_CLOSEOUT_ID
    assert action["phase"] == "P8"
    assert action["risk"] == "medium"
    assert "mainline acceptance" in action["objective"]
    assert "K194" in action["reason"]
    assert "docs/tests/helper closeout" in action["human_gate"]


def test_next_action_after_mainline_closeout_creates_st01_non_benchmark_stabilization():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY_ID
    assert action["phase"] == "P11"
    assert action["risk"] == "medium"
    assert "Topic Knowledge stable local/internal boundary" in action["objective"]
    assert "post-LG10 mainline closeout is complete" in action["reason"]
    assert "benchmark/public performance claims" in action["human_gate"]


def test_next_action_after_st01_advances_to_http_local_stable_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        _non_benchmark_stabilization_slice(
            module, ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY_ID
        ),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE_ID
    assert action["phase"] == "P11"
    assert action["risk"] == "medium"
    assert "HTTP controlled beta" in action["objective"]
    assert ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY_ID in action["reason"]


def test_next_action_after_st02_advances_to_lg10_boundary_hardening_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        _non_benchmark_stabilization_slice(
            module, ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY_ID
        ),
        _non_benchmark_stabilization_slice(
            module, ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE_ID
        ),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == ST03_LG10_BOUNDARY_PREVIEW_HARDENING_ID
    assert action["phase"] == "P11"
    assert action["risk"] == "medium"
    assert "LG10 boundary previews" in action["objective"]
    assert ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE_ID in action["reason"]


def test_next_action_after_st03_advances_to_survey_first_stabilization_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        _non_benchmark_stabilization_slice(
            module, ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY_ID
        ),
        _non_benchmark_stabilization_slice(
            module, ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE_ID
        ),
        _non_benchmark_stabilization_slice(
            module, ST03_LG10_BOUNDARY_PREVIEW_HARDENING_ID
        ),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == ST04_SURVEY_FIRST_RETRIEVAL_POLICY_STABILIZATION_ID
    assert action["phase"] == "P11"
    assert action["risk"] == "medium"
    assert "survey-first retrieval" in action["objective"]
    assert ST03_LG10_BOUNDARY_PREVIEW_HARDENING_ID in action["reason"]


def test_next_action_after_st05_advances_to_zotero_dry_run_stabilization_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        *[
            _non_benchmark_stabilization_slice(module, slice_id)
            for slice_id in (
                ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY_ID,
                ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE_ID,
                ST03_LG10_BOUNDARY_PREVIEW_HARDENING_ID,
                ST04_SURVEY_FIRST_RETRIEVAL_POLICY_STABILIZATION_ID,
                ST05_LG9_CONTRACT_GUARD_PRODUCTIZATION_ID,
            )
        ],
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == ST06_ZOTERO_SERVICE_DRY_RUN_STABILIZATION_ID
    assert action["phase"] == "P11"
    assert action["risk"] == "high"
    assert "Zotero service routing" in action["objective"]
    assert ST05_LG9_CONTRACT_GUARD_PRODUCTIZATION_ID in action["reason"]


def test_next_action_after_st06_advances_to_runtime_selfdev_tooling_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        *[
            _non_benchmark_stabilization_slice(module, slice_id)
            for slice_id in (
                ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY_ID,
                ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE_ID,
                ST03_LG10_BOUNDARY_PREVIEW_HARDENING_ID,
                ST04_SURVEY_FIRST_RETRIEVAL_POLICY_STABILIZATION_ID,
                ST05_LG9_CONTRACT_GUARD_PRODUCTIZATION_ID,
                ST06_ZOTERO_SERVICE_DRY_RUN_STABILIZATION_ID,
            )
        ],
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == ST07_RUNTIME_SELFDEV_TOOLING_STABLE_COMPONENTS_ID
    assert action["phase"] == "P11"
    assert action["risk"] == "low"
    assert "runtime-shell and self-dev automation helpers" in action["objective"]
    assert ST06_ZOTERO_SERVICE_DRY_RUN_STABILIZATION_ID in action["reason"]


def test_next_action_after_st07_advances_to_non_benchmark_closeout_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        *[
            _non_benchmark_stabilization_slice(module, slice_id)
            for slice_id in (
                ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY_ID,
                ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE_ID,
                ST03_LG10_BOUNDARY_PREVIEW_HARDENING_ID,
                ST04_SURVEY_FIRST_RETRIEVAL_POLICY_STABILIZATION_ID,
                ST05_LG9_CONTRACT_GUARD_PRODUCTIZATION_ID,
                ST06_ZOTERO_SERVICE_DRY_RUN_STABILIZATION_ID,
                ST07_RUNTIME_SELFDEV_TOOLING_STABLE_COMPONENTS_ID,
            )
        ],
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == ST08_NON_BENCHMARK_STABILIZATION_CLOSEOUT_ID
    assert action["phase"] == "P11"
    assert action["risk"] == "low"
    assert "Close out LG11 non-benchmark stabilization" in action["objective"]
    assert ST07_RUNTIME_SELFDEV_TOOLING_STABLE_COMPONENTS_ID in action["reason"]


def test_next_action_after_st08_creates_local_autonomy_goal1_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        *[
            _non_benchmark_stabilization_slice(module, slice_id)
            for slice_id in module.NON_BENCHMARK_STABILIZATION_SLICE_IDS
        ],
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == G01_LOCAL_AUTONOMY_CONTROL_PLANE_ID
    assert action["phase"] == "P12"
    assert action["risk"] == "high"
    assert "local autonomy preapproval policy" in action["objective"]
    assert "approved all future local gates" in action["reason"]
    assert "Pre-approved" in action["human_gate"]
    assert "commit, push, PR" in action["human_gate"]


def test_next_action_after_local_autonomy_goal1_creates_goal2_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        *[
            _non_benchmark_stabilization_slice(module, slice_id)
            for slice_id in module.NON_BENCHMARK_STABILIZATION_SLICE_IDS
        ],
        _local_autonomy_goal1_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == G02_DURABLE_SEMANTICS_LOCAL_IMPLEMENTATION_ID
    assert action["phase"] == "P12"
    assert action["risk"] == "high"
    assert "executable local durable semantics" in action["objective"]
    assert "Goal 1 is complete" in action["reason"]
    assert "Pre-approved" in action["human_gate"]


def test_next_action_after_local_autonomy_goal2_creates_goal3_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        *[
            _non_benchmark_stabilization_slice(module, slice_id)
            for slice_id in module.NON_BENCHMARK_STABILIZATION_SLICE_IDS
        ],
        _local_autonomy_goal1_slice(module, "done"),
        _local_autonomy_goal2_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == G03_PRODUCTIZATION_ZOTERO_LOCAL_PRODUCTIZATION_ID
    assert action["phase"] == "P12"
    assert action["risk"] == "high"
    assert "productization/Zotero" in action["objective"]
    assert "Goal 2 is complete" in action["reason"]
    assert "Pre-approved" in action["human_gate"]


def test_next_action_after_local_autonomy_goal3_creates_goal4_slice():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        *[
            _non_benchmark_stabilization_slice(module, slice_id)
            for slice_id in module.NON_BENCHMARK_STABILIZATION_SLICE_IDS
        ],
        _local_autonomy_goal1_slice(module, "done"),
        _local_autonomy_goal2_slice(module, "done"),
        _local_autonomy_goal3_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "create_slice"
    assert action["slice_id"] == G04_PRIVATE_BENCHMARK_PERFORMANCE_GOVERNANCE_ID
    assert action["phase"] == "P12"
    assert action["risk"] == "high"
    assert "private benchmark/performance governance" in action["objective"]
    assert "Goal 3 is complete" in action["reason"]
    assert "Pre-approved" in action["human_gate"]


def test_next_action_after_local_autonomy_goal4_reports_final_boundary():
    module = load_script_module()
    recovered_slices = [
        *_lg10_recovered_slices_through_k181(module),
        _lg10_boundary_preview_batch_gate_slice(module, "done"),
        _lg10_cli_boundary_preview_slice(module, "done"),
        _lg10_mcp_boundary_preview_slice(module, "done"),
        _lg10_http_preview_gate_slice(module, "done"),
        _lg10_http_boundary_preview_slice(module, "done"),
        _lg10_python_facade_preview_gate_slice(module, "done"),
        _lg10_python_facade_boundary_preview_slice(module, "done"),
        _lg10_skills_docs_preview_gate_slice(module, "done"),
        _lg10_skills_docs_boundary_preview_slice(module, "done"),
        _lg10_doctor_preview_gate_slice(module, "done"),
        _lg10_doctor_boundary_preview_slice(module, "done"),
        _lg10_showcase_preview_gate_slice(module, "done"),
        _lg10_showcase_boundary_preview_slice(module, "done"),
        _post_lg10_mainline_closeout_slice(module, "done"),
        *[
            _non_benchmark_stabilization_slice(module, slice_id)
            for slice_id in module.NON_BENCHMARK_STABILIZATION_SLICE_IDS
        ],
        _local_autonomy_goal1_slice(module, "done"),
        _local_autonomy_goal2_slice(module, "done"),
        _local_autonomy_goal3_slice(module, "done"),
        _local_autonomy_goal4_slice(module, "done"),
    ]

    action = module.suggest_next_action(
        recovered_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert action["action"] == "complete_local_autonomy_goal_4"
    assert action["slice_id"] == G04_PRIVATE_BENCHMARK_PERFORMANCE_GOVERNANCE_ID
    assert "Goal 4 is complete" in action["reason"]
    assert "final verification" in action["human_gate"]


def test_next_action_batch_risk_flags_wait_for_gate():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        selfdev_batch_risk_flags={
            "public_surface_changed": True,
            "storage_or_provenance_changed": True,
            "orchestrator_gate_changed": True,
            "benchmark_claim_changed": True,
            "dependency_changed": True,
        },
    )

    assert action["action"] == "wait_for_gate"
    assert "risk flags do not match" in action["reason"]
    assert "public_surface_changed" in action["reason"]
    assert "storage_or_provenance_changed" in action["reason"]
    assert "orchestrator_gate_changed" in action["reason"]
    assert "benchmark_claim_changed" in action["reason"]
    assert "dependency_changed" in action["reason"]


def test_next_action_batch_test_failures_wait_for_gate():
    module = load_script_module()
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
    )

    action = module.suggest_next_action(
        completed_slices,
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
        selfdev_batch_failed_test_attempts=2,
    )

    assert action["action"] == "wait_for_gate"
    assert "focused tests failed twice" in action["reason"]
    assert "fresh gate" in action["human_gate"]


def test_status_reports_next_action_boundary_when_no_todo(monkeypatch, capsys):
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id=K122_SLICE_ID,
        phase="P6",
        status="done",
        risk="high",
        parallel="no",
        objective="Completed first checkpoint source.",
        allowed_files="runtime files",
        tests="focused tests",
        human_gate="none",
    )
    monkeypatch.setattr(module, "load_slices", lambda: [completed_slice])
    monkeypatch.setattr(module, "git_changed_files", lambda: [])
    monkeypatch.setattr(
        module,
        "suggest_next_action",
        lambda slices, **kwargs: {
            "action": "wait_for_gate",
            "slice_id": K122_SLICE_ID,
            "phase": "P6",
            "risk": "high",
            "objective": (
                "LG6 runtime-shell P6B first live runtime event source is complete."
            ),
            "reason": "first source complete",
            "human_gate": "fresh gate required",
        },
    )

    result = module.main(["status"])

    captured = capsys.readouterr()
    assert result == 0
    assert "Next action: wait_for_gate" in captured.out
    assert f"Boundary slice: {K122_SLICE_ID}" in captured.out
    assert "Objective: LG6 runtime-shell P6B first live runtime event source" in (
        captured.out
    )


def test_status_command_appends_selfdev_runtime_event(monkeypatch, tmp_path, capsys):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: completed_slices)
    monkeypatch.setattr(module, "git_changed_files", lambda: ["docs/example.md"])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T063300Z")

    result = module.main(["status"])

    captured = capsys.readouterr()
    event_id = f"selfdev_status:{K133_STATUS_SOURCE_ID}:20260610T063300Z"
    stored = _read_runtime_event_by_event_id(db, event_id)
    by_job = _read_runtime_events(db, job_id=K133_STATUS_SOURCE_ID)

    assert result == 0
    assert "Next action: create_slice" in captured.out
    assert f"Boundary slice: {K133_STATUS_SOURCE_ID}" in captured.out
    assert stored is not None
    assert stored.record.event_id == event_id
    assert stored.record.event_type == "selfdev.status_reported"
    assert stored.record.created_at == "20260610T063300Z"
    assert stored.record.origin_surface == "self_dev"
    assert stored.record.job_id == K133_STATUS_SOURCE_ID
    assert stored.record.artifact_refs == (module._display_path(module.SLICES_FILE),)
    assert stored.record.payload == {
        "action": "create_slice",
        "dirty_file_count": 1,
        "filename": module.SLICES_FILE.name,
        "phase": "P6",
        "reason": (
            "K132 batch gate is active; this is a whitelisted homogeneous "
            "self-dev runtime event source inside the approved batch window."
        ),
        "risk": "high",
        "risk_flags": {
            "benchmark_claim_changed": False,
            "dependency_changed": False,
            "orchestrator_gate_changed": False,
            "public_surface_changed": False,
            "storage_or_provenance_changed": False,
        },
        "slice_id": K133_STATUS_SOURCE_ID,
    }
    assert [event.record.event_id for event in by_job] == [event_id]
    assert stored.metadata == {
        "action": "create_slice",
        "dirty_file_count": 1,
        "phase": "P6",
        "risk": "high",
        "risk_flags": {
            "benchmark_claim_changed": False,
            "dependency_changed": False,
            "orchestrator_gate_changed": False,
            "public_surface_changed": False,
            "storage_or_provenance_changed": False,
        },
        "slice_id": K133_STATUS_SOURCE_ID,
        "slices_path": module._display_path(module.SLICES_FILE),
    }


def test_status_runtime_event_metadata_json_is_stable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: completed_slices)
    monkeypatch.setattr(
        module,
        "git_changed_files",
        lambda: [
            ".rh-selfdev/slices.md",
            ".rh-selfdev/handoffs/K133.md",
        ],
    )
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T063301Z")

    result = module.main(["status"])

    capsys.readouterr()
    assert result == 0
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_status:{K133_STATUS_SOURCE_ID}:20260610T063301Z",),
        ).fetchone()
    finally:
        conn.close()

    expected_risk_flags = {
        "benchmark_claim_changed": False,
        "dependency_changed": False,
        "orchestrator_gate_changed": False,
        "public_surface_changed": False,
        "storage_or_provenance_changed": False,
    }
    assert row is not None
    assert row["payload_json"] == json.dumps(
        {
            "action": "create_slice",
            "dirty_file_count": 2,
            "filename": module.SLICES_FILE.name,
            "phase": "P6",
            "reason": (
                "K132 batch gate is active; this is a whitelisted homogeneous "
                "self-dev runtime event source inside the approved batch window."
            ),
            "risk": "high",
            "risk_flags": expected_risk_flags,
            "slice_id": K133_STATUS_SOURCE_ID,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert row["metadata_json"] == json.dumps(
        {
            "action": "create_slice",
            "dirty_file_count": 2,
            "phase": "P6",
            "risk": "high",
            "risk_flags": expected_risk_flags,
            "slice_id": K133_STATUS_SOURCE_ID,
            "slices_path": module._display_path(module.SLICES_FILE),
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_status_runtime_event_duplicate_timestamp_is_nonfatal(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: completed_slices)
    monkeypatch.setattr(module, "git_changed_files", lambda: [])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T063302Z")

    first = module.main(["status"])
    second = module.main(["status"])

    capsys.readouterr()
    assert first == 0
    assert second == 0
    conn = db.connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_status:{K133_STATUS_SOURCE_ID}:20260610T063302Z",),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


def test_status_command_succeeds_when_runtime_event_store_unavailable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db_path = tmp_path / "unmigrated.db"
    completed_slices = _runtime_event_store_completed_slices(
        module,
        K132_BATCH_GATE_ID,
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setattr(module, "load_slices", lambda: completed_slices)
    monkeypatch.setattr(module, "git_changed_files", lambda: [])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T063303Z")

    result = module.main(["status"])

    captured = capsys.readouterr()
    assert result == 0
    assert "Next action: create_slice" in captured.out
    assert f"Boundary slice: {K133_STATUS_SOURCE_ID}" in captured.out


def test_cloud_command_appends_selfdev_runtime_event(monkeypatch, tmp_path, capsys):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [_cloud_command_slice(module)])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T064300Z")

    result = module.main(
        [
            "cloud-command",
            K134_CLOUD_COMMAND_SOURCE_ID,
            "--env",
            "env_123",
            "--branch",
            "selfdev/k134",
            "--attempts",
            "2",
        ]
    )

    captured = capsys.readouterr()
    event_id = f"selfdev_cloud_command:{K134_CLOUD_COMMAND_SOURCE_ID}:20260610T064300Z"
    stored = _read_runtime_event_by_event_id(db, event_id)
    by_job = _read_runtime_events(db, job_id=K134_CLOUD_COMMAND_SOURCE_ID)

    assert result == 0
    assert captured.out.startswith("codex\ncloud\nexec\n")
    assert "env_123" in captured.out
    assert "selfdev/k134" in captured.out
    assert stored is not None
    assert stored.record.event_id == event_id
    assert stored.record.event_type == "selfdev.cloud_command_rendered"
    assert stored.record.created_at == "20260610T064300Z"
    assert stored.record.origin_surface == "self_dev"
    assert stored.record.job_id == K134_CLOUD_COMMAND_SOURCE_ID
    assert stored.record.tool_name == "rh-selfdev cloud-command"
    assert stored.record.artifact_refs == (module._display_path(module.SLICES_FILE),)
    assert stored.record.payload == {
        "attempts": 2,
        "branch": "selfdev/k134",
        "command_argc": 10,
        "environment_id_present": True,
        "filename": module.SLICES_FILE.name,
        "slice_id": K134_CLOUD_COMMAND_SOURCE_ID,
    }
    assert "prompt" not in stored.record.payload
    assert [event.record.event_id for event in by_job] == [event_id]
    assert stored.metadata == {
        "attempts": 2,
        "branch": "selfdev/k134",
        "command_argc": 10,
        "environment_id_present": True,
        "slice_id": K134_CLOUD_COMMAND_SOURCE_ID,
        "slices_path": module._display_path(module.SLICES_FILE),
    }


def test_cloud_command_runtime_event_metadata_json_is_stable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [_cloud_command_slice(module)])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T064301Z")

    result = module.main(
        [
            "cloud-command",
            K134_CLOUD_COMMAND_SOURCE_ID,
            "--env",
            "env_abc",
            "--branch",
            "selfdev/k134",
        ]
    )

    capsys.readouterr()
    assert result == 0
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_cloud_command:{K134_CLOUD_COMMAND_SOURCE_ID}:20260610T064301Z",),
        ).fetchone()
    finally:
        conn.close()

    expected = {
        "attempts": 1,
        "branch": "selfdev/k134",
        "command_argc": 10,
        "environment_id_present": True,
        "slice_id": K134_CLOUD_COMMAND_SOURCE_ID,
    }
    assert row is not None
    assert row["payload_json"] == json.dumps(
        {
            **expected,
            "filename": module.SLICES_FILE.name,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert row["metadata_json"] == json.dumps(
        {
            **expected,
            "slices_path": module._display_path(module.SLICES_FILE),
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_cloud_command_runtime_event_duplicate_timestamp_is_nonfatal(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [_cloud_command_slice(module)])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T064302Z")

    command = [
        "cloud-command",
        K134_CLOUD_COMMAND_SOURCE_ID,
        "--env",
        "env_123",
        "--branch",
        "selfdev/k134",
    ]
    first = module.main(command)
    second = module.main(command)

    capsys.readouterr()
    assert first == 0
    assert second == 0
    conn = db.connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_cloud_command:{K134_CLOUD_COMMAND_SOURCE_ID}:20260610T064302Z",),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


def test_cloud_command_succeeds_when_runtime_event_store_unavailable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db_path = tmp_path / "unmigrated.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [_cloud_command_slice(module)])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T064303Z")

    result = module.main(
        [
            "cloud-command",
            K134_CLOUD_COMMAND_SOURCE_ID,
            "--env",
            "env_123",
            "--branch",
            "selfdev/k134",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.startswith("codex\ncloud\nexec\n")
    assert "selfdev/k134" in captured.out


def test_codex_command_appends_selfdev_runtime_event(monkeypatch, tmp_path, capsys):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    worktree_path = tmp_path / "worktree"
    prompt_path = tmp_path / "prompt.md"
    output_path = tmp_path / "output.jsonl"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [_codex_command_slice(module)])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T064500Z")

    result = module.main(
        [
            "codex-command",
            K135_CODEX_COMMAND_SOURCE_ID,
            "--worktree",
            str(worktree_path),
            "--prompt-path",
            str(prompt_path),
            "--output",
            str(output_path),
            "--model",
            "gpt-5.4",
        ]
    )

    captured = capsys.readouterr()
    event_id = f"selfdev_codex_command:{K135_CODEX_COMMAND_SOURCE_ID}:20260610T064500Z"
    stored = _read_runtime_event_by_event_id(db, event_id)
    by_job = _read_runtime_events(db, job_id=K135_CODEX_COMMAND_SOURCE_ID)

    assert result == 0
    assert captured.out.startswith("codex\nexec\n--json\n")
    assert str(worktree_path) in captured.out
    assert str(output_path) in captured.out
    assert str(prompt_path) not in captured.out
    assert stored is not None
    assert stored.record.event_id == event_id
    assert stored.record.event_type == "selfdev.codex_command_rendered"
    assert stored.record.created_at == "20260610T064500Z"
    assert stored.record.origin_surface == "self_dev"
    assert stored.record.job_id == K135_CODEX_COMMAND_SOURCE_ID
    assert stored.record.tool_name == "rh-selfdev codex-command"
    assert stored.record.artifact_refs == (module._display_path(module.SLICES_FILE),)
    assert stored.record.payload == {
        "command_argc": 14,
        "filename": module.SLICES_FILE.name,
        "model": "gpt-5.4",
        "output_path": str(output_path),
        "prompt_path": str(prompt_path),
        "slice_id": K135_CODEX_COMMAND_SOURCE_ID,
        "worktree_path": str(worktree_path),
    }
    assert "prompt_text" not in stored.record.payload
    assert [event.record.event_id for event in by_job] == [event_id]
    assert stored.metadata == {
        "command_argc": 14,
        "model": "gpt-5.4",
        "output_path": str(output_path),
        "prompt_path": str(prompt_path),
        "slice_id": K135_CODEX_COMMAND_SOURCE_ID,
        "slices_path": module._display_path(module.SLICES_FILE),
        "worktree_path": str(worktree_path),
    }


def test_codex_command_runtime_event_metadata_json_is_stable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    worktree_path = tmp_path / "worktree"
    prompt_path = tmp_path / "prompt.md"
    output_path = tmp_path / "output.jsonl"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [_codex_command_slice(module)])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T064501Z")

    result = module.main(
        [
            "codex-command",
            K135_CODEX_COMMAND_SOURCE_ID,
            "--worktree",
            str(worktree_path),
            "--prompt-path",
            str(prompt_path),
            "--output",
            str(output_path),
        ]
    )

    capsys.readouterr()
    assert result == 0
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_codex_command:{K135_CODEX_COMMAND_SOURCE_ID}:20260610T064501Z",),
        ).fetchone()
    finally:
        conn.close()

    expected = {
        "command_argc": 12,
        "output_path": str(output_path),
        "prompt_path": str(prompt_path),
        "slice_id": K135_CODEX_COMMAND_SOURCE_ID,
        "worktree_path": str(worktree_path),
    }
    assert row is not None
    assert row["payload_json"] == json.dumps(
        {
            **expected,
            "filename": module.SLICES_FILE.name,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert row["metadata_json"] == json.dumps(
        {
            **expected,
            "model": None,
            "slices_path": module._display_path(module.SLICES_FILE),
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_codex_command_runtime_event_duplicate_timestamp_is_nonfatal(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    worktree_path = tmp_path / "worktree"
    prompt_path = tmp_path / "prompt.md"
    output_path = tmp_path / "output.jsonl"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [_codex_command_slice(module)])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T064502Z")

    command = [
        "codex-command",
        K135_CODEX_COMMAND_SOURCE_ID,
        "--worktree",
        str(worktree_path),
        "--prompt-path",
        str(prompt_path),
        "--output",
        str(output_path),
    ]
    first = module.main(command)
    second = module.main(command)

    capsys.readouterr()
    assert first == 0
    assert second == 0
    conn = db.connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_codex_command:{K135_CODEX_COMMAND_SOURCE_ID}:20260610T064502Z",),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


def test_codex_command_succeeds_when_runtime_event_store_unavailable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db_path = tmp_path / "unmigrated.db"
    worktree_path = tmp_path / "worktree"
    prompt_path = tmp_path / "prompt.md"
    output_path = tmp_path / "output.jsonl"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [_codex_command_slice(module)])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T064503Z")

    result = module.main(
        [
            "codex-command",
            K135_CODEX_COMMAND_SOURCE_ID,
            "--worktree",
            str(worktree_path),
            "--prompt-path",
            str(prompt_path),
            "--output",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.startswith("codex\nexec\n--json\n")
    assert str(worktree_path) in captured.out
    assert str(output_path) in captured.out


def test_cloud_submit_appends_selfdev_runtime_event_on_success(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return module.subprocess.CompletedProcess(
            command,
            0,
            stdout="cloud task submitted: task_123\n",
            stderr="queued\n",
        )

    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [_cloud_submit_slice(module)])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T101500Z")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "cloud-submit",
            K141_CLOUD_SUBMIT_SOURCE_ID,
            "--env",
            "env_secret_123",
            "--branch",
            "selfdev/k141",
            "--attempts",
            "2",
        ]
    )

    captured = capsys.readouterr()
    started_event_id = (
        f"selfdev_cloud_submit_started:{K141_CLOUD_SUBMIT_SOURCE_ID}:20260610T101500Z"
    )
    event_id = f"selfdev_cloud_submit:{K141_CLOUD_SUBMIT_SOURCE_ID}:20260610T101500Z"
    stored = _read_runtime_event_by_event_id(db, event_id)
    by_job = _read_runtime_events(db, job_id=K141_CLOUD_SUBMIT_SOURCE_ID)

    assert result == 0
    assert captured.out == "cloud task submitted: task_123\n"
    assert captured.err == "queued\n"
    assert len(calls) == 1
    assert calls[0][1] == {
        "cwd": module.REPO_ROOT,
        "check": False,
        "capture_output": True,
        "text": True,
    }
    assert calls[0][0][:6] == [
        "codex",
        "cloud",
        "exec",
        "--env",
        "env_secret_123",
        "--branch",
    ]
    assert stored is not None
    assert stored.record.event_id == event_id
    assert stored.record.event_type == "selfdev.cloud_submit_recorded"
    assert stored.record.created_at == "20260610T101500Z"
    assert stored.record.origin_surface == "self_dev"
    assert stored.record.job_id == K141_CLOUD_SUBMIT_SOURCE_ID
    assert stored.record.tool_name == "rh-selfdev cloud-submit"
    assert stored.record.artifact_refs == (module._display_path(module.SLICES_FILE),)
    assert stored.record.payload == {
        "attempts": 2,
        "branch": "selfdev/k141",
        "command_argc": 10,
        "environment_id_present": True,
        "filename": module.SLICES_FILE.name,
        "returncode": 0,
        "slice_id": K141_CLOUD_SUBMIT_SOURCE_ID,
    }
    assert "env_secret_123" not in json.dumps(stored.record.payload)
    assert "task_123" not in json.dumps(stored.record.payload)
    assert "queued" not in json.dumps(stored.record.payload)
    assert [event.record.event_id for event in by_job] == [started_event_id, event_id]
    assert stored.metadata == {
        "attempts": 2,
        "branch": "selfdev/k141",
        "command_argc": 10,
        "environment_id_present": True,
        "returncode": 0,
        "slice_id": K141_CLOUD_SUBMIT_SOURCE_ID,
        "slices_path": module._display_path(module.SLICES_FILE),
    }


def test_cloud_submit_appends_started_event_before_subprocess(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    started_event_id = (
        f"selfdev_cloud_submit_started:{K143_CLOUD_SUBMIT_STARTED_SOURCE_ID}:"
        "20260610T104500Z"
    )

    def fake_run(command, **kwargs):
        assert _read_runtime_event_by_event_id(db, started_event_id) is not None
        return module.subprocess.CompletedProcess(
            command,
            0,
            stdout="cloud task submitted: task_456\n",
            stderr="",
        )

    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(
        module,
        "load_slices",
        lambda: [_cloud_submit_started_slice(module)],
    )
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T104500Z")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "cloud-submit",
            K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
            "--env",
            "env_secret_123",
            "--branch",
            "selfdev/k143",
            "--attempts",
            "2",
        ]
    )

    captured = capsys.readouterr()
    success_event_id = (
        f"selfdev_cloud_submit:{K143_CLOUD_SUBMIT_STARTED_SOURCE_ID}:20260610T104500Z"
    )
    started = _read_runtime_event_by_event_id(db, started_event_id)
    success = _read_runtime_event_by_event_id(db, success_event_id)
    by_job = _read_runtime_events(db, job_id=K143_CLOUD_SUBMIT_STARTED_SOURCE_ID)

    assert result == 0
    assert captured.out == "cloud task submitted: task_456\n"
    assert started is not None
    assert started.record.event_type == "selfdev.cloud_submit_started"
    assert started.record.payload == {
        "attempts": 2,
        "branch": "selfdev/k143",
        "command_argc": 10,
        "environment_id_present": True,
        "filename": module.SLICES_FILE.name,
        "slice_id": K143_CLOUD_SUBMIT_STARTED_SOURCE_ID,
    }
    assert "env_secret_123" not in json.dumps(started.record.payload)
    assert "task_456" not in json.dumps(started.record.payload)
    assert success is not None
    assert success.record.event_type == "selfdev.cloud_submit_recorded"
    assert [event.record.event_id for event in by_job] == [
        started_event_id,
        success_event_id,
    ]


def test_cloud_submit_success_sequence_uses_attempt_timestamp_for_readback_order(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    timestamps = iter(("20260610T121000Z", "20260610T120900Z"))

    def fake_run(command, **kwargs):
        return module.subprocess.CompletedProcess(
            command,
            0,
            stdout="cloud task submitted: task_sequence_secret\n",
            stderr="queued sequence output\n",
        )

    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(
        module,
        "load_slices",
        lambda: [_cloud_submit_sequence_slice(module)],
    )
    monkeypatch.setattr(module, "timestamp", lambda: next(timestamps))
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "cloud-submit",
            K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID,
            "--env",
            "env_sequence_secret",
            "--branch",
            "selfdev/k145",
        ]
    )

    captured = capsys.readouterr()
    started_event_id = (
        f"selfdev_cloud_submit_started:{K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID}:"
        "20260610T121000Z"
    )
    success_event_id = (
        f"selfdev_cloud_submit:{K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID}:"
        "20260610T121000Z"
    )
    by_job = _read_runtime_events(db, job_id=K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID)

    assert result == 0
    assert captured.out == "cloud task submitted: task_sequence_secret\n"
    assert captured.err == "queued sequence output\n"
    assert [event.record.event_id for event in by_job] == [
        started_event_id,
        success_event_id,
    ]
    assert [event.record.created_at for event in by_job] == [
        "20260610T121000Z",
        "20260610T121000Z",
    ]
    event_json = json.dumps(
        [
            {"metadata": event.metadata, "payload": event.record.payload}
            for event in by_job
        ],
        sort_keys=True,
    )
    assert "env_sequence_secret" not in event_json
    assert "task_sequence_secret" not in event_json
    assert "queued sequence output" not in event_json


def test_cloud_submit_records_failure_event_without_success_event(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)

    def fake_run(command, **kwargs):
        return module.subprocess.CompletedProcess(
            command,
            17,
            stdout="",
            stderr="cloud rejected\n",
        )

    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(
        module,
        "load_slices",
        lambda: [_cloud_submit_failure_slice(module)],
    )
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T101501Z")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "cloud-submit",
            K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
            "--env",
            "env_secret_123",
            "--branch",
            "selfdev/k142",
        ]
    )

    captured = capsys.readouterr()
    success_event_id = (
        f"selfdev_cloud_submit:{K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID}:20260610T101501Z"
    )
    failure_event_id = (
        f"selfdev_cloud_submit_failed:{K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID}:"
        "20260610T101501Z"
    )
    stored = _read_runtime_event_by_event_id(db, failure_event_id)

    assert result == 17
    assert captured.err == "cloud rejected\n"
    assert _read_runtime_event_by_event_id(db, success_event_id) is None
    assert stored is not None
    assert stored.record.event_id == failure_event_id
    assert stored.record.event_type == "selfdev.cloud_submit_failed"
    assert stored.record.error_code == "cloud_submit_failed"
    assert stored.record.job_id == K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID
    assert stored.record.payload == {
        "attempts": 1,
        "branch": "selfdev/k142",
        "command_argc": 10,
        "environment_id_present": True,
        "filename": module.SLICES_FILE.name,
        "returncode": 17,
        "slice_id": K142_CLOUD_SUBMIT_FAILURE_SOURCE_ID,
    }
    assert "env_secret_123" not in json.dumps(stored.record.payload)
    assert "cloud rejected" not in json.dumps(stored.record.payload)


def test_cloud_submit_failure_sequence_uses_attempt_timestamp_for_readback_order(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    timestamps = iter(("20260610T121500Z", "20260610T121400Z"))

    def fake_run(command, **kwargs):
        return module.subprocess.CompletedProcess(
            command,
            23,
            stdout="",
            stderr="cloud rejected with sequence secret\n",
        )

    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(
        module,
        "load_slices",
        lambda: [_cloud_submit_sequence_slice(module)],
    )
    monkeypatch.setattr(module, "timestamp", lambda: next(timestamps))
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "cloud-submit",
            K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID,
            "--env",
            "env_sequence_secret",
            "--branch",
            "selfdev/k145",
        ]
    )

    captured = capsys.readouterr()
    started_event_id = (
        f"selfdev_cloud_submit_started:{K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID}:"
        "20260610T121500Z"
    )
    success_event_id = (
        f"selfdev_cloud_submit:{K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID}:"
        "20260610T121500Z"
    )
    failure_event_id = (
        f"selfdev_cloud_submit_failed:{K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID}:"
        "20260610T121500Z"
    )
    by_job = _read_runtime_events(db, job_id=K145_CLOUD_SUBMIT_SEQUENCE_HARDENING_ID)

    assert result == 23
    assert captured.err == "cloud rejected with sequence secret\n"
    assert _read_runtime_event_by_event_id(db, success_event_id) is None
    assert [event.record.event_id for event in by_job] == [
        started_event_id,
        failure_event_id,
    ]
    assert [event.record.created_at for event in by_job] == [
        "20260610T121500Z",
        "20260610T121500Z",
    ]
    event_json = json.dumps(
        [
            {"metadata": event.metadata, "payload": event.record.payload}
            for event in by_job
        ],
        sort_keys=True,
    )
    assert "env_sequence_secret" not in event_json
    assert "cloud rejected with sequence secret" not in event_json


def test_cloud_submit_succeeds_when_runtime_event_store_unavailable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db_path = tmp_path / "unmigrated.db"

    def fake_run(command, **kwargs):
        return module.subprocess.CompletedProcess(
            command,
            0,
            stdout="cloud task submitted\n",
            stderr="",
        )

    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [_cloud_submit_slice(module)])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T101502Z")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "cloud-submit",
            K141_CLOUD_SUBMIT_SOURCE_ID,
            "--env",
            "env_secret_123",
            "--branch",
            "selfdev/k141",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "cloud task submitted\n"


def test_cloud_submit_success_ignores_runtime_event_append_exceptions(
    monkeypatch,
    capsys,
):
    module = load_script_module()
    calls = []

    def raise_append(**kwargs):
        raise RuntimeError("runtime event append failed")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return module.subprocess.CompletedProcess(
            command,
            0,
            stdout="cloud task submitted despite append failure\n",
            stderr="queued despite append failure\n",
        )

    monkeypatch.setattr(
        module,
        "load_slices",
        lambda: [_cloud_submit_store_failure_slice(module)],
    )
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T123000Z")
    monkeypatch.setattr(
        module,
        "_append_cloud_submit_started_runtime_event",
        raise_append,
    )
    monkeypatch.setattr(module, "_append_cloud_submit_runtime_event", raise_append)
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "cloud-submit",
            K146_CLOUD_SUBMIT_STORE_FAILURE_HARDENING_ID,
            "--env",
            "env_secret_123",
            "--branch",
            "selfdev/k146",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "cloud task submitted despite append failure\n"
    assert captured.err == "queued despite append failure\n"
    assert len(calls) == 1


def test_cloud_submit_failure_ignores_runtime_event_append_exceptions(
    monkeypatch,
    capsys,
):
    module = load_script_module()
    calls = []

    def raise_append(**kwargs):
        raise RuntimeError("runtime event append failed")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return module.subprocess.CompletedProcess(
            command,
            29,
            stdout="partial cloud output despite append failure\n",
            stderr="cloud rejected despite append failure\n",
        )

    monkeypatch.setattr(
        module,
        "load_slices",
        lambda: [_cloud_submit_store_failure_slice(module)],
    )
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T123001Z")
    monkeypatch.setattr(
        module,
        "_append_cloud_submit_started_runtime_event",
        raise_append,
    )
    monkeypatch.setattr(
        module,
        "_append_cloud_submit_failure_runtime_event",
        raise_append,
    )
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.main(
        [
            "cloud-submit",
            K146_CLOUD_SUBMIT_STORE_FAILURE_HARDENING_ID,
            "--env",
            "env_secret_123",
            "--branch",
            "selfdev/k146",
        ]
    )

    captured = capsys.readouterr()
    assert result == 29
    assert captured.out == "partial cloud output despite append failure\n"
    assert captured.err == "cloud rejected despite append failure\n"
    assert len(calls) == 1


def test_next_action_cli_can_ignore_external_active_slice(monkeypatch, capsys):
    module = load_script_module()
    zotero_slice = module.SelfDevSlice(
        slice_id="ZOTERO_WRITE_AGENT_RUNTIME",
        phase="P3",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Zotero runtime is handled by another session.",
        allowed_files="zotero files",
        tests="zotero tests",
        human_gate="zotero gate",
    )
    completed_gate_check = module.SelfDevSlice(
        slice_id="S48_LG2_HTTP_ORCHESTRATOR_GATE_CHECK_SERVICE_ROUTING",
        phase="P3",
        status="done",
        risk="high",
        parallel="no",
        objective="Completed HTTP gate-check routing.",
        allowed_files="http",
        tests="focused tests",
        human_gate="none",
    )
    completed_shape_harness = module.SelfDevSlice(
        slice_id="S42_LG2_HTTP_DEFERRED_SHAPE_TEST_HARNESS",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed HTTP deferred-shape harness.",
        allowed_files="tests",
        tests="focused tests",
        human_gate="none",
    )
    monkeypatch.setattr(
        module,
        "load_slices",
        lambda: [completed_shape_harness, completed_gate_check, zotero_slice],
    )

    result = module.main(
        [
            "next-action",
            "--json",
            "--ignore-active-slice",
            "ZOTERO_WRITE_AGENT_RUNTIME",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert '"action": "create_slice"' in captured.out
    assert (
        '"slice_id": "S49_LG2_HTTP_ORCHESTRATOR_STATUS_SERVICE_ROUTING"' in captured.out
    )


def test_checkpoint_records_suggested_next_action_when_no_todo():
    module = load_script_module()
    completed_slice = module.SelfDevSlice(
        slice_id="S21_DONE",
        phase="P3",
        status="done",
        risk="low",
        parallel="no",
        objective="Completed automation.",
        allowed_files="scripts",
        tests="focused tests",
        human_gate="none",
    )

    text = module.build_checkpoint_text(
        slices=[completed_slice],
        changed_files=[],
        transport_coverage_exists=False,
    )

    assert "## Suggested Next Action" in text
    assert "S22_LG2_TRANSPORT_READ_INVENTORY" in text
    assert "Create one bounded slice" in text


def test_checkpoint_records_completion_boundary_when_no_todo():
    module = load_script_module()
    completed_slices = [
        module.SelfDevSlice(
            slice_id=slice_id,
            phase="P5",
            status="done",
            risk="low",
            parallel="no",
            objective=f"Completed {slice_id}.",
            allowed_files="runtime files",
            tests="focused tests",
            human_gate="none",
        )
        for slice_id in (
            "K103_RUNTIME_EVENT_NORMALIZER_READ_MODEL",
            "K104_RUNTIME_JOB_LEDGER_READ_MODEL",
            "K105_RUNTIME_TOOL_FAILURE_GATE_NORMALIZER",
            "K106_RUNTIME_SKILL_PROVENANCE_SCANNER",
            "K107_RUNTIME_DOCTOR_READONLY_DIAGNOSTICS",
            "K108_RUNTIME_SHOWCASE_MANIFEST_NORMALIZER",
        )
    ]

    text = module.build_checkpoint_text(
        slices=completed_slices,
        changed_files=[],
        transport_coverage_exists=True,
        cli_read_shape_tests_exist=True,
    )

    assert "## Next Action Boundary" in text
    assert "complete_runtime_shell_p5" in text
    assert "P6 storage" in text
    assert "Create one bounded slice" not in text


def test_checkpoint_command_writes_output(monkeypatch, tmp_path, capsys):
    module = load_script_module()
    next_slice = module.SelfDevSlice(
        slice_id="S02_NEXT",
        phase="P1",
        status="todo",
        risk="medium",
        parallel="no",
        objective="Continue service migration.",
        allowed_files="service files",
        tests="focused tests",
        human_gate="review",
    )
    output_path = tmp_path / "checkpoint.md"
    monkeypatch.setattr(module, "load_slices", lambda: [next_slice])
    monkeypatch.setattr(module, "git_changed_files", lambda: ["docs/example.md"])

    result = module.main(
        [
            "checkpoint",
            "--output",
            str(output_path),
            "--note",
            "ready to clear",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert str(output_path) in captured.out
    assert output_path.exists()
    text = output_path.read_text(encoding="utf-8")
    assert "Next slice: S02_NEXT" in text
    assert "ready to clear" in text


def test_checkpoint_command_appends_selfdev_runtime_event(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    output_path = tmp_path / "checkpoint.md"
    slice_def = module.SelfDevSlice(
        slice_id=K122_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev checkpoint events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "git_changed_files", lambda: ["docs/example.md"])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T010203Z")

    result = module.main(
        [
            "checkpoint",
            "--output",
            str(output_path),
            "--note",
            "approved first source",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert str(output_path) in captured.out
    event_id = "selfdev_checkpoint:20260610T010203Z"
    stored = _read_runtime_event_by_event_id(db, event_id)
    by_job = _read_runtime_events(db, job_id=K122_SLICE_ID)

    assert stored is not None
    assert stored.record.event_id == event_id
    assert stored.record.event_type == "selfdev.checkpoint_created"
    assert stored.record.created_at == "20260610T010203Z"
    assert stored.record.origin_surface == "self_dev"
    assert stored.record.actor == "codex"
    assert stored.record.job_id == K122_SLICE_ID
    assert stored.record.tool_name == "rh-selfdev checkpoint"
    assert stored.record.artifact_refs == (str(output_path),)
    assert stored.record.payload == {}
    assert [event.record.event_id for event in by_job] == [event_id]
    assert stored.metadata == {
        "checkpoint_path": str(output_path),
        "dirty_file_count": 1,
        "notes": ["approved first source"],
        "risk_flags": {
            "benchmark_claim_changed": False,
            "dependency_changed": False,
            "orchestrator_gate_changed": False,
            "public_surface_changed": False,
            "storage_or_provenance_changed": False,
        },
        "slice_id": K122_SLICE_ID,
    }


def test_checkpoint_runtime_event_metadata_json_is_stable(
    monkeypatch,
    tmp_path,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    output_path = tmp_path / "checkpoint.md"
    slice_def = module.SelfDevSlice(
        slice_id=K122_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev checkpoint events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(
        module,
        "git_changed_files",
        lambda: [
            "packages/research_harness/research_harness/cli.py",
            "packages/research_harness/research_harness/storage/SCHEMA.md",
        ],
    )
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T010204Z")

    result = module.main(
        [
            "checkpoint",
            "--output",
            str(output_path),
            "--note",
            "zeta",
            "--note",
            "alpha",
        ]
    )

    assert result == 0
    expected_metadata = {
        "checkpoint_path": str(output_path),
        "dirty_file_count": 2,
        "notes": ["zeta", "alpha"],
        "risk_flags": {
            "benchmark_claim_changed": False,
            "dependency_changed": False,
            "orchestrator_gate_changed": False,
            "public_surface_changed": True,
            "storage_or_provenance_changed": True,
        },
        "slice_id": K122_SLICE_ID,
    }
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            ("selfdev_checkpoint:20260610T010204Z",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["payload_json"] == "{}"
    assert row["metadata_json"] == json.dumps(
        expected_metadata,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_checkpoint_runtime_event_duplicate_timestamp_is_nonfatal(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    output_path = tmp_path / "checkpoint.md"
    slice_def = module.SelfDevSlice(
        slice_id=K122_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev checkpoint events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "git_changed_files", lambda: [])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T010205Z")

    first = module.main(["checkpoint", "--output", str(output_path)])
    second = module.main(["checkpoint", "--output", str(output_path)])

    captured = capsys.readouterr()
    assert first == 0
    assert second == 0
    assert str(output_path) in captured.out
    conn = db.connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM runtime_events
            WHERE event_id = ?
            """,
            ("selfdev_checkpoint:20260610T010205Z",),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


def test_checkpoint_command_succeeds_when_runtime_event_store_unavailable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db_path = tmp_path / "unmigrated.db"
    output_path = tmp_path / "checkpoint.md"
    slice_def = module.SelfDevSlice(
        slice_id=K122_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev checkpoint events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "git_changed_files", lambda: [])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T010206Z")

    result = module.main(["checkpoint", "--output", str(output_path)])

    captured = capsys.readouterr()
    assert result == 0
    assert str(output_path) in captured.out
    assert output_path.exists()
    assert "Date: 20260610T010206Z" in output_path.read_text(encoding="utf-8")


def test_handoff_command_appends_selfdev_runtime_event(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    output_path = tmp_path / f"{K123_SLICE_ID}-20260610T020304Z.md"
    slice_def = module.SelfDevSlice(
        slice_id=K123_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev handoff events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "git_changed_files", lambda: ["docs/example.md"])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T020304Z")

    result = module.main(
        [
            "handoff",
            K123_SLICE_ID,
            "--output",
            str(output_path),
            "--status",
            "done",
            "--note",
            "routed handoff source",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert str(output_path) in captured.out
    assert output_path.exists()
    event_id = f"selfdev_handoff:{K123_SLICE_ID}:20260610T020304Z"
    stored = _read_runtime_event_by_event_id(db, event_id)
    by_job = _read_runtime_events(db, job_id=K123_SLICE_ID)

    assert stored is not None
    assert stored.record.event_id == event_id
    assert stored.record.event_type == "selfdev.handoff_created"
    assert stored.record.created_at == "20260610T020304Z"
    assert stored.record.origin_surface == "self_dev"
    assert stored.record.job_id == K123_SLICE_ID
    assert stored.record.artifact_refs == (str(output_path),)
    assert stored.record.payload == {
        "filename": output_path.name,
        "status": "done",
    }
    assert [event.record.event_id for event in by_job] == [event_id]
    assert stored.metadata == {
        "dirty_file_count": 1,
        "handoff_path": str(output_path),
        "notes": ["routed handoff source"],
        "risk_flags": {
            "benchmark_claim_changed": False,
            "dependency_changed": False,
            "orchestrator_gate_changed": False,
            "public_surface_changed": False,
            "storage_or_provenance_changed": False,
        },
        "slice_id": K123_SLICE_ID,
        "status": "done",
    }


def test_handoff_runtime_event_metadata_json_is_stable(
    monkeypatch,
    tmp_path,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    output_path = tmp_path / f"{K123_SLICE_ID}-20260610T020305Z.md"
    slice_def = module.SelfDevSlice(
        slice_id=K123_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev handoff events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(
        module,
        "git_changed_files",
        lambda: [
            "packages/research_harness/research_harness/cli.py",
            "packages/research_harness/research_harness/storage/SCHEMA.md",
        ],
    )
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T020305Z")

    result = module.main(
        [
            "handoff",
            K123_SLICE_ID,
            "--output",
            str(output_path),
            "--status",
            "done",
            "--note",
            "zeta",
            "--note",
            "alpha",
        ]
    )

    assert result == 0
    expected_metadata = {
        "dirty_file_count": 2,
        "handoff_path": str(output_path),
        "notes": ["zeta", "alpha"],
        "risk_flags": {
            "benchmark_claim_changed": False,
            "dependency_changed": False,
            "orchestrator_gate_changed": False,
            "public_surface_changed": True,
            "storage_or_provenance_changed": True,
        },
        "slice_id": K123_SLICE_ID,
        "status": "done",
    }
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_handoff:{K123_SLICE_ID}:20260610T020305Z",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["payload_json"] == json.dumps(
        {
            "filename": output_path.name,
            "status": "done",
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert row["metadata_json"] == json.dumps(
        expected_metadata,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_handoff_runtime_event_duplicate_timestamp_is_nonfatal(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    output_path = tmp_path / f"{K123_SLICE_ID}-20260610T020306Z.md"
    slice_def = module.SelfDevSlice(
        slice_id=K123_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev handoff events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "git_changed_files", lambda: [])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T020306Z")

    first = module.main(["handoff", K123_SLICE_ID, "--output", str(output_path)])
    second = module.main(["handoff", K123_SLICE_ID, "--output", str(output_path)])

    captured = capsys.readouterr()
    assert first == 0
    assert second == 0
    assert str(output_path) in captured.out
    conn = db.connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_handoff:{K123_SLICE_ID}:20260610T020306Z",),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


def test_handoff_command_succeeds_when_runtime_event_store_unavailable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db_path = tmp_path / "unmigrated.db"
    output_path = tmp_path / f"{K123_SLICE_ID}-20260610T020307Z.md"
    slice_def = module.SelfDevSlice(
        slice_id=K123_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev handoff events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "git_changed_files", lambda: [])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T020307Z")

    result = module.main(["handoff", K123_SLICE_ID, "--output", str(output_path)])

    captured = capsys.readouterr()
    assert result == 0
    assert str(output_path) in captured.out
    assert output_path.exists()
    assert "Date: 20260610T020307Z" in output_path.read_text(encoding="utf-8")


def test_gate_command_appends_selfdev_runtime_event(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    gate_dir = tmp_path / "gates"
    slice_def = module.SelfDevSlice(
        slice_id=K125_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev gate report events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "GATE_DIR", gate_dir)
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T030304Z")

    result = module.main(
        [
            "gate",
            K125_SLICE_ID,
            "--task-id",
            "task-17",
            "--executor",
            "codex",
            "--changed-file",
            "docs/example.md",
            "--tests",
            "focused tests passed",
        ]
    )

    captured = capsys.readouterr()
    gate_path = gate_dir / f"{K125_SLICE_ID}-20260610T030304Z.md"
    assert result == 0
    assert str(gate_path) in captured.out
    assert gate_path.exists()
    event_id = f"selfdev_gate_report:{K125_SLICE_ID}:20260610T030304Z"
    stored = _read_runtime_event_by_event_id(db, event_id)
    by_job = _read_runtime_events(db, job_id=K125_SLICE_ID)

    assert stored is not None
    assert stored.record.event_id == event_id
    assert stored.record.event_type == "selfdev.gate_report_created"
    assert stored.record.created_at == "20260610T030304Z"
    assert stored.record.origin_surface == "self_dev"
    assert stored.record.job_id == K125_SLICE_ID
    assert stored.record.gate_decision == "approve"
    assert stored.record.artifact_refs == (str(gate_path),)
    assert stored.record.payload == {
        "filename": gate_path.name,
        "recommendation": "approve",
        "task_id": "task-17",
    }
    assert [event.record.event_id for event in by_job] == [event_id]
    assert stored.metadata == {
        "changed_file_count": 1,
        "gate_path": str(gate_path),
        "recommendation": "approve",
        "risk_flags": {
            "benchmark_claim_changed": False,
            "dependency_changed": False,
            "orchestrator_gate_changed": False,
            "public_surface_changed": False,
            "storage_or_provenance_changed": False,
        },
        "slice_id": K125_SLICE_ID,
        "task_id": "task-17",
        "tests": "focused tests passed",
    }


def test_gate_runtime_event_metadata_json_is_stable(
    monkeypatch,
    tmp_path,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    gate_dir = tmp_path / "gates"
    slice_def = module.SelfDevSlice(
        slice_id=K125_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev gate report events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "GATE_DIR", gate_dir)
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T030305Z")

    result = module.main(
        [
            "gate",
            K125_SLICE_ID,
            "--task-id",
            "task-18",
            "--executor",
            "codex",
            "--changed-file",
            "packages/research_harness/research_harness/cli.py",
            "--changed-file",
            "packages/research_harness/research_harness/storage/SCHEMA.md",
            "--tests",
            "zeta then alpha",
        ]
    )

    assert result == 0
    gate_path = gate_dir / f"{K125_SLICE_ID}-20260610T030305Z.md"
    expected_metadata = {
        "changed_file_count": 2,
        "gate_path": str(gate_path),
        "recommendation": "request_changes",
        "risk_flags": {
            "benchmark_claim_changed": False,
            "dependency_changed": False,
            "orchestrator_gate_changed": False,
            "public_surface_changed": True,
            "storage_or_provenance_changed": True,
        },
        "slice_id": K125_SLICE_ID,
        "task_id": "task-18",
        "tests": "zeta then alpha",
    }
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_gate_report:{K125_SLICE_ID}:20260610T030305Z",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["payload_json"] == json.dumps(
        {
            "filename": gate_path.name,
            "recommendation": "request_changes",
            "task_id": "task-18",
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert row["metadata_json"] == json.dumps(
        expected_metadata,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_gate_runtime_event_duplicate_timestamp_is_nonfatal(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    gate_dir = tmp_path / "gates"
    slice_def = module.SelfDevSlice(
        slice_id=K125_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev gate report events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "GATE_DIR", gate_dir)
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T030306Z")

    first = module.main(["gate", K125_SLICE_ID])
    second = module.main(["gate", K125_SLICE_ID])

    captured = capsys.readouterr()
    assert first == 0
    assert second == 0
    assert str(gate_dir / f"{K125_SLICE_ID}-20260610T030306Z.md") in captured.out
    conn = db.connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_gate_report:{K125_SLICE_ID}:20260610T030306Z",),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


def test_gate_command_succeeds_when_runtime_event_store_unavailable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db_path = tmp_path / "unmigrated.db"
    gate_dir = tmp_path / "gates"
    slice_def = module.SelfDevSlice(
        slice_id=K125_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev gate report events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setattr(module, "GATE_DIR", gate_dir)
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T030307Z")

    result = module.main(["gate", K125_SLICE_ID])

    captured = capsys.readouterr()
    gate_path = gate_dir / f"{K125_SLICE_ID}-20260610T030307Z.md"
    assert result == 0
    assert str(gate_path) in captured.out
    assert gate_path.exists()
    assert "Date: 20260610T030307Z" in gate_path.read_text(encoding="utf-8")


def test_prompt_command_appends_selfdev_runtime_event(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    prompt_dir = tmp_path / "prompts"
    slice_def = module.SelfDevSlice(
        slice_id=K127_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev prompt events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "PROMPT_DIR", prompt_dir)
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T040304Z")

    result = module.main(["prompt", K127_SLICE_ID])

    captured = capsys.readouterr()
    prompt_path = prompt_dir / f"{K127_SLICE_ID}.md"
    prompt_text = prompt_path.read_text(encoding="utf-8")
    event_id = f"selfdev_prompt:{K127_SLICE_ID}:20260610T040304Z"
    stored = _read_runtime_event_by_event_id(db, event_id)
    by_job = _read_runtime_events(db, job_id=K127_SLICE_ID)

    assert result == 0
    assert str(prompt_path) in captured.out
    assert stored is not None
    assert stored.record.event_id == event_id
    assert stored.record.event_type == "selfdev.prompt_created"
    assert stored.record.created_at == "20260610T040304Z"
    assert stored.record.origin_surface == "self_dev"
    assert stored.record.job_id == K127_SLICE_ID
    assert stored.record.artifact_refs == (str(prompt_path),)
    assert stored.record.payload == {
        "filename": prompt_path.name,
        "prompt_bytes": len(prompt_text.encode("utf-8")),
    }
    assert [event.record.event_id for event in by_job] == [event_id]
    assert stored.metadata == {
        "prompt_bytes": len(prompt_text.encode("utf-8")),
        "prompt_path": str(prompt_path),
        "slice_id": K127_SLICE_ID,
    }


def test_prompt_runtime_event_metadata_json_is_stable(
    monkeypatch,
    tmp_path,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    prompt_dir = tmp_path / "prompts"
    slice_def = module.SelfDevSlice(
        slice_id=K127_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev prompt events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "PROMPT_DIR", prompt_dir)
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T040305Z")

    result = module.main(["prompt", K127_SLICE_ID])

    assert result == 0
    prompt_path = prompt_dir / f"{K127_SLICE_ID}.md"
    prompt_text = prompt_path.read_text(encoding="utf-8")
    expected_metadata = {
        "prompt_bytes": len(prompt_text.encode("utf-8")),
        "prompt_path": str(prompt_path),
        "slice_id": K127_SLICE_ID,
    }
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_prompt:{K127_SLICE_ID}:20260610T040305Z",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["payload_json"] == json.dumps(
        {
            "filename": prompt_path.name,
            "prompt_bytes": len(prompt_text.encode("utf-8")),
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert row["metadata_json"] == json.dumps(
        expected_metadata,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_prompt_runtime_event_duplicate_timestamp_is_nonfatal(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    prompt_dir = tmp_path / "prompts"
    slice_def = module.SelfDevSlice(
        slice_id=K127_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev prompt events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "PROMPT_DIR", prompt_dir)
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T040306Z")

    first = module.main(["prompt", K127_SLICE_ID])
    second = module.main(["prompt", K127_SLICE_ID])

    captured = capsys.readouterr()
    assert first == 0
    assert second == 0
    assert str(prompt_dir / f"{K127_SLICE_ID}.md") in captured.out
    conn = db.connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_prompt:{K127_SLICE_ID}:20260610T040306Z",),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


def test_prompt_command_succeeds_when_runtime_event_store_unavailable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db_path = tmp_path / "unmigrated.db"
    prompt_dir = tmp_path / "prompts"
    slice_def = module.SelfDevSlice(
        slice_id=K127_SLICE_ID,
        phase="P6",
        status="in_progress",
        risk="high",
        parallel="no",
        objective="Route self-dev prompt events.",
        allowed_files="scripts/rh-selfdev.py",
        tests="focused tests",
        human_gate="approved",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setattr(module, "PROMPT_DIR", prompt_dir)
    monkeypatch.setattr(module, "load_slices", lambda: [slice_def])
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T040307Z")

    result = module.main(["prompt", K127_SLICE_ID])

    captured = capsys.readouterr()
    prompt_path = prompt_dir / f"{K127_SLICE_ID}.md"
    assert result == 0
    assert str(prompt_path) in captured.out
    assert prompt_path.exists()
    assert "Slice: K127_RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE" in (
        prompt_path.read_text(encoding="utf-8")
    )


def test_slice_status_command_updates_row_and_appends_selfdev_runtime_event(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    slices_file = tmp_path / "slices.md"
    _write_slice_status_fixture(slices_file)
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "SLICES_FILE", slices_file)
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T050304Z")

    result = module.main(["slice-status", K129_SLICE_ID, "in_progress"])

    captured = capsys.readouterr()
    event_id = f"selfdev_slice_status:{K129_SLICE_ID}:20260610T050304Z"
    stored = _read_runtime_event_by_event_id(db, event_id)
    by_job = _read_runtime_events(db, job_id=K129_SLICE_ID)
    updated_text = slices_file.read_text(encoding="utf-8")

    assert result == 0
    assert f"{K129_SLICE_ID}: todo -> in_progress" in captured.out
    assert f"| {K129_SLICE_ID} | P6 | in_progress | high |" in updated_text
    assert "`scripts/rh-selfdev.py`" in updated_text
    assert "`focused tests`" in updated_text
    assert stored is not None
    assert stored.record.event_id == event_id
    assert stored.record.event_type == "selfdev.slice_status_changed"
    assert stored.record.created_at == "20260610T050304Z"
    assert stored.record.origin_surface == "self_dev"
    assert stored.record.job_id == K129_SLICE_ID
    assert stored.record.artifact_refs == (str(slices_file),)
    assert stored.record.payload == {
        "filename": slices_file.name,
        "new_status": "in_progress",
        "previous_status": "todo",
    }
    assert [event.record.event_id for event in by_job] == [event_id]
    assert stored.metadata == {
        "new_status": "in_progress",
        "previous_status": "todo",
        "slice_id": K129_SLICE_ID,
        "slices_path": str(slices_file),
    }


def test_slice_status_runtime_event_metadata_json_is_stable(
    monkeypatch,
    tmp_path,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    slices_file = tmp_path / "slices.md"
    _write_slice_status_fixture(slices_file)
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "SLICES_FILE", slices_file)
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T050305Z")

    result = module.main(["slice-status", K129_SLICE_ID, "in_progress"])

    assert result == 0
    expected_metadata = {
        "new_status": "in_progress",
        "previous_status": "todo",
        "slice_id": K129_SLICE_ID,
        "slices_path": str(slices_file),
    }
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json, metadata_json
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_slice_status:{K129_SLICE_ID}:20260610T050305Z",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["payload_json"] == json.dumps(
        {
            "filename": slices_file.name,
            "new_status": "in_progress",
            "previous_status": "todo",
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert row["metadata_json"] == json.dumps(
        expected_metadata,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_slice_status_runtime_event_duplicate_timestamp_is_nonfatal(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db = _migrated_runtime_event_db(tmp_path)
    slices_file = tmp_path / "slices.md"
    _write_slice_status_fixture(slices_file)
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setattr(module, "SLICES_FILE", slices_file)
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T050306Z")

    first = module.main(["slice-status", K129_SLICE_ID, "in_progress"])
    second = module.main(["slice-status", K129_SLICE_ID, "done"])

    captured = capsys.readouterr()
    assert first == 0
    assert second == 0
    assert f"{K129_SLICE_ID}: in_progress -> done" in captured.out
    assert f"| {K129_SLICE_ID} | P6 | done | high |" in (
        slices_file.read_text(encoding="utf-8")
    )
    conn = db.connect()
    try:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM runtime_events
            WHERE event_id = ?
            """,
            (f"selfdev_slice_status:{K129_SLICE_ID}:20260610T050306Z",),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


def test_slice_status_command_succeeds_when_runtime_event_store_unavailable(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = load_script_module()
    db_path = tmp_path / "unmigrated.db"
    slices_file = tmp_path / "slices.md"
    _write_slice_status_fixture(slices_file)
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setattr(module, "SLICES_FILE", slices_file)
    monkeypatch.setattr(module, "timestamp", lambda: "20260610T050307Z")

    result = module.main(["slice-status", K129_SLICE_ID, "done"])

    captured = capsys.readouterr()
    assert result == 0
    assert f"{K129_SLICE_ID}: todo -> done" in captured.out
    assert f"| {K129_SLICE_ID} | P6 | done | high |" in (
        slices_file.read_text(encoding="utf-8")
    )
