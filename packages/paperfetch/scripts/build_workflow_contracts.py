"""Regenerate Workflow contract digests and committed JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path

from paperfetch.workflows.contracts import (
    DatasetManifest,
    EnvironmentDefinition,
    HostProfile,
    WorkflowRegistry,
    WorkflowResourceManifest,
    attach_content_digest,
    verify_content_digest,
)
from paperfetch.workflows.schema_export import export_schemas


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "src" / "paperfetch" / "data" / "workflow"
MODELS = {
    "spc.workflow-registry.v1": WorkflowRegistry,
    "spc.workflow-resource-manifest.v1": WorkflowResourceManifest,
    "spc.environment-definition.v1": EnvironmentDefinition,
    "spc.dataset-manifest.v1": DatasetManifest,
    "spc.host-profile.v1": HostProfile,
}


def main() -> int:
    paths = sorted(
        path
        for path in DATA_ROOT.rglob("*.json")
        if "schemas" not in path.parts and "fixtures" not in path.parts
    )
    paths.extend(sorted((ROOT / "deploy" / "workflow").glob("*.json")))
    signed_contracts = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        schema_version = str(payload.get("schema_version") or "")
        model = MODELS.get(schema_version)
        if model is None:
            raise ValueError(f"unsupported schema_version in {path}: {schema_version}")
        signed = attach_content_digest(payload)
        verify_content_digest(signed)
        model.model_validate(signed)
        signed_contracts.append((path, signed))
    for path, signed in signed_contracts:
        path.write_text(
            json.dumps(signed, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    schemas = export_schemas(DATA_ROOT / "schemas")
    print(f"signed_contracts={len(signed_contracts)} schemas={len(schemas)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
