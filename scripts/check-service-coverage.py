#!/usr/bin/env python3
"""Check public MCP service coverage metadata.

This is a structural guard for the self-development control plane. It parses
source files and the coverage matrix without importing project packages, keeping
`codex-check --quick` lightweight and deterministic.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOL_SURFACE_PATH = (
    ROOT
    / "packages"
    / "research_harness_mcp"
    / "research_harness_mcp"
    / "tool_surface.py"
)
MCP_TOOLS_PATH = (
    ROOT / "packages" / "research_harness_mcp" / "research_harness_mcp" / "tools.py"
)
SERVICE_DISPATCH_PATH = (
    ROOT
    / "packages"
    / "research_harness_mcp"
    / "research_harness_mcp"
    / "tools_service_dispatch.py"
)
SERVICE_REGISTRY_PATH = (
    ROOT
    / "packages"
    / "research_harness"
    / "research_harness"
    / "service"
    / "registry.py"
)
COVERAGE_PATH = ROOT / "docs" / "contracts" / "service-coverage.md"

VALID_STATUSES = {
    "service-backed-mcp",
    "registered-only",
    "existing-path",
    "deferred-gate",
}
COVERAGE_ROW_RE = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE,
)


def _literal_names_from_assignment(source: str, assignment_name: str) -> list[str]:
    tree = ast.parse(source)
    for node in tree.body:
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == assignment_name:
                    value = node.value
                    break
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == assignment_name
        ):
            value = node.value
        if value is None:
            continue
        if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
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


def parse_public_tool_names(surface_text: str) -> list[str]:
    return _literal_names_from_assignment(surface_text, "PUBLIC_MCP_TOOL_NAMES")


def parse_service_backed_mcp_names(
    mcp_tools_text: str, service_dispatch_text: str | None = None
) -> list[str]:
    names = _literal_names_from_assignment(
        mcp_tools_text, "_SERVICE_BACKED_CONVENIENCE_TOOLS"
    )
    if names or service_dispatch_text is None:
        return names
    return _literal_names_from_assignment(
        service_dispatch_text, "_SERVICE_BACKED_CONVENIENCE_TOOLS"
    )


def parse_coverage_rows(coverage_text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for name, status, _current_path, _next_action in COVERAGE_ROW_RE.findall(
        coverage_text
    ):
        rows[name] = status.strip()
    return rows


def parse_coverage_next_actions(coverage_text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for name, _status, _current_path, next_action in COVERAGE_ROW_RE.findall(
        coverage_text
    ):
        rows[name] = next_action.strip()
    return rows


def parse_public_service_command_names(registry_text: str) -> list[str]:
    tree = ast.parse(registry_text)
    commands: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "ServiceCommand":
            continue
        name = _keyword_literal(node, "name")
        visibility = _keyword_tuple(node, "visibility")
        if name and "public_mcp" in visibility:
            commands.append(name)
    return commands


def _keyword_literal(node: ast.Call, key: str) -> str | None:
    for keyword in node.keywords:
        if keyword.arg != key:
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(
            keyword.value.value, str
        ):
            return keyword.value.value
    return None


def _keyword_tuple(node: ast.Call, key: str) -> tuple[str, ...]:
    for keyword in node.keywords:
        if keyword.arg != key:
            continue
        if not isinstance(keyword.value, (ast.Tuple, ast.List, ast.Set)):
            return ()
        values: list[str] = []
        for element in keyword.value.elts:
            if not isinstance(element, ast.Constant) or not isinstance(
                element.value, str
            ):
                return ()
            values.append(element.value)
        return tuple(values)
    return ()


def _duplicates(names: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        if name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    return duplicates


def validate_service_coverage(
    *,
    surface_text: str,
    mcp_tools_text: str,
    service_dispatch_text: str | None = None,
    registry_text: str,
    coverage_text: str,
) -> list[str]:
    errors: list[str] = []
    public_names = parse_public_tool_names(surface_text)
    service_backed = parse_service_backed_mcp_names(
        mcp_tools_text, service_dispatch_text
    )
    service_public = parse_public_service_command_names(registry_text)
    coverage_rows = parse_coverage_rows(coverage_text)
    coverage_next_actions = parse_coverage_next_actions(coverage_text)

    public_set = set(public_names)
    service_backed_set = set(service_backed)
    service_public_set = set(service_public)
    coverage_set = set(coverage_rows)

    for label, names in (
        ("PUBLIC_MCP_TOOL_NAMES", public_names),
        ("_SERVICE_BACKED_CONVENIENCE_TOOLS", service_backed),
        ("public_mcp service commands", service_public),
    ):
        duplicates = _duplicates(names)
        if duplicates:
            errors.append(f"{label} has duplicate names: {', '.join(duplicates)}")

    missing_coverage = sorted(public_set - coverage_set)
    extra_coverage = sorted(coverage_set - public_set)
    if missing_coverage:
        errors.append(
            f"coverage matrix missing public tools: {', '.join(missing_coverage)}"
        )
    if extra_coverage:
        errors.append(
            f"coverage matrix has non-public tools: {', '.join(extra_coverage)}"
        )

    bad_statuses = sorted(
        f"{name}={status}"
        for name, status in coverage_rows.items()
        if status not in VALID_STATUSES
    )
    if bad_statuses:
        errors.append(
            f"coverage matrix has invalid statuses: {', '.join(bad_statuses)}"
        )

    non_public_service = sorted(service_public_set - public_set)
    if non_public_service:
        errors.append(
            "public_mcp service commands are outside public MCP surface: "
            + ", ".join(non_public_service)
        )

    service_without_registry = sorted(service_backed_set - service_public_set)
    if service_without_registry:
        errors.append(
            "MCP service-backed tools are missing public service commands: "
            + ", ".join(service_without_registry)
        )

    registered_only = {
        name for name, status in coverage_rows.items() if status == "registered-only"
    }
    deferred_gate = {
        name for name, status in coverage_rows.items() if status == "deferred-gate"
    }
    deferred_without_gate_reason = sorted(
        name
        for name in deferred_gate
        if not coverage_next_actions.get(name, "").lower().startswith("gate:")
    )
    if deferred_without_gate_reason:
        errors.append(
            "deferred-gate rows need gate reasons in the Next slice column: "
            + ", ".join(deferred_without_gate_reason)
        )

    deferred_service_backed = sorted(deferred_gate & service_backed_set)
    if deferred_service_backed:
        errors.append(
            "deferred-gate tools cannot also be MCP service-backed: "
            + ", ".join(deferred_service_backed)
        )

    service_without_adapter = service_public_set - service_backed_set
    documented_service_without_adapter = registered_only | (
        deferred_gate & service_public_set
    )
    if service_without_adapter != documented_service_without_adapter:
        errors.append(
            "registered-only status does not match service registry: "
            f"doc={sorted(documented_service_without_adapter)} "
            f"registry_only={sorted(service_without_adapter)}"
        )

    documented_service_backed = {
        name for name, status in coverage_rows.items() if status == "service-backed-mcp"
    }
    if documented_service_backed != service_backed_set:
        errors.append(
            "coverage service-backed-mcp status does not match MCP adapter set: "
            f"doc={sorted(documented_service_backed)} adapter={sorted(service_backed_set)}"
        )

    registered_without_registry = sorted(registered_only - service_public_set)
    if registered_without_registry:
        errors.append(
            "registered-only tools are missing public service commands: "
            + ", ".join(registered_without_registry)
        )

    return errors


def main() -> int:
    inputs: dict[str, Any] = {
        "surface_text": TOOL_SURFACE_PATH.read_text(encoding="utf-8"),
        "mcp_tools_text": MCP_TOOLS_PATH.read_text(encoding="utf-8"),
        "service_dispatch_text": SERVICE_DISPATCH_PATH.read_text(encoding="utf-8"),
        "registry_text": SERVICE_REGISTRY_PATH.read_text(encoding="utf-8"),
        "coverage_text": COVERAGE_PATH.read_text(encoding="utf-8"),
    }
    errors = validate_service_coverage(**inputs)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    rows = parse_coverage_rows(inputs["coverage_text"])
    service_backed = parse_service_backed_mcp_names(
        inputs["mcp_tools_text"], inputs["service_dispatch_text"]
    )
    deferred_gate = [name for name, status in rows.items() if status == "deferred-gate"]
    print(
        "Service coverage guard passed; "
        f"public_tools={len(rows)} "
        f"service_backed_mcp={len(service_backed)} "
        f"deferred_gate={len(deferred_gate)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
