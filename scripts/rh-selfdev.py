#!/usr/bin/env python3
"""Self-development orchestration helper for Research Harness.

The helper keeps long-running Codex work slice-based and reviewable. It avoids
shell command construction; every external command is represented as an argv
list so callers can inspect or run it safely.
"""

import argparse
import dataclasses
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "packages/research_harness"
if PACKAGE_ROOT.is_dir() and str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))
CONTROL_PLANE = REPO_ROOT / ".rh-selfdev/control-plane.md"
SLICES_FILE = REPO_ROOT / ".rh-selfdev/slices.md"
HANDOFF_DIR = REPO_ROOT / ".rh-selfdev/handoffs"
GATE_DIR = REPO_ROOT / ".rh-selfdev/gates"
CHECKPOINT_FILE = REPO_ROOT / ".rh-selfdev/checkpoint.md"
PROMPT_DIR = REPO_ROOT / ".tmp/rh-selfdev-prompts"
TRANSPORT_COVERAGE_PATH = REPO_ROOT / "docs/contracts/transport-coverage.md"
CLI_READ_SHAPE_TEST_PATH = (
    REPO_ROOT / "packages/research_harness/tests/test_cli_read_service_shape.py"
)

SLICE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
K_SLICE_NUMBER_PATTERN = re.compile(r"^K(?P<number>\d+)_")
VALID_STATUSES = {"todo", "in_progress", "blocked", "gate", "done"}
RISK_KEYS = (
    "public_surface_changed",
    "storage_or_provenance_changed",
    "orchestrator_gate_changed",
    "benchmark_claim_changed",
    "dependency_changed",
)
TRANSPORT_INVENTORY_TEMPLATE_SUFFIX = "LG2_TRANSPORT_READ_INVENTORY"
CLI_ROUTE_TEST_TEMPLATE_SUFFIX = "LG2_CLI_READ_ROUTE_TEST_HARNESS"
CLI_TOPIC_READ_ROUTING_TEMPLATE_SUFFIX = "LG2_CLI_TOPIC_READ_SERVICE_ROUTING"
CLI_PAPER_LIST_ROUTING_TEMPLATE_SUFFIX = "LG2_CLI_PAPER_LIST_SERVICE_ROUTING"
CLI_PROVENANCE_SUMMARY_ROUTING_TEMPLATE_SUFFIX = (
    "LG2_CLI_PROVENANCE_SUMMARY_SERVICE_ROUTING"
)
CLI_PROVENANCE_EXPORT_ROUTING_TEMPLATE_SUFFIX = (
    "LG2_CLI_PROVENANCE_EXPORT_SERVICE_ROUTING"
)
CLI_ORCHESTRATOR_READ_ROUTING_TEMPLATE_SUFFIX = (
    "LG2_CLI_ORCHESTRATOR_READ_SERVICE_ROUTING"
)
PYTHON_ORCHESTRATOR_READ_ROUTING_TEMPLATE_SUFFIX = (
    "LG2_PYTHON_ORCHESTRATOR_READ_SERVICE_ROUTING"
)
HTTP_TOPIC_LIST_ROUTING_TEMPLATE_SUFFIX = "LG2_HTTP_TOPIC_LIST_SERVICE_ROUTING"
HTTP_PROVENANCE_SUMMARY_ROUTING_TEMPLATE_SUFFIX = (
    "LG2_HTTP_PROVENANCE_SUMMARY_SERVICE_ROUTING"
)
HTTP_DEFERRED_SHAPE_HARNESS_TEMPLATE_SUFFIX = "LG2_HTTP_DEFERRED_SHAPE_TEST_HARNESS"
HTTP_TOPIC_SHOW_ROUTING_TEMPLATE_SUFFIX = "LG2_HTTP_TOPIC_SHOW_SERVICE_ROUTING"
HTTP_PAPER_LIST_ROUTING_TEMPLATE_SUFFIX = "LG2_HTTP_PAPER_LIST_SERVICE_ROUTING"
HTTP_ORCHESTRATOR_GATE_CHECK_ROUTING_TEMPLATE_SUFFIX = (
    "LG2_HTTP_ORCHESTRATOR_GATE_CHECK_SERVICE_ROUTING"
)
HTTP_ORCHESTRATOR_STATUS_ROUTING_TEMPLATE_SUFFIX = (
    "LG2_HTTP_ORCHESTRATOR_STATUS_SERVICE_ROUTING"
)
LG3_COMPATIBILITY_LIFECYCLE_GUARD_TEMPLATE_SUFFIX = "LG3_COMPATIBILITY_LIFECYCLE_GUARD"
ARCHITECTURE_COMPLETION_AUDIT_TEMPLATE_SUFFIX = "ARCHITECTURE_COMPLETION_AUDIT"
CROSS_TOPIC_ATLAS_LOCAL_CLI_PREVIEW_SUFFIX = "CROSS_TOPIC_ATLAS_LOCAL_CLI_PREVIEW"
KNOWLEDGE_LOCAL_PREVIEW_CLOSEOUT_SUFFIX = "KNOWLEDGE_LOCAL_PREVIEW_CLOSEOUT"
KNOWLEDGE_CONTROLLED_BETA_DOCS_CLOSEOUT_SUFFIX = (
    "KNOWLEDGE_CONTROLLED_BETA_DOCS_CLOSEOUT"
)
KNOWLEDGE_CONTROLLED_BETA_ACCEPTANCE_REPAIR_SUFFIX = (
    "KNOWLEDGE_CONTROLLED_BETA_ACCEPTANCE_REPAIR"
)
KNOWLEDGE_HTTP_BETA_COMPLETION_SUFFIXES = (
    KNOWLEDGE_CONTROLLED_BETA_ACCEPTANCE_REPAIR_SUFFIX,
    KNOWLEDGE_CONTROLLED_BETA_DOCS_CLOSEOUT_SUFFIX,
)
RUNTIME_EVENT_NORMALIZER_SUFFIX = "RUNTIME_EVENT_NORMALIZER_READ_MODEL"
RUNTIME_JOB_LEDGER_SUFFIX = "RUNTIME_JOB_LEDGER_READ_MODEL"
RUNTIME_TOOL_FAILURE_GATE_NORMALIZER_SUFFIX = "RUNTIME_TOOL_FAILURE_GATE_NORMALIZER"
RUNTIME_SKILL_PROVENANCE_SCANNER_SUFFIX = "RUNTIME_SKILL_PROVENANCE_SCANNER"
RUNTIME_DOCTOR_READONLY_DIAGNOSTICS_SUFFIX = "RUNTIME_DOCTOR_READONLY_DIAGNOSTICS"
RUNTIME_SHOWCASE_MANIFEST_NORMALIZER_SUFFIX = "RUNTIME_SHOWCASE_MANIFEST_NORMALIZER"
RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI_SUFFIX = "RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI"
RUNTIME_EVENT_STORE_SCHEMA_ONLY_SUFFIX = "RUNTIME_EVENT_STORE_SCHEMA_ONLY"
RUNTIME_EVENT_STORE_SELFDEV_CHECKPOINT_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_CHECKPOINT_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_HANDOFF_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_HANDOFF_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_SLICE_STATUS_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_SLICE_STATUS_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_BATCH_SOURCE_GATE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_BATCH_SOURCE_GATE"
)
RUNTIME_EVENT_STORE_SELFDEV_STATUS_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_STATUS_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_CLOUD_COMMAND_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_CLOUD_COMMAND_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_CODEX_COMMAND_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_CODEX_COMMAND_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_FAILURE_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_FAILURE_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STARTED_SOURCE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STARTED_SOURCE"
)
RUNTIME_EVENT_STORE_SELFDEV_EXTENDED_BATCH_SOURCE_GATE_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_EXTENDED_BATCH_SOURCE_GATE"
)
RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_EVENT_SEQUENCE_HARDENING_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_EVENT_SEQUENCE_HARDENING"
)
RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STORE_FAILURE_HARDENING_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STORE_FAILURE_HARDENING"
)
RUNTIME_EVENT_STORE_SELFDEV_REDACTION_GUARD_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_REDACTION_GUARD"
)
RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_EXTENDED_BATCH_RECOVERY_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_EXTENDED_BATCH_RECOVERY"
)
RUNTIME_EVENT_STORE_SELFDEV_EVENT_STORE_CONTRACT_REFRESH_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_EVENT_STORE_CONTRACT_REFRESH"
)
RUNTIME_EVENT_STORE_SELFDEV_EXTENDED_BATCH_CLOSEOUT_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_EXTENDED_BATCH_CLOSEOUT"
)
RUNTIME_EVENT_STORE_POST_CLOSEOUT_REVIEW_GATE_SUFFIX = (
    "RUNTIME_EVENT_STORE_POST_CLOSEOUT_REVIEW_GATE"
)
RUNTIME_EVENT_STORE_POST_CLOSEOUT_REVIEW_PACKAGE_SUFFIX = (
    "RUNTIME_EVENT_STORE_POST_CLOSEOUT_REVIEW_PACKAGE"
)
RUNTIME_SHELL_BROAD_AUTONOMY_POLICY_GATE_SUFFIX = (
    "RUNTIME_SHELL_BROAD_AUTONOMY_POLICY_GATE"
)
RUNTIME_EVENT_STORE_INTERNAL_REVIEW_AUDIT_SUFFIX = (
    "RUNTIME_EVENT_STORE_INTERNAL_REVIEW_AUDIT"
)
RUNTIME_EVENT_STORE_SELFDEV_METADATA_REDACTION_AUDIT_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_METADATA_REDACTION_AUDIT"
)
RUNTIME_EVENT_STORE_SELFDEV_POST_AUDIT_NEXT_ACTION_RECOVERY_SUFFIX = (
    "RUNTIME_EVENT_STORE_SELFDEV_POST_AUDIT_NEXT_ACTION_RECOVERY"
)
LG8_LG10_LONG_GOAL_ACTIVATION_SUFFIX = "LG8_LG10_LONG_GOAL_ACTIVATION"
LG8_PRIVATE_PERFORMANCE_BASELINE_SUFFIX = "LG8_PRIVATE_PERFORMANCE_BASELINE"
LG8_LG9_COMBINED_EXECUTION_CONTRACT_SUFFIX = "LG8_LG9_COMBINED_EXECUTION_CONTRACT"
LG8_SELFDEV_NEXT_ACTION_RECOVERY_HOT_PATH_SUFFIX = (
    "LG8_SELFDEV_NEXT_ACTION_RECOVERY_HOT_PATH"
)
LG8_RUNTIME_EVENT_APPEND_TEMPDB_HOT_PATH_SUFFIX = (
    "LG8_RUNTIME_EVENT_APPEND_TEMPDB_HOT_PATH"
)
LG8_SELFDEV_NEXT_ACTION_COMMAND_HOT_PATH_SUFFIX = (
    "LG8_SELFDEV_NEXT_ACTION_COMMAND_HOT_PATH"
)
LG9_DURABLE_CONTRACT_MATRIX_SUFFIX = "LG9_DURABLE_CONTRACT_MATRIX"
LG9_PROVENANCE_ARTIFACT_LINKAGE_CONTRACT_SUFFIX = (
    "LG9_PROVENANCE_ARTIFACT_LINKAGE_CONTRACT"
)
LG9_ORCHESTRATOR_READONLY_MAPPING_CONTRACT_SUFFIX = (
    "LG9_ORCHESTRATOR_READONLY_MAPPING_CONTRACT"
)
LG8_LG9_PRIVATE_CLOSEOUT_GUARD_SUFFIX = "LG8_LG9_PRIVATE_CLOSEOUT_GUARD"
LG10_PUBLIC_PRODUCTIZATION_GATE_BOUNDARY_SUFFIX = (
    "LG10_PUBLIC_PRODUCTIZATION_GATE_BOUNDARY"
)
LG10_BOUNDARY_PREVIEW_PUBLIC_SURFACE_BATCH_GATE_SUFFIX = (
    "LG10_BOUNDARY_PREVIEW_PUBLIC_SURFACE_BATCH_GATE"
)
LG10_CLI_BOUNDARY_PREVIEW_SUFFIX = "LG10_CLI_BOUNDARY_PREVIEW"
LG10_MCP_BOUNDARY_PREVIEW_SUFFIX = "LG10_MCP_BOUNDARY_PREVIEW"
LG10_HTTP_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE_SUFFIX = (
    "LG10_HTTP_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
LG10_HTTP_BOUNDARY_PREVIEW_SUFFIX = "LG10_HTTP_BOUNDARY_PREVIEW"
LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE_SUFFIX = (
    "LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_SUFFIX = "LG10_PYTHON_FACADE_BOUNDARY_PREVIEW"
LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE_SUFFIX = (
    "LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_SUFFIX = "LG10_SKILLS_DOCS_BOUNDARY_PREVIEW"
LG10_DOCTOR_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE_SUFFIX = (
    "LG10_DOCTOR_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
LG10_DOCTOR_BOUNDARY_PREVIEW_SUFFIX = "LG10_DOCTOR_BOUNDARY_PREVIEW"
LG10_SHOWCASE_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE_SUFFIX = (
    "LG10_SHOWCASE_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE"
)
LG10_SHOWCASE_BOUNDARY_PREVIEW_SUFFIX = "LG10_SHOWCASE_BOUNDARY_PREVIEW"
POST_LG10_MAINLINE_ACCEPTANCE_CLOSEOUT_SUFFIX = "POST_LG10_MAINLINE_ACCEPTANCE_CLOSEOUT"
NON_BENCHMARK_STABILIZATION_SLICE_IDS = (
    "ST01_TOPIC_KNOWLEDGE_STABLE_LOCAL_BOUNDARY",
    "ST02_KNOWLEDGE_HTTP_BETA_TO_LOCAL_STABLE",
    "ST03_LG10_BOUNDARY_PREVIEW_HARDENING",
    "ST04_SURVEY_FIRST_RETRIEVAL_POLICY_STABILIZATION",
    "ST05_LG9_CONTRACT_GUARD_PRODUCTIZATION",
    "ST06_ZOTERO_SERVICE_DRY_RUN_STABILIZATION",
    "ST07_RUNTIME_SELFDEV_TOOLING_STABLE_COMPONENTS",
    "ST08_NON_BENCHMARK_STABILIZATION_CLOSEOUT",
)
LOCAL_AUTONOMY_GOAL1_SLICE_ID = "G01_LOCAL_AUTONOMY_CONTROL_PLANE"
LOCAL_AUTONOMY_GOAL2_SLICE_ID = "G02_DURABLE_SEMANTICS_LOCAL_IMPLEMENTATION"
LOCAL_AUTONOMY_GOAL3_SLICE_ID = "G03_PRODUCTIZATION_ZOTERO_LOCAL_PRODUCTIZATION"
LOCAL_AUTONOMY_GOAL4_SLICE_ID = "G04_PRIVATE_BENCHMARK_PERFORMANCE_GOVERNANCE"
LG16_EXISTING_SYSTEM_FINALIZATION_ID = "LG16_EXISTING_SYSTEM_FINALIZATION"
PHASE_B_GATE_SLICE_IDS = (
    "LG17_PHASE_B_PUBLIC_HTTP_GATE",
    "LG18_PHASE_B_ZOTERO_REAL_SYNC_GATE",
    "LG19_PHASE_B_RELEASE_DEPENDENCY_GATE",
)
RUNTIME_EVENT_STORE_SELFDEV_BATCH_WINDOW_SIZE = 3
RUNTIME_EVENT_STORE_SELFDEV_EXTENDED_BATCH_WINDOW_SIZE = 6
SELFDEV_FREEFORM_METADATA_REDACTION_PATTERNS = (
    re.compile(r"\benv_[A-Za-z0-9_-]+\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)\b(?:prompt|stdout|stderr)\s+(?:body|text|output)\s+[^;,\n]+"),
    re.compile(r"(?i)\bcloud\s+task\s+(?:output|submitted|rejected)\s+[^;,\n]+"),
)
SELFDEV_VERIFICATION_MATRIX_ID = "runtime-event-selfdev-closeout"
SELFDEV_VERIFICATION_MATRIX_SCOPE = "private-rh-selfdev"
LG9_DURABLE_CONTRACT_MATRIX_ID = "lg9-runtime-durable-semantics"
LG9_DURABLE_CONTRACT_MATRIX_SCOPE = "private-rh-selfdev"
LG9_PROVENANCE_ARTIFACT_CONTRACT_ID = "lg9-provenance-artifact-linkage"
LG9_ORCHESTRATOR_READONLY_CONTRACT_ID = "lg9-orchestrator-readonly-mapping"
LG8_LG9_PRIVATE_CLOSEOUT_REPORT_ID = "lg8-lg9-private-closeout"
LG10_PUBLIC_PRODUCTIZATION_BOUNDARY_ID = "lg10-public-productization-boundary"
NON_BENCHMARK_STABILIZATION_CLOSEOUT_REPORT_ID = (
    "rh-non-benchmark-stabilization-closeout-2026-06-11"
)
SELFDEV_CLOSEOUT_MATRIX_ID = "selfdev-runtime-shell-closeout"
SELFDEV_CLOSEOUT_MATRIX_SCOPE = "private-rh-selfdev"
SELFDEV_CLOSEOUT_MATRIX_SLICE_ID = (
    "K165_SELFDEV_RUNTIME_SHELL_CLOSEOUT_OBJECTIVE_MATRIX"
)
RUNTIME_SELFDEV_TOOLING_STABLE_COMPONENTS_ID = (
    "runtime-selfdev-tooling-stable-components"
)
SELFDEV_FAST_BATCH_LANE_ID = "selfdev-fast-batch-lane"
SELFDEV_FAST_BATCH_PROTOCOL_SLICE_ID = "K163_SELFDEV_FAST_BATCH_LANE_PROTOCOL"
SELFDEV_FAST_BATCH_RUNNER_SLICE_ID = "K164_SELFDEV_BATCH_RUNNER_HELPERS"
SELFDEV_FAST_BATCH_DEFAULT_SIZE = 6
SELFDEV_FAST_BATCH_MIN_SIZE = 4
SELFDEV_FAST_BATCH_MAX_SIZE = 8
SELFDEV_FAST_BATCH_ALLOWED_CATEGORIES = frozenset(
    {
        "docs",
        "tests",
        "private-helper",
        "self-recovery",
        "redaction",
        "review-package",
        "verification-tooling",
    }
)
SELFDEV_FAST_BATCH_FORBIDDEN_CATEGORIES = frozenset(
    {
        "public-surface",
        "storage",
        "provenance",
        "orchestrator",
        "benchmark",
        "dependency",
        "external-action",
    }
)
SELFDEV_FAST_BATCH_RISK_BOUNDARIES = (
    "public RH CLI/MCP/HTTP/Python facade/Zotero/skill behavior",
    "storage schema or storage semantics",
    "provenance ownership or artifact lineage",
    "orchestrator gate, transition, or rollback semantics",
    "benchmark/scorer/promotion claims",
    "dependency changes",
    "Cloud diff apply, real Cloud submission, commit, push, PR, release, or publishing",
)


@dataclasses.dataclass(frozen=True)
class SelfDevSlice:
    slice_id: str
    phase: str
    status: str
    risk: str
    parallel: str
    objective: str
    allowed_files: str
    tests: str
    human_gate: str


class GatePendingError(ValueError):
    """Raised when a slice is waiting for human gate approval."""


def is_valid_slice_id(slice_id: str) -> bool:
    return bool(SLICE_ID_PATTERN.fullmatch(slice_id))


def _strip_cell(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        value = value[1:-1]
    return value.replace("`", "")


def _parse_table_row(line: str) -> Optional[list[str]]:
    if not line.startswith("|"):
        return None
    cells = [_strip_cell(cell) for cell in line.strip().strip("|").split("|")]
    if len(cells) != 9:
        return None
    if cells[0] in {"Slice ID", "---"} or set(cells[0]) == {"-"}:
        return None
    if not is_valid_slice_id(cells[0]):
        return None
    return cells


def _parse_raw_table_row(line: str) -> Optional[list[str]]:
    if not line.startswith("|"):
        return None
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) != 9:
        return None
    normalized_id = _strip_cell(cells[0])
    if normalized_id in {"Slice ID", "---"} or set(normalized_id) == {"-"}:
        return None
    if not is_valid_slice_id(normalized_id):
        return None
    return cells


def load_slices(path: Path = SLICES_FILE) -> list[SelfDevSlice]:
    slices: list[SelfDevSlice] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = _parse_table_row(line)
        if cells is None:
            continue
        status = cells[2]
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status for {cells[0]}: {status}")
        slices.append(
            SelfDevSlice(
                slice_id=cells[0],
                phase=cells[1],
                status=status,
                risk=cells[3],
                parallel=cells[4],
                objective=cells[5],
                allowed_files=cells[6],
                tests=cells[7],
                human_gate=cells[8],
            )
        )
    if not slices:
        raise ValueError(f"no self-development slices found in {path}")
    return slices


def select_next_slice(slices: list[SelfDevSlice]) -> SelfDevSlice:
    for slice_def in slices:
        if slice_def.status == "gate":
            raise GatePendingError(
                f"{slice_def.slice_id} is waiting for human gate approval"
            )
        if slice_def.status == "todo":
            return slice_def
    raise ValueError("no todo self-development slice remains")


def select_pending_gate(slices: list[SelfDevSlice]) -> Optional[SelfDevSlice]:
    for slice_def in slices:
        if slice_def.status == "gate":
            return slice_def
    return None


def select_active_slice(slices: list[SelfDevSlice]) -> Optional[SelfDevSlice]:
    for slice_def in slices:
        if slice_def.status == "in_progress":
            return slice_def
    return None


def find_slice(slice_id: str, slices: list[SelfDevSlice]) -> SelfDevSlice:
    if not is_valid_slice_id(slice_id):
        raise ValueError(f"invalid slice id: {slice_id}")
    for slice_def in slices:
        if slice_def.slice_id == slice_id:
            return slice_def
    raise ValueError(f"unknown slice id: {slice_id}")


def build_worker_prompt(slice_def: SelfDevSlice) -> str:
    return f"""You are a Codex worker executing one Research Harness self-development slice.

Read first:
- .rh-selfdev/control-plane.md
- .rh-selfdev/checkpoint.md if it exists
- .rh-selfdev/slices.md

Do not automatically read docs/agent-guide.md.
Do not load or invoke RH research workflow skills unless this exact slice asks you to edit one.
Do not rely on chat-only state; persist resumable progress in a handoff, gate,
or checkpoint before stopping.

Slice: {slice_def.slice_id}
Phase: {slice_def.phase}
Risk: {slice_def.risk}
Objective: {slice_def.objective}
Allowed files: {slice_def.allowed_files}
Required tests: {slice_def.tests}
Human gate: {slice_def.human_gate}

Constraints:
- Work only on this slice.
- Do not touch unrelated dirty worktree files.
- Do not add public MCP/CLI/HTTP/skill surface.
- Do not change storage, provenance, artifact writing, paper ingestion, or orchestrator gates.
- Do not change benchmark promotion claims.
- Do not add dependencies.
- Stop and write a handoff if the work needs any forbidden change, exceeds 800 diff lines, touches more than 8 files, or fails tests after two fix attempts.
- If context pressure is high, write a checkpoint before asking the main session
  to clear or compact.

Done when:
- The slice objective is complete or explicitly blocked.
- Focused tests have been run when implementation changed.
- A concise handoff is written or returned with changed files, tests, risks, and recommended next action.
"""


def build_codex_exec_command(
    *,
    worktree_path: Path,
    prompt_path: Path,
    output_path: Path,
    model: Optional[str] = None,
) -> list[str]:
    command = [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "--ask-for-approval",
        "never",
        "-C",
        str(worktree_path),
        "-o",
        str(output_path),
    ]
    if model:
        command.extend(["--model", model])
    command.append("-")
    return command


def build_cloud_exec_command(
    *,
    environment_id: str,
    branch: str,
    prompt: str,
    attempts: int = 1,
) -> list[str]:
    if not environment_id.strip():
        raise ValueError("environment id is required")
    if not 1 <= attempts <= 4:
        raise ValueError("cloud attempts must be between 1 and 4")
    if any(token in branch for token in ("\n", "\r", ";")):
        raise ValueError(f"unsafe branch value: {branch!r}")
    return [
        "codex",
        "cloud",
        "exec",
        "--env",
        environment_id,
        "--branch",
        branch,
        "--attempts",
        str(attempts),
        prompt,
    ]


def _selfdev_verification_matrix() -> tuple[dict[str, Any], ...]:
    return (
        {
            "id": "selfdev-normalizer",
            "purpose": "Self-dev script and runtime event normalizer coverage.",
            "argv": (
                ".venv/bin/python",
                "-m",
                "pytest",
                "packages/research_harness/tests/test_rh_selfdev_script.py",
                "packages/research_harness/tests/test_runtime_event_normalizer.py",
                "-q",
            ),
        },
        {
            "id": "runtime-event-store",
            "purpose": "Runtime event store contract, readback, and writer coverage.",
            "argv": (
                ".venv/bin/python",
                "-m",
                "pytest",
                "packages/research_harness/tests/test_runtime_event_store_contract.py",
                "packages/research_harness/tests/test_runtime_event_store_readback.py",
                "packages/research_harness/tests/test_runtime_event_store_writer.py",
                "-q",
            ),
        },
        {
            "id": "public-surface-guards",
            "purpose": "Runtime event store and MCP public-surface freeze guards.",
            "argv": (
                ".venv/bin/python",
                "-m",
                "pytest",
                "packages/research_harness/tests/test_runtime_event_store_public_surface_guard.py",
                "packages/research_harness/tests/test_mcp_public_surface_guard.py",
                "-q",
            ),
        },
        {
            "id": "ruff",
            "purpose": "Scoped lint over touched self-dev and runtime-event files.",
            "argv": (
                ".venv/bin/ruff",
                "check",
                "scripts/rh-selfdev.py",
                "packages/research_harness/research_harness/runtime/event_normalizer.py",
                "packages/research_harness/research_harness/runtime/event_store.py",
                "packages/research_harness/tests/test_rh_selfdev_script.py",
                "packages/research_harness/tests/test_runtime_event_normalizer.py",
                "packages/research_harness/tests/test_runtime_event_store_contract.py",
                "packages/research_harness/tests/test_runtime_event_store_readback.py",
                "packages/research_harness/tests/test_runtime_event_store_writer.py",
            ),
        },
        {
            "id": "selfdev-status",
            "purpose": "Recover current self-development status and risk flags.",
            "argv": ("python3", "scripts/rh-selfdev.py", "status"),
        },
        {
            "id": "selfdev-next-action",
            "purpose": "Recover the next self-development boundary as JSON.",
            "argv": ("python3", "scripts/rh-selfdev.py", "next-action", "--json"),
        },
        {
            "id": "diff-check",
            "purpose": "Reject whitespace errors in the dirty bundle.",
            "argv": ("git", "diff", "--check"),
        },
    )


def _selfdev_verification_matrix_payload() -> dict[str, Any]:
    return {
        "matrix_id": SELFDEV_VERIFICATION_MATRIX_ID,
        "scope": SELFDEV_VERIFICATION_MATRIX_SCOPE,
        "public_surface": "unchanged",
        "commands": [
            {
                "id": entry["id"],
                "purpose": entry["purpose"],
                "argv": list(entry["argv"]),
            }
            for entry in _selfdev_verification_matrix()
        ],
    }


def _lg9_durable_contract_matrix() -> tuple[dict[str, Any], ...]:
    stop_before = (
        "storage schema changes, storage semantics, provenance ownership, "
        "artifact lineage, orchestrator gate or rollback behavior, public "
        "surface, benchmark claims, dependencies, external actions, Zotero, "
        "HTTP, MCP, RH/ARE, commits, pushes, PRs, releases, or publishing"
    )
    return (
        {
            "id": "runtime-event",
            "contract": (
                "Runtime events remain append-only, normalized, redacted, and "
                "read back through stable private JSON shapes."
            ),
            "evidence_state": "tested",
            "evidence": (
                "K149 refreshed event-store contract coverage; K175/K176 "
                "preserved runtime-event and self-dev recovery semantics while "
                "recording private performance evidence."
            ),
            "migration_status": "not_authorized",
            "stop_before": stop_before,
        },
        {
            "id": "job-ledger",
            "contract": (
                "Job ledger health remains a private read-model contract until "
                "storage semantics or public exposure are gate-approved."
            ),
            "evidence_state": "audited",
            "evidence": "K167 records the read-only job-ledger health closeout audit.",
            "migration_status": "not_authorized",
            "stop_before": stop_before,
        },
        {
            "id": "tool-boundary",
            "contract": (
                "Tool-boundary and gate-display semantics remain internally "
                "documented and do not alter public tool payloads."
            ),
            "evidence_state": "audited",
            "evidence": "K168 records the read-only tool-boundary closeout audit.",
            "migration_status": "not_authorized",
            "stop_before": stop_before,
        },
        {
            "id": "doctor-showcase",
            "contract": (
                "Doctor and showcase readiness remains private and descriptive "
                "until public CLI, HTTP, MCP, Zotero, or skill exposure is "
                "gate-approved."
            ),
            "evidence_state": "audited",
            "evidence": "K169 records the private doctor/showcase readiness audit.",
            "migration_status": "not_authorized",
            "stop_before": stop_before,
        },
        {
            "id": "provenance-artifact-linkage",
            "contract": (
                "Provenance and artifact-lineage links may be described as "
                "gaps, but ownership or lineage behavior must not change "
                "without a gate."
            ),
            "evidence_state": "docs-only",
            "evidence": (
                "LG9 combined contract keeps provenance ownership and artifact "
                "lineage outside low-risk implementation slices."
            ),
            "migration_status": "not_authorized",
            "stop_before": stop_before,
        },
        {
            "id": "orchestrator-read-only-mapping",
            "contract": (
                "Orchestrator gate, transition, rollback, and stage semantics "
                "remain read-only mapping concerns until a dedicated gate "
                "approves behavior changes."
            ),
            "evidence_state": "docs-only",
            "evidence": (
                "LG9 combined contract keeps orchestrator gate behavior outside "
                "low-risk implementation slices."
            ),
            "migration_status": "not_authorized",
            "stop_before": stop_before,
        },
    )


def _lg9_durable_contract_matrix_payload() -> dict[str, Any]:
    return {
        "matrix_id": LG9_DURABLE_CONTRACT_MATRIX_ID,
        "scope": LG9_DURABLE_CONTRACT_MATRIX_SCOPE,
        "slice_id": "K177_LG9_DURABLE_CONTRACT_MATRIX",
        "public_surface": "unchanged",
        "claim_policy": "private_contract_matrix_only",
        "contracts": [dict(entry) for entry in _lg9_durable_contract_matrix()],
        "verification_commands": [
            {
                "id": "lg9-contract-matrix-tests",
                "purpose": "Verify the private LG9 durable contract matrix.",
                "argv": [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "packages/research_harness/tests/test_rh_selfdev_script.py",
                    "-q",
                ],
            },
            {
                "id": "lg9-contract-matrix-json",
                "purpose": "Render the private LG9 durable contract matrix JSON.",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "lg9-contract-matrix",
                    "--json",
                ],
            },
            {
                "id": "diff-check",
                "purpose": "Reject whitespace errors in the dirty bundle.",
                "argv": ["git", "diff", "--check"],
            },
        ],
    }


def _lg9_provenance_artifact_contract_payload() -> dict[str, Any]:
    stop_before = (
        "storage schema changes, storage semantics, provenance ownership "
        "mutation, artifact lineage mutation, artifact writer behavior changes, "
        "historical backfill, public surface, orchestrator behavior, benchmark "
        "claims, dependencies, external actions, Zotero, HTTP, MCP, RH/ARE, "
        "commits, pushes, PRs, releases, or publishing"
    )
    contract_nodes = [
        {
            "id": "artifact-identity",
            "definition": (
                "Artifact identity must remain stable and descriptive until an "
                "artifact-lineage gate approves any writer or migration work."
            ),
            "implementation_status": "contract_only",
            "mutation_policy": "not_authorized",
        },
        {
            "id": "source-hash",
            "definition": (
                "Source hashes may be referenced as contract evidence, but no "
                "new hashing, backfill, or storage behavior is introduced here."
            ),
            "implementation_status": "contract_only",
            "mutation_policy": "not_authorized",
        },
        {
            "id": "provenance-owner",
            "definition": (
                "Provenance ownership remains with existing RH provenance "
                "paths; ownership changes require a bounded gate."
            ),
            "implementation_status": "contract_only",
            "mutation_policy": "not_authorized",
        },
        {
            "id": "lineage-edge",
            "definition": (
                "Lineage edges are named as a future contract surface only; "
                "edge creation, migration, and replay semantics are not changed."
            ),
            "implementation_status": "contract_only",
            "mutation_policy": "not_authorized",
        },
    ]
    return {
        "contract_id": LG9_PROVENANCE_ARTIFACT_CONTRACT_ID,
        "scope": LG9_DURABLE_CONTRACT_MATRIX_SCOPE,
        "slice_id": "K178_LG9_PROVENANCE_ARTIFACT_LINKAGE_CONTRACT",
        "public_surface": "unchanged",
        "storage_behavior": "unchanged",
        "artifact_lineage_behavior": "unchanged",
        "contract_nodes": contract_nodes,
        "stop_before": stop_before,
        "verification_commands": [
            {
                "id": "provenance-artifact-contract-tests",
                "purpose": "Verify the private provenance/artifact linkage contract.",
                "argv": [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "packages/research_harness/tests/test_rh_selfdev_script.py",
                    "-q",
                ],
            },
            {
                "id": "provenance-artifact-contract-json",
                "purpose": "Render the private provenance/artifact contract JSON.",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "lg9-provenance-artifact-contract",
                    "--json",
                ],
            },
            {
                "id": "diff-check",
                "purpose": "Reject whitespace errors in the dirty bundle.",
                "argv": ["git", "diff", "--check"],
            },
        ],
    }


def _lg9_orchestrator_readonly_contract_payload() -> dict[str, Any]:
    stop_before = (
        "orchestrator gate behavior changes, transition behavior changes, "
        "rollback behavior changes, stage semantics, storage/provenance "
        "semantics, artifact lineage, public surface, benchmark claims, "
        "dependencies, external actions, Zotero, HTTP, MCP, RH/ARE, commits, "
        "pushes, PRs, releases, or publishing"
    )
    contract_nodes = [
        {
            "id": "gate-state",
            "definition": (
                "Gate state may be mapped for read-only diagnostics, but gate "
                "criteria and pass/fail behavior remain unchanged."
            ),
            "implementation_status": "contract_only",
            "mutation_policy": "not_authorized",
        },
        {
            "id": "transition-map",
            "definition": (
                "Transitions may be named as read-only mapping edges, but no "
                "transition execution or ordering behavior changes here."
            ),
            "implementation_status": "contract_only",
            "mutation_policy": "not_authorized",
        },
        {
            "id": "rollback-boundary",
            "definition": (
                "Rollback boundaries may be documented for review, but rollback "
                "trigger, replay, or recovery behavior remains gate-bound."
            ),
            "implementation_status": "contract_only",
            "mutation_policy": "not_authorized",
        },
        {
            "id": "stage-read-model",
            "definition": (
                "Stage state may be summarized as a private read model, but "
                "stage advancement semantics remain unchanged."
            ),
            "implementation_status": "contract_only",
            "mutation_policy": "not_authorized",
        },
    ]
    return {
        "contract_id": LG9_ORCHESTRATOR_READONLY_CONTRACT_ID,
        "scope": LG9_DURABLE_CONTRACT_MATRIX_SCOPE,
        "slice_id": "K179_LG9_ORCHESTRATOR_READONLY_MAPPING_CONTRACT",
        "public_surface": "unchanged",
        "orchestrator_behavior": "unchanged",
        "contract_nodes": contract_nodes,
        "stop_before": stop_before,
        "verification_commands": [
            {
                "id": "orchestrator-readonly-contract-tests",
                "purpose": "Verify the private orchestrator read-only contract.",
                "argv": [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "packages/research_harness/tests/test_rh_selfdev_script.py",
                    "-q",
                ],
            },
            {
                "id": "orchestrator-readonly-contract-json",
                "purpose": "Render the private orchestrator read-only contract JSON.",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "lg9-orchestrator-readonly-contract",
                    "--json",
                ],
            },
            {
                "id": "diff-check",
                "purpose": "Reject whitespace errors in the dirty bundle.",
                "argv": ["git", "diff", "--check"],
            },
        ],
    }


def _durable_semantics_local_implementation_payload() -> dict[str, Any]:
    durable_semantics = _load_durable_semantics_module()
    report = durable_semantics.diagnose_current_migrated_schema()
    payload = report.to_payload()
    payload.update(
        {
            "guard_id": "lg9-durable-semantics-local-implementation",
            "scope": LG9_DURABLE_CONTRACT_MATRIX_SCOPE,
            "slice_id": LOCAL_AUTONOMY_GOAL2_SLICE_ID,
            "schema_source": "current_package_migrations_temp_db",
            "public_surface": "unchanged",
            "storage_semantics": "read_only_diagnostics_only",
            "provenance_ownership": "unchanged",
            "artifact_lineage_behavior": "unchanged",
            "orchestrator_behavior": "unchanged",
            "mutation_policy": "not_authorized",
            "verification_commands": [
                {
                    "id": "durable-semantics-tests",
                    "purpose": "Verify executable local durable semantics guards.",
                    "argv": [
                        ".venv/bin/python",
                        "-m",
                        "pytest",
                        "packages/research_harness/tests/test_durable_semantics.py",
                        "packages/research_harness/tests/test_rh_selfdev_script.py",
                        "-q",
                        "-k",
                        "durable_semantics or lg9_contract_guard_productization",
                    ],
                },
                {
                    "id": "durable-semantics-json",
                    "purpose": "Render executable local durable semantics diagnostics.",
                    "argv": [
                        "python3",
                        "scripts/rh-selfdev.py",
                        "durable-semantics",
                        "--json",
                    ],
                },
                {
                    "id": "diff-check",
                    "purpose": "Reject whitespace errors in the dirty bundle.",
                    "argv": ["git", "diff", "--check"],
                },
            ],
        }
    )
    return payload


def _load_durable_semantics_module() -> Any:
    module_path = (
        REPO_ROOT
        / "packages/research_harness/research_harness/runtime/durable_semantics.py"
    )
    spec = importlib.util.spec_from_file_location(
        "rh_selfdev_durable_semantics",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load durable semantics module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _productization_zotero_local_payload() -> dict[str, Any]:
    productization_boundary = _load_productization_boundary_module()
    payload = productization_boundary.productization_zotero_local_status()
    payload.update(
        {
            "slice_id": LOCAL_AUTONOMY_GOAL3_SLICE_ID,
            "public_surface": "unchanged",
            "zotero_real_sync": "deferred",
            "zotero_ui": "deferred",
            "verification_commands": [
                {
                    "id": "productization-zotero-local-tests",
                    "purpose": (
                        "Verify stable local productization and Zotero dry-run "
                        "classification."
                    ),
                    "argv": [
                        ".venv/bin/python",
                        "-m",
                        "pytest",
                        "packages/research_harness/tests/test_productization_boundary_components.py",
                        "packages/research_harness/tests/test_service_layer.py",
                        "packages/research_harness_mcp/research_harness_mcp/tests/test_tools.py",
                        "packages/research_harness/tests/test_rh_selfdev_script.py",
                        "-q",
                        "-k",
                        "productization_zotero_local or zotero_sync or local_autonomy_goal3",
                    ],
                },
                {
                    "id": "productization-zotero-local-json",
                    "purpose": "Render stable local productization/Zotero JSON.",
                    "argv": [
                        "python3",
                        "scripts/rh-selfdev.py",
                        "productization-zotero-local",
                        "--json",
                    ],
                },
                {
                    "id": "diff-check",
                    "purpose": "Reject whitespace errors in the dirty bundle.",
                    "argv": ["git", "diff", "--check"],
                },
            ],
        }
    )
    return payload


def _load_productization_boundary_module() -> Any:
    module_path = (
        REPO_ROOT
        / "packages/research_harness/research_harness/_productization/boundary.py"
    )
    spec = importlib.util.spec_from_file_location(
        "rh_selfdev_productization_boundary",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load productization module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _private_performance_governance_payload() -> dict[str, Any]:
    reports = _private_performance_report_summaries()
    latest_report = reports[-1] if reports else {}
    closeout = _lg8_lg9_private_closeout_payload()
    all_private = all(report["private_scope"] is True for report in reports)
    all_no_claim = all(
        report["claim_policy"] == "no_benchmark_or_public_performance_claim"
        for report in reports
    )
    all_ok = all(report["overall_status"] == "ok" for report in reports)
    total_failures = sum(int(report["failure_count"]) for report in reports)
    status = (
        "stable_private_performance_governance"
        if reports and all_private and all_no_claim and all_ok and total_failures == 0
        else "private_performance_governance_needs_attention"
    )
    return {
        "governance_id": "private-benchmark-performance-governance",
        "scope": "private-rh-selfdev",
        "slice_id": LOCAL_AUTONOMY_GOAL4_SLICE_ID,
        "status": status,
        "claim_policy": "no_benchmark_or_public_performance_claim",
        "public_claim_status": "not_approved",
        "benchmark_promotion_status": "not_approved",
        "scorer_semantics_changed": False,
        "rh_are_boundary_changed": False,
        "public_surface": "unchanged",
        "dependency_changed": False,
        "report_count": len(reports),
        "latest_report": latest_report,
        "reports": reports,
        "hot_path_evidence": closeout["lg8_hot_path_evidence"],
        "required_private_commands": [
            {
                "id": "private-performance-rerun",
                "argv": [
                    "python3",
                    "scripts/rh-perf-baseline.py",
                    "--iterations",
                    "3",
                    "--output-dir",
                    ".rh-selfdev",
                    "--json",
                ],
            },
            {
                "id": "lg8-lg9-private-closeout",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "lg8-lg9-closeout",
                    "--json",
                ],
            },
        ],
        "deferred": [
            "public_benchmark_claims",
            "public_performance_claims",
            "leaderboard_or_ranking",
            "scorer_semantics_changes",
            "rh_are_boundary_moves",
            "external_benchmark_submission",
            "release_or_publishing",
        ],
        "verification_commands": [
            {
                "id": "private-performance-governance-tests",
                "purpose": "Verify private performance governance payload and runner plan.",
                "argv": [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "packages/research_harness/tests/test_rh_selfdev_script.py",
                    "packages/research_harness/tests/test_rh_perf_baseline.py",
                    "-q",
                    "-k",
                    "private_performance_governance or default_plan or local_autonomy_goal4",
                ],
            },
            {
                "id": "private-performance-governance-json",
                "purpose": "Render private benchmark/performance governance JSON.",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "private-performance-governance",
                    "--json",
                ],
            },
            {
                "id": "diff-check",
                "purpose": "Reject whitespace errors in the dirty bundle.",
                "argv": ["git", "diff", "--check"],
            },
        ],
    }


def _private_performance_report_summaries() -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for path in sorted(
        (REPO_ROOT / ".rh-selfdev").glob("rh-performance-baseline-*.json")
    ):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        measurement_summaries = [
            dict(measurement.get("summary", {}))
            for measurement in payload.get("measurements", [])
        ]
        failure_count = sum(
            int(summary.get("failure_count", 0)) for summary in measurement_summaries
        )
        summaries.append(
            {
                "path": _display_path(path),
                "created_at": str(payload.get("created_at", "")),
                "overall_status": str(payload.get("overall_status", "")),
                "private_scope": bool(payload.get("private_scope", False)),
                "claim_policy": str(payload.get("claim_policy", "")),
                "measurement_count": len(measurement_summaries),
                "failure_count": failure_count,
                "timed_out_count": sum(
                    int(summary.get("timed_out_count", 0))
                    for summary in measurement_summaries
                ),
            }
        )
    return summaries


def _lg9_contract_guard_productization_payload() -> dict[str, Any]:
    matrix = _lg9_durable_contract_matrix_payload()
    provenance = _lg9_provenance_artifact_contract_payload()
    orchestrator = _lg9_orchestrator_readonly_contract_payload()
    durable_semantics = _durable_semantics_local_implementation_payload()
    stop_before = (
        "storage schema changes, storage semantics, provenance ownership "
        "changes, artifact-lineage behavior changes, artifact writer behavior "
        "changes, orchestrator gate or rollback behavior changes, public "
        "surface changes, benchmark claims, dependencies, external actions, "
        "Zotero, HTTP, MCP, RH/ARE, commits, pushes, PRs, releases, or "
        "publishing"
    )
    return {
        "guard_id": "lg9-contract-guard-productization",
        "scope": LG9_DURABLE_CONTRACT_MATRIX_SCOPE,
        "slice_id": "ST05_LG9_CONTRACT_GUARD_PRODUCTIZATION",
        "status": durable_semantics["status"],
        "public_surface": "unchanged",
        "storage_semantics": "unchanged",
        "provenance_ownership": "unchanged",
        "artifact_lineage_behavior": "unchanged",
        "orchestrator_behavior": "unchanged",
        "schema_migration_required": durable_semantics["schema_migration_required"],
        "executable_guard_source": durable_semantics["guard_id"],
        "executable_guard_checks": durable_semantics["checks"],
        "guards": [
            {
                "id": "durable-contract-matrix",
                "classification": "stable_internal_guard",
                "source_id": matrix["matrix_id"],
                "contract_count": len(matrix["contracts"]),
                "mutation_policy": "not_authorized",
                "checked_fields": [
                    "scope",
                    "public_surface",
                    "claim_policy",
                    "migration_status",
                    "stop_before",
                ],
            },
            {
                "id": "provenance-artifact-linkage",
                "classification": "stable_internal_read_model_guard",
                "source_id": provenance["contract_id"],
                "contract_node_count": len(provenance["contract_nodes"]),
                "mutation_policy": "not_authorized",
                "checked_fields": [
                    "public_surface",
                    "storage_behavior",
                    "artifact_lineage_behavior",
                    "implementation_status",
                    "mutation_policy",
                    "stop_before",
                ],
            },
            {
                "id": "orchestrator-readonly-mapping",
                "classification": "stable_internal_read_model_guard",
                "source_id": orchestrator["contract_id"],
                "contract_node_count": len(orchestrator["contract_nodes"]),
                "mutation_policy": "not_authorized",
                "checked_fields": [
                    "public_surface",
                    "orchestrator_behavior",
                    "implementation_status",
                    "mutation_policy",
                    "stop_before",
                ],
            },
        ],
        "stop_before": stop_before,
        "verification_commands": [
            {
                "id": "lg9-contract-guard-tests",
                "purpose": "Verify ST05 private LG9 guard productization.",
                "argv": [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "packages/research_harness/tests/test_rh_selfdev_script.py",
                    "-q",
                    "-k",
                    "lg9_contract_guard_productization",
                ],
            },
            {
                "id": "lg9-contract-guards-json",
                "purpose": "Render the private ST05 LG9 guard report JSON.",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "lg9-contract-guards",
                    "--json",
                ],
            },
            {
                "id": "diff-check",
                "purpose": "Reject whitespace errors in the dirty bundle.",
                "argv": ["git", "diff", "--check"],
            },
        ],
    }


def _lg8_lg9_private_closeout_payload() -> dict[str, Any]:
    return {
        "report_id": LG8_LG9_PRIVATE_CLOSEOUT_REPORT_ID,
        "scope": LG9_DURABLE_CONTRACT_MATRIX_SCOPE,
        "slice_id": "K180_LG8_LG9_PRIVATE_CLOSEOUT_GUARD",
        "completion_state": "combined_private_complete",
        "public_surface": "unchanged",
        "lg10_status": "gate_bound",
        "claim_policy": "no_public_performance_or_benchmark_claim",
        "risk_boundary": (
            "Private local evidence and private durable contracts only. Stop "
            "before public productization, benchmark claims, storage/provenance "
            "semantics, artifact lineage, orchestrator behavior, dependencies, "
            "external actions, Zotero, HTTP, MCP, RH/ARE, commits, pushes, PRs, "
            "releases, or publishing."
        ),
        "lg8_hot_path_evidence": [
            {
                "slice_id": "K174_LG8_SELFDEV_NEXT_ACTION_RECOVERY_HOT_PATH",
                "metric": "selfdev_next_action_recovery",
                "before": ".rh-selfdev/rh-performance-baseline-20260611T045600Z.*",
                "after": ".rh-selfdev/rh-performance-baseline-20260611T045900Z.*",
                "private_scope": True,
            },
            {
                "slice_id": "K175_LG8_RUNTIME_EVENT_APPEND_TEMPDB_HOT_PATH",
                "metric": "runtime_event_append_tempdb",
                "before": ".rh-selfdev/rh-performance-baseline-20260611T045900Z.*",
                "after": ".rh-selfdev/rh-performance-baseline-20260611T050300Z.*",
                "private_scope": True,
            },
            {
                "slice_id": "K176_LG8_SELFDEV_NEXT_ACTION_COMMAND_HOT_PATH",
                "metric": "selfdev_next_action_recovery",
                "before": ".rh-selfdev/rh-performance-baseline-20260611T050300Z.*",
                "after": ".rh-selfdev/rh-performance-baseline-20260611T051455Z.*",
                "private_scope": True,
            },
        ],
        "lg9_contract_evidence": [
            {
                "slice_id": "K177_LG9_DURABLE_CONTRACT_MATRIX",
                "artifact": ".rh-selfdev/rh-lg9-durable-contract-matrix-2026-06-11.md",
                "implementation_status": "tested",
            },
            {
                "slice_id": "K178_LG9_PROVENANCE_ARTIFACT_LINKAGE_CONTRACT",
                "artifact": ".rh-selfdev/rh-lg9-provenance-artifact-linkage-contract-2026-06-11.md",
                "implementation_status": "contract_only",
            },
            {
                "slice_id": "K179_LG9_ORCHESTRATOR_READONLY_MAPPING_CONTRACT",
                "artifact": ".rh-selfdev/rh-lg9-orchestrator-readonly-mapping-contract-2026-06-11.md",
                "implementation_status": "contract_only",
            },
        ],
        "verification_commands": [
            {
                "id": "selfdev-and-perf-tests",
                "purpose": "Verify self-dev recovery, LG9 contracts, and private perf runner tests.",
                "argv": [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "packages/research_harness/tests/test_rh_selfdev_script.py",
                    "packages/research_harness/tests/test_rh_perf_baseline.py",
                    "-q",
                ],
            },
            {
                "id": "private-closeout-json",
                "purpose": "Render the private LG8/LG9 closeout JSON.",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "lg8-lg9-closeout",
                    "--json",
                ],
            },
            {
                "id": "next-action",
                "purpose": "Confirm next-action reports private completion.",
                "argv": ["python3", "scripts/rh-selfdev.py", "next-action", "--json"],
            },
            {
                "id": "diff-check",
                "purpose": "Reject whitespace errors in the dirty bundle.",
                "argv": ["git", "diff", "--check"],
            },
        ],
    }


def _lg10_public_productization_boundary_payload() -> dict[str, Any]:
    stop_before = [
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
    public_surfaces = [
        "CLI",
        "MCP",
        "HTTP",
        "Python facade",
        "Zotero",
        "doctor",
        "showcase",
        "skills/docs",
    ]
    required_evidence = [
        "shape-lock tests",
        "opt-in default",
        "compatibility proof",
        "docs claim review",
        "rollback/fallback plan",
    ]
    return {
        "boundary_id": LG10_PUBLIC_PRODUCTIZATION_BOUNDARY_ID,
        "scope": "private-rh-selfdev-gate-plan",
        "slice_id": "K181_LG10_PUBLIC_PRODUCTIZATION_GATE_BOUNDARY",
        "lg8_lg9_prerequisite": "complete",
        "lg10_status": "gate_bound",
        "public_surfaces": public_surfaces,
        "allowed_future_pattern": "one_public_surface_per_gate_slice",
        "future_slice_policy": (
            "A future human-approved LG10 slice may change exactly one public "
            "surface, must be opt-in by default, and must preserve existing "
            "behavior unless the gate explicitly approves a compatibility break."
        ),
        "required_pre_implementation_evidence": required_evidence,
        "stop_before": stop_before,
        "risk_flags": {
            "public_surface_changed": False,
            "storage_or_provenance_changed": False,
            "orchestrator_gate_changed": False,
            "benchmark_claim_changed": False,
            "dependency_changed": False,
        },
        "surface_boundaries": [
            {
                "surface": surface,
                "future_scope": "gate_required",
                "minimum_evidence": list(required_evidence),
                "default_policy": "opt_in_and_backwards_compatible",
            }
            for surface in public_surfaces
        ],
        "verification_commands": [
            {
                "id": "selfdev-boundary-tests",
                "purpose": "Verify K181 next-action recovery and boundary payload.",
                "argv": [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "packages/research_harness/tests/test_rh_selfdev_script.py",
                    "-q",
                ],
            },
            {
                "id": "lg10-boundary-json",
                "purpose": "Render the LG10 public-productization boundary JSON.",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "lg10-productization-boundary",
                    "--json",
                ],
            },
            {
                "id": "next-action",
                "purpose": "Confirm next-action waits for a fresh LG10 gate.",
                "argv": ["python3", "scripts/rh-selfdev.py", "next-action", "--json"],
            },
            {
                "id": "status",
                "purpose": "Render the self-dev status boundary.",
                "argv": ["python3", "scripts/rh-selfdev.py", "status"],
            },
            {
                "id": "diff-check",
                "purpose": "Reject whitespace errors in the dirty bundle.",
                "argv": ["git", "diff", "--check"],
            },
        ],
    }


def _selfdev_closeout_matrix_payload() -> dict[str, Any]:
    verification_payload = _selfdev_verification_matrix_payload()
    return {
        "matrix_id": SELFDEV_CLOSEOUT_MATRIX_ID,
        "scope": SELFDEV_CLOSEOUT_MATRIX_SCOPE,
        "slice_id": SELFDEV_CLOSEOUT_MATRIX_SLICE_ID,
        "public_surface": "unchanged",
        "completion_state": "internal-closeout-complete",
        "tracks": [
            {
                "id": "selfdev-internal-automation",
                "target_percent": 100,
                "current_percent_estimate": 100,
                "requirements": [
                    {
                        "id": "checkpoint-handoff-recovery",
                        "status": "complete",
                        "evidence": "checkpoint, handoff, gate, status, and next-action recovery are covered by prior K-slices.",
                    },
                    {
                        "id": "verification-matrix",
                        "status": "complete",
                        "evidence": "K160 added the private verification matrix helper with argv-only entries.",
                    },
                    {
                        "id": "fast-batch-lane",
                        "status": "complete",
                        "evidence": "K163/K164 added the private low-risk batch protocol and summary helper.",
                    },
                    {
                        "id": "closeout-matrix",
                        "status": "complete",
                        "evidence": "K165 records the 100 percent closeout target, low-risk follow-up queue, and gate boundaries.",
                    },
                    {
                        "id": "closeout-gap-audit",
                        "status": "complete",
                        "evidence": "K166 records the remaining self-dev automation gaps and final closeout criteria.",
                    },
                    {
                        "id": "final-selfdev-closeout-report",
                        "status": "complete",
                        "evidence": "K170 records the final internal closeout report for the authorized private scope.",
                    },
                ],
            },
            {
                "id": "runtime-shell-internal-capabilities",
                "target_percent": 100,
                "current_percent_estimate": 100,
                "requirements": [
                    {
                        "id": "runtime-read-models",
                        "status": "complete",
                        "evidence": "K103-K108 implemented read-model helpers for events, jobs, tool/gate failures, skills, doctor diagnostics, and showcase manifests.",
                    },
                    {
                        "id": "runtime-event-store",
                        "status": "complete",
                        "evidence": "K113-K150 implemented and closed out the private append-only runtime event store line.",
                    },
                    {
                        "id": "runtime-event-store-private-sources",
                        "status": "complete",
                        "evidence": "Self-dev checkpoint, handoff, gate, status, next-action, prompt, cloud dry-run, and cloud-submit event families are covered inside approved gates.",
                    },
                    {
                        "id": "job-ledger-health-closeout",
                        "status": "complete",
                        "evidence": "K167 records the read-only job-ledger health closeout audit and remaining gate boundaries.",
                    },
                    {
                        "id": "tool-boundary-closeout",
                        "status": "complete",
                        "evidence": "K168 records the read-only tool-boundary and gate-display closeout audit.",
                    },
                    {
                        "id": "doctor-showcase-internal-closeout",
                        "status": "complete",
                        "evidence": "K169 records the private doctor/showcase readiness closeout audit.",
                    },
                    {
                        "id": "large-risk-productization-gates",
                        "status": "gate_required",
                        "evidence": "Public surface, storage/provenance, orchestrator, benchmark, dependency, external, Zotero, HTTP, MCP, and RH/ARE work remain outside the authorized internal closeout.",
                    },
                ],
            },
        ],
        "next_low_risk_slices": [],
        "gate_boundaries": [
            {
                "id": "public-surface",
                "stop_before": "public RH CLI/MCP/HTTP/Python facade/Zotero/skill behavior changes",
            },
            {
                "id": "storage-provenance",
                "stop_before": "storage schema, storage semantics, provenance ownership, or artifact-lineage changes",
            },
            {
                "id": "orchestrator-benchmark-dependency",
                "stop_before": "orchestrator gate semantics, benchmark/scorer/promotion claims, or dependency changes",
            },
            {
                "id": "external-actions",
                "stop_before": "Cloud diff apply, real Cloud submission, commit, push, PR, release, publishing, or credential/config mutation",
            },
        ],
        "verification_commands": [
            {
                "id": entry["id"],
                "purpose": entry["purpose"],
                "argv": list(entry["argv"]),
            }
            for entry in verification_payload["commands"]
        ]
        + [
            {
                "id": "closeout-matrix",
                "purpose": "Confirm the private closeout objective matrix is recoverable as JSON.",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "closeout-matrix",
                    "--json",
                ],
            }
        ],
    }


def _runtime_selfdev_tooling_stable_components_payload() -> dict[str, Any]:
    verification_payload = _selfdev_verification_matrix_payload()
    closeout_payload = _selfdev_closeout_matrix_payload()
    batch_payload = _selfdev_fast_batch_summary()
    redaction_families = _selfdev_redaction_invariant_families()
    stop_before = (
        "public surface changes, storage schema changes, storage semantics, "
        "provenance ownership changes, artifact-lineage behavior changes, "
        "orchestrator gate or rollback behavior changes, benchmark claims, "
        "dependencies, external actions, real Zotero sync/UI/apply behavior, "
        "credential/config mutation, RH/ARE boundary moves, commits, pushes, "
        "PRs, releases, or publishing"
    )
    components = [
        {
            "id": "checkpoint-handoff-gate-recovery",
            "classification": "stable_internal_maintenance_tool",
            "source_id": "rh-self-dev-control-plane",
            "evidence": (
                "Control-plane checkpoint, handoff, gate, and checkpoint "
                "recovery protocols are durable self-dev review surfaces."
            ),
            "mutation_policy": "not_authorized",
        },
        {
            "id": "next-action-status-control-plane",
            "classification": "stable_internal_maintenance_tool",
            "source_id": "rh-selfdev-status-next-action",
            "evidence": (
                "status and next-action helpers deterministically recover the "
                "current slice and stop boundaries from the slice queue."
            ),
            "mutation_policy": "not_authorized",
        },
        {
            "id": "verification-matrix-argv",
            "classification": "stable_internal_guard",
            "source_id": verification_payload["matrix_id"],
            "evidence": (
                "The verification matrix exposes argv arrays for focused "
                "self-dev/runtime checks without shell strings."
            ),
            "entry_count": len(verification_payload["commands"]),
            "mutation_policy": "not_authorized",
        },
        {
            "id": "fast-batch-lane-summary",
            "classification": "stable_internal_batch_helper",
            "source_id": batch_payload["lane_id"],
            "evidence": (
                "The batch summary helper classifies eligible low-risk "
                "internal docs/tests/private-helper work and rejects large-risk "
                "categories."
            ),
            "eligible_subtask_count": len(batch_payload["subtasks"]),
            "rejected_subtask_count": len(batch_payload["rejected_subtasks"]),
            "mutation_policy": "not_authorized",
        },
        {
            "id": "redaction-invariant-registry",
            "classification": "stable_internal_guard",
            "source_id": "selfdev-redaction-invariant-families",
            "evidence": (
                "The redaction invariant registry covers checkpoint, handoff, "
                "gate, status, next-action, cloud-command, codex-command, and "
                "cloud-submit self-dev event families."
            ),
            "family_count": len(redaction_families),
            "mutation_policy": "not_authorized",
        },
        {
            "id": "closeout-objective-matrix",
            "classification": "stable_internal_read_model",
            "source_id": closeout_payload["matrix_id"],
            "evidence": (
                "The closeout objective matrix records completed self-dev "
                "automation and runtime-shell internal capability tracks."
            ),
            "track_count": len(closeout_payload["tracks"]),
            "mutation_policy": "not_authorized",
        },
        {
            "id": "runtime-shell-internal-docs",
            "classification": "stable_internal_docs",
            "source_id": "rh-runtime-shell-implementation-plan",
            "evidence": (
                "Runtime-shell implementation and optimization protocol docs "
                "remain the durable boundary for thin-shell local maintenance "
                "tooling."
            ),
            "mutation_policy": "not_authorized",
        },
    ]
    return {
        "component_id": RUNTIME_SELFDEV_TOOLING_STABLE_COMPONENTS_ID,
        "scope": SELFDEV_CLOSEOUT_MATRIX_SCOPE,
        "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[6],
        "status": "stable_internal_maintenance_tooling",
        "public_surface": "unchanged",
        "storage_semantics": "unchanged",
        "provenance_ownership": "unchanged",
        "artifact_lineage_behavior": "unchanged",
        "orchestrator_behavior": "unchanged",
        "components": components,
        "deferred": [
            {
                "id": "public-runtime-shell-exposure",
                "reason": "public CLI/MCP/HTTP/Python/Zotero/skill behavior remains gate-bound",
            },
            {
                "id": "runtime-storage-or-provenance-migration",
                "reason": "storage/provenance/artifact-lineage semantic changes remain gate-bound",
            },
            {
                "id": "real-zotero-or-external-actions",
                "reason": "real Zotero sync/UI/apply and external actions remain excluded",
            },
        ],
        "stop_before": stop_before,
        "verification_commands": [
            {
                "id": "runtime-selfdev-tooling-tests",
                "purpose": "Verify ST07 private runtime/self-dev tooling stabilization.",
                "argv": [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "packages/research_harness/tests/test_rh_selfdev_script.py",
                    "-q",
                    "-k",
                    "runtime_selfdev_tooling or st07_advances",
                ],
            },
            {
                "id": "runtime-selfdev-tooling-json",
                "purpose": "Render private ST07 stable tooling JSON.",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "runtime-selfdev-tooling",
                    "--json",
                ],
            },
            {
                "id": "next-action",
                "purpose": "Confirm self-dev recovery advances to the next slice.",
                "argv": ["python3", "scripts/rh-selfdev.py", "next-action", "--json"],
            },
            {
                "id": "status",
                "purpose": "Confirm control-plane status is recoverable.",
                "argv": ["python3", "scripts/rh-selfdev.py", "status"],
            },
            {
                "id": "diff-check",
                "purpose": "Reject whitespace errors in the dirty bundle.",
                "argv": ["git", "diff", "--check"],
            },
        ],
    }


def _non_benchmark_stabilization_closeout_payload() -> dict[str, Any]:
    classifications = [
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[0],
            "item": "Topic Knowledge local/internal capability",
            "classification": "stable_internal_component",
            "decision": "stable_internal",
            "evidence": (
                "ST01 handoff and topic knowledge docs classify the capability "
                "as local/internal without public internet deployment."
            ),
            "deferred": [
                "public internet deployment",
                "storage/provenance/orchestrator semantic changes",
                "real Zotero sync/UI",
            ],
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[1],
            "item": "Topic Knowledge HTTP local bridge",
            "classification": "stable_local_internal_bridge",
            "decision": "stable_internal",
            "evidence": (
                "ST02 handoff and `docs/knowledge-http-api.md` classify HTTP "
                "as a local/internal bridge while preserving payload/error "
                "compatibility."
            ),
            "deferred": [
                "stable external API release",
                "public internet deployment",
            ],
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[2],
            "item": "LG10 opt-in productization boundary components",
            "classification": "stable_internal_boundary_components",
            "decision": "stable_internal",
            "evidence": (
                "ST03 handoff and the productization boundary registry classify "
                "CLI, MCP, HTTP, Python facade, skills/docs, doctor, and "
                "showcase boundaries while deferring Zotero."
            ),
            "deferred": [
                "release-readiness claims",
                "additional public surfaces",
                "Zotero productization",
            ],
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[3],
            "item": "Survey-first retrieval policy",
            "classification": "stable_internal_policy_component",
            "decision": "stable_internal",
            "evidence": (
                "ST04 handoff and survey-first policy docs/tests prove "
                "under-filled topics seed first, normal topics avoid extra "
                "fanout, auto-ingest avoids low-confidence survey/facet "
                "results, and no-survey fallback preserves original retrieval."
            ),
            "deferred": [
                "public API shape changes",
                "benchmark promotion claims",
            ],
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[4],
            "item": "LG9 contract guards/read-model checks",
            "classification": "stable_internal_guard",
            "decision": "stable_internal",
            "evidence": (
                "ST05 gate and `lg9-contract-guards --json` classify contract "
                "matrix, provenance/artifact linkage, and orchestrator "
                "read-only mapping as executable internal guards."
            ),
            "deferred": [
                "storage schema or semantic migrations",
                "provenance ownership changes",
                "artifact-lineage behavior changes",
                "orchestrator gate or rollback behavior changes",
            ],
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[5],
            "item": "Zotero service dry-run validation",
            "classification": "stable_internal_dry_run_validation",
            "decision": "stable_internal",
            "evidence": (
                "ST06 gate and tests classify stable Zotero behavior as "
                "direction=push dry_run=true only, with no Zotero client "
                "creation for the stable path."
            ),
            "deferred": [
                "pull/both dry-run",
                "real Zotero sync/UI/apply",
                "credentials or network-backed Zotero access",
            ],
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[6],
            "item": "Runtime-shell/self-dev maintenance tooling",
            "classification": "stable_internal_maintenance_tooling",
            "decision": "stable_internal",
            "evidence": (
                "`runtime-selfdev-tooling --json` and ST07 docs classify "
                "checkpoint recovery, status/next-action, verification matrix, "
                "batch summary, redaction invariants, closeout matrix, and "
                "runtime-shell docs as internal maintenance tooling."
            ),
            "deferred": [
                "public runtime-shell exposure",
                "storage/provenance/orchestrator semantic changes",
                "external actions",
            ],
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[7],
            "item": "LG11 closeout report",
            "classification": "stable_internal_closeout_report",
            "decision": "complete",
            "evidence": (
                "This closeout report classifies all authorized non-benchmark "
                "stabilization items and leaves only explicitly excluded work."
            ),
            "deferred": [
                "benchmark/public performance claims",
                "external release actions",
            ],
        },
    ]
    excluded_work = [
        "benchmark scoring",
        "leaderboard/ranking",
        "public performance claims",
        "releases/publishing",
        "commits/pushes/PRs",
        "dependency changes",
        "external actions",
        "public internet deployment",
        "storage/provenance/orchestrator semantic changes",
        "artifact-lineage changes",
        "real Zotero sync/UI/apply",
    ]
    return {
        "report_id": NON_BENCHMARK_STABILIZATION_CLOSEOUT_REPORT_ID,
        "scope": "private-rh-selfdev-lg11-closeout",
        "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[7],
        "status": "complete",
        "completion_date": "2026-06-12",
        "classifications": classifications,
        "remaining_implementation_slices": [],
        "excluded_work": excluded_work,
        "risk_flags": {
            "public_surface_changed": False,
            "storage_or_provenance_changed": False,
            "orchestrator_gate_changed": False,
            "benchmark_claim_changed": False,
            "dependency_changed": False,
        },
        "acceptance": {
            "all_items_classified": True,
            "no_unstabilized_preview_beta_or_contract_only_items": True,
            "checkpoint_should_report_pending_slice": "none",
            "only_remaining_work": "excluded_or_gate_bound",
        },
        "verification_commands": [
            {
                "id": "service-coverage",
                "purpose": "Verify service coverage classifications.",
                "argv": ["python3", "scripts/check-service-coverage.py"],
            },
            {
                "id": "quick-check",
                "purpose": "Run the quick self-dev verification gate.",
                "argv": ["scripts/codex-check.sh", "--quick"],
            },
            {
                "id": "closeout-tests",
                "purpose": "Verify ST08 closeout payload and queue recovery.",
                "argv": [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "packages/research_harness/tests/test_rh_selfdev_script.py",
                    "-q",
                    "-k",
                    "non_benchmark_stabilization_closeout or st08_completes",
                ],
            },
            {
                "id": "closeout-json",
                "purpose": "Render private LG11 non-benchmark closeout JSON.",
                "argv": [
                    "python3",
                    "scripts/rh-selfdev.py",
                    "non-benchmark-closeout",
                    "--json",
                ],
            },
            {
                "id": "next-action",
                "purpose": "Confirm no LG11 implementation slice remains.",
                "argv": ["python3", "scripts/rh-selfdev.py", "next-action", "--json"],
            },
            {
                "id": "status",
                "purpose": "Confirm control-plane status is recoverable.",
                "argv": ["python3", "scripts/rh-selfdev.py", "status"],
            },
            {
                "id": "diff-check",
                "purpose": "Reject whitespace errors in the dirty bundle.",
                "argv": ["git", "diff", "--check"],
            },
        ],
    }


def detect_risk_flags(changed_files: list[str]) -> dict[str, bool]:
    flags = dict.fromkeys(RISK_KEYS, False)
    for file_name in changed_files:
        normalized = file_name.replace("\\", "/")
        if (
            "research_harness_mcp" in normalized
            or normalized.endswith("AGENTS.md")
            or "/skills/" in f"/{normalized}"
            or normalized.endswith("cli.py")
            or normalized.endswith("http_api.py")
        ):
            flags["public_surface_changed"] = True
        if (
            "/storage/" in f"/{normalized}"
            or "/provenance/" in f"/{normalized}"
            or normalized.startswith("packages/research_harness/migrations/")
        ):
            flags["storage_or_provenance_changed"] = True
        if "/orchestrator/" in f"/{normalized}" and any(
            part in normalized
            for part in (
                "gate",
                "transition",
                "rollback",
                "invariant",
                "stage",
            )
        ):
            flags["orchestrator_gate_changed"] = True
        if normalized.startswith("docs/researchflowbench-results") or (
            "researchflowbench" in normalized and "results" in normalized
        ):
            flags["benchmark_claim_changed"] = True
        if normalized.endswith(
            (
                "pyproject.toml",
                "poetry.lock",
                "package.json",
                "package-lock.json",
                "pnpm-lock.yaml",
                "yarn.lock",
                "requirements.txt",
            )
        ):
            flags["dependency_changed"] = True
    return flags


def _selfdev_fast_batch_default_subtasks() -> tuple[dict[str, Any], ...]:
    return (
        {
            "slice_id": SELFDEV_FAST_BATCH_PROTOCOL_SLICE_ID,
            "risk": "low",
            "category": "docs",
            "objective": "Document the private fast batch lane protocol.",
            "allowed_files": (
                ".rh-selfdev/control-plane.md",
                ".rh-selfdev/slices.md",
                ".rh-selfdev/handoffs/**",
                ".rh-selfdev/checkpoint.md",
            ),
            "focused_tests": (
                {
                    "id": "diff-check",
                    "purpose": "Reject whitespace errors after protocol edits.",
                    "argv": ("git", "diff", "--check"),
                },
            ),
        },
        {
            "slice_id": SELFDEV_FAST_BATCH_RUNNER_SLICE_ID,
            "risk": "low",
            "category": "private-helper",
            "objective": "Add private self-dev batch planning and report helpers.",
            "allowed_files": (
                "scripts/rh-selfdev.py",
                "packages/research_harness/tests/test_rh_selfdev_script.py",
                ".rh-selfdev/slices.md",
                ".rh-selfdev/handoffs/**",
                ".rh-selfdev/checkpoint.md",
            ),
            "focused_tests": (
                {
                    "id": "selfdev-script",
                    "purpose": "Focused self-dev helper regression coverage.",
                    "argv": (
                        ".venv/bin/python",
                        "-m",
                        "pytest",
                        "packages/research_harness/tests/test_rh_selfdev_script.py",
                        "-q",
                    ),
                },
            ),
        },
    )


def _argv_payload(argv: Any) -> list[str]:
    if isinstance(argv, str):
        raise ValueError("argv must be a sequence, not a shell string")
    try:
        return [str(arg) for arg in argv]
    except TypeError as exc:
        raise ValueError("argv must be a sequence") from exc


def _focused_test_payloads(focused_tests: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for index, entry in enumerate(focused_tests or ()):
        if not isinstance(entry, Mapping):
            raise ValueError("focused test entries must be mappings")
        payloads.append(
            {
                "id": str(entry.get("id") or f"focused-test-{index + 1}"),
                "purpose": str(entry.get("purpose") or "Focused batch check."),
                "argv": _argv_payload(entry.get("argv", ())),
            }
        )
    return payloads


def _string_sequence(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value]
    except TypeError as exc:
        raise ValueError("value must be a string or sequence") from exc


def _selfdev_fast_batch_rejection_reason(
    subtask: Mapping[str, Any],
) -> Optional[str]:
    risk = str(subtask.get("risk") or "").strip().lower()
    if risk != "low":
        return f"risk is {risk or 'unspecified'}"

    category = str(subtask.get("category") or "").strip().lower()
    if category in {
        "public-surface",
        "benchmark",
        "dependency",
        "external-action",
    }:
        return f"forbidden category: {category}"

    allowed_files = _string_sequence(subtask.get("allowed_files"))
    flags = detect_risk_flags(allowed_files)
    risky_flags = [key for key in RISK_KEYS if flags.get(key)]
    if risky_flags:
        return f"risk flags: {', '.join(risky_flags)}"

    if category in SELFDEV_FAST_BATCH_FORBIDDEN_CATEGORIES:
        return f"forbidden category: {category}"
    if category not in SELFDEV_FAST_BATCH_ALLOWED_CATEGORIES:
        return f"unsupported category: {category or 'unspecified'}"
    return None


def _selfdev_fast_batch_subtask_payload(
    subtask: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "slice_id": str(subtask["slice_id"]),
        "risk": str(subtask.get("risk") or "low"),
        "category": str(subtask["category"]),
        "objective": str(subtask.get("objective") or ""),
        "allowed_files": _string_sequence(subtask.get("allowed_files")),
        "focused_tests": _focused_test_payloads(subtask.get("focused_tests", ())),
    }


def _dedupe_focused_tests(
    subtasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    focused_tests: list[dict[str, Any]] = []
    for subtask in subtasks:
        for test in subtask["focused_tests"]:
            key = (test["id"], tuple(test["argv"]))
            if key in seen:
                continue
            seen.add(key)
            focused_tests.append(test)
    return focused_tests


def _selfdev_fast_batch_summary(
    *,
    batch_slice_id: str = SELFDEV_FAST_BATCH_RUNNER_SLICE_ID,
    subtasks: Optional[list[Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    selected_subtasks = (
        list(_selfdev_fast_batch_default_subtasks())
        if subtasks is None
        else list(subtasks)
    )
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for subtask in selected_subtasks:
        reason = _selfdev_fast_batch_rejection_reason(subtask)
        if reason is None:
            accepted.append(_selfdev_fast_batch_subtask_payload(subtask))
            continue
        rejected.append(
            {
                "slice_id": str(subtask.get("slice_id") or "unknown"),
                "risk": str(subtask.get("risk") or ""),
                "category": str(subtask.get("category") or ""),
                "rejection_reason": reason,
            }
        )

    if len(accepted) > SELFDEV_FAST_BATCH_MAX_SIZE:
        overflow = accepted[SELFDEV_FAST_BATCH_MAX_SIZE:]
        accepted = accepted[:SELFDEV_FAST_BATCH_MAX_SIZE]
        rejected.extend(
            {
                "slice_id": subtask["slice_id"],
                "risk": subtask["risk"],
                "category": subtask["category"],
                "rejection_reason": (
                    f"batch size exceeds fast lane max {SELFDEV_FAST_BATCH_MAX_SIZE}"
                ),
            }
            for subtask in overflow
        )

    verification_payload = _selfdev_verification_matrix_payload()
    return {
        "lane_id": SELFDEV_FAST_BATCH_LANE_ID,
        "batch_slice_id": batch_slice_id,
        "protocol_slice_id": SELFDEV_FAST_BATCH_PROTOCOL_SLICE_ID,
        "runner_slice_id": SELFDEV_FAST_BATCH_RUNNER_SLICE_ID,
        "batch_size": {
            "default": SELFDEV_FAST_BATCH_DEFAULT_SIZE,
            "min": SELFDEV_FAST_BATCH_MIN_SIZE,
            "max": SELFDEV_FAST_BATCH_MAX_SIZE,
            "actual": len(accepted),
        },
        "subtasks": accepted,
        "rejected_subtasks": rejected,
        "allowed_categories": sorted(SELFDEV_FAST_BATCH_ALLOWED_CATEGORIES),
        "risk_boundaries": list(SELFDEV_FAST_BATCH_RISK_BOUNDARIES),
        "focused_tests": _dedupe_focused_tests(accepted),
        "final_matrix_id": verification_payload["matrix_id"],
        "final_matrix_commands": verification_payload["commands"],
        "handoff_policy": (
            "Write one batch handoff and refresh one checkpoint after the "
            "batch-level verification matrix passes."
        ),
        "stop_rules": (
            "Stop on public surface, storage/provenance, orchestrator, "
            "benchmark, dependency, external action, repeated focused-test "
            "failure, or batch scope overflow."
        ),
    }


def git_changed_files(repo_root: Path = REPO_ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    changed: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append(path)
    return changed


def write_prompt(slice_def: SelfDevSlice, prompt_dir: Optional[Path] = None) -> Path:
    prompt_dir = prompt_dir or PROMPT_DIR
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"{slice_def.slice_id}.md"
    created_at = timestamp()
    text = build_worker_prompt(slice_def)
    prompt_path.write_text(text, encoding="utf-8")
    _append_prompt_runtime_event(
        path=prompt_path,
        text=text,
        created_at=created_at,
        slice_def=slice_def,
    )
    return prompt_path


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _prompt_event_metadata(
    *,
    path: Path,
    text: str,
    slice_def: SelfDevSlice,
) -> dict[str, Any]:
    return {
        "prompt_bytes": len(text.encode("utf-8")),
        "prompt_path": _display_path(path),
        "slice_id": slice_def.slice_id,
    }


def _append_prompt_runtime_event(
    *,
    path: Path,
    text: str,
    created_at: str,
    slice_def: SelfDevSlice,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import normalize_selfdev_prompt
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        record = normalize_selfdev_prompt(
            path=Path(_display_path(path)),
            text=text,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_prompt_event_metadata(
                path=path,
                text=text,
                slice_def=slice_def,
            ),
        )
    except Exception:
        return None


def update_slice_status(
    *,
    slice_id: str,
    new_status: str,
    path: Path = SLICES_FILE,
) -> str:
    if not is_valid_slice_id(slice_id):
        raise ValueError(f"invalid slice id: {slice_id}")
    if new_status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {new_status}")

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    updated_lines: list[str] = []
    previous_status: Optional[str] = None
    for line in lines:
        cells = _parse_raw_table_row(line)
        if cells is None or _strip_cell(cells[0]) != slice_id:
            updated_lines.append(line)
            continue
        previous_status = _strip_cell(cells[2])
        cells[2] = new_status
        updated_lines.append(f"| {' | '.join(cells)} |")

    if previous_status is None:
        raise ValueError(f"unknown slice id: {slice_id}")

    trailing_newline = "\n" if text.endswith("\n") else ""
    path.write_text("\n".join(updated_lines) + trailing_newline, encoding="utf-8")
    return previous_status


def _slice_status_event_metadata(
    *,
    path: Path,
    slice_id: str,
    previous_status: str,
    new_status: str,
) -> dict[str, Any]:
    return {
        "new_status": new_status,
        "previous_status": previous_status,
        "slice_id": slice_id,
        "slices_path": _display_path(path),
    }


def _redact_selfdev_freeform_metadata(value: Any) -> Any:
    if isinstance(value, str):
        redacted = value
        for pattern in SELFDEV_FREEFORM_METADATA_REDACTION_PATTERNS:
            redacted = pattern.sub("[redacted]", redacted)
        return redacted
    if isinstance(value, list):
        return [_redact_selfdev_freeform_metadata(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_selfdev_freeform_metadata(item) for item in value)
    if isinstance(value, dict):
        return {
            key: _redact_selfdev_freeform_metadata(item) for key, item in value.items()
        }
    return value


def _redacted_selfdev_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _redact_selfdev_freeform_metadata(value) for key, value in values.items()
    }


def _selfdev_redaction_invariant_families() -> tuple[dict[str, Any], ...]:
    must_not_persist = (
        "prompt_body",
        "stdout_body",
        "stderr_body",
        "raw_environment_id",
        "credential_like_token",
        "cloud_task_output",
    )
    helper = "_redact_selfdev_freeform_metadata"
    return (
        {
            "family": "checkpoint",
            "scope": SELFDEV_VERIFICATION_MATRIX_SCOPE,
            "redacts_freeform_values": True,
            "freeform_fields": ("notes",),
            "redaction_helper": helper,
            "must_not_persist": must_not_persist,
        },
        {
            "family": "handoff",
            "scope": SELFDEV_VERIFICATION_MATRIX_SCOPE,
            "redacts_freeform_values": True,
            "freeform_fields": ("notes",),
            "redaction_helper": helper,
            "must_not_persist": must_not_persist,
        },
        {
            "family": "gate",
            "scope": SELFDEV_VERIFICATION_MATRIX_SCOPE,
            "redacts_freeform_values": True,
            "freeform_fields": ("tests",),
            "redaction_helper": helper,
            "must_not_persist": must_not_persist,
        },
        {
            "family": "status",
            "scope": SELFDEV_VERIFICATION_MATRIX_SCOPE,
            "redacts_freeform_values": True,
            "freeform_fields": ("reason",),
            "redaction_helper": helper,
            "must_not_persist": must_not_persist,
        },
        {
            "family": "next-action",
            "scope": SELFDEV_VERIFICATION_MATRIX_SCOPE,
            "redacts_freeform_values": True,
            "freeform_fields": ("reason", "human_gate"),
            "redaction_helper": helper,
            "must_not_persist": must_not_persist,
        },
        {
            "family": "cloud-command",
            "scope": SELFDEV_VERIFICATION_MATRIX_SCOPE,
            "redacts_freeform_values": True,
            "freeform_fields": ("branch",),
            "redaction_helper": helper,
            "must_not_persist": must_not_persist,
        },
        {
            "family": "codex-command",
            "scope": SELFDEV_VERIFICATION_MATRIX_SCOPE,
            "redacts_freeform_values": True,
            "freeform_fields": ("model", "output_path", "prompt_path", "worktree_path"),
            "redaction_helper": helper,
            "must_not_persist": must_not_persist,
        },
        {
            "family": "cloud-submit",
            "scope": SELFDEV_VERIFICATION_MATRIX_SCOPE,
            "redacts_freeform_values": True,
            "freeform_fields": ("branch",),
            "redaction_helper": helper,
            "must_not_persist": must_not_persist,
        },
    )


def _append_slice_status_runtime_event(
    *,
    path: Path,
    created_at: str,
    slice_id: str,
    previous_status: str,
    new_status: str,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import (
            normalize_selfdev_slice_status_change,
        )
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        record = normalize_selfdev_slice_status_change(
            path=Path(_display_path(path)),
            slice_id=slice_id,
            previous_status=previous_status,
            new_status=new_status,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_slice_status_event_metadata(
                path=path,
                slice_id=slice_id,
                previous_status=previous_status,
                new_status=new_status,
            ),
        )
    except Exception:
        return None


def write_slice_status(
    *,
    slice_id: str,
    new_status: str,
    path: Optional[Path] = None,
) -> str:
    slices_path = path or SLICES_FILE
    created_at = timestamp()
    previous_status = update_slice_status(
        slice_id=slice_id,
        new_status=new_status,
        path=slices_path,
    )
    _append_slice_status_runtime_event(
        path=slices_path,
        created_at=created_at,
        slice_id=slice_id,
        previous_status=previous_status,
        new_status=new_status,
    )
    return previous_status


def _next_action_event_metadata(
    *,
    action: dict[str, str],
    path: Path,
) -> dict[str, Any]:
    return {
        "action": action.get("action"),
        "phase": action.get("phase"),
        "risk": action.get("risk"),
        "slice_id": action.get("slice_id"),
        "slices_path": _display_path(path),
    }


def _status_event_payload(
    *,
    action: dict[str, str],
    changed_files: list[str],
    risk_flags: dict[str, bool],
) -> dict[str, Any]:
    safe_action = _redacted_selfdev_mapping(action)
    return {
        "action": safe_action.get("action"),
        "dirty_file_count": len(changed_files),
        "phase": safe_action.get("phase"),
        "reason": safe_action.get("reason"),
        "risk": safe_action.get("risk"),
        "risk_flags": dict(risk_flags),
        "slice_id": safe_action.get("slice_id"),
    }


def _status_event_metadata(
    *,
    status_payload: dict[str, Any],
    path: Path,
) -> dict[str, Any]:
    return {
        "action": status_payload.get("action"),
        "dirty_file_count": status_payload.get("dirty_file_count"),
        "phase": status_payload.get("phase"),
        "risk": status_payload.get("risk"),
        "risk_flags": status_payload.get("risk_flags"),
        "slice_id": status_payload.get("slice_id"),
        "slices_path": _display_path(path),
    }


def _append_status_runtime_event(
    *,
    action: dict[str, str],
    changed_files: list[str],
    risk_flags: dict[str, bool],
    created_at: str,
    path: Path = SLICES_FILE,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import normalize_selfdev_status
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        status_payload = _status_event_payload(
            action=action,
            changed_files=changed_files,
            risk_flags=risk_flags,
        )
        record = normalize_selfdev_status(
            path=Path(_display_path(path)),
            status_payload=status_payload,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_status_event_metadata(
                status_payload=status_payload,
                path=path,
            ),
        )
    except Exception:
        return None


def _cloud_command_event_context(
    *,
    slice_def: SelfDevSlice,
    command: list[str],
    environment_id: str,
    branch: str,
    attempts: int,
) -> dict[str, Any]:
    return {
        "attempts": attempts,
        "branch": _redact_selfdev_freeform_metadata(branch),
        "command_argc": len(command),
        "environment_id_present": bool(environment_id.strip()),
        "slice_id": slice_def.slice_id,
    }


def _cloud_command_event_metadata(
    *,
    command_context: dict[str, Any],
    path: Path,
) -> dict[str, Any]:
    return {
        "attempts": command_context.get("attempts"),
        "branch": command_context.get("branch"),
        "command_argc": command_context.get("command_argc"),
        "environment_id_present": command_context.get("environment_id_present"),
        "slice_id": command_context.get("slice_id"),
        "slices_path": _display_path(path),
    }


def _append_cloud_command_runtime_event(
    *,
    slice_def: SelfDevSlice,
    command: list[str],
    environment_id: str,
    branch: str,
    attempts: int,
    created_at: str,
    path: Path = SLICES_FILE,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import (
            normalize_selfdev_cloud_command,
        )
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        command_context = _cloud_command_event_context(
            slice_def=slice_def,
            command=command,
            environment_id=environment_id,
            branch=branch,
            attempts=attempts,
        )
        record = normalize_selfdev_cloud_command(
            path=Path(_display_path(path)),
            command_context=command_context,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_cloud_command_event_metadata(
                command_context=command_context,
                path=path,
            ),
        )
    except Exception:
        return None


def _cloud_submit_event_context(
    *,
    slice_def: SelfDevSlice,
    command: list[str],
    environment_id: str,
    branch: str,
    attempts: int,
    returncode: int,
) -> dict[str, Any]:
    return {
        "attempts": attempts,
        "branch": _redact_selfdev_freeform_metadata(branch),
        "command_argc": len(command),
        "environment_id_present": bool(environment_id.strip()),
        "returncode": returncode,
        "slice_id": slice_def.slice_id,
    }


def _cloud_submit_event_metadata(
    *,
    command_context: dict[str, Any],
    path: Path,
) -> dict[str, Any]:
    return {
        "attempts": command_context.get("attempts"),
        "branch": command_context.get("branch"),
        "command_argc": command_context.get("command_argc"),
        "environment_id_present": command_context.get("environment_id_present"),
        "returncode": command_context.get("returncode"),
        "slice_id": command_context.get("slice_id"),
        "slices_path": _display_path(path),
    }


def _cloud_submit_started_event_context(
    *,
    slice_def: SelfDevSlice,
    command: list[str],
    environment_id: str,
    branch: str,
    attempts: int,
) -> dict[str, Any]:
    return {
        "attempts": attempts,
        "branch": _redact_selfdev_freeform_metadata(branch),
        "command_argc": len(command),
        "environment_id_present": bool(environment_id.strip()),
        "slice_id": slice_def.slice_id,
    }


def _cloud_submit_started_event_metadata(
    *,
    command_context: dict[str, Any],
    path: Path,
) -> dict[str, Any]:
    return {
        "attempts": command_context.get("attempts"),
        "branch": command_context.get("branch"),
        "command_argc": command_context.get("command_argc"),
        "environment_id_present": command_context.get("environment_id_present"),
        "slice_id": command_context.get("slice_id"),
        "slices_path": _display_path(path),
    }


def _append_cloud_submit_started_runtime_event(
    *,
    slice_def: SelfDevSlice,
    command: list[str],
    environment_id: str,
    branch: str,
    attempts: int,
    created_at: str,
    path: Path = SLICES_FILE,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import (
            normalize_selfdev_cloud_submit_started,
        )
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        command_context = _cloud_submit_started_event_context(
            slice_def=slice_def,
            command=command,
            environment_id=environment_id,
            branch=branch,
            attempts=attempts,
        )
        record = normalize_selfdev_cloud_submit_started(
            path=Path(_display_path(path)),
            command_context=command_context,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_cloud_submit_started_event_metadata(
                command_context=command_context,
                path=path,
            ),
        )
    except Exception:
        return None


def _append_cloud_submit_runtime_event(
    *,
    slice_def: SelfDevSlice,
    command: list[str],
    environment_id: str,
    branch: str,
    attempts: int,
    returncode: int,
    created_at: str,
    path: Path = SLICES_FILE,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import (
            normalize_selfdev_cloud_submit,
        )
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        command_context = _cloud_submit_event_context(
            slice_def=slice_def,
            command=command,
            environment_id=environment_id,
            branch=branch,
            attempts=attempts,
            returncode=returncode,
        )
        record = normalize_selfdev_cloud_submit(
            path=Path(_display_path(path)),
            command_context=command_context,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_cloud_submit_event_metadata(
                command_context=command_context,
                path=path,
            ),
        )
    except Exception:
        return None


def _append_cloud_submit_failure_runtime_event(
    *,
    slice_def: SelfDevSlice,
    command: list[str],
    environment_id: str,
    branch: str,
    attempts: int,
    returncode: int,
    created_at: str,
    path: Path = SLICES_FILE,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import (
            normalize_selfdev_cloud_submit_failure,
        )
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        command_context = _cloud_submit_event_context(
            slice_def=slice_def,
            command=command,
            environment_id=environment_id,
            branch=branch,
            attempts=attempts,
            returncode=returncode,
        )
        record = normalize_selfdev_cloud_submit_failure(
            path=Path(_display_path(path)),
            command_context=command_context,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_cloud_submit_event_metadata(
                command_context=command_context,
                path=path,
            ),
        )
    except Exception:
        return None


def _best_effort_cloud_submit_event_append(
    appender: Any,
    **kwargs: Any,
) -> Optional[object]:
    try:
        return appender(**kwargs)
    except Exception:
        return None


def _codex_command_event_context(
    *,
    slice_def: SelfDevSlice,
    command: list[str],
    worktree_path: Path,
    prompt_path: Path,
    output_path: Path,
    model: Optional[str],
) -> dict[str, Any]:
    return {
        "command_argc": len(command),
        "model": _redact_selfdev_freeform_metadata(model),
        "output_path": _redact_selfdev_freeform_metadata(str(output_path)),
        "prompt_path": _redact_selfdev_freeform_metadata(str(prompt_path)),
        "slice_id": slice_def.slice_id,
        "worktree_path": _redact_selfdev_freeform_metadata(str(worktree_path)),
    }


def _codex_command_event_metadata(
    *,
    command_context: dict[str, Any],
    path: Path,
) -> dict[str, Any]:
    return {
        "command_argc": command_context.get("command_argc"),
        "model": command_context.get("model"),
        "output_path": command_context.get("output_path"),
        "prompt_path": command_context.get("prompt_path"),
        "slice_id": command_context.get("slice_id"),
        "slices_path": _display_path(path),
        "worktree_path": command_context.get("worktree_path"),
    }


def _append_codex_command_runtime_event(
    *,
    slice_def: SelfDevSlice,
    command: list[str],
    worktree_path: Path,
    prompt_path: Path,
    output_path: Path,
    model: Optional[str],
    created_at: str,
    path: Path = SLICES_FILE,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import (
            normalize_selfdev_codex_command,
        )
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        command_context = _codex_command_event_context(
            slice_def=slice_def,
            command=command,
            worktree_path=worktree_path,
            prompt_path=prompt_path,
            output_path=output_path,
            model=model,
        )
        record = normalize_selfdev_codex_command(
            path=Path(_display_path(path)),
            command_context=command_context,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_codex_command_event_metadata(
                command_context=command_context,
                path=path,
            ),
        )
    except Exception:
        return None


def _append_next_action_runtime_event(
    *,
    action: dict[str, str],
    created_at: str,
    path: Path = SLICES_FILE,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import (
            normalize_selfdev_next_action,
        )
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        safe_action = _redacted_selfdev_mapping(action)
        record = normalize_selfdev_next_action(
            path=Path(_display_path(path)),
            action=safe_action,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_next_action_event_metadata(
                action=safe_action,
                path=path,
            ),
        )
    except Exception:
        return None


def write_gate_report(
    *,
    slice_def: SelfDevSlice,
    task_id: Optional[str],
    executor: str,
    changed_files: list[str],
    diff_text: str = "",
    tests: str = "",
    gate_dir: Path = GATE_DIR,
) -> Path:
    gate_dir.mkdir(parents=True, exist_ok=True)
    flags = detect_risk_flags(changed_files)
    recommended = "request_changes" if any(flags.values()) else "approve"
    created_at = timestamp()
    lines = [
        f"# Gate: {slice_def.slice_id}",
        "",
        f"Date: {created_at}",
        f"Executor: {executor}",
        f"Task id: {task_id or 'n/a'}",
        f"Recommendation: {recommended}",
        "",
        "## Objective",
        "",
        slice_def.objective,
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- `{file_name}`" for file_name in changed_files)
    if not changed_files:
        lines.append("- None reported.")
    lines.extend(["", "## Tests", "", tests or slice_def.tests or "Not reported."])
    lines.extend(["", "## Risk Flags", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in flags.items())
    lines.extend(["", "## Diff Preview", ""])
    if diff_text:
        preview = "\n".join(diff_text.splitlines()[:120])
        lines.extend(["```diff", preview, "```"])
    else:
        lines.append("No diff attached.")
    lines.extend(
        [
            "",
            "## Human Gate",
            "",
            slice_def.human_gate,
        ]
    )
    gate_path = gate_dir / f"{slice_def.slice_id}-{created_at}.md"
    text = "\n".join(lines) + "\n"
    gate_path.write_text(text, encoding="utf-8")
    _append_gate_report_runtime_event(
        path=gate_path,
        text=text,
        created_at=created_at,
        slice_def=slice_def,
        task_id=task_id,
        changed_files=changed_files,
        tests=tests,
        recommendation=recommended,
    )
    return gate_path


def _gate_report_event_metadata(
    *,
    path: Path,
    slice_def: SelfDevSlice,
    task_id: Optional[str],
    changed_files: list[str],
    tests: str,
    recommendation: str,
) -> dict[str, Any]:
    return {
        "changed_file_count": len(changed_files),
        "gate_path": _display_path(path),
        "recommendation": recommendation,
        "risk_flags": detect_risk_flags(changed_files),
        "slice_id": slice_def.slice_id,
        "task_id": task_id or "n/a",
        "tests": _redact_selfdev_freeform_metadata(tests),
    }


def _append_gate_report_runtime_event(
    *,
    path: Path,
    text: str,
    created_at: str,
    slice_def: SelfDevSlice,
    task_id: Optional[str],
    changed_files: list[str],
    tests: str,
    recommendation: str,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import (
            normalize_selfdev_gate_report,
        )
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        record = normalize_selfdev_gate_report(
            path=Path(_display_path(path)),
            text=text,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_gate_report_event_metadata(
                path=path,
                slice_def=slice_def,
                task_id=task_id,
                changed_files=changed_files,
                tests=tests,
                recommendation=recommendation,
            ),
        )
    except Exception:
        return None


def build_handoff_text(
    *,
    slice_def: SelfDevSlice,
    created_at: str,
    executor: str,
    status: str,
    changed_files: list[str],
    tests: str,
    notes: list[str],
    next_action: str,
) -> str:
    flags = detect_risk_flags(changed_files)
    lines = [
        f"# Handoff: {slice_def.slice_id}",
        "",
        f"Date: {created_at}",
        f"Executor: {executor}",
        f"Status: {status}",
        "",
        "## Objective",
        "",
        slice_def.objective,
        "",
        "## Changes",
        "",
    ]
    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- Handoff written by `scripts/rh-selfdev.py handoff`.")
    lines.extend(["", "## Changed Files", ""])
    if changed_files:
        lines.extend(f"- `{file_name}`" for file_name in changed_files)
    else:
        lines.append("- None reported.")
    lines.extend(
        ["", "## Verification", "", tests or slice_def.tests or "Not reported."]
    )
    lines.extend(["", "## Risk Flags", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in flags.items())
    lines.extend(["", "## Next Action", "", next_action or "Not reported."])
    return "\n".join(lines) + "\n"


def _handoff_event_metadata(
    *,
    path: Path,
    slice_def: SelfDevSlice,
    changed_files: list[str],
    notes: list[str],
    status: str,
) -> dict[str, Any]:
    return {
        "dirty_file_count": len(changed_files),
        "handoff_path": _display_path(path),
        "notes": _redact_selfdev_freeform_metadata(list(notes)),
        "risk_flags": detect_risk_flags(changed_files),
        "slice_id": slice_def.slice_id,
        "status": status,
    }


def _append_handoff_runtime_event(
    *,
    path: Path,
    text: str,
    created_at: str,
    slice_def: SelfDevSlice,
    changed_files: list[str],
    notes: list[str],
    status: str,
) -> Optional[object]:
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import (
            normalize_selfdev_handoff,
        )
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        record = normalize_selfdev_handoff(
            path=Path(_display_path(path)),
            text=text,
            created_at=created_at,
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_handoff_event_metadata(
                path=path,
                slice_def=slice_def,
                changed_files=changed_files,
                notes=notes,
                status=status,
            ),
        )
    except Exception:
        return None


def write_handoff(
    *,
    slice_def: SelfDevSlice,
    path: Optional[Path] = None,
    status: str = "done",
    executor: str = "codex",
    changed_files: Optional[list[str]] = None,
    tests: str = "",
    notes: Optional[list[str]] = None,
    next_action: str = "",
) -> Path:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid handoff status: {status}")
    created_at = timestamp()
    handoff_path = path or HANDOFF_DIR / f"{slice_def.slice_id}-{created_at}.md"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    changed = changed_files if changed_files is not None else git_changed_files()
    note_values = notes or []
    text = build_handoff_text(
        slice_def=slice_def,
        created_at=created_at,
        executor=executor,
        status=status,
        changed_files=changed,
        tests=tests,
        notes=note_values,
        next_action=next_action,
    )
    handoff_path.write_text(text, encoding="utf-8")
    _append_handoff_runtime_event(
        path=handoff_path,
        text=text,
        created_at=created_at,
        slice_def=slice_def,
        changed_files=changed,
        notes=note_values,
        status=status,
    )
    return handoff_path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _recent_artifacts(directory: Path, limit: int = 5) -> list[str]:
    if not directory.exists():
        return []
    artifacts = [path for path in directory.glob("*.md") if path.name != "README.md"]
    return [
        _display_path(path)
        for path in sorted(
            artifacts,
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
    ][:limit]


def _current_slice_summary(slices: list[SelfDevSlice]) -> list[str]:
    gate_slice = select_pending_gate(slices)
    if gate_slice is not None:
        return [
            f"Pending gate: {gate_slice.slice_id}",
            f"Phase/risk: {gate_slice.phase}/{gate_slice.risk}",
            f"Objective: {gate_slice.objective}",
            f"Human gate: {gate_slice.human_gate}",
        ]
    active_slice = select_active_slice(slices)
    if active_slice is not None:
        return [
            f"Active slice: {active_slice.slice_id}",
            f"Phase/risk: {active_slice.phase}/{active_slice.risk}",
            f"Objective: {active_slice.objective}",
            f"Allowed files: {active_slice.allowed_files}",
            f"Tests: {active_slice.tests}",
            f"Human gate: {active_slice.human_gate}",
        ]
    try:
        next_slice = select_next_slice(slices)
    except ValueError:
        return ["No todo self-development slice remains."]
    return [
        f"Next slice: {next_slice.slice_id}",
        f"Phase/risk: {next_slice.phase}/{next_slice.risk}",
        f"Objective: {next_slice.objective}",
        f"Allowed files: {next_slice.allowed_files}",
        f"Tests: {next_slice.tests}",
        f"Human gate: {next_slice.human_gate}",
    ]


def _next_slice_id(slices: list[SelfDevSlice], suffix: str) -> str:
    numbers: list[int] = []
    for slice_def in slices:
        match = re.match(r"^S(\d+)_", slice_def.slice_id)
        if match:
            numbers.append(int(match.group(1)))
    next_number = max(numbers, default=-1) + 1
    return f"S{next_number:02d}_{suffix}"


def _next_knowledge_slice_id(slices: list[SelfDevSlice], suffix: str) -> str:
    numbers: list[int] = []
    for slice_def in slices:
        match = re.match(r"^K(\d+)_", slice_def.slice_id)
        if match:
            numbers.append(int(match.group(1)))
    next_number = max(numbers, default=98) + 1
    return f"K{next_number}_{suffix}"


def _transport_inventory_template(slices: list[SelfDevSlice]) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(slices, TRANSPORT_INVENTORY_TEMPLATE_SUFFIX),
        "phase": "P3",
        "risk": "low",
        "objective": (
            "Inventory ResearchService-equivalent read-only commands across "
            "Python, CLI, and HTTP transports without routing runtime paths."
        ),
        "reason": "no todo slice remains and transport inventory is missing",
        "allowed_files": (
            "`docs/service-layer-plan.md`; `.rh-selfdev/*`; "
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`"
        ),
        "tests": (
            "`python3 scripts/rh-selfdev.py next-action --json`; "
            "`.venv/bin/python -m pytest "
            "packages/research_harness/tests/test_rh_selfdev_script.py -q`; "
            "`scripts/codex-check.sh --quick`"
        ),
        "human_gate": (
            "No gate unless the slice changes public RH surface or runtime behavior."
        ),
        "stop_rules": (
            "Create one bounded slice before editing; stop before runtime "
            "routing, public surface, storage/provenance, orchestrator, "
            "benchmark, dependency, or compact-threshold boundary changes."
        ),
    }


def _cli_route_test_template(slices: list[SelfDevSlice]) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(slices, CLI_ROUTE_TEST_TEMPLATE_SUFFIX),
        "phase": "P3",
        "risk": "low",
        "objective": (
            "Add a CLI read-only ResearchService route test harness before any "
            "CLI runtime routing changes."
        ),
        "reason": "transport inventory exists; next safe step is test harness",
        "allowed_files": (
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`; "
            "`packages/research_harness/tests/**`; `scripts/**`"
        ),
        "tests": (
            "focused CLI transport tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "No gate unless the slice routes CLI runtime behavior or changes CLI output shape."
        ),
        "stop_rules": (
            "Stop before CLI runtime routing, public output-shape changes, "
            "storage/provenance, orchestrator, benchmark, dependency, or "
            "compact-threshold boundary changes."
        ),
    }


def _cli_topic_read_routing_template(slices: list[SelfDevSlice]) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(slices, CLI_TOPIC_READ_ROUTING_TEMPLATE_SUFFIX),
        "phase": "P3",
        "risk": "medium",
        "objective": (
            "Route CLI topic list and topic show through ResearchService while "
            "preserving the locked JSON output shape."
        ),
        "reason": "CLI read shape tests exist; next safe step is bounded routing",
        "allowed_files": (
            "`packages/research_harness/research_harness/cli.py`; "
            "`packages/research_harness/tests/test_cli_read_service_shape.py`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "CLI shape tests; focused service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "No gate if public CLI output shape is preserved and focused tests pass; "
            "gate required for output-shape or public command changes."
        ),
        "stop_rules": (
            "Stop before changing CLI command names, JSON output shape, storage/"
            "provenance ownership, orchestrator gates, benchmark claims, "
            "dependencies, or compact-threshold boundaries."
        ),
    }


def _cli_paper_list_routing_template(slices: list[SelfDevSlice]) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(slices, CLI_PAPER_LIST_ROUTING_TEMPLATE_SUFFIX),
        "phase": "P3",
        "risk": "medium",
        "objective": (
            "Route CLI paper list through ResearchService while preserving the "
            "locked JSON output shape."
        ),
        "reason": "CLI topic reads are service-backed; next safe CLI read group is paper list",
        "allowed_files": (
            "`packages/research_harness/research_harness/cli.py`; "
            "`packages/research_harness/tests/test_cli_read_service_shape.py`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "CLI shape tests; focused service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "No gate if public CLI output shape is preserved and focused tests pass; "
            "gate required for output-shape or public command changes."
        ),
        "stop_rules": (
            "Stop before changing CLI command names, JSON output shape, storage/"
            "provenance ownership, orchestrator gates, benchmark claims, "
            "dependencies, or compact-threshold boundaries."
        ),
    }


def _cli_provenance_summary_routing_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(
            slices, CLI_PROVENANCE_SUMMARY_ROUTING_TEMPLATE_SUFFIX
        ),
        "phase": "P3",
        "risk": "medium",
        "objective": (
            "Route CLI provenance summary through ResearchService while "
            "preserving the locked JSON output shape."
        ),
        "reason": "CLI paper list is service-backed; next safe CLI read group is provenance summary",
        "allowed_files": (
            "`packages/research_harness/research_harness/cli.py`; "
            "`packages/research_harness/tests/test_cli_read_service_shape.py`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "CLI shape tests; focused service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "No gate if public CLI output shape is preserved and focused tests pass; "
            "gate required for output-shape or public command changes."
        ),
        "stop_rules": (
            "Stop before changing CLI command names, JSON output shape, storage/"
            "provenance ownership, orchestrator gates, benchmark claims, "
            "dependencies, or compact-threshold boundaries."
        ),
    }


def _cli_provenance_export_routing_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(
            slices, CLI_PROVENANCE_EXPORT_ROUTING_TEMPLATE_SUFFIX
        ),
        "phase": "P3",
        "risk": "medium",
        "objective": (
            "Route CLI provenance export through ResearchService while "
            "preserving the locked JSON output shape."
        ),
        "reason": (
            "CLI provenance summary is service-backed; next safe CLI read group "
            "is provenance export"
        ),
        "allowed_files": (
            "`packages/research_harness/research_harness/cli.py`; "
            "`packages/research_harness/tests/test_cli_read_service_shape.py`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "CLI shape tests; focused service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "No gate if public CLI output shape is preserved and focused tests pass; "
            "gate required for output-shape or public command changes."
        ),
        "stop_rules": (
            "Stop before changing CLI command names, JSON output shape, storage/"
            "provenance ownership, orchestrator gates, benchmark claims, "
            "dependencies, or compact-threshold boundaries."
        ),
    }


def _cli_orchestrator_read_routing_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(
            slices, CLI_ORCHESTRATOR_READ_ROUTING_TEMPLATE_SUFFIX
        ),
        "phase": "P3",
        "risk": "high",
        "objective": (
            "Route CLI orchestrator status and orchestrator gate-check through "
            "ResearchService while preserving the locked JSON output shape."
        ),
        "reason": (
            "CLI provenance export is service-backed; next LG2 candidate is "
            "read-only orchestrator CLI routing"
        ),
        "allowed_files": (
            "`packages/research_harness/research_harness/cli.py`; "
            "`packages/research_harness/tests/test_cli_read_service_shape.py`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "CLI shape tests; focused service/orchestrator read tests; "
            "`scripts/codex-check.sh --quick`; `git diff --check`"
        ),
        "human_gate": (
            "Gate required for any orchestrator gate-decision, transition, or "
            "JSON output-shape change; no gate for adapter-only routing that "
            "preserves read-only semantics and passes focused tests."
        ),
        "stop_rules": (
            "Stop before changing CLI command names, JSON output shape, "
            "orchestrator gate decisions/transitions, storage/provenance "
            "ownership, benchmark claims, dependencies, or compact-threshold "
            "boundaries."
        ),
    }


def _python_orchestrator_read_routing_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(
            slices, PYTHON_ORCHESTRATOR_READ_ROUTING_TEMPLATE_SUFFIX
        ),
        "phase": "P3",
        "risk": "high",
        "objective": (
            "Route Python facade orchestrator read helpers through "
            "ResearchService while preserving existing return shapes."
        ),
        "reason": (
            "CLI orchestrator reads are service-backed; next LG2 candidate is "
            "Python facade orchestrator read routing"
        ),
        "allowed_files": (
            "`packages/research_harness/research_harness/api.py`; "
            "`packages/research_harness/tests/**`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "focused Python facade/service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "Gate required for public Python return-shape changes or any "
            "orchestrator gate-decision/transition change; no gate for "
            "adapter-only routing that preserves shapes and semantics."
        ),
        "stop_rules": (
            "Stop before changing Python public return shapes, orchestrator "
            "gate decisions/transitions, storage/provenance ownership, "
            "benchmark claims, dependencies, or compact-threshold boundaries."
        ),
    }


def _http_topic_list_routing_template(slices: list[SelfDevSlice]) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(slices, HTTP_TOPIC_LIST_ROUTING_TEMPLATE_SUFFIX),
        "phase": "P3",
        "risk": "medium",
        "objective": (
            "Route HTTP topic_list equivalent through ResearchService while "
            "preserving the existing HTTP response shape."
        ),
        "reason": (
            "Python facade orchestrator reads are service-backed; next LG2 "
            "candidate is HTTP topic_list routing"
        ),
        "allowed_files": (
            "`packages/research_harness_mcp/research_harness_mcp/http_api.py`; "
            "`packages/research_harness_mcp/tests/**`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "focused HTTP API/service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "Gate required for public HTTP route or response-shape changes; no "
            "gate for adapter-only routing that preserves shape and semantics."
        ),
        "stop_rules": (
            "Stop before changing HTTP paths, response shape, storage/provenance "
            "ownership, orchestrator gates, benchmark claims, dependencies, or "
            "compact-threshold boundaries."
        ),
    }


def _http_provenance_summary_routing_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(
            slices, HTTP_PROVENANCE_SUMMARY_ROUTING_TEMPLATE_SUFFIX
        ),
        "phase": "P3",
        "risk": "medium",
        "objective": (
            "Route HTTP provenance_summary equivalent through ResearchService "
            "while preserving the existing HTTP response shape."
        ),
        "reason": (
            "HTTP topic_list is service-backed; next LG2 candidate is HTTP "
            "provenance_summary routing"
        ),
        "allowed_files": (
            "`packages/research_harness_mcp/research_harness_mcp/http_api.py`; "
            "`packages/research_harness_mcp/tests/**`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "focused HTTP API/service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "Gate required for public HTTP route or response-shape changes; no "
            "gate for adapter-only routing that preserves shape and semantics."
        ),
        "stop_rules": (
            "Stop before changing HTTP paths, response shape, storage/provenance "
            "ownership, orchestrator gates, benchmark claims, dependencies, or "
            "compact-threshold boundaries."
        ),
    }


def _http_deferred_shape_harness_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(slices, HTTP_DEFERRED_SHAPE_HARNESS_TEMPLATE_SUFFIX),
        "phase": "P3",
        "risk": "low",
        "objective": (
            "Add HTTP read-only response-shape tests for deferred-shape LG2 "
            "transport candidates before routing more HTTP endpoints through "
            "ResearchService."
        ),
        "reason": (
            "HTTP topic_list and provenance_summary are service-backed; the "
            "remaining HTTP equivalents are deferred-shape candidates that need "
            "focused shape tests before runtime routing."
        ),
        "allowed_files": (
            "`packages/research_harness_mcp/tests/**`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "focused HTTP API shape tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "No gate unless the slice routes HTTP runtime behavior or changes "
            "public HTTP response shapes."
        ),
        "stop_rules": (
            "Stop before HTTP runtime routing, public route or response-shape "
            "changes, storage/provenance ownership, orchestrator gates, "
            "benchmark claims, dependencies, or compact-threshold boundaries."
        ),
    }


def _http_topic_show_routing_template(slices: list[SelfDevSlice]) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(slices, HTTP_TOPIC_SHOW_ROUTING_TEMPLATE_SUFFIX),
        "phase": "P3",
        "risk": "medium",
        "objective": (
            "Route HTTP topic_show equivalent through ResearchService while "
            "preserving the existing HTTP topic detail response shape."
        ),
        "reason": (
            "HTTP deferred-shape tests are locked; next LG2 candidate is HTTP "
            "topic_show routing."
        ),
        "allowed_files": (
            "`packages/research_harness_mcp/research_harness_mcp/http_api.py`; "
            "`packages/research_harness_mcp/tests/**`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "focused HTTP API/service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "Gate required for public HTTP route or response-shape changes; no "
            "gate for adapter-only routing that preserves shape and semantics."
        ),
        "stop_rules": (
            "Stop before changing HTTP paths, response shape, storage/provenance "
            "ownership, orchestrator gates, benchmark claims, dependencies, or "
            "compact-threshold boundaries."
        ),
    }


def _http_paper_list_routing_template(slices: list[SelfDevSlice]) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(slices, HTTP_PAPER_LIST_ROUTING_TEMPLATE_SUFFIX),
        "phase": "P3",
        "risk": "medium",
        "objective": (
            "Route HTTP paper_list equivalent through ResearchService while "
            "preserving the existing HTTP pagination and filter response shape."
        ),
        "reason": (
            "HTTP topic_show is service-backed; next LG2 candidate is HTTP "
            "paper_list routing."
        ),
        "allowed_files": (
            "`packages/research_harness_mcp/research_harness_mcp/http_api.py`; "
            "`packages/research_harness_mcp/tests/**`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "focused HTTP API/service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "Gate required for public HTTP route or response-shape changes; no "
            "gate for adapter-only routing that preserves shape and semantics."
        ),
        "stop_rules": (
            "Stop before changing HTTP paths, response shape, storage/provenance "
            "ownership, orchestrator gates, benchmark claims, dependencies, or "
            "compact-threshold boundaries."
        ),
    }


def _http_orchestrator_gate_check_routing_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(
            slices, HTTP_ORCHESTRATOR_GATE_CHECK_ROUTING_TEMPLATE_SUFFIX
        ),
        "phase": "P3",
        "risk": "high",
        "objective": (
            "Route HTTP orchestrator_gate_check equivalent through "
            "ResearchService while preserving the existing HTTP gate "
            "pass-through response shape."
        ),
        "reason": (
            "HTTP paper_list is service-backed; next LG2 deferred-shape "
            "candidate is HTTP orchestrator_gate_check routing."
        ),
        "allowed_files": (
            "`packages/research_harness_mcp/research_harness_mcp/http_api.py`; "
            "`packages/research_harness_mcp/tests/**`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "focused HTTP API/service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "Gate required for orchestrator gate behavior changes; no gate for "
            "adapter-only read routing that preserves shape and semantics."
        ),
        "stop_rules": (
            "Stop before changing HTTP paths, response shape, storage/provenance "
            "ownership, orchestrator gate decisions/transitions, benchmark "
            "claims, dependencies, or compact-threshold boundaries."
        ),
    }


def _http_orchestrator_status_routing_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(
            slices, HTTP_ORCHESTRATOR_STATUS_ROUTING_TEMPLATE_SUFFIX
        ),
        "phase": "P3",
        "risk": "high",
        "objective": (
            "Route HTTP orchestrator_status equivalent through ResearchService "
            "while preserving the existing HTTP topic detail status response "
            "shape."
        ),
        "reason": (
            "HTTP orchestrator_gate_check is service-backed; next LG2 "
            "deferred-shape candidate is HTTP orchestrator_status routing."
        ),
        "allowed_files": (
            "`packages/research_harness_mcp/research_harness_mcp/http_api.py`; "
            "`packages/research_harness_mcp/tests/**`; "
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`"
        ),
        "tests": (
            "focused HTTP API/service tests; `scripts/codex-check.sh --quick`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "Gate required for orchestrator status behavior changes; no gate "
            "for adapter-only read routing that preserves shape and semantics."
        ),
        "stop_rules": (
            "Stop before changing HTTP paths, response shape, storage/provenance "
            "ownership, orchestrator gate decisions/transitions, benchmark "
            "claims, dependencies, or compact-threshold boundaries."
        ),
    }


def _lg3_compatibility_lifecycle_guard_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(
            slices, LG3_COMPATIBILITY_LIFECYCLE_GUARD_TEMPLATE_SUFFIX
        ),
        "phase": "P3",
        "risk": "low",
        "objective": (
            "Add a machine-checked compatibility lifecycle guard for Tier B "
            "inventory decisions without changing compatibility runtime "
            "behavior or public MCP tool names."
        ),
        "reason": (
            "LG2 transport convergence is complete; next long-goal boundary is "
            "LG3 compatibility surface rationalization."
        ),
        "allowed_files": (
            "`docs/mcp-tool-audit.md`; "
            "`docs/contracts/compatibility-inventory.md`; "
            "`.rh-selfdev/*`; `scripts/**`; "
            "`packages/research_harness/tests/**`"
        ),
        "tests": (
            "focused compatibility inventory guard tests; "
            "`python3 scripts/check-mcp-public-surface.py`; "
            "`scripts/codex-check.sh --quick`; `git diff --check`"
        ),
        "human_gate": (
            "No gate for a docs-only/read-only guard; gate required before "
            "deprecating, removing, or changing compatibility names or public "
            "tool listings."
        ),
        "stop_rules": (
            "Stop before changing compatibility runtime behavior, public MCP "
            "tool names, advertised tool count, storage/provenance, "
            "orchestrator gates, benchmark claims, dependencies, or "
            "compact-threshold boundaries."
        ),
    }


def _architecture_completion_audit_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_slice_id(
            slices, ARCHITECTURE_COMPLETION_AUDIT_TEMPLATE_SUFFIX
        ),
        "phase": "P3",
        "risk": "low",
        "objective": (
            "Produce an architecture completion audit for LG1 deferred-gate "
            "coverage, LG2 transport convergence, and LG3 compatibility guard "
            "status without changing runtime behavior."
        ),
        "reason": (
            "LG3 compatibility lifecycle guard is complete; the architecture "
            "line needs one final evidence-backed completion audit."
        ),
        "allowed_files": (
            "`.rh-selfdev/*`; `docs/service-layer-plan.md`; `docs/mcp-tool-audit.md`"
        ),
        "tests": (
            "`python3 scripts/check-service-coverage.py`; "
            "`python3 scripts/check-transport-service-coverage.py`; "
            "`python3 scripts/check-mcp-public-surface.py`; "
            "`python3 scripts/check-compatibility-inventory.py`; "
            "`scripts/codex-check.sh --quick`; `git diff --check`"
        ),
        "human_gate": (
            "No gate for a docs-only completion audit; gate required before "
            "routing deferred mutating tools, changing compatibility behavior, "
            "or touching Zotero runtime."
        ),
        "stop_rules": (
            "Stop before runtime routing, compatibility behavior changes, "
            "public surface changes, storage/provenance, orchestrator gates, "
            "benchmark claims, dependencies, Zotero runtime work, or "
            "compact-threshold boundaries."
        ),
    }


def _architecture_line_complete_action(
    audit_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "complete_architecture_line",
        "slice_id": audit_slice.slice_id,
        "phase": audit_slice.phase,
        "risk": audit_slice.risk,
        "objective": "Architecture optimization line is complete for the authorized scope.",
        "reason": (
            "LG1, LG2, and LG3 architecture criteria are satisfied for the "
            "authorized non-Zotero scope; remaining deferred gates require "
            "separate human approval before runtime behavior changes."
        ),
        "human_gate": (
            "None for current architecture scope. Deferred mutating/storage/"
            "orchestrator/Zotero work remains gate-bound and is not part of "
            "this completed line."
        ),
    }


def _topic_knowledge_local_preview_closeout_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices, KNOWLEDGE_LOCAL_PREVIEW_CLOSEOUT_SUFFIX
        ),
        "phase": "P5",
        "risk": "low",
        "objective": (
            "Close out the Topic Knowledge and Cross-Topic local CLI previews "
            "by refreshing self-development next-action state, verifying local "
            "preview/public-surface guards, and documenting deferred gates "
            "without runtime behavior changes."
        ),
        "reason": (
            "K94 and K98 local CLI previews are complete; self-development "
            "automation should stop falling back to the completed architecture "
            "line and record the knowledge preview boundary."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/rh-topic-knowledge-layer-v1-spec.md`"
        ),
        "tests": (
            "`.venv/bin/python -m pytest "
            "packages/research_harness/tests/test_rh_selfdev_script.py -q`; "
            "`python3 scripts/rh-selfdev.py next-action --json`; "
            "`.venv/bin/python -m pytest "
            "packages/research_harness/tests/test_cli_knowledge_status.py "
            "packages/research_harness/tests/test_cli_cross_topic_atlas.py "
            "packages/research_harness/tests/test_mcp_public_surface_guard.py "
            "packages/research_harness/tests/test_topic_knowledge_regression_guards.py -q`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "No gate for self-development closeout only. Gate required before "
            "MCP, HTTP, Zotero, skill, storage/provenance, orchestrator, "
            "benchmark, dependency, commit, push, PR, release, or RH/ARE "
            "changes."
        ),
        "stop_rules": (
            "Stop before runtime behavior changes, new public surface beyond "
            "the already approved local CLI previews, storage/provenance, "
            "artifact lineage, orchestrator gates, benchmark claims, "
            "dependencies, RH/ARE boundary changes, or compact-threshold "
            "boundaries."
        ),
    }


def _topic_knowledge_line_complete_action(
    closeout_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "complete_topic_knowledge_line",
        "slice_id": closeout_slice.slice_id,
        "phase": closeout_slice.phase,
        "risk": closeout_slice.risk,
        "objective": (
            "Topic Knowledge local preview line is complete for the authorized "
            "K91-K99 scope."
        ),
        "reason": (
            "Knowledge-status and Cross-Topic Atlas local CLI previews are "
            "implemented and closed out; remaining persistent, transport, "
            "or product integrations require separate human-gated slices."
        ),
        "human_gate": (
            "None for K99 closeout. Future MCP/HTTP/Zotero/skill exposure, "
            "storage/provenance, artifact lineage, orchestrator integration, "
            "benchmark claims, dependency changes, commits, pushes, PRs, "
            "releases, or RH/ARE changes remain gate-bound."
        ),
    }


def _topic_knowledge_http_beta_line_complete_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "complete_topic_knowledge_line",
        "slice_id": completion_slice.slice_id,
        "phase": completion_slice.phase,
        "risk": completion_slice.risk,
        "objective": (
            "Topic Knowledge controlled beta HTTP API/docs line is complete "
            "for the authorized scope."
        ),
        "reason": (
            "The approved read-only CLI and HTTP beta previews are implemented, "
            "hardened, documented, and covered by acceptance repair checks; "
            "remaining product integrations require separate human-gated slices."
        ),
        "human_gate": (
            "None for controlled beta completion. Future stable external API "
            "release, MCP/Zotero/skill exposure, storage/provenance, artifact "
            "lineage, orchestrator integration, benchmark claims, dependency "
            "changes, commits, pushes, PRs, releases, or RH/ARE changes remain "
            "gate-bound."
        ),
    }


def _runtime_shell_p5_slice_done(
    slices: list[SelfDevSlice],
    suffix: str,
) -> bool:
    return any(
        slice_def.status == "done" and slice_def.slice_id.endswith(suffix)
        for slice_def in slices
    )


def _runtime_shell_p5_slice_by_suffix(
    slices: list[SelfDevSlice],
    suffix: str,
) -> Optional[SelfDevSlice]:
    for slice_def in reversed(slices):
        if slice_def.status == "done" and slice_def.slice_id.endswith(suffix):
            return slice_def
    return None


def _runtime_shell_p5_complete_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "complete_runtime_shell_p5",
        "slice_id": completion_slice.slice_id,
        "phase": completion_slice.phase,
        "risk": completion_slice.risk,
        "objective": (
            "LG6 runtime-shell P5 read-model and read-only diagnostics line is "
            "complete for the S58-approved scope."
        ),
        "reason": (
            "K103-K108 implemented the event, job-ledger, tool-boundary, "
            "skill-provenance, doctor, and showcase manifest read-model "
            "helpers without public shape, storage/provenance, artifact "
            "lineage, orchestrator gate, benchmark, dependency, or RH/ARE "
            "changes."
        ),
        "human_gate": (
            "P6 storage, public MCP/CLI/HTTP/Zotero/skill wiring, artifact "
            "lineage, orchestrator gate behavior, benchmark claims, dependency "
            "changes, commits, pushes, PRs, releases, or RH/ARE moves require a "
            "fresh human-gated slice before execution."
        ),
    }


def _runtime_shell_p6a_boundary_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": completion_slice.slice_id,
        "phase": completion_slice.phase,
        "risk": completion_slice.risk,
        "objective": (
            "LG6 runtime-shell P6A opt-in doctor diagnostics preview is "
            "complete for the K109-approved scope."
        ),
        "reason": (
            "P6A public CLI preview is complete; no additional P6 storage, "
            "public-surface, artifact-lineage, orchestrator, benchmark, "
            "dependency, Zotero, HTTP, MCP, release, PR, push, or RH/ARE work "
            "is approved."
        ),
        "human_gate": (
            "A fresh gate-approved slice is required before any broader "
            "runtime-shell migration or public-surface expansion."
        ),
    }


def _runtime_event_store_schema_boundary_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": completion_slice.slice_id,
        "phase": completion_slice.phase,
        "risk": completion_slice.risk,
        "objective": (
            "LG6 runtime-shell P6B schema-only runtime event store foundation "
            "is complete for the K112-approved scope."
        ),
        "reason": (
            "The runtime event store schema is complete; no writer integration, "
            "backfill, provenance ownership change, public surface, artifact "
            "lineage, orchestrator, benchmark, dependency, Zotero, HTTP, MCP, "
            "release, PR, push, or RH/ARE work is approved."
        ),
        "human_gate": (
            "A fresh gate-approved slice is required before writer integration "
            "or historical backfill into runtime_events."
        ),
    }


def _runtime_event_store_first_source_boundary_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": completion_slice.slice_id,
        "phase": completion_slice.phase,
        "risk": completion_slice.risk,
        "objective": (
            "LG6 runtime-shell P6B first live runtime event source is complete "
            "for the K121-approved self-dev checkpoint scope."
        ),
        "reason": (
            "The first self-dev checkpoint source is complete; no additional "
            "live source routing, backfill, provenance ownership change, "
            "public surface, artifact lineage, orchestrator, benchmark, "
            "dependency, Zotero, HTTP, MCP, release, PR, push, or RH/ARE work "
            "is approved."
        ),
        "human_gate": (
            "A fresh gate-approved slice is required before routing any other "
            "live source into runtime_events or changing runtime event storage "
            "semantics."
        ),
    }


def _runtime_event_store_handoff_source_boundary_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": completion_slice.slice_id,
        "phase": completion_slice.phase,
        "risk": completion_slice.risk,
        "objective": (
            "LG6 runtime-shell P6B second live runtime event source is complete "
            "for the K123-approved self-dev handoff scope."
        ),
        "reason": (
            "The self-dev handoff source is complete; no additional live "
            "source routing, backfill, provenance ownership change, public "
            "surface, artifact lineage, orchestrator, benchmark, dependency, "
            "Zotero, HTTP, MCP, release, PR, push, or RH/ARE work is approved."
        ),
        "human_gate": (
            "A fresh gate-approved slice is required before routing any "
            "additional live source into runtime_events or changing runtime "
            "event storage semantics."
        ),
    }


def _runtime_event_store_gate_report_source_boundary_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": completion_slice.slice_id,
        "phase": completion_slice.phase,
        "risk": completion_slice.risk,
        "objective": (
            "LG6 runtime-shell P6B third live runtime event source is complete "
            "for the K124-approved self-dev gate report scope."
        ),
        "reason": (
            "The self-dev gate report source is complete; no additional live "
            "source routing, backfill, provenance ownership change, public "
            "surface, artifact lineage, orchestrator, benchmark, dependency, "
            "Zotero, HTTP, MCP, release, PR, push, or RH/ARE work is approved."
        ),
        "human_gate": (
            "A fresh gate-approved slice is required before routing any "
            "additional live source into runtime_events or changing runtime "
            "event storage semantics."
        ),
    }


def _runtime_event_store_prompt_source_boundary_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": completion_slice.slice_id,
        "phase": completion_slice.phase,
        "risk": completion_slice.risk,
        "objective": (
            "LG6 runtime-shell P6B fourth live runtime event source is complete "
            "for the K126-approved self-dev prompt scope."
        ),
        "reason": (
            "The self-dev prompt source is complete; no additional live source "
            "routing, backfill, provenance ownership change, public surface, "
            "artifact lineage, orchestrator, benchmark, dependency, Zotero, "
            "HTTP, MCP, release, PR, push, or RH/ARE work is approved."
        ),
        "human_gate": (
            "A fresh gate-approved slice is required before routing any "
            "additional live source into runtime_events or changing runtime "
            "event storage semantics."
        ),
    }


def _runtime_event_store_slice_status_source_boundary_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": completion_slice.slice_id,
        "phase": completion_slice.phase,
        "risk": completion_slice.risk,
        "objective": (
            "LG6 runtime-shell P6B fifth live runtime event source is complete "
            "for the K128-approved self-dev slice-status scope."
        ),
        "reason": (
            "The self-dev slice-status source is complete; no additional live "
            "source routing, backfill, provenance ownership change, public "
            "surface, artifact lineage, orchestrator, benchmark, dependency, "
            "Zotero, HTTP, MCP, release, PR, push, or RH/ARE work is approved."
        ),
        "human_gate": (
            "A fresh gate-approved slice is required before routing any "
            "additional live source into runtime_events or changing runtime "
            "event storage semantics."
        ),
    }


def _runtime_event_store_next_action_source_boundary_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": completion_slice.slice_id,
        "phase": completion_slice.phase,
        "risk": completion_slice.risk,
        "objective": (
            "LG6 runtime-shell P6B sixth live runtime event source is complete "
            "for the K130-approved self-dev next-action scope."
        ),
        "reason": (
            "The self-dev next-action source is complete; no additional live "
            "source routing, backfill, provenance ownership change, public "
            "surface, artifact lineage, orchestrator, benchmark, dependency, "
            "Zotero, HTTP, MCP, release, PR, push, or RH/ARE work is approved."
        ),
        "human_gate": (
            "A fresh gate-approved slice is required before routing any "
            "additional live source into runtime_events or changing runtime "
            "event storage semantics."
        ),
    }


def _selfdev_batch_source_candidates() -> tuple[dict[str, str], ...]:
    return (
        {
            "suffix": RUNTIME_EVENT_STORE_SELFDEV_STATUS_SOURCE_SUFFIX,
            "event_type": "selfdev.status_reported",
            "source": "`python3 scripts/rh-selfdev.py status` reports",
            "focused_test": "packages/research_harness/tests/test_rh_selfdev_script.py",
            "safe": "true",
        },
        {
            "suffix": RUNTIME_EVENT_STORE_SELFDEV_CLOUD_COMMAND_SOURCE_SUFFIX,
            "event_type": "selfdev.cloud_command_rendered",
            "source": (
                "`python3 scripts/rh-selfdev.py cloud-command` dry-run command "
                "rendering"
            ),
            "focused_test": "packages/research_harness/tests/test_rh_selfdev_script.py",
            "safe": "true",
        },
        {
            "suffix": RUNTIME_EVENT_STORE_SELFDEV_CODEX_COMMAND_SOURCE_SUFFIX,
            "event_type": "selfdev.codex_command_rendered",
            "source": "script-owned local `codex exec` dry-run command rendering",
            "focused_test": "packages/research_harness/tests/test_rh_selfdev_script.py",
            "safe": "true",
        },
        {
            "suffix": RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_SOURCE_SUFFIX,
            "event_type": "selfdev.cloud_submit_recorded",
            "source": "`python3 scripts/rh-selfdev.py cloud-submit` submission",
            "safe": "false",
            "blocked_reason": (
                "cloud-submit is an external action and is not covered by the "
                "self-dev batch authorization window"
            ),
        },
    )


def _selfdev_batch_source_is_done(
    slices: list[SelfDevSlice],
    suffix: str,
) -> bool:
    return _runtime_shell_p5_slice_done(slices, suffix)


def _selfdev_batch_completed_safe_sources(
    slices: list[SelfDevSlice],
) -> list[SelfDevSlice]:
    safe_suffixes = {
        candidate["suffix"]
        for candidate in _selfdev_batch_source_candidates()
        if candidate.get("safe") == "true"
    }
    return [
        slice_def
        for slice_def in slices
        if slice_def.status == "done"
        and any(slice_def.slice_id.endswith(suffix) for suffix in safe_suffixes)
    ]


def _selfdev_batch_wait_action(
    *,
    reference_slice: SelfDevSlice,
    reason: str,
    human_gate: str,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": reference_slice.slice_id,
        "phase": reference_slice.phase,
        "risk": "high",
        "objective": (
            "LG6 runtime-shell P6B self-dev runtime event source batch window "
            "is paused."
        ),
        "reason": reason,
        "human_gate": human_gate,
    }


def _selfdev_batch_source_template(
    *,
    slices: list[SelfDevSlice],
    candidate: dict[str, str],
    completed_safe_count: int,
    window_size: int,
) -> dict[str, str]:
    event_type = candidate["event_type"]
    source = candidate["source"]
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(slices, candidate["suffix"]),
        "phase": "P6",
        "risk": "high",
        "objective": (
            f"Route only {source} into the private append-only "
            f"`runtime_events` store as `{event_type}`, with deterministic "
            "event ids, inert metadata, duplicate handling, and non-fatal "
            "event-store failure."
        ),
        "reason": (
            "K132 batch gate is active; this is a whitelisted homogeneous "
            "self-dev runtime event source inside the approved batch window."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/research_harness/runtime/event_normalizer.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`packages/research_harness/tests/test_runtime_event_normalizer.py`; "
            "`packages/research_harness/tests/test_runtime_event_store_public_surface_guard.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/rh-runtime-shell-implementation-plan.md`; "
            "`.rh-selfdev/long-goals.md`"
        ),
        "tests": (
            "`.venv/bin/python -m pytest "
            "packages/research_harness/tests/test_rh_selfdev_script.py "
            "packages/research_harness/tests/test_runtime_event_normalizer.py -q`; "
            "`.venv/bin/python -m pytest "
            "packages/research_harness/tests/test_runtime_event_store_public_surface_guard.py "
            "packages/research_harness/tests/test_mcp_public_surface_guard.py -q`; "
            "scoped ruff for touched Python files; "
            "`python3 scripts/rh-selfdev.py status`; "
            "`python3 scripts/rh-selfdev.py next-action --json`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "Covered by K132 only while the slice stays within the homogeneous "
            "self-dev runtime event source whitelist. Fresh approval is "
            "required for cloud-submit, public surface, backfill, storage "
            "semantics, provenance ownership, artifact lineage, orchestrator "
            "gates, benchmark claims, dependencies, Zotero, HTTP, MCP, RH/ARE, "
            "commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop after the focused slice handoff/checkpoint, after three "
            "batch sources, if no safe candidate remains, if focused tests fail "
            "twice, or before any forbidden scope expansion."
        ),
        "batch_window_remaining": str(window_size - completed_safe_count),
        "batch_window_size": str(window_size),
    }


def _selfdev_extended_batch_candidates() -> tuple[dict[str, str], ...]:
    return (
        {
            "suffix": RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_EVENT_SEQUENCE_HARDENING_SUFFIX,
            "objective": (
                "Harden the cloud-submit runtime event sequence so started, "
                "success, and failure events remain ordered, redacted, and "
                "non-fatal without running real Cloud submissions."
            ),
            "reason_detail": "cloud-submit runtime event sequence hardening",
        },
        {
            "suffix": RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STORE_FAILURE_HARDENING_SUFFIX,
            "objective": (
                "Harden cloud-submit event-store failure handling so started, "
                "success, and failure event append failures cannot alter "
                "stdout, stderr, or return-code behavior."
            ),
            "reason_detail": "cloud-submit event-store failure hardening",
        },
        {
            "suffix": RUNTIME_EVENT_STORE_SELFDEV_REDACTION_GUARD_SUFFIX,
            "objective": (
                "Add a focused guard proving self-dev runtime event payloads "
                "and metadata exclude prompt text, stdout/stderr bodies, "
                "environment ids, credentials, and Cloud task output bodies."
            ),
            "reason_detail": "self-dev runtime event redaction guard",
        },
        {
            "suffix": RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_EXTENDED_BATCH_RECOVERY_SUFFIX,
            "objective": (
                "Harden next-action recovery around the extended batch window "
                "so completed candidates, risk flags, and focused-test failure "
                "boundaries remain deterministic."
            ),
            "reason_detail": "extended batch next-action recovery hardening",
        },
        {
            "suffix": RUNTIME_EVENT_STORE_SELFDEV_EVENT_STORE_CONTRACT_REFRESH_SUFFIX,
            "objective": (
                "Refresh private runtime event store contract coverage for the "
                "expanded self-dev event families without changing schema, "
                "storage semantics, or public surfaces."
            ),
            "reason_detail": "self-dev event-store contract refresh",
        },
        {
            "suffix": RUNTIME_EVENT_STORE_SELFDEV_EXTENDED_BATCH_CLOSEOUT_SUFFIX,
            "objective": (
                "Create the extended batch closeout review package and pause "
                "at a phase checkpoint before any broader runtime-shell work."
            ),
            "reason_detail": "extended batch closeout review",
        },
    )


def _selfdev_extended_batch_completed_slices(
    slices: list[SelfDevSlice],
) -> list[SelfDevSlice]:
    completed: list[SelfDevSlice] = []
    for candidate in _selfdev_extended_batch_candidates():
        slice_def = _runtime_shell_p5_slice_by_suffix(slices, candidate["suffix"])
        if slice_def is not None:
            completed.append(slice_def)
    return completed


def _selfdev_extended_batch_source_template(
    *,
    slices: list[SelfDevSlice],
    candidate: dict[str, str],
    completed_count: int,
    window_size: int,
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(slices, candidate["suffix"]),
        "phase": "P6",
        "risk": "high",
        "objective": candidate["objective"],
        "reason": (
            "K144 extended batch gate is active; this is an allowlisted "
            f"{candidate['reason_detail']} slice inside the approved window."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/research_harness/runtime/event_normalizer.py`; "
            "`packages/research_harness/research_harness/runtime/event_store.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`packages/research_harness/tests/test_runtime_event_normalizer.py`; "
            "`packages/research_harness/tests/test_runtime_event_store_contract.py`; "
            "`packages/research_harness/tests/test_runtime_event_store_readback.py`; "
            "`packages/research_harness/tests/test_runtime_event_store_writer.py`; "
            "`packages/research_harness/tests/test_runtime_event_store_public_surface_guard.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/rh-runtime-shell-implementation-plan.md`; "
            "`.rh-selfdev/long-goals.md`"
        ),
        "tests": (
            "focused RED/GREEN tests for the selected slice; "
            "`.venv/bin/python -m pytest "
            "packages/research_harness/tests/test_rh_selfdev_script.py "
            "packages/research_harness/tests/test_runtime_event_normalizer.py -q`; "
            "`.venv/bin/python -m pytest "
            "packages/research_harness/tests/test_runtime_event_store_contract.py "
            "packages/research_harness/tests/test_runtime_event_store_readback.py "
            "packages/research_harness/tests/test_runtime_event_store_writer.py -q`; "
            "`.venv/bin/python -m pytest "
            "packages/research_harness/tests/test_runtime_event_store_public_surface_guard.py "
            "packages/research_harness/tests/test_mcp_public_surface_guard.py -q`; "
            "scoped ruff for touched Python files; "
            "`python3 scripts/rh-selfdev.py status`; "
            "`python3 scripts/rh-selfdev.py next-action --json`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "Covered by K144 only while the slice stays inside the explicit "
            "extended self-dev runtime event source and event-store hardening "
            "allowlist. Fresh approval is required for real Cloud submission, "
            "Cloud diff apply, public surface, storage schema/semantics, "
            "provenance ownership, artifact lineage, orchestrator gates, "
            "benchmark claims, dependencies, Zotero, HTTP, MCP, RH/ARE, "
            "commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop after the focused slice handoff/checkpoint, after the K144 "
            "window is exhausted, if focused tests fail twice, if risk flags "
            "appear, or before any forbidden scope expansion."
        ),
        "batch_window_remaining": str(window_size - completed_count),
        "batch_window_size": str(window_size),
    }


def _runtime_event_store_post_closeout_review_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices, RUNTIME_EVENT_STORE_POST_CLOSEOUT_REVIEW_PACKAGE_SUFFIX
        ),
        "phase": "P6",
        "risk": "low",
        "objective": (
            "Create a docs-only post-K150 runtime event store review package "
            "that groups the current dirty worktree, verification evidence, "
            "and remaining gate boundaries before broader runtime-shell work."
        ),
        "reason": (
            "K151 post-closeout review gate is active; create exactly one "
            "docs-only review package before any implementation expansion."
        ),
        "allowed_files": (
            "`.rh-selfdev/rh-runtime-shell-post-k150-review-package-2026-06-11.md`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/rh-runtime-shell-implementation-plan.md`; "
            "`.rh-selfdev/long-goals.md`"
        ),
        "tests": (
            "`git diff --check`; "
            "`python3 scripts/rh-selfdev.py status`; "
            "`python3 scripts/rh-selfdev.py next-action --json`"
        ),
        "human_gate": (
            "Covered by K151 only for a docs-only review package. No real "
            "Cloud submission, Cloud diff apply, public surface, storage "
            "schema/semantics, provenance ownership, artifact lineage, "
            "orchestrator gate, benchmark claim, dependency, Zotero, HTTP, "
            "MCP, RH/ARE, commit, push, PR, release, or publishing change is "
            "approved."
        ),
        "stop_rules": (
            "Stop after the review package handoff/checkpoint, if risk flags "
            "appear, or before any forbidden implementation expansion."
        ),
    }


def _runtime_event_store_post_closeout_review_done_action(
    review_slice: SelfDevSlice,
) -> dict[str, str]:
    return _selfdev_batch_wait_action(
        reference_slice=review_slice,
        reason=(
            "post-K150 review package is complete; stop before additional "
            "runtime-shell implementation work"
        ),
        human_gate=(
            "A fresh gate is required before implementation expansion, live "
            "source routing, storage/public-surface changes, or runtime event "
            "storage semantic changes."
        ),
    )


def _runtime_event_store_internal_review_audit_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices, RUNTIME_EVENT_STORE_INTERNAL_REVIEW_AUDIT_SUFFIX
        ),
        "phase": "P6",
        "risk": "low",
        "objective": (
            "Run a review/audit pass over the K138-K152 runtime event store "
            "and self-dev runtime event changes, recording concrete findings, "
            "safe-fix candidates, and large-risk boundaries without changing "
            "runtime behavior."
        ),
        "reason": (
            "K153 broad autonomy policy is active; this is a low-risk "
            "internal review/audit slice before selecting the next "
            "implementation line."
        ),
        "allowed_files": (
            "`.rh-selfdev/rh-runtime-shell-post-k150-review-package-2026-06-11.md`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/rh-runtime-shell-implementation-plan.md`; "
            "`.rh-selfdev/long-goals.md`"
        ),
        "tests": (
            "`git diff --check`; "
            "`python3 scripts/rh-selfdev.py status`; "
            "`python3 scripts/rh-selfdev.py next-action --json`"
        ),
        "human_gate": (
            "Covered by K153 broad autonomy for non-large-risk internal "
            "review/audit work only. Stop for external actions, commits, "
            "pushes, PRs, releases, dependencies, public surface changes, "
            "storage/provenance/orchestrator semantics, benchmark claims, "
            "Zotero, HTTP, MCP, or RH/ARE boundary changes."
        ),
        "stop_rules": (
            "Stop if the audit identifies a large-risk boundary, if files "
            "outside the review scope are required, or if verification fails "
            "twice."
        ),
    }


def _runtime_event_store_internal_review_audit_done_action(
    audit_slice: SelfDevSlice,
) -> dict[str, str]:
    return _selfdev_batch_wait_action(
        reference_slice=audit_slice,
        reason=(
            "internal review audit is complete; select the next "
            "non-large-risk implementation line explicitly"
        ),
        human_gate=(
            "Under the K153 broad autonomy policy, continue autonomously for "
            "bounded non-large-risk internal slices; stop for large-risk "
            "external actions, public surface, storage/provenance/orchestrator "
            "semantics, benchmark claims, dependencies, commits, pushes, PRs, "
            "releases, publishing, Zotero, HTTP, MCP, or RH/ARE boundary "
            "changes."
        ),
    )


def _runtime_event_store_broad_autonomy_followup_done_action(
    completion_slice: SelfDevSlice,
) -> dict[str, str]:
    label = _runtime_event_store_broad_autonomy_followup_label(completion_slice)
    return _selfdev_batch_wait_action(
        reference_slice=completion_slice,
        reason=(
            f"{label} is complete; select the next non-large-risk "
            "implementation line explicitly"
        ),
        human_gate=(
            "Under the K153 broad autonomy policy, continue autonomously for "
            "bounded non-large-risk internal slices; stop for large-risk "
            "external actions, public surface, storage/provenance/orchestrator "
            "semantics, benchmark claims, dependencies, commits, pushes, PRs, "
            "releases, publishing, Zotero, HTTP, MCP, or RH/ARE boundary "
            "changes."
        ),
    )


def _runtime_event_store_broad_autonomy_followup_label(
    completion_slice: SelfDevSlice,
) -> str:
    _, _, remainder = completion_slice.slice_id.partition("_")
    for prefix in (
        "RUNTIME_EVENT_STORE_SELFDEV_",
        "RUNTIME_EVENT_STORE_",
        "RUNTIME_SHELL_",
    ):
        if remainder.startswith(prefix):
            remainder = remainder.removeprefix(prefix)
            break
    label = remainder.lower().replace("_", " ")
    return label.replace("post audit", "post-audit").replace(
        "next action",
        "next-action",
    )


def _k_slice_number(slice_id: str) -> Optional[int]:
    match = K_SLICE_NUMBER_PATTERN.match(slice_id)
    if match is None:
        return None
    return int(match.group("number"))


def _runtime_event_store_latest_broad_autonomy_followup(
    slices: list[SelfDevSlice],
    audit_slice: SelfDevSlice,
) -> Optional[SelfDevSlice]:
    try:
        audit_index = slices.index(audit_slice)
    except ValueError:
        return None

    latest: Optional[SelfDevSlice] = None
    latest_number = -1
    for slice_def in slices[audit_index + 1 :]:
        k_number = _k_slice_number(slice_def.slice_id)
        if (
            slice_def.status == "done"
            and slice_def.phase == "P6"
            and slice_def.risk == "low"
            and k_number is not None
            and k_number > latest_number
        ):
            latest = slice_def
            latest_number = k_number
    return latest


def _runtime_event_store_broad_autonomy_next_action(
    slices: list[SelfDevSlice],
) -> Optional[dict[str, str]]:
    gate_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        RUNTIME_SHELL_BROAD_AUTONOMY_POLICY_GATE_SUFFIX,
    )
    if gate_slice is None:
        return None

    audit_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        RUNTIME_EVENT_STORE_INTERNAL_REVIEW_AUDIT_SUFFIX,
    )
    if audit_slice is not None:
        followup_slice = _runtime_event_store_latest_broad_autonomy_followup(
            slices,
            audit_slice,
        )
        if followup_slice is not None:
            return _runtime_event_store_broad_autonomy_followup_done_action(
                followup_slice
            )
        return _runtime_event_store_internal_review_audit_done_action(audit_slice)

    return _runtime_event_store_internal_review_audit_template(slices)


def _lg8_private_performance_baseline_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG8_PRIVATE_PERFORMANCE_BASELINE_SUFFIX,
        ),
        "phase": "P8",
        "risk": "low",
        "objective": (
            "Create the LG8 private performance baseline runner and report for "
            "cold-start, read-path, runtime-event, job-resume, and "
            "verification-matrix timings without benchmark promotion claims."
        ),
        "reason": (
            "LG8/LG9/LG10 long-goal activation is complete; performance "
            "governance starts with a private baseline before durable-semantics "
            "or public-productization work."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`scripts/rh-perf-baseline.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`packages/research_harness/tests/test_rh_perf_baseline.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/rh-performance-baseline-*.md`; "
            "`.rh-selfdev/rh-performance-baseline-*.json`"
        ),
        "tests": (
            "RED/GREEN private baseline runner tests; "
            "`python3 scripts/rh-selfdev.py next-action --json`; "
            "`python3 scripts/rh-selfdev.py status`; "
            "`python3 scripts/rh-selfdev.py verification-matrix --json`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "No gate for private measurement tooling and private reports. Stop "
            "before public surface changes, storage/provenance/orchestrator "
            "semantics, benchmark promotion claims, dependency changes, "
            "external actions, credential/config mutation, local/private data "
            "exposure, compatibility-name removal, Zotero, HTTP, MCP, RH/ARE, "
            "commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before public surface, storage/provenance, orchestrator, "
            "benchmark promotion, dependency, external-action, credential, "
            "local/private-data, Zotero, HTTP, MCP, RH/ARE, commit, push, PR, "
            "release, or publishing boundaries."
        ),
    }


def _lg8_private_performance_baseline_done_action(
    baseline_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": baseline_slice.slice_id,
        "phase": baseline_slice.phase,
        "risk": baseline_slice.risk,
        "objective": baseline_slice.objective,
        "reason": (
            "private performance baseline is complete; select the first "
            "evidence-backed hot-path optimization slice explicitly"
        ),
        "human_gate": (
            "Under LG8, continue only for bounded private hot-path optimization "
            "slices with before/after evidence. Stop before benchmark "
            "promotion claims, public surface, storage/provenance, "
            "orchestrator, dependency, external, Zotero, HTTP, MCP, RH/ARE, "
            "commit, push, PR, release, or publishing changes."
        ),
    }


def _lg8_lg9_combined_execution_contract_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG8_LG9_COMBINED_EXECUTION_CONTRACT_SUFFIX,
        ),
        "phase": "P8",
        "risk": "low",
        "objective": (
            "Bind LG8 performance governance and LG9 durable semantics as a "
            "combined execution contract."
        ),
        "reason": (
            "K172 private performance baseline is complete; bind LG8 evidence "
            "flow to LG9 durable semantics before starting hot-path work."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/rh-lg8-lg9-combined-execution-plan-2026-06-11.md`"
        ),
        "tests": (
            "RED/GREEN focused next-action recovery tests; "
            "`python3 scripts/rh-selfdev.py next-action --json`; "
            "`python3 scripts/rh-selfdev.py status`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "No gate for private planning and recovery tooling. Stop before "
            "public surface changes, storage/provenance/orchestrator "
            "semantics, benchmark promotion claims, dependency changes, "
            "external actions, credential/config mutation, local/private data "
            "exposure, compatibility-name removal, Zotero, HTTP, MCP, RH/ARE, "
            "commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before public surface, storage/provenance, orchestrator, "
            "benchmark promotion, dependency, external-action, credential, "
            "local/private-data, Zotero, HTTP, MCP, RH/ARE, commit, push, PR, "
            "release, or publishing boundaries."
        ),
    }


def _lg8_selfdev_next_action_hot_path_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG8_SELFDEV_NEXT_ACTION_RECOVERY_HOT_PATH_SUFFIX,
        ),
        "phase": "P8",
        "risk": "low",
        "objective": (
            "Optimize private self-dev next-action recovery hot path with "
            "before/after evidence while preserving LG9 durable recovery "
            "semantics."
        ),
        "reason": (
            "K173 combined LG8/LG9 contract is complete; K172 baseline shows "
            "self-dev next-action recovery as the slowest private hot path, "
            "and LG9 recovery semantics must stay stable."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`scripts/rh-perf-baseline.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`packages/research_harness/tests/test_rh_perf_baseline.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/rh-performance-baseline-*.md`; "
            "`.rh-selfdev/rh-performance-baseline-*.json`"
        ),
        "tests": (
            "RED/GREEN focused next-action recovery tests; before/after "
            "private baseline evidence; `python3 scripts/rh-selfdev.py "
            "next-action --json`; `python3 scripts/rh-selfdev.py status`; "
            "`git diff --check`"
        ),
        "human_gate": (
            "No gate for private helper optimization if public surface, "
            "payload shape, storage/provenance/orchestrator semantics, "
            "benchmark claims, dependencies, external actions, Zotero, HTTP, "
            "MCP, RH/ARE, commits, pushes, PRs, releases, and publishing remain "
            "unchanged."
        ),
        "stop_rules": (
            "Stop before public surface, storage/provenance, orchestrator, "
            "benchmark promotion, dependency, external-action, credential, "
            "local/private-data, Zotero, HTTP, MCP, RH/ARE, commit, push, PR, "
            "release, or publishing boundaries."
        ),
    }


def _lg8_runtime_event_append_hot_path_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG8_RUNTIME_EVENT_APPEND_TEMPDB_HOT_PATH_SUFFIX,
        ),
        "phase": "P8",
        "risk": "low",
        "objective": (
            "Optimize private runtime event append temp-DB measurement hot path "
            "with before/after evidence while preserving LG9 runtime-event "
            "storage semantics."
        ),
        "reason": (
            "K174 LG8/LG9 self-dev recovery hot path is complete; K172/K174 "
            "baselines show runtime event append temp-DB measurement as the "
            "next runtime-semantics hot path."
        ),
        "allowed_files": (
            "`scripts/rh-perf-baseline.py`; "
            "`packages/research_harness/tests/test_rh_perf_baseline.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/rh-lg8-lg9-combined-execution-plan-2026-06-11.md`; "
            "`.rh-selfdev/rh-performance-baseline-*.md`; "
            "`.rh-selfdev/rh-performance-baseline-*.json`"
        ),
        "tests": (
            "RED/GREEN private perf runner tests; before/after private baseline "
            "evidence; `python3 scripts/rh-selfdev.py next-action --json`; "
            "`python3 scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "No gate for private measurement-runner optimization if storage "
            "schema, storage semantics, provenance ownership, artifact lineage, "
            "orchestrator behavior, public surface, benchmark claims, "
            "dependencies, external actions, Zotero, HTTP, MCP, RH/ARE, commits, "
            "pushes, PRs, releases, and publishing remain unchanged."
        ),
        "stop_rules": (
            "Stop before public surface, storage/provenance, orchestrator, "
            "benchmark promotion, dependency, external-action, credential, "
            "local/private-data, Zotero, HTTP, MCP, RH/ARE, commit, push, PR, "
            "release, or publishing boundaries."
        ),
    }


def _lg8_next_action_command_hot_path_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG8_SELFDEV_NEXT_ACTION_COMMAND_HOT_PATH_SUFFIX,
        ),
        "phase": "P8",
        "risk": "low",
        "objective": (
            "Optimize private self-dev next-action command hot path by "
            "skipping unnecessary risk-flag scans on the LG8/LG9 recovery "
            "branch while preserving durable recovery semantics."
        ),
        "reason": (
            "K175 LG8/LG9 runtime-event append hot path is complete; the "
            "self-dev next-action command still pays command-level risk scan "
            "overhead before reaching the LG8/LG9 private recovery branch."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`scripts/rh-perf-baseline.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`packages/research_harness/tests/test_rh_perf_baseline.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/rh-lg8-lg9-combined-execution-plan-2026-06-11.md`; "
            "`.rh-selfdev/rh-performance-baseline-*.md`; "
            "`.rh-selfdev/rh-performance-baseline-*.json`"
        ),
        "tests": (
            "RED/GREEN focused next-action command fast-path tests; "
            "before/after private baseline evidence; `python3 "
            "scripts/rh-selfdev.py next-action --json`; `python3 "
            "scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "No gate for private self-dev command optimization if public "
            "surface, payload shape, storage/provenance/orchestrator "
            "semantics, benchmark claims, dependencies, external actions, "
            "Zotero, HTTP, MCP, RH/ARE, commits, pushes, PRs, releases, and "
            "publishing remain unchanged."
        ),
        "stop_rules": (
            "Stop before public surface, storage/provenance, orchestrator, "
            "benchmark promotion, dependency, external-action, credential, "
            "local/private-data, Zotero, HTTP, MCP, RH/ARE, commit, push, PR, "
            "release, or publishing boundaries."
        ),
    }


def _lg9_durable_contract_matrix_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG9_DURABLE_CONTRACT_MATRIX_SUFFIX,
        ),
        "phase": "P8",
        "risk": "low",
        "objective": (
            "Create the private LG9 durable contract matrix covering runtime "
            "event, job ledger, tool-boundary, doctor/showcase, provenance "
            "linkage, and orchestrator read-only mapping semantics."
        ),
        "reason": (
            "K176 completed the third evidence-backed LG8 private hot-path "
            "slice; shift to LG9 durable contract coverage before any LG10 "
            "public productization work."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/rh-lg8-lg9-combined-execution-plan-2026-06-11.md`; "
            "`.rh-selfdev/rh-lg9-durable-contract-matrix-2026-06-11.md`"
        ),
        "tests": (
            "RED/GREEN focused LG9 contract matrix tests; `python3 "
            "scripts/rh-selfdev.py lg9-contract-matrix --json`; `python3 "
            "scripts/rh-selfdev.py next-action --json`; `python3 "
            "scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "No gate for a private docs/tests/helper contract matrix. Stop "
            "before public surface, storage/provenance semantics, artifact "
            "lineage, orchestrator gate or rollback behavior, benchmark "
            "claims, dependencies, external actions, Zotero, HTTP, MCP, "
            "RH/ARE, commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before public surface, storage/provenance, orchestrator, "
            "benchmark promotion, dependency, external-action, credential, "
            "local/private-data, Zotero, HTTP, MCP, RH/ARE, commit, push, PR, "
            "release, or publishing boundaries."
        ),
    }


def _lg9_durable_contract_matrix_done_action(
    matrix_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": matrix_slice.slice_id,
        "phase": matrix_slice.phase,
        "risk": matrix_slice.risk,
        "objective": matrix_slice.objective,
        "reason": (
            "LG9 durable contract matrix is complete; select the next private "
            "durable-semantics contract slice explicitly"
        ),
        "human_gate": (
            "Continue only for bounded private LG9 docs/tests/helper contract "
            "slices. Stop before public surface, storage/provenance semantics, "
            "artifact lineage, orchestrator gate or rollback behavior, "
            "benchmark claims, dependencies, external actions, Zotero, HTTP, "
            "MCP, RH/ARE, commit, push, PR, release, or publishing changes."
        ),
    }


def _lg9_provenance_artifact_contract_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG9_PROVENANCE_ARTIFACT_LINKAGE_CONTRACT_SUFFIX,
        ),
        "phase": "P8",
        "risk": "low",
        "objective": (
            "Create the private LG9 provenance/artifact linkage contract "
            "without changing storage, provenance ownership, or artifact "
            "lineage behavior."
        ),
        "reason": (
            "K177 completed the LG9 durable contract matrix and left "
            "provenance/artifact linkage as a docs-only gate-bound contract."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/rh-lg8-lg9-combined-execution-plan-2026-06-11.md`; "
            "`.rh-selfdev/rh-lg9-provenance-artifact-linkage-contract-2026-06-11.md`"
        ),
        "tests": (
            "RED/GREEN focused LG9 provenance/artifact contract tests; "
            "`python3 scripts/rh-selfdev.py "
            "lg9-provenance-artifact-contract --json`; `python3 "
            "scripts/rh-selfdev.py next-action --json`; `python3 "
            "scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "No gate for a private docs/tests/helper provenance/artifact "
            "contract. Stop before public surface, storage/provenance "
            "semantics, artifact lineage, orchestrator behavior, benchmark "
            "claims, dependencies, external actions, Zotero, HTTP, MCP, "
            "RH/ARE, commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before public surface, storage/provenance, artifact lineage, "
            "orchestrator, benchmark promotion, dependency, external-action, "
            "credential, local/private-data, Zotero, HTTP, MCP, RH/ARE, "
            "commit, push, PR, release, or publishing boundaries."
        ),
    }


def _lg9_provenance_artifact_contract_done_action(
    contract_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": contract_slice.slice_id,
        "phase": contract_slice.phase,
        "risk": contract_slice.risk,
        "objective": contract_slice.objective,
        "reason": (
            "LG9 provenance/artifact linkage contract is complete; select the "
            "next private durable-semantics contract slice explicitly"
        ),
        "human_gate": (
            "Continue only for bounded private LG9 docs/tests/helper contract "
            "slices. Stop before public surface, storage/provenance semantics, "
            "artifact lineage, orchestrator gate or rollback behavior, "
            "benchmark claims, dependencies, external actions, Zotero, HTTP, "
            "MCP, RH/ARE, commit, push, PR, release, or publishing changes."
        ),
    }


def _lg9_orchestrator_readonly_contract_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG9_ORCHESTRATOR_READONLY_MAPPING_CONTRACT_SUFFIX,
        ),
        "phase": "P8",
        "risk": "low",
        "objective": (
            "Create the private LG9 orchestrator read-only mapping contract "
            "without changing gate, transition, rollback, or stage behavior."
        ),
        "reason": (
            "K178 completed the provenance/artifact linkage contract; the "
            "remaining docs-only LG9 high-risk domain is orchestrator read-only "
            "mapping."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/rh-lg8-lg9-combined-execution-plan-2026-06-11.md`; "
            "`.rh-selfdev/rh-lg9-orchestrator-readonly-mapping-contract-2026-06-11.md`"
        ),
        "tests": (
            "RED/GREEN focused LG9 orchestrator read-only contract tests; "
            "`python3 scripts/rh-selfdev.py "
            "lg9-orchestrator-readonly-contract --json`; `python3 "
            "scripts/rh-selfdev.py next-action --json`; `python3 "
            "scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "No gate for a private docs/tests/helper orchestrator read-only "
            "contract. Stop before public surface, orchestrator gate, "
            "transition, rollback, or stage behavior changes, "
            "storage/provenance semantics, artifact lineage, benchmark claims, "
            "dependencies, external actions, Zotero, HTTP, MCP, RH/ARE, "
            "commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before public surface, orchestrator behavior, "
            "storage/provenance, artifact lineage, benchmark promotion, "
            "dependency, external-action, credential, local/private-data, "
            "Zotero, HTTP, MCP, RH/ARE, commit, push, PR, release, or "
            "publishing boundaries."
        ),
    }


def _lg9_orchestrator_readonly_contract_done_action(
    contract_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": contract_slice.slice_id,
        "phase": contract_slice.phase,
        "risk": contract_slice.risk,
        "objective": contract_slice.objective,
        "reason": (
            "LG9 orchestrator read-only mapping contract is complete; select "
            "the next private regression-guard or closeout slice explicitly"
        ),
        "human_gate": (
            "Continue only for bounded private LG8/LG9 docs/tests/helper "
            "closeout or regression-guard slices. Stop before public surface, "
            "storage/provenance semantics, artifact lineage, orchestrator gate "
            "or rollback behavior, benchmark claims, dependencies, external "
            "actions, Zotero, HTTP, MCP, RH/ARE, commit, push, PR, release, or "
            "publishing changes."
        ),
    }


def _lg8_lg9_private_closeout_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG8_LG9_PRIVATE_CLOSEOUT_GUARD_SUFFIX,
        ),
        "phase": "P8",
        "risk": "low",
        "objective": (
            "Create the private LG8/LG9 closeout with a regression-guarded "
            "evidence report while keeping LG10 public productization gate-bound."
        ),
        "reason": (
            "K179 completed the orchestrator read-only mapping contract; the "
            "remaining private work is closeout and regression-guard evidence."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/rh-lg8-lg9-combined-execution-plan-2026-06-11.md`; "
            "`.rh-selfdev/rh-lg8-lg9-private-closeout-report-2026-06-11.md`"
        ),
        "tests": (
            "RED/GREEN focused LG8/LG9 closeout tests; `python3 "
            "scripts/rh-selfdev.py lg8-lg9-closeout --json`; `python3 "
            "scripts/rh-selfdev.py next-action --json`; `python3 "
            "scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "No gate for private docs/tests/helper closeout. LG10 remains "
            "gate-bound. Stop before public surface, storage/provenance "
            "semantics, artifact lineage, orchestrator behavior, benchmark "
            "claims, dependencies, external actions, Zotero, HTTP, MCP, "
            "RH/ARE, commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before public surface, storage/provenance, artifact lineage, "
            "orchestrator, benchmark promotion, dependency, external-action, "
            "credential, local/private-data, Zotero, HTTP, MCP, RH/ARE, "
            "commit, push, PR, release, or publishing boundaries."
        ),
    }


def _lg10_public_productization_boundary_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG10_PUBLIC_PRODUCTIZATION_GATE_BOUNDARY_SUFFIX,
        ),
        "phase": "P8",
        "risk": "low",
        "objective": (
            "Define the LG10 public-productization gate and implementation "
            "boundary without exposing public capability."
        ),
        "reason": (
            "K180 completed the private LG8/LG9 closeout; the final bridge "
            "artifact records LG10 boundaries before any public implementation "
            "can be considered."
        ),
        "allowed_files": (
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/rh-lg10-public-productization-boundary-2026-06-11.md`"
        ),
        "tests": (
            "RED/GREEN focused LG10 boundary tests; `python3 "
            "scripts/rh-selfdev.py lg10-productization-boundary --json`; "
            "`python3 scripts/rh-selfdev.py next-action --json`; `python3 "
            "scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "No gate for private boundary documentation. Stop before public "
            "implementation, public surface changes, storage/provenance "
            "semantics, artifact lineage, orchestrator behavior, benchmark "
            "claims, dependencies, external actions, Zotero, HTTP, MCP, "
            "RH/ARE, commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before public implementation, public surface, "
            "storage/provenance, artifact lineage, orchestrator, benchmark "
            "claim, dependency, external-action, credential, local/private-data, "
            "compatibility-name removal, Zotero, HTTP, MCP, RH/ARE, commit, "
            "push, PR, release, or publishing boundaries."
        ),
    }


def _lg8_lg9_private_program_complete_action(
    closeout_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "complete_lg8_lg9_private_program",
        "slice_id": closeout_slice.slice_id,
        "phase": closeout_slice.phase,
        "risk": closeout_slice.risk,
        "objective": closeout_slice.objective,
        "reason": (
            "combined LG8/LG9 private program is complete: three private LG8 "
            "hot-path slices have evidence, LG9 durable contracts are recorded, "
            "and LG10 public productization remains gate-bound"
        ),
        "human_gate": (
            "A fresh gate is required before LG10 public productization, public "
            "performance or benchmark claims, storage/provenance semantics, "
            "artifact lineage, orchestrator behavior, dependencies, external "
            "actions, Zotero, HTTP, MCP, RH/ARE, commit, push, PR, release, or "
            "publishing changes."
        ),
    }


def _lg10_public_productization_boundary_done_action(
    boundary_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": boundary_slice.slice_id,
        "phase": boundary_slice.phase,
        "risk": boundary_slice.risk,
        "objective": boundary_slice.objective,
        "reason": (
            "K181 records the LG10 public-productization boundary; a fresh gate "
            "is required before any LG10 implementation."
        ),
        "human_gate": (
            "Do not create public implementation slices automatically. A fresh "
            "human gate is required before changing CLI, MCP, HTTP, Python "
            "facade, Zotero, doctor, showcase, skills/docs, storage/provenance, "
            "artifact lineage, orchestrator behavior, benchmark claims, "
            "dependencies, external actions, commits, pushes, PRs, releases, or "
            "publishing."
        ),
    }


def _lg10_cli_boundary_preview_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(slices, LG10_CLI_BOUNDARY_PREVIEW_SUFFIX),
        "phase": "P8",
        "risk": "medium",
        "objective": (
            "Expose the LG10 productization boundary through an opt-in CLI "
            "preview while preserving default CLI behavior."
        ),
        "reason": (
            "K182 records direct user authorization for the LG10 boundary-preview "
            "public-surface batch; start with the lowest-blast-radius CLI surface."
        ),
        "allowed_files": (
            "`packages/research_harness/research_harness/cli.py`; "
            "`packages/research_harness/research_harness/_productization/**`; "
            "`packages/research_harness/tests/test_cli_productization_boundary.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/gates/**`"
        ),
        "tests": (
            "RED/GREEN CLI boundary preview tests; focused self-dev recovery "
            "tests; `python3 scripts/rh-selfdev.py next-action --json`; "
            "`python3 scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "Covered by K182. Change exactly one public surface: CLI. The "
            "preview must be opt-in, read-only, shape-locked, compatible by "
            "default, and must not touch MCP, HTTP, Python facade, Zotero, "
            "doctor, showcase, skills/docs, storage/provenance, artifact "
            "lineage, orchestrator behavior, benchmark claims, dependencies, "
            "external actions, commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before any non-CLI public surface, storage/provenance, "
            "artifact lineage, orchestrator, benchmark claim, dependency, "
            "external action, credential/config mutation, local/private-data "
            "exposure, compatibility-name removal, commit, push, PR, release, "
            "or publishing boundary."
        ),
    }


def _lg10_mcp_boundary_preview_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(slices, LG10_MCP_BOUNDARY_PREVIEW_SUFFIX),
        "phase": "P8",
        "risk": "medium",
        "objective": (
            "Expose the LG10 productization boundary through an opt-in MCP "
            "preview while preserving existing MCP tools and payloads."
        ),
        "reason": (
            "K183 completes the opt-in CLI boundary preview; continue the "
            "K182-approved batch with the next single public surface, MCP."
        ),
        "allowed_files": (
            "`packages/research_harness_mcp/**`; "
            "`packages/research_harness/research_harness/_productization/**`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`docs/mcp-tool-audit.md`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/handoffs/**`"
        ),
        "tests": (
            "RED/GREEN MCP boundary preview tests; public-surface guard update; "
            "`python3 scripts/rh-selfdev.py next-action --json`; `python3 "
            "scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "Covered by K182. Change exactly one public surface: MCP. The "
            "preview must be opt-in, read-only, shape-locked, compatible by "
            "default, and must not touch CLI further, HTTP, Python facade, "
            "Zotero, doctor, showcase, skills/docs, storage/provenance, "
            "artifact lineage, orchestrator behavior, benchmark claims, "
            "dependencies, external actions, commits, pushes, PRs, releases, "
            "or publishing."
        ),
        "stop_rules": (
            "Stop before any non-MCP public surface, storage/provenance, "
            "artifact lineage, orchestrator, benchmark claim, dependency, "
            "external action, credential/config mutation, local/private-data "
            "exposure, compatibility-name removal, commit, push, PR, release, "
            "or publishing boundary."
        ),
    }


def _lg10_http_boundary_preview_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(slices, LG10_HTTP_BOUNDARY_PREVIEW_SUFFIX),
        "phase": "P8",
        "risk": "medium",
        "objective": (
            "Expose the LG10 productization boundary through an opt-in HTTP "
            "preview while preserving existing HTTP routes and payloads."
        ),
        "reason": (
            "K185 records direct user continuation for the next single public "
            "surface after the CLI/MCP boundary previews: HTTP."
        ),
        "allowed_files": (
            "`packages/research_harness_mcp/research_harness_mcp/http_api.py`; "
            "`packages/research_harness_mcp/tests/test_productization_http_api.py`; "
            "`packages/research_harness/research_harness/_productization/**`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/gates/**`"
        ),
        "tests": (
            "RED/GREEN HTTP boundary preview tests; focused self-dev recovery "
            "tests; `python3 scripts/rh-selfdev.py next-action --json`; "
            "`python3 scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "Covered by K185. Change exactly one public surface: HTTP. The "
            "preview must be opt-in, read-only, shape-locked, compatible by "
            "default, and must not touch CLI further, MCP further, Python "
            "facade, Zotero, doctor, showcase, skills/docs, "
            "storage/provenance, artifact lineage, orchestrator behavior, "
            "benchmark claims, dependencies, external actions, commits, "
            "pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before any non-HTTP public surface, storage/provenance, "
            "artifact lineage, orchestrator, benchmark claim, dependency, "
            "external action, credential/config mutation, local/private-data "
            "exposure, compatibility-name removal, commit, push, PR, release, "
            "or publishing boundary."
        ),
    }


def _lg10_python_facade_boundary_preview_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_SUFFIX,
        ),
        "phase": "P8",
        "risk": "medium",
        "objective": (
            "Expose the LG10 productization boundary through an opt-in Python "
            "facade preview while preserving existing facade imports and "
            "runtime behavior."
        ),
        "reason": (
            "K187 records direct user continuation for the next single public "
            "surface after the HTTP boundary preview: Python facade."
        ),
        "allowed_files": (
            "`packages/research_harness/research_harness/__init__.py`; "
            "`packages/research_harness/research_harness/_productization/**`; "
            "`packages/research_harness/tests/test_productization_python_facade.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/gates/**`"
        ),
        "tests": (
            "RED/GREEN Python facade boundary preview tests; focused self-dev "
            "recovery tests; `python3 scripts/rh-selfdev.py next-action "
            "--json`; `python3 scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "Covered by K187. Change exactly one public surface: Python "
            "facade. The preview must be opt-in, read-only, shape-locked, "
            "compatible by default, and must not touch CLI further, MCP "
            "further, HTTP further, Zotero, doctor, showcase, skills/docs, "
            "storage/provenance, artifact lineage, orchestrator behavior, "
            "benchmark claims, dependencies, external actions, commits, "
            "pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before any non-Python-facade public surface, "
            "storage/provenance, artifact lineage, orchestrator, benchmark "
            "claim, dependency, external action, credential/config mutation, "
            "local/private-data exposure, compatibility-name removal, commit, "
            "push, PR, release, or publishing boundary."
        ),
    }


def _lg10_skills_docs_boundary_preview_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_SUFFIX,
        ),
        "phase": "P8",
        "risk": "medium",
        "objective": (
            "Expose the LG10 productization boundary through an opt-in "
            "skills/docs preview while preserving skill runtime behavior."
        ),
        "reason": (
            "K189 records direct user continuation for the next single public "
            "surface after the Python facade boundary preview: skills/docs."
        ),
        "allowed_files": (
            "`docs/skills/README.md`; "
            "`packages/research_harness/tests/test_productization_skills_docs.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`scripts/rh-selfdev.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/gates/**`"
        ),
        "tests": (
            "RED/GREEN skills/docs boundary preview tests; focused self-dev "
            "recovery tests; `python3 scripts/rh-selfdev.py next-action "
            "--json`; `python3 scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "Covered by K189. Change exactly one public surface: skills/docs. "
            "The preview must be documentation-only, opt-in by instruction, "
            "shape-locked, compatible by default, and must not touch CLI "
            "further, MCP further, HTTP further, Python facade further, "
            "Zotero, doctor, showcase, storage/provenance, artifact lineage, "
            "orchestrator behavior, benchmark claims, dependencies, external "
            "actions, commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before any non-skills/docs public surface, "
            "storage/provenance, artifact lineage, orchestrator, benchmark "
            "claim, dependency, external action, credential/config mutation, "
            "local/private-data exposure, compatibility-name removal, commit, "
            "push, PR, release, or publishing boundary."
        ),
    }


def _lg10_doctor_boundary_preview_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG10_DOCTOR_BOUNDARY_PREVIEW_SUFFIX,
        ),
        "phase": "P8",
        "risk": "medium",
        "objective": (
            "Expose the LG10 productization boundary through an opt-in doctor "
            "preview while preserving default doctor output."
        ),
        "reason": (
            "K191 records direct user continuation for the next single public "
            "surface after the skills/docs boundary preview: doctor."
        ),
        "allowed_files": (
            "`packages/research_harness/research_harness/cli.py`; "
            "`packages/research_harness/research_harness/_productization/**`; "
            "`packages/research_harness/tests/test_doctor.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`scripts/rh-selfdev.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/gates/**`"
        ),
        "tests": (
            "RED/GREEN doctor boundary preview tests; focused self-dev "
            "recovery tests; `python3 scripts/rh-selfdev.py next-action "
            "--json`; `python3 scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "Covered by K191. Change exactly one public surface: doctor. The "
            "preview must be opt-in, read-only, shape-locked, compatible by "
            "default, and must not touch CLI productization further, MCP "
            "further, HTTP further, Python facade further, skills/docs "
            "further, Zotero, showcase, storage/provenance, artifact lineage, "
            "orchestrator behavior, benchmark claims, dependencies, external "
            "actions, commits, pushes, PRs, releases, or publishing."
        ),
        "stop_rules": (
            "Stop before any non-doctor public surface, storage/provenance, "
            "artifact lineage, orchestrator, benchmark claim, dependency, "
            "external action, credential/config mutation, local/private-data "
            "exposure, compatibility-name removal, commit, push, PR, release, "
            "or publishing boundary."
        ),
    }


def _lg10_showcase_boundary_preview_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(
            slices,
            LG10_SHOWCASE_BOUNDARY_PREVIEW_SUFFIX,
        ),
        "phase": "P8",
        "risk": "medium",
        "objective": (
            "Expose the LG10 productization boundary through an opt-in "
            "showcase bundle preview while preserving default manifest output."
        ),
        "reason": (
            "K193 records direct user continuation for the next single public "
            "surface after the doctor boundary preview: showcase."
        ),
        "allowed_files": (
            "`scripts/build_showcase_bundle.py`; "
            "`packages/research_harness/tests/test_showcase_bundle_script.py`; "
            "`packages/research_harness/research_harness/_productization/**`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`docs/showcase-bundle.md`; "
            "`scripts/rh-selfdev.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/long-goals.md`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/gates/**`"
        ),
        "tests": (
            "RED/GREEN showcase boundary preview tests; focused self-dev "
            "recovery tests; `python3 scripts/rh-selfdev.py next-action "
            "--json`; `python3 scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "Covered by K193. Change exactly one public surface: showcase. The "
            "preview must be opt-in, read-only, local-file only, shape-locked, "
            "compatible by default, and must not touch CLI productization "
            "further, MCP further, HTTP further, Python facade further, "
            "skills/docs further, doctor further, Zotero, storage/provenance, "
            "artifact lineage, orchestrator behavior, benchmark claims, "
            "dependencies, external actions, commits, pushes, PRs, releases, "
            "or publishing."
        ),
        "stop_rules": (
            "Stop before any non-showcase public surface, storage/provenance, "
            "artifact lineage, orchestrator, benchmark claim, dependency, "
            "external action, credential/config mutation, local/private-data "
            "exposure, compatibility-name removal, commit, push, PR, release, "
            "or publishing boundary."
        ),
    }


def _post_lg10_mainline_closeout_template() -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": POST_LG10_MAINLINE_ACCEPTANCE_CLOSEOUT_SUFFIX,
        "phase": "P8",
        "risk": "medium",
        "objective": (
            "Close out the post-LG10 mainline acceptance evidence and mark "
            "LG8/LG9/LG10 optimization complete."
        ),
        "reason": (
            "K194 completed the final authorized LG10 public-surface preview; "
            "create a docs/tests/helper closeout slice before ending the "
            "current mainline."
        ),
        "allowed_files": (
            "`.rh-selfdev/*`; "
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`"
        ),
        "tests": (
            "RED/GREEN mainline closeout tests; `python3 "
            "scripts/rh-selfdev.py next-action --json`; `python3 "
            "scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            "No gate for docs/tests/helper closeout that changes no public RH "
            "CLI/MCP/HTTP/Python/Zotero behavior. Stop before new public "
            "surface, benchmark/public performance claims, release/publish, "
            "storage/provenance/orchestrator semantics, dependencies, external "
            "actions, commits, pushes, PRs, or RH/ARE boundary changes."
        ),
    }


def _mainline_optimization_complete_action(
    closeout_slice: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "complete_mainline_optimization",
        "slice_id": closeout_slice.slice_id,
        "phase": closeout_slice.phase,
        "risk": closeout_slice.risk,
        "objective": closeout_slice.objective,
        "reason": (
            "LG8/LG9/LG10 mainline optimization is complete: LG8/LG9 private "
            "evidence is closed out, LG10 public previews are accepted, and "
            "the post-LG10 closeout report records deferred boundaries."
        ),
        "human_gate": (
            "Open a fresh human gate before any new mainline, Zotero work, "
            "benchmark/public performance claim, release/publish action, "
            "storage/provenance/orchestrator semantic change, dependency "
            "change, external action, commit, push, PR, or RH/ARE boundary "
            "change."
        ),
    }


def _non_benchmark_stabilization_templates() -> tuple[dict[str, str], ...]:
    shared_allowed_files = (
        "`.rh-selfdev/slices.md`; "
        "`.rh-selfdev/long-goals.md`; "
        "`.rh-selfdev/checkpoint.md`; "
        "`.rh-selfdev/handoffs/**`; "
        "`.rh-selfdev/gates/**`; "
        "`scripts/rh-selfdev.py`; "
        "`packages/research_harness/tests/test_rh_selfdev_script.py`"
    )
    shared_tests = (
        "focused stabilization tests; `python3 scripts/rh-selfdev.py "
        "next-action --json`; `python3 scripts/rh-selfdev.py status`; "
        "`git diff --check`"
    )
    shared_gate = (
        "Covered by direct user authorization for local non-benchmark "
        "stabilization only. Stop before benchmark/public performance claims, "
        "public internet deployment, external actions, dependency changes, "
        "storage/provenance/orchestrator semantic changes, commits, pushes, "
        "PRs, releases, or publishing."
    )
    return (
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[0],
            "phase": "P11",
            "risk": "medium",
            "objective": (
                "Stabilize the Topic Knowledge stable local/internal boundary "
                "as a durable RH capability without expanding public internet "
                "deployment, storage schema, paper identity, Zotero, "
                "orchestrator, dependency, benchmark, release, or RH/ARE scope."
            ),
            "reason": (
                "post-LG10 mainline closeout is complete; the user authorized "
                "non-benchmark stabilization with benchmark/public performance "
                "claims excluded."
            ),
            "allowed_files": (
                shared_allowed_files
                + "; `.rh-selfdev/rh-topic-knowledge-layer-v1-spec.md`; "
                "`docs/mcp-tool-audit.md`; `docs/service-layer-plan.md`"
            ),
            "tests": shared_tests,
            "human_gate": shared_gate,
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[1],
            "phase": "P11",
            "risk": "medium",
            "objective": (
                "Convert Topic Knowledge HTTP controlled beta wording and "
                "guards into a stable local/internal HTTP bridge boundary "
                "without approving stable external API release."
            ),
            "reason": (
                f"{NON_BENCHMARK_STABILIZATION_SLICE_IDS[0]} is complete; "
                "the remaining Topic Knowledge HTTP controlled beta boundary "
                "needs a local/internal stabilization decision."
            ),
            "allowed_files": (
                shared_allowed_files + "; `docs/knowledge-http-api.md`; "
                "`packages/research_harness_mcp/tests/test_knowledge_http_api.py`"
            ),
            "tests": (
                "focused Topic Knowledge HTTP docs/guard tests; "
                "`python3 scripts/rh-selfdev.py next-action --json`; "
                "`python3 scripts/rh-selfdev.py status`; `git diff --check`"
            ),
            "human_gate": shared_gate,
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[2],
            "phase": "P11",
            "risk": "medium",
            "objective": (
                "Harden LG10 boundary previews into durable opt-in "
                "productization boundary components while preserving names, "
                "payload shapes, default compatibility, and release exclusions."
            ),
            "reason": (
                f"{NON_BENCHMARK_STABILIZATION_SLICE_IDS[1]} is complete; "
                "LG10 boundary previews need a stable/deferred decision per "
                "surface."
            ),
            "allowed_files": (
                shared_allowed_files
                + "; `packages/research_harness/research_harness/_productization/**`"
            ),
            "tests": shared_tests,
            "human_gate": shared_gate,
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[3],
            "phase": "P11",
            "risk": "medium",
            "objective": (
                "Stabilize survey-first retrieval as a formal internal "
                "retrieval policy component with flags, guardrails, and "
                "regression tests for under-filled topics, normal topics, "
                "auto_ingest safety, and no-survey fallback."
            ),
            "reason": (
                f"{NON_BENCHMARK_STABILIZATION_SLICE_IDS[2]} is complete; "
                "survey-first retrieval must move from recent optimization to "
                "formal internal policy."
            ),
            "allowed_files": (
                "`packages/research_harness/research_harness/primitives/**`; "
                "`packages/research_harness/tests/test_primitives.py`; "
                "`packages/research_harness/tests/test_service_layer.py`; "
                + shared_allowed_files
            ),
            "tests": (
                "focused survey-first primitive/service tests; "
                "`python3 scripts/rh-selfdev.py next-action --json`; "
                "`python3 scripts/rh-selfdev.py status`; `git diff --check`"
            ),
            "human_gate": shared_gate,
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[4],
            "phase": "P11",
            "risk": "high",
            "objective": (
                "Productize LG9 contract-only semantics into executable "
                "internal guards/read-model checks without schema, provenance, "
                "artifact-lineage, or orchestrator semantic migrations."
            ),
            "reason": (
                f"{NON_BENCHMARK_STABILIZATION_SLICE_IDS[3]} is complete; "
                "LG9 contract-only items need executable internal guard "
                "coverage or explicit deferral."
            ),
            "allowed_files": (
                "`scripts/rh-selfdev.py`; `packages/research_harness/tests/**`; "
                "`.rh-selfdev/rh-lg9-*.md`; " + shared_allowed_files
            ),
            "tests": (
                "focused LG9 internal guard/read-model tests; "
                "`python3 scripts/rh-selfdev.py next-action --json`; "
                "`python3 scripts/rh-selfdev.py status`; `git diff --check`"
            ),
            "human_gate": (
                "Write a gate artifact before implementation. The current user "
                "authorization covers internal guard/read-model checks only; "
                "stop before schema, provenance ownership, artifact-lineage, "
                "or orchestrator gate/rollback semantic changes."
            ),
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[5],
            "phase": "P11",
            "risk": "high",
            "objective": (
                "Stabilize Zotero service routing as dry-run and validation "
                "paths only, with real Zotero sync/UI/apply behavior deferred."
            ),
            "reason": (
                f"{NON_BENCHMARK_STABILIZATION_SLICE_IDS[4]} is complete; "
                "Zotero service routing must be classified as stable dry-run/"
                "validation or explicitly deferred."
            ),
            "allowed_files": (
                "`packages/research_harness/research_harness/service/**`; "
                "`packages/research_harness_mcp/research_harness_mcp/tools.py`; "
                "`packages/research_harness/tests/**`; "
                "`packages/research_harness_mcp/research_harness_mcp/tests/test_tools.py`; "
                + shared_allowed_files
            ),
            "tests": (
                "focused Zotero dry-run/validation tests with no real Zotero "
                "calls; `python3 scripts/rh-selfdev.py next-action --json`; "
                "`python3 scripts/rh-selfdev.py status`; `git diff --check`"
            ),
            "human_gate": (
                "Write a gate artifact before implementation. The current user "
                "authorization covers dry-run/validation stabilization only; "
                "real Zotero sync, UI apply paths, external calls, credentials, "
                "or public deployment remain excluded."
            ),
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[6],
            "phase": "P11",
            "risk": "low",
            "objective": (
                "Stabilize runtime-shell and self-dev automation helpers as "
                "internal maintenance tooling with deterministic docs, guards, "
                "and verification commands."
            ),
            "reason": (
                f"{NON_BENCHMARK_STABILIZATION_SLICE_IDS[5]} is complete; "
                "runtime-shell/self-dev helper optimizations need a stable "
                "internal component decision."
            ),
            "allowed_files": shared_allowed_files
            + "; `.rh-selfdev/rh-runtime-shell-*.md`",
            "tests": shared_tests,
            "human_gate": shared_gate,
        },
        {
            "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[7],
            "phase": "P11",
            "risk": "low",
            "objective": (
                "Close out LG11 non-benchmark stabilization by classifying "
                "each item as stable component, stable internal/private "
                "component, or explicitly deferred with reason."
            ),
            "reason": (
                f"{NON_BENCHMARK_STABILIZATION_SLICE_IDS[6]} is complete; "
                "only the non-benchmark stabilization closeout remains."
            ),
            "allowed_files": shared_allowed_files
            + "; `.rh-selfdev/rh-non-benchmark-stabilization-closeout-2026-06-11.md`",
            "tests": (
                "`python3 scripts/check-service-coverage.py`; "
                "`scripts/codex-check.sh --quick`; "
                "`python3 scripts/rh-selfdev.py next-action --json`; "
                "`python3 scripts/rh-selfdev.py status`; `git diff --check`"
            ),
            "human_gate": shared_gate,
        },
    )


def _non_benchmark_stabilization_next_action(
    slices: list[SelfDevSlice],
    closeout_slice: SelfDevSlice,
) -> dict[str, str]:
    completed: set[str] = {
        slice_def.slice_id
        for slice_def in slices
        if slice_def.status == "done"
        and slice_def.slice_id in NON_BENCHMARK_STABILIZATION_SLICE_IDS
    }
    for template in _non_benchmark_stabilization_templates():
        if template["slice_id"] not in completed:
            return {"action": "create_slice", **template}

    return _local_autonomy_goal1_next_action(slices, closeout_slice)


def _local_autonomy_goal1_next_action(
    slices: list[SelfDevSlice],
    closeout_slice: SelfDevSlice,
) -> dict[str, str]:
    goal1_slice = next(
        (
            slice_def
            for slice_def in slices
            if slice_def.slice_id == LOCAL_AUTONOMY_GOAL1_SLICE_ID
        ),
        None,
    )
    if goal1_slice is None:
        return {
            "action": "create_slice",
            "slice_id": LOCAL_AUTONOMY_GOAL1_SLICE_ID,
            "phase": "P12",
            "risk": "high",
            "objective": (
                "Record the 2026-06-12 local autonomy preapproval policy, "
                "normalize stale gate wording, and make RH self-dev recovery "
                "stop only at large-goal completion or non-local external "
                "action boundaries."
            ),
            "reason": (
                "LG11 is complete and the user approved all future local gates "
                "as a four-goal autonomy program; the control plane and "
                "next-action recovery need to encode that policy before "
                "durable semantics, productization/Zotero, or benchmark work."
            ),
            "allowed_files": (
                "`.rh-selfdev/control-plane.md`; "
                "`.rh-selfdev/long-goals.md`; "
                "`.rh-selfdev/slices.md`; "
                "`.rh-selfdev/checkpoint.md`; "
                "`.rh-selfdev/gates/**`; "
                "`.rh-selfdev/handoffs/**`; "
                "`.rh-selfdev/rh-review-package-*.md`; "
                "`scripts/rh-selfdev.py`; "
                "`packages/research_harness/tests/test_rh_selfdev_script.py`"
            ),
            "tests": (
                ".venv/bin/python -m pytest "
                "packages/research_harness/tests/test_rh_selfdev_script.py "
                "-q -k 'local_autonomy or st08_completes'; "
                "python3 scripts/rh-selfdev.py next-action --json; "
                "python3 scripts/rh-selfdev.py status; git diff --check"
            ),
            "human_gate": (
                "Pre-approved by the user's 2026-06-12 local autonomy "
                "authorization. Continue locally through gate artifacts and "
                "handoffs; stop only before commit, push, PR, release, "
                "publishing, real Cloud submission, Cloud diff apply, real "
                "Zotero network sync/apply, credential/config mutation, or "
                "third-party resource writes."
            ),
            "stop_rules": (
                "Stop at large-goal completion, repeated focused-test failure, "
                "unavailable local evidence, context checkpoint boundaries, "
                "or any non-local/external action."
            ),
            "prior_closeout_slice": closeout_slice.slice_id,
        }

    if goal1_slice.status == "done":
        return _local_autonomy_goal2_next_action(slices, goal1_slice)

    return {
        "action": "complete_non_benchmark_stabilization",
        "slice_id": NON_BENCHMARK_STABILIZATION_SLICE_IDS[-1],
        "phase": "P11",
        "risk": "low",
        "objective": (
            "LG11 non-benchmark stabilization is complete for the authorized "
            "local/internal scope."
        ),
        "reason": (
            "all non-benchmark stabilization slices are classified as stable "
            "component, stable internal/private component, or explicitly "
            "deferred with reason; benchmark/public performance claims remain "
            "excluded."
        ),
        "human_gate": (
            "No further local LG11 implementation slice remains. A fresh gate "
            "is required before benchmark work, public performance claims, "
            "external release actions, dependency changes, storage/provenance/"
            "orchestrator semantic changes, real Zotero sync/UI, commits, "
            "pushes, PRs, releases, or publishing."
        ),
        "mainline_closeout_slice": closeout_slice.slice_id,
    }


def _local_autonomy_goal2_next_action(
    slices: list[SelfDevSlice],
    goal1_slice: SelfDevSlice,
) -> dict[str, str]:
    goal2_slice = next(
        (
            slice_def
            for slice_def in slices
            if slice_def.slice_id == LOCAL_AUTONOMY_GOAL2_SLICE_ID
        ),
        None,
    )
    if goal2_slice is None:
        return {
            "action": "create_slice",
            "slice_id": LOCAL_AUTONOMY_GOAL2_SLICE_ID,
            "phase": "P12",
            "risk": "high",
            "objective": (
                "Implement executable local durable semantics guards for LG9 "
                "runtime events, artifact/provenance lineage read models, and "
                "orchestrator read-only mappings without schema migrations or "
                "behavior changes."
            ),
            "reason": (
                "Goal 1 is complete and the user authorized continuing local "
                "gate classes; the next large goal converts contract-only LG9 "
                "semantics into read-only executable diagnostics."
            ),
            "allowed_files": (
                "`packages/research_harness/research_harness/runtime/**`; "
                "`packages/research_harness/tests/test_durable_semantics.py`; "
                "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
                "`scripts/rh-selfdev.py`; "
                "`.rh-selfdev/slices.md`; "
                "`.rh-selfdev/checkpoint.md`; "
                "`.rh-selfdev/gates/**`; "
                "`.rh-selfdev/handoffs/**`; "
                "`.rh-selfdev/rh-lg9-*.md`"
            ),
            "tests": (
                ".venv/bin/python -m pytest "
                "packages/research_harness/tests/test_durable_semantics.py "
                "packages/research_harness/tests/test_rh_selfdev_script.py "
                "-q -k 'durable_semantics or lg9_contract_guard_productization'; "
                "python3 scripts/rh-selfdev.py durable-semantics --json; "
                "python3 scripts/rh-selfdev.py next-action --json; "
                "python3 scripts/rh-selfdev.py status; git diff --check"
            ),
            "human_gate": (
                "Pre-approved for local execution by the user's 2026-06-12 "
                "authorization. No storage schema migration, provenance "
                "ownership change, artifact-lineage behavior change, "
                "orchestrator behavior change, public surface change, "
                "benchmark/public performance claim, dependency change, "
                "external action, credential/config mutation, commit, push, "
                "PR, release, or publishing is included."
            ),
            "prior_goal_slice": goal1_slice.slice_id,
        }

    if goal2_slice.status == "done":
        return _local_autonomy_goal3_next_action(slices, goal2_slice)

    return {
        "action": "complete_local_autonomy_goal_1",
        "slice_id": goal1_slice.slice_id,
        "phase": goal1_slice.phase,
        "risk": goal1_slice.risk,
        "objective": goal1_slice.objective,
        "reason": (
            "Goal 1 is complete: RH self-development control-plane, "
            "long-goal policy, slice queue, gate record, handoff, and "
            "checkpoint encode the 2026-06-12 pre-approved local autonomy "
            "program."
        ),
        "human_gate": (
            "Goal 2 durable semantics local implementation is present but not "
            "complete; resume or finish that slice before moving on."
        ),
    }


def _local_autonomy_goal3_next_action(
    slices: list[SelfDevSlice],
    goal2_slice: SelfDevSlice,
) -> dict[str, str]:
    goal3_slice = next(
        (
            slice_def
            for slice_def in slices
            if slice_def.slice_id == LOCAL_AUTONOMY_GOAL3_SLICE_ID
        ),
        None,
    )
    if goal3_slice is None:
        return {
            "action": "create_slice",
            "slice_id": LOCAL_AUTONOMY_GOAL3_SLICE_ID,
            "phase": "P12",
            "risk": "high",
            "objective": (
                "Stabilize productization/Zotero local productization by "
                "classifying LG10 boundary components and Zotero push dry-run "
                "validation as stable local components while keeping real "
                "Zotero sync/UI/apply deferred."
            ),
            "reason": (
                "Goal 2 is complete and the next local-autonomy goal is the "
                "productization/Zotero local productization boundary."
            ),
            "allowed_files": (
                "`packages/research_harness/research_harness/_productization/**`; "
                "`packages/research_harness/research_harness/service/**`; "
                "`packages/research_harness_mcp/research_harness_mcp/**`; "
                "`packages/research_harness/tests/test_productization_boundary_components.py`; "
                "`packages/research_harness/tests/test_service_layer.py`; "
                "`packages/research_harness_mcp/research_harness_mcp/tests/test_tools.py`; "
                "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
                "`scripts/rh-selfdev.py`; "
                "`.rh-selfdev/slices.md`; "
                "`.rh-selfdev/checkpoint.md`; "
                "`.rh-selfdev/gates/**`; "
                "`.rh-selfdev/handoffs/**`"
            ),
            "tests": (
                ".venv/bin/python -m pytest "
                "packages/research_harness/tests/test_productization_boundary_components.py "
                "packages/research_harness/tests/test_service_layer.py "
                "packages/research_harness_mcp/research_harness_mcp/tests/test_tools.py "
                "packages/research_harness/tests/test_rh_selfdev_script.py "
                "-q -k 'productization_zotero_local or zotero_sync or local_autonomy_goal3'; "
                "python3 scripts/rh-selfdev.py productization-zotero-local --json; "
                "python3 scripts/rh-selfdev.py next-action --json; "
                "python3 scripts/rh-selfdev.py status; git diff --check"
            ),
            "human_gate": (
                "Pre-approved for local execution by the user's 2026-06-12 "
                "authorization. Real Zotero network sync/apply, Zotero UI "
                "release, public release claims, benchmark/public performance "
                "claims, external actions, credential/config mutation, commit, "
                "push, PR, release, and publishing remain excluded."
            ),
            "prior_goal_slice": goal2_slice.slice_id,
        }

    if goal3_slice.status == "done":
        return _local_autonomy_goal4_next_action(slices, goal3_slice)

    return {
        "action": "complete_local_autonomy_goal_2",
        "slice_id": goal2_slice.slice_id,
        "phase": goal2_slice.phase,
        "risk": goal2_slice.risk,
        "objective": goal2_slice.objective,
        "reason": (
            "Goal 2 is complete: durable LG9 semantics are represented by "
            "stable local executable schema/read-model diagnostics without "
            "storage/provenance/orchestrator behavior changes."
        ),
        "human_gate": (
            "Goal 3 productization/Zotero local productization is present but "
            "not complete; resume or finish that slice before moving on."
        ),
    }


def _local_autonomy_goal4_next_action(
    slices: list[SelfDevSlice],
    goal3_slice: SelfDevSlice,
) -> dict[str, str]:
    goal4_slice = next(
        (
            slice_def
            for slice_def in slices
            if slice_def.slice_id == LOCAL_AUTONOMY_GOAL4_SLICE_ID
        ),
        None,
    )
    if goal4_slice is None:
        return {
            "action": "create_slice",
            "slice_id": LOCAL_AUTONOMY_GOAL4_SLICE_ID,
            "phase": "P12",
            "risk": "high",
            "objective": (
                "Stabilize private benchmark/performance governance by "
                "classifying existing LG8 private performance baseline "
                "reports and LG8/LG9 closeout evidence as private-only "
                "regression governance without public benchmark or public "
                "performance claims."
            ),
            "reason": (
                "Goal 3 is complete and the final local-autonomy goal is "
                "private benchmark/performance governance; this records the "
                "private measurement path while keeping public claims, scorer "
                "semantics, leaderboard/ranking, RH/ARE boundary moves, and "
                "external submissions deferred."
            ),
            "allowed_files": (
                "`scripts/rh-selfdev.py`; "
                "`scripts/rh-perf-baseline.py`; "
                "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
                "`packages/research_harness/tests/test_rh_perf_baseline.py`; "
                "`.rh-selfdev/rh-lg8-lg9-private-closeout-report-2026-06-11.md`; "
                "`.rh-selfdev/rh-performance-baseline-*.json`; "
                "`.rh-selfdev/rh-performance-baseline-*.md`; "
                "`.rh-selfdev/slices.md`; "
                "`.rh-selfdev/long-goals.md`; "
                "`.rh-selfdev/checkpoint.md`; "
                "`.rh-selfdev/gates/**`; "
                "`.rh-selfdev/handoffs/**`"
            ),
            "tests": (
                ".venv/bin/python -m pytest "
                "packages/research_harness/tests/test_rh_selfdev_script.py "
                "packages/research_harness/tests/test_rh_perf_baseline.py "
                "-q -k 'private_performance_governance or "
                "local_autonomy_goal4 or default_plan'; "
                "python3 scripts/rh-selfdev.py private-performance-governance --json; "
                "python3 scripts/rh-selfdev.py next-action --json; "
                "python3 scripts/rh-selfdev.py status; git diff --check"
            ),
            "human_gate": (
                "Pre-approved for local execution by the user's 2026-06-12 "
                "authorization. This does not approve public benchmark "
                "claims, public performance claims, leaderboard/ranking moves, "
                "scorer semantic changes, RH/ARE boundary moves, external "
                "submissions, releases, publishing, real Cloud actions, "
                "credential/config mutation, commit, push, or PR."
            ),
            "prior_goal_slice": goal3_slice.slice_id,
        }

    if goal4_slice.status == "done":
        return {
            "action": "complete_local_autonomy_goal_4",
            "slice_id": goal4_slice.slice_id,
            "phase": goal4_slice.phase,
            "risk": goal4_slice.risk,
            "objective": goal4_slice.objective,
            "reason": (
                "Goal 4 is complete: private benchmark/performance governance "
                "is stable for local regression use with existing private "
                "baseline reports and LG8/LG9 closeout evidence, while public "
                "benchmark/performance claims, scorer semantics changes, "
                "leaderboard/ranking, RH/ARE boundary moves, external "
                "submissions, releases, and publishing remain deferred."
            ),
            "human_gate": (
                "LG12 local-autonomy implementation is complete. Proceed to "
                "final verification, then the separately authorized unified "
                "commit, push, and PR external-action boundary."
            ),
        }

    return {
        "action": "complete_local_autonomy_goal_3",
        "slice_id": goal3_slice.slice_id,
        "phase": goal3_slice.phase,
        "risk": goal3_slice.risk,
        "objective": goal3_slice.objective,
        "reason": (
            "Goal 3 is complete: productization boundary components and "
            "Zotero push dry-run validation are stable local components, "
            "while real Zotero sync/UI/apply remains deferred."
        ),
        "human_gate": (
            "Goal 4 private benchmark/performance governance is present but "
            "not complete; resume or finish that slice before final "
            "verification or external actions."
        ),
    }


def _lg10_boundary_preview_next_action(
    slices: list[SelfDevSlice],
    boundary_slice: SelfDevSlice,
) -> dict[str, str]:
    batch_gate_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_BOUNDARY_PREVIEW_PUBLIC_SURFACE_BATCH_GATE_SUFFIX,
    )
    if batch_gate_slice is None:
        return _lg10_public_productization_boundary_done_action(boundary_slice)

    cli_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_CLI_BOUNDARY_PREVIEW_SUFFIX,
    )
    if cli_slice is None:
        return _lg10_cli_boundary_preview_template(slices)

    mcp_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_MCP_BOUNDARY_PREVIEW_SUFFIX,
    )
    if mcp_slice is None:
        return _lg10_mcp_boundary_preview_template(slices)

    http_gate_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_HTTP_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE_SUFFIX,
    )
    if http_gate_slice is None:
        return _lg10_public_productization_boundary_done_action(mcp_slice)

    http_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_HTTP_BOUNDARY_PREVIEW_SUFFIX,
    )
    if http_slice is None:
        return _lg10_http_boundary_preview_template(slices)

    python_facade_gate_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE_SUFFIX,
    )
    if python_facade_gate_slice is None:
        return _lg10_public_productization_boundary_done_action(http_slice)

    python_facade_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_PYTHON_FACADE_BOUNDARY_PREVIEW_SUFFIX,
    )
    if python_facade_slice is None:
        return _lg10_python_facade_boundary_preview_template(slices)

    skills_docs_gate_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE_SUFFIX,
    )
    if skills_docs_gate_slice is None:
        return _lg10_public_productization_boundary_done_action(python_facade_slice)

    skills_docs_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_SKILLS_DOCS_BOUNDARY_PREVIEW_SUFFIX,
    )
    if skills_docs_slice is None:
        return _lg10_skills_docs_boundary_preview_template(slices)

    doctor_gate_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_DOCTOR_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE_SUFFIX,
    )
    if doctor_gate_slice is None:
        return _lg10_public_productization_boundary_done_action(skills_docs_slice)

    doctor_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_DOCTOR_BOUNDARY_PREVIEW_SUFFIX,
    )
    if doctor_slice is None:
        return _lg10_doctor_boundary_preview_template(slices)

    showcase_gate_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_SHOWCASE_BOUNDARY_PREVIEW_PUBLIC_SURFACE_GATE_SUFFIX,
    )
    if showcase_gate_slice is None:
        return _lg10_public_productization_boundary_done_action(doctor_slice)

    showcase_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_SHOWCASE_BOUNDARY_PREVIEW_SUFFIX,
    )
    if showcase_slice is None:
        return _lg10_showcase_boundary_preview_template(slices)

    closeout_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        POST_LG10_MAINLINE_ACCEPTANCE_CLOSEOUT_SUFFIX,
    )
    if closeout_slice is None:
        return _post_lg10_mainline_closeout_template()

    return _non_benchmark_stabilization_next_action(slices, closeout_slice)


def _lg8_first_hot_path_done_action(hot_path_slice: SelfDevSlice) -> dict[str, str]:
    return {
        "action": "wait_for_gate",
        "slice_id": hot_path_slice.slice_id,
        "phase": hot_path_slice.phase,
        "risk": hot_path_slice.risk,
        "objective": hot_path_slice.objective,
        "reason": (
            "current LG8/LG9 hot-path slice is complete; select the next "
            "evidence-backed private optimization or durable-semantics "
            "contract slice explicitly"
        ),
        "human_gate": (
            "Continue only for bounded private LG8/LG9 slices with before/after "
            "evidence and stable semantics. Stop before benchmark promotion "
            "claims, public surface, storage/provenance, orchestrator, "
            "dependency, external, Zotero, HTTP, MCP, RH/ARE, commit, push, PR, "
            "release, or publishing changes."
        ),
    }


def _lg8_performance_governance_next_action(
    slices: list[SelfDevSlice],
) -> Optional[dict[str, str]]:
    activation_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG8_LG10_LONG_GOAL_ACTIVATION_SUFFIX,
    )
    if activation_slice is None:
        return None

    baseline_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG8_PRIVATE_PERFORMANCE_BASELINE_SUFFIX,
    )
    if baseline_slice is None:
        return _lg8_private_performance_baseline_template(slices)

    combined_contract_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG8_LG9_COMBINED_EXECUTION_CONTRACT_SUFFIX,
    )
    if combined_contract_slice is None:
        return _lg8_lg9_combined_execution_contract_template(slices)

    first_hot_path_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG8_SELFDEV_NEXT_ACTION_RECOVERY_HOT_PATH_SUFFIX,
    )
    if first_hot_path_slice is None:
        return _lg8_selfdev_next_action_hot_path_template(slices)

    runtime_event_append_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG8_RUNTIME_EVENT_APPEND_TEMPDB_HOT_PATH_SUFFIX,
    )
    if runtime_event_append_slice is None:
        return _lg8_runtime_event_append_hot_path_template(slices)

    next_action_command_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG8_SELFDEV_NEXT_ACTION_COMMAND_HOT_PATH_SUFFIX,
    )
    if next_action_command_slice is None:
        return _lg8_next_action_command_hot_path_template(slices)

    lg9_contract_matrix_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG9_DURABLE_CONTRACT_MATRIX_SUFFIX,
    )
    if lg9_contract_matrix_slice is None:
        return _lg9_durable_contract_matrix_template(slices)

    provenance_artifact_contract_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG9_PROVENANCE_ARTIFACT_LINKAGE_CONTRACT_SUFFIX,
    )
    if provenance_artifact_contract_slice is None:
        return _lg9_provenance_artifact_contract_template(slices)

    orchestrator_readonly_contract_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG9_ORCHESTRATOR_READONLY_MAPPING_CONTRACT_SUFFIX,
    )
    if orchestrator_readonly_contract_slice is None:
        return _lg9_orchestrator_readonly_contract_template(slices)

    private_closeout_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG8_LG9_PRIVATE_CLOSEOUT_GUARD_SUFFIX,
    )
    if private_closeout_slice is None:
        return _lg8_lg9_private_closeout_template(slices)

    lg10_boundary_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        LG10_PUBLIC_PRODUCTIZATION_GATE_BOUNDARY_SUFFIX,
    )
    if lg10_boundary_slice is None:
        return _lg10_public_productization_boundary_template(slices)
    return _lg10_boundary_preview_next_action(slices, lg10_boundary_slice)


def _lg8_no_todo_next_action_fast_path(
    slices: list[SelfDevSlice],
    *,
    ignored_active_slice_ids: set[str],
) -> Optional[dict[str, str]]:
    dispatch_slices = [
        slice_def
        for slice_def in slices
        if not (
            slice_def.slice_id in ignored_active_slice_ids
            and slice_def.status in {"gate", "in_progress"}
        )
    ]
    if select_pending_gate(dispatch_slices) is not None:
        return None
    if select_active_slice(dispatch_slices) is not None:
        return None
    try:
        select_next_slice(dispatch_slices)
    except ValueError:
        phase_b_action = _phase_b_next_action(slices)
        if phase_b_action is not None:
            return phase_b_action
        lg16_done = _lg16_existing_system_finalization_done(slices)
        if lg16_done is not None:
            return _lg16_existing_system_finalization_complete_action(lg16_done)
        return _lg8_performance_governance_next_action(slices)
    return None


def _runtime_event_store_post_closeout_review_next_action(
    slices: list[SelfDevSlice],
) -> Optional[dict[str, str]]:
    gate_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        RUNTIME_EVENT_STORE_POST_CLOSEOUT_REVIEW_GATE_SUFFIX,
    )
    if gate_slice is None:
        return None

    review_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        RUNTIME_EVENT_STORE_POST_CLOSEOUT_REVIEW_PACKAGE_SUFFIX,
    )
    if review_slice is not None:
        broad_autonomy_action = _runtime_event_store_broad_autonomy_next_action(slices)
        if broad_autonomy_action is not None:
            return broad_autonomy_action
        return _runtime_event_store_post_closeout_review_done_action(review_slice)

    return _runtime_event_store_post_closeout_review_template(slices)


def _runtime_event_store_selfdev_extended_batch_next_action(
    *,
    slices: list[SelfDevSlice],
    completion_slice: SelfDevSlice,
    window_size: int,
    failed_test_attempts: int,
    risk_flags: Optional[dict[str, bool]],
) -> Optional[dict[str, str]]:
    extended_gate_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        RUNTIME_EVENT_STORE_SELFDEV_EXTENDED_BATCH_SOURCE_GATE_SUFFIX,
    )
    if extended_gate_slice is None or extended_gate_slice.status != "done":
        return None

    completed_slices = _selfdev_extended_batch_completed_slices(slices)
    reference_slice = completed_slices[-1] if completed_slices else completion_slice
    if failed_test_attempts >= 2:
        return _selfdev_batch_wait_action(
            reference_slice=reference_slice,
            reason=(
                "extended batch focused tests failed twice; stop before "
                "continuing the approved window"
            ),
            human_gate=(
                "A fresh gate is required before continuing the extended batch "
                "after repeated focused test failure."
            ),
        )

    risky_flags = [
        key for key in RISK_KEYS if risk_flags is not None and risk_flags.get(key)
    ]
    if risky_flags:
        return _selfdev_batch_wait_action(
            reference_slice=reference_slice,
            reason=(
                "extended batch risk flags do not match the approved window: "
                f"{', '.join(risky_flags)}"
            ),
            human_gate=(
                "A fresh gate is required before continuing with public, "
                "storage/provenance, orchestrator, benchmark, dependency, or "
                "other higher-risk changes."
            ),
        )

    if len(completed_slices) >= window_size:
        post_closeout_action = _runtime_event_store_post_closeout_review_next_action(
            slices
        )
        if post_closeout_action is not None:
            return post_closeout_action
        return _selfdev_batch_wait_action(
            reference_slice=reference_slice,
            reason=(
                "extended batch window is exhausted after "
                f"{len(completed_slices)} allowlisted slices"
            ),
            human_gate=(
                "Report the extended batch result and request a fresh gate "
                "before routing additional live sources or changing runtime "
                "event storage semantics."
            ),
        )

    for candidate in _selfdev_extended_batch_candidates():
        if _selfdev_batch_source_is_done(slices, candidate["suffix"]):
            continue
        return _selfdev_extended_batch_source_template(
            slices=slices,
            candidate=candidate,
            completed_count=len(completed_slices),
            window_size=window_size,
        )

    return _selfdev_batch_wait_action(
        reference_slice=reference_slice,
        reason="no allowlisted extended batch candidate remains",
        human_gate=(
            "Report the extended batch result and request a fresh gate before "
            "additional live source routing or runtime event storage changes."
        ),
    )


def _runtime_event_store_selfdev_batch_next_action(
    *,
    slices: list[SelfDevSlice],
    completion_slice: SelfDevSlice,
    window_size: int,
    failed_test_attempts: int,
    risk_flags: Optional[dict[str, bool]],
) -> Optional[dict[str, str]]:
    batch_gate_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        RUNTIME_EVENT_STORE_SELFDEV_BATCH_SOURCE_GATE_SUFFIX,
    )
    if batch_gate_slice is None:
        return None

    cloud_submit_started_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_STARTED_SOURCE_SUFFIX,
    )
    if (
        cloud_submit_started_slice is not None
        and cloud_submit_started_slice.status == "done"
    ):
        extended_next_action = _runtime_event_store_selfdev_extended_batch_next_action(
            slices=slices,
            completion_slice=cloud_submit_started_slice,
            window_size=RUNTIME_EVENT_STORE_SELFDEV_EXTENDED_BATCH_WINDOW_SIZE,
            failed_test_attempts=failed_test_attempts,
            risk_flags=risk_flags,
        )
        if extended_next_action is not None:
            return extended_next_action

    completed_sources = _selfdev_batch_completed_safe_sources(slices)
    reference_slice = completed_sources[-1] if completed_sources else batch_gate_slice
    if failed_test_attempts >= 2:
        return _selfdev_batch_wait_action(
            reference_slice=reference_slice,
            reason=(
                "self-dev batch focused tests failed twice; stop before "
                "continuing the preauthorized window"
            ),
            human_gate=(
                "A fresh gate is required before continuing the batch after "
                "repeated focused test failure."
            ),
        )

    if (
        cloud_submit_started_slice is not None
        and cloud_submit_started_slice.status == "done"
    ):
        return _selfdev_batch_wait_action(
            reference_slice=cloud_submit_started_slice,
            reason=(
                "cloud-submit started source is complete; no additional live "
                "source routing, cloud diff apply, public surface, backfill, "
                "storage semantics, provenance ownership, artifact lineage, "
                "orchestrator, benchmark, dependency, Zotero, HTTP, MCP, "
                "RH/ARE, commit, push, PR, release, or publishing work is "
                "approved."
            ),
            human_gate=(
                "A fresh gate is required before routing any additional live "
                "source into runtime_events or changing runtime event storage "
                "semantics."
            ),
        )

    cloud_submit_failure_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_FAILURE_SOURCE_SUFFIX,
    )
    if (
        cloud_submit_failure_slice is not None
        and cloud_submit_failure_slice.status == "done"
    ):
        return _selfdev_batch_wait_action(
            reference_slice=cloud_submit_failure_slice,
            reason=(
                "cloud-submit failure source is complete; no additional live "
                "source routing, cloud diff apply, public surface, backfill, "
                "storage semantics, provenance ownership, artifact lineage, "
                "orchestrator, benchmark, dependency, Zotero, HTTP, MCP, "
                "RH/ARE, commit, push, PR, release, or publishing work is "
                "approved."
            ),
            human_gate=(
                "A fresh gate is required before routing any additional live "
                "source into runtime_events or changing runtime event storage "
                "semantics."
            ),
        )

    cloud_submit_slice = _runtime_shell_p5_slice_by_suffix(
        slices,
        RUNTIME_EVENT_STORE_SELFDEV_CLOUD_SUBMIT_SOURCE_SUFFIX,
    )
    if cloud_submit_slice is not None and cloud_submit_slice.status == "done":
        return _selfdev_batch_wait_action(
            reference_slice=cloud_submit_slice,
            reason=(
                "cloud-submit source is complete; no additional live source "
                "routing, cloud diff apply, public surface, backfill, storage "
                "semantics, provenance ownership, artifact lineage, "
                "orchestrator, benchmark, dependency, Zotero, HTTP, MCP, "
                "RH/ARE, commit, push, PR, release, or publishing work is "
                "approved."
            ),
            human_gate=(
                "A fresh gate is required before routing any additional live "
                "source into runtime_events or changing runtime event storage "
                "semantics."
            ),
        )

    if len(completed_sources) >= window_size:
        return _selfdev_batch_wait_action(
            reference_slice=reference_slice,
            reason=(
                "self-dev batch window is exhausted after "
                f"{len(completed_sources)} whitelisted runtime event sources"
            ),
            human_gate=(
                "Report the batch result and request a fresh gate before "
                "routing additional live sources into runtime_events."
            ),
        )

    risky_flags = [
        key for key in RISK_KEYS if risk_flags is not None and risk_flags.get(key)
    ]
    if risky_flags:
        return _selfdev_batch_wait_action(
            reference_slice=reference_slice,
            reason=(
                "self-dev batch risk flags do not match the approved source "
                f"window: {', '.join(risky_flags)}"
            ),
            human_gate=(
                "A fresh gate is required before continuing with public, "
                "storage/provenance, orchestrator, benchmark, dependency, or "
                "other higher-risk changes."
            ),
        )

    for candidate in _selfdev_batch_source_candidates():
        if _selfdev_batch_source_is_done(slices, candidate["suffix"]):
            continue
        if candidate.get("safe") != "true":
            return _selfdev_batch_wait_action(
                reference_slice=reference_slice,
                reason=candidate.get(
                    "blocked_reason",
                    "next self-dev runtime event source is not whitelisted",
                ),
                human_gate=(
                    "cloud-submit requires explicit human approval; recording "
                    "an event after an approved submission is not approval to "
                    "perform the submission."
                ),
            )
        return _selfdev_batch_source_template(
            slices=slices,
            candidate=candidate,
            completed_safe_count=len(completed_sources),
            window_size=window_size,
        )

    return _selfdev_batch_wait_action(
        reference_slice=completion_slice,
        reason="no safe whitelisted self-dev runtime event source candidate remains",
        human_gate=(
            "Report the batch result and request a fresh gate before routing "
            "additional live sources into runtime_events."
        ),
    )


def _runtime_tool_failure_gate_normalizer_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return _runtime_shell_p5_template(
        slices=slices,
        suffix=RUNTIME_TOOL_FAILURE_GATE_NORMALIZER_SUFFIX,
        objective=(
            "Add pure typed tool failure and gate event normalization helpers "
            "for existing service, MCP, HTTP, Zotero, and orchestrator payloads "
            "without changing public output shapes or gate decisions."
        ),
        reason=(
            "runtime event and job ledger read-model slices are complete; the "
            "next S58-approved LG6 P5 slice is tool/failure/gate normalization"
        ),
        focused_test="packages/research_harness/tests/test_runtime_tool_boundary.py",
        boundary=(
            "public MCP/CLI/HTTP/Zotero/skill shapes, storage/provenance writes, "
            "artifact lineage, orchestrator gate behavior, benchmark claims, "
            "dependencies, commits, pushes, PRs, releases, or RH/ARE moves"
        ),
    )


def _runtime_skill_provenance_scanner_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return _runtime_shell_p5_template(
        slices=slices,
        suffix=RUNTIME_SKILL_PROVENANCE_SCANNER_SUFFIX,
        objective=(
            "Add a read-only skill provenance scanner for existing skill "
            "manifests, docs, sidecars, and generated-cache exclusions without "
            "changing advertised skill behavior or manifest contracts."
        ),
        reason=(
            "tool/failure/gate normalization is complete; the next S58-approved "
            "LG6 P5 slice is skill provenance read-model scanning"
        ),
        focused_test="packages/research_harness/tests/test_runtime_skill_provenance.py",
        boundary=(
            "manifest schema changes, advertised skill behavior changes, install "
            "behavior changes, public surface changes, storage/provenance, or "
            "dependency changes"
        ),
    )


def _runtime_doctor_readonly_diagnostics_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return _runtime_shell_p5_template(
        slices=slices,
        suffix=RUNTIME_DOCTOR_READONLY_DIAGNOSTICS_SUFFIX,
        objective=(
            "Add read-only doctor diagnostic helpers behind existing public "
            "shapes without changing `rh doctor` output or runtime behavior."
        ),
        reason=(
            "skill provenance scanning is complete; the next S58-approved LG6 "
            "P5 slice is read-only doctor diagnostics"
        ),
        focused_test="packages/research_harness/tests/test_runtime_doctor_diagnostics.py",
        boundary=(
            "public doctor command/output changes, storage/provenance, "
            "artifact lineage changes, dependencies, or RH/ARE moves"
        ),
    )


def _runtime_showcase_manifest_normalizer_template(
    slices: list[SelfDevSlice],
) -> dict[str, str]:
    return _runtime_shell_p5_template(
        slices=slices,
        suffix=RUNTIME_SHOWCASE_MANIFEST_NORMALIZER_SUFFIX,
        objective=(
            "Add read-only showcase manifest normalization helpers for existing "
            "manifest.json bundle files without adding public commands, DB "
            "lookups, publishing behavior, or artifact lineage semantics."
        ),
        reason=(
            "doctor diagnostics are complete; the next S58-approved LG6 P5 "
            "slice is showcase manifest normalization"
        ),
        focused_test="packages/research_harness/tests/test_runtime_showcase_manifest.py",
        boundary=(
            "public showcase command/output changes, DB lookups, publishing "
            "behavior, artifact lineage changes, dependencies, or RH/ARE moves"
        ),
    )


def _runtime_shell_p5_template(
    *,
    slices: list[SelfDevSlice],
    suffix: str,
    objective: str,
    reason: str,
    focused_test: str,
    boundary: str,
) -> dict[str, str]:
    return {
        "action": "create_slice",
        "slice_id": _next_knowledge_slice_id(slices, suffix),
        "phase": "P5",
        "risk": "low",
        "objective": objective,
        "reason": reason,
        "allowed_files": (
            "`packages/research_harness/research_harness/runtime/**`; "
            f"`{focused_test}`; "
            "`scripts/rh-selfdev.py`; "
            "`packages/research_harness/tests/test_rh_selfdev_script.py`; "
            "`.rh-selfdev/slices.md`; "
            "`.rh-selfdev/handoffs/**`; "
            "`.rh-selfdev/checkpoint.md`; "
            "`.rh-selfdev/rh-runtime-shell-implementation-plan.md`"
        ),
        "tests": (
            f"focused runtime-shell test `{focused_test}`; "
            "self-dev next-action tests; public surface guard; "
            "`python3 scripts/rh-selfdev.py status`; `git diff --check`"
        ),
        "human_gate": (
            f"No gate for read-only helper records. Gate required before {boundary}."
        ),
        "stop_rules": (
            "Stop before public surface, storage/provenance, artifact lineage, "
            "orchestrator gates, benchmark claims, dependencies, or "
            "compact-threshold boundaries."
        ),
    }


def _runtime_shell_p5_next_action(
    slices: list[SelfDevSlice],
    *,
    selfdev_batch_window_size: int = RUNTIME_EVENT_STORE_SELFDEV_BATCH_WINDOW_SIZE,
    selfdev_batch_failed_test_attempts: int = 0,
    selfdev_batch_risk_flags: Optional[dict[str, bool]] = None,
) -> Optional[dict[str, str]]:
    event_done = _runtime_shell_p5_slice_done(slices, RUNTIME_EVENT_NORMALIZER_SUFFIX)
    job_done = _runtime_shell_p5_slice_done(slices, RUNTIME_JOB_LEDGER_SUFFIX)
    if not (event_done and job_done):
        return None
    if not _runtime_shell_p5_slice_done(
        slices, RUNTIME_TOOL_FAILURE_GATE_NORMALIZER_SUFFIX
    ):
        return _runtime_tool_failure_gate_normalizer_template(slices)
    if not _runtime_shell_p5_slice_done(
        slices, RUNTIME_SKILL_PROVENANCE_SCANNER_SUFFIX
    ):
        return _runtime_skill_provenance_scanner_template(slices)
    if not _runtime_shell_p5_slice_done(
        slices, RUNTIME_DOCTOR_READONLY_DIAGNOSTICS_SUFFIX
    ):
        return _runtime_doctor_readonly_diagnostics_template(slices)
    if not _runtime_shell_p5_slice_done(
        slices, RUNTIME_SHOWCASE_MANIFEST_NORMALIZER_SUFFIX
    ):
        return _runtime_showcase_manifest_normalizer_template(slices)
    next_action_source_completion_slice = _runtime_shell_p5_slice_by_suffix(
        slices, RUNTIME_EVENT_STORE_SELFDEV_NEXT_ACTION_SOURCE_SUFFIX
    )
    if next_action_source_completion_slice is not None:
        batch_next_action = _runtime_event_store_selfdev_batch_next_action(
            slices=slices,
            completion_slice=next_action_source_completion_slice,
            window_size=selfdev_batch_window_size,
            failed_test_attempts=selfdev_batch_failed_test_attempts,
            risk_flags=selfdev_batch_risk_flags,
        )
        if batch_next_action is not None:
            return batch_next_action
        return _runtime_event_store_next_action_source_boundary_action(
            next_action_source_completion_slice
        )
    slice_status_source_completion_slice = _runtime_shell_p5_slice_by_suffix(
        slices, RUNTIME_EVENT_STORE_SELFDEV_SLICE_STATUS_SOURCE_SUFFIX
    )
    if slice_status_source_completion_slice is not None:
        return _runtime_event_store_slice_status_source_boundary_action(
            slice_status_source_completion_slice
        )
    prompt_source_completion_slice = _runtime_shell_p5_slice_by_suffix(
        slices, RUNTIME_EVENT_STORE_SELFDEV_PROMPT_SOURCE_SUFFIX
    )
    if prompt_source_completion_slice is not None:
        return _runtime_event_store_prompt_source_boundary_action(
            prompt_source_completion_slice
        )
    gate_report_source_completion_slice = _runtime_shell_p5_slice_by_suffix(
        slices, RUNTIME_EVENT_STORE_SELFDEV_GATE_REPORT_SOURCE_SUFFIX
    )
    if gate_report_source_completion_slice is not None:
        return _runtime_event_store_gate_report_source_boundary_action(
            gate_report_source_completion_slice
        )
    handoff_source_completion_slice = _runtime_shell_p5_slice_by_suffix(
        slices, RUNTIME_EVENT_STORE_SELFDEV_HANDOFF_SOURCE_SUFFIX
    )
    if handoff_source_completion_slice is not None:
        return _runtime_event_store_handoff_source_boundary_action(
            handoff_source_completion_slice
        )
    first_source_completion_slice = _runtime_shell_p5_slice_by_suffix(
        slices, RUNTIME_EVENT_STORE_SELFDEV_CHECKPOINT_SOURCE_SUFFIX
    )
    if first_source_completion_slice is not None:
        return _runtime_event_store_first_source_boundary_action(
            first_source_completion_slice
        )
    event_store_completion_slice = _runtime_shell_p5_slice_by_suffix(
        slices, RUNTIME_EVENT_STORE_SCHEMA_ONLY_SUFFIX
    )
    if event_store_completion_slice is not None:
        return _runtime_event_store_schema_boundary_action(event_store_completion_slice)
    p6a_completion_slice = _runtime_shell_p5_slice_by_suffix(
        slices, RUNTIME_DOCTOR_DIAGNOSTICS_OPT_IN_CLI_SUFFIX
    )
    if p6a_completion_slice is not None:
        return _runtime_shell_p6a_boundary_action(p6a_completion_slice)
    completion_slice = _runtime_shell_p5_slice_by_suffix(
        slices, RUNTIME_SHOWCASE_MANIFEST_NORMALIZER_SUFFIX
    )
    if completion_slice is not None:
        return _runtime_shell_p5_complete_action(completion_slice)
    return None


def _transport_cli_statuses(path: Path = TRANSPORT_COVERAGE_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    statuses: dict[str, str] = {}
    row_re = re.compile(
        r"^\|\s*`([^`]+)`\s*\|\s*`?([^|`]+)`?\s*\|\s*`?([^|`]+)`?\s*\|\s*`?([^|`]+)`?\s*\|",
        re.MULTILINE,
    )
    for command_name, _mcp_status, _python_status, cli_status in row_re.findall(
        path.read_text(encoding="utf-8")
    ):
        statuses[command_name.strip()] = cli_status.strip()
    return statuses


def _transport_python_statuses(path: Path = TRANSPORT_COVERAGE_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    statuses: dict[str, str] = {}
    row_re = re.compile(
        r"^\|\s*`([^`]+)`\s*\|\s*`?([^|`]+)`?\s*\|\s*`?([^|`]+)`?\s*\|",
        re.MULTILINE,
    )
    for command_name, _mcp_status, python_status in row_re.findall(
        path.read_text(encoding="utf-8")
    ):
        statuses[command_name.strip()] = python_status.strip()
    return statuses


def _transport_http_statuses(path: Path = TRANSPORT_COVERAGE_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    statuses: dict[str, str] = {}
    row_re = re.compile(
        r"^\|\s*`([^`]+)`\s*\|\s*`?([^|`]+)`?\s*\|\s*`?([^|`]+)`?\s*\|\s*`?([^|`]+)`?\s*\|\s*`?([^|`]+)`?\s*\|",
        re.MULTILINE,
    )
    for (
        command_name,
        _mcp_status,
        _python_status,
        _cli_status,
        http_status,
    ) in row_re.findall(path.read_text(encoding="utf-8")):
        statuses[command_name.strip()] = http_status.strip()
    return statuses


def _cli_topic_reads_are_service_backed() -> bool:
    statuses = _transport_cli_statuses()
    return all(
        statuses.get(command_name) == "service-backed"
        for command_name in ("topic_list", "topic_show")
    )


def _cli_paper_list_is_service_backed() -> bool:
    return _transport_cli_statuses().get("paper_list") == "service-backed"


def _cli_provenance_summary_is_service_backed() -> bool:
    return _transport_cli_statuses().get("provenance_summary") == "service-backed"


def _cli_provenance_export_is_service_backed() -> bool:
    return _transport_cli_statuses().get("provenance_export") == "service-backed"


def _cli_orchestrator_reads_are_service_backed() -> bool:
    statuses = _transport_cli_statuses()
    return all(
        statuses.get(command_name) == "service-backed"
        for command_name in ("orchestrator_status", "orchestrator_gate_check")
    )


def _python_orchestrator_reads_are_service_backed() -> bool:
    statuses = _transport_python_statuses()
    return all(
        statuses.get(command_name) == "service-backed"
        for command_name in ("orchestrator_status", "orchestrator_gate_check")
    )


def _http_topic_list_is_service_backed() -> bool:
    return _transport_http_statuses().get("topic_list") == "service-backed"


def _http_provenance_summary_is_service_backed() -> bool:
    return _transport_http_statuses().get("provenance_summary") == "service-backed"


def _http_topic_show_is_service_backed() -> bool:
    return _transport_http_statuses().get("topic_show") == "service-backed"


def _http_paper_list_is_service_backed() -> bool:
    return _transport_http_statuses().get("paper_list") == "service-backed"


def _http_orchestrator_gate_check_is_service_backed() -> bool:
    return _transport_http_statuses().get("orchestrator_gate_check") == "service-backed"


def _http_orchestrator_status_is_service_backed() -> bool:
    return _transport_http_statuses().get("orchestrator_status") == "service-backed"


def _http_deferred_shape_harness_is_done(slices: list[SelfDevSlice]) -> bool:
    return any(
        slice_def.status == "done"
        and slice_def.slice_id.endswith(HTTP_DEFERRED_SHAPE_HARNESS_TEMPLATE_SUFFIX)
        for slice_def in slices
    )


def _http_orchestrator_status_routing_is_done(
    slices: list[SelfDevSlice],
) -> bool:
    return any(
        slice_def.status == "done"
        and slice_def.slice_id.endswith(
            HTTP_ORCHESTRATOR_STATUS_ROUTING_TEMPLATE_SUFFIX
        )
        for slice_def in slices
    )


def _lg3_compatibility_lifecycle_guard_is_done(
    slices: list[SelfDevSlice],
) -> bool:
    return any(
        slice_def.status == "done"
        and slice_def.slice_id.endswith(
            LG3_COMPATIBILITY_LIFECYCLE_GUARD_TEMPLATE_SUFFIX
        )
        for slice_def in slices
    )


def _architecture_completion_audit_done(
    slices: list[SelfDevSlice],
) -> Optional[SelfDevSlice]:
    for slice_def in slices:
        if slice_def.status == "done" and slice_def.slice_id.endswith(
            ARCHITECTURE_COMPLETION_AUDIT_TEMPLATE_SUFFIX
        ):
            return slice_def
    return None


def _cross_topic_atlas_local_cli_preview_done(
    slices: list[SelfDevSlice],
) -> bool:
    return any(
        slice_def.status == "done"
        and slice_def.slice_id.endswith(CROSS_TOPIC_ATLAS_LOCAL_CLI_PREVIEW_SUFFIX)
        for slice_def in slices
    )


def _topic_knowledge_local_preview_closeout_done(
    slices: list[SelfDevSlice],
) -> Optional[SelfDevSlice]:
    for slice_def in slices:
        if slice_def.status == "done" and slice_def.slice_id.endswith(
            KNOWLEDGE_LOCAL_PREVIEW_CLOSEOUT_SUFFIX
        ):
            return slice_def
    return None


def _topic_knowledge_http_beta_completion_done(
    slices: list[SelfDevSlice],
) -> Optional[SelfDevSlice]:
    for suffix in KNOWLEDGE_HTTP_BETA_COMPLETION_SUFFIXES:
        for slice_def in reversed(slices):
            if slice_def.status == "done" and slice_def.slice_id.endswith(suffix):
                return slice_def
    return None


def _lg16_existing_system_finalization_done(
    slices: list[SelfDevSlice],
) -> Optional[SelfDevSlice]:
    for slice_def in reversed(slices):
        if (
            slice_def.slice_id == LG16_EXISTING_SYSTEM_FINALIZATION_ID
            and slice_def.status == "done"
        ):
            return slice_def
    return None


def _lg16_existing_system_finalization_complete_action(
    slice_def: SelfDevSlice,
) -> dict[str, str]:
    return {
        "action": "complete_existing_system_finalization",
        "slice_id": slice_def.slice_id,
        "phase": slice_def.phase,
        "risk": slice_def.risk,
        "objective": slice_def.objective,
        "reason": (
            "LG16 existing-system finalization is complete: new public surface is "
            "frozen, critical-path coverage is wired to real focused tests, "
            "transport matrices reject unresolved direct/deferred debt, and "
            "service-backed facade/CLI/HTTP adapters are shape-locked."
        ),
        "human_gate": (
            "Phase A internal stabilization is locally complete. Phase B remains "
            "separate for public HTTP deployment, real Zotero sync/apply, release "
            "actions, and public benchmark/performance claims."
        ),
    }


def _phase_b_gate_templates() -> tuple[dict[str, str], ...]:
    common_allowed_files = (
        "`.rh-selfdev/slices.md`; "
        "`.rh-selfdev/long-goals.md`; "
        "`.rh-selfdev/checkpoint.md`; "
        "`.rh-selfdev/handoffs/**`; "
        "`.rh-selfdev/gates/**`; "
        "`scripts/rh-selfdev.py`; "
        "`packages/research_harness/tests/test_rh_selfdev_script.py`"
    )
    return (
        {
            "slice_id": PHASE_B_GATE_SLICE_IDS[0],
            "phase": "P18",
            "risk": "high",
            "objective": (
                "Close the Phase B public HTTP deployment gate locally by "
                "requiring mandatory auth for non-loopback bind attempts, "
                "documenting TLS/proxy/allowlist/CORS/cache policy, and "
                "making release smoke start the HTTP app and hit representative "
                "routes."
            ),
            "reason": (
                "LG16 internal stabilization is complete and Phase B has been "
                "started; public HTTP deployment needs local gate hardening "
                "before any external exposure."
            ),
            "allowed_files": (
                common_allowed_files
                + "; `packages/research_harness_mcp/research_harness_mcp/http_auth.py`; "
                "`packages/research_harness_mcp/tests/test_http_boundary_auth.py`; "
                "`scripts/check-release-gates.py`; "
                "`scripts/release-artifact-smoke.sh`; "
                "`packages/research_harness/tests/test_release_gate_scripts.py`; "
                "`docs/contracts/release-boundary.md`; "
                "`docs/knowledge-http-api.md`; `docs/quickstart.md`; "
                "`docs/quickstart.zh.md`"
            ),
            "tests": (
                "focused Phase B HTTP tests; `python3 scripts/check-release-gates.py`; "
                "`scripts/release-artifact-smoke.sh`; `scripts/codex-check.sh --quick`; "
                "`git diff --check`"
            ),
            "human_gate": (
                "Local gate work is pre-approved by the RH self-dev control "
                "plane. Stop before real public deployment, credential/config "
                "mutation, third-party writes, commits, pushes, PRs, releases, "
                "or publishing."
            ),
        },
        {
            "slice_id": PHASE_B_GATE_SLICE_IDS[1],
            "phase": "P18",
            "risk": "high",
            "objective": (
                "Close the Phase B Zotero real sync/apply gate locally with "
                "fake/sandbox adapter coverage for dry-run, pull/both, and "
                "non-dry-run intent/preview/receipt/rollback evidence."
            ),
            "reason": (
                f"{PHASE_B_GATE_SLICE_IDS[0]} is complete; Phase B Zotero "
                "real sync/apply readiness remains the next deferred release gate."
            ),
            "allowed_files": (
                common_allowed_files
                + "; Zotero sync/apply service, HTTP, CLI, and fake-adapter tests "
                "selected by the bounded LG18 slice"
            ),
            "tests": (
                "focused Zotero fake/sandbox sync/apply tests; release/Zotero "
                "guards; `scripts/codex-check.sh --quick`; `git diff --check`"
            ),
            "human_gate": (
                "Local fake/sandbox implementation is allowed. Stop before real "
                "Zotero network sync/apply, credentials, third-party writes, "
                "release/publish, commits, pushes, PRs, or public readiness claims."
            ),
        },
        {
            "slice_id": PHASE_B_GATE_SLICE_IDS[2],
            "phase": "P18",
            "risk": "high",
            "objective": (
                "Close the Phase B release/dependency gate by keeping dependency "
                "audit required, recording zero-vulnerability or risk-accepted "
                "evidence, and requiring critical-path coverage before public release."
            ),
            "reason": (
                f"{PHASE_B_GATE_SLICE_IDS[1]} is complete; Phase B release/"
                "dependency readiness is the remaining local publication gate."
            ),
            "allowed_files": (
                common_allowed_files
                + "; release workflow, dependency-audit, coverage, release-gate "
                "guard, and focused release tests selected by the bounded LG19 slice"
            ),
            "tests": (
                "focused release/dependency guard tests; required dependency audit; "
                "`scripts/codex-check.sh --coverage`; `scripts/codex-check.sh --quick`; "
                "`git diff --check`"
            ),
            "human_gate": (
                "Local release/dependency gate hardening is allowed. Stop before "
                "commits, pushes, PRs, releases, publishing, dependency upgrades "
                "outside the gate, public claims, credentials, or third-party writes."
            ),
        },
    )


def _phase_b_next_action(slices: list[SelfDevSlice]) -> Optional[dict[str, str]]:
    phase_b_started = any(
        slice_def.slice_id in PHASE_B_GATE_SLICE_IDS for slice_def in slices
    )
    if not phase_b_started:
        return None

    completed = {
        slice_def.slice_id
        for slice_def in slices
        if slice_def.status == "done" and slice_def.slice_id in PHASE_B_GATE_SLICE_IDS
    }
    for template in _phase_b_gate_templates():
        if template["slice_id"] not in completed:
            return {"action": "create_slice", **template}

    return {
        "action": "complete_phase_b_release_gates",
        "slice_id": PHASE_B_GATE_SLICE_IDS[-1],
        "phase": "P18",
        "risk": "high",
        "objective": "Close Phase B public HTTP, Zotero, and release gates locally.",
        "reason": (
            "Phase B local gates are complete: public HTTP deployment is guarded, "
            "Zotero real sync/apply is fake/sandbox validated, and release/"
            "dependency gates require audit plus critical-path coverage evidence."
        ),
        "human_gate": (
            "Non-local actions remain excluded: real public deployment, real "
            "Zotero network sync/apply, commits, pushes, PRs, releases, "
            "publishing, credentials, third-party writes, and public benchmark/"
            "performance claims still require an explicit user request."
        ),
    }


def suggest_next_action(
    slices: list[SelfDevSlice],
    *,
    ignored_active_slice_ids: Optional[set[str]] = None,
    selfdev_batch_window_size: int = RUNTIME_EVENT_STORE_SELFDEV_BATCH_WINDOW_SIZE,
    selfdev_batch_failed_test_attempts: int = 0,
    selfdev_batch_risk_flags: Optional[dict[str, bool]] = None,
    transport_coverage_exists: Optional[bool] = None,
    cli_read_shape_tests_exist: Optional[bool] = None,
    cli_topic_reads_service_backed: Optional[bool] = None,
    cli_paper_list_service_backed: Optional[bool] = None,
    cli_provenance_summary_service_backed: Optional[bool] = None,
    cli_provenance_export_service_backed: Optional[bool] = None,
    cli_orchestrator_reads_service_backed: Optional[bool] = None,
    python_orchestrator_reads_service_backed: Optional[bool] = None,
    http_topic_list_service_backed: Optional[bool] = None,
    http_provenance_summary_service_backed: Optional[bool] = None,
    http_deferred_shape_harness_done: Optional[bool] = None,
    http_topic_show_service_backed: Optional[bool] = None,
    http_paper_list_service_backed: Optional[bool] = None,
    http_orchestrator_gate_check_service_backed: Optional[bool] = None,
    http_orchestrator_status_service_backed: Optional[bool] = None,
    http_orchestrator_status_routing_done: Optional[bool] = None,
    lg3_compatibility_lifecycle_guard_done: Optional[bool] = None,
    architecture_completion_audit_done: Optional[SelfDevSlice] = None,
) -> dict[str, str]:
    ignored_active_slice_ids = ignored_active_slice_ids or set()
    dispatch_slices = [
        slice_def
        for slice_def in slices
        if not (
            slice_def.slice_id in ignored_active_slice_ids
            and slice_def.status in {"gate", "in_progress"}
        )
    ]

    gate_slice = select_pending_gate(dispatch_slices)
    if gate_slice is not None:
        return {
            "action": "wait_for_gate",
            "slice_id": gate_slice.slice_id,
            "phase": gate_slice.phase,
            "risk": gate_slice.risk,
            "objective": gate_slice.objective,
            "reason": "pending human gate blocks dispatch",
            "human_gate": gate_slice.human_gate,
        }

    active_slice = select_active_slice(dispatch_slices)
    if active_slice is not None:
        return {
            "action": "continue_slice",
            "slice_id": active_slice.slice_id,
            "phase": active_slice.phase,
            "risk": active_slice.risk,
            "objective": active_slice.objective,
            "reason": "slice is already in progress",
            "allowed_files": active_slice.allowed_files,
            "tests": active_slice.tests,
            "human_gate": active_slice.human_gate,
        }

    try:
        next_slice = select_next_slice(dispatch_slices)
    except ValueError:
        phase_b_action = _phase_b_next_action(slices)
        if phase_b_action is not None:
            return phase_b_action
        lg16_done = _lg16_existing_system_finalization_done(slices)
        if lg16_done is not None:
            return _lg16_existing_system_finalization_complete_action(lg16_done)
        lg8_performance_governance_next_action = (
            _lg8_performance_governance_next_action(slices)
        )
        if lg8_performance_governance_next_action is not None:
            return lg8_performance_governance_next_action
        if transport_coverage_exists is None:
            transport_coverage_exists = TRANSPORT_COVERAGE_PATH.exists()
        if cli_read_shape_tests_exist is None:
            cli_read_shape_tests_exist = CLI_READ_SHAPE_TEST_PATH.exists()
        if cli_topic_reads_service_backed is None:
            cli_topic_reads_service_backed = _cli_topic_reads_are_service_backed()
        if cli_paper_list_service_backed is None:
            cli_paper_list_service_backed = _cli_paper_list_is_service_backed()
        if cli_provenance_summary_service_backed is None:
            cli_provenance_summary_service_backed = (
                _cli_provenance_summary_is_service_backed()
            )
        if cli_provenance_export_service_backed is None:
            cli_provenance_export_service_backed = (
                _cli_provenance_export_is_service_backed()
            )
        if cli_orchestrator_reads_service_backed is None:
            cli_orchestrator_reads_service_backed = (
                _cli_orchestrator_reads_are_service_backed()
            )
        if python_orchestrator_reads_service_backed is None:
            python_orchestrator_reads_service_backed = (
                _python_orchestrator_reads_are_service_backed()
            )
        if http_topic_list_service_backed is None:
            http_topic_list_service_backed = _http_topic_list_is_service_backed()
        if http_provenance_summary_service_backed is None:
            http_provenance_summary_service_backed = (
                _http_provenance_summary_is_service_backed()
            )
        if http_deferred_shape_harness_done is None:
            http_deferred_shape_harness_done = _http_deferred_shape_harness_is_done(
                slices
            )
        if http_topic_show_service_backed is None:
            http_topic_show_service_backed = _http_topic_show_is_service_backed()
        if http_paper_list_service_backed is None:
            http_paper_list_service_backed = _http_paper_list_is_service_backed()
        if http_orchestrator_gate_check_service_backed is None:
            http_orchestrator_gate_check_service_backed = (
                _http_orchestrator_gate_check_is_service_backed()
            )
        if http_orchestrator_status_service_backed is None:
            http_orchestrator_status_service_backed = (
                _http_orchestrator_status_is_service_backed()
            )
        if http_orchestrator_status_routing_done is None:
            http_orchestrator_status_routing_done = (
                _http_orchestrator_status_routing_is_done(slices)
            )
        if lg3_compatibility_lifecycle_guard_done is None:
            lg3_compatibility_lifecycle_guard_done = (
                _lg3_compatibility_lifecycle_guard_is_done(slices)
            )
        if architecture_completion_audit_done is None:
            architecture_completion_audit_done = _architecture_completion_audit_done(
                slices
            )
        runtime_shell_p5_next_action = _runtime_shell_p5_next_action(
            slices,
            selfdev_batch_window_size=selfdev_batch_window_size,
            selfdev_batch_failed_test_attempts=selfdev_batch_failed_test_attempts,
            selfdev_batch_risk_flags=selfdev_batch_risk_flags,
        )
        if runtime_shell_p5_next_action is not None:
            return runtime_shell_p5_next_action
        topic_knowledge_http_beta_done = _topic_knowledge_http_beta_completion_done(
            slices
        )
        if topic_knowledge_http_beta_done is not None:
            return _topic_knowledge_http_beta_line_complete_action(
                topic_knowledge_http_beta_done
            )
        topic_knowledge_closeout_done = _topic_knowledge_local_preview_closeout_done(
            slices
        )
        if topic_knowledge_closeout_done is not None:
            return _topic_knowledge_line_complete_action(topic_knowledge_closeout_done)
        if _cross_topic_atlas_local_cli_preview_done(slices):
            return _topic_knowledge_local_preview_closeout_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
            and cli_provenance_export_service_backed
            and cli_orchestrator_reads_service_backed
            and python_orchestrator_reads_service_backed
            and http_topic_list_service_backed
            and http_provenance_summary_service_backed
            and http_deferred_shape_harness_done
            and http_topic_show_service_backed
            and http_paper_list_service_backed
            and http_orchestrator_gate_check_service_backed
            and http_orchestrator_status_service_backed
            and http_orchestrator_status_routing_done
        ):
            if architecture_completion_audit_done is not None:
                return _architecture_line_complete_action(
                    architecture_completion_audit_done
                )
            if lg3_compatibility_lifecycle_guard_done:
                return _architecture_completion_audit_template(slices)
            return _lg3_compatibility_lifecycle_guard_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
            and cli_provenance_export_service_backed
            and cli_orchestrator_reads_service_backed
            and python_orchestrator_reads_service_backed
            and http_topic_list_service_backed
            and http_provenance_summary_service_backed
            and http_deferred_shape_harness_done
            and http_topic_show_service_backed
            and http_paper_list_service_backed
            and http_orchestrator_gate_check_service_backed
        ):
            return _http_orchestrator_status_routing_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
            and cli_provenance_export_service_backed
            and cli_orchestrator_reads_service_backed
            and python_orchestrator_reads_service_backed
            and http_topic_list_service_backed
            and http_provenance_summary_service_backed
            and http_deferred_shape_harness_done
            and http_topic_show_service_backed
            and http_paper_list_service_backed
        ):
            return _http_orchestrator_gate_check_routing_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
            and cli_provenance_export_service_backed
            and cli_orchestrator_reads_service_backed
            and python_orchestrator_reads_service_backed
            and http_topic_list_service_backed
            and http_provenance_summary_service_backed
            and http_deferred_shape_harness_done
            and http_topic_show_service_backed
        ):
            return _http_paper_list_routing_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
            and cli_provenance_export_service_backed
            and cli_orchestrator_reads_service_backed
            and python_orchestrator_reads_service_backed
            and http_topic_list_service_backed
            and http_provenance_summary_service_backed
            and http_deferred_shape_harness_done
        ):
            return _http_topic_show_routing_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
            and cli_provenance_export_service_backed
            and cli_orchestrator_reads_service_backed
            and python_orchestrator_reads_service_backed
            and http_topic_list_service_backed
            and http_provenance_summary_service_backed
        ):
            return _http_deferred_shape_harness_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
            and cli_provenance_export_service_backed
            and cli_orchestrator_reads_service_backed
            and python_orchestrator_reads_service_backed
            and http_topic_list_service_backed
        ):
            return _http_provenance_summary_routing_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
            and cli_provenance_export_service_backed
            and cli_orchestrator_reads_service_backed
            and python_orchestrator_reads_service_backed
        ):
            return _http_topic_list_routing_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
            and cli_provenance_export_service_backed
            and cli_orchestrator_reads_service_backed
        ):
            return _python_orchestrator_read_routing_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
            and cli_provenance_export_service_backed
        ):
            return _cli_orchestrator_read_routing_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
            and cli_provenance_summary_service_backed
        ):
            return _cli_provenance_export_routing_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
            and cli_paper_list_service_backed
        ):
            return _cli_provenance_summary_routing_template(slices)
        if (
            transport_coverage_exists
            and cli_read_shape_tests_exist
            and cli_topic_reads_service_backed
        ):
            return _cli_paper_list_routing_template(slices)
        if transport_coverage_exists and cli_read_shape_tests_exist:
            return _cli_topic_read_routing_template(slices)
        if transport_coverage_exists:
            return _cli_route_test_template(slices)
        return _transport_inventory_template(slices)

    return {
        "action": "run_slice",
        "slice_id": next_slice.slice_id,
        "phase": next_slice.phase,
        "risk": next_slice.risk,
        "objective": next_slice.objective,
        "reason": "todo slice is available",
        "allowed_files": next_slice.allowed_files,
        "tests": next_slice.tests,
        "human_gate": next_slice.human_gate,
    }


def _format_next_action(action: dict[str, str]) -> list[str]:
    ordered_keys = (
        "action",
        "slice_id",
        "phase",
        "risk",
        "objective",
        "reason",
        "allowed_files",
        "tests",
        "human_gate",
        "stop_rules",
    )
    return [
        f"{key}: {action[key]}" for key in ordered_keys if key in action and action[key]
    ]


def build_checkpoint_text(
    *,
    slices: list[SelfDevSlice],
    changed_files: list[str],
    notes: Optional[list[str]] = None,
    transport_coverage_exists: Optional[bool] = None,
    cli_read_shape_tests_exist: Optional[bool] = None,
) -> str:
    flags = detect_risk_flags(changed_files)
    lines = [
        "# RH Self-Development Checkpoint",
        "",
        f"Date: {timestamp()}",
        "Executor: codex",
        "",
        "## Current Slice State",
        "",
    ]
    lines.extend(f"- {line}" for line in _current_slice_summary(slices))
    lines.extend(["", "## Dirty Files", ""])
    if changed_files:
        lines.extend(f"- `{file_name}`" for file_name in changed_files)
    else:
        lines.append("- None reported.")
    lines.extend(["", "## Risk Flags", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in flags.items())
    if notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
    action = suggest_next_action(
        slices,
        transport_coverage_exists=transport_coverage_exists,
        cli_read_shape_tests_exist=cli_read_shape_tests_exist,
        selfdev_batch_risk_flags=flags,
    )
    if action["action"] == "create_slice":
        lines.extend(["", "## Suggested Next Action", ""])
        lines.append("- Create one bounded slice before continuing.")
        lines.extend(f"- {line}" for line in _format_next_action(action))
    elif action:
        lines.extend(["", "## Next Action Boundary", ""])
        lines.append("- Do not create another implementation slice automatically.")
        lines.extend(f"- {line}" for line in _format_next_action(action))
    lines.extend(["", "## Recent Handoffs", ""])
    handoffs = _recent_artifacts(HANDOFF_DIR)
    lines.extend(f"- `{path}`" for path in handoffs) if handoffs else lines.append(
        "- None found."
    )
    lines.extend(["", "## Recent Gates", ""])
    gates = _recent_artifacts(GATE_DIR)
    lines.extend(f"- `{path}`" for path in gates) if gates else lines.append(
        "- None found."
    )
    lines.extend(
        [
            "",
            "## Resume Instructions",
            "",
            "1. Read `.rh-selfdev/control-plane.md`.",
            "2. Read `.rh-selfdev/long-goals.md` if present.",
            "3. Read `.rh-selfdev/slices.md` and this checkpoint.",
            "4. Run `python3 scripts/rh-selfdev.py status`.",
            "5. If a gate is pending, resolve or report that gate before dispatching another slice.",
            "6. If no todo slice remains, run `python3 scripts/rh-selfdev.py next-action --json`; continue only when it returns `create_slice`, and stop/report when it returns a completion or gate boundary.",
            "7. Continue only within the selected slice's allowed files and stop rules.",
            "",
            "## Clear/Compact Protocol",
            "",
            "Before clearing the main session, run "
            '`python3 scripts/rh-selfdev.py checkpoint --note "<state>"`; '
            "then clear or compact the session. After clearing, resume from the "
            "files listed above rather than from chat history.",
        ]
    )
    return "\n".join(lines) + "\n"


def _checkpoint_timestamp_from_text(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.startswith("Date: "):
            value = line.removeprefix("Date: ").strip()
            return value or None
    return None


def _checkpoint_event_job_id(slices: list[SelfDevSlice]) -> Optional[str]:
    active_slice = select_active_slice(slices)
    if active_slice is not None:
        return active_slice.slice_id
    gate_slice = select_pending_gate(slices)
    if gate_slice is not None:
        return gate_slice.slice_id
    try:
        return select_next_slice(slices).slice_id
    except (GatePendingError, ValueError):
        action = suggest_next_action(slices)
        value = action.get("slice_id")
        return value if value else None


def _checkpoint_event_metadata(
    *,
    path: Path,
    slices: list[SelfDevSlice],
    changed_files: list[str],
    notes: list[str],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "checkpoint_path": _display_path(path),
        "dirty_file_count": len(changed_files),
        "notes": _redact_selfdev_freeform_metadata(list(notes)),
        "risk_flags": detect_risk_flags(changed_files),
    }
    active_slice = select_active_slice(slices)
    gate_slice = select_pending_gate(slices)
    if active_slice is not None:
        metadata["slice_id"] = active_slice.slice_id
    elif gate_slice is not None:
        metadata["pending_gate"] = gate_slice.slice_id
    else:
        job_id = _checkpoint_event_job_id(slices)
        if job_id is not None:
            metadata["slice_id"] = job_id
    return metadata


def _append_checkpoint_runtime_event(
    *,
    path: Path,
    text: str,
    slices: list[SelfDevSlice],
    changed_files: list[str],
    notes: list[str],
) -> Optional[object]:
    created_at = _checkpoint_timestamp_from_text(text)
    if created_at is None:
        return None
    try:
        from research_harness._core.config import load_runtime_config
        from research_harness._core.storage.db import Database
        from research_harness.runtime.event_normalizer import RuntimeEventRecord
        from research_harness.runtime.event_store import _append_runtime_event
    except Exception:
        return None

    try:
        config = load_runtime_config(cwd=REPO_ROOT)
        if not config.db_path.exists():
            return None
        db = Database(config.db_path)
        record = RuntimeEventRecord(
            event_id=f"selfdev_checkpoint:{created_at}",
            event_type="selfdev.checkpoint_created",
            created_at=created_at,
            origin_surface="self_dev",
            actor="codex",
            job_id=_checkpoint_event_job_id(slices),
            tool_name="rh-selfdev checkpoint",
            artifact_refs=(_display_path(path),),
            payload={},
        )
        return _append_runtime_event(
            db,
            record,
            metadata=_checkpoint_event_metadata(
                path=path,
                slices=slices,
                changed_files=changed_files,
                notes=notes,
            ),
        )
    except Exception:
        return None


def write_checkpoint(
    *,
    path: Path = CHECKPOINT_FILE,
    notes: Optional[list[str]] = None,
) -> Path:
    slices = load_slices()
    changed = git_changed_files()
    path.parent.mkdir(parents=True, exist_ok=True)
    note_values = notes or []
    text = build_checkpoint_text(
        slices=slices,
        changed_files=changed,
        notes=note_values,
    )
    path.write_text(text, encoding="utf-8")
    _append_checkpoint_runtime_event(
        path=path,
        text=text,
        slices=slices,
        changed_files=changed,
        notes=note_values,
    )
    return path


def command_status(args: argparse.Namespace) -> int:
    slices = load_slices()
    gate_slice = select_pending_gate(slices)
    active_slice = select_active_slice(slices)
    changed = git_changed_files()
    flags = detect_risk_flags(changed)
    status_action: dict[str, str]
    print(f"Control plane: {CONTROL_PLANE.relative_to(REPO_ROOT)}")
    if gate_slice is not None:
        status_action = {
            "action": "wait_for_gate",
            "slice_id": gate_slice.slice_id,
            "phase": gate_slice.phase,
            "risk": gate_slice.risk,
            "objective": gate_slice.objective,
            "reason": "pending human gate blocks dispatch",
            "human_gate": gate_slice.human_gate,
        }
        print(
            f"Pending gate: {gate_slice.slice_id} "
            f"({gate_slice.phase}, {gate_slice.risk})"
        )
        print(f"Objective: {gate_slice.objective}")
        print(f"Human gate: {gate_slice.human_gate}")
        print("Next dispatch: blocked until this gate is approved.")
    elif active_slice is not None:
        status_action = {
            "action": "continue_slice",
            "slice_id": active_slice.slice_id,
            "phase": active_slice.phase,
            "risk": active_slice.risk,
            "objective": active_slice.objective,
            "reason": "slice is already in progress",
            "human_gate": active_slice.human_gate,
        }
        print(
            f"Active slice: {active_slice.slice_id} "
            f"({active_slice.phase}, {active_slice.risk})"
        )
        print(f"Objective: {active_slice.objective}")
        print(f"Allowed files: {active_slice.allowed_files}")
        print(f"Tests: {active_slice.tests}")
        print(f"Human gate: {active_slice.human_gate}")
    else:
        try:
            next_slice = select_next_slice(slices)
            status_action = {
                "action": "run_slice",
                "slice_id": next_slice.slice_id,
                "phase": next_slice.phase,
                "risk": next_slice.risk,
                "objective": next_slice.objective,
                "reason": "todo slice is available",
                "human_gate": next_slice.human_gate,
            }
            print(
                f"Next slice: {next_slice.slice_id} "
                f"({next_slice.phase}, {next_slice.risk})"
            )
            print(f"Objective: {next_slice.objective}")
            print(f"Allowed files: {next_slice.allowed_files}")
            print(f"Tests: {next_slice.tests}")
            print(f"Human gate: {next_slice.human_gate}")
        except ValueError:
            action = suggest_next_action(slices, selfdev_batch_risk_flags=flags)
            status_action = action
            print(f"Next action: {action.get('action', 'none')}")
            if action.get("slice_id"):
                print(f"Boundary slice: {action['slice_id']}")
            if action.get("phase") or action.get("risk"):
                print(
                    "Phase/risk: "
                    f"{action.get('phase', 'n/a')}/{action.get('risk', 'n/a')}"
                )
            if action.get("objective"):
                print(f"Objective: {action['objective']}")
            if action.get("reason"):
                print(f"Reason: {action['reason']}")
            if action.get("human_gate"):
                print(f"Human gate: {action['human_gate']}")
    print(f"Dirty files: {len(changed)}")
    for file_name in changed:
        print(f"  - {file_name}")
    print("Risk flags:")
    for key, value in flags.items():
        print(f"  - {key}: {value}")
    _append_status_runtime_event(
        action=status_action,
        changed_files=changed,
        risk_flags=flags,
        created_at=timestamp(),
    )
    return 0


def _resolve_slice_arg(slice_arg: Optional[str]) -> SelfDevSlice:
    slices = load_slices()
    if slice_arg is None or slice_arg == "next":
        return select_next_slice(slices)
    return find_slice(slice_arg, slices)


def command_prompt(args: argparse.Namespace) -> int:
    slice_def = _resolve_slice_arg(args.slice)
    prompt_path = write_prompt(slice_def, prompt_dir=PROMPT_DIR)
    print(_display_path(prompt_path))
    return 0


def command_cloud_command(args: argparse.Namespace) -> int:
    slice_def = _resolve_slice_arg(args.slice)
    prompt = build_worker_prompt(slice_def)
    command = build_cloud_exec_command(
        environment_id=args.env,
        branch=args.branch,
        prompt=prompt,
        attempts=args.attempts,
    )
    _append_cloud_command_runtime_event(
        slice_def=slice_def,
        command=command,
        environment_id=args.env,
        branch=args.branch,
        attempts=args.attempts,
        created_at=timestamp(),
    )
    print("\n".join(command))
    return 0


def command_codex_command(args: argparse.Namespace) -> int:
    slice_def = _resolve_slice_arg(args.slice)
    worktree_path = Path(args.worktree)
    prompt_path = Path(args.prompt_path)
    output_path = Path(args.output)
    command = build_codex_exec_command(
        worktree_path=worktree_path,
        prompt_path=prompt_path,
        output_path=output_path,
        model=args.model,
    )
    _append_codex_command_runtime_event(
        slice_def=slice_def,
        command=command,
        worktree_path=worktree_path,
        prompt_path=prompt_path,
        output_path=output_path,
        model=args.model,
        created_at=timestamp(),
    )
    print("\n".join(command))
    return 0


def command_cloud_submit(args: argparse.Namespace) -> int:
    slice_def = _resolve_slice_arg(args.slice)
    prompt = build_worker_prompt(slice_def)
    command = build_cloud_exec_command(
        environment_id=args.env,
        branch=args.branch,
        prompt=prompt,
        attempts=args.attempts,
    )
    event_created_at = timestamp()
    _best_effort_cloud_submit_event_append(
        _append_cloud_submit_started_runtime_event,
        slice_def=slice_def,
        command=command,
        environment_id=args.env,
        branch=args.branch,
        attempts=args.attempts,
        created_at=event_created_at,
    )
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        _best_effort_cloud_submit_event_append(
            _append_cloud_submit_failure_runtime_event,
            slice_def=slice_def,
            command=command,
            environment_id=args.env,
            branch=args.branch,
            attempts=args.attempts,
            returncode=result.returncode,
            created_at=event_created_at,
        )
        return result.returncode
    _best_effort_cloud_submit_event_append(
        _append_cloud_submit_runtime_event,
        slice_def=slice_def,
        command=command,
        environment_id=args.env,
        branch=args.branch,
        attempts=args.attempts,
        returncode=result.returncode,
        created_at=event_created_at,
    )
    return 0


def command_gate(args: argparse.Namespace) -> int:
    slice_def = _resolve_slice_arg(args.slice)
    changed_files = args.changed_file or git_changed_files()
    diff_text = ""
    if args.diff_file:
        diff_text = Path(args.diff_file).read_text(encoding="utf-8")
    gate_path = write_gate_report(
        slice_def=slice_def,
        task_id=args.task_id,
        executor=args.executor,
        changed_files=changed_files,
        diff_text=diff_text,
        tests=args.tests or "",
        gate_dir=GATE_DIR,
    )
    print(_display_path(gate_path))
    return 0


def command_handoff(args: argparse.Namespace) -> int:
    slice_def = _resolve_slice_arg(args.slice)
    output_path = Path(args.output) if args.output else None
    if output_path is not None and not output_path.is_absolute():
        output_path = REPO_ROOT / output_path
    handoff_path = write_handoff(
        slice_def=slice_def,
        path=output_path,
        status=args.status,
        executor=args.executor,
        changed_files=args.changed_file,
        tests=args.tests or "",
        notes=args.note or [],
        next_action=args.next_action or "",
    )
    print(_display_path(handoff_path))
    return 0


def command_slice_status(args: argparse.Namespace) -> int:
    previous_status = write_slice_status(
        slice_id=args.slice,
        new_status=args.status,
        path=SLICES_FILE,
    )
    print(f"{args.slice}: {previous_status} -> {args.status}")
    return 0


def command_checkpoint(args: argparse.Namespace) -> int:
    output_path = Path(args.output) if args.output else CHECKPOINT_FILE
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path
    checkpoint_path = write_checkpoint(path=output_path, notes=args.note or [])
    print(_display_path(checkpoint_path))
    if args.print_text:
        print(checkpoint_path.read_text(encoding="utf-8"))
    return 0


def command_next_action(args: argparse.Namespace) -> int:
    slices = load_slices()
    ignored_active_slice_ids = set(args.ignore_active_slice or [])
    action = _lg8_no_todo_next_action_fast_path(
        slices,
        ignored_active_slice_ids=ignored_active_slice_ids,
    )
    if action is None:
        changed = git_changed_files()
        action = suggest_next_action(
            slices,
            ignored_active_slice_ids=ignored_active_slice_ids,
            selfdev_batch_risk_flags=detect_risk_flags(changed),
        )
    _append_next_action_runtime_event(action=action, created_at=timestamp())
    if args.json:
        print(json.dumps(action, indent=2, sort_keys=True))
    else:
        for line in _format_next_action(action):
            print(line)
    return 0


def command_verification_matrix(args: argparse.Namespace) -> int:
    payload = _selfdev_verification_matrix_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Matrix: {payload['matrix_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Public surface: {payload['public_surface']}")
    for entry in payload["commands"]:
        print(f"- {entry['id']}: {entry['purpose']}")
        print("  argv:")
        for arg in entry["argv"]:
            print(f"    - {arg}")
    return 0


def command_lg9_contract_matrix(args: argparse.Namespace) -> int:
    payload = _lg9_durable_contract_matrix_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Matrix: {payload['matrix_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Public surface: {payload['public_surface']}")
    for entry in payload["contracts"]:
        print(f"- {entry['id']}: {entry['evidence_state']}")
        print(f"  migration: {entry['migration_status']}")
        print(f"  stop before: {entry['stop_before']}")
    return 0


def command_lg9_provenance_artifact_contract(args: argparse.Namespace) -> int:
    payload = _lg9_provenance_artifact_contract_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Contract: {payload['contract_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Public surface: {payload['public_surface']}")
    print(f"Stop before: {payload['stop_before']}")
    for entry in payload["contract_nodes"]:
        print(f"- {entry['id']}: {entry['implementation_status']}")
        print(f"  mutation: {entry['mutation_policy']}")
    return 0


def command_lg9_orchestrator_readonly_contract(args: argparse.Namespace) -> int:
    payload = _lg9_orchestrator_readonly_contract_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Contract: {payload['contract_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Public surface: {payload['public_surface']}")
    print(f"Stop before: {payload['stop_before']}")
    for entry in payload["contract_nodes"]:
        print(f"- {entry['id']}: {entry['implementation_status']}")
        print(f"  mutation: {entry['mutation_policy']}")
    return 0


def command_durable_semantics(args: argparse.Namespace) -> int:
    payload = _durable_semantics_local_implementation_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Guard: {payload['guard_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Status: {payload['status']}")
    print(f"Schema source: {payload['schema_source']}")
    print(f"Schema migration required: {payload['schema_migration_required']}")
    print(f"Public surface: {payload['public_surface']}")
    for entry in payload["checks"]:
        print(f"- {entry['check_id']}: {entry['ok']}")
        if entry["missing"]:
            print(f"  missing: {', '.join(entry['missing'])}")
    return 0


def command_productization_zotero_local(args: argparse.Namespace) -> int:
    payload = _productization_zotero_local_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Component: {payload['component_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Status: {payload['status']}")
    print(f"Public payload shapes: {payload['public_payload_shapes']}")
    print(f"External actions: {payload['external_actions']}")
    print(f"Zotero: {payload['zotero']['classification']}")
    print(f"Zotero real sync: {payload['zotero_real_sync']}")
    return 0


def command_private_performance_governance(args: argparse.Namespace) -> int:
    payload = _private_performance_governance_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Governance: {payload['governance_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Status: {payload['status']}")
    print(f"Claim policy: {payload['claim_policy']}")
    print(f"Reports: {payload['report_count']}")
    print(f"Public claims: {payload['public_claim_status']}")
    print(f"Benchmark promotion: {payload['benchmark_promotion_status']}")
    return 0


def command_lg9_contract_guards(args: argparse.Namespace) -> int:
    payload = _lg9_contract_guard_productization_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Guard: {payload['guard_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Status: {payload['status']}")
    print(f"Public surface: {payload['public_surface']}")
    print(f"Stop before: {payload['stop_before']}")
    for entry in payload["guards"]:
        print(f"- {entry['id']}: {entry['classification']}")
        print(f"  mutation: {entry['mutation_policy']}")
    return 0


def command_lg8_lg9_closeout(args: argparse.Namespace) -> int:
    payload = _lg8_lg9_private_closeout_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Report: {payload['report_id']}")
    print(f"State: {payload['completion_state']}")
    print(f"LG10: {payload['lg10_status']}")
    print(f"Public surface: {payload['public_surface']}")
    print("LG8 evidence:")
    for entry in payload["lg8_hot_path_evidence"]:
        print(f"- {entry['slice_id']}: {entry['metric']}")
    print("LG9 contracts:")
    for entry in payload["lg9_contract_evidence"]:
        print(f"- {entry['slice_id']}: {entry['implementation_status']}")
    return 0


def command_lg10_productization_boundary(args: argparse.Namespace) -> int:
    payload = _lg10_public_productization_boundary_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Boundary: {payload['boundary_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"LG8/LG9 prerequisite: {payload['lg8_lg9_prerequisite']}")
    print(f"LG10: {payload['lg10_status']}")
    print(f"Allowed future pattern: {payload['allowed_future_pattern']}")
    print("Public surfaces:")
    for surface in payload["public_surfaces"]:
        print(f"- {surface}")
    print("Required evidence:")
    for entry in payload["required_pre_implementation_evidence"]:
        print(f"- {entry}")
    print("Stop before:")
    for boundary in payload["stop_before"]:
        print(f"- {boundary}")
    return 0


def command_batch_summary(args: argparse.Namespace) -> int:
    payload = _selfdev_fast_batch_summary()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Lane: {payload['lane_id']}")
    print(f"Batch slice: {payload['batch_slice_id']}")
    print(f"Protocol slice: {payload['protocol_slice_id']}")
    print(
        "Batch size: "
        f"default {payload['batch_size']['default']}, "
        f"actual {payload['batch_size']['actual']}, "
        f"max {payload['batch_size']['max']}"
    )
    print("Subtasks:")
    for subtask in payload["subtasks"]:
        print(f"- {subtask['slice_id']} ({subtask['category']}, {subtask['risk']})")
        for test in subtask["focused_tests"]:
            print(f"  focused: {test['id']}")
            print("  argv:")
            for arg in test["argv"]:
                print(f"    - {arg}")
    if payload["rejected_subtasks"]:
        print("Rejected subtasks:")
        for subtask in payload["rejected_subtasks"]:
            print(f"- {subtask['slice_id']}: {subtask['rejection_reason']}")
    print("Final matrix:")
    for entry in payload["final_matrix_commands"]:
        print(f"- {entry['id']}: {entry['purpose']}")
        print("  argv:")
        for arg in entry["argv"]:
            print(f"    - {arg}")
    return 0


def command_closeout_matrix(args: argparse.Namespace) -> int:
    payload = _selfdev_closeout_matrix_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Matrix: {payload['matrix_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Slice: {payload['slice_id']}")
    print(f"Public surface: {payload['public_surface']}")
    print("Tracks:")
    for track in payload["tracks"]:
        print(
            f"- {track['id']}: "
            f"{track['current_percent_estimate']}% -> "
            f"{track['target_percent']}%"
        )
        for requirement in track["requirements"]:
            print(f"  - {requirement['id']}: {requirement['status']}")
    print("Next low-risk slices:")
    for slice_def in payload["next_low_risk_slices"]:
        print(f"- {slice_def['slice_id']}: {slice_def['objective']}")
    print("Gate boundaries:")
    for boundary in payload["gate_boundaries"]:
        print(f"- {boundary['id']}: {boundary['stop_before']}")
    print("Verification:")
    for entry in payload["verification_commands"]:
        print(f"- {entry['id']}: {entry['purpose']}")
        print("  argv:")
        for arg in entry["argv"]:
            print(f"    - {arg}")
    return 0


def command_runtime_selfdev_tooling(args: argparse.Namespace) -> int:
    payload = _runtime_selfdev_tooling_stable_components_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Components: {payload['component_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Status: {payload['status']}")
    print(f"Public surface: {payload['public_surface']}")
    print(f"Stop before: {payload['stop_before']}")
    for entry in payload["components"]:
        print(f"- {entry['id']}: {entry['classification']}")
        print(f"  mutation: {entry['mutation_policy']}")
    print("Deferred:")
    for entry in payload["deferred"]:
        print(f"- {entry['id']}: {entry['reason']}")
    print("Verification:")
    for entry in payload["verification_commands"]:
        print(f"- {entry['id']}: {entry['purpose']}")
        print("  argv:")
        for arg in entry["argv"]:
            print(f"    - {arg}")
    return 0


def command_non_benchmark_closeout(args: argparse.Namespace) -> int:
    payload = _non_benchmark_stabilization_closeout_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Report: {payload['report_id']}")
    print(f"Scope: {payload['scope']}")
    print(f"Status: {payload['status']}")
    print("Classifications:")
    for entry in payload["classifications"]:
        print(f"- {entry['slice_id']}: {entry['classification']} ({entry['decision']})")
    print("Excluded work:")
    for entry in payload["excluded_work"]:
        print(f"- {entry}")
    print("Verification:")
    for entry in payload["verification_commands"]:
        print(f"- {entry['id']}: {entry['purpose']}")
        print("  argv:")
        for arg in entry["argv"]:
            print(f"    - {arg}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Research Harness self-development orchestration helper."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show next slice and risk state.")
    status.set_defaults(func=command_status)

    next_action = subparsers.add_parser(
        "next-action", help="Print the next safe self-development action."
    )
    next_action.add_argument("--json", action="store_true")
    next_action.add_argument(
        "--ignore-active-slice",
        action="append",
        default=[],
        help="Ignore an active slice owned by another session.",
    )
    next_action.set_defaults(func=command_next_action)

    verification_matrix = subparsers.add_parser(
        "verification-matrix",
        help="Print the private runtime-event self-dev verification matrix.",
    )
    verification_matrix.add_argument("--json", action="store_true")
    verification_matrix.set_defaults(func=command_verification_matrix)

    lg9_contract_matrix = subparsers.add_parser(
        "lg9-contract-matrix",
        help="Print the private LG9 durable contract matrix.",
    )
    lg9_contract_matrix.add_argument("--json", action="store_true")
    lg9_contract_matrix.set_defaults(func=command_lg9_contract_matrix)

    lg9_provenance_artifact_contract = subparsers.add_parser(
        "lg9-provenance-artifact-contract",
        help="Print the private LG9 provenance/artifact linkage contract.",
    )
    lg9_provenance_artifact_contract.add_argument("--json", action="store_true")
    lg9_provenance_artifact_contract.set_defaults(
        func=command_lg9_provenance_artifact_contract
    )

    lg9_orchestrator_readonly_contract = subparsers.add_parser(
        "lg9-orchestrator-readonly-contract",
        help="Print the private LG9 orchestrator read-only mapping contract.",
    )
    lg9_orchestrator_readonly_contract.add_argument("--json", action="store_true")
    lg9_orchestrator_readonly_contract.set_defaults(
        func=command_lg9_orchestrator_readonly_contract
    )

    durable_semantics = subparsers.add_parser(
        "durable-semantics",
        help="Print executable local durable semantics diagnostics.",
    )
    durable_semantics.add_argument("--json", action="store_true")
    durable_semantics.set_defaults(func=command_durable_semantics)

    productization_zotero_local = subparsers.add_parser(
        "productization-zotero-local",
        help="Print stable local productization/Zotero dry-run diagnostics.",
    )
    productization_zotero_local.add_argument("--json", action="store_true")
    productization_zotero_local.set_defaults(func=command_productization_zotero_local)

    private_performance_governance = subparsers.add_parser(
        "private-performance-governance",
        help="Print private benchmark/performance governance diagnostics.",
    )
    private_performance_governance.add_argument("--json", action="store_true")
    private_performance_governance.set_defaults(
        func=command_private_performance_governance
    )

    lg9_contract_guards = subparsers.add_parser(
        "lg9-contract-guards",
        help="Print the private ST05 LG9 internal guard report.",
    )
    lg9_contract_guards.add_argument("--json", action="store_true")
    lg9_contract_guards.set_defaults(func=command_lg9_contract_guards)

    lg8_lg9_closeout = subparsers.add_parser(
        "lg8-lg9-closeout",
        help="Print the private LG8/LG9 closeout report.",
    )
    lg8_lg9_closeout.add_argument("--json", action="store_true")
    lg8_lg9_closeout.set_defaults(func=command_lg8_lg9_closeout)

    lg10_productization_boundary = subparsers.add_parser(
        "lg10-productization-boundary",
        help="Print the private LG10 public-productization gate boundary.",
    )
    lg10_productization_boundary.add_argument("--json", action="store_true")
    lg10_productization_boundary.set_defaults(func=command_lg10_productization_boundary)

    batch_summary = subparsers.add_parser(
        "batch-summary",
        help="Print the private self-dev fast batch lane summary.",
    )
    batch_summary.add_argument("--json", action="store_true")
    batch_summary.set_defaults(func=command_batch_summary)

    closeout_matrix = subparsers.add_parser(
        "closeout-matrix",
        help="Print the private self-dev/runtime-shell closeout objective matrix.",
    )
    closeout_matrix.add_argument("--json", action="store_true")
    closeout_matrix.set_defaults(func=command_closeout_matrix)

    runtime_selfdev_tooling = subparsers.add_parser(
        "runtime-selfdev-tooling",
        help="Print the private ST07 runtime/self-dev tooling stabilization report.",
    )
    runtime_selfdev_tooling.add_argument("--json", action="store_true")
    runtime_selfdev_tooling.set_defaults(func=command_runtime_selfdev_tooling)

    non_benchmark_closeout = subparsers.add_parser(
        "non-benchmark-closeout",
        help="Print the private LG11 non-benchmark stabilization closeout.",
    )
    non_benchmark_closeout.add_argument("--json", action="store_true")
    non_benchmark_closeout.set_defaults(func=command_non_benchmark_closeout)

    prompt = subparsers.add_parser("prompt", help="Write worker prompt for a slice.")
    prompt.add_argument("slice", nargs="?", default="next")
    prompt.set_defaults(func=command_prompt)

    cloud_command = subparsers.add_parser(
        "cloud-command", help="Print argv lines for a cloud task submission."
    )
    cloud_command.add_argument("slice", nargs="?", default="next")
    cloud_command.add_argument("--env", required=True)
    cloud_command.add_argument("--branch", required=True)
    cloud_command.add_argument("--attempts", type=int, default=1)
    cloud_command.set_defaults(func=command_cloud_command)

    codex_command = subparsers.add_parser(
        "codex-command", help="Print argv lines for a local codex exec task."
    )
    codex_command.add_argument("slice", nargs="?", default="next")
    codex_command.add_argument("--worktree", required=True)
    codex_command.add_argument("--prompt-path", required=True)
    codex_command.add_argument("--output", required=True)
    codex_command.add_argument("--model")
    codex_command.set_defaults(func=command_codex_command)

    cloud_submit = subparsers.add_parser(
        "cloud-submit", help="Submit a cloud task for a slice."
    )
    cloud_submit.add_argument("slice", nargs="?", default="next")
    cloud_submit.add_argument("--env", required=True)
    cloud_submit.add_argument("--branch", required=True)
    cloud_submit.add_argument("--attempts", type=int, default=1)
    cloud_submit.set_defaults(func=command_cloud_submit)

    gate = subparsers.add_parser("gate", help="Write a human gate report.")
    gate.add_argument("slice", nargs="?", default="next")
    gate.add_argument("--task-id")
    gate.add_argument("--executor", default="manual")
    gate.add_argument("--diff-file")
    gate.add_argument("--tests")
    gate.add_argument("--changed-file", action="append")
    gate.set_defaults(func=command_gate)

    handoff = subparsers.add_parser("handoff", help="Write a self-dev handoff.")
    handoff.add_argument("slice", nargs="?", default="next")
    handoff.add_argument("--output")
    handoff.add_argument("--status", default="done", choices=sorted(VALID_STATUSES))
    handoff.add_argument("--executor", default="codex")
    handoff.add_argument("--changed-file", action="append")
    handoff.add_argument("--tests")
    handoff.add_argument("--note", action="append")
    handoff.add_argument("--next-action")
    handoff.set_defaults(func=command_handoff)

    slice_status = subparsers.add_parser(
        "slice-status", help="Update one self-dev slice status."
    )
    slice_status.add_argument("slice")
    slice_status.add_argument("status", choices=sorted(VALID_STATUSES))
    slice_status.set_defaults(func=command_slice_status)

    checkpoint = subparsers.add_parser(
        "checkpoint", help="Write resumable state before clearing context."
    )
    checkpoint.add_argument("--output")
    checkpoint.add_argument("--note", action="append")
    checkpoint.add_argument("--print", dest="print_text", action="store_true")
    checkpoint.set_defaults(func=command_checkpoint)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except GatePendingError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
