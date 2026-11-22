"""Read-only normalization for showcase bundle manifests."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping


SHOWCASE_MANIFEST_SCHEMA_VERSION = "research_harness.showcase_bundle.v0"
SHOWCASE_MANIFEST_RECORD_SCHEMA_VERSION = "showcase_manifest_record.v0"
SHOWCASE_REQUIRED_SLOTS = (
    "final_pdf",
    "provenance_export",
    "citation_integrity_report",
    "paper_pool_summary",
    "claim_evidence_graph",
    "zotero_screenshot",
    "researchflowbench_score_report",
)

ShowcaseManifestStatus = Literal["complete", "incomplete", "invalid"]


@dataclass(frozen=True)
class ShowcaseManifestRecord:
    """Internal normalized view over an existing showcase bundle manifest."""

    record_id: str
    event_type: str
    status: ShowcaseManifestStatus
    complete: bool
    manifest_path: str | None = None
    manifest_schema_version: str | None = None
    title: str | None = None
    created_at: str | None = None
    required_slots: tuple[str, ...] = SHOWCASE_REQUIRED_SLOTS
    present_slots: tuple[str, ...] = ()
    missing_slots: tuple[str, ...] = ()
    unknown_slots: tuple[str, ...] = ()
    invalid_reasons: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    total_bytes: int = 0
    checksum_count: int = 0
    error_code: str | None = None
    schema_version: str = SHOWCASE_MANIFEST_RECORD_SCHEMA_VERSION
    payload: Mapping[str, Any] | None = None


def read_showcase_manifest(manifest_path: Path) -> ShowcaseManifestRecord:
    """Read and normalize an existing manifest file without writing anything."""

    path = Path(manifest_path)
    if not path.is_file():
        return _invalid_record(
            manifest_path=path,
            error_code="showcase_manifest_missing",
            invalid_reasons=("manifest_missing",),
            payload={"parse_error": "missing_file"},
        )

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _invalid_record(
            manifest_path=path,
            error_code="showcase_manifest_invalid_json",
            invalid_reasons=("invalid_json",),
            payload={"parse_error": "invalid_json"},
        )

    if not isinstance(parsed, Mapping):
        return _invalid_record(
            manifest_path=path,
            error_code="showcase_manifest_invalid",
            invalid_reasons=("non_object_json",),
            payload={"parse_error": "non_object_json"},
        )

    return normalize_showcase_manifest(parsed, manifest_path=path)


def normalize_showcase_manifest(
    source: Mapping[str, Any],
    *,
    manifest_path: Path | None = None,
) -> ShowcaseManifestRecord:
    """Normalize the current showcase bundle manifest shape without side effects."""

    manifest_path_text = str(manifest_path) if manifest_path is not None else None
    required_slots = (
        _slot_tuple(source.get("required_slots")) or SHOWCASE_REQUIRED_SLOTS
    )
    artifacts_value = source.get("artifacts")
    artifacts: Mapping[str, Any] = (
        artifacts_value if isinstance(artifacts_value, Mapping) else {}
    )
    invalid_reasons: list[str] = []
    if artifacts_value is not None and not isinstance(artifacts_value, Mapping):
        invalid_reasons.append("artifacts_not_object")

    manifest_schema_version = _text(source.get("schema_version"))
    if manifest_schema_version != SHOWCASE_MANIFEST_SCHEMA_VERSION:
        invalid_reasons.append("invalid_schema_version")

    artifact_keys = tuple(str(key) for key in artifacts)
    required_set = set(required_slots)
    unknown_slots = tuple(
        sorted(key for key in artifact_keys if key not in required_set)
    )
    invalid_reasons.extend(f"{slot}:unknown_slot" for slot in unknown_slots)

    present_slots: list[str] = []
    missing_slots = set(_slot_tuple(source.get("missing_slots")))
    artifact_refs: list[str] = []
    if manifest_path_text:
        artifact_refs.append(manifest_path_text)
    total_bytes = 0
    checksum_count = 0

    for slot in required_slots:
        artifact = artifacts.get(slot)
        if not isinstance(artifact, Mapping):
            missing_slots.add(slot)
            invalid_reasons.append(f"{slot}:artifact_entry_missing")
            continue

        status = _text(artifact.get("status")) or "unknown"
        bundle_path = _text(artifact.get("bundle_path"))
        if status == "present":
            present_slots.append(slot)
            if not bundle_path:
                invalid_reasons.append(f"{slot}:missing_bundle_path")
            elif _is_safe_bundle_path(bundle_path):
                artifact_refs.append(bundle_path)
            else:
                invalid_reasons.append(f"{slot}:unsafe_bundle_path")
            bytes_value = _int(artifact.get("bytes"))
            if bytes_value is None:
                invalid_reasons.append(f"{slot}:missing_bytes")
            else:
                total_bytes += bytes_value
            if _text(artifact.get("sha256")):
                checksum_count += 1
            else:
                invalid_reasons.append(f"{slot}:missing_sha256")
            continue

        if status == "missing":
            missing_slots.add(slot)
            if bundle_path:
                invalid_reasons.append(f"{slot}:missing_has_bundle_path")
            continue

        invalid_reasons.append(f"{slot}:invalid_status")
        missing_slots.add(slot)

    for slot in required_slots:
        if slot not in present_slots:
            missing_slots.add(slot)

    source_complete = _bool(source.get("complete"))
    structurally_complete = not missing_slots and not invalid_reasons
    if source_complete is not None and source_complete != structurally_complete:
        invalid_reasons.append("complete_flag_mismatch")

    invalid_reason_tuple = tuple(sorted(set(invalid_reasons)))
    missing_slot_tuple = tuple(slot for slot in required_slots if slot in missing_slots)
    present_slot_tuple = tuple(slot for slot in required_slots if slot in present_slots)

    if invalid_reason_tuple:
        status: ShowcaseManifestStatus = "invalid"
        event_type = "showcase.manifest_invalid"
        error_code = "showcase_manifest_invalid"
    elif missing_slot_tuple:
        status = "incomplete"
        event_type = "showcase.manifest_incomplete"
        error_code = "showcase_bundle_incomplete"
    else:
        status = "complete"
        event_type = "showcase.manifest_complete"
        error_code = None

    title = _text(source.get("title"))
    record_key = manifest_path_text or title or "unknown"
    return ShowcaseManifestRecord(
        record_id=f"showcase_manifest:{_slug(record_key)}",
        event_type=event_type,
        status=status,
        complete=status == "complete",
        manifest_path=manifest_path_text,
        manifest_schema_version=manifest_schema_version,
        title=title,
        created_at=_text(source.get("created_at")),
        required_slots=required_slots,
        present_slots=present_slot_tuple,
        missing_slots=missing_slot_tuple,
        unknown_slots=unknown_slots,
        invalid_reasons=invalid_reason_tuple,
        artifact_refs=tuple(artifact_refs),
        total_bytes=total_bytes,
        checksum_count=checksum_count,
        error_code=error_code,
        payload={
            "artifact_count": len(artifact_keys),
            "required_slot_count": len(required_slots),
            "source_complete": source_complete,
            "source_missing_slots": list(_slot_tuple(source.get("missing_slots"))),
        },
    )


def showcase_manifest_record_to_dict(
    record: ShowcaseManifestRecord,
) -> dict[str, Any]:
    """Return a JSON-like dictionary for a showcase manifest record."""

    payload = asdict(record)
    payload["required_slots"] = list(record.required_slots)
    payload["present_slots"] = list(record.present_slots)
    payload["missing_slots"] = list(record.missing_slots)
    payload["unknown_slots"] = list(record.unknown_slots)
    payload["invalid_reasons"] = list(record.invalid_reasons)
    payload["artifact_refs"] = list(record.artifact_refs)
    payload["payload"] = _json_clone(record.payload or {})
    return payload


def _invalid_record(
    *,
    manifest_path: Path | None,
    error_code: str,
    invalid_reasons: tuple[str, ...],
    payload: Mapping[str, Any],
) -> ShowcaseManifestRecord:
    path_text = str(manifest_path) if manifest_path is not None else None
    return ShowcaseManifestRecord(
        record_id=f"showcase_manifest:{_slug(path_text or 'unknown')}",
        event_type="showcase.manifest_invalid",
        status="invalid",
        complete=False,
        manifest_path=path_text,
        required_slots=SHOWCASE_REQUIRED_SLOTS,
        invalid_reasons=invalid_reasons,
        artifact_refs=(path_text,) if path_text else (),
        error_code=error_code,
        payload=dict(payload),
    )


def _slot_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    slots: list[str] = []
    for item in value:
        text = _text(item)
        if text:
            slots.append(text)
    return tuple(slots)


def _is_safe_bundle_path(value: str) -> bool:
    if value.startswith(("/", "\\")):
        return False
    path = PurePosixPath(value)
    return bool(value.strip()) and ".." not in path.parts


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    try:
        return None if value is None else int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    text = _text(value)
    if text is None:
        return None
    normalized = text.lower()
    if normalized in {"1", "true", "yes", "y", "complete", "completed"}:
        return True
    if normalized in {"0", "false", "no", "n", "incomplete"}:
        return False
    return None


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return text.strip("_") or "unknown"


def _json_clone(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_clone(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_clone(item) for item in value]
    if isinstance(value, list):
        return [_json_clone(item) for item in value]
    return value
