from __future__ import annotations

import errno
import hashlib
import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "research_harness"
MODULE_PATH = PACKAGE_ROOT / "_selfdev/read_only_inventory_manifest.py"
_ISOLATED_MODULE_NAME = "_rh_test_read_only_inventory_manifest_shared"
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
INVENTORY_MANIFEST_SCHEMA_VERSION = inventory_module.INVENTORY_MANIFEST_SCHEMA_VERSION
RECORD_LEVEL_ERROR_CODES = inventory_module.RECORD_LEVEL_ERROR_CODES
InventoryClassification = inventory_module.InventoryClassification
InventoryIssue = inventory_module.InventoryIssue
InventoryManifestError = inventory_module.InventoryManifestError
InventorySourceSpec = inventory_module.InventorySourceSpec
build_inventory_manifest = inventory_module.build_inventory_manifest
inventory_manifest_to_dict = inventory_module.inventory_manifest_to_dict
reconcile_inventory_manifests = inventory_module.reconcile_inventory_manifests
serialize_inventory_manifest = inventory_module.serialize_inventory_manifest


RESOLVER = "library_identity_resolver"

requires_unprivileged = pytest.mark.skipif(
    os.geteuid() == 0, reason="permission-denied paths cannot be exercised as root"
)


def _write_pdf(path: Path, body: bytes = b"fixture") -> bytes:
    content = b"%PDF-1.7\n" + body + b"\n%%EOF\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _pdf_classification(**kwargs) -> InventoryClassification:
    return InventoryClassification(
        record_classes=("pdf_asset",), work_type="academic_paper", **kwargs
    )


def _source(
    root: Path,
    *,
    source_id: str = "pku-ts-pdf-cache",
    default: InventoryClassification | None = None,
    overrides: tuple[tuple[str, InventoryClassification], ...] = (),
) -> InventorySourceSpec:
    return InventorySourceSpec(
        source_id=source_id,
        host_id="pku",
        root=root,
        root_locator=f"pku:{root.name}",
        source_type="paper_asset_cache",
        authority="source_snapshot",
        access_class="internal_research",
        default_classification=default,
        path_classifications=overrides,
    )


def _build(
    *sources: InventorySourceSpec, observed_at: str = "2026-08-04T02:00:00Z", **kwargs
):
    return build_inventory_manifest(
        sources=sources,
        snapshot_id="pku-library-2026-08-04",
        observed_at=observed_at,
        **kwargs,
    )


# --------------------------------------------------------------------------
# Core contract
# --------------------------------------------------------------------------


def test_builds_deterministic_read_only_manifest_with_explicit_authority(
    tmp_path: Path,
):
    root = tmp_path / "pdfs"
    second_content = _write_pdf(root / "b.pdf", b"second")
    first_content = _write_pdf(root / "nested" / "a.pdf", b"first")
    before = {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }
    classification = _pdf_classification()

    first = _build(_source(root, default=classification))
    second = _build(_source(root, default=classification))
    later_scan = _build(
        _source(root, default=classification),
        observed_at="2026-08-04T03:00:00Z",
    )
    payload = inventory_manifest_to_dict(first)

    assert first == second
    assert serialize_inventory_manifest(first) == serialize_inventory_manifest(second)
    assert later_scan.records == first.records
    assert later_scan.manifest_sha256 == first.manifest_sha256
    assert serialize_inventory_manifest(later_scan) != serialize_inventory_manifest(
        first
    )
    assert payload["schema_version"] == INVENTORY_MANIFEST_SCHEMA_VERSION
    assert payload["platform"] == "posix"
    assert payload["sources"][0]["authority"] == "source_snapshot"
    assert [record["relative_path"] for record in payload["records"]] == [
        "b.pdf",
        "nested/a.pdf",
    ]
    assert payload["records"][0]["sha256"] == hashlib.sha256(second_content).hexdigest()
    assert payload["records"][1]["sha256"] == hashlib.sha256(first_content).hexdigest()
    assert payload["manifest_sha256"] == first.manifest_sha256
    assert {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    } == before


def test_signature_probe_survives_reads_larger_than_the_probe_window(tmp_path: Path):
    root = tmp_path / "big"
    _write_pdf(root / "large.pdf", b"x" * (4 * 1024 * 1024))

    manifest = _build(_source(root, default=_pdf_classification()))

    assert manifest.counts.pdf_asset_count.value == 1
    assert manifest.coverage.complete is True


# --------------------------------------------------------------------------
# Root resolution policy
# --------------------------------------------------------------------------


def test_symlinked_root_component_is_resolved_once_and_recorded_as_evidence(
    tmp_path: Path,
):
    real_root = tmp_path / "real_store"
    _write_pdf(real_root / "a.pdf")
    linked_root = tmp_path / "linked_store"
    linked_root.symlink_to(real_root, target_is_directory=True)
    classification = _pdf_classification()

    direct = _build(_source(real_root, default=classification))
    through_link = _build(_source(linked_root, default=classification))

    assert direct.sources[0].root_resolution == "direct"
    assert through_link.sources[0].root_resolution == "resolved"
    assert (
        direct.sources[0].root_fingerprint == through_link.sources[0].root_fingerprint
    )
    assert [record.sha256 for record in direct.records] == [
        record.sha256 for record in through_link.records
    ]


def test_resolution_does_not_permit_following_links_inside_the_source(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "outside.pdf"
    _write_pdf(outside)
    (root / "link.pdf").symlink_to(outside)

    with pytest.raises(InventoryManifestError, match="unsupported_file_type"):
        _build(_source(root, default=_pdf_classification()))


def test_root_swap_to_symlink_fails_before_any_external_file_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    outside = tmp_path / "outside"
    root.mkdir()
    _write_pdf(outside / "secret.pdf", b"must-not-be-read")
    original_open = inventory_module.os.open
    original_read = inventory_module.os.read
    swapped = False
    read_calls: list[int] = []

    def swapping_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and path == root.name and kwargs.get("dir_fd") is not None:
            root.rmdir()
            root.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    def recording_read(descriptor: int, size: int) -> bytes:
        read_calls.append(descriptor)
        return original_read(descriptor, size)

    monkeypatch.setattr(inventory_module.os, "open", swapping_open)
    monkeypatch.setattr(inventory_module.os, "read", recording_read)

    with pytest.raises(InventoryManifestError, match="source_root_unreadable"):
        _build(_source(root, default=_pdf_classification()))

    assert swapped is True
    assert read_calls == []


def test_os_errors_do_not_echo_absolute_source_paths(tmp_path: Path):
    missing_root = tmp_path / "private" / "missing"

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(missing_root, default=None))

    assert exc_info.value.code == "source_root_unreadable"
    assert str(missing_root) not in str(exc_info.value)


def test_non_posix_platform_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    root = tmp_path / "source"
    _write_pdf(root / "a.pdf")
    monkeypatch.setattr(inventory_module.os, "name", "nt")

    with pytest.raises(InventoryManifestError, match="unsupported_platform"):
        _build(_source(root, default=_pdf_classification()))


# --------------------------------------------------------------------------
# Five counts: basis, unit, state
# --------------------------------------------------------------------------


def test_keeps_all_five_count_classes_separate_and_marks_partial_identity(
    tmp_path: Path,
):
    root = tmp_path / "mixed"
    _write_pdf(root / "paper-a.pdf")
    (root / "paper-a.json").write_text('{"text": "parsed"}\n', encoding="utf-8")
    (root / "registry-1.json").write_text("{}\n", encoding="utf-8")
    (root / "registry-2.json").write_text("{}\n", encoding="utf-8")
    (root / "topic-a.json").write_text("{}\n", encoding="utf-8")
    (root / "topic-b.json").write_text("{}\n", encoding="utf-8")
    overrides = (
        (
            "paper-a.pdf",
            _pdf_classification(
                resolved_work_key="work:a",
                identity_authority=RESOLVER,
                identifiers=("doi:10.1/a",),
            ),
        ),
        (
            "paper-a.json",
            InventoryClassification(
                record_classes=("parsed_fulltext",),
                work_type="derived_parse",
                resolved_work_key="work:a",
                identity_authority=RESOLVER,
                parse_quality_passed=True,
            ),
        ),
        (
            "registry-1.json",
            InventoryClassification(
                record_classes=("source_record", "canonical_paper"),
                work_type="academic_paper",
                resolved_work_key="work:a",
                identity_authority=RESOLVER,
            ),
        ),
        (
            "registry-2.json",
            InventoryClassification(
                record_classes=("source_record", "canonical_paper"),
                work_type="academic_paper",
            ),
        ),
        (
            "topic-a.json",
            InventoryClassification(
                record_classes=("topic_membership",),
                work_type="topic_link",
                resolved_work_key="work:a",
                identity_authority=RESOLVER,
                topic_id="time-series",
            ),
        ),
        (
            "topic-b.json",
            InventoryClassification(
                record_classes=("topic_membership",),
                work_type="topic_link",
                resolved_work_key="work:a",
                identity_authority=RESOLVER,
                topic_id="automation-research",
            ),
        ),
    )

    manifest = _build(_source(root, default=None, overrides=overrides))
    counts = inventory_manifest_to_dict(manifest)["counts"]

    assert counts["source_record_count"]["value"] == 2
    assert counts["canonical_paper_count"]["value"] is None
    assert counts["canonical_paper_count"]["state"] == "not_computed"
    assert counts["pdf_asset_count"]["value"] == 1
    assert counts["parsed_fulltext_count"]["value"] == 1
    assert counts["topic_membership_count"]["value"] == 2
    assert counts["topic_membership_count"]["state"] == "computed"
    assert "canonical_identity_incomplete" in manifest.diagnostics


def test_every_count_declares_a_basis_and_unit_so_they_cannot_be_compared(
    tmp_path: Path,
):
    root = tmp_path / "units"
    _write_pdf(root / "v1.pdf", b"one")
    _write_pdf(root / "v2.pdf", b"two")
    (root / "grobid.json").write_text("g", encoding="utf-8")
    (root / "mineru.json").write_text("m", encoding="utf-8")
    asset = _pdf_classification(resolved_work_key="work:a", identity_authority=RESOLVER)
    parse = InventoryClassification(
        record_classes=("parsed_fulltext",),
        work_type="derived_parse",
        resolved_work_key="work:a",
        identity_authority=RESOLVER,
        parse_quality_passed=True,
    )
    overrides = (
        ("v1.pdf", asset),
        ("v2.pdf", asset),
        ("grobid.json", parse),
        ("mineru.json", parse),
    )

    counts = _build(_source(root, overrides=overrides)).counts

    # Two versions of one work and two parsers of one work are two assets and
    # two parse artifacts, not two works. The basis/unit pair says so.
    assert counts.pdf_asset_count.value == 2
    assert counts.pdf_asset_count.basis == "unique_content_hash"
    assert counts.pdf_asset_count.unit == "content_asset"
    assert "not_comparable_to_canonical_paper_count" in counts.pdf_asset_count.caveats
    assert (
        "distinct_versions_of_one_work_count_separately"
        in counts.pdf_asset_count.caveats
    )
    assert counts.parsed_fulltext_count.value == 2
    assert counts.parsed_fulltext_count.unit == "parsed_artifact"
    assert (
        "multiple_parsers_of_one_work_count_separately"
        in counts.parsed_fulltext_count.caveats
    )
    units = {getattr(counts, field).unit for field in counts.__dataclass_fields__}
    assert len(units) == len(counts.__dataclass_fields__)


def test_source_local_identity_never_produces_a_canonical_paper_count(tmp_path: Path):
    root = tmp_path / "adapter"
    _write_pdf(root / "paper.pdf")
    source_local = InventoryClassification(
        record_classes=("canonical_paper", "pdf_asset"),
        work_type="academic_paper",
        resolved_work_key="row-17",
        identity_authority="source_local",
    )

    manifest = _build(_source(root, default=source_local))

    assert manifest.counts.canonical_paper_count.value is None
    assert manifest.counts.canonical_paper_count.state == "not_computed"
    assert (
        "requires_resolver_identity_authority_on_every_record"
        in manifest.counts.canonical_paper_count.caveats
    )
    assert "canonical_identity_incomplete" in manifest.diagnostics


def test_incomplete_identity_never_reports_inflated_topic_membership_count(
    tmp_path: Path,
):
    root = tmp_path / "source"
    root.mkdir()
    (root / "left.json").write_text("{}\n", encoding="utf-8")
    (root / "right.json").write_text("{}\n", encoding="utf-8")
    membership = InventoryClassification(
        record_classes=("topic_membership",),
        work_type="topic_link",
        topic_id="time-series",
    )

    counts = inventory_manifest_to_dict(_build(_source(root, default=membership)))[
        "counts"
    ]

    assert counts["topic_membership_count"]["value"] is None
    assert counts["topic_membership_count"]["state"] == "not_computed"


def test_rejected_parse_quality_is_recorded_as_an_informational_issue(tmp_path: Path):
    root = tmp_path / "parses"
    root.mkdir()
    (root / "bad.json").write_text("{}", encoding="utf-8")
    rejected = InventoryClassification(
        record_classes=("parsed_fulltext",), work_type="derived_parse"
    )

    manifest = _build(_source(root, default=rejected))

    assert manifest.counts.parsed_fulltext_count.value == 0
    assert [issue.code for issue in manifest.issues] == [
        "parsed_fulltext_quality_rejected"
    ]
    # Informational issues do not make the scan incomplete.
    assert manifest.coverage.complete is True


# --------------------------------------------------------------------------
# Degraded mode, coverage, and the digest
# --------------------------------------------------------------------------


def test_record_errors_become_issues_and_mark_the_manifest_incomplete(tmp_path: Path):
    root = tmp_path / "cache"
    _write_pdf(root / "paper1.pdf", b"one")
    _write_pdf(root / "paper2.pdf", b"two")
    (root / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")

    manifest = _build(
        _source(root, default=_pdf_classification()), record_error_policy="issue"
    )

    assert manifest.coverage.files_seen == 3
    assert manifest.coverage.records_emitted == 2
    assert manifest.coverage.complete is False
    assert manifest.coverage.issue_codes == (("invalid_pdf_signature", 1),)
    assert [(issue.code, issue.relative_path) for issue in manifest.issues] == [
        ("invalid_pdf_signature", ".DS_Store")
    ]
    assert manifest.counts.pdf_asset_count.value == 2
    assert manifest.counts.pdf_asset_count.state == "degraded"
    assert "scan_coverage_incomplete" in manifest.counts.pdf_asset_count.caveats


def test_degraded_and_complete_manifests_never_share_a_digest(tmp_path: Path):
    clean = tmp_path / "clean"
    _write_pdf(clean / "paper1.pdf", b"one")
    dirty = tmp_path / "dirty"
    _write_pdf(dirty / "paper1.pdf", b"one")
    (dirty / "stray.txt").write_bytes(b"not a pdf")

    complete = _build(_source(clean, source_id="s", default=_pdf_classification()))
    degraded = _build(
        _source(dirty, source_id="s", default=_pdf_classification()),
        record_error_policy="issue",
    )

    assert complete.records[0].sha256 == degraded.records[0].sha256
    assert complete.coverage.complete is True
    assert degraded.coverage.complete is False
    assert complete.manifest_sha256 != degraded.manifest_sha256


@requires_unprivileged
def test_unreadable_subdirectory_is_reported_rather_than_silently_skipped(
    tmp_path: Path,
):
    root = tmp_path / "tree"
    _write_pdf(root / "visible.pdf")
    blocked = root / "blocked"
    _write_pdf(blocked / "hidden.pdf")
    blocked.chmod(0o000)
    try:
        manifest = _build(
            _source(root, default=_pdf_classification()), record_error_policy="issue"
        )
    finally:
        blocked.chmod(0o755)

    assert manifest.coverage.complete is False
    assert ("source_directory_unreadable", "blocked") in [
        (issue.code, issue.relative_path) for issue in manifest.issues
    ]
    assert [record.relative_path for record in manifest.records] == ["visible.pdf"]


@requires_unprivileged
def test_unreadable_file_is_reported_rather_than_silently_skipped(tmp_path: Path):
    root = tmp_path / "tree"
    _write_pdf(root / "ok.pdf")
    locked = root / "locked.pdf"
    _write_pdf(locked)
    locked.chmod(0o000)
    try:
        manifest = _build(
            _source(root, default=_pdf_classification()), record_error_policy="issue"
        )
    finally:
        locked.chmod(0o644)

    assert ("source_file_unreadable", "locked.pdf") in [
        (issue.code, issue.relative_path) for issue in manifest.issues
    ]
    assert manifest.coverage.files_seen == 2
    assert manifest.coverage.records_emitted == 1


def test_tamper_signals_stay_fatal_even_under_the_issue_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    paper_path = root / "paper.pdf"
    _write_pdf(paper_path)
    other_path = root / "other.pdf"
    _write_pdf(other_path, b"other")
    original_hash = inventory_module._hash_stable_file_at

    def touching_hash(*args, **kwargs):
        result = original_hash(*args, **kwargs)
        os.utime(other_path, ns=(1, 1))
        return result

    monkeypatch.setattr(inventory_module, "_hash_stable_file_at", touching_hash)

    with pytest.raises(InventoryManifestError, match="source_changed_during_scan"):
        _build(
            _source(root, default=_pdf_classification()), record_error_policy="issue"
        )

    assert "source_changed_during_scan" not in RECORD_LEVEL_ERROR_CODES


def test_unclassified_file_aborts_under_the_default_fatal_policy(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "unclassified.txt").write_bytes(b"data")

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=None))

    assert exc_info.value.code == "unclassified_inventory_file"
    assert exc_info.value.relative_path == "unclassified.txt"


def test_invalid_pdf_signature_aborts_under_the_default_fatal_policy(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "not-a-pdf.pdf").write_bytes(b"plain text")

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert exc_info.value.code == "invalid_pdf_signature"
    assert exc_info.value.relative_path == "not-a-pdf.pdf"


# --------------------------------------------------------------------------
# Real TOCTOU detection (no wholesale monkeypatch of the hashing helper)
# --------------------------------------------------------------------------


def test_file_swapped_between_listing_and_open_is_detected_before_any_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    target = root / "paper.pdf"
    _write_pdf(target, b"original")
    original_open = inventory_module.os.open
    original_read = inventory_module.os.read
    swapped = False
    read_calls: list[int] = []

    def swapping_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and path == "paper.pdf" and kwargs.get("dir_fd") is not None:
            swapped = True
            target.unlink()
            _write_pdf(target, b"substituted-content")
        return original_open(path, flags, *args, **kwargs)

    def recording_read(descriptor: int, size: int) -> bytes:
        read_calls.append(descriptor)
        return original_read(descriptor, size)

    monkeypatch.setattr(inventory_module.os, "open", swapping_open)
    monkeypatch.setattr(inventory_module.os, "read", recording_read)

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert swapped is True
    assert exc_info.value.code == "source_file_changed"
    # The substituted bytes were never hashed.
    assert read_calls == []


def test_file_mutated_mid_read_is_detected_after_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    target = root / "paper.pdf"
    _write_pdf(target, b"y" * (2 * 1024 * 1024))
    original_read = inventory_module.os.read
    mutated = False

    def mutating_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        chunk = original_read(descriptor, size)
        if chunk and not mutated:
            mutated = True
            os.utime(target, ns=(1, 1))
        return chunk

    monkeypatch.setattr(inventory_module.os, "read", mutating_read)

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert mutated is True
    assert exc_info.value.code == "source_file_changed"


def test_entry_removed_between_listing_and_stat_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    _write_pdf(root / "keep.pdf")
    doomed = root / "vanish.pdf"
    _write_pdf(doomed)
    original_stat = inventory_module.os.stat
    removed = False

    def removing_stat(path, *args, **kwargs):
        nonlocal removed
        if (
            not removed
            and kwargs.get("dir_fd") is not None
            and os.fsdecode(path) == "vanish.pdf"
        ):
            removed = True
            doomed.unlink()
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(inventory_module.os, "stat", removing_stat)

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert removed is True
    assert exc_info.value.code in {
        "source_entry_unreadable",
        "source_changed_during_scan",
    }


def test_directory_replaced_between_listing_and_open_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    child = root / "child"
    _write_pdf(child / "a.pdf")
    original_open_child_directory = inventory_module._open_child_directory
    swapped = False

    def swapping_open_child_directory(*args, **kwargs):
        nonlocal swapped
        if not swapped and kwargs.get("relative_path") == "child":
            swapped = True
            (child / "a.pdf").unlink()
            child.rmdir()
            (root / "child").write_bytes(b"replacement")
        return original_open_child_directory(*args, **kwargs)

    monkeypatch.setattr(
        inventory_module,
        "_open_child_directory",
        swapping_open_child_directory,
    )

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert swapped is True
    assert exc_info.value.code == "source_changed_during_scan"
    assert exc_info.value.relative_path == "child"


def test_directory_removed_between_listing_and_open_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    child = root / "child"
    child.mkdir(parents=True)
    _write_pdf(root / "a.pdf")
    original_open = inventory_module.os.open
    removed = False

    def removing_open(path, flags, *args, **kwargs):
        nonlocal removed
        if not removed and path == "child" and kwargs.get("dir_fd") is not None:
            removed = True
            child.rmdir()
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(inventory_module.os, "open", removing_open)

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert removed is True
    assert exc_info.value.code == "source_changed_during_scan"


def test_new_entry_appearing_during_the_scan_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    _write_pdf(root / "a.pdf")
    original_hash = inventory_module._hash_stable_file_at
    added = False

    def adding_hash(*args, **kwargs):
        nonlocal added
        result = original_hash(*args, **kwargs)
        if not added:
            added = True
            _write_pdf(root / "b.pdf", b"appeared")
        return result

    monkeypatch.setattr(inventory_module, "_hash_stable_file_at", adding_hash)

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert added is True
    assert exc_info.value.code == "source_changed_during_scan"


def test_directory_metadata_drift_with_a_stable_listing_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    _write_pdf(root / "a.pdf")
    original_hash = inventory_module._hash_stable_file_at
    touched = False

    def touching_hash(*args, **kwargs):
        nonlocal touched
        result = original_hash(*args, **kwargs)
        if not touched:
            touched = True
            os.utime(root, ns=(1, 1))
        return result

    monkeypatch.setattr(inventory_module, "_hash_stable_file_at", touching_hash)

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert touched is True
    assert exc_info.value.code == "source_changed_during_scan"
    assert exc_info.value.relative_path == "."


def test_reverification_stat_failure_is_reported_with_the_full_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    _write_pdf(root / "nested" / "deep.pdf")
    original_stat = inventory_module.os.stat

    def failing_stat(path, *args, **kwargs):
        if path == "deep.pdf" and kwargs.get("dir_fd") is not None:
            raise OSError(5, "simulated")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(inventory_module.os, "stat", failing_stat)

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert exc_info.value.code == "source_changed_during_scan"
    # The full source-relative path, not the bare basename.
    assert exc_info.value.relative_path == "nested/deep.pdf"


def test_reverification_listing_failure_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    _write_pdf(root / "a.pdf")
    original_scandir = inventory_module.os.scandir
    calls = 0

    def failing_scandir(target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(5, "simulated")
        return original_scandir(target)

    monkeypatch.setattr(inventory_module.os, "scandir", failing_scandir)

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert exc_info.value.code == "source_changed_during_scan"


def test_root_replaced_after_the_scan_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    _write_pdf(root / "a.pdf")
    original_hash = inventory_module._hash_stable_file_at
    swapped = False

    def swapping_hash(*args, **kwargs):
        nonlocal swapped
        result = original_hash(*args, **kwargs)
        if not swapped:
            swapped = True
            os.utime(root, ns=(1, 1))
        return result

    monkeypatch.setattr(inventory_module, "_hash_stable_file_at", swapping_hash)

    with pytest.raises(InventoryManifestError, match="source_changed_during_scan"):
        _build(_source(root, default=_pdf_classification()))


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------


def test_content_hash_deduplicates_assets_but_never_merges_work_identity(
    tmp_path: Path,
):
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    shared = _write_pdf(left_root / "paper.pdf")
    right_root.mkdir()
    (right_root / "paper-copy.pdf").write_bytes(shared)
    left = _build(
        _source(
            left_root,
            source_id="left",
            default=_pdf_classification(
                resolved_work_key="work:a",
                identity_authority=RESOLVER,
                identifiers=("doi:10.1/a",),
            ),
        )
    )
    right = _build(
        _source(
            right_root,
            source_id="right",
            default=_pdf_classification(
                resolved_work_key="work:b",
                identity_authority=RESOLVER,
                identifiers=("doi:10.1/b",),
            ),
        )
    )

    report = reconcile_inventory_manifests(left, right)

    assert report.exact_asset_hash_matches == (
        ("left:paper.pdf", "right:paper-copy.pdf"),
    )
    assert report.identity_conflicts == (("left:paper.pdf", "right:paper-copy.pdf"),)
    assert report.auto_merge_count == 0
    assert report.manual_review_count == 1
    assert report.identity_comparison_state == "computed"


def test_same_identity_with_different_content_is_a_version_candidate(
    tmp_path: Path,
):
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    _write_pdf(left_root / "v1.pdf", b"version-one")
    _write_pdf(right_root / "v2.pdf", b"version-two")
    classification = _pdf_classification(
        resolved_work_key="work:a",
        identity_authority=RESOLVER,
        identifiers=("arxiv:2601.00001",),
    )

    report = reconcile_inventory_manifests(
        _build(_source(left_root, source_id="left", default=classification)),
        _build(_source(right_root, source_id="right", default=classification)),
    )

    assert report.version_candidates == (("left:v1.pdf", "right:v2.pdf"),)
    assert report.identity_conflicts == ()
    assert report.auto_merge_count == 0
    assert report.identity_comparison_state == "computed"


def test_unresolved_identity_reports_not_comparable_instead_of_a_clean_zero(
    tmp_path: Path,
):
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    _write_pdf(left_root / "v1.pdf", b"one")
    _write_pdf(right_root / "v2.pdf", b"two")

    report = reconcile_inventory_manifests(
        _build(_source(left_root, source_id="left", default=_pdf_classification())),
        _build(_source(right_root, source_id="right", default=_pdf_classification())),
    )

    assert report.manual_review_count == 0
    assert report.identity_comparison_state == "not_comparable"
    assert report.comparable_left_count == 0
    assert report.comparable_right_count == 0
    assert report.unresolved_left_count == 1
    assert report.unresolved_right_count == 1


def test_duplicate_content_inside_one_manifest_is_surfaced(tmp_path: Path):
    root = tmp_path / "dup"
    _write_pdf(root / "a.pdf", b"same")
    _write_pdf(root / "copy.pdf", b"same")
    manifest = _build(_source(root, source_id="s", default=_pdf_classification()))

    report = reconcile_inventory_manifests(manifest, manifest)

    assert manifest.counts.pdf_asset_count.value == 1
    assert len(manifest.records) == 2
    assert report.duplicate_hash_groups_left == (("s:a.pdf", "s:copy.pdf"),)
    assert report.duplicate_hash_groups_right == (("s:a.pdf", "s:copy.pdf"),)


# --------------------------------------------------------------------------
# Validation raise sites
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"record_classes": ("nonsense",)}, "invalid_record_class"),
        ({"record_classes": ("pdf_asset", "pdf_asset")}, "duplicate_record_class"),
        ({"work_type": "  "}, "empty_work_type"),
        (
            {"resolved_work_key": "  ", "identity_authority": RESOLVER},
            "empty_resolved_work_key",
        ),
        ({"resolved_work_key": "work:a"}, "resolved_work_key_without_authority"),
        ({"identity_authority": RESOLVER}, "identity_authority_without_work_key"),
        (
            {"resolved_work_key": "work:a", "identity_authority": " "},
            "empty_identity_authority",
        ),
        (
            {"record_classes": ("topic_membership",)},
            "topic_membership_missing_topic_id",
        ),
        ({"topic_id": "t"}, "topic_id_without_membership"),
        ({"parse_quality_passed": True}, "parse_quality_without_parsed_fulltext"),
        ({"identifiers": ("doi:1", " ")}, "invalid_identifier"),
        ({"identifiers": ("doi:1", "doi:1")}, "duplicate_identifier"),
    ],
)
def test_classification_validation_raise_sites(kwargs: dict, code: str):
    with pytest.raises(InventoryManifestError) as exc_info:
        InventoryClassification(**kwargs)

    assert exc_info.value.code == code


@pytest.mark.parametrize(
    ("field_name", "code"),
    [
        ("source_id", "empty_source_id"),
        ("host_id", "empty_host_id"),
        ("root_locator", "empty_root_locator"),
        ("source_type", "empty_source_type"),
        ("authority", "empty_authority"),
        ("access_class", "empty_access_class"),
    ],
)
def test_source_spec_requires_every_authority_field(
    field_name: str, code: str, tmp_path: Path
):
    fields = {
        "source_id": "s",
        "host_id": "h",
        "root": tmp_path,
        "root_locator": "loc",
        "source_type": "t",
        "authority": "a",
        "access_class": "c",
    }
    fields[field_name] = "   "

    with pytest.raises(InventoryManifestError) as exc_info:
        InventorySourceSpec(**fields)

    assert exc_info.value.code == code


@pytest.mark.parametrize(
    "relative_path",
    ["../outside.pdf", "/absolute.pdf", "", ".", "nested//a.pdf", "back\\slash.pdf"],
)
def test_unsafe_relative_classification_paths_are_rejected(
    relative_path: str, tmp_path: Path
):
    with pytest.raises(InventoryManifestError, match="unsafe_relative_path"):
        InventorySourceSpec(
            source_id="unsafe",
            host_id="local",
            root=tmp_path,
            root_locator="local:source",
            source_type="test",
            authority="cache",
            access_class="internal",
            path_classifications=((relative_path, _pdf_classification()),),
        )


def test_rejects_duplicate_source_ids_and_duplicate_path_overrides(tmp_path: Path):
    root = tmp_path / "source"
    _write_pdf(root / "paper.pdf")
    classification = _pdf_classification()
    source = _source(root, default=classification)

    with pytest.raises(InventoryManifestError, match="duplicate_source_id"):
        _build(source, source)

    with pytest.raises(InventoryManifestError, match="duplicate_path_classification"):
        _source(
            root,
            overrides=(("paper.pdf", classification), ("paper.pdf", classification)),
        )


def test_classification_override_for_a_missing_path_is_fatal(tmp_path: Path):
    root = tmp_path / "source"
    _write_pdf(root / "present.pdf")

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(
            _source(
                root,
                default=_pdf_classification(),
                overrides=(("absent.pdf", _pdf_classification()),),
            )
        )

    assert exc_info.value.code == "classification_path_missing"
    assert exc_info.value.relative_path == "absent.pdf"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"snapshot_id": " "}, "empty_snapshot_id"),
        ({"observed_at": " "}, "empty_observed_at"),
        ({"record_error_policy": "sometimes"}, "invalid_record_error_policy"),
    ],
)
def test_build_argument_validation_raise_sites(kwargs: dict, code: str, tmp_path: Path):
    call = {
        "sources": (),
        "snapshot_id": "snap",
        "observed_at": "2026-08-04T00:00:00Z",
        **kwargs,
    }

    with pytest.raises(InventoryManifestError) as exc_info:
        build_inventory_manifest(**call)

    assert exc_info.value.code == code


def test_issue_severity_is_validated():
    with pytest.raises(InventoryManifestError, match="invalid_issue_severity"):
        InventoryIssue(
            code="c", severity="catastrophic", source_id="s", relative_path="p"
        )


@pytest.mark.parametrize(
    ("raised_errno", "expected_code"),
    [
        (errno.EMFILE, "source_scan_resource_exhausted"),
        (errno.ENFILE, "source_scan_resource_exhausted"),
        (errno.EACCES, "source_file_unreadable"),
        (errno.ENOENT, "source_changed_during_scan"),
    ],
)
def test_open_failures_are_classified_by_what_they_actually_mean(
    raised_errno: int,
    expected_code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A descriptor shortage or a permission problem must not be reported as a
    tampering signal; only "the entry is no longer what the listing said" is."""

    root = tmp_path / "source"
    _write_pdf(root / "paper.pdf")
    original_open = inventory_module.os.open

    def failing_open(path, flags, *args, **kwargs):
        if path == "paper.pdf" and kwargs.get("dir_fd") is not None:
            raise OSError(raised_errno, os.strerror(raised_errno))
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(inventory_module.os, "open", failing_open)

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert exc_info.value.code == expected_code


def test_resource_exhaustion_is_fatal_even_under_the_issue_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "source"
    _write_pdf(root / "paper.pdf")
    original_open = inventory_module.os.open

    def exhausted_open(path, flags, *args, **kwargs):
        if path == "paper.pdf" and kwargs.get("dir_fd") is not None:
            raise OSError(errno.EMFILE, "too many open files")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(inventory_module.os, "open", exhausted_open)

    # A truncated scan caused by running out of descriptors must never be
    # downgraded into a "degraded but usable" manifest.
    with pytest.raises(InventoryManifestError, match="source_scan_resource_exhausted"):
        _build(
            _source(root, default=_pdf_classification()), record_error_policy="issue"
        )

    assert "source_scan_resource_exhausted" not in RECORD_LEVEL_ERROR_CODES


def test_unsupported_file_type_is_fatal_by_default(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    os.mkfifo(root / "pipe")

    with pytest.raises(InventoryManifestError) as exc_info:
        _build(_source(root, default=_pdf_classification()))

    assert exc_info.value.code == "unsupported_file_type"


# --------------------------------------------------------------------------
# Structural guards
# --------------------------------------------------------------------------


def test_every_raise_site_in_the_module_is_covered_by_a_test():
    """The value of this module is its fail-closed paths, so a coverage
    percentage is the wrong gate: assert instead that every distinct error code
    the module can raise is named somewhere in this test file."""

    source = MODULE_PATH.read_text(encoding="utf-8")
    raised_codes = set(
        re.findall(r'InventoryManifestError\(\s*\n?\s*"([a-z_]+)"', source)
    )
    # Codes reached indirectly: through helper parameters, through the f-string
    # in InventorySourceSpec, and through the errno classifier.
    raised_codes.update({"invalid_identifier", "duplicate_identifier"})
    raised_codes.update(
        f"empty_{field}"
        for field in (
            "source_id",
            "host_id",
            "root_locator",
            "source_type",
            "authority",
            "access_class",
        )
    )
    raised_codes.update(
        re.findall(
            r'return "([a-z_]+)"',
            source[source.index("def _classify_open_failure") :],
        )
    )
    tests = Path(__file__).read_text(encoding="utf-8") + (
        Path(__file__).with_name("test_read_only_inventory_manifest_finalizer.py")
    ).read_text(encoding="utf-8")
    uncovered = sorted(code for code in raised_codes if code not in tests)

    assert uncovered == [], f"error codes with no test: {uncovered}"


def test_module_declares_no_write_or_network_capability():
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "socket",
        "sqlite3",
        "requests",
        "httpx",
        "urllib",
        "shutil",
        "O_WRONLY",
        "O_CREAT",
        "os.remove",
        "os.write",
    ):
        assert forbidden not in source, f"unexpected capability: {forbidden}"
