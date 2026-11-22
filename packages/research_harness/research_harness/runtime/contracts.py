"""Compatibility shim for core runtime contract models."""

from __future__ import annotations

from research_harness._core.runtime.contracts import (
    RUN_SPEC_SCHEMA_VERSION,
    RUN_TRACE_SCHEMA_VERSION,
    ArtifactEnvelope,
    ArtifactLineage,
    ArtifactValidation,
    CapabilityManifest,
    CapabilityOwner,
    CapabilityType,
    GuardrailResult,
    GuardrailScope,
    GuardrailSeverity,
    RunSpec,
    RunStatus,
    RunTrace,
    RunVisibleInputs,
    TaskType,
    TraceStep,
    TraceStepKind,
    TraceStepStatus,
)

__all__ = [
    "RUN_SPEC_SCHEMA_VERSION",
    "RUN_TRACE_SCHEMA_VERSION",
    "ArtifactEnvelope",
    "ArtifactLineage",
    "ArtifactValidation",
    "CapabilityManifest",
    "CapabilityOwner",
    "CapabilityType",
    "GuardrailResult",
    "GuardrailScope",
    "GuardrailSeverity",
    "RunSpec",
    "RunStatus",
    "RunTrace",
    "RunVisibleInputs",
    "TaskType",
    "TraceStep",
    "TraceStepKind",
    "TraceStepStatus",
]
