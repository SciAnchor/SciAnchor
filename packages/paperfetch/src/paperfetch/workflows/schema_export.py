"""Export committed JSON Schema files from the authoritative Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path

from paperfetch.workflows.contracts import (
    DatasetManifest,
    EnvironmentDefinition,
    EnvironmentValidationLedger,
    HostProfile,
    WorkflowReady,
    WorkflowRegistry,
    WorkflowResourceManifest,
)

SCHEMA_MODELS = {
    "dataset-manifest.v1.schema.json": DatasetManifest,
    "environment-definition.v1.schema.json": EnvironmentDefinition,
    "environment-validation-ledger.v1.schema.json": EnvironmentValidationLedger,
    "host-profile.v1.schema.json": HostProfile,
    "workflow-ready.v1.schema.json": WorkflowReady,
    "workflow-registry.v1.schema.json": WorkflowRegistry,
    "workflow-resource-manifest.v1.schema.json": WorkflowResourceManifest,
}


def export_schemas(output_dir: str | Path) -> list[Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, model in SCHEMA_MODELS.items():
        path = destination / filename
        payload = model.model_json_schema()
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
