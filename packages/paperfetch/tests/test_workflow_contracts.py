from __future__ import annotations

import json

import pytest

from paperfetch.workflows.contracts import (
    ContractError,
    DatasetManifest,
    WorkflowResourceManifest,
    attach_content_digest,
    binding_key,
    canonical_json_bytes,
    load_contract,
    verify_content_digest,
)
from paperfetch.workflows.registry import (
    WorkflowRegistryStore,
    builtin_registry_root,
)
from paperfetch.workflows.schema_export import SCHEMA_MODELS, export_schemas


def test_canonical_json_and_binding_key_are_stable():
    identity = {
        "topic_id": 16,
        "workflow_ref": "workflow:npj-gene.glioma@provisional-1",
        "host_id": "host:desktop-d29igt8-wsl",
    }
    assert canonical_json_bytes(identity) == (
        b'{"host_id":"host:desktop-d29igt8-wsl","topic_id":16,'
        b'"workflow_ref":"workflow:npj-gene.glioma@provisional-1"}'
    )
    assert binding_key(**identity).startswith("sha256:")
    assert len(binding_key(**identity)) == 71


def test_binding_key_gold_fixture_preserves_topic_id_type():
    path = builtin_registry_root() / "fixtures" / "binding-key-gold.v1.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    for case in fixture["cases"]:
        assert binding_key(**case["input"]) == case["binding_key"]
    assert fixture["cases"][0]["binding_key"] != fixture["cases"][1]["binding_key"]


def test_load_contract_rejects_tampered_digest(tmp_path):
    source = (
        builtin_registry_root() / "manifests" / "npj-gene.glioma.provisional-1.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["manifest_revision"] = 99
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match="content_digest 不一致"):
        load_contract(target, WorkflowResourceManifest)


def test_unknown_schema_version_is_rejected(tmp_path):
    source = (
        builtin_registry_root() / "manifests" / "npj-gene.glioma.provisional-1.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["schema_version"] = "spc.workflow-resource-manifest.v2"
    payload = attach_content_digest(payload)
    target = tmp_path / "unknown.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match="literal_error"):
        load_contract(target, WorkflowResourceManifest)


def test_builtin_glioma_registry_matches_confirmed_roles():
    registry = WorkflowRegistryStore()
    manifest = registry.workflow("workflow:npj-gene.glioma@provisional-1")
    requirements = {item.dataset_ref: item for item in manifest.dataset_requirements}

    assert requirements["dataset:geo:GSE274546@provisional-2026-08-01"].required is True
    assert requirements["dataset:geo:GSE131928@2026-08-01"].required is True
    assert requirements["dataset:geo:GSE274548@provisional-1"].required is False
    assert requirements["dataset:geo:GSE84465@provisional-1"].required is False
    assert "copykat-sensitivity-audit" in manifest.selected_modules
    assert "monocle" not in " ".join(manifest.selected_modules).lower()

    primary = requirements["dataset:geo:GSE274546@provisional-2026-08-01"]
    artifacts = {item.artifact_id: item for item in primary.artifact_requirements}
    assert artifacts["raw-archive"].required is True
    assert artifacts["family-soft"].required is False
    assert artifacts["filelist"].required is False

    dataset = registry.dataset(primary.dataset_ref)
    assert dataset.content_identity.workflow_baseline_package_sha256 == (
        "e40b3c7f3a5bde97b08cefbc986d4667bfaae461d8fb43c8df6abae00e8604d0"
    )
    assert dataset.content_identity.server_wsl_package_sha256 == (
        "6f0d5726a6a3338dd35f4dbd8b96f3427923f3d484073d7e5a5eb3c7cc4e1675"
    )
    assert dataset.content_identity.raw_archive_member_manifest_sha256 == (
        "46d5c6cd90634c236a0ce16db02dfe1e982fa67f59b03d6908a5af481394c985"
    )

    replication = requirements["dataset:geo:GSE131928@2026-08-01"]
    replication_artifacts = {
        item.artifact_id: item for item in replication.artifact_requirements
    }
    assert replication_artifacts["raw-archive"].required is True
    assert replication_artifacts["adult-pediatric-annotation"].required is True
    replication_dataset = registry.dataset(replication.dataset_ref)
    assert replication_dataset.lifecycle_status.value == "frozen"
    assert replication_dataset.content_identity.identity_status == "verified"
    assert replication_dataset.content_identity.raw_archive_member_count == 2
    assert replication_dataset.content_identity.raw_archive_member_manifest_sha256 == (
        "fdb2b8f6caab51a6c99901139bff52e90fdb620729eb51708f40d94dc6cc1f55"
    )
    assert replication_dataset.content_identity.workflow_baseline_package_sha256 == (
        "f0edd741959b8c4ab375df7aec95c696095894bc5b9752e0ad3a977a978d602e"
    )
    assert replication_dataset.content_identity.server_wsl_package_sha256 == (
        "f0edd741959b8c4ab375df7aec95c696095894bc5b9752e0ad3a977a978d602e"
    )

    r_environment = registry.environment("environment:npj-gene-r@1")
    py_environment = registry.environment("environment:npj-gene-py@1")
    assert r_environment.lock_digest == (
        "sha256:bcaddc2c0e3aa04b76a8b7ada6d50a59c92530b27ca16eb18ead9e077e9df296"
    )
    assert py_environment.lock_digest == (
        "sha256:334ec498a12f8bcf5ff045756d468e2b5ab9a65fbb4f15f06925920a03a84e3e"
    )
    assert r_environment.probes[0].type == "conda_lock"
    assert py_environment.probes[0].type == "conda_lock"


def test_frozen_dataset_requires_verified_complete_identity():
    payload = {
        "schema_version": "spc.dataset-manifest.v1",
        "dataset_ref": "dataset:geo:GSE1@1",
        "lifecycle_status": "frozen",
        "source_identity": {
            "namespace": "geo",
            "accession": "GSE1",
            "official_url": "https://example.invalid/GSE1",
        },
        "source_snapshot": {
            "observed_at": "2026-08-01T00:00:00Z",
            "remote_snapshot_digest": "sha256:" + "a" * 64,
        },
        "artifacts": [],
        "acquisition_sources": [
            {"source_id": "fixture", "mode": "automatic", "priority": 10}
        ],
        "content_identity": {
            "identity_status": "blocked_pending_member_audit",
            "raw_archive_member_count": None,
            "raw_archive_member_manifest_sha256": None,
            "workflow_baseline_package_sha256": None,
            "server_wsl_package_sha256": None,
        },
    }

    with pytest.raises(ValueError, match="已验证的内容身份"):
        DatasetManifest.model_validate(attach_content_digest(payload))


def test_all_builtin_contract_digests_are_valid():
    root = builtin_registry_root()
    registry = WorkflowRegistryStore(root)
    verify_content_digest(registry.registry)
    for reference in registry.registry.workflows:
        verify_content_digest(registry.workflow(reference))
    for reference in registry.registry.environments:
        verify_content_digest(registry.environment(reference))
    for reference in registry.registry.datasets:
        verify_content_digest(registry.dataset(reference))


def test_committed_json_schemas_match_models(tmp_path):
    generated = export_schemas(tmp_path)
    committed_root = builtin_registry_root() / "schemas"
    assert {path.name for path in generated} == set(SCHEMA_MODELS)
    for generated_path in generated:
        committed = json.loads(
            (committed_root / generated_path.name).read_text(encoding="utf-8")
        )
        actual = json.loads(generated_path.read_text(encoding="utf-8"))
        assert actual == committed
