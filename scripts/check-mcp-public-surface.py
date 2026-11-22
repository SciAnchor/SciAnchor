#!/usr/bin/env python3
"""Check the contracted MCP public surface against the audit snapshot.

This guard is intentionally dependency-light: it parses the source constant and
the audit document instead of importing the MCP package. Runtime behavior is
covered by package tests; this script keeps `codex-check --quick` usable as a
surface-freeze gate.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "docs" / "mcp-tool-audit.md"
SURFACE_PATH = (
    ROOT
    / "packages"
    / "research_harness_mcp"
    / "research_harness_mcp"
    / "tool_surface.py"
)

EXPECTED_PUBLIC_TOOL_COUNT = 54
TIER_A_HEADER = "## Tier A: Public Contracted Tools"
SERVICE_COVERAGE_MARKER = "Service dispatcher coverage:"

COUNT_RE = re.compile(r"^- Public advertised MCP tools:\s*(\d+)\s*$", re.MULTILINE)
TIER_A_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|")


def parse_advertised_count(audit_text: str) -> int | None:
    match = COUNT_RE.search(audit_text)
    if match is None:
        return None
    return int(match.group(1))


def parse_tier_a_names(audit_text: str) -> list[str]:
    lines = audit_text.splitlines()
    try:
        start = lines.index(TIER_A_HEADER) + 1
    except ValueError:
        return []

    names: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        match = TIER_A_ROW_RE.match(line)
        if match is not None:
            names.append(match.group(1))
    return names


def parse_public_names_from_source(surface_text: str) -> list[str]:
    tree = ast.parse(surface_text)
    for node in tree.body:
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "PUBLIC_MCP_TOOL_NAMES"
                ):
                    value = node.value
                    break
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PUBLIC_MCP_TOOL_NAMES"
        ):
            value = node.value

        if value is None:
            continue
        if not isinstance(value, (ast.Tuple, ast.List)):
            return []
        names: list[str] = []
        for element in value.elts:
            if not isinstance(element, ast.Constant) or not isinstance(
                element.value, str
            ):
                return []
            names.append(element.value)
        return names
    return []


def _duplicates(names: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        if name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    return duplicates


def validate_public_surface(*, audit_text: str, surface_text: str) -> list[str]:
    errors: list[str] = []
    advertised_count = parse_advertised_count(audit_text)
    audit_names = parse_tier_a_names(audit_text)
    source_names = parse_public_names_from_source(surface_text)

    if advertised_count is None:
        errors.append("docs/mcp-tool-audit.md is missing advertised count")
    elif advertised_count != EXPECTED_PUBLIC_TOOL_COUNT:
        errors.append(
            "docs/mcp-tool-audit.md advertised count "
            f"{advertised_count} != frozen count {EXPECTED_PUBLIC_TOOL_COUNT}"
        )

    if SERVICE_COVERAGE_MARKER not in audit_text:
        errors.append(
            "docs/mcp-tool-audit.md is missing service dispatcher coverage marker"
        )

    if not audit_names:
        errors.append("docs/mcp-tool-audit.md Tier A table has no tool names")
    if not source_names:
        errors.append("tool_surface.py PUBLIC_MCP_TOOL_NAMES has no parseable names")

    for label, names in (
        ("docs/mcp-tool-audit.md Tier A table", audit_names),
        ("tool_surface.py PUBLIC_MCP_TOOL_NAMES", source_names),
    ):
        duplicate_names = _duplicates(names)
        if duplicate_names:
            errors.append(f"{label} has duplicate names: {', '.join(duplicate_names)}")
        if len(names) != EXPECTED_PUBLIC_TOOL_COUNT:
            errors.append(
                f"{label} count {len(names)} != frozen count "
                f"{EXPECTED_PUBLIC_TOOL_COUNT}"
            )

    if audit_names and source_names and audit_names != source_names:
        errors.append(
            "docs/mcp-tool-audit.md Tier A table does not match "
            "tool_surface.py PUBLIC_MCP_TOOL_NAMES"
        )

    return errors


def main() -> int:
    errors: list[str] = []
    if not AUDIT_PATH.is_file():
        errors.append(f"missing audit document: {AUDIT_PATH.relative_to(ROOT)}")
    if not SURFACE_PATH.is_file():
        errors.append(f"missing surface source: {SURFACE_PATH.relative_to(ROOT)}")
    if not errors:
        errors.extend(
            validate_public_surface(
                audit_text=AUDIT_PATH.read_text(encoding="utf-8"),
                surface_text=SURFACE_PATH.read_text(encoding="utf-8"),
            )
        )

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print(f"MCP public surface guard passed; public_tools={EXPECTED_PUBLIC_TOOL_COUNT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
