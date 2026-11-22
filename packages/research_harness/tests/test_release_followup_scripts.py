from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "scripts").exists()
)


def load_script(path: str, module_name: str):
    script_path = REPO_ROOT / path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _release_gate_inputs(module) -> dict[str, str]:
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


def test_coverage_threshold_accepts_current_non_regression_floor():
    module = load_script("scripts/check-coverage-threshold.py", "coverage_threshold")

    errors = module.validate_coverage_threshold(
        measured_percent=24.29,
        threshold_percent=24.0,
    )

    assert errors == []


def test_coverage_threshold_rejects_regression_below_floor():
    module = load_script("scripts/check-coverage-threshold.py", "coverage_threshold")

    errors = module.validate_coverage_threshold(
        measured_percent=23.99,
        threshold_percent=24.0,
    )

    assert errors == [
        "coverage regression: 23.99% is below threshold 24.00%",
    ]


def test_worktree_inventory_classifies_selfdev_gate_evidence():
    module = load_script("scripts/worktree-inventory.py", "worktree_inventory")

    entry = module.classify_path(
        ".rh-selfdev/gates/LG14_RELEASE_FOLLOWUP_CLOSURE_GATE-20260615T000000Z.md"
    )

    assert entry.category == "rh_self_dev_gates_handoffs_checkpoints"
    assert entry.commit_inclusion_status == "include"


def test_worktree_inventory_classifies_source_tests_and_scripts():
    module = load_script("scripts/worktree-inventory.py", "worktree_inventory")

    source = module.classify_path(
        "packages/research_harness_mcp/research_harness_mcp/new_route.py"
    )
    test = module.classify_path("packages/research_harness_mcp/tests/test_new_route.py")
    script = module.classify_path("scripts/check-new-release-gate.py")

    deploy = module.classify_path("deploy/gateway.env.example")
    plugin = module.classify_path(
        "integrations/example-plugin/.claude-plugin/plugin.json"
    )

    assert source.category == "new_source_modules"
    assert test.category == "new_tests"
    assert script.category == "scripts"
    assert deploy.category == "deploy_templates"
    assert plugin.category == "integrations"
    assert deploy.commit_inclusion_status == "include"
    assert plugin.commit_inclusion_status == "include"

    # A filled-in env file under deploy/ is a secret, not a template.
    for private in (
        "deploy/ticket-worker.env",
        "deploy/agent.env",
        "deploy/prod.env.local",
    ):
        entry = module.classify_path(private)
        assert entry.commit_inclusion_status == "exclude_before_commit", private
    assert (
        module.classify_path("deploy/environment.yml").commit_inclusion_status
        == "include"
    )


def test_worktree_inventory_flags_generated_and_private_artifacts():
    module = load_script("scripts/worktree-inventory.py", "worktree_inventory")

    generated = module.classify_path(
        "packages/research_harness/tests/__pycache__/x.pyc"
    )
    private = module.classify_path(".env")

    assert generated.category == "unexpected_generated_artifacts"
    assert private.category == "unexpected_generated_artifacts"
    assert generated.commit_inclusion_status == "exclude_before_commit"
    assert private.commit_inclusion_status == "exclude_before_commit"


def test_worktree_inventory_summary_counts_unexpected():
    module = load_script("scripts/worktree-inventory.py", "worktree_inventory")

    inventory = module.build_inventory(
        [
            ".rh-selfdev/handoffs/LG14_RELEASE_FOLLOWUP_CLOSURE-20260615T000000Z.md",
            "packages/research_harness/tests/test_new_gate.py",
            "site/generated/index.html",
        ]
    )

    assert inventory["total_untracked"] == 3
    assert inventory["unexpected_count"] == 1
    assert inventory["summary"]["rh_self_dev_gates_handoffs_checkpoints"] == 1
    assert inventory["summary"]["new_tests"] == 1


def test_release_gate_rejects_push_triggered_release_publishing():
    module = load_script("scripts/check-release-gates.py", "release_gates")
    inputs = _release_gate_inputs(module)
    bad_release_text = inputs["release_text"].replace(
        "workflow_dispatch:",
        "push:\n    branches: [main]\n  workflow_dispatch:",
    )

    errors = module.validate_release_gates(
        **{
            **inputs,
            "release_text": bad_release_text,
        }
    )

    assert "release workflow must not publish GitHub releases on push to main" in errors


def test_dependency_audit_required_report_rejects_stale_report_after_audit_failure(
    tmp_path: Path,
):
    fake_python = tmp_path / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"--version"* ]]; then\n'
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    report_dir = tmp_path / "audit"
    report_dir.mkdir()
    (report_dir / "pip-audit-report.json").write_text(
        '{"dependencies": [], "stale": true}\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "dependency-audit-report.sh"),
            "--require-report",
            str(report_dir),
        ],
        check=False,
        cwd=REPO_ROOT,
        env={**os.environ, "RESEARCH_HARNESS_PYTHON": str(fake_python)},
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "required dependency audit report was not generated" in result.stderr
