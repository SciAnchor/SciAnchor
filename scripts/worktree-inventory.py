#!/usr/bin/env python3
"""Inventory untracked files and fail on release-unsafe generated artifacts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON_PATH = ROOT / ".rh-selfdev" / "rh-untracked-file-inventory-2026-06-15.json"
DEFAULT_MARKDOWN_PATH = (
    ROOT / ".rh-selfdev" / "rh-untracked-file-inventory-2026-06-15.md"
)

GENERATED_PARTS = {
    ".tmp",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
}
GENERATED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".coverage",
    ".db",
    ".sqlite",
    ".sqlite3",
}
PRIVATE_BASENAMES = {
    ".env",
    ".env.local",
    ".envrc",
    "credentials.json",
    "secrets.json",
}
# A filled-in env file (`prod.env`, `ticket-worker.env`, `.env.local`); only a `.example` template is source.
ENV_FILE = re.compile(r"(?:^|\.)env(?:\.|$)")
PRIVATE_SUFFIXES = {
    ".pem",
    ".p12",
    ".pfx",
    ".key",
}


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    category: str
    owner: str
    commit_inclusion_status: str
    reason: str


def git_untracked_paths(root: Path = ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths: list[str] = []
    for raw_entry in result.stdout.split(b"\0"):
        if not raw_entry:
            continue
        text = raw_entry.decode("utf-8", errors="replace")
        if text.startswith("?? "):
            paths.append(text[3:])
    return sorted(paths)


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in Path(path).parts if part)


def _looks_generated_or_private(path: str) -> tuple[bool, str]:
    parts = _path_parts(path)
    basename = parts[-1] if parts else path
    suffixes = Path(path).suffixes
    if any(part in GENERATED_PARTS for part in parts):
        return True, "generated/cache path segment"
    if path.startswith("site/"):
        return True, "generated documentation site output"
    if path.startswith(".research-harness/"):
        return True, "local Research Harness state"
    if any(path.endswith(suffix) for suffix in GENERATED_SUFFIXES):
        return True, "generated/cache/database suffix"
    if basename in PRIVATE_BASENAMES or (
        ENV_FILE.search(basename) and not basename.endswith(".example")
    ):
        return True, "environment or credential-looking file"
    if any(path.endswith(suffix) for suffix in PRIVATE_SUFFIXES):
        return True, "credential-looking suffix"
    if any(part in {"secrets", "credentials"} for part in parts):
        return True, "credential-looking path segment"
    if ".egg-info" in parts:
        return True, "package build metadata"
    if any(part.endswith(".egg-info") for part in parts):
        return True, "package build metadata"
    if suffixes and suffixes[-1] in {".log", ".bak"}:
        return True, "local log/backup artifact"
    return False, ""


def classify_path(path: str) -> InventoryEntry:
    generated, generated_reason = _looks_generated_or_private(path)
    if generated:
        return InventoryEntry(
            path=path,
            category="unexpected_generated_artifacts",
            owner="exclude-before-commit",
            commit_inclusion_status="exclude_before_commit",
            reason=generated_reason,
        )

    if (
        path.startswith(".rh-selfdev/gates/")
        or path.startswith(".rh-selfdev/handoffs/")
        or path
        in {
            ".rh-selfdev/checkpoint.md",
            ".rh-selfdev/slices.md",
            ".rh-selfdev/long-goals.md",
            ".rh-selfdev/control-plane.md",
        }
    ):
        return InventoryEntry(
            path=path,
            category="rh_self_dev_gates_handoffs_checkpoints",
            owner="RH self-development control plane",
            commit_inclusion_status="include",
            reason="durable self-development evidence",
        )

    if path.startswith("scripts/"):
        return InventoryEntry(
            path=path,
            category="scripts",
            owner="release/self-development tooling",
            commit_inclusion_status="include",
            reason="script addition or release gate helper",
        )

    if path.startswith("skills/"):
        return InventoryEntry(
            path=path,
            category="skills",
            owner="Research Harness skill source",
            commit_inclusion_status="include",
            reason="public skill source or agent profile",
        )

    if path.startswith("packages/") and (
        "/tests/" in path or Path(path).name.startswith("test_")
    ):
        return InventoryEntry(
            path=path,
            category="new_tests",
            owner="package test surface",
            commit_inclusion_status="include",
            reason="focused test coverage for package or gate behavior",
        )

    if path.startswith("packages/"):
        return InventoryEntry(
            path=path,
            category="new_source_modules",
            owner="package source surface",
            commit_inclusion_status="include",
            reason="source module addition from release hardening work",
        )

    if path.startswith("deploy/"):
        return InventoryEntry(
            path=path,
            category="deploy_templates",
            owner="deployment templates",
            commit_inclusion_status="include",
            reason="deployment template or example configuration",
        )

    if path.startswith("integrations/"):
        return InventoryEntry(
            path=path,
            category="integrations",
            owner="host integrations",
            commit_inclusion_status="include",
            reason="plugin or integration source for a host tool",
        )

    if path.startswith("docs/"):
        return InventoryEntry(
            path=path,
            category="docs",
            owner="release documentation and evidence",
            commit_inclusion_status="include",
            reason="documentation or feedback evidence",
        )

    return InventoryEntry(
        path=path,
        category="unexpected_generated_artifacts",
        owner="needs-review",
        commit_inclusion_status="exclude_before_commit",
        reason="unclassified untracked path",
    )


def build_inventory(paths: list[str]) -> dict[str, object]:
    entries = [classify_path(path) for path in sorted(paths)]
    categories: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        categories.setdefault(entry.category, []).append(asdict(entry))
    unexpected = categories.get("unexpected_generated_artifacts", [])
    return {
        "schema": "rh.schema.selfdev.untracked_file_inventory.v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_untracked": len(entries),
        "unexpected_count": len(unexpected),
        "summary": {
            category: len(items) for category, items in sorted(categories.items())
        },
        "categories": categories,
        "unexpected": unexpected,
    }


def render_markdown(inventory: dict[str, object]) -> str:
    summary = inventory["summary"]
    assert isinstance(summary, dict)
    categories = inventory["categories"]
    assert isinstance(categories, dict)

    lines = [
        "# RH Untracked File Inventory - 2026-06-15",
        "",
        "Scope: `git status --short --untracked-files=all` in the current checkout.",
        "",
        f"- Total untracked files: {inventory['total_untracked']}",
        f"- Unexpected/generated artifacts: {inventory['unexpected_count']}",
        "- Commit inclusion rule: include only source, tests, scripts, docs, and self-dev evidence; exclude generated/cache/private artifacts before commit.",
        "",
        "## Summary",
        "",
        "| Category | Count | Commit inclusion |",
        "|---|---:|---|",
    ]
    for category, count in sorted(summary.items()):
        status = (
            "exclude before commit"
            if category == "unexpected_generated_artifacts"
            else "include"
        )
        lines.append(f"| `{category}` | {count} | {status} |")

    for category, raw_entries in sorted(categories.items()):
        entries = list(raw_entries)
        lines.extend(["", f"## {category}", ""])
        if not entries:
            lines.append("_None._")
            continue
        lines.append("| Path | Owner | Commit inclusion | Reason |")
        lines.append("|---|---|---|---|")
        for entry in entries:
            assert isinstance(entry, dict)
            lines.append(
                "| `{path}` | {owner} | {status} | {reason} |".format(
                    path=entry["path"],
                    owner=entry["owner"],
                    status=entry["commit_inclusion_status"],
                    reason=entry["reason"],
                )
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--allow-unexpected",
        action="store_true",
        help="Do not fail when generated/private/unclassified paths are present.",
    )
    args = parser.parse_args()

    inventory = build_inventory(git_untracked_paths())
    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.output_md:
        output_md = Path(args.output_md)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(render_markdown(inventory), encoding="utf-8")

    unexpected_count = int(inventory["unexpected_count"])
    print(
        "Untracked file inventory: "
        f"{inventory['total_untracked']} files, {unexpected_count} unexpected/generated"
    )
    if unexpected_count and not args.allow_unexpected:
        for entry in inventory["unexpected"]:
            assert isinstance(entry, dict)
            print(
                f"FAIL: exclude before commit: {entry['path']} ({entry['reason']})",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
