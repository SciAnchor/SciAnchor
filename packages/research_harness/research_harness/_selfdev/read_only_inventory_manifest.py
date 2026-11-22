"""Private read-only inventory manifests for PGL migration planning.

This module is a private ``_selfdev`` helper. It is not exported from the package
root and has no CLI, MCP, HTTP, or Python facade entry point.

Scope boundary: this module observes bytes on disk. It never resolves work
identity. Callers supply an already-resolved ``resolved_work_key`` together with
the ``identity_authority`` that produced it; a key minted by a source-local
adapter can never be promoted into ``canonical_paper_count`` (see
``RESOLVER_IDENTITY_AUTHORITIES``).

Two properties are load bearing and are asserted per raise site in the focused
tests:

1. **Read-only, no-follow traversal.** The scanner binds a directory descriptor
   chain from ``/`` with ``O_NOFOLLOW | O_DIRECTORY`` and reads files through
   ``openat``-style relative opens. It compares the file's identity fingerprint
   after opening but *before* reading, so a swapped file's bytes are never
   hashed. Symlinks and special files inside a source are refused.

2. **No silent skip.** Every regular file either becomes a record or produces an
   ``InventoryIssue``. The ``coverage`` block records both totals and is part of
   the manifest digest, so a degraded manifest cannot be silently compared with
   a complete one.

Platform: POSIX. The traversal depends on ``dir_fd``, ``O_NOFOLLOW``, and
``O_DIRECTORY`` semantics and fails closed on platforms that lack them.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path, PurePosixPath
from typing import Literal


INVENTORY_MANIFEST_SCHEMA_VERSION = "pgl.read_only_inventory_manifest.v1"
INVENTORY_MANIFEST_HASH_CONTRACT = (
    "sha256:canonical-json:exclude-observed_at-and-manifest_sha256:"
    "include-coverage-and-issues:v2"
)
INVENTORY_MANIFEST_PLATFORM = "posix"

#: Identity authorities whose keys may be counted as canonical works. A
#: source-local adapter must declare ``source_local`` (or any other value) and
#: will never produce a canonical count, which keeps PGL00 from silently
#: standing in for the identity resolver.
RESOLVER_IDENTITY_AUTHORITIES = frozenset({"library_identity_resolver"})

_PDF_SIGNATURE = b"%PDF-"
_SIGNATURE_PROBE_BYTES = len(_PDF_SIGNATURE)
_READ_CHUNK_BYTES = 1024 * 1024

RecordClass = Literal[
    "source_record",
    "canonical_paper",
    "pdf_asset",
    "parsed_fulltext",
    "topic_membership",
]
VALID_RECORD_CLASSES = frozenset(
    {
        "source_record",
        "canonical_paper",
        "pdf_asset",
        "parsed_fulltext",
        "topic_membership",
    }
)

RecordErrorPolicy = Literal["fatal", "issue"]
IssueSeverity = Literal["info", "record"]

#: Error codes that describe a single file or subtree. Under
#: ``record_error_policy="issue"`` these are demoted to issues instead of
#: aborting the scan. Everything else stays fatal: configuration mistakes and
#: whole-source tamper signals must not be survivable.
RECORD_LEVEL_ERROR_CODES = frozenset(
    {
        "invalid_pdf_signature",
        "source_directory_unreadable",
        "source_entry_unreadable",
        "source_file_changed",
        "source_file_unreadable",
        "unclassified_inventory_file",
        "unsupported_file_type",
    }
)


class InventoryManifestError(ValueError):
    """Typed, fail-closed error raised by the private inventory scanner.

    ``detail`` is restricted to stable, caller-supplied tokens. OS error strings
    are attached as ``__cause__`` and never rendered into the message, so
    absolute source paths cannot leak through an error surface.
    """

    def __init__(
        self,
        code: str,
        *,
        source_id: str = "",
        relative_path: str = "",
        detail: str = "",
    ) -> None:
        self.code = code
        self.source_id = source_id
        self.relative_path = relative_path
        self.detail = detail
        context = ":".join(value for value in (source_id, relative_path) if value)
        message = code if not context else f"{code}: {context}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class InventoryIssue:
    """One non-fatal observation that kept a file out of the record set."""

    code: str
    severity: IssueSeverity
    source_id: str
    relative_path: str

    def __post_init__(self) -> None:
        if self.severity not in {"info", "record"}:
            raise InventoryManifestError("invalid_issue_severity", detail=self.severity)


@dataclass(frozen=True)
class InventoryClassification:
    """Explicit count and identity meaning assigned to one source file.

    ``resolved_work_key`` is an *input* to this module, never an output. It must
    be accompanied by the ``identity_authority`` that produced it.
    """

    record_classes: tuple[RecordClass, ...] = ()
    work_type: str = "unknown"
    resolved_work_key: str | None = None
    identity_authority: str | None = None
    identifiers: tuple[str, ...] = ()
    topic_id: str | None = None
    parse_quality_passed: bool = False

    def __post_init__(self) -> None:
        unknown = set(self.record_classes) - VALID_RECORD_CLASSES
        if unknown:
            raise InventoryManifestError(
                "invalid_record_class", detail=",".join(sorted(unknown))
            )
        if len(self.record_classes) != len(set(self.record_classes)):
            raise InventoryManifestError("duplicate_record_class")
        if not self.work_type.strip():
            raise InventoryManifestError("empty_work_type")
        if self.resolved_work_key is not None and not self.resolved_work_key.strip():
            raise InventoryManifestError("empty_resolved_work_key")
        if self.resolved_work_key and not self.identity_authority:
            raise InventoryManifestError("resolved_work_key_without_authority")
        if self.identity_authority and not self.resolved_work_key:
            raise InventoryManifestError("identity_authority_without_work_key")
        if self.identity_authority is not None and not self.identity_authority.strip():
            raise InventoryManifestError("empty_identity_authority")
        if "topic_membership" in self.record_classes and not self.topic_id:
            raise InventoryManifestError("topic_membership_missing_topic_id")
        if self.topic_id and "topic_membership" not in self.record_classes:
            raise InventoryManifestError("topic_id_without_membership")
        if self.parse_quality_passed and "parsed_fulltext" not in self.record_classes:
            raise InventoryManifestError("parse_quality_without_parsed_fulltext")
        _validate_nonempty_values(
            self.identifiers,
            code="invalid_identifier",
            duplicate_code="duplicate_identifier",
        )


@dataclass(frozen=True)
class InventorySourceSpec:
    """Read-only filesystem source and its explicit authority classification."""

    source_id: str
    host_id: str
    root: Path
    root_locator: str
    source_type: str
    authority: str
    access_class: str
    default_classification: InventoryClassification | None = None
    path_classifications: tuple[tuple[str, InventoryClassification], ...] = ()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("host_id", self.host_id),
            ("root_locator", self.root_locator),
            ("source_type", self.source_type),
            ("authority", self.authority),
            ("access_class", self.access_class),
        ):
            if not value.strip():
                raise InventoryManifestError(f"empty_{field_name}")
        paths = tuple(path for path, _classification in self.path_classifications)
        for relative_path in paths:
            _validate_relative_path(relative_path)
        if len(paths) != len(set(paths)):
            raise InventoryManifestError("duplicate_path_classification")


@dataclass(frozen=True)
class InventorySourceRecord:
    """Source authority plus the evidence of how its root was reached.

    ``root_resolution`` is ``direct`` when the caller-supplied path contained no
    symlinked component, and ``resolved`` when one or more components were
    resolved before the no-follow traversal began. ``root_fingerprint`` pins the
    device and inode actually scanned so two runs can be compared even when the
    caller path is unstable.
    """

    source_id: str
    host_id: str
    root_locator: str
    source_type: str
    authority: str
    access_class: str
    root_resolution: Literal["direct", "resolved"]
    root_fingerprint: str


@dataclass(frozen=True)
class InventoryRecord:
    record_id: str
    source_id: str
    relative_path: str
    work_type: str
    record_classes: tuple[RecordClass, ...]
    byte_size: int
    mtime_ns: int
    permission_mode: str
    sha256: str
    resolved_work_key: str | None
    identity_authority: str | None
    identifiers: tuple[str, ...]
    topic_id: str | None
    parse_quality_passed: bool


@dataclass(frozen=True)
class InventoryCount:
    """One of the five counts, carrying the meaning needed to read it safely.

    ``basis`` says what was de-duplicated, ``unit`` says what one increment
    means, and ``caveats`` are stable codes a renderer turns into qualifying
    prose. Two counts with different ``unit`` values must never be added,
    divided, or compared.
    """

    value: int | None
    basis: str
    unit: str
    state: str
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True)
class InventoryCounts:
    source_record_count: InventoryCount
    canonical_paper_count: InventoryCount
    pdf_asset_count: InventoryCount
    parsed_fulltext_count: InventoryCount
    topic_membership_count: InventoryCount


@dataclass(frozen=True)
class InventoryCoverage:
    """Scan completeness. Part of the digest, so degraded never equals complete."""

    files_seen: int
    records_emitted: int
    directories_scanned: int
    issues_total: int
    issue_codes: tuple[tuple[str, int], ...]
    complete: bool


@dataclass(frozen=True)
class InventoryManifest:
    snapshot_id: str
    observed_at: str
    sources: tuple[InventorySourceRecord, ...]
    records: tuple[InventoryRecord, ...]
    counts: InventoryCounts
    coverage: InventoryCoverage
    issues: tuple[InventoryIssue, ...]
    diagnostics: tuple[str, ...]
    manifest_sha256: str
    schema_version: str = INVENTORY_MANIFEST_SCHEMA_VERSION
    platform: str = INVENTORY_MANIFEST_PLATFORM


@dataclass(frozen=True)
class InventoryReconciliationReport:
    """Dry-run alignment inputs.

    ``manual_review_count == 0`` is only meaningful when
    ``identity_comparison_state == "computed"``. When no record on either side
    carries a resolver-issued key there is nothing to compare, and the state
    says so rather than reporting a clean zero.
    """

    exact_asset_hash_matches: tuple[tuple[str, str], ...]
    identity_conflicts: tuple[tuple[str, str], ...]
    version_candidates: tuple[tuple[str, str], ...]
    manual_review_count: int
    identity_comparison_state: Literal["computed", "not_comparable"]
    comparable_left_count: int
    comparable_right_count: int
    unresolved_left_count: int
    unresolved_right_count: int
    duplicate_hash_groups_left: tuple[tuple[str, ...], ...]
    duplicate_hash_groups_right: tuple[tuple[str, ...], ...]
    auto_merge_count: int = 0


class _ScanState:
    """Mutable accumulator for one source scan.

    Lists rather than tuple rebuilding: the previous implementation rebuilt the
    whole record/path/fingerprint tuple per directory entry, which made a single
    large directory superlinear in its entry count.
    """

    __slots__ = ("records", "issues", "seen_paths", "files_seen", "directories_scanned")

    def __init__(self) -> None:
        self.records: list[InventoryRecord] = []
        self.issues: list[InventoryIssue] = []
        self.seen_paths: set[str] = set()
        self.files_seen = 0
        self.directories_scanned = 0


def build_inventory_manifest(
    *,
    sources: tuple[InventorySourceSpec, ...],
    snapshot_id: str,
    observed_at: str,
    record_error_policy: RecordErrorPolicy = "fatal",
) -> InventoryManifest:
    """Scan explicit filesystem roots without following links or writing sources.

    ``record_error_policy="fatal"`` (the default) aborts the whole scan on the
    first unreadable, unclassified, or malformed file. ``"issue"`` keeps the
    scan going and records each one in ``issues``; failed records contribute
    nothing to any count or to the digest's record list, and ``coverage`` marks
    the manifest incomplete.
    """

    if not snapshot_id.strip():
        raise InventoryManifestError("empty_snapshot_id")
    if not observed_at.strip():
        raise InventoryManifestError("empty_observed_at")
    if record_error_policy not in {"fatal", "issue"}:
        raise InventoryManifestError(
            "invalid_record_error_policy", detail=str(record_error_policy)
        )
    _require_posix_traversal()
    source_ids = tuple(source.source_id for source in sources)
    if len(source_ids) != len(set(source_ids)):
        raise InventoryManifestError("duplicate_source_id")

    ordered_sources = tuple(sorted(sources, key=lambda source: source.source_id))
    source_records: list[InventorySourceRecord] = []
    all_records: list[InventoryRecord] = []
    all_issues: list[InventoryIssue] = []
    files_seen = 0
    records_emitted = 0
    directories_scanned = 0
    for source in ordered_sources:
        source_record, state = _scan_source(source, record_error_policy)
        source_records.append(source_record)
        all_records.extend(state.records)
        all_issues.extend(state.issues)
        files_seen += state.files_seen
        records_emitted += len(state.records)
        directories_scanned += state.directories_scanned

    return _finalize_inventory_manifest(
        snapshot_id=snapshot_id,
        observed_at=observed_at,
        source_records=tuple(source_records),
        records=tuple(all_records),
        issues=tuple(all_issues),
        files_seen=files_seen,
        records_emitted=records_emitted,
        directories_scanned=directories_scanned,
        source_record_basis="physical_file",
    )


def _finalize_inventory_manifest(
    *,
    snapshot_id: str,
    observed_at: str,
    source_records: tuple[InventorySourceRecord, ...],
    records: tuple[InventoryRecord, ...],
    issues: tuple[InventoryIssue, ...],
    files_seen: int,
    records_emitted: int,
    directories_scanned: int,
    source_record_basis: Literal["physical_file", "logical_row"],
) -> InventoryManifest:
    """Assemble the private manifest after a source-specific read-only scan."""

    if not snapshot_id.strip():
        raise InventoryManifestError("empty_snapshot_id")
    if not observed_at.strip():
        raise InventoryManifestError("empty_observed_at")
    if source_record_basis not in {"physical_file", "logical_row"}:
        raise InventoryManifestError(
            "invalid_source_record_basis", detail=source_record_basis
        )
    if records_emitted != len(records):
        raise InventoryManifestError(
            "records_emitted_mismatch",
            detail=f"expected={len(records)};actual={records_emitted}",
        )

    ordered_records = tuple(
        sorted(
            records,
            key=lambda record: (
                os.fsencode(record.source_id),
                os.fsencode(record.relative_path),
            ),
        )
    )
    ordered_issues = tuple(
        sorted(
            issues,
            key=lambda issue: (
                os.fsencode(issue.source_id),
                os.fsencode(issue.relative_path),
                issue.code,
            ),
        )
    )
    counts, diagnostics, count_issues = _calculate_counts(
        ordered_records,
        source_record_basis=source_record_basis,
    )
    ordered_issues = tuple(
        sorted(
            (*ordered_issues, *count_issues),
            key=lambda issue: (
                os.fsencode(issue.source_id),
                os.fsencode(issue.relative_path),
                issue.code,
            ),
        )
    )
    coverage = _build_coverage(
        files_seen=files_seen,
        records_emitted=records_emitted,
        directories_scanned=directories_scanned,
        issues=ordered_issues,
    )
    counts = _apply_coverage_to_counts(counts, coverage)
    provisional = InventoryManifest(
        snapshot_id=snapshot_id,
        observed_at=observed_at,
        sources=source_records,
        records=ordered_records,
        counts=counts,
        coverage=coverage,
        issues=ordered_issues,
        diagnostics=diagnostics,
        manifest_sha256="",
    )
    digest = hashlib.sha256(
        _canonical_bytes(_manifest_digest_payload(provisional))
    ).hexdigest()
    return InventoryManifest(
        snapshot_id=provisional.snapshot_id,
        observed_at=provisional.observed_at,
        sources=provisional.sources,
        records=provisional.records,
        counts=provisional.counts,
        coverage=provisional.coverage,
        issues=provisional.issues,
        diagnostics=provisional.diagnostics,
        manifest_sha256=digest,
    )


def inventory_manifest_to_dict(manifest: InventoryManifest) -> dict[str, object]:
    """Return the JSON-safe inventory contract without local ``Path`` objects."""

    payload = _manifest_payload(manifest)
    return {**payload, "manifest_sha256": manifest.manifest_sha256}


def serialize_inventory_manifest(manifest: InventoryManifest) -> str:
    """Serialize a manifest deterministically for replay and hash comparison."""

    return (
        json.dumps(
            inventory_manifest_to_dict(manifest),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def reconcile_inventory_manifests(
    left: InventoryManifest,
    right: InventoryManifest,
) -> InventoryReconciliationReport:
    """Compare asset and identity evidence without performing identity merges."""

    left_assets = tuple(
        record for record in left.records if "pdf_asset" in record.record_classes
    )
    right_assets = tuple(
        record for record in right.records if "pdf_asset" in record.record_classes
    )
    left_comparable = tuple(
        record for record in left_assets if _is_resolver_identity(record)
    )
    right_comparable = tuple(
        record for record in right_assets if _is_resolver_identity(record)
    )
    right_by_hash = _group_records(right_assets, key_name="sha256")
    right_by_work = _group_records(right_comparable, key_name="resolved_work_key")
    exact_matches = {
        (left_record.record_id, right_record.record_id)
        for left_record in left_assets
        for right_record in right_by_hash.get(left_record.sha256, ())
    }
    identity_conflicts = {
        (left_record.record_id, right_record.record_id)
        for left_record in left_comparable
        for right_record in right_by_hash.get(left_record.sha256, ())
        if _is_resolver_identity(right_record)
        and left_record.resolved_work_key != right_record.resolved_work_key
    }
    version_candidates = {
        (left_record.record_id, right_record.record_id)
        for left_record in left_comparable
        for right_record in right_by_work.get(left_record.resolved_work_key, ())
        if left_record.sha256 != right_record.sha256
    }
    manual_pairs = identity_conflicts | version_candidates
    comparable = bool(left_comparable) and bool(right_comparable)
    return InventoryReconciliationReport(
        exact_asset_hash_matches=tuple(sorted(exact_matches)),
        identity_conflicts=tuple(sorted(identity_conflicts)),
        version_candidates=tuple(sorted(version_candidates)),
        manual_review_count=len(manual_pairs),
        identity_comparison_state="computed" if comparable else "not_comparable",
        comparable_left_count=len(left_comparable),
        comparable_right_count=len(right_comparable),
        unresolved_left_count=len(left_assets) - len(left_comparable),
        unresolved_right_count=len(right_assets) - len(right_comparable),
        duplicate_hash_groups_left=_duplicate_hash_groups(left_assets),
        duplicate_hash_groups_right=_duplicate_hash_groups(right_assets),
    )


def _require_posix_traversal() -> None:
    missing = [name for name in ("O_NOFOLLOW", "O_DIRECTORY") if not hasattr(os, name)]
    if missing or os.name != "posix":
        raise InventoryManifestError(
            "unsupported_platform", detail=",".join(missing) or sys.platform
        )


def _scan_source(
    source: InventorySourceSpec,
    record_error_policy: RecordErrorPolicy,
) -> tuple[InventorySourceRecord, _ScanState]:
    absolute_root = Path(os.path.abspath(source.root))
    resolved_root = Path(os.path.realpath(source.root))
    resolution: Literal["direct", "resolved"] = (
        "direct" if resolved_root == absolute_root else "resolved"
    )
    state = _ScanState()
    root_fd = _open_directory_chain(resolved_root, source_id=source.source_id)
    try:
        root_status = os.fstat(root_fd)
        root_fingerprint = _status_fingerprint(root_status)
        _scan_directory_fd(
            source=source,
            directory_fd=root_fd,
            relative_directory="",
            state=state,
            record_error_policy=record_error_policy,
        )
        reopened_fd = _open_directory_chain(resolved_root, source_id=source.source_id)
        try:
            if _status_fingerprint(os.fstat(reopened_fd)) != root_fingerprint:
                raise InventoryManifestError(
                    "source_changed_during_scan",
                    source_id=source.source_id,
                    relative_path=".",
                )
        finally:
            os.close(reopened_fd)
    finally:
        os.close(root_fd)

    missing_overrides = {
        relative_path
        for relative_path, _classification in source.path_classifications
        if relative_path not in state.seen_paths
    }
    if missing_overrides:
        raise InventoryManifestError(
            "classification_path_missing",
            source_id=source.source_id,
            relative_path=sorted(missing_overrides, key=os.fsencode)[0],
        )
    source_record = InventorySourceRecord(
        source_id=source.source_id,
        host_id=source.host_id,
        root_locator=source.root_locator,
        source_type=source.source_type,
        authority=source.authority,
        access_class=source.access_class,
        root_resolution=resolution,
        root_fingerprint=f"{root_status.st_dev}:{root_status.st_ino}",
    )
    return source_record, state


def _scan_directory_fd(
    *,
    source: InventorySourceSpec,
    directory_fd: int,
    relative_directory: str,
    state: _ScanState,
    record_error_policy: RecordErrorPolicy,
) -> None:
    state.directories_scanned += 1
    directory_before = os.fstat(directory_fd)
    try:
        with os.scandir(directory_fd) as iterator:
            entries = sorted(iterator, key=lambda entry: os.fsencode(entry.name))
    except OSError as exc:
        _handle_record_error(
            InventoryManifestError(
                "source_directory_unreadable",
                source_id=source.source_id,
                relative_path=relative_directory or ".",
            ),
            state=state,
            policy=record_error_policy,
            cause=exc,
        )
        return

    fingerprints: list[tuple[str, str, tuple[int, int, int, int, int, int]]] = []
    classifications = dict(source.path_classifications)
    for entry in entries:
        relative_path = (
            f"{relative_directory}/{entry.name}" if relative_directory else entry.name
        )
        try:
            entry_status = entry.stat(follow_symlinks=False)
        except OSError as exc:
            _handle_record_error(
                InventoryManifestError(
                    "source_entry_unreadable",
                    source_id=source.source_id,
                    relative_path=relative_path,
                ),
                state=state,
                policy=record_error_policy,
                cause=exc,
            )
            continue
        fingerprints.append(
            (entry.name, relative_path, _status_fingerprint(entry_status))
        )
        if stat.S_ISDIR(entry_status.st_mode):
            try:
                child_fd = _open_child_directory(
                    directory_fd,
                    entry.name,
                    expected_status=entry_status,
                    source_id=source.source_id,
                    relative_path=relative_path,
                )
            except InventoryManifestError as error:
                _handle_record_error(error, state=state, policy=record_error_policy)
                continue
            try:
                _scan_directory_fd(
                    source=source,
                    directory_fd=child_fd,
                    relative_directory=relative_path,
                    state=state,
                    record_error_policy=record_error_policy,
                )
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(entry_status.st_mode):
            state.files_seen += 1
            # A present override that becomes an issue is not a missing path.
            state.seen_paths.add(relative_path)
            _scan_regular_file(
                source=source,
                directory_fd=directory_fd,
                name=entry.name,
                relative_path=relative_path,
                entry_status=entry_status,
                classification=classifications.get(
                    relative_path, source.default_classification
                ),
                state=state,
                record_error_policy=record_error_policy,
            )
        else:
            _handle_record_error(
                InventoryManifestError(
                    "unsupported_file_type",
                    source_id=source.source_id,
                    relative_path=relative_path,
                ),
                state=state,
                policy=record_error_policy,
            )

    _verify_directory_unchanged(
        directory_fd=directory_fd,
        source_id=source.source_id,
        relative_directory=relative_directory,
        initial_names=tuple(os.fsencode(entry.name) for entry in entries),
        initial_status=directory_before,
        entry_fingerprints=tuple(fingerprints),
    )


def _scan_regular_file(
    *,
    source: InventorySourceSpec,
    directory_fd: int,
    name: str,
    relative_path: str,
    entry_status: os.stat_result,
    classification: InventoryClassification | None,
    state: _ScanState,
    record_error_policy: RecordErrorPolicy,
) -> None:
    if classification is None:
        _handle_record_error(
            InventoryManifestError(
                "unclassified_inventory_file",
                source_id=source.source_id,
                relative_path=relative_path,
            ),
            state=state,
            policy=record_error_policy,
        )
        return
    try:
        digest, first_bytes, stable_status = _hash_stable_file_at(
            directory_fd,
            name,
            initial_status=entry_status,
            source_id=source.source_id,
            relative_path=relative_path,
        )
    except InventoryManifestError as error:
        _handle_record_error(error, state=state, policy=record_error_policy)
        return
    if "pdf_asset" in classification.record_classes and not first_bytes.startswith(
        _PDF_SIGNATURE
    ):
        _handle_record_error(
            InventoryManifestError(
                "invalid_pdf_signature",
                source_id=source.source_id,
                relative_path=relative_path,
            ),
            state=state,
            policy=record_error_policy,
        )
        return
    state.records.append(
        _inventory_record(
            source,
            relative_path,
            classification,
            digest,
            stable_status,
        )
    )


def _handle_record_error(
    error: InventoryManifestError,
    *,
    state: _ScanState,
    policy: RecordErrorPolicy,
    cause: BaseException | None = None,
) -> None:
    """Raise under ``fatal`` policy, otherwise record a non-sensitive issue."""

    if policy == "fatal" or error.code not in RECORD_LEVEL_ERROR_CODES:
        if cause is not None:
            raise error from cause
        raise error
    state.issues.append(
        InventoryIssue(
            code=error.code,
            severity="record",
            source_id=error.source_id,
            relative_path=error.relative_path,
        )
    )


def _open_directory_chain(root: Path, *, source_id: str) -> int:
    """Bind a descriptor to ``root`` without following any symlink.

    ``root`` must already be resolved: callers go through ``_scan_source``,
    which resolves once and records whether resolution was needed. Resolving up
    front is what makes a legitimately symlinked location scannable at all,
    while the no-follow chain still guarantees nothing inside the source is
    reached through a link.
    """

    absolute_root = Path(os.path.abspath(root))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    current_fd: int | None = None
    try:
        current_fd = os.open(os.sep, flags)
        for part in absolute_root.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as exc:
        if current_fd is not None:
            os.close(current_fd)
        raise InventoryManifestError(
            "source_root_unreadable", source_id=source_id
        ) from exc


def _classify_open_failure(exc: OSError, *, unreadable_code: str) -> str:
    """Map an ``open`` failure to the error it actually describes.

    Reporting a permission problem or a descriptor shortage as
    ``source_changed_during_scan`` would raise a tamper alarm for an ordinary
    environmental failure, and would send an operator looking for an attacker.
    Only errors that mean "the entry is no longer what the listing said" are
    treated as a mid-scan change.
    """

    if exc.errno in {errno.EMFILE, errno.ENFILE, errno.ENOMEM}:
        return "source_scan_resource_exhausted"
    if exc.errno in {errno.EACCES, errno.EPERM}:
        return unreadable_code
    return "source_changed_during_scan"


def _open_child_directory(
    parent_fd: int,
    name: str,
    *,
    expected_status: os.stat_result,
    source_id: str,
    relative_path: str,
) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        child_fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise InventoryManifestError(
            _classify_open_failure(exc, unreadable_code="source_directory_unreadable"),
            source_id=source_id,
            relative_path=relative_path,
        ) from exc
    if _status_fingerprint(os.fstat(child_fd)) != _status_fingerprint(expected_status):
        os.close(child_fd)
        raise InventoryManifestError(
            "source_changed_during_scan",
            source_id=source_id,
            relative_path=relative_path,
        )
    return child_fd


def _inventory_record(
    source: InventorySourceSpec,
    relative_path: str,
    classification: InventoryClassification,
    digest: str,
    stable_status: os.stat_result,
) -> InventoryRecord:
    return InventoryRecord(
        record_id=f"{source.source_id}:{relative_path}",
        source_id=source.source_id,
        relative_path=relative_path,
        work_type=classification.work_type,
        record_classes=tuple(sorted(classification.record_classes)),
        byte_size=stable_status.st_size,
        mtime_ns=stable_status.st_mtime_ns,
        permission_mode=oct(stat.S_IMODE(stable_status.st_mode)),
        sha256=digest,
        resolved_work_key=classification.resolved_work_key,
        identity_authority=classification.identity_authority,
        identifiers=tuple(sorted(set(classification.identifiers))),
        topic_id=classification.topic_id,
        parse_quality_passed=classification.parse_quality_passed,
    )


def _verify_directory_unchanged(
    *,
    directory_fd: int,
    source_id: str,
    relative_directory: str,
    initial_names: tuple[bytes, ...],
    initial_status: os.stat_result,
    entry_fingerprints: tuple[
        tuple[str, str, tuple[int, int, int, int, int, int]], ...
    ],
) -> None:
    relative_path = relative_directory or "."
    try:
        with os.scandir(directory_fd) as iterator:
            final_names = tuple(sorted(os.fsencode(entry.name) for entry in iterator))
    except OSError as exc:
        raise InventoryManifestError(
            "source_changed_during_scan",
            source_id=source_id,
            relative_path=relative_path,
        ) from exc
    if final_names != initial_names:
        raise InventoryManifestError(
            "source_changed_during_scan",
            source_id=source_id,
            relative_path=relative_path,
        )
    for entry_name, entry_relative_path, fingerprint in entry_fingerprints:
        try:
            final_status = os.stat(
                entry_name, dir_fd=directory_fd, follow_symlinks=False
            )
        except OSError as exc:
            raise InventoryManifestError(
                "source_changed_during_scan",
                source_id=source_id,
                relative_path=entry_relative_path,
            ) from exc
        if _status_fingerprint(final_status) != fingerprint:
            raise InventoryManifestError(
                "source_changed_during_scan",
                source_id=source_id,
                relative_path=entry_relative_path,
            )
    if _status_fingerprint(os.fstat(directory_fd)) != _status_fingerprint(
        initial_status
    ):
        raise InventoryManifestError(
            "source_changed_during_scan",
            source_id=source_id,
            relative_path=relative_path,
        )


def _hash_stable_file_at(
    directory_fd: int,
    name: str,
    *,
    initial_status: os.stat_result,
    source_id: str,
    relative_path: str,
) -> tuple[str, bytes, os.stat_result]:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise InventoryManifestError(
            _classify_open_failure(exc, unreadable_code="source_file_unreadable"),
            source_id=source_id,
            relative_path=relative_path,
        ) from exc
    try:
        before = os.fstat(descriptor)
        if _status_fingerprint(initial_status) != _status_fingerprint(before):
            raise InventoryManifestError(
                "source_file_changed",
                source_id=source_id,
                relative_path=relative_path,
            )
        digest = hashlib.sha256()
        first_bytes = b""
        while chunk := os.read(descriptor, _READ_CHUNK_BYTES):
            if len(first_bytes) < _SIGNATURE_PROBE_BYTES:
                first_bytes = (first_bytes + chunk)[:_SIGNATURE_PROBE_BYTES]
            digest.update(chunk)
        after = os.fstat(descriptor)
        if _status_fingerprint(before) != _status_fingerprint(after):
            raise InventoryManifestError(
                "source_file_changed",
                source_id=source_id,
                relative_path=relative_path,
            )
        return digest.hexdigest(), first_bytes, after
    finally:
        os.close(descriptor)


def _is_resolver_identity(record: InventoryRecord) -> bool:
    return bool(record.resolved_work_key) and (
        record.identity_authority in RESOLVER_IDENTITY_AUTHORITIES
    )


def _calculate_counts(
    records: tuple[InventoryRecord, ...],
    *,
    source_record_basis: Literal["physical_file", "logical_row"] = "physical_file",
) -> tuple[InventoryCounts, tuple[str, ...], tuple[InventoryIssue, ...]]:
    canonical_records = tuple(
        record for record in records if "canonical_paper" in record.record_classes
    )
    resolver_canonical = tuple(
        record for record in canonical_records if _is_resolver_identity(record)
    )
    canonical_complete = bool(canonical_records) and len(resolver_canonical) == len(
        canonical_records
    )
    diagnostics: list[str] = []
    if not canonical_records:
        diagnostics.append("canonical_identity_not_observed")
    elif not canonical_complete:
        diagnostics.append("canonical_identity_incomplete")

    issues = tuple(
        InventoryIssue(
            code="parsed_fulltext_quality_rejected",
            severity="info",
            source_id=record.source_id,
            relative_path=record.relative_path,
        )
        for record in records
        if "parsed_fulltext" in record.record_classes
        and not record.parse_quality_passed
    )

    membership_records = tuple(
        record for record in records if "topic_membership" in record.record_classes
    )
    resolver_membership = tuple(
        record for record in membership_records if _is_resolver_identity(record)
    )
    membership_complete = bool(membership_records) and len(resolver_membership) == len(
        membership_records
    )
    if membership_records and not membership_complete:
        diagnostics.append("topic_membership_identity_incomplete")

    source_record_count = InventoryCount(
        value=sum("source_record" in record.record_classes for record in records),
        basis=source_record_basis,
        unit="source_record",
        state="computed",
        caveats=("may_contain_multiple_records_per_work",),
    )
    canonical_paper_count = InventoryCount(
        value=(
            len({record.resolved_work_key for record in resolver_canonical})
            if canonical_complete
            else None
        ),
        basis="unique_work_identity",
        unit="canonical_work",
        state="computed" if canonical_complete else "not_computed",
        caveats=(
            ()
            if canonical_complete
            else ("requires_resolver_identity_authority_on_every_record",)
        ),
    )
    pdf_asset_count = InventoryCount(
        value=len(
            {
                record.sha256
                for record in records
                if "pdf_asset" in record.record_classes
            }
        ),
        basis="unique_content_hash",
        unit="content_asset",
        state="computed",
        caveats=(
            "basis_is_content_hash_not_work_identity",
            "distinct_versions_of_one_work_count_separately",
            "not_comparable_to_canonical_paper_count",
        ),
    )
    parsed_fulltext_count = InventoryCount(
        value=len(
            {
                record.sha256
                for record in records
                if "parsed_fulltext" in record.record_classes
                and record.parse_quality_passed
            }
        ),
        basis="unique_content_hash",
        unit="parsed_artifact",
        state="computed",
        caveats=(
            "basis_is_content_hash_not_work_identity",
            "multiple_parsers_of_one_work_count_separately",
            "not_comparable_to_canonical_paper_count",
        ),
    )
    membership_edges = {
        (record.resolved_work_key, record.topic_id) for record in resolver_membership
    }
    topic_membership_count = InventoryCount(
        value=len(membership_edges) if membership_complete else None,
        basis="unique_work_topic_edge",
        unit="topic_edge",
        state="computed" if membership_complete else "not_computed",
        caveats=(
            ("one_work_may_belong_to_many_topics",)
            if membership_complete
            else ("requires_resolver_identity_authority_on_every_record",)
        ),
    )
    counts = InventoryCounts(
        source_record_count=source_record_count,
        canonical_paper_count=canonical_paper_count,
        pdf_asset_count=pdf_asset_count,
        parsed_fulltext_count=parsed_fulltext_count,
        topic_membership_count=topic_membership_count,
    )
    return counts, tuple(sorted(set(diagnostics))), issues


def _build_coverage(
    *,
    files_seen: int,
    records_emitted: int,
    directories_scanned: int,
    issues: tuple[InventoryIssue, ...],
) -> InventoryCoverage:
    blocking = tuple(issue for issue in issues if issue.severity == "record")
    code_counts: dict[str, int] = {}
    for issue in issues:
        code_counts[issue.code] = code_counts.get(issue.code, 0) + 1
    return InventoryCoverage(
        files_seen=files_seen,
        records_emitted=records_emitted,
        directories_scanned=directories_scanned,
        issues_total=len(issues),
        issue_codes=tuple(sorted(code_counts.items())),
        complete=not blocking,
    )


def _apply_coverage_to_counts(
    counts: InventoryCounts, coverage: InventoryCoverage
) -> InventoryCounts:
    """Mark every count degraded when the scan did not cover every file."""

    if coverage.complete:
        return counts
    return InventoryCounts(
        **{
            field: _degrade_count(getattr(counts, field))
            for field in counts.__dataclass_fields__
        }
    )


def _degrade_count(count: InventoryCount) -> InventoryCount:
    return InventoryCount(
        value=count.value,
        basis=count.basis,
        unit=count.unit,
        state="degraded" if count.state == "computed" else count.state,
        caveats=tuple(sorted({*count.caveats, "scan_coverage_incomplete"})),
    )


def _duplicate_hash_groups(
    records: tuple[InventoryRecord, ...],
) -> tuple[tuple[str, ...], ...]:
    by_hash: dict[str, list[str]] = {}
    for record in records:
        by_hash.setdefault(record.sha256, []).append(record.record_id)
    return tuple(
        sorted(
            tuple(sorted(record_ids))
            for record_ids in by_hash.values()
            if len(record_ids) > 1
        )
    )


def _group_records(
    records: tuple[InventoryRecord, ...],
    *,
    key_name: Literal["sha256", "resolved_work_key"],
) -> dict[str | None, tuple[InventoryRecord, ...]]:
    ordered = sorted(
        records,
        key=lambda record: (
            getattr(record, key_name) is None,
            getattr(record, key_name) or "",
        ),
    )
    return {
        key: tuple(group)
        for key, group in groupby(ordered, key=lambda record: getattr(record, key_name))
    }


def _count_payload(count: InventoryCount) -> dict[str, object]:
    return {
        "value": count.value,
        "basis": count.basis,
        "unit": count.unit,
        "state": count.state,
        "caveats": list(count.caveats),
    }


def _manifest_payload(manifest: InventoryManifest) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version,
        "hash_contract": INVENTORY_MANIFEST_HASH_CONTRACT,
        "platform": manifest.platform,
        "snapshot_id": manifest.snapshot_id,
        "observed_at": manifest.observed_at,
        "sources": [
            {
                "source_id": source.source_id,
                "host_id": source.host_id,
                "root_locator": source.root_locator,
                "source_type": source.source_type,
                "authority": source.authority,
                "access_class": source.access_class,
                "root_resolution": source.root_resolution,
                "root_fingerprint": source.root_fingerprint,
            }
            for source in manifest.sources
        ],
        "records": [
            {
                "record_id": record.record_id,
                "source_id": record.source_id,
                "relative_path": record.relative_path,
                "work_type": record.work_type,
                "record_classes": list(record.record_classes),
                "byte_size": record.byte_size,
                "mtime_ns": record.mtime_ns,
                "permission_mode": record.permission_mode,
                "sha256": record.sha256,
                "resolved_work_key": record.resolved_work_key,
                "identity_authority": record.identity_authority,
                "identifiers": list(record.identifiers),
                "topic_id": record.topic_id,
                "parse_quality_passed": record.parse_quality_passed,
            }
            for record in manifest.records
        ],
        "counts": {
            field: _count_payload(getattr(manifest.counts, field))
            for field in manifest.counts.__dataclass_fields__
        },
        "coverage": {
            "files_seen": manifest.coverage.files_seen,
            "records_emitted": manifest.coverage.records_emitted,
            "directories_scanned": manifest.coverage.directories_scanned,
            "issues_total": manifest.coverage.issues_total,
            "issue_codes": [
                [code, count] for code, count in manifest.coverage.issue_codes
            ],
            "complete": manifest.coverage.complete,
        },
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity,
                "source_id": issue.source_id,
                "relative_path": issue.relative_path,
            }
            for issue in manifest.issues
        ],
        "diagnostics": list(manifest.diagnostics),
    }


def _manifest_digest_payload(manifest: InventoryManifest) -> dict[str, object]:
    return {
        key: value
        for key, value in _manifest_payload(manifest).items()
        if key != "observed_at"
    }


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _status_fingerprint(status: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _validate_relative_path(relative_path: str) -> None:
    path = PurePosixPath(relative_path)
    if (
        not relative_path
        or path.is_absolute()
        or "/".join(path.parts) != relative_path
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in relative_path
    ):
        raise InventoryManifestError(
            "unsafe_relative_path", relative_path=relative_path
        )


def _validate_nonempty_values(
    values: tuple[str, ...], *, code: str, duplicate_code: str
) -> None:
    if any(not value.strip() for value in values):
        raise InventoryManifestError(code)
    if len(values) != len(set(values)):
        raise InventoryManifestError(duplicate_code)
