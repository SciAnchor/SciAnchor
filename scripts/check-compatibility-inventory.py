#!/usr/bin/env python3
"""Check Tier B compatibility lifecycle inventory against the surface audit.

This guard is intentionally read-only. It does not import the MCP runtime or
change compatibility behavior; it only keeps the LG3 lifecycle plan synchronized
with the frozen public surface audit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "docs" / "mcp-tool-audit.md"
INVENTORY_PATH = ROOT / "docs" / "contracts" / "compatibility-inventory.md"

ALLOWED_POLICIES = {"keep", "wrapper", "deprecate", "remove-later"}
PUBLIC_HEADER = "## Tier A: Public Contracted Tools"
PRIMITIVE_AUDIT_HEADER = "## Tier B: Internal Primitive Compatibility Names"
SURFACE_AUDIT_HEADER = "## Tier B: Internal Surface Compatibility Names"
PRIMITIVE_INVENTORY_HEADER = "## Primitive Compatibility Names"
SURFACE_INVENTORY_HEADER = "## Internal Surface Compatibility Names"
TIER_A_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|")
INVENTORY_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|` ]+)\s*\|")
COUNT_RE = re.compile(r"^- Tier B total:\s*(\d+)\s*$", re.MULTILINE)


def _section_lines(text: str, header: str) -> list[str]:
    lines = text.splitlines()
    try:
        start = lines.index(header) + 1
    except ValueError:
        return []

    section: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        section.append(line)
    return section


def _duplicates(names: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        if name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    return duplicates


def parse_public_names(audit_text: str) -> list[str]:
    return [
        match.group(1)
        for line in _section_lines(audit_text, PUBLIC_HEADER)
        if (match := TIER_A_ROW_RE.match(line)) is not None
    ]


def parse_audit_code_block_names(audit_text: str, header: str) -> list[str]:
    names: list[str] = []
    in_code_block = False
    for line in _section_lines(audit_text, header):
        if line.strip() == "```text":
            in_code_block = True
            continue
        if in_code_block and line.strip() == "```":
            break
        if in_code_block and line.strip():
            names.append(line.strip())
    return names


def parse_inventory_table(inventory_text: str, header: str) -> dict[str, str]:
    policies: dict[str, str] = {}
    for line in _section_lines(inventory_text, header):
        match = INVENTORY_ROW_RE.match(line)
        if match is None:
            continue
        name, policy = match.groups()
        if name == "Name":
            continue
        policies[name] = policy.strip()
    return policies


def parse_declared_tier_b_total(audit_text: str) -> int | None:
    match = COUNT_RE.search(audit_text)
    if match is None:
        return None
    return int(match.group(1))


def validate_compatibility_inventory(
    *,
    audit_text: str,
    inventory_text: str,
) -> list[str]:
    errors: list[str] = []
    public_names = parse_public_names(audit_text)
    primitive_audit_names = parse_audit_code_block_names(
        audit_text, PRIMITIVE_AUDIT_HEADER
    )
    surface_audit_names = parse_audit_code_block_names(audit_text, SURFACE_AUDIT_HEADER)
    primitive_inventory = parse_inventory_table(
        inventory_text, PRIMITIVE_INVENTORY_HEADER
    )
    surface_inventory = parse_inventory_table(inventory_text, SURFACE_INVENTORY_HEADER)

    audit_names = primitive_audit_names + surface_audit_names
    inventory_names = list(primitive_inventory) + list(surface_inventory)
    audit_name_set = set(audit_names)
    inventory_name_set = set(inventory_names)
    public_name_set = set(public_names)

    if not public_names:
        errors.append("docs/mcp-tool-audit.md Tier A table has no public names")
    if not primitive_audit_names:
        errors.append("docs/mcp-tool-audit.md has no Tier B primitive names")
    if not surface_audit_names:
        errors.append("docs/mcp-tool-audit.md has no Tier B internal surface names")
    if not primitive_inventory:
        errors.append("compatibility inventory has no primitive rows")
    if not surface_inventory:
        errors.append("compatibility inventory has no internal surface rows")

    for label, names in (
        ("audit Tier B names", audit_names),
        ("inventory Tier B names", inventory_names),
    ):
        duplicate_names = _duplicates(names)
        if duplicate_names:
            errors.append(f"{label} has duplicates: {', '.join(duplicate_names)}")

    declared_total = parse_declared_tier_b_total(inventory_text)
    if declared_total is None:
        errors.append("compatibility inventory is missing Tier B total")
    elif declared_total != len(audit_name_set):
        errors.append(
            f"compatibility inventory Tier B total {declared_total} != "
            f"parsed Tier B names {len(audit_name_set)}"
        )

    missing = sorted(audit_name_set - inventory_name_set)
    if missing:
        errors.append("missing Tier B inventory names: " + ", ".join(missing))

    extra = sorted(inventory_name_set - audit_name_set)
    if extra:
        errors.append("extra Tier B inventory names: " + ", ".join(extra))

    public_overlap = sorted(inventory_name_set & public_name_set)
    if public_overlap:
        errors.append("public names in Tier B inventory: " + ", ".join(public_overlap))

    for name, policy in {**primitive_inventory, **surface_inventory}.items():
        if policy not in ALLOWED_POLICIES:
            errors.append(f"invalid policy for {name}: {policy}")

    return errors


def main() -> int:
    errors: list[str] = []
    if not AUDIT_PATH.is_file():
        errors.append(f"missing audit document: {AUDIT_PATH.relative_to(ROOT)}")
    if not INVENTORY_PATH.is_file():
        errors.append(
            f"missing compatibility inventory: {INVENTORY_PATH.relative_to(ROOT)}"
        )
    if not errors:
        errors.extend(
            validate_compatibility_inventory(
                audit_text=AUDIT_PATH.read_text(encoding="utf-8"),
                inventory_text=INVENTORY_PATH.read_text(encoding="utf-8"),
            )
        )

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    audit_names = set(
        parse_audit_code_block_names(
            AUDIT_PATH.read_text(encoding="utf-8"), PRIMITIVE_AUDIT_HEADER
        )
    ) | set(
        parse_audit_code_block_names(
            AUDIT_PATH.read_text(encoding="utf-8"), SURFACE_AUDIT_HEADER
        )
    )
    print(f"Compatibility inventory guard passed; tier_b_names={len(audit_names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
