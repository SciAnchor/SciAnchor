#!/usr/bin/env python3
"""Check transport convergence coverage metadata.

This guard is intentionally structural and docs-focused. It does not import
Research Harness runtime packages or route transport code; it checks that
transport inventory remains synchronized with the service-backed read and
action-equivalent surfaces.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE_COVERAGE_PATH = ROOT / "docs" / "contracts" / "service-coverage.md"
PYTHON_API_PATH = ROOT / "packages" / "research_harness" / "research_harness" / "api.py"
TRANSPORT_COVERAGE_PATH = ROOT / "docs" / "contracts" / "transport-coverage.md"

READ_TRANSPORT_COMMANDS = (
    "topic_list",
    "topic_show",
    "paper_list",
    "provenance_summary",
    "provenance_export",
    "orchestrator_status",
    "orchestrator_gate_check",
    "cross_topic_atlas",
    "paperindex_search",
    "skill_list",
    "skill_get",
)
ACTION_TRANSPORT_COMMANDS = (
    "paper_search",
    "paper_ingest",
    "paper_summarize",
    "claim_extract",
    "evidence_link",
    "gap_detect",
    "baseline_identify",
    "section_draft",
    "consistency_check",
    "topic_knowledge_status",
    "topic_knowledge_refresh",
)
WRITE_EFFECT_TRANSPORT_COMMANDS = (
    "orchestrator_resume",
    "orchestrator_advance",
    "orchestrator_record_artifact",
    "zotero_sync",
)
VALID_TRANSPORT_STATUSES = {
    "service-backed",
    "missing-equivalent",
    "not-applicable",
}
LG16_DEBT_STATUSES = {"existing-direct", "deferred-shape"}

SERVICE_ROW_RE = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE,
)
TRANSPORT_ROW_RE = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE,
)


def _strip_cell(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        value = value[1:-1]
    return value.replace("`", "")


def parse_service_coverage_rows(coverage_text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for name, status in SERVICE_ROW_RE.findall(coverage_text):
        rows[name] = _strip_cell(status)
    return rows


def parse_transport_coverage_rows(
    coverage_text: str,
) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for (
        name,
        service_status,
        python_api,
        cli,
        http,
        next_action,
    ) in TRANSPORT_ROW_RE.findall(coverage_text):
        rows[name] = {
            "service_status": _strip_cell(service_status),
            "python_api": _strip_cell(python_api),
            "cli": _strip_cell(cli),
            "http": _strip_cell(http),
            "next_action": next_action.strip(),
        }
    return rows


def parse_python_service_routed_primitives(api_text: str) -> set[str]:
    tree = ast.parse(api_text)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_SERVICE_ROUTED_PRIMITIVES"
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, (ast.Set, ast.Tuple, ast.List)):
            return set()
        primitives: set[str] = set()
        for item in node.value.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                primitives.add(item.value)
        return primitives
    return set()


def validate_transport_coverage(
    *,
    service_coverage_text: str,
    transport_coverage_text: str,
    python_api_text: str | None = None,
) -> list[str]:
    errors: list[str] = []
    service_rows = parse_service_coverage_rows(service_coverage_text)
    transport_rows = parse_transport_coverage_rows(transport_coverage_text)
    if python_api_text is None:
        python_api_text = PYTHON_API_PATH.read_text(encoding="utf-8")
    python_service_primitives = parse_python_service_routed_primitives(python_api_text)

    required_read = set(READ_TRANSPORT_COMMANDS)
    required_action = set(ACTION_TRANSPORT_COMMANDS)
    required_write_effect = set(WRITE_EFFECT_TRANSPORT_COMMANDS)
    required = required_read | required_action | required_write_effect
    present = set(transport_rows)

    missing_read = sorted(required_read - present)
    if missing_read:
        errors.append(
            "transport matrix missing read commands: " + ", ".join(missing_read)
        )

    missing_action = sorted(required_action - present)
    if missing_action:
        errors.append(
            "transport matrix missing action commands: " + ", ".join(missing_action)
        )

    missing_python_primitives = sorted(python_service_primitives - present)
    if missing_python_primitives:
        errors.append(
            "transport matrix missing Python service-routed primitives: "
            + ", ".join(missing_python_primitives)
        )

    python_without_service_status = sorted(
        name
        for name in python_service_primitives & present
        if transport_rows[name]["python_api"] != "service-backed"
    )
    if python_without_service_status:
        errors.append(
            "Python service-routed primitives are not marked service-backed: "
            + ", ".join(python_without_service_status)
        )

    missing_write_effect = sorted(required_write_effect - present)
    if missing_write_effect:
        errors.append(
            "transport matrix missing write/effect commands: "
            + ", ".join(missing_write_effect)
        )

    extra = sorted(present - required)
    if extra:
        errors.append(
            "transport matrix has rows that are not tracked read/action/write-effect commands: "
            + ", ".join(extra)
        )

    service_not_backed = sorted(
        name for name in required if service_rows.get(name) != "service-backed-mcp"
    )
    if service_not_backed:
        errors.append(
            "required transport commands are not MCP service-backed: "
            + ", ".join(service_not_backed)
        )

    service_mismatches = sorted(
        f"{name}={row['service_status']} (service coverage={service_rows.get(name, 'missing')})"
        for name, row in transport_rows.items()
        if name in required and row["service_status"] != service_rows.get(name)
    )
    if service_mismatches:
        errors.append(
            "transport matrix service status mismatch: " + ", ".join(service_mismatches)
        )

    invalid_statuses: list[str] = []
    debt_statuses: list[str] = []
    for name, row in transport_rows.items():
        for column in ("python_api", "cli", "http"):
            value = row[column]
            if value not in VALID_TRANSPORT_STATUSES:
                invalid_statuses.append(f"{name}.{column}={value}")
            if value in LG16_DEBT_STATUSES:
                debt_statuses.append(f"{name}.{column}={value}")
    if invalid_statuses:
        errors.append(
            "transport matrix has invalid transport statuses: "
            + ", ".join(sorted(invalid_statuses))
        )
    if debt_statuses:
        errors.append(
            "LG16 debt statuses are not allowed: " + ", ".join(sorted(debt_statuses))
        )

    missing_next_action = sorted(
        name
        for name, row in transport_rows.items()
        if name in required
        and not row["next_action"].lower().startswith(("candidate:", "defer:", "done"))
    )
    if missing_next_action:
        errors.append(
            "transport matrix rows need candidate/defer/done next actions: "
            + ", ".join(missing_next_action)
        )

    return errors


def main() -> int:
    errors = validate_transport_coverage(
        service_coverage_text=SERVICE_COVERAGE_PATH.read_text(encoding="utf-8"),
        transport_coverage_text=TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8"),
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    rows = parse_transport_coverage_rows(
        TRANSPORT_COVERAGE_PATH.read_text(encoding="utf-8")
    )
    print(
        "Transport service coverage guard passed; "
        f"read_commands={len(READ_TRANSPORT_COMMANDS)} "
        f"action_commands={len(ACTION_TRANSPORT_COMMANDS)} "
        f"write_effect_commands={len(WRITE_EFFECT_TRANSPORT_COMMANDS)} "
        f"rows={len(rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
