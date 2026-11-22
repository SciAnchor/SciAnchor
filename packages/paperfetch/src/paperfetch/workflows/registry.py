"""Versioned file registry for Workflow resource definitions."""

from __future__ import annotations

from pathlib import Path

from paperfetch.workflows.contracts import (
    ContractError,
    DatasetManifest,
    EnvironmentDefinition,
    WorkflowRegistry,
    WorkflowResourceManifest,
    load_contract,
)


def builtin_registry_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "workflow"


class WorkflowRegistryStore:
    """Load registered definitions without accepting path traversal."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or builtin_registry_root()).expanduser().resolve()
        self.registry = load_contract(self.root / "registry.json", WorkflowRegistry)

    def _registered_path(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ContractError(f"注册路径超出注册表根目录：{relative_path}") from exc
        return candidate

    @staticmethod
    def _lookup(mapping: dict[str, str], reference: str, kind: str) -> str:
        try:
            return mapping[reference]
        except KeyError as exc:
            raise ContractError(f"未注册的 {kind}：{reference}") from exc

    def workflow(self, workflow_ref: str) -> WorkflowResourceManifest:
        relative = self._lookup(self.registry.workflows, workflow_ref, "workflow")
        return load_contract(self._registered_path(relative), WorkflowResourceManifest)

    def environment(self, environment_ref: str) -> EnvironmentDefinition:
        relative = self._lookup(
            self.registry.environments, environment_ref, "environment"
        )
        return load_contract(self._registered_path(relative), EnvironmentDefinition)

    def dataset(self, dataset_ref: str) -> DatasetManifest:
        relative = self._lookup(self.registry.datasets, dataset_ref, "dataset")
        return load_contract(self._registered_path(relative), DatasetManifest)
