#!/usr/bin/env python3
"""Build a local public showcase bundle from RH evidence artifacts.

The bundle is intentionally file-based: it packages existing artifacts without
querying private databases or running model-backed primitives.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


SHOWCASE_SLOTS = (
    "final_pdf",
    "provenance_export",
    "citation_integrity_report",
    "paper_pool_summary",
    "claim_evidence_graph",
    "zotero_screenshot",
    "researchflowbench_score_report",
)

SLOT_LABELS = {
    "final_pdf": "Final paper or report PDF",
    "provenance_export": "Provenance export",
    "citation_integrity_report": "Citation and integrity report",
    "paper_pool_summary": "Paper pool summary",
    "claim_evidence_graph": "Claim/evidence graph",
    "zotero_screenshot": "Zotero workflow screenshot",
    "researchflowbench_score_report": "ResearchFlowBench score report",
}


class IncompleteShowcaseBundle(Exception):
    """Raised when require_complete is set and any required slot is missing."""

    def __init__(self, missing_slots: list[str], manifest_path: Path):
        self.missing_slots = missing_slots
        self.manifest_path = manifest_path
        super().__init__(
            "showcase bundle is incomplete; missing slots: "
            + ", ".join(missing_slots)
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_filename(slot: str, source_path: Path) -> str:
    suffix = source_path.suffix or ".artifact"
    return f"{slot}{suffix}"


def _productization_boundary_payload() -> dict[str, object]:
    boundary_path = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "research_harness"
        / "research_harness"
        / "_productization"
        / "boundary.py"
    )
    spec = importlib.util.spec_from_file_location(
        "rh_productization_boundary", boundary_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load LG10 boundary payload from {boundary_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module.build_lg10_productization_boundary_payload(
        scope="public-showcase-opt-in-preview"
    )


def _parse_artifact_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "artifact must use SLOT=PATH, for example final_pdf=paper.pdf"
        )
    slot, raw_path = value.split("=", 1)
    slot = slot.strip()
    if slot not in SHOWCASE_SLOTS:
        allowed = ", ".join(SHOWCASE_SLOTS)
        raise argparse.ArgumentTypeError(
            f"unknown showcase slot {slot!r}; allowed slots: {allowed}"
        )
    path = Path(raw_path).expanduser()
    return slot, path


def _readme_text(manifest: dict[str, object]) -> str:
    lines = [
        f"# {manifest['title']}",
        "",
        "This directory is a Research Harness public showcase bundle.",
        "It is built from local files and records the evidence artifacts that",
        "should appear in the public launch story.",
        "",
        f"- Schema: `{manifest['schema_version']}`",
        f"- Created at: `{manifest['created_at']}`",
        f"- Complete: `{manifest['complete']}`",
        "",
        "## Artifacts",
        "",
        "| Slot | Status | Bundled file |",
        "|---|---|---|",
    ]
    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, dict)
    for slot in SHOWCASE_SLOTS:
        item = artifacts[slot]
        assert isinstance(item, dict)
        bundle_path = item.get("bundle_path") or ""
        label = item.get("label") or slot
        lines.append(f"| {label} | `{item['status']}` | `{bundle_path}` |")

    missing = manifest.get("missing_slots") or []
    if missing:
        lines.extend(
            [
                "",
                "## Missing Slots",
                "",
                "Fill these before publishing the showcase:",
                "",
            ]
        )
        for slot in missing:
            lines.append(f"- `{slot}`: {SLOT_LABELS.get(str(slot), str(slot))}")

    lines.extend(
        [
            "",
            "## README Snippet",
            "",
            "```md",
            "## Showcase",
            "",
            "Research Harness turns one research question into a durable topic,",
            "paper pool, claim/evidence map, provenance trace, and reviewable",
            "writing bundle.",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def build_showcase_bundle(
    output_dir: str | Path,
    artifact_paths: dict[str, str | Path],
    title: str = "Research Harness Showcase Bundle",
    created_at: str | None = None,
    require_complete: bool = False,
    productization_boundary: bool = False,
) -> dict[str, object]:
    """Create a showcase bundle directory and return its manifest."""

    unknown_slots = sorted(set(artifact_paths) - set(SHOWCASE_SLOTS))
    if unknown_slots:
        raise ValueError(f"unknown showcase slots: {', '.join(unknown_slots)}")

    output_path = Path(output_dir)
    artifacts_dir = output_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "schema_version": "research_harness.showcase_bundle.v0",
        "title": title,
        "created_at": created_at or _utc_now(),
        "required_slots": list(SHOWCASE_SLOTS),
        "missing_slots": [],
        "complete": False,
        "artifacts": {},
    }
    if productization_boundary:
        manifest["productization_boundary"] = _productization_boundary_payload()

    manifest_artifacts: dict[str, dict[str, object]] = {}
    missing_slots: list[str] = []

    for slot in SHOWCASE_SLOTS:
        raw_path = artifact_paths.get(slot)
        source_path = Path(raw_path).expanduser() if raw_path is not None else None
        if source_path is not None and source_path.exists():
            target = artifacts_dir / _bundle_filename(slot, source_path)
            shutil.copy2(source_path, target)
            manifest_artifacts[slot] = {
                "label": SLOT_LABELS[slot],
                "status": "present",
                "source_path": str(source_path),
                "bundle_path": target.relative_to(output_path).as_posix(),
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
            continue

        missing_slots.append(slot)
        manifest_artifacts[slot] = {
            "label": SLOT_LABELS[slot],
            "status": "missing",
            "source_path": str(source_path) if source_path is not None else "",
            "bundle_path": "",
            "bytes": 0,
            "sha256": "",
        }

    manifest["artifacts"] = manifest_artifacts
    manifest["missing_slots"] = missing_slots
    manifest["complete"] = not missing_slots

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    (output_path / "README.md").write_text(_readme_text(manifest))

    if require_complete and missing_slots:
        raise IncompleteShowcaseBundle(missing_slots, manifest_path)

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        help="Directory where the showcase bundle should be written.",
    )
    parser.add_argument(
        "--title",
        default="Research Harness Showcase Bundle",
        help="Human-readable bundle title.",
    )
    parser.add_argument(
        "--created-at",
        default=None,
        help="Override manifest timestamp, usually for reproducible tests.",
    )
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        type=_parse_artifact_arg,
        help="Artifact mapping as SLOT=PATH. Repeat for multiple slots.",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit nonzero if any required showcase slot is missing.",
    )
    parser.add_argument(
        "--productization-boundary",
        action="store_true",
        help=(
            "Add the opt-in LG10 productization boundary preview to the "
            "manifest without publishing or querying private state."
        ),
    )
    args = parser.parse_args()

    artifact_paths = dict(args.artifact)
    try:
        manifest = build_showcase_bundle(
            output_dir=args.output,
            artifact_paths=artifact_paths,
            title=args.title,
            created_at=args.created_at,
            require_complete=args.require_complete,
            productization_boundary=args.productization_boundary,
        )
    except IncompleteShowcaseBundle as exc:
        print(f"wrote incomplete showcase manifest: {exc.manifest_path}")
        print(str(exc))
        return 1

    print(f"wrote showcase bundle: {Path(args.output)}")
    print(f"complete: {manifest['complete']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
