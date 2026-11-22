#!/usr/bin/env python3
"""Check Research Harness package-boundary import direction.

The physical `_core/_workflow/_evolution` split is still planned, so this guard
also enforces the current stable islands. It must never pass vacuously: if the
current directories disappear or no files are scanned, the script fails.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "packages" / "research_harness" / "research_harness"
DOC_PATH = ROOT / "docs" / "architecture-package-split.md"

CURRENT_ALLOWED_DEPS = {
    "_core": set(),
    "storage": {"_core"},
    "core": {"_core"},
}

# The canonical evolution package is ``research_harness.evolution``; the
# ``_evolution`` physical split target does not exist yet. ``_core`` must not
# import the evolution layer, so the REAL package name is forbidden here (the
# legacy ``_evolution`` name is kept for forward-compat).
#
# Known debt (intentionally not enforced yet, to avoid masking it):
#   * ``_workflow -> research_harness.evolution`` reverse imports exist
#     (execution/harness.py, execution/llm_primitives.py) and are a documented
#     split blocker, so ``evolution`` is intentionally not forbidden for
#     ``_workflow`` yet.
#   * The merged top-level packages ``_selfdev``/``integrations``/``acquisition``
#     /``_productization`` are not yet modeled as scanned source islands.
FUTURE_BOUNDARIES = {
    "_core": {
        "research_harness._workflow",
        "research_harness._evolution",
        "research_harness.evolution",
    },
    "_workflow": {"research_harness._evolution"},
    "_evolution": set(),
}

WORKFLOW_EXECUTION_COMPAT_MODULES = (
    "backend",
    "prompts",
    "writing_checks",
    "dag_reasoning",
    "claim_verification",
    "compiled_summary",
    "harness_actions",
    "loops",
    "fal_image_client",
    "latex_compiler",
    "local",
    "harness",
    "tracked",
    "claude_code",
    "factory",
    "llm_primitives",
)

WORKFLOW_ORCHESTRATOR_COMPAT_MODULES = (
    "adversarial",
    "artifacts",
    "claims",
    "integrity",
    "invariants",
    "judge",
    "models",
    "review",
    "serializers",
    "service",
    "snapshots",
    "stages",
    "transitions",
)


def _module_names(node: ast.AST, *, path: Path) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        if node.level:
            rel = path.relative_to(PACKAGE_ROOT).with_suffix("")
            package_parts = ["research_harness", *rel.parts[:-1]]
            base = package_parts[: len(package_parts) - node.level + 1]
            return [".".join([*base, *node.module.split(".")])]
        return [node.module]
    return []


def _existing_subpackages() -> set[str]:
    return {
        path.name
        for path in PACKAGE_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }


def _current_forbidden_prefixes(directory: str) -> set[str]:
    allowed = {directory, *CURRENT_ALLOWED_DEPS[directory]}
    return {
        f"research_harness.{name}"
        for name in _existing_subpackages()
        if name not in allowed
    }


def _violations() -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    scanned: dict[str, int] = {}

    for directory in CURRENT_ALLOWED_DEPS:
        package_dir = PACKAGE_ROOT / directory
        if not package_dir.exists():
            errors.append(f"current boundary directory missing: {package_dir}")
            continue
        forbidden = _current_forbidden_prefixes(directory)
        scanned[directory] = _scan_directory(package_dir, forbidden, errors)

    for directory, forbidden in FUTURE_BOUNDARIES.items():
        package_dir = PACKAGE_ROOT / directory
        if not package_dir.exists():
            continue
        scanned[directory] = _scan_directory(package_dir, forbidden, errors)

    errors.extend(
        _workflow_shim_violations(
            public_package="execution",
            canonical_package="execution",
            module_names=WORKFLOW_EXECUTION_COMPAT_MODULES,
        )
    )
    errors.extend(
        _workflow_shim_violations(
            public_package="orchestrator",
            canonical_package="orchestrator",
            module_names=WORKFLOW_ORCHESTRATOR_COMPAT_MODULES,
        )
    )

    if not any(scanned.values()):
        errors.append("architecture boundary check scanned zero Python files")
    return errors, scanned


def _scan_directory(
    package_dir: Path,
    forbidden: set[str],
    errors: list[str],
) -> int:
    scanned = 0
    for path in sorted(package_dir.rglob("*.py")):
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            errors.append(f"{path}: cannot parse Python: {exc}")
            continue
        for node in ast.walk(tree):
            for module in _module_names(node, path=path):
                if any(
                    module == prefix or module.startswith(f"{prefix}.")
                    for prefix in forbidden
                ):
                    rel = path.relative_to(ROOT)
                    errors.append(f"{rel}: imports forbidden module {module}")
    return scanned


def _workflow_shim_violations(
    *,
    public_package: str,
    canonical_package: str,
    module_names: tuple[str, ...],
) -> list[str]:
    errors: list[str] = []
    for module_name in module_names:
        canonical_path = (
            PACKAGE_ROOT / "_workflow" / canonical_package / f"{module_name}.py"
        )
        public_path = PACKAGE_ROOT / public_package / f"{module_name}.py"

        if not canonical_path.is_file():
            errors.append(f"workflow canonical module missing: {canonical_path}")
            continue
        if not public_path.is_file():
            errors.append(f"workflow compatibility shim missing: {public_path}")
            continue

        text = public_path.read_text(encoding="utf-8")
        expected_snippets = (
            f"from research_harness._workflow.{canonical_package} import {module_name} as _canonical",
            "_PUBLIC_MODULE_NAME = __name__",
            "globals().update(_canonical.__dict__)",
            "sys.modules[_PUBLIC_MODULE_NAME] = _canonical",
        )
        for snippet in expected_snippets:
            if snippet not in text:
                rel = public_path.relative_to(ROOT)
                errors.append(f"{rel}: missing workflow shim snippet: {snippet}")
    return errors


def main() -> int:
    errors: list[str] = []
    if not DOC_PATH.is_file():
        errors.append("docs/architecture-package-split.md is missing")
    else:
        text = DOC_PATH.read_text(encoding="utf-8")
        for marker in ("research_harness_core", "_core", "_workflow", "_evolution"):
            if marker not in text:
                errors.append(f"docs/architecture-package-split.md missing {marker}")

    violations, scanned = _violations()
    errors.extend(violations)

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    checked = ", ".join(f"{name}={count}" for name, count in sorted(scanned.items()))
    print(f"Architecture boundary check passed; scanned {checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
