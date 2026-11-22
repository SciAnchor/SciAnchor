from __future__ import annotations

import json
from pathlib import Path

from research_harness.runtime.showcase_manifest import (
    SHOWCASE_MANIFEST_RECORD_SCHEMA_VERSION,
    SHOWCASE_MANIFEST_SCHEMA_VERSION,
    SHOWCASE_REQUIRED_SLOTS,
    normalize_showcase_manifest,
    read_showcase_manifest,
    showcase_manifest_record_to_dict,
)


def _complete_manifest() -> dict[str, object]:
    artifacts: dict[str, dict[str, object]] = {}
    for index, slot in enumerate(SHOWCASE_REQUIRED_SLOTS, start=1):
        artifacts[slot] = {
            "label": slot.replace("_", " ").title(),
            "status": "present",
            "source_path": f"/private/source/{slot}.dat",
            "bundle_path": f"artifacts/{slot}.dat",
            "bytes": index * 10,
            "sha256": f"hash-{slot}",
        }
    return {
        "schema_version": SHOWCASE_MANIFEST_SCHEMA_VERSION,
        "title": "Public Launch Showcase",
        "created_at": "2026-06-09T14:00:00Z",
        "required_slots": list(SHOWCASE_REQUIRED_SLOTS),
        "missing_slots": [],
        "complete": True,
        "artifacts": artifacts,
    }


def test_normalize_complete_showcase_manifest_without_mutating_source():
    source = _complete_manifest()
    original = json.loads(json.dumps(source))

    record = normalize_showcase_manifest(
        source,
        manifest_path=Path(".tmp/showcase/public/manifest.json"),
    )
    payload = showcase_manifest_record_to_dict(record)

    assert source == original
    assert record.schema_version == SHOWCASE_MANIFEST_RECORD_SCHEMA_VERSION
    assert record.event_type == "showcase.manifest_complete"
    assert record.status == "complete"
    assert record.record_id == "showcase_manifest:tmp_showcase_public_manifest_json"
    assert record.manifest_schema_version == SHOWCASE_MANIFEST_SCHEMA_VERSION
    assert record.title == "Public Launch Showcase"
    assert record.required_slots == SHOWCASE_REQUIRED_SLOTS
    assert record.present_slots == SHOWCASE_REQUIRED_SLOTS
    assert record.missing_slots == ()
    assert record.invalid_reasons == ()
    assert record.total_bytes == 280
    assert record.checksum_count == len(SHOWCASE_REQUIRED_SLOTS)
    assert payload["artifact_refs"][0] == ".tmp/showcase/public/manifest.json"
    assert "artifacts/final_pdf.dat" in payload["artifact_refs"]


def test_normalize_incomplete_manifest_reports_missing_slots():
    source = _complete_manifest()
    artifacts = source["artifacts"]
    assert isinstance(artifacts, dict)
    artifacts["zotero_screenshot"] = {
        "label": "Zotero workflow screenshot",
        "status": "missing",
        "source_path": "",
        "bundle_path": "",
        "bytes": 0,
        "sha256": "",
    }
    source["missing_slots"] = ["zotero_screenshot"]
    source["complete"] = False

    record = normalize_showcase_manifest(source)

    assert record.event_type == "showcase.manifest_incomplete"
    assert record.status == "incomplete"
    assert record.error_code == "showcase_bundle_incomplete"
    assert record.missing_slots == ("zotero_screenshot",)
    assert "zotero_screenshot" not in record.present_slots
    assert record.payload["artifact_count"] == len(SHOWCASE_REQUIRED_SLOTS)


def test_normalize_invalid_manifest_flags_schema_and_unsafe_bundle_path():
    source = _complete_manifest()
    source["schema_version"] = "showcase.v0"
    artifacts = source["artifacts"]
    assert isinstance(artifacts, dict)
    artifacts["final_pdf"]["bundle_path"] = "../private/final.pdf"
    artifacts["unexpected_slot"] = {
        "status": "present",
        "bundle_path": "artifacts/unexpected.txt",
        "bytes": 1,
        "sha256": "hash-unexpected",
    }

    record = normalize_showcase_manifest(source)
    payload = showcase_manifest_record_to_dict(record)

    assert record.event_type == "showcase.manifest_invalid"
    assert record.status == "invalid"
    assert record.error_code == "showcase_manifest_invalid"
    assert "invalid_schema_version" in record.invalid_reasons
    assert "final_pdf:unsafe_bundle_path" in record.invalid_reasons
    assert record.unknown_slots == ("unexpected_slot",)
    assert "../private/final.pdf" not in payload["artifact_refs"]


def test_read_showcase_manifest_reads_file_without_writes(tmp_path: Path):
    manifest_path = tmp_path / "showcase" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest = _complete_manifest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    before = manifest_path.read_text(encoding="utf-8")

    record = read_showcase_manifest(manifest_path)

    assert manifest_path.read_text(encoding="utf-8") == before
    assert record.status == "complete"
    assert record.artifact_refs[0] == str(manifest_path)


def test_read_showcase_manifest_invalid_json_returns_non_leaking_record(
    tmp_path: Path,
):
    manifest_path = tmp_path / "showcase" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text("{not json /private/raw/path", encoding="utf-8")

    record = read_showcase_manifest(manifest_path)
    payload = showcase_manifest_record_to_dict(record)

    assert record.status == "invalid"
    assert record.event_type == "showcase.manifest_invalid"
    assert record.error_code == "showcase_manifest_invalid_json"
    assert record.invalid_reasons == ("invalid_json",)
    assert str(manifest_path) in payload["artifact_refs"]
    assert "/private/raw/path" not in str(payload)
