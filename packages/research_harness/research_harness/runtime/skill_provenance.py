"""Read-only skill provenance scanner for the runtime-shell read model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from research_harness.skill.manifest import _parse_frontmatter

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - PyYAML is an existing optional import
    yaml = None  # type: ignore


SKILL_PROVENANCE_RECORD_SCHEMA_VERSION = "skill_provenance_record.v0"
SKILL_PROVENANCE_REPORT_SCHEMA_VERSION = "skill_provenance_report.v0"
_CONTRACT_ORDER = ("input", "output", "guardrails")


@dataclass(frozen=True)
class SkillProvenanceRecord:
    """Internal provenance view over one existing skill package."""

    skill_name: str
    package_path: str
    skill_md_path: str
    schema_version: str = SKILL_PROVENANCE_RECORD_SCHEMA_VERSION
    source_kind: str = "repo_skill"
    manifest_path: str | None = None
    manifest_generated_at: str | None = None
    public_suite: str | None = None
    task_type: str | None = None
    data_access_level: str | None = None
    portable_description: str | None = None
    version: str | None = None
    license: str | None = None
    content_hashes: Mapping[str, str] | None = None
    sidecar_files: tuple[str, ...] = ()
    track_files: tuple[str, ...] = ()
    agent_overlays: tuple[str, ...] = ()
    runtime_capability_type: str | None = None
    runtime_contract_refs: tuple[str, ...] = ()
    allowed_tools_declared: tuple[str, ...] = ()
    forbidden_tools_declared: tuple[str, ...] = ()
    artifact_schemas: str | None = None
    required_artifacts: tuple[str, ...] = ()
    produced_artifacts: tuple[str, ...] = ()
    gate_policy: str | None = None
    source_attribution: Mapping[str, Any] | None = None
    memory_policy: Mapping[str, Any] | None = None
    validation_status: str = "not_validated"
    visibility: str = "public"
    excluded_generated_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillProvenanceReport:
    """Internal read-only report for a skill provenance scan."""

    manifest_path: str
    manifest_generated_at: str
    public_skill_count: int
    records: tuple[SkillProvenanceRecord, ...]
    schema_version: str = SKILL_PROVENANCE_REPORT_SCHEMA_VERSION
    manifest_drift: bool = False
    missing_from_manifest: tuple[str, ...] = ()
    manifest_only: tuple[str, ...] = ()


def scan_skill_provenance(
    repo_root: Path,
    *,
    skills_dirname: str = "skills",
) -> SkillProvenanceReport:
    """Scan existing skill files into an internal read-model without writes."""

    repo_root = repo_root.resolve()
    skills_dir = repo_root / skills_dirname
    manifest_path = skills_dir / "manifest.json"
    manifest = _read_manifest(manifest_path)
    manifest_entries = {
        str(entry.get("name")): entry
        for entry in manifest.get("skills", [])
        if isinstance(entry, Mapping) and entry.get("name")
    }
    discovered = _discover_skill_dirs(skills_dir)
    discovered_names = set(discovered)
    manifest_names = set(manifest_entries)

    records = tuple(
        _record_for_skill(
            repo_root=repo_root,
            skills_dir=skills_dir,
            manifest_path=manifest_path,
            manifest_generated_at=str(manifest.get("generated_at") or ""),
            skill_dir=skill_dir,
            manifest_entry=manifest_entries.get(skill_name),
        )
        for skill_name, skill_dir in sorted(discovered.items())
    )
    missing = tuple(sorted(discovered_names - manifest_names))
    manifest_only = tuple(sorted(manifest_names - discovered_names))

    return SkillProvenanceReport(
        manifest_path=str(manifest_path.relative_to(repo_root)),
        manifest_generated_at=str(manifest.get("generated_at") or ""),
        public_skill_count=len(records),
        records=records,
        manifest_drift=bool(missing or manifest_only),
        missing_from_manifest=missing,
        manifest_only=manifest_only,
    )


def skill_provenance_record_to_dict(
    record: SkillProvenanceRecord,
) -> dict[str, Any]:
    payload = asdict(record)
    payload["content_hashes"] = dict(record.content_hashes or {})
    payload["sidecar_files"] = list(record.sidecar_files)
    payload["track_files"] = list(record.track_files)
    payload["agent_overlays"] = list(record.agent_overlays)
    payload["runtime_contract_refs"] = list(record.runtime_contract_refs)
    payload["allowed_tools_declared"] = list(record.allowed_tools_declared)
    payload["forbidden_tools_declared"] = list(record.forbidden_tools_declared)
    payload["required_artifacts"] = list(record.required_artifacts)
    payload["produced_artifacts"] = list(record.produced_artifacts)
    payload["source_attribution"] = _json_clone(record.source_attribution or {})
    payload["memory_policy"] = _json_clone(record.memory_policy or {})
    payload["excluded_generated_files"] = list(record.excluded_generated_files)
    return payload


def skill_provenance_report_to_dict(
    report: SkillProvenanceReport,
) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "manifest_path": report.manifest_path,
        "manifest_generated_at": report.manifest_generated_at,
        "public_skill_count": report.public_skill_count,
        "manifest_drift": report.manifest_drift,
        "missing_from_manifest": list(report.missing_from_manifest),
        "manifest_only": list(report.manifest_only),
        "records": [
            skill_provenance_record_to_dict(record) for record in report.records
        ],
    }


def _record_for_skill(
    *,
    repo_root: Path,
    skills_dir: Path,
    manifest_path: Path,
    manifest_generated_at: str,
    skill_dir: Path,
    manifest_entry: Mapping[str, Any] | None,
) -> SkillProvenanceRecord:
    skill_md = skill_dir / "SKILL.md"
    frontmatter = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    skill_name = str(
        (manifest_entry or {}).get("name") or frontmatter.get("name") or skill_dir.name
    )
    extras = dict((manifest_entry or {}).get("extras") or {})
    package_rel = str(skill_dir.relative_to(repo_root))
    skill_md_rel = str(skill_md.relative_to(repo_root))
    skill_yaml = skill_dir / "skill.yaml"
    runtime_payload = _read_yaml_mapping(skill_yaml) if skill_yaml.is_file() else {}
    contract_refs = _contract_refs(runtime_payload)
    sidecars, hashes, excluded = _scan_package_files(skill_dir)

    return SkillProvenanceRecord(
        skill_name=skill_name,
        package_path=package_rel,
        skill_md_path=skill_md_rel,
        source_kind="promoted_runtime_skill" if runtime_payload else "repo_skill",
        manifest_path=str(manifest_path.relative_to(repo_root)),
        manifest_generated_at=manifest_generated_at,
        public_suite=_scalar(
            extras.get("public_suite") or frontmatter.get("public_suite")
        ),
        task_type=_scalar(extras.get("task_type") or frontmatter.get("task_type")),
        data_access_level=_scalar(
            extras.get("data_access_level") or frontmatter.get("data_access_level")
        ),
        portable_description=_scalar(
            (manifest_entry or {}).get("description") or frontmatter.get("description")
        ),
        version=_scalar(
            (manifest_entry or {}).get("version") or runtime_payload.get("version")
        ),
        license=_scalar(runtime_payload.get("license")),
        content_hashes=hashes,
        sidecar_files=sidecars,
        track_files=tuple(path for path in sidecars if path.startswith("tracks/")),
        agent_overlays=tuple(path for path in sidecars if path.startswith("agents/")),
        runtime_capability_type=_scalar(runtime_payload.get("capability_type")),
        runtime_contract_refs=contract_refs,
        allowed_tools_declared=_string_tuple(
            (manifest_entry or {}).get("allowed_tools")
            or frontmatter.get("allowed-tools")
            or frontmatter.get("allowed_tools")
            or runtime_payload.get("allowed_tools")
        ),
        forbidden_tools_declared=_string_tuple(runtime_payload.get("forbidden_tools")),
        artifact_schemas=_scalar(extras.get("artifact_schemas")),
        required_artifacts=_string_tuple(runtime_payload.get("required_artifacts")),
        produced_artifacts=_string_tuple(runtime_payload.get("produced_artifacts")),
        gate_policy=_scalar(extras.get("gates") or frontmatter.get("gates")),
        source_attribution=_mapping(runtime_payload.get("source_attribution")),
        memory_policy=_mapping(runtime_payload.get("memory_policy")),
        validation_status="read_only_scanned",
        excluded_generated_files=excluded,
    )


def _discover_skill_dirs(skills_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for entry in sorted(skills_dir.iterdir() if skills_dir.is_dir() else []):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        frontmatter = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        out[str(frontmatter.get("name") or entry.name)] = entry
    return out


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"generated_at": "", "skills": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"generated_at": "", "skills": []}


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if yaml is None:
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _contract_refs(payload: Mapping[str, Any]) -> tuple[str, ...]:
    contracts = payload.get("contracts") if isinstance(payload, Mapping) else None
    if not isinstance(contracts, Mapping):
        contracts = (
            {
                "input": "contracts/input.yaml",
                "output": "contracts/output.yaml",
                "guardrails": "contracts/guardrails.yaml",
            }
            if payload
            else {}
        )
    return tuple(
        str(contracts[name])
        for name in _CONTRACT_ORDER
        if name in contracts and contracts[name]
    )


def _scan_package_files(
    skill_dir: Path,
) -> tuple[tuple[str, ...], dict[str, str], tuple[str, ...]]:
    sidecars: list[str] = []
    hashes: dict[str, str] = {}
    excluded: list[str] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(skill_dir).as_posix()
        if _is_generated_file(path):
            excluded.append(rel)
            continue
        hashes[rel] = f"sha256:{_sha256(path)}"
        if rel != "SKILL.md":
            sidecars.append(rel)
    return tuple(sidecars), hashes, tuple(excluded)


def _is_generated_file(path: Path) -> bool:
    parts = set(path.parts)
    return "__pycache__" in parts or path.suffix in {".pyc", ".pyo"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = " ".join(value.split())
        return text or None
    return str(value)


def _json_clone(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(dict(value), sort_keys=True))
    except (TypeError, ValueError):
        return {str(key): str(item) for key, item in value.items()}
