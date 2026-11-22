#!/usr/bin/env python3
"""Check RH critical-path coverage metadata and release hook wiring."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COVERAGE_PATH = ROOT / "docs" / "contracts" / "critical-path-coverage.md"
CODEX_CHECK_PATH = ROOT / "scripts" / "codex-check.sh"
COVERAGE_BASELINE_PATH = ROOT / "scripts" / "coverage-baseline.sh"

REQUIRED_CRITICAL_PATHS = (
    "public_mcp_tools",
    "service_validation",
    "orchestrator_artifact_gate",
    "topic_knowledge",
    "zotero_dry_run_boundary",
    "golden_workflows",
    "transport_service_convergence",
)
VALID_STATUSES = {"covered"}

ROW_RE = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE,
)
CODE_SPAN_RE = re.compile(r"`([^`]+)`")


def parse_coverage_rows(coverage_text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for path_id, status, guard, focused_tests, release_hook in ROW_RE.findall(
        coverage_text
    ):
        rows[path_id] = {
            "status": status.strip(),
            "guard": guard.strip(),
            "focused_tests": focused_tests.strip(),
            "release_hook": release_hook.strip(),
        }
    return rows


def validate_critical_path_coverage(
    *,
    coverage_text: str,
    codex_check_text: str,
    coverage_baseline_text: str,
    root: Path = ROOT,
) -> list[str]:
    errors: list[str] = []
    rows = parse_coverage_rows(coverage_text)
    required = set(REQUIRED_CRITICAL_PATHS)
    present = set(rows)

    missing = sorted(required - present)
    if missing:
        errors.append(
            "critical coverage matrix missing critical paths: " + ", ".join(missing)
        )

    extra = sorted(present - required)
    if extra:
        errors.append("critical coverage matrix has unknown paths: " + ", ".join(extra))

    invalid_statuses = sorted(
        f"{path_id}={row['status']}"
        for path_id, row in rows.items()
        if row["status"] not in VALID_STATUSES
    )
    if invalid_statuses:
        errors.append(
            "critical coverage matrix has invalid statuses: "
            + ", ".join(invalid_statuses)
        )

    missing_files = _missing_referenced_files(rows, root=root)
    if missing_files:
        errors.append(
            "critical coverage referenced files are missing: "
            + ", ".join(missing_files)
        )

    if "scripts/check-critical-path-coverage.py" not in codex_check_text:
        errors.append("codex-check --coverage is missing critical path guard")

    missing_from_coverage = _focused_tests_missing_from_coverage(
        rows,
        coverage_baseline_text=coverage_baseline_text,
    )
    if missing_from_coverage:
        errors.append(
            "focused tests not included in coverage command: "
            + ", ".join(missing_from_coverage)
        )

    return errors


def _missing_referenced_files(
    rows: dict[str, dict[str, str]],
    *,
    root: Path,
) -> list[str]:
    missing: list[str] = []
    for row in rows.values():
        for cell_name in ("guard", "focused_tests", "release_hook"):
            for ref in _file_refs(row[cell_name]):
                if not (root / ref).exists():
                    missing.append(ref)
    return sorted(set(missing))


def _file_refs(cell: str) -> tuple[str, ...]:
    refs: list[str] = []
    for raw_ref in CODE_SPAN_RE.findall(cell):
        ref = raw_ref.strip().split()[0]
        if ref.startswith(("scripts/", "packages/", "docs/", ".github/")):
            refs.append(ref)
    return tuple(refs)


def _focused_tests_missing_from_coverage(
    rows: dict[str, dict[str, str]],
    *,
    coverage_baseline_text: str,
) -> list[str]:
    targets = _coverage_default_targets(coverage_baseline_text)
    focused_refs = sorted(
        {
            ref
            for row in rows.values()
            for ref in _file_refs(row["focused_tests"])
            if ref.startswith("packages/")
        }
    )
    return [
        ref for ref in focused_refs if not _coverage_target_includes_ref(targets, ref)
    ]


def _coverage_default_targets(coverage_baseline_text: str) -> tuple[str, ...]:
    targets: list[str] = []
    in_default_target_block = False
    in_targets_assignment = False
    for line in coverage_baseline_text.splitlines():
        stripped = line.strip()
        if stripped == 'if [[ "${#TARGETS[@]}" -eq 0 ]]; then':
            in_default_target_block = True
            continue
        if not in_default_target_block:
            continue
        if stripped == "fi":
            break
        if "TARGETS=(" in stripped:
            in_targets_assignment = True
        if not in_targets_assignment:
            continue
        for target in re.findall(r'"([^"]+)"', stripped):
            if target.startswith("packages/"):
                targets.append(target)
        if in_targets_assignment and stripped == ")":
            in_targets_assignment = False
    return tuple(targets)


def _coverage_target_includes_ref(targets: tuple[str, ...], ref: str) -> bool:
    for target in targets:
        normalized = target.rstrip("/")
        if ref == normalized or ref.startswith(f"{normalized}/"):
            return True
    return False


def main() -> int:
    missing_inputs = [
        path
        for path in (COVERAGE_PATH, CODEX_CHECK_PATH, COVERAGE_BASELINE_PATH)
        if not path.is_file()
    ]
    if missing_inputs:
        for path in missing_inputs:
            print(
                f"FAIL: missing critical path input: {path.relative_to(ROOT)}",
                file=sys.stderr,
            )
        return 1

    errors = validate_critical_path_coverage(
        coverage_text=COVERAGE_PATH.read_text(encoding="utf-8"),
        codex_check_text=CODEX_CHECK_PATH.read_text(encoding="utf-8"),
        coverage_baseline_text=COVERAGE_BASELINE_PATH.read_text(encoding="utf-8"),
        root=ROOT,
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rows = parse_coverage_rows(COVERAGE_PATH.read_text(encoding="utf-8"))
    print(f"Critical path coverage guard passed; paths={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
