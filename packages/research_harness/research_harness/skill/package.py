"""v2 skill package loader.

The legacy skill manifest indexes ``SKILL.md`` for agent discovery. This module
loads optional ``skill.yaml`` files for promoted RH skills that also need
runtime-facing contracts, guardrails, replay tests, and promotion policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from research_harness.runtime import CapabilityManifest, RunSpec, RunVisibleInputs

from .manifest import DEFAULT_SKILLS_DIRNAME, _parse_frontmatter

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - package validation requires PyYAML
    yaml = None  # type: ignore


SKILL_PACKAGE_FILENAME = "skill.yaml"
SKILL_PACKAGE_SCHEMA_VERSION = "rh.skill.v2"

_REQUIRED_KEYS = {
    "name",
    "version",
    "license",
    "capability_type",
    "description",
    "input_schema",
    "output_schema",
    "allowed_tools",
    "required_artifacts",
    "guardrails",
    "replay_tests",
    "promotion_policy",
}


@dataclass(frozen=True)
class SkillPackageManifest:
    """Machine-readable contract for a promoted skill package."""

    skill_dir: Path
    schema_version: str
    name: str
    version: str
    license: str
    capability_type: str
    description: str
    input_schema: str
    output_schema: str
    allowed_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    required_artifacts: tuple[str, ...] = ()
    optional_artifacts: tuple[str, ...] = ()
    produced_artifacts: tuple[str, ...] = ()
    guardrails: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    replay_tests: tuple[Mapping[str, Any], ...] = ()
    promotion_policy: Mapping[str, Any] = field(default_factory=dict)
    contract_paths: Mapping[str, Path] = field(default_factory=dict)
    source_attribution: Mapping[str, Any] = field(default_factory=dict)
    memory_policy: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill_dir", self.skill_dir.resolve())
        object.__setattr__(self, "version", str(self.version))
        object.__setattr__(self, "allowed_tools", _string_tuple(self.allowed_tools))
        object.__setattr__(self, "forbidden_tools", _string_tuple(self.forbidden_tools))
        object.__setattr__(
            self, "required_artifacts", _string_tuple(self.required_artifacts)
        )
        object.__setattr__(
            self, "optional_artifacts", _string_tuple(self.optional_artifacts)
        )
        object.__setattr__(
            self, "produced_artifacts", _string_tuple(self.produced_artifacts)
        )
        guardrails = {
            str(scope): _string_tuple(values)
            for scope, values in dict(self.guardrails).items()
        }
        object.__setattr__(self, "guardrails", MappingProxyType(guardrails))
        replay_tests = tuple(MappingProxyType(dict(item)) for item in self.replay_tests)
        object.__setattr__(self, "replay_tests", replay_tests)
        object.__setattr__(
            self, "promotion_policy", MappingProxyType(dict(self.promotion_policy))
        )
        contract_paths = {
            str(name): Path(path) for name, path in dict(self.contract_paths).items()
        }
        object.__setattr__(self, "contract_paths", MappingProxyType(contract_paths))
        object.__setattr__(
            self, "source_attribution", MappingProxyType(dict(self.source_attribution))
        )
        object.__setattr__(
            self, "memory_policy", MappingProxyType(dict(self.memory_policy))
        )
        object.__setattr__(self, "raw", MappingProxyType(dict(self.raw)))

    def to_capability_manifest(self) -> CapabilityManifest:
        """Convert the skill package into a runtime capability manifest."""

        replay_test_ids = tuple(
            str(test.get("id"))
            for test in self.replay_tests
            if isinstance(test.get("id"), str) and test.get("id")
        )
        metadata = {
            "description": self.description,
            "package_schema_version": self.schema_version,
            "skill_path": str(self.skill_dir),
            "contracts": {
                name: str(path) for name, path in self.contract_paths.items()
            },
            "optional_artifacts": list(self.optional_artifacts),
            "replay_tests": [dict(test) for test in self.replay_tests],
            "promotion_policy": dict(self.promotion_policy),
            "source_attribution": dict(self.source_attribution),
            "memory_policy": dict(self.memory_policy),
        }

        return CapabilityManifest(
            name=self.name,
            version=self.version,
            capability_type=self.capability_type,
            owner="core",
            license=self.license,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            allowed_tools=self.allowed_tools,
            forbidden_tools=self.forbidden_tools,
            required_artifacts=self.required_artifacts,
            produced_artifacts=self.produced_artifacts,
            guardrails=_flatten_guardrails(self.guardrails),
            tests=replay_test_ids,
            metadata=metadata,
        )

    def to_runtime_contract(
        self,
        *,
        topic_id: int,
        artifact_refs: tuple[str, ...] | list[str] = (),
        objective: str = "",
        literal_inputs: Mapping[str, Any] | None = None,
        user_brief: Mapping[str, Any] | None = None,
        run_id: str = "",
        task_type: str = "evaluation",
        project_id: int | None = None,
    ) -> dict[str, Any]:
        """Build a checkpoint-ready runtime contract from this skill package."""

        capability = self.to_capability_manifest()
        safe_name = self.name.replace("-", "_")
        spec = RunSpec(
            run_id=run_id or f"run.{safe_name}.topic_{topic_id}",
            task_type=task_type,
            topic_id=topic_id,
            project_id=project_id,
            objective=objective or f"Run {self.name}.",
            visible_inputs=RunVisibleInputs(
                artifact_refs=tuple(str(ref) for ref in artifact_refs),
                literal_inputs=dict(literal_inputs or {}),
                user_brief=dict(user_brief or {}),
            ),
            required_outputs=self.produced_artifacts,
            capability_policy={
                "allowed_capabilities": [self.name],
                "allowed_tools": list(self.allowed_tools),
                "denied_tools": list(self.forbidden_tools),
            },
            guardrails={scope: list(names) for scope, names in self.guardrails.items()},
        )

        return {
            "schema_version": "rh.runtime_contract.v0",
            "skill_name": self.name,
            "capability_manifest": capability.to_dict(),
            "run_spec": spec.to_dict(),
        }


def load_skill_package_manifest(skill_dir: Path) -> SkillPackageManifest:
    """Load and validate ``skill.yaml`` from one skill directory."""

    skill_dir = skill_dir.resolve()
    skill_yaml = skill_dir / SKILL_PACKAGE_FILENAME
    skill_md = skill_dir / "SKILL.md"
    if not skill_yaml.is_file():
        raise FileNotFoundError(f"skill package manifest not found: {skill_yaml}")
    if not skill_md.is_file():
        raise FileNotFoundError(f"skill entrypoint not found: {skill_md}")

    raw = _read_yaml_mapping(skill_yaml)
    missing = sorted(_REQUIRED_KEYS - raw.keys())
    if missing:
        raise ValueError(f"{skill_yaml} missing required keys: {', '.join(missing)}")

    frontmatter = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    _validate_frontmatter_alignment(skill_yaml, raw, frontmatter)

    contracts = dict(raw.get("contracts") or {})
    if not contracts:
        contracts = {
            "input": "contracts/input.yaml",
            "output": "contracts/output.yaml",
            "guardrails": "contracts/guardrails.yaml",
        }
    _validate_contracts(skill_dir, raw, contracts)

    return SkillPackageManifest(
        skill_dir=skill_dir,
        schema_version=str(raw.get("schema_version") or SKILL_PACKAGE_SCHEMA_VERSION),
        name=str(raw["name"]),
        version=str(raw["version"]),
        license=str(raw["license"]),
        capability_type=str(raw["capability_type"]),
        description=str(raw["description"]),
        input_schema=str(raw["input_schema"]),
        output_schema=str(raw["output_schema"]),
        allowed_tools=_string_tuple(raw.get("allowed_tools")),
        forbidden_tools=_string_tuple(raw.get("forbidden_tools")),
        required_artifacts=_string_tuple(raw.get("required_artifacts")),
        optional_artifacts=_string_tuple(raw.get("optional_artifacts")),
        produced_artifacts=_string_tuple(raw.get("produced_artifacts")),
        guardrails=_guardrail_map(raw.get("guardrails")),
        replay_tests=_mapping_tuple(raw.get("replay_tests")),
        promotion_policy=dict(raw.get("promotion_policy") or {}),
        contract_paths={name: Path(path) for name, path in contracts.items()},
        source_attribution=dict(raw.get("source_attribution") or {}),
        memory_policy=dict(raw.get("memory_policy") or {}),
        raw=raw,
    )


def iter_skill_package_manifests(
    repo_root: Path,
    skills_dirname: str = DEFAULT_SKILLS_DIRNAME,
) -> Iterable[SkillPackageManifest]:
    """Yield every promoted skill package under ``skills/``."""

    skills_dir = repo_root / skills_dirname
    if not skills_dir.is_dir():
        raise FileNotFoundError(f"skills directory not found: {skills_dir}")

    for entry in sorted(skills_dir.iterdir()):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        if (entry / SKILL_PACKAGE_FILENAME).is_file():
            yield load_skill_package_manifest(entry)


def iter_skill_package_capabilities(
    repo_root: Path,
    skills_dirname: str = DEFAULT_SKILLS_DIRNAME,
) -> Iterable[CapabilityManifest]:
    """Yield runtime capability manifests for every promoted skill package."""

    for package in iter_skill_package_manifests(repo_root, skills_dirname):
        yield package.to_capability_manifest()


def build_skill_runtime_contract(
    repo_root: Path,
    skill_name: str,
    *,
    topic_id: int,
    artifact_refs: tuple[str, ...] | list[str] = (),
    objective: str = "",
    literal_inputs: Mapping[str, Any] | None = None,
    user_brief: Mapping[str, Any] | None = None,
    run_id: str = "",
    task_type: str = "evaluation",
    project_id: int | None = None,
    skills_dirname: str = DEFAULT_SKILLS_DIRNAME,
) -> dict[str, Any]:
    """Load one promoted skill package and build its runtime contract."""

    package = load_skill_package_manifest(repo_root / skills_dirname / skill_name)
    return package.to_runtime_contract(
        topic_id=topic_id,
        artifact_refs=artifact_refs,
        objective=objective,
        literal_inputs=literal_inputs,
        user_brief=user_brief,
        run_id=run_id,
        task_type=task_type,
        project_id=project_id,
    )


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load v2 skill packages")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def _validate_frontmatter_alignment(
    skill_yaml: Path,
    raw: Mapping[str, Any],
    frontmatter: Mapping[str, Any],
) -> None:
    for key in ("name", "version"):
        if str(raw.get(key)) != str(frontmatter.get(key)):
            raise ValueError(
                f"{skill_yaml} {key}={raw.get(key)!r} does not match "
                f"SKILL.md frontmatter {key}={frontmatter.get(key)!r}"
            )


def _validate_contracts(
    skill_dir: Path,
    raw: Mapping[str, Any],
    contracts: Mapping[str, Any],
) -> None:
    for key in ("input", "output", "guardrails"):
        if key not in contracts:
            raise ValueError(
                f"{skill_dir / SKILL_PACKAGE_FILENAME} missing {key} contract"
            )
        contract_path = skill_dir / str(contracts[key])
        if not contract_path.is_file():
            raise FileNotFoundError(f"skill contract not found: {contract_path}")
        contract = _read_yaml_mapping(contract_path)
        if not str(contract.get("schema_version", "")).startswith("rh.schema."):
            raise ValueError(f"{contract_path} must declare rh.schema.* schema_version")
        if not contract.get("type"):
            raise ValueError(f"{contract_path} must declare a type")

        if key == "input" and contract.get("schema_version") != raw.get("input_schema"):
            raise ValueError(f"{contract_path} schema_version must match input_schema")
        if key == "output" and contract.get("schema_version") != raw.get(
            "output_schema"
        ):
            raise ValueError(f"{contract_path} schema_version must match output_schema")


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _guardrail_map(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        return {}
    return {str(scope): _string_tuple(items) for scope, items in value.items()}


def _flatten_guardrails(value: Mapping[str, Iterable[str]]) -> tuple[str, ...]:
    out: list[str] = []
    for items in value.values():
        out.extend(str(item) for item in items)
    return tuple(out)


def _mapping_tuple(value: Any) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("replay_tests must be a list of mappings")
    out: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("each replay_tests entry must be a mapping")
        out.append(dict(item))
    return tuple(out)
