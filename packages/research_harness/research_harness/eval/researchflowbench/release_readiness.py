"""Release-readiness checks for RH-owned ResearchFlowBench task packs."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable

from .builder import build_synthetic_pilot20_task_pack
from .leakage import validate_leakage_audit
from .schema_dry_run import run_schema_dry_run


PRIVATE_DATA_MARKERS = (
    "/Users/",
    "/private/",
    "/home/",
    ".research-harness/downloads",
    "RESEARCH_HARNESS_DB_PATH=",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "api_key",
    "access_token",
    "BEGIN PRIVATE KEY",
)

REQUIRED_DOC_SNIPPETS = (
    "release-check",
    "release-readiness",
    "schema dry-run",
    "ruff",
    "pytest",
)

QUALITY_COMMANDS = (
    "ruff check packages/research_harness/research_harness/eval/researchflowbench "
    "packages/research_harness/research_harness/evolution/harness "
    "packages/research_harness/research_harness/cli.py",
    "pytest packages/research_harness/tests/test_researchflowbench_*.py "
    "packages/research_harness/tests/test_cli.py "
    "packages/research_harness/tests/test_longtask_supervisor.py -q",
)


@dataclass(frozen=True)
class ReleaseReadinessCheck:
    """One release-readiness gate result."""

    name: str
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReleaseReadinessReport:
    """Aggregated release-readiness report for a ResearchFlowBench pack."""

    task_pack_root: str
    status: str
    checks: tuple[ReleaseReadinessCheck, ...]
    quality_commands: tuple[str, ...] = QUALITY_COMMANDS
    mutation_performed: bool = False
    automatic_release_label_change: bool = False
    schema_version: str = "researchflowbench.release_readiness.v0.1"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["check_count"] = len(self.checks)
        payload["failed_checks"] = [
            check.name for check in self.checks if not check.passed
        ]
        return payload


def run_release_readiness_checks(
    task_pack_root: str | Path,
    *,
    docs_path: str | Path = "docs/researchflowbench.md",
    schema_dry_run_output: str | Path | None = None,
    reproducibility_output: str | Path | None = None,
) -> ReleaseReadinessReport:
    """Run read-only release-readiness checks over an RH-owned Pilot-20 pack."""

    root = Path(task_pack_root)
    checks = [
        _private_data_check(root),
        _hidden_gold_leakage_check(root),
        _schema_dry_run_check(root, schema_dry_run_output),
        _reproducible_build_check(root, reproducibility_output),
        _docs_updated_check(Path(docs_path)),
        _quality_commands_check(),
    ]
    status = "pass" if all(check.passed for check in checks) else "fail"
    return ReleaseReadinessReport(
        task_pack_root=str(root),
        status=status,
        checks=tuple(checks),
    )


def _private_data_check(root: Path) -> ReleaseReadinessCheck:
    findings: list[dict[str, Any]] = []
    scanned_files = 0
    for path in _iter_text_files(root):
        scanned_files += 1
        text = path.read_text(encoding="utf-8")
        for marker in PRIVATE_DATA_MARKERS:
            if marker in text:
                findings.append(
                    {
                        "path": _display_path(path, root),
                        "marker": marker,
                    }
                )
    return ReleaseReadinessCheck(
        name="no_private_data",
        passed=not findings,
        details={
            "scanned_files": scanned_files,
            "private_marker_findings": findings,
        },
    )


def _hidden_gold_leakage_check(root: Path) -> ReleaseReadinessCheck:
    task_dirs = sorted((root / "tasks").glob("T*_*/"))
    leakage_reports = [validate_leakage_audit(task_dir) for task_dir in task_dirs]
    failures = [
        {
            "task_id": report.get("task_id"),
            "failures": report.get("failures") or [],
        }
        for report in leakage_reports
        if not report.get("independent_audit_pass")
    ]
    return ReleaseReadinessCheck(
        name="no_hidden_gold_leakage",
        passed=not failures and bool(task_dirs),
        details={
            "task_count": len(task_dirs),
            "failed_tasks": failures,
        },
    )


def _schema_dry_run_check(
    root: Path, output_dir: str | Path | None
) -> ReleaseReadinessCheck:
    if output_dir is None:
        with TemporaryDirectory(prefix="rfb-release-schema-dry-run-") as tmp_dir:
            summary = run_schema_dry_run(root, tmp_dir)
    else:
        summary = run_schema_dry_run(root, output_dir)
    return ReleaseReadinessCheck(
        name="schema_dry_run_pass",
        passed=bool(summary.get("dry_run_pass")),
        details=summary,
    )


def _reproducible_build_check(
    root: Path, output_dir: str | Path | None
) -> ReleaseReadinessCheck:
    if output_dir is None:
        with TemporaryDirectory(prefix="rfb-release-rebuild-") as tmp_dir:
            return _compare_rebuilt_pack(root, Path(tmp_dir) / "pilot20")
    out = Path(output_dir)
    if out.exists():
        shutil.rmtree(out)
    return _compare_rebuilt_pack(root, out)


def _compare_rebuilt_pack(root: Path, generated_root: Path) -> ReleaseReadinessCheck:
    result = build_synthetic_pilot20_task_pack(generated_root)
    expected_files = _relative_files(root)
    actual_files = _relative_files(result.root)
    shared_files = sorted(expected_files & actual_files)
    hash_mismatches = [
        rel_path
        for rel_path in shared_files
        if _sha256(root / rel_path) != _sha256(result.root / rel_path)
    ]
    missing_files = sorted(expected_files - actual_files)
    extra_files = sorted(actual_files - expected_files)
    return ReleaseReadinessCheck(
        name="reproducible_build",
        passed=not missing_files and not extra_files and not hash_mismatches,
        details={
            "generated_root": str(result.root),
            "expected_file_count": len(expected_files),
            "actual_file_count": len(actual_files),
            "missing_files": missing_files,
            "extra_files": extra_files,
            "hash_mismatches": hash_mismatches,
        },
    )


def _docs_updated_check(docs_path: Path) -> ReleaseReadinessCheck:
    if not docs_path.exists():
        return ReleaseReadinessCheck(
            name="docs_updated",
            passed=False,
            details={"docs_path": str(docs_path), "missing": True},
        )
    text = docs_path.read_text(encoding="utf-8").lower()
    missing = [snippet for snippet in REQUIRED_DOC_SNIPPETS if snippet not in text]
    return ReleaseReadinessCheck(
        name="docs_updated",
        passed=not missing,
        details={
            "docs_path": str(docs_path),
            "required_snippets": list(REQUIRED_DOC_SNIPPETS),
            "missing_snippets": missing,
        },
    )


def _quality_commands_check() -> ReleaseReadinessCheck:
    return ReleaseReadinessCheck(
        name="ruff_and_tests_commanded",
        passed=True,
        details={
            "commands": list(QUALITY_COMMANDS),
            "note": (
                "Release readiness requires these focused commands to pass in "
                "the operator environment before public status changes."
            ),
        },
    )


def _iter_text_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        yield path


def _relative_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def write_release_readiness_report(
    report: ReleaseReadinessReport, out_file: str | Path
) -> Path:
    path = Path(out_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
