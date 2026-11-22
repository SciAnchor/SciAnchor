from __future__ import annotations

import hashlib
import json
from pathlib import Path

from paperfetch.workflows.contracts import (
    DatasetManifest,
    EnvironmentDefinition,
    HostProfile,
    ProbeDefinition,
    ResourceStatus,
    WorkflowResourceManifest,
    attach_content_digest,
    verify_content_digest,
)
from paperfetch.workflows.readiness import check_workflow


def _model(model, payload):
    return model.model_validate(attach_content_digest(payload))


def _write_validation_ledger(
    path: Path,
    *,
    environment_ref: str,
    workflow_ref: str,
    dataset_ref: str,
    covered_modules: list[str] | None = None,
) -> None:
    payload = attach_content_digest(
        {
            "schema_version": "spc.environment-validation-ledger.v1",
            "environment_ref": environment_ref,
            "environment_lock_digest": "sha256:" + "a" * 64,
            "workflow_ref": workflow_ref,
            "validation_level": "REAL_PASS",
            "status": "passed",
            "execution_host_id": "host:test-execution",
            "producer_actor": "test",
            "validator_id": "fixture-validator",
            "validator_revision": "fixture-1",
            "started_at": "2026-08-01T00:00:00Z",
            "completed_at": "2026-08-01T00:01:00Z",
            "covered_modules": covered_modules or ["fixture-module"],
            "dataset_refs": [dataset_ref],
            "checks": [{"check_id": "fixture", "status": "passed", "detail": None}],
            "evidence": [
                {
                    "evidence_id": "fixture-report",
                    "kind": "report",
                    "uri": "urn:test:fixture-report",
                    "sha256": "d" * 64,
                }
            ],
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


class FakeRegistry:
    def __init__(self, workflow, environments, datasets):
        self._workflow = workflow
        self._environments = environments
        self._datasets = datasets

    def workflow(self, _reference):
        return self._workflow

    def environment(self, reference):
        return self._environments[reference]

    def dataset(self, reference):
        return self._datasets[reference]


def _resources(
    tmp_path: Path, *, dataset_required: bool = True, provisional: bool = False
):
    env_root = tmp_path / "envs"
    env_prefix = env_root / "analysis"
    (env_prefix / "conda-meta").mkdir(parents=True)
    (env_prefix / "conda-meta" / "history").write_text("created", encoding="utf-8")
    conda = tmp_path / "conda.exe"
    conda.write_text("placeholder", encoding="utf-8")

    data_root = tmp_path / "data"
    dataset_dir = data_root / "geo" / "GSE1"
    dataset_dir.mkdir(parents=True)
    payload = b"count matrix"
    raw = dataset_dir / "GSE1_RAW.tar"
    raw.write_bytes(payload)
    raw_sha = hashlib.sha256(payload).hexdigest()
    optional = dataset_dir / "GSE1_metadata.txt"
    optional.write_text("optional metadata", encoding="utf-8")
    optional_sha = hashlib.sha256(optional.read_bytes()).hexdigest()
    (dataset_dir / "archive.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "filename": raw.name,
                        "size_bytes": len(payload),
                        "sha256": raw_sha,
                    },
                    {
                        "filename": optional.name,
                        "size_bytes": optional.stat().st_size,
                        "sha256": optional_sha,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    environment_ref = "environment:test-analysis@1"
    dataset_ref = "dataset:geo:GSE1@1"
    workflow_ref = "workflow:test.analysis@1"
    _write_validation_ledger(
        env_prefix / "validation-ledger.json",
        environment_ref=environment_ref,
        workflow_ref=workflow_ref,
        dataset_ref=dataset_ref,
    )
    environment = _model(
        EnvironmentDefinition,
        {
            "schema_version": "spc.environment-definition.v1",
            "environment_ref": environment_ref,
            "lifecycle_status": "frozen",
            "runtime": "conda",
            "platforms": ["windows-x86_64"],
            "lock_digest": "sha256:" + "a" * 64,
            "external_identity": None,
            "probes": [
                {
                    "type": "file_exists",
                    "level": "IMPORT_PASS",
                    "path": "conda-meta/history",
                },
                {
                    "type": "validation_ledger",
                    "level": "REAL_PASS",
                    "path": "validation-ledger.json",
                },
            ],
        },
    )
    dataset = _model(
        DatasetManifest,
        {
            "schema_version": "spc.dataset-manifest.v1",
            "dataset_ref": dataset_ref,
            "lifecycle_status": "frozen",
            "source_identity": {
                "namespace": "geo",
                "accession": "GSE1",
                "official_url": "https://example.invalid/GSE1",
            },
            "source_snapshot": {
                "observed_at": "2026-08-01T00:00:00Z",
                "remote_snapshot_digest": "sha256:" + "b" * 64,
            },
            "artifacts": [
                {
                    "artifact_id": "raw-archive",
                    "filename": raw.name,
                    "kind": "supplementary",
                    "size_bytes": len(payload),
                    "sha256": raw_sha,
                    "source_url": "https://example.invalid/GSE1_RAW.tar",
                    "last_modified": "2026-08-01T00:00:00Z",
                    "etag": None,
                },
                {
                    "artifact_id": "optional-metadata",
                    "filename": optional.name,
                    "kind": "metadata",
                    "size_bytes": optional.stat().st_size,
                    "sha256": optional_sha,
                    "source_url": "https://example.invalid/GSE1_metadata.txt",
                    "last_modified": "2026-08-01T00:00:00Z",
                    "etag": None,
                },
            ],
            "acquisition_sources": [
                {"source_id": "fixture", "mode": "automatic", "priority": 10}
            ],
            "content_identity": {
                "identity_status": "verified",
                "raw_archive_member_count": 1,
                "raw_archive_member_manifest_sha256": "c" * 64,
                "workflow_baseline_package_sha256": raw_sha,
                "server_wsl_package_sha256": raw_sha,
            },
        },
    )
    workflow = _model(
        WorkflowResourceManifest,
        {
            "schema_version": "spc.workflow-resource-manifest.v1",
            "workflow_ref": workflow_ref,
            "workflow_source": {
                "authority_type": "static_manifest",
                "authority_id": "fixture",
                "source_revision": "fixture-1",
                "exported_at": "2026-08-01T00:00:00Z",
            },
            "manifest_revision": 1,
            "lifecycle_status": "provisional" if provisional else "frozen",
            "platforms": ["windows-x86_64"],
            "selected_modules": ["fixture-module"],
            "environment_requirements": [
                {
                    "requirement_id": "analysis",
                    "environment_ref": environment_ref,
                    "required": True,
                    "required_by_modules": ["fixture-module"],
                    "minimum_validation_level": "REAL_PASS",
                }
            ],
            "dataset_requirements": [
                {
                    "requirement_id": "counts",
                    "dataset_ref": dataset_ref,
                    "required": dataset_required,
                    "purpose_hint": "fixture",
                    "artifact_requirements": [
                        {
                            "artifact_id": "raw-archive",
                            "required": True,
                            "use": "execution_input",
                        },
                        {
                            "artifact_id": "optional-metadata",
                            "required": False,
                            "use": "optional_metadata",
                        },
                    ],
                    "readiness_enforcement": "resource_only",
                }
            ],
        },
    )
    profile = _model(
        HostProfile,
        {
            "schema_version": "spc.host-profile.v1",
            "host_id": "host:test-windows",
            "platform": "windows-x86_64",
            "conda_executable": str(conda),
            "allowed_environment_roots": [str(env_root)],
            "allowed_data_roots": [str(data_root)],
            "catalog_root": str(data_root / "catalog"),
            "environment_mappings": {environment_ref: str(env_prefix)},
            "dataset_mappings": {},
        },
    )
    registry = FakeRegistry(
        workflow, {environment_ref: environment}, {dataset_ref: dataset}
    )
    return registry, profile, dataset_dir, workflow_ref


def test_ready_workflow_generates_digest_and_launcher(tmp_path):
    registry, profile, _, workflow_ref = _resources(tmp_path)

    report = check_workflow(workflow_ref, profile, registry=registry, mode="production")

    assert report.resource_status == ResourceStatus.READY
    assert report.environments[0].launcher.argv_prefix[1:3] == ["run", "--prefix"]
    assert report.datasets[0].artifact_results[0].status.value == "ready"
    verify_content_digest(report.model_dump(mode="json"))


def test_missing_required_dataset_blocks(tmp_path):
    registry, profile, dataset_dir, workflow_ref = _resources(tmp_path)
    for path in dataset_dir.iterdir():
        path.unlink()
    dataset_dir.rmdir()

    report = check_workflow(workflow_ref, profile, registry=registry)

    assert report.resource_status == ResourceStatus.BLOCKED
    assert {item.code for item in report.blockers} == {"DATASET_NOT_MATERIALIZED"}


def test_missing_optional_dataset_is_degraded_not_blocked(tmp_path):
    registry, profile, dataset_dir, workflow_ref = _resources(
        tmp_path, dataset_required=False
    )
    for path in dataset_dir.iterdir():
        path.unlink()
    dataset_dir.rmdir()

    report = check_workflow(workflow_ref, profile, registry=registry)

    assert report.resource_status == ResourceStatus.READY_WITH_OPTIONAL_MISSING
    assert report.blockers == []


def test_missing_optional_artifact_inside_required_dataset_is_degraded(tmp_path):
    registry, profile, dataset_dir, workflow_ref = _resources(tmp_path)
    (dataset_dir / "GSE1_metadata.txt").unlink()

    report = check_workflow(workflow_ref, profile, registry=registry)

    assert report.resource_status == ResourceStatus.READY_WITH_OPTIONAL_MISSING
    assert report.datasets[0].status.value == "optional_missing"
    assert report.blockers == []


def test_production_mode_blocks_provisional_manifest(tmp_path):
    registry, profile, _, workflow_ref = _resources(tmp_path, provisional=True)

    report = check_workflow(workflow_ref, profile, registry=registry, mode="production")

    assert report.resource_status == ResourceStatus.BLOCKED
    assert "MANIFEST_PROVISIONAL" in {item.code for item in report.blockers}


def test_empty_validation_ledger_cannot_claim_real_pass(tmp_path):
    registry, profile, _, workflow_ref = _resources(tmp_path)
    ledger = Path(profile.environment_mappings["environment:test-analysis@1"]) / (
        "validation-ledger.json"
    )
    ledger.write_text("{}", encoding="utf-8")

    report = check_workflow(workflow_ref, profile, registry=registry, mode="production")

    assert report.resource_status == ResourceStatus.BLOCKED
    probe = report.environments[0].probe_results[1]
    assert probe.status.value == "invalid"
    assert "EnvironmentValidationLedger" in (probe.detail or "")


def test_validation_ledger_must_cover_required_modules(tmp_path):
    registry, profile, _, workflow_ref = _resources(tmp_path)
    prefix = Path(profile.environment_mappings["environment:test-analysis@1"])
    _write_validation_ledger(
        prefix / "validation-ledger.json",
        environment_ref="environment:test-analysis@1",
        workflow_ref=workflow_ref,
        dataset_ref="dataset:geo:GSE1@1",
        covered_modules=["different-module"],
    )

    report = check_workflow(workflow_ref, profile, registry=registry, mode="production")

    assert report.resource_status == ResourceStatus.BLOCKED
    assert "未覆盖必需模块" in (report.environments[0].probe_results[1].detail or "")


def test_validation_ledger_rejects_dataset_outside_workflow(tmp_path):
    registry, profile, _, workflow_ref = _resources(tmp_path)
    prefix = Path(profile.environment_mappings["environment:test-analysis@1"])
    _write_validation_ledger(
        prefix / "validation-ledger.json",
        environment_ref="environment:test-analysis@1",
        workflow_ref=workflow_ref,
        dataset_ref="dataset:geo:GSE999@1",
        covered_modules=["fixture-module"],
    )

    report = check_workflow(workflow_ref, profile, registry=registry, mode="production")

    assert report.resource_status == ResourceStatus.BLOCKED
    assert "数据集未在 Workflow 中注册" in (
        report.environments[0].probe_results[1].detail or ""
    )


def test_production_mode_blocks_provisional_environment_definition(tmp_path):
    registry, profile, _, workflow_ref = _resources(tmp_path)
    environment = registry._environments["environment:test-analysis@1"]
    environment.lifecycle_status = "provisional"

    report = check_workflow(workflow_ref, profile, registry=registry, mode="production")

    assert report.resource_status == ResourceStatus.BLOCKED
    assert "ENVIRONMENT_DEFINITION_PROVISIONAL" in {
        item.code for item in report.blockers
    }


def test_conda_lock_probe_binds_installed_environment(tmp_path, monkeypatch):
    registry, profile, _, workflow_ref = _resources(tmp_path)
    environment = registry._environments["environment:test-analysis@1"]
    environment.probes.insert(
        0,
        ProbeDefinition(type="conda_lock", level="IMPORT_PASS"),
    )

    monkeypatch.setattr(
        "paperfetch.workflows.readiness.inspect_conda_environment",
        lambda *_args: ({"packages": [{"name": "fixture"}]}, environment.lock_digest),
    )

    report = check_workflow(workflow_ref, profile, registry=registry, mode="production")

    assert report.resource_status == ResourceStatus.READY
    assert report.environments[0].probe_results[0].status.value == "ready"
    assert "软件包=1" in (report.environments[0].probe_results[0].detail or "")


def test_conda_lock_mismatch_blocks_environment(tmp_path, monkeypatch):
    registry, profile, _, workflow_ref = _resources(tmp_path)
    environment = registry._environments["environment:test-analysis@1"]
    environment.probes.insert(
        0,
        ProbeDefinition(type="conda_lock", level="IMPORT_PASS"),
    )

    monkeypatch.setattr(
        "paperfetch.workflows.readiness.inspect_conda_environment",
        lambda *_args: ({"packages": []}, "sha256:" + "f" * 64),
    )

    report = check_workflow(workflow_ref, profile, registry=registry, mode="production")

    assert report.resource_status == ResourceStatus.BLOCKED
    assert "conda lock 不一致" in (report.environments[0].probe_results[0].detail or "")
