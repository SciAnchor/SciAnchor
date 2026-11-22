from __future__ import annotations

import json
import shutil
from pathlib import Path

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.eval.researchflowbench import (
    QUALITY_COMMANDS,
    run_release_readiness_checks,
)


PILOT20_ROOT = (
    Path(__file__).resolve().parent
    / "fixtures/researchflowbench/pilot20_v0_synthetic_task_pack"
)
DOCS_PATH = Path(__file__).resolve().parents[3] / "docs/researchflowbench.md"


def _copy_pack(tmp_path: Path) -> Path:
    target = tmp_path / "researchflowbench_pilot20_v0"
    shutil.copytree(PILOT20_ROOT, target)
    return target


def _check(report, name: str) -> dict:
    checks = {check.name: check for check in report.checks}
    return checks[name].to_dict()


def test_release_readiness_passes_for_public_pilot20_fixture(tmp_path: Path):
    report = run_release_readiness_checks(
        PILOT20_ROOT,
        docs_path=DOCS_PATH,
        schema_dry_run_output=tmp_path / "dry-run",
        reproducibility_output=tmp_path / "rebuilt",
    )

    assert report.status == "pass", report.to_dict()
    assert report.mutation_performed is False
    assert report.automatic_release_label_change is False
    assert _check(report, "no_private_data")["passed"] is True
    assert _check(report, "no_hidden_gold_leakage")["passed"] is True
    assert _check(report, "schema_dry_run_pass")["passed"] is True
    assert _check(report, "reproducible_build")["passed"] is True
    assert _check(report, "docs_updated")["passed"] is True
    assert _check(report, "ruff_and_tests_commanded")["passed"] is True
    assert report.quality_commands == QUALITY_COMMANDS


def test_researchflowbench_docs_keep_private_regression_boundary():
    text = DOCS_PATH.read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())

    for required in (
        "ResearchFlowBench is RH-owned runtime and regression evidence",
        "Private/local benchmark and performance runs are regression governance only.",
        "They do not authorize public benchmark, leaderboard, ranking, release-grade, or public performance claims.",
        "If a benchmark artifact is intended for public cross-library ranking, publish it through ARE.",
    ):
        assert required in normalized_text


def test_release_readiness_blocks_private_path_markers(tmp_path: Path):
    root = _copy_pack(tmp_path)
    prompt = root / "tasks/T01_full_context_citation_eval/prompt.md"
    prompt.write_text(
        prompt.read_text(encoding="utf-8")
        + "\nPrivate fixture path: /Users/example/.research-harness/downloads/a.pdf\n",
        encoding="utf-8",
    )

    report = run_release_readiness_checks(root, docs_path=DOCS_PATH)

    assert report.status == "fail"
    private_check = _check(report, "no_private_data")
    assert private_check["passed"] is False
    assert private_check["details"]["private_marker_findings"]


def test_release_readiness_blocks_hidden_canary_in_visible_input(tmp_path: Path):
    root = _copy_pack(tmp_path)
    prompt = root / "tasks/T01_full_context_citation_eval/prompt.md"
    prompt.write_text(
        prompt.read_text(encoding="utf-8") + "\nSYNTHETIC_HIDDEN_CANARY_T01\n",
        encoding="utf-8",
    )

    report = run_release_readiness_checks(root, docs_path=DOCS_PATH)

    assert report.status == "fail"
    leakage_check = _check(report, "no_hidden_gold_leakage")
    assert leakage_check["passed"] is False
    assert leakage_check["details"]["failed_tasks"][0]["failures"] == [
        "canary_leaked_into_visible_input"
    ]


def test_release_check_cli_emits_json_report(tmp_path: Path):
    report_file = tmp_path / "release-readiness.json"
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "release-check",
            "--task-pack",
            str(PILOT20_ROOT),
            "--docs-path",
            str(DOCS_PATH),
            "--schema-dry-run-output",
            str(tmp_path / "dry-run"),
            "--rebuild-output",
            str(tmp_path / "rebuilt"),
            "--out",
            str(report_file),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "researchflowbench.release_readiness.v0.1"
    assert payload["status"] == "pass"
    assert payload["report_file"] == str(report_file)
    assert report_file.exists()
