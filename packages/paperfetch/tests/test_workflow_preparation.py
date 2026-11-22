from __future__ import annotations

import hashlib
import json
from pathlib import Path

from paperfetch.datasets.geo import GeoLargeDownloadBlocked
from paperfetch.workflows.contracts import (
    DatasetManifest,
    EnvironmentDefinition,
    HostProfile,
    ResourceStatus,
    WorkflowResourceManifest,
    attach_content_digest,
    verify_content_digest,
)
from paperfetch.workflows.preparation import prepare_workflow


def _model(model, payload):
    return model.model_validate(attach_content_digest(payload))


def _write_validation_ledger(
    path: Path,
    *,
    environment_ref: str,
    workflow_ref: str,
    dataset_ref: str,
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
            "covered_modules": ["fixture-module"],
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
    def __init__(self, workflow, environment, dataset):
        self._workflow = workflow
        self._environment = environment
        self._dataset = dataset

    def workflow(self, _reference):
        return self._workflow

    def environment(self, _reference):
        return self._environment

    def dataset(self, _reference):
        return self._dataset


def _resources(tmp_path: Path, *, with_artifact_requirement: bool = True):
    env_root = tmp_path / "envs"
    env_prefix = env_root / "analysis"
    (env_prefix / "conda-meta").mkdir(parents=True)
    (env_prefix / "conda-meta" / "history").write_text("created", encoding="utf-8")
    conda = tmp_path / "conda.exe"
    conda.write_text("placeholder", encoding="utf-8")

    data_root = tmp_path / "data"
    data_root.mkdir()
    payload = b"registered workflow dataset"
    artifact_sha = hashlib.sha256(payload).hexdigest()
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
    artifacts = (
        [
            {
                "artifact_id": "raw-archive",
                "filename": "GSE1_RAW.tar",
                "kind": "supplementary",
                "size_bytes": len(payload),
                "sha256": artifact_sha,
                "source_url": "https://example.invalid/GSE1_RAW.tar",
                "last_modified": "2026-08-01T00:00:00Z",
                "etag": None,
            }
        ]
        if with_artifact_requirement
        else []
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
            "artifacts": artifacts,
            "acquisition_sources": [
                {"source_id": "ncbi-geo", "mode": "automatic", "priority": 10}
            ],
            "content_identity": {
                "identity_status": "verified",
                "raw_archive_member_count": 1,
                "raw_archive_member_manifest_sha256": "c" * 64,
                "workflow_baseline_package_sha256": artifact_sha,
                "server_wsl_package_sha256": artifact_sha,
            },
        },
    )
    artifact_requirements = (
        [{"artifact_id": "raw-archive", "required": True, "use": "execution_input"}]
        if with_artifact_requirement
        else []
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
            "lifecycle_status": "frozen",
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
                    "required": True,
                    "purpose_hint": "fixture",
                    "artifact_requirements": artifact_requirements,
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
    registry = FakeRegistry(workflow, environment, dataset)
    return registry, profile, workflow_ref, payload, artifact_sha


class WritingGeoStore:
    calls = 0
    payload = b""
    last_kwargs = {}

    def __init__(self, output_dir, **kwargs):
        self.root = Path(output_dir)
        type(self).last_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def download(self, accession, *, filenames, allow_large):
        type(self).calls += 1
        assert accession == "GSE1"
        assert filenames == ["GSE1_RAW.tar"]
        assert allow_large is False
        directory = self.root / accession
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / filenames[0]
        target.write_bytes(type(self).payload)
        archive = {
            "files": [
                {
                    "filename": target.name,
                    "size_bytes": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            ]
        }
        (directory / "archive.json").write_text(json.dumps(archive), encoding="utf-8")
        return {"status": "complete", "dataset_dir": str(directory)}


def test_prepare_materializes_registered_required_dataset(tmp_path):
    registry, profile, workflow_ref, payload, _ = _resources(tmp_path)
    WritingGeoStore.calls = 0
    WritingGeoStore.payload = payload
    WritingGeoStore.last_kwargs = {}

    outcome = prepare_workflow(
        workflow_ref,
        profile,
        registry=registry,
        mode="production",
        dataset_concurrency=3,
        lock_timeout_seconds=12.5,
        geo_store_factory=WritingGeoStore,
    )

    assert outcome.exit_code == 0
    assert outcome.report.resource_status == ResourceStatus.READY
    assert outcome.actions[0].action == "prepared"
    assert WritingGeoStore.calls == 1
    assert WritingGeoStore.last_kwargs["dataset_concurrency"] == 3
    assert WritingGeoStore.last_kwargs["lock_timeout_seconds"] == 12.5
    verify_content_digest(outcome.report.model_dump(mode="json"))


def test_prepare_is_idempotent_and_reuses_verified_dataset(tmp_path):
    registry, profile, workflow_ref, payload, _ = _resources(tmp_path)
    WritingGeoStore.calls = 0
    WritingGeoStore.payload = payload
    first = prepare_workflow(
        workflow_ref,
        profile,
        registry=registry,
        mode="production",
        geo_store_factory=WritingGeoStore,
    )

    class FailIfConstructed:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("idempotent prepare must not open a download store")

    second = prepare_workflow(
        workflow_ref,
        profile,
        registry=registry,
        mode="production",
        geo_store_factory=FailIfConstructed,
    )

    assert first.exit_code == second.exit_code == 0
    assert second.actions[0].action == "reused"
    assert WritingGeoStore.calls == 1


def test_prepare_blocks_incomplete_dataset_definition_without_guessing(tmp_path):
    registry, profile, workflow_ref, _, _ = _resources(
        tmp_path,
        with_artifact_requirement=False,
    )

    outcome = prepare_workflow(
        workflow_ref,
        profile,
        registry=registry,
        mode="production",
        geo_store_factory=WritingGeoStore,
    )

    assert outcome.exit_code == 2
    assert outcome.report.resource_status == ResourceStatus.BLOCKED
    assert "DATASET_DEFINITION_INCOMPLETE" in {
        item.code for item in outcome.report.blockers
    }
    assert outcome.actions[0].action == "blocked_definition"


def test_prepare_preserves_large_download_approval_gate(tmp_path):
    registry, profile, workflow_ref, _, _ = _resources(tmp_path)

    class LargeGeoStore(WritingGeoStore):
        def download(self, accession, *, filenames, allow_large):
            plan = {
                "size_gate": {"max_bytes": 1},
                "totals": {"known_bytes": 2, "unknown_size_files": []},
            }
            raise GeoLargeDownloadBlocked(plan)

    outcome = prepare_workflow(
        workflow_ref,
        profile,
        registry=registry,
        mode="production",
        geo_store_factory=LargeGeoStore,
    )

    assert outcome.exit_code == 2
    assert "DATASET_LARGE_DOWNLOAD_APPROVAL_REQUIRED" in {
        item.code for item in outcome.report.blockers
    }


def test_prepare_returns_integrity_exit_for_wrong_downloaded_bytes(tmp_path):
    registry, profile, workflow_ref, payload, _ = _resources(tmp_path)
    WritingGeoStore.calls = 0
    WritingGeoStore.payload = b"x" * len(payload)

    outcome = prepare_workflow(
        workflow_ref,
        profile,
        registry=registry,
        mode="production",
        geo_store_factory=WritingGeoStore,
    )

    assert outcome.exit_code == 4
    assert "ARTIFACT_SHA256_MISMATCH" in {item.code for item in outcome.report.blockers}


def test_prepare_returns_temporary_exit_for_interrupted_download(tmp_path):
    registry, profile, workflow_ref, _, _ = _resources(tmp_path)

    class IncompleteGeoStore(WritingGeoStore):
        def download(self, accession, *, filenames, allow_large):
            return {
                "status": "incomplete",
                "last_error": "stream retries exhausted after connection timeout",
            }

    outcome = prepare_workflow(
        workflow_ref,
        profile,
        registry=registry,
        mode="production",
        geo_store_factory=IncompleteGeoStore,
    )

    assert outcome.exit_code == 3
    assert "DATASET_PREPARATION_INCOMPLETE" in {
        item.code for item in outcome.report.blockers
    }


def test_prepare_treats_public_geo_403_as_retryable(tmp_path):
    registry, profile, workflow_ref, _, _ = _resources(tmp_path)

    class RateLimitedGeoStore(WritingGeoStore):
        def download(self, accession, *, filenames, allow_large):
            return {
                "status": "incomplete",
                "last_error": "HTTPError: 403 Client Error: Forbidden for public GEO file",
            }

    outcome = prepare_workflow(
        workflow_ref,
        profile,
        registry=registry,
        mode="production",
        geo_store_factory=RateLimitedGeoStore,
    )

    assert outcome.exit_code == 3
