from pathlib import Path


PRIVATE_REPORT_MARKER = ".research-harness" + "/reports"
TEST_ROOTS = (
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[2] / "research_harness_mcp/tests",
)


def test_public_tests_do_not_reference_private_report_roots():
    violations: list[str] = []
    for root in TEST_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("test_*.py")):
            text = path.read_text(encoding="utf-8")
            if PRIVATE_REPORT_MARKER in text:
                violations.append(str(path.relative_to(root.parents[1])))

    assert violations == []


def test_release_artifact_smoke_script_exists_and_checks_install_state():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "release-artifact-smoke.sh"
    text = script.read_text(encoding="utf-8")

    assert "-m build" in text
    assert "pip install" in text
    assert "Database(" in text
    assert ".migrate()" in text
    # The CLI smoke must exercise the entry point installed into the fresh
    # artifact venv, not whatever ``rh`` happens to be on PATH.
    assert '"$VENV_DIR/bin/rh" --help' in text
    assert "research_harness_mcp" in text


def test_ci_and_release_workflows_run_release_artifact_smoke():
    repo_root = Path(__file__).resolve().parents[3]
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (repo_root / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "scripts/release-artifact-smoke.sh" in ci
    assert "scripts/release-artifact-smoke.sh" in release
    assert ci.index("scripts/codex-check.sh --full") < ci.index(
        "scripts/release-artifact-smoke.sh"
    )
    assert release.index("scripts/release-artifact-smoke.sh") < release.index(
        "gh release create"
    )
