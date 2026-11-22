from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "scripts").exists()
)


def load_guard_module():
    script_path = REPO_ROOT / "scripts" / "check-critical-path-coverage.py"
    assert script_path.exists()
    spec = importlib.util.spec_from_file_location(
        "critical_path_coverage_guard", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_critical_path_coverage_guard_accepts_current_matrix():
    module = load_guard_module()

    errors = module.validate_critical_path_coverage(
        coverage_text=module.COVERAGE_PATH.read_text(encoding="utf-8"),
        codex_check_text=module.CODEX_CHECK_PATH.read_text(encoding="utf-8"),
        coverage_baseline_text=module.COVERAGE_BASELINE_PATH.read_text(
            encoding="utf-8"
        ),
        root=module.ROOT,
    )

    assert errors == []


def test_critical_path_coverage_guard_requires_all_critical_paths():
    module = load_guard_module()
    coverage_text = module.COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "| `topic_knowledge` | `covered` | `scripts/check-service-coverage.py` | `packages/research_harness/tests/test_topic_knowledge_status.py`, `packages/research_harness/tests/test_topic_knowledge_layer.py`, `packages/research_harness_mcp/tests/test_topic_knowledge_status_http.py`, `packages/research_harness_mcp/tests/test_topic_knowledge_refresh_http.py` | `scripts/codex-check.sh --coverage` |\n",
        "",
    )

    errors = module.validate_critical_path_coverage(
        coverage_text=coverage_text,
        codex_check_text=module.CODEX_CHECK_PATH.read_text(encoding="utf-8"),
        coverage_baseline_text=module.COVERAGE_BASELINE_PATH.read_text(
            encoding="utf-8"
        ),
        root=module.ROOT,
    )

    assert any("missing critical paths" in error for error in errors)


def test_critical_path_coverage_guard_rejects_missing_focused_test_path():
    module = load_guard_module()
    coverage_text = module.COVERAGE_PATH.read_text(encoding="utf-8").replace(
        "packages/research_harness/tests/test_service_layer.py",
        "packages/research_harness/tests/test_missing_service_layer.py",
    )

    errors = module.validate_critical_path_coverage(
        coverage_text=coverage_text,
        codex_check_text=module.CODEX_CHECK_PATH.read_text(encoding="utf-8"),
        coverage_baseline_text=module.COVERAGE_BASELINE_PATH.read_text(
            encoding="utf-8"
        ),
        root=module.ROOT,
    )

    assert any("referenced files are missing" in error for error in errors)


def test_critical_path_coverage_guard_requires_codex_coverage_hook():
    module = load_guard_module()
    codex_check_text = module.CODEX_CHECK_PATH.read_text(encoding="utf-8").replace(
        "scripts/check-critical-path-coverage.py",
        "scripts/check-other-coverage.py",
    )

    errors = module.validate_critical_path_coverage(
        coverage_text=module.COVERAGE_PATH.read_text(encoding="utf-8"),
        codex_check_text=codex_check_text,
        coverage_baseline_text=module.COVERAGE_BASELINE_PATH.read_text(
            encoding="utf-8"
        ),
        root=module.ROOT,
    )

    assert any(
        "codex-check --coverage is missing critical path guard" in error
        for error in errors
    )


def test_critical_path_coverage_guard_rejects_focused_test_not_run_by_coverage():
    module = load_guard_module()
    coverage_baseline_text = module.COVERAGE_BASELINE_PATH.read_text(
        encoding="utf-8"
    ).replace("packages/research_harness_mcp/tests", "packages/other_mcp/tests")

    errors = module.validate_critical_path_coverage(
        coverage_text=module.COVERAGE_PATH.read_text(encoding="utf-8"),
        codex_check_text=module.CODEX_CHECK_PATH.read_text(encoding="utf-8"),
        coverage_baseline_text=coverage_baseline_text,
        root=module.ROOT,
    )

    assert any(
        "focused tests not included in coverage command" in error for error in errors
    )
