#!/usr/bin/env python3
"""Check that release CI and local gate scripts include required guard rails."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release.yml"
CODEX_CHECK_PATH = ROOT / "scripts" / "codex-check.sh"
RELEASE_SMOKE_PATH = ROOT / "scripts" / "release-artifact-smoke.sh"
DEPENDENCY_AUDIT_PATH = ROOT / "scripts" / "dependency-audit-report.sh"
COVERAGE_BASELINE_PATH = ROOT / "scripts" / "coverage-baseline.sh"
COVERAGE_THRESHOLD_PATH = ROOT / "scripts" / "check-coverage-threshold.py"
CRITICAL_PATH_COVERAGE_PATH = ROOT / "scripts" / "check-critical-path-coverage.py"
WORKTREE_INVENTORY_PATH = ROOT / "scripts" / "worktree-inventory.py"
RESEARCH_HARNESS_PYPROJECT_PATH = (
    ROOT / "packages" / "research_harness" / "pyproject.toml"
)
RESEARCH_HARNESS_MCP_PYPROJECT_PATH = (
    ROOT / "packages" / "research_harness_mcp" / "pyproject.toml"
)
LLM_ROUTER_PYPROJECT_PATH = ROOT / "packages" / "llm_router" / "pyproject.toml"
PAPERINDEX_PYPROJECT_PATH = ROOT / "packages" / "paperindex" / "pyproject.toml"
SKILLS_MANIFEST_PATH = ROOT / "skills" / "manifest.json"


def _require_contains(
    errors: list[str],
    *,
    text: str,
    needle: str,
    message: str,
) -> None:
    if needle not in text:
        errors.append(message)


def _workflow_steps(workflow_text: str) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in workflow_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            current = {"name": stripped.removeprefix("- name:").strip(), "lines": []}
            steps.append(current)
            continue
        if current is not None:
            current_lines = current["lines"]
            assert isinstance(current_lines, list)
            current_lines.append(line)
    return steps


def _step_index(steps: list[dict[str, object]], name: str) -> int | None:
    for index, step in enumerate(steps):
        if step.get("name") == name:
            return index
    return None


def _step_text(steps: list[dict[str, object]], name: str) -> str:
    for step in steps:
        if step.get("name") != name:
            continue
        lines = step.get("lines", [])
        assert isinstance(lines, list)
        return "\n".join(str(line) for line in lines)
    return ""


def _require_step_contains(
    errors: list[str],
    *,
    steps: list[dict[str, object]],
    step_name: str,
    needle: str,
    message: str,
) -> None:
    text = _step_text(steps, step_name)
    if not text or needle not in text:
        errors.append(message)


def _require_step_order(
    errors: list[str],
    *,
    steps: list[dict[str, object]],
    names: tuple[str, ...],
    message: str,
) -> None:
    indexes = [_step_index(steps, name) for name in names]
    if any(index is None for index in indexes):
        errors.append(message)
        return
    concrete_indexes = [int(index) for index in indexes if index is not None]
    if concrete_indexes != sorted(concrete_indexes):
        errors.append(message)


def _has_push_trigger(workflow_text: str) -> bool:
    lines = workflow_text.splitlines()
    in_on_block = False
    for line in lines:
        if line.startswith("on:"):
            in_on_block = True
            if "push" in line:
                return True
            continue
        if not in_on_block:
            continue
        if line and not line.startswith((" ", "\t")):
            return False
        if line.strip().startswith("push:"):
            return True
    return False


def validate_release_gates(
    *,
    ci_text: str,
    release_text: str,
    codex_check_text: str,
    smoke_text: str,
    dependency_audit_text: str,
    coverage_baseline_text: str,
    coverage_threshold_text: str,
    worktree_inventory_text: str,
    research_harness_pyproject_text: str,
    research_harness_mcp_pyproject_text: str,
) -> list[str]:
    errors: list[str] = []

    _require_contains(
        errors,
        text=ci_text,
        needle="scripts/codex-check.sh --full",
        message="CI is missing full codex check",
    )
    _require_contains(
        errors,
        text=ci_text,
        needle="scripts/codex-check.sh --coverage",
        message="CI is missing coverage codex check",
    )
    _require_contains(
        errors,
        text=ci_text,
        needle="scripts/release-artifact-smoke.sh",
        message="CI is missing release artifact smoke",
    )
    _require_contains(
        errors,
        text=ci_text,
        needle="ruff check packages/",
        message="CI is missing ruff check",
    )
    _require_contains(
        errors,
        text=ci_text,
        needle="ruff format --check packages/",
        message="CI is missing ruff format check",
    )
    _require_contains(
        errors,
        text=ci_text,
        needle="scripts/check-release-gates.py",
        message="CI is missing release gate self-check",
    )
    _require_contains(
        errors,
        text=ci_text,
        needle="scripts/dependency-audit-report.sh",
        message="CI is missing advisory dependency audit",
    )

    _require_contains(
        errors,
        text=release_text,
        needle="workflow_dispatch:",
        message="release workflow is missing manual workflow_dispatch trigger",
    )
    _require_contains(
        errors,
        text=release_text,
        needle="inputs:",
        message="release workflow is missing explicit dispatch inputs",
    )
    _require_contains(
        errors,
        text=release_text,
        needle="inputs.tag",
        message="release workflow is missing explicit tag input",
    )
    if _has_push_trigger(release_text) and "gh release create" in release_text:
        errors.append(
            "release workflow must not publish GitHub releases on push to main"
        )

    _require_contains(
        errors,
        text=release_text,
        needle="scripts/codex-check.sh --quick",
        message="release workflow is missing quick codex check",
    )
    _require_contains(
        errors,
        text=release_text,
        needle="scripts/release-artifact-smoke.sh",
        message="release workflow is missing release artifact smoke",
    )
    _require_contains(
        errors,
        text=release_text,
        needle="scripts/codex-check.sh --full",
        message="release workflow is missing full codex check",
    )
    _require_contains(
        errors,
        text=release_text,
        needle="scripts/codex-check.sh --coverage",
        message="release workflow is missing coverage codex check",
    )
    _require_contains(
        errors,
        text=release_text,
        needle="dependency-audit-report.sh --require-report",
        message="release workflow is missing required dependency audit",
    )

    release_steps = _workflow_steps(release_text)
    _require_step_contains(
        errors,
        steps=release_steps,
        step_name="Checkout",
        needle="ref: refs/tags/${{ inputs.tag }}",
        message="release workflow checkout must use the requested tag ref",
    )
    _require_step_contains(
        errors,
        steps=release_steps,
        step_name="Verify requested tag checkout",
        needle='tag_commit="$(git rev-parse "refs/tags/$tag^{}")"',
        message="release workflow must verify HEAD matches the requested tag commit",
    )
    _require_step_order(
        errors,
        steps=release_steps,
        names=(
            "Checkout",
            "Verify requested tag checkout",
            "Install packages",
            "Quick release guards",
            "Full release guards",
            "Coverage release guards",
            "Required dependency audit",
            "Release artifact smoke",
            "Publish requested release",
        ),
        message="release workflow required steps are out of order",
    )
    _require_contains(
        errors,
        text=release_text,
        needle='"pip>=26.1.2"',
        message="release workflow must upgrade pip to >=26.1.2",
    )
    _require_contains(
        errors,
        text=research_harness_pyproject_text,
        needle='"idna>=3.15"',
        message="research-harness must require idna>=3.15",
    )
    _require_contains(
        errors,
        text=research_harness_mcp_pyproject_text,
        needle='"PyJWT>=2.13.0"',
        message="research-harness-mcp must require PyJWT>=2.13.0",
    )
    _require_contains(
        errors,
        text=research_harness_mcp_pyproject_text,
        needle='"starlette>=1.0.1"',
        message="research-harness-mcp must require starlette>=1.0.1",
    )
    # Workspace sibling packages (packages/llm_router, packages/paperindex) are
    # declared as standard package requirements without private git+ssh pins.
    _require_contains(
        errors,
        text=research_harness_pyproject_text,
        needle='"llm-router[all]"',
        message="research-harness must require llm-router[all]",
    )
    _require_contains(
        errors,
        text=research_harness_pyproject_text,
        needle='"paperindex"',
        message="research-harness must require paperindex",
    )
    if "git+ssh://" in research_harness_pyproject_text:
        errors.append("research-harness must not use private git+ssh dependencies")
    _require_contains(
        errors,
        text=ci_text,
        needle='pip install -e "packages/llm_router[all]"',
        message="CI is missing workspace llm_router editable install",
    )
    _require_contains(
        errors,
        text=ci_text,
        needle='pip install -e "packages/paperindex"',
        message="CI is missing workspace paperindex editable install",
    )
    _require_contains(
        errors,
        text=release_text,
        needle='pip install -e "packages/llm_router[all]"',
        message="release workflow is missing workspace llm_router editable install",
    )
    _require_contains(
        errors,
        text=release_text,
        needle='pip install -e "packages/paperindex"',
        message="release workflow is missing workspace paperindex editable install",
    )

    for needle, message in (
        ("scripts/check-mcp-public-surface.py", "codex-check is missing MCP guard"),
        ("scripts/check-service-coverage.py", "codex-check is missing service guard"),
        (
            "scripts/check-transport-service-coverage.py",
            "codex-check is missing transport guard",
        ),
        (
            "scripts/check-release-doc-consistency.py",
            "codex-check is missing release-doc guard",
        ),
        ("scripts/dump-schema.py --check", "codex-check is missing schema check"),
        ("run_python_full", "codex-check is missing full Python test path"),
        ("run_mcp", "codex-check is missing MCP smoke path"),
        ("run_dependency_audit", "codex-check is missing dependency audit path"),
        ("run_coverage_baseline", "codex-check is missing coverage baseline path"),
        (
            "scripts/check-critical-path-coverage.py",
            "codex-check is missing critical path coverage guard",
        ),
        (
            "scripts/worktree-inventory.py",
            "codex-check is missing worktree inventory guard",
        ),
    ):
        _require_contains(
            errors,
            text=codex_check_text,
            needle=needle,
            message=message,
        )

    for needle, message in (
        ("schema_migrations", "release smoke is missing migration replay check"),
        ("research_harness_mcp.tools", "release smoke is missing MCP import smoke"),
        ('rh" --help', "release smoke is missing CLI smoke"),
        ("uvicorn", "release smoke is missing live HTTP route smoke"),
        ("urllib.request", "release smoke is missing live HTTP route smoke"),
        ('"/api/topics"', "release smoke is missing live HTTP route smoke"),
        ('"/api/papers"', "release smoke is missing live HTTP route smoke"),
        (
            "RESEARCH_HARNESS_DB_PATH",
            "release smoke is missing live HTTP route smoke",
        ),
    ):
        _require_contains(errors, text=smoke_text, needle=needle, message=message)

    _require_contains(
        errors,
        text=dependency_audit_text,
        needle="pip-audit",
        message="dependency audit report script is missing pip-audit entry",
    )
    _require_contains(
        errors,
        text=dependency_audit_text,
        needle="advisory",
        message="dependency audit report script is not advisory",
    )
    _require_contains(
        errors,
        text=dependency_audit_text,
        needle="--require-report",
        message="dependency audit report script is missing require-report mode",
    )
    _require_contains(
        errors,
        text=coverage_baseline_text,
        needle="pytest-cov",
        message="coverage baseline script is missing pytest-cov check",
    )
    _require_contains(
        errors,
        text=coverage_baseline_text,
        needle="--cov-report",
        message="coverage baseline script is missing coverage report output",
    )
    _require_contains(
        errors,
        text=coverage_baseline_text,
        needle="check-coverage-threshold.py",
        message="coverage baseline script is missing threshold checker",
    )
    _require_contains(
        errors,
        text=coverage_threshold_text,
        needle="threshold_percent",
        message="coverage threshold checker is missing threshold decision support",
    )
    _require_contains(
        errors,
        text=worktree_inventory_text,
        needle="unexpected_generated_artifacts",
        message="worktree inventory guard is missing generated artifact classification",
    )
    _require_contains(
        errors,
        text=worktree_inventory_text,
        needle="exclude_before_commit",
        message="worktree inventory guard is missing commit inclusion status",
    )

    return errors


def main() -> int:
    paths = (
        CI_WORKFLOW_PATH,
        RELEASE_WORKFLOW_PATH,
        CODEX_CHECK_PATH,
        RELEASE_SMOKE_PATH,
        DEPENDENCY_AUDIT_PATH,
        COVERAGE_BASELINE_PATH,
        COVERAGE_THRESHOLD_PATH,
        CRITICAL_PATH_COVERAGE_PATH,
        WORKTREE_INVENTORY_PATH,
        RESEARCH_HARNESS_PYPROJECT_PATH,
        RESEARCH_HARNESS_MCP_PYPROJECT_PATH,
        LLM_ROUTER_PYPROJECT_PATH,
        PAPERINDEX_PYPROJECT_PATH,
        SKILLS_MANIFEST_PATH,
    )
    missing = [path for path in paths if not path.is_file()]
    if missing:
        for path in missing:
            print(f"FAIL: missing gate file: {path.relative_to(ROOT)}", file=sys.stderr)
        return 1

    errors = validate_release_gates(
        ci_text=CI_WORKFLOW_PATH.read_text(encoding="utf-8"),
        release_text=RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8"),
        codex_check_text=CODEX_CHECK_PATH.read_text(encoding="utf-8"),
        smoke_text=RELEASE_SMOKE_PATH.read_text(encoding="utf-8"),
        dependency_audit_text=DEPENDENCY_AUDIT_PATH.read_text(encoding="utf-8"),
        coverage_baseline_text=COVERAGE_BASELINE_PATH.read_text(encoding="utf-8"),
        coverage_threshold_text=COVERAGE_THRESHOLD_PATH.read_text(encoding="utf-8"),
        worktree_inventory_text=WORKTREE_INVENTORY_PATH.read_text(encoding="utf-8"),
        research_harness_pyproject_text=RESEARCH_HARNESS_PYPROJECT_PATH.read_text(
            encoding="utf-8"
        ),
        research_harness_mcp_pyproject_text=RESEARCH_HARNESS_MCP_PYPROJECT_PATH.read_text(
            encoding="utf-8"
        ),
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("Release gate guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
