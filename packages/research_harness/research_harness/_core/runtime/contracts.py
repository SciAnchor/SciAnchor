"""Contract models for the Research Harness runtime rebuild.

These models are intentionally pure and storage-free. They define the typed
interfaces that future CLI, MCP, HTTP, runtime, eval, and skill-evolution layers
can share without depending on the legacy skill surface.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any


RUN_SPEC_SCHEMA_VERSION = "rh.run.v0"
RUN_TRACE_SCHEMA_VERSION = "rh.trace.v0"


class TaskType(str, Enum):
    RETRIEVAL = "retrieval"
    ANALYSIS = "analysis"
    WRITING = "writing"
    RENDERING = "rendering"
    EVALUATION = "evaluation"
    EVOLUTION = "evolution"


class CapabilityType(str, Enum):
    PRIMITIVE = "primitive"
    SKILL = "skill"
    ADAPTER = "adapter"
    EVALUATOR = "evaluator"


class CapabilityOwner(str, Enum):
    CORE = "core"
    EXTERNAL = "external"
    PRO = "pro"


class GuardrailScope(str, Enum):
    INPUT = "input"
    TOOL = "tool"
    OUTPUT = "output"


class GuardrailSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class RunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"


class TraceStepKind(str, Enum):
    STAGE_EVENT = "stage_event"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    GUARDRAIL = "guardrail"
    ARTIFACT_WRITE = "artifact_write"
    JUDGE = "judge"
    HANDOFF = "handoff"


class TraceStepStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"


_UNKNOWN_LICENSE_VALUES = {"", "unknown", "noassertion", "none", "n/a"}


def _coerce_enum(value: Any, enum_type: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(
            f"unknown {field_name}: {value!r}; allowed: {allowed}"
        ) from exc


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return dict(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _find_forbidden_keys(
    payload: Any,
    forbidden: set[str],
    *,
    path: str = "",
) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_str = str(key)
            current = f"{path}.{key_str}" if path else key_str
            if key_str in forbidden:
                found.append(current)
            found.extend(_find_forbidden_keys(value, forbidden, path=current))
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            current = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(_find_forbidden_keys(value, forbidden, path=current))
    return tuple(found)


@dataclass(frozen=True)
class RunVisibleInputs:
    """Inputs the runtime may expose to a capability."""

    user_brief: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    literal_inputs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_brief", _dict(self.user_brief))
        object.__setattr__(
            self,
            "artifact_refs",
            tuple(str(item) for item in _tuple(self.artifact_refs)),
        )
        object.__setattr__(self, "literal_inputs", _dict(self.literal_inputs))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RunSpec:
    """Stable contract for one RH runtime operation."""

    run_id: str
    task_type: TaskType | str
    topic_id: int
    objective: str
    schema_version: str = RUN_SPEC_SCHEMA_VERSION
    project_id: int | None = None
    visible_inputs: RunVisibleInputs = field(default_factory=RunVisibleInputs)
    forbidden_inputs: tuple[str, ...] = ()
    required_outputs: tuple[str, ...] = ()
    capability_policy: dict[str, Any] = field(default_factory=dict)
    guardrails: dict[str, Any] = field(default_factory=dict)
    trace_policy: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != RUN_SPEC_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported RunSpec schema_version: {self.schema_version}"
            )
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.objective:
            raise ValueError("objective is required")
        if self.topic_id <= 0:
            raise ValueError("topic_id must be positive")
        if self.project_id is not None and self.project_id <= 0:
            raise ValueError("project_id must be positive when provided")

        object.__setattr__(
            self, "task_type", _coerce_enum(self.task_type, TaskType, "task_type")
        )
        if not isinstance(self.visible_inputs, RunVisibleInputs):
            object.__setattr__(
                self,
                "visible_inputs",
                RunVisibleInputs(**_dict(self.visible_inputs)),
            )
        object.__setattr__(
            self,
            "forbidden_inputs",
            tuple(str(item) for item in _tuple(self.forbidden_inputs)),
        )
        object.__setattr__(
            self,
            "required_outputs",
            tuple(str(item) for item in _tuple(self.required_outputs)),
        )
        object.__setattr__(self, "capability_policy", _dict(self.capability_policy))
        object.__setattr__(self, "guardrails", _dict(self.guardrails))
        object.__setattr__(self, "trace_policy", _dict(self.trace_policy))
        self._validate_forbidden_visible_inputs()

    def _validate_forbidden_visible_inputs(self) -> None:
        forbidden = {item for item in self.forbidden_inputs if item}
        if not forbidden:
            return
        found = _find_forbidden_keys(
            self.visible_inputs.user_brief, forbidden
        ) + _find_forbidden_keys(self.visible_inputs.literal_inputs, forbidden)
        if found:
            raise ValueError(
                "forbidden visible input present: " + ", ".join(sorted(found))
            )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))

    def stable_hash(self) -> str:
        return _stable_hash(self.to_dict())


@dataclass(frozen=True)
class GuardrailResult:
    """Result of one runtime guardrail check."""

    name: str
    scope: GuardrailScope | str
    passed: bool
    severity: GuardrailSeverity | str = GuardrailSeverity.INFO
    tripwire_triggered: bool | None = None
    checked_refs: tuple[str, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("guardrail name is required")
        object.__setattr__(
            self, "scope", _coerce_enum(self.scope, GuardrailScope, "scope")
        )
        object.__setattr__(
            self,
            "severity",
            _coerce_enum(self.severity, GuardrailSeverity, "severity"),
        )
        object.__setattr__(
            self,
            "checked_refs",
            tuple(str(item) for item in _tuple(self.checked_refs)),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_dict(item) for item in _tuple(self.diagnostics)),
        )
        if self.tripwire_triggered is None:
            object.__setattr__(
                self,
                "tripwire_triggered",
                (not self.passed) and self.severity == GuardrailSeverity.BLOCKING,
            )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class CapabilityManifest:
    """Machine-readable registration contract for a runtime capability."""

    name: str
    version: str
    capability_type: CapabilityType | str
    owner: CapabilityOwner | str
    license: str
    input_schema: str
    output_schema: str
    source_url: str = ""
    source_commit: str = ""
    allowed_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    required_artifacts: tuple[str, ...] = ()
    produced_artifacts: tuple[str, ...] = ()
    guardrails: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    eval_profiles: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("capability name is required")
        if not self.version:
            raise ValueError("capability version is required")
        if not self.input_schema:
            raise ValueError("input_schema is required")
        if not self.output_schema:
            raise ValueError("output_schema is required")
        object.__setattr__(
            self,
            "capability_type",
            _coerce_enum(self.capability_type, CapabilityType, "capability_type"),
        )
        object.__setattr__(
            self, "owner", _coerce_enum(self.owner, CapabilityOwner, "owner")
        )
        license_value = self.license.strip()
        object.__setattr__(self, "license", license_value)
        for field_name in (
            "allowed_tools",
            "forbidden_tools",
            "required_artifacts",
            "produced_artifacts",
            "guardrails",
            "tests",
            "eval_profiles",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(str(item) for item in _tuple(getattr(self, field_name))),
            )
        object.__setattr__(self, "metadata", _dict(self.metadata))
        self._validate_external_attribution()

    def _validate_external_attribution(self) -> None:
        if self.owner != CapabilityOwner.EXTERNAL:
            return
        if not self.source_url:
            raise ValueError("external capability requires source_url attribution")
        if self.license.lower() in _UNKNOWN_LICENSE_VALUES:
            raise ValueError("external capability requires a known license")

    def validate_run_spec(
        self,
        spec: RunSpec,
        *,
        requested_tools: tuple[str, ...] | list[str] | None = None,
    ) -> tuple[GuardrailResult, ...]:
        """Validate that a RunSpec is allowed to invoke this capability."""

        effective_tools = set(
            _tuple(
                requested_tools
                if requested_tools is not None
                else spec.capability_policy.get("allowed_tools")
            )
        )
        denied_tools = set(_tuple(spec.capability_policy.get("denied_tools")))
        allowed_capabilities = set(
            _tuple(spec.capability_policy.get("allowed_capabilities"))
        )
        visible_artifact_types = _visible_artifact_types(spec.visible_inputs)
        declared_outputs = set(spec.required_outputs)
        declared_guardrails = _declared_guardrails(spec.guardrails)

        allowed_tool_extra = tuple(
            sorted(
                str(tool)
                for tool in effective_tools
                if self.allowed_tools and str(tool) not in self.allowed_tools
            )
        )
        forbidden_tool_hits = tuple(
            sorted(
                str(tool)
                for tool in effective_tools
                if str(tool)
                in set(self.forbidden_tools) | {str(t) for t in denied_tools}
            )
        )
        missing_artifacts = tuple(
            sorted(
                artifact
                for artifact in self.required_artifacts
                if artifact not in visible_artifact_types
            )
        )
        missing_outputs = tuple(
            sorted(
                artifact
                for artifact in self.produced_artifacts
                if artifact not in declared_outputs
            )
        )
        missing_guardrails = tuple(
            sorted(
                guardrail
                for guardrail in self.guardrails
                if guardrail not in declared_guardrails
            )
        )
        capability_allowed = not allowed_capabilities or self.name in {
            str(item) for item in allowed_capabilities
        }

        return (
            GuardrailResult(
                name="capability_allowed",
                scope=GuardrailScope.INPUT,
                passed=capability_allowed,
                severity=GuardrailSeverity.BLOCKING,
                checked_refs=(self.name,),
                diagnostics=(
                    {
                        "allowed_capabilities": tuple(
                            sorted(str(item) for item in allowed_capabilities)
                        ),
                    },
                ),
            ),
            GuardrailResult(
                name="capability_allowed_tools",
                scope=GuardrailScope.TOOL,
                passed=not allowed_tool_extra,
                severity=GuardrailSeverity.BLOCKING,
                checked_refs=tuple(sorted(str(item) for item in effective_tools)),
                diagnostics=({"extra": allowed_tool_extra},),
            ),
            GuardrailResult(
                name="capability_forbidden_tools",
                scope=GuardrailScope.TOOL,
                passed=not forbidden_tool_hits,
                severity=GuardrailSeverity.BLOCKING,
                checked_refs=tuple(sorted(str(item) for item in effective_tools)),
                diagnostics=({"forbidden": forbidden_tool_hits},),
            ),
            GuardrailResult(
                name="capability_required_artifacts",
                scope=GuardrailScope.INPUT,
                passed=not missing_artifacts,
                severity=GuardrailSeverity.BLOCKING,
                checked_refs=tuple(sorted(visible_artifact_types)),
                diagnostics=({"missing": missing_artifacts},),
            ),
            GuardrailResult(
                name="capability_required_outputs",
                scope=GuardrailScope.OUTPUT,
                passed=not missing_outputs,
                severity=GuardrailSeverity.BLOCKING,
                checked_refs=tuple(sorted(declared_outputs)),
                diagnostics=({"missing": missing_outputs},),
            ),
            GuardrailResult(
                name="capability_required_guardrails",
                scope=GuardrailScope.OUTPUT,
                passed=not missing_guardrails,
                severity=GuardrailSeverity.BLOCKING,
                checked_refs=tuple(sorted(declared_guardrails)),
                diagnostics=({"missing": missing_guardrails},),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


def _visible_artifact_types(visible_inputs: RunVisibleInputs) -> set[str]:
    out: set[str] = set()
    for ref in visible_inputs.artifact_refs:
        parts = ref.split(":")
        if len(parts) >= 3 and parts[0] == "artifact":
            out.add(parts[1])
        elif ref:
            out.add(ref)
    return out


def _declared_guardrails(guardrails: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for value in guardrails.values():
        for item in _tuple(value):
            if isinstance(item, dict):
                name = item.get("name")
                if name:
                    out.add(str(name))
            elif item:
                out.add(str(item))
    return out


@dataclass(frozen=True)
class ArtifactLineage:
    """Source references consumed by an artifact."""

    source_artifact_ids: tuple[int, ...] = ()
    source_paper_ids: tuple[int, ...] = ()
    source_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_artifact_ids",
            tuple(int(item) for item in _tuple(self.source_artifact_ids)),
        )
        object.__setattr__(
            self,
            "source_paper_ids",
            tuple(int(item) for item in _tuple(self.source_paper_ids)),
        )
        object.__setattr__(
            self,
            "source_claim_ids",
            tuple(str(item) for item in _tuple(self.source_claim_ids)),
        )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class ArtifactValidation:
    """Validation summary attached to an artifact envelope."""

    schema_valid: bool
    guardrail_results: tuple[GuardrailResult, ...] = ()
    judge_results: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        guardrails: list[GuardrailResult] = []
        for item in _tuple(self.guardrail_results):
            if isinstance(item, GuardrailResult):
                guardrails.append(item)
            else:
                guardrails.append(GuardrailResult(**_dict(item)))
        object.__setattr__(self, "guardrail_results", tuple(guardrails))
        object.__setattr__(
            self,
            "judge_results",
            tuple(_dict(item) for item in _tuple(self.judge_results)),
        )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class ArtifactEnvelope:
    """Typed artifact payload plus lineage and validation state."""

    artifact_id: int
    artifact_type: str
    schema_version: str
    topic_id: int
    run_id: str
    payload: dict[str, Any]
    project_id: int | None = None
    producer: dict[str, Any] = field(default_factory=dict)
    lineage: ArtifactLineage = field(default_factory=ArtifactLineage)
    validation: ArtifactValidation = field(
        default_factory=lambda: ArtifactValidation(schema_valid=False)
    )
    staleness: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.artifact_id <= 0:
            raise ValueError("artifact_id must be positive")
        if not self.artifact_type:
            raise ValueError("artifact_type is required")
        if not self.schema_version:
            raise ValueError("schema_version is required")
        if self.topic_id <= 0:
            raise ValueError("topic_id must be positive")
        if not self.run_id:
            raise ValueError("run_id is required")
        object.__setattr__(self, "payload", _dict(self.payload))
        object.__setattr__(self, "producer", _dict(self.producer))
        if not isinstance(self.lineage, ArtifactLineage):
            object.__setattr__(self, "lineage", ArtifactLineage(**_dict(self.lineage)))
        if not isinstance(self.validation, ArtifactValidation):
            object.__setattr__(
                self,
                "validation",
                ArtifactValidation(**_dict(self.validation)),
            )
        object.__setattr__(self, "staleness", _dict(self.staleness))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class TraceStep:
    """One event inside a runtime trace."""

    step_id: str
    kind: TraceStepKind | str
    status: TraceStepStatus | str
    started_at: str = ""
    finished_at: str = ""
    input_ref: str | None = None
    output_ref: str | None = None
    cost_usd: float | None = None
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("step_id is required")
        object.__setattr__(self, "kind", _coerce_enum(self.kind, TraceStepKind, "kind"))
        object.__setattr__(
            self, "status", _coerce_enum(self.status, TraceStepStatus, "status")
        )
        if self.cost_usd is not None and self.cost_usd < 0:
            raise ValueError("cost_usd cannot be negative")
        object.__setattr__(self, "metadata", _dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class RunTrace:
    """End-to-end record of one RH runtime attempt."""

    run_id: str
    task_id: str
    status: RunStatus | str
    schema_version: str = RUN_TRACE_SCHEMA_VERSION
    trial_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    steps: tuple[TraceStep, ...] = ()
    outputs: dict[str, Any] = field(default_factory=dict)
    costs: dict[str, Any] = field(default_factory=dict)
    errors: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != RUN_TRACE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported RunTrace schema_version: {self.schema_version}"
            )
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.task_id:
            raise ValueError("task_id is required")
        object.__setattr__(
            self, "status", _coerce_enum(self.status, RunStatus, "status")
        )
        object.__setattr__(self, "inputs", _dict(self.inputs))
        steps: list[TraceStep] = []
        for item in _tuple(self.steps):
            if isinstance(item, TraceStep):
                steps.append(item)
            else:
                steps.append(TraceStep(**_dict(item)))
        object.__setattr__(self, "steps", tuple(steps))
        object.__setattr__(self, "outputs", _dict(self.outputs))
        object.__setattr__(self, "costs", _dict(self.costs))
        object.__setattr__(
            self, "errors", tuple(_dict(item) for item in _tuple(self.errors))
        )

    @classmethod
    def from_spec(
        cls,
        spec: RunSpec,
        *,
        task_id: str,
        status: RunStatus | str,
        trial_id: str = "",
        steps: tuple[TraceStep, ...] = (),
        output_artifact_ids: tuple[int, ...] = (),
        errors: tuple[dict[str, Any], ...] = (),
    ) -> "RunTrace":
        total_cost = round(
            sum(step.cost_usd or 0.0 for step in steps),
            10,
        )
        return cls(
            run_id=spec.run_id,
            task_id=task_id,
            trial_id=trial_id,
            status=status,
            inputs={
                "run_spec_hash": spec.stable_hash(),
                "visible_artifact_refs": list(spec.visible_inputs.artifact_refs),
            },
            steps=steps,
            outputs={"artifact_ids": tuple(int(item) for item in output_artifact_ids)},
            costs={"total_usd": total_cost},
            errors=errors,
        )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))
