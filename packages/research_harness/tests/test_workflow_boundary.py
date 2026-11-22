from __future__ import annotations

import importlib
import sys


WORKFLOW_EXECUTION_MODULES = (
    "backend",
    "prompts",
    "writing_checks",
    "writing_rigor",
    "dag_reasoning",
    "claim_verification",
    "compiled_summary",
    "harness_actions",
    "loops",
    "fal_image_client",
    "latex_compiler",
    "local",
    "harness",
    "tracked",
    "claude_code",
    "factory",
    "llm_primitives",
)

WORKFLOW_ORCHESTRATOR_MODULES = (
    "adversarial",
    "artifacts",
    "claims",
    "integrity",
    "invariants",
    "judge",
    "models",
    "review",
    "serializers",
    "service",
    "snapshots",
    "stages",
    "transitions",
)


def test_execution_public_modules_alias_workflow_canonical_modules() -> None:
    public_execution_package = importlib.import_module("research_harness.execution")

    for module_name in WORKFLOW_EXECUTION_MODULES:
        public_name = f"research_harness.execution.{module_name}"
        canonical_name = f"research_harness._workflow.execution.{module_name}"

        public_module = importlib.import_module(public_name)
        canonical_module = importlib.import_module(canonical_name)

        assert public_module is canonical_module
        assert sys.modules[public_name] is canonical_module
        assert getattr(public_execution_package, module_name) is canonical_module


def test_orchestrator_public_modules_alias_workflow_canonical_modules() -> None:
    public_orchestrator_package = importlib.import_module(
        "research_harness.orchestrator"
    )

    for module_name in WORKFLOW_ORCHESTRATOR_MODULES:
        public_name = f"research_harness.orchestrator.{module_name}"
        canonical_name = f"research_harness._workflow.orchestrator.{module_name}"

        public_module = importlib.import_module(public_name)
        canonical_module = importlib.import_module(canonical_name)

        assert public_module is canonical_module
        assert sys.modules[public_name] is canonical_module
        assert getattr(public_orchestrator_package, module_name) is canonical_module


def test_execution_backend_has_workflow_canonical_path() -> None:
    from research_harness._workflow.execution.backend import BackendInfo
    from research_harness._workflow.execution.backend import ExecutionBackend
    from research_harness._workflow.execution.backend import PrimitiveResult
    from research_harness.execution.backend import BackendInfo as PublicBackendInfo
    from research_harness.execution.backend import (
        ExecutionBackend as PublicExecutionBackend,
    )
    from research_harness.execution.backend import (
        PrimitiveResult as PublicPrimitiveResult,
    )

    assert PublicBackendInfo is BackendInfo
    assert PublicExecutionBackend is ExecutionBackend
    assert PublicPrimitiveResult is PrimitiveResult


def test_execution_prompts_have_workflow_canonical_path() -> None:
    from research_harness._workflow.execution.prompts import direction_ranking_prompt
    from research_harness._workflow.execution.prompts import paper_summarize_prompt
    from research_harness.execution.prompts import (
        direction_ranking_prompt as public_direction_ranking_prompt,
    )
    from research_harness.execution.prompts import (
        paper_summarize_prompt as public_paper_summarize_prompt,
    )

    assert public_direction_ranking_prompt is direction_ranking_prompt
    assert public_paper_summarize_prompt is paper_summarize_prompt


def test_execution_writing_checks_have_workflow_canonical_path() -> None:
    from research_harness._workflow.execution.writing_checks import REVIEW_DIMENSIONS
    from research_harness._workflow.execution.writing_checks import run_all_checks
    from research_harness.execution.writing_checks import (
        REVIEW_DIMENSIONS as public_review_dimensions,
    )
    from research_harness.execution.writing_checks import (
        run_all_checks as public_run_all_checks,
    )

    assert public_review_dimensions is REVIEW_DIMENSIONS
    assert public_run_all_checks is run_all_checks


def test_execution_dag_reasoning_has_workflow_canonical_path() -> None:
    from research_harness._workflow.execution.dag_reasoning import DAGGap
    from research_harness._workflow.execution.dag_reasoning import gap_detect_dag
    from research_harness.execution.dag_reasoning import DAGGap as PublicDAGGap
    from research_harness.execution.dag_reasoning import (
        gap_detect_dag as public_gap_detect_dag,
    )

    assert PublicDAGGap is DAGGap
    assert public_gap_detect_dag is gap_detect_dag


def test_execution_claim_verification_has_workflow_canonical_path() -> None:
    from research_harness._workflow.execution.claim_verification import (
        ClaimVerificationResult,
    )
    from research_harness._workflow.execution.claim_verification import verify_claims
    from research_harness.execution.claim_verification import (
        ClaimVerificationResult as PublicClaimVerificationResult,
    )
    from research_harness.execution.claim_verification import (
        verify_claims as public_verify_claims,
    )

    assert PublicClaimVerificationResult is ClaimVerificationResult
    assert public_verify_claims is verify_claims


def test_execution_compiled_summary_has_workflow_canonical_path() -> None:
    from research_harness._workflow.execution.compiled_summary import COMPILED_FIELDS
    from research_harness._workflow.execution.compiled_summary import (
        ensure_compiled_summary,
    )
    from research_harness.execution.compiled_summary import (
        COMPILED_FIELDS as public_compiled_fields,
    )
    from research_harness.execution.compiled_summary import (
        ensure_compiled_summary as public_ensure_compiled_summary,
    )

    assert public_compiled_fields is COMPILED_FIELDS
    assert public_ensure_compiled_summary is ensure_compiled_summary
