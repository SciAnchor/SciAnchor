from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "scripts").exists()
)


def load_gate_module():
    script_path = REPO_ROOT / "scripts" / "check-release-gates.py"
    spec = importlib.util.spec_from_file_location("release_gate_guard", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_inputs(module):
    return {
        "ci_text": module.CI_WORKFLOW_PATH.read_text(encoding="utf-8"),
        "release_text": module.RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8"),
        "codex_check_text": module.CODEX_CHECK_PATH.read_text(encoding="utf-8"),
        "smoke_text": module.RELEASE_SMOKE_PATH.read_text(encoding="utf-8"),
        "dependency_audit_text": module.DEPENDENCY_AUDIT_PATH.read_text(
            encoding="utf-8"
        ),
        "coverage_baseline_text": module.COVERAGE_BASELINE_PATH.read_text(
            encoding="utf-8"
        ),
        "coverage_threshold_text": module.COVERAGE_THRESHOLD_PATH.read_text(
            encoding="utf-8"
        ),
        "worktree_inventory_text": module.WORKTREE_INVENTORY_PATH.read_text(
            encoding="utf-8"
        ),
        "research_harness_pyproject_text": module.RESEARCH_HARNESS_PYPROJECT_PATH.read_text(
            encoding="utf-8"
        ),
        "research_harness_mcp_pyproject_text": module.RESEARCH_HARNESS_MCP_PYPROJECT_PATH.read_text(
            encoding="utf-8"
        ),
    }


def test_release_gate_guard_accepts_current_ci_and_scripts():
    module = load_gate_module()

    errors = module.validate_release_gates(**current_inputs(module))

    assert errors == []


def test_release_gate_guard_requires_full_codex_check_in_ci():
    module = load_gate_module()
    inputs = current_inputs(module)
    inputs["ci_text"] = inputs["ci_text"].replace("scripts/codex-check.sh --full", "")

    errors = module.validate_release_gates(**inputs)

    assert any("CI is missing full codex check" in error for error in errors)


def test_release_gate_guard_requires_coverage_codex_check_in_ci():
    module = load_gate_module()
    inputs = current_inputs(module)
    inputs["ci_text"] = inputs["ci_text"].replace(
        "scripts/codex-check.sh --coverage", ""
    )

    errors = module.validate_release_gates(**inputs)

    assert any("CI is missing coverage codex check" in error for error in errors)


def test_release_gate_guard_requires_release_quick_gate_before_publish():
    module = load_gate_module()
    inputs = current_inputs(module)
    inputs["release_text"] = inputs["release_text"].replace(
        "scripts/codex-check.sh --quick",
        "",
    )

    errors = module.validate_release_gates(**inputs)

    assert any(
        "release workflow is missing quick codex check" in error for error in errors
    )


def test_release_gate_guard_requires_tag_ref_checkout_before_publish():
    module = load_gate_module()
    inputs = current_inputs(module)
    inputs["release_text"] = inputs["release_text"].replace(
        "          ref: refs/tags/${{ inputs.tag }}\n",
        "",
    )

    errors = module.validate_release_gates(**inputs)

    assert any(
        "release workflow checkout must use the requested tag ref" in error
        for error in errors
    )


def test_release_gate_guard_requires_full_coverage_audit_before_publish():
    module = load_gate_module()
    inputs = current_inputs(module)
    inputs["release_text"] = inputs["release_text"].replace(
        "      - name: Full release guards\n"
        "        run: scripts/codex-check.sh --full\n\n",
        "",
    )

    errors = module.validate_release_gates(**inputs)

    assert any(
        "release workflow is missing full codex check" in error for error in errors
    )
    assert any(
        "release workflow required steps are out of order" in error for error in errors
    )


def test_release_gate_guard_requires_dependency_security_floors():
    module = load_gate_module()
    inputs = current_inputs(module)
    inputs["release_text"] = inputs["release_text"].replace('"pip>=26.1.2"', "pip")
    inputs["research_harness_pyproject_text"] = inputs[
        "research_harness_pyproject_text"
    ].replace('"idna>=3.15"', "")
    inputs["research_harness_mcp_pyproject_text"] = (
        inputs["research_harness_mcp_pyproject_text"]
        .replace('"PyJWT>=2.13.0"', "")
        .replace('"starlette>=1.0.1"', "")
    )
    inputs["research_harness_pyproject_text"] = (
        inputs["research_harness_pyproject_text"]
        .replace('"llm-router[all]"', '"llm-router @ git+ssh://example.com/r.git"')
        .replace('"paperindex"', "")
    )

    errors = module.validate_release_gates(**inputs)

    assert any(
        "release workflow must upgrade pip to >=26.1.2" in error for error in errors
    )
    assert any("research-harness must require idna>=3.15" in error for error in errors)
    assert any(
        "research-harness-mcp must require PyJWT>=2.13.0" in error for error in errors
    )
    assert any(
        "research-harness-mcp must require starlette>=1.0.1" in error
        for error in errors
    )
    assert any(
        "research-harness must require llm-router[all]" in error for error in errors
    )
    assert any("research-harness must require paperindex" in error for error in errors)
    assert any(
        "research-harness must not use private git+ssh dependencies" in error
        for error in errors
    )


def test_release_gate_guard_requires_live_http_route_smoke():
    module = load_gate_module()
    inputs = current_inputs(module)
    inputs["smoke_text"] = (
        inputs["smoke_text"]
        .replace("uvicorn", "")
        .replace("urllib.request", "")
        .replace('"/api/topics"', '""')
    )

    errors = module.validate_release_gates(**inputs)

    assert any(
        "release smoke is missing live HTTP route smoke" in error for error in errors
    )


def test_release_gate_guard_requires_advisory_dependency_audit():
    module = load_gate_module()
    inputs = current_inputs(module)
    inputs["ci_text"] = inputs["ci_text"].replace(
        "scripts/dependency-audit-report.sh",
        "",
    )

    errors = module.validate_release_gates(**inputs)

    assert any("CI is missing advisory dependency audit" in error for error in errors)


def test_release_gate_guard_requires_coverage_threshold_checker():
    module = load_gate_module()
    inputs = current_inputs(module)
    inputs["coverage_baseline_text"] = inputs["coverage_baseline_text"].replace(
        "check-coverage-threshold.py",
        "",
    )

    errors = module.validate_release_gates(**inputs)

    assert any(
        "coverage baseline script is missing threshold checker" in error
        for error in errors
    )


def test_release_gate_guard_requires_worktree_inventory_guard():
    module = load_gate_module()
    inputs = current_inputs(module)
    inputs["codex_check_text"] = inputs["codex_check_text"].replace(
        "scripts/worktree-inventory.py",
        "",
    )

    errors = module.validate_release_gates(**inputs)

    assert any(
        "codex-check is missing worktree inventory guard" in error for error in errors
    )
