from __future__ import annotations

import hashlib
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "research_harness"
MODULE_PATH = PACKAGE_ROOT / "_selfdev/read_only_inventory_manifest.py"
_ISOLATED_MODULE_NAME = "_rh_test_read_only_inventory_manifest_finalizer"
_CANONICAL_MODULE_NAMES = (
    "research_harness",
    "research_harness._selfdev",
    "research_harness._selfdev.read_only_inventory_manifest",
)
_MISSING_MODULE = object()


def _canonical_module_state() -> tuple[object, ...]:
    return tuple(
        sys.modules.get(name, _MISSING_MODULE) for name in _CANONICAL_MODULE_NAMES
    )


def _load_isolated_manifest_module():
    canonical_before = _canonical_module_state()
    spec = importlib.util.spec_from_file_location(_ISOLATED_MODULE_NAME, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("isolated manifest module loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_ISOLATED_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_ISOLATED_MODULE_NAME, None)
        raise
    if _canonical_module_state() != canonical_before:
        raise RuntimeError("isolated manifest module changed canonical imports")
    return module


inventory_module = _load_isolated_manifest_module()
InventoryClassification = inventory_module.InventoryClassification
InventoryManifestError = inventory_module.InventoryManifestError
InventoryRecord = inventory_module.InventoryRecord
InventorySourceRecord = inventory_module.InventorySourceRecord
InventorySourceSpec = inventory_module.InventorySourceSpec
_finalize_inventory_manifest = inventory_module._finalize_inventory_manifest
build_inventory_manifest = inventory_module.build_inventory_manifest


def _source_record() -> InventorySourceRecord:
    return InventorySourceRecord(
        source_id="logical-source",
        host_id="test-host",
        root_locator="snapshot:logical-source",
        source_type="logical_registry",
        authority="source_snapshot",
        access_class="read_only",
        root_resolution="direct",
        root_fingerprint="1:2",
    )


def _logical_record() -> InventoryRecord:
    return InventoryRecord(
        record_id="logical-source:row-1",
        source_id="logical-source",
        relative_path="row-1",
        work_type="unknown",
        record_classes=("source_record",),
        byte_size=0,
        mtime_ns=0,
        permission_mode="0000",
        sha256=hashlib.sha256(b"row-1").hexdigest(),
        resolved_work_key=None,
        identity_authority=None,
        identifiers=(),
        topic_id=None,
        parse_quality_passed=False,
    )


def _finalize(**overrides):
    record = _logical_record()
    values = {
        "snapshot_id": "snapshot",
        "observed_at": "2026-08-05T00:00:00Z",
        "source_records": (_source_record(),),
        "records": (record,),
        "issues": (),
        "files_seen": 1,
        "records_emitted": 1,
        "directories_scanned": 0,
        "source_record_basis": "logical_row",
    }
    return _finalize_inventory_manifest(**{**values, **overrides})


def test_private_finalizer_rejects_invalid_source_record_basis() -> None:
    with pytest.raises(InventoryManifestError) as captured:
        _finalize(source_record_basis="unknown")

    assert captured.value.code == "invalid_source_record_basis"


def test_private_finalizer_rejects_records_emitted_mismatch() -> None:
    with pytest.raises(InventoryManifestError) as captured:
        _finalize(records_emitted=2)

    assert captured.value.code == "records_emitted_mismatch"


def test_private_finalizer_preserves_logical_row_basis_and_digest() -> None:
    first = _finalize(observed_at="2026-08-05T00:00:00Z")
    second = _finalize(observed_at="2026-08-06T00:00:00Z")

    assert first.counts.source_record_count.value == 1
    assert first.counts.source_record_count.basis == "logical_row"
    assert first.coverage.records_emitted == 1
    assert first.manifest_sha256 == second.manifest_sha256


def _pdf_source(root: Path, *, overrides=()) -> InventorySourceSpec:
    return InventorySourceSpec(
        source_id="pdf-source",
        host_id="test-host",
        root=root,
        root_locator="snapshot:pdf-source",
        source_type="paper_asset_cache",
        authority="source_snapshot",
        access_class="read_only",
        default_classification=None,
        path_classifications=overrides,
    )


def _pdf_classification() -> InventoryClassification:
    return InventoryClassification(
        record_classes=("pdf_asset", "source_record"),
        work_type="academic_paper",
    )


def test_filesystem_builder_retains_physical_file_basis(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "paper.pdf").write_bytes(b"%PDF-1.7\n%%EOF\n")

    manifest = build_inventory_manifest(
        sources=(
            replace(
                _pdf_source(root),
                default_classification=_pdf_classification(),
            ),
        ),
        snapshot_id="snapshot",
        observed_at="2026-08-05T00:00:00Z",
    )

    assert manifest.counts.source_record_count.value == 1
    assert manifest.counts.source_record_count.basis == "physical_file"


def test_present_override_issue_is_not_also_reported_missing(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "bad.pdf").write_bytes(b"plain text")

    manifest = build_inventory_manifest(
        sources=(_pdf_source(root, overrides=(("bad.pdf", _pdf_classification()),)),),
        snapshot_id="snapshot",
        observed_at="2026-08-05T00:00:00Z",
        record_error_policy="issue",
    )

    assert [(issue.code, issue.relative_path) for issue in manifest.issues] == [
        ("invalid_pdf_signature", "bad.pdf")
    ]


def test_pdf_signature_must_start_at_byte_zero(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "prefixed.pdf").write_bytes(b"prefix%PDF-1.7\n%%EOF\n")

    with pytest.raises(InventoryManifestError) as captured:
        build_inventory_manifest(
            sources=(
                replace(
                    _pdf_source(root),
                    default_classification=_pdf_classification(),
                ),
            ),
            snapshot_id="snapshot",
            observed_at="2026-08-05T00:00:00Z",
        )

    assert captured.value.code == "invalid_pdf_signature"
