from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from research_harness.cli import main
from research_harness.eval.researchflowbench import (
    TaskPackBuildError,
    build_postsearch_pilot5_task_pack,
    build_synthetic_pilot20_task_pack,
    run_postsearch_pilot5_baseline,
    run_postsearch_pilot5_predictions,
    run_postsearch_pilot5_primitive,
    run_pilot20_baseline,
    run_schema_dry_run,
    synthetic_pilot20_pack_spec,
    validate_pilot20_task_pack,
)
from research_harness.storage.db import Database

PILOT20_FIXTURE_ROOT = (
    Path(__file__).resolve().parent
    / "fixtures/researchflowbench/pilot20_v0_synthetic_task_pack"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }


def test_builder_generates_valid_pilot20_pack_and_schema_dry_run(tmp_path: Path):
    root = tmp_path / "pilot20"

    result = build_synthetic_pilot20_task_pack(root)

    assert result.root == root
    assert result.task_count == 20
    assert result.validation_report.is_valid, result.validation_report.to_dict()

    manifest = _load_json(root / "pilot20_manifest_draft.json")
    assert manifest["pack_id"] == "researchflowbench.synthetic_public_pilot20_v0"
    assert manifest["synthetic"] is True
    assert manifest["model_execution_performed"] is False
    assert [task["task_no"] for task in manifest["tasks"]] == [
        "T01",
        "T02",
        "T03",
        "T04",
        "T05",
        "T06",
        "T07",
        "T08",
        "T09",
        "T10",
        "T11",
        "T12",
        "T13",
        "T14",
        "T15",
        "T16",
        "T17",
        "T18",
        "T19",
        "T20",
    ]
    assert "citation.candidate_generation" in manifest["expected_rh_axes"]
    assert "retrieval.provenance_coverage" in manifest["expected_rh_axes"]

    validation = validate_pilot20_task_pack(root)
    assert validation.is_valid, validation.to_dict()

    dry_run = run_schema_dry_run(root, tmp_path / "dry_run")
    assert dry_run["dry_run_pass"], dry_run
    assert dry_run["task_count"] == 20


def test_builder_regenerates_checked_in_public_fixture(tmp_path: Path):
    root = tmp_path / "pilot20"

    build_synthetic_pilot20_task_pack(root)

    expected_files = _relative_files(PILOT20_FIXTURE_ROOT)
    actual_files = _relative_files(root)
    assert actual_files == expected_files
    for rel_path in expected_files:
        assert (root / rel_path).read_bytes() == (
            PILOT20_FIXTURE_ROOT / rel_path
        ).read_bytes(), rel_path


def test_builder_recomputes_manifest_and_visible_hashes(tmp_path: Path):
    root = tmp_path / "pilot20"

    build_synthetic_pilot20_task_pack(root)

    task_dir = root / "tasks/T01_full_context_citation_eval"
    visible_manifest = _load_json(
        task_dir / "tool_fixtures/visible_input_manifest.json"
    )
    assert visible_manifest["file_hashes_sha256"] == {
        "input_bundle.json": _sha256(task_dir / "input_bundle.json"),
        "prompt.md": _sha256(task_dir / "prompt.md"),
        "tool_fixtures/local_static_corpus.jsonl": _sha256(
            task_dir / "tool_fixtures/local_static_corpus.jsonl"
        ),
    }

    manifest = _load_json(root / "pilot20_manifest_draft.json")
    inventory = set(manifest["file_inventory"])
    assert "pilot20_manifest_draft.json" not in inventory
    assert (
        "tasks/T01_full_context_citation_eval/tool_fixtures/visible_input_manifest.json"
        in inventory
    )
    for rel_path, expected_hash in manifest["file_hashes_sha256"].items():
        assert expected_hash == _sha256(root / rel_path)


def test_builder_rejects_hidden_canary_in_visible_prompt(tmp_path: Path):
    spec = synthetic_pilot20_pack_spec()
    leaky_task = dataclasses.replace(
        spec.tasks[0],
        prompt=spec.tasks[0].prompt + "\nSYNTHETIC_HIDDEN_CANARY_T01\n",
    )
    leaky_spec = dataclasses.replace(spec, tasks=(leaky_task, *spec.tasks[1:]))

    with pytest.raises(TaskPackBuildError) as exc_info:
        build_synthetic_pilot20_task_pack(tmp_path / "leaky", spec=leaky_spec)

    assert "canary_leaked_into_visible_input" in str(exc_info.value)


def test_builder_refuses_non_empty_output_without_overwrite(tmp_path: Path):
    root = tmp_path / "pilot20"
    root.mkdir()
    (root / "sentinel.txt").write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        build_synthetic_pilot20_task_pack(root)


def test_top_level_build_pilot20_cli_emits_json_and_dry_run(runner, tmp_path: Path):
    root = tmp_path / "pilot20"
    dry_run_root = tmp_path / "dry-run"

    result = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "build-pilot20",
            "--out",
            str(root),
            "--schema-dry-run-output",
            str(dry_run_root),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "researchflowbench.builder_result.v0.1"
    assert payload["task_count"] == 20
    assert payload["validation_pass"] is True
    assert payload["preflight_pass"] is True
    assert payload["leakage_pass"] is True
    assert payload["schema_dry_run"]["dry_run_pass"] is True
    assert (root / "pilot20_manifest_draft.json").exists()
    assert (dry_run_root / "schema_dry_run_summary.json").exists()


def test_top_level_build_pilot20_cli_reports_strict_build_errors(
    monkeypatch, runner, tmp_path: Path
):
    from research_harness.eval.researchflowbench import cli as researchflowbench_cli

    def fail_build(*_args, **_kwargs):
        raise TaskPackBuildError("synthetic strict failure")

    monkeypatch.setattr(
        researchflowbench_cli, "build_synthetic_pilot20_task_pack", fail_build
    )

    result = runner.invoke(
        main,
        [
            "researchflowbench",
            "build-pilot20",
            "--out",
            str(tmp_path / "pilot20"),
        ],
    )

    assert result.exit_code != 0
    assert "synthetic strict failure" in result.output


def test_model_free_baseline_scores_pilot20_fixture_without_model_calls():
    result = run_pilot20_baseline(PILOT20_FIXTURE_ROOT)

    report = result.report
    assert result.validation_report.is_valid, result.validation_report.to_dict()
    assert report["schema_version"] == "researchflowbench_score_report.v0"
    assert report["benchmark_id"] == "researchflowbench.synthetic_public_pilot20_v0"
    assert report["baseline_id"] == "stub_zero"
    assert report["split"] == "draft_dev"
    assert report["model_execution_performed"] is False
    assert report["metadata"]["automatic_mutation_enabled"] is False
    assert report["metrics"]["score_count"] == 20
    assert len(report["scores"]) == 20
    assert all(
        score["metrics"]["model_execution_performed"] is False
        for score in report["scores"]
    )
    assert all(
        score["metrics"]["external_search_used"] is False for score in report["scores"]
    )
    assert "citation.candidate_generation" in report["rh_axis_ids"]


def test_researchflowbench_run_baseline_cli_writes_score_report(runner, tmp_path: Path):
    score_file = tmp_path / "score-report.json"

    result = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "run-baseline",
            "--task-pack",
            str(PILOT20_FIXTURE_ROOT),
            "--out",
            str(score_file),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "researchflowbench.baseline_run_result.v0.1"
    assert payload["score_count"] == 20
    assert payload["validation_pass"] is True
    assert payload["model_execution_performed"] is False
    report = _load_json(score_file)
    assert report["schema_version"] == "researchflowbench_score_report.v0"
    assert report["scores"][0]["task_id"].startswith("rfb.synthetic.")


def test_postsearch_pilot5_builder_and_baseline_cover_downstream_axes(tmp_path: Path):
    root = tmp_path / "postsearch-pilot5"

    manifest = build_postsearch_pilot5_task_pack(root, include_gold=True)
    result = run_postsearch_pilot5_baseline(root)

    assert manifest["benchmark_id"] == "researchflowbench.postsearch_pilot5_v0"
    assert manifest["task_count"] == 5
    assert manifest["gold_written"] is True
    assert (root / "tasks/postsearch.P03_evidence_link_support/input.json").exists()

    report = result.report
    assert result.validation_report.is_valid, result.validation_report.to_dict()
    assert report["benchmark_id"] == "researchflowbench.postsearch_pilot5_v0"
    assert report["baseline_id"] == "stub_zero"
    assert report["metrics"]["score_count"] == 5
    assert report["metrics"]["blocked_score_count"] == 0
    assert report["metrics"]["mean_combined_score"] == 0.0
    assert "paper_selection.precision" in report["rh_axis_ids"]
    assert "paper_reading.claim_quality" in report["rh_axis_ids"]
    assert "evidence_linking.support_accuracy" in report["rh_axis_ids"]
    assert "section_drafting.citation_grounding" in report["rh_axis_ids"]
    assert "final_bundle.pdf_quality" in report["rh_axis_ids"]


def test_postsearch_pilot5_cli_builds_and_scores(runner, tmp_path: Path):
    root = tmp_path / "postsearch-pilot5"
    score_file = tmp_path / "postsearch-score.json"

    build = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "build-postsearch-pilot5",
            "--out",
            str(root),
            "--include-gold",
        ],
    )
    assert build.exit_code == 0, build.output
    build_payload = json.loads(build.output)
    assert build_payload["task_count"] == 5
    assert build_payload["gold_written"] is True

    run = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "run-postsearch-baseline",
            "--task-pack",
            str(root),
            "--out",
            str(score_file),
        ],
    )
    assert run.exit_code == 0, run.output
    run_payload = json.loads(run.output)
    assert run_payload["score_count"] == 5
    assert run_payload["blocked_score_count"] == 0
    report = _load_json(score_file)
    assert report["metrics"]["mean_paper_selection_precision"] == 0.0


def test_postsearch_pilot5_final_bundle_quality_primitive_uses_pdf_scan(
    tmp_path: Path,
):
    root = tmp_path / "postsearch-pilot5"
    build_postsearch_pilot5_task_pack(root, include_gold=True)

    result = run_postsearch_pilot5_primitive(
        root, runner_id="final_bundle_quality_scan"
    )

    assert result.validation_report.is_valid, result.validation_report.to_dict()
    report = result.report
    assert report["runner_id"] == "final_bundle_quality_scan"
    assert report["metrics"]["score_count"] == 5
    assert report["metrics"]["blocked_score_count"] == 0
    final_score = next(
        score
        for score in report["scores"]
        if score["task_id"] == "postsearch.P05_final_bundle_quality"
    )
    assert final_score["evidence_state"] == "fixture_or_local_gold"
    assert final_score["metrics"]["final_bundle_check_coverage"] == 1.0
    assert final_score["metrics"]["citation_integrity"] == 0.0
    assert final_score["metrics"]["combined_score"] == 0.5
    assert final_score["runner_output"]["issue_counts"]["blocking"] == 1


def test_postsearch_pilot5_final_bundle_quality_primitive_cli(
    runner,
    tmp_path: Path,
):
    root = tmp_path / "postsearch-pilot5"
    score_file = tmp_path / "postsearch-final-bundle-score.json"
    build_postsearch_pilot5_task_pack(root, include_gold=True)

    result = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "run-postsearch-primitive",
            "--task-pack",
            str(root),
            "--runner",
            "final_bundle_quality_scan",
            "--out",
            str(score_file),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["score_count"] == 5
    assert payload["blocked_score_count"] == 0
    report = _load_json(score_file)
    assert report["metrics"]["mean_final_bundle_check_coverage"] == 0.2


def test_postsearch_pilot5_contract_scan_runner_scores_downstream_tasks(
    tmp_path: Path,
):
    root = tmp_path / "postsearch-pilot5"
    build_postsearch_pilot5_task_pack(root, include_gold=True)

    result = run_postsearch_pilot5_primitive(
        root,
        runner_id="postsearch_contract_scan",
    )

    report = result.report
    assert report["runner_id"] == "postsearch_contract_scan"
    assert report["baseline_kind"] == "deterministic_postsearch_contract_scan"
    assert report["metrics"]["score_count"] == 5
    assert report["metrics"]["blocked_score_count"] == 0
    assert report["metrics"]["skipped_score_count"] == 1
    assert report["metrics"]["supported_score_count"] == 4
    assert report["metrics"]["mean_supported_combined_score"] == 1.0
    assert report["metrics"]["mean_combined_score"] == 0.8

    scored = {
        score["task_id"]: score
        for score in report["scores"]
        if score["evidence_state"] == "fixture_contract_scan"
    }
    assert set(scored) == {
        "postsearch.P01_paper_selection_precision",
        "postsearch.P02_claim_extraction_quality",
        "postsearch.P03_evidence_link_support",
        "postsearch.P04_section_draft_grounding",
    }
    assert all(score["metrics"]["combined_score"] == 1.0 for score in scored.values())
    assert (
        scored["postsearch.P03_evidence_link_support"]["metrics"][
            "typed_contract_coverage"
        ]
        == 1.0
    )
    assert (
        scored["postsearch.P03_evidence_link_support"]["metrics"][
            "citation_governance_replay_coverage"
        ]
        == 1.0
    )
    assert (
        scored["postsearch.P02_claim_extraction_quality"]["runner_output"][
            "contract_scan_kind"
        ]
        == "deterministic_visible_contract"
    )

    final_score = next(
        score
        for score in report["scores"]
        if score["task_id"] == "postsearch.P05_final_bundle_quality"
    )
    assert final_score["evidence_state"] == "skipped_runner_scope"
    assert final_score["skip_reasons"] == [
        "contract_scan_not_supported_for_task_type:final_bundle"
    ]


def test_postsearch_pilot5_contract_scan_runner_cli(
    runner,
    tmp_path: Path,
):
    root = tmp_path / "postsearch-pilot5"
    score_file = tmp_path / "postsearch-contract-score.json"
    build_postsearch_pilot5_task_pack(root, include_gold=True)

    result = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "run-postsearch-primitive",
            "--task-pack",
            str(root),
            "--runner",
            "postsearch_contract_scan",
            "--out",
            str(score_file),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["runner_id"] == "postsearch_contract_scan"
    assert payload["score_count"] == 5
    assert payload["blocked_score_count"] == 0
    assert payload["skipped_score_count"] == 1
    assert payload["supported_score_count"] == 4
    report = _load_json(score_file)
    assert report["baseline_kind"] == "deterministic_postsearch_contract_scan"


def test_postsearch_pilot5_evidence_link_record_replay_uses_real_primitive(
    tmp_path: Path,
):
    root = tmp_path / "postsearch-pilot5"
    build_postsearch_pilot5_task_pack(root, include_gold=True)

    result = run_postsearch_pilot5_primitive(
        root,
        runner_id="evidence_link_record_replay",
    )

    report = result.report
    assert report["runner_id"] == "evidence_link_record_replay"
    assert report["baseline_kind"] == "real_rh_evidence_link_record_replay"
    assert report["metrics"]["score_count"] == 5
    assert report["metrics"]["blocked_score_count"] == 0
    assert report["metrics"]["skipped_score_count"] == 4
    assert report["metrics"]["supported_score_count"] == 1
    assert report["metrics"]["mean_supported_combined_score"] == 1.0
    assert report["metrics"]["mean_combined_score"] == 0.2

    evidence_score = next(
        score
        for score in report["scores"]
        if score["task_id"] == "postsearch.P03_evidence_link_support"
    )
    assert evidence_score["evidence_state"] == "fixture_real_primitive_replay"
    assert evidence_score["metrics"]["support_label_accuracy"] == 1.0
    assert evidence_score["metrics"]["evidence_span_exact_match"] == 1.0
    assert evidence_score["metrics"]["typed_contract_coverage"] == 1.0
    assert evidence_score["metrics"]["citation_governance_replay_coverage"] == 1.0
    assert evidence_score["runner_output"]["primitive"] == "evidence_link"
    assert (
        evidence_score["runner_output"]["support_label_source"]
        == "deterministic_visible_span_scan"
    )
    assert evidence_score["runner_output"]["recorded_links"] == [
        {
            "claim_id": "C-E1",
            "source_type": "candidate_span",
            "span_id": "S-1",
            "strength": "partial_support",
            "support_status": "partial",
            "evidence_span": {
                "paper_id": 0,
                "section": "candidate_span",
                "snippet": "The system improves citation accuracy on held-out drafts.",
            },
            "citation_candidate": {
                "paper_id": 0,
                "identifier": "S-1",
                "source_type": "candidate_span",
                "title": "Post-search visible span S-1",
            },
            "citation_verification": {
                "object_type": "citation_verification",
                "target_id": "S-1",
                "status": "partial",
            },
            "notes": "postsearch Pilot-5 replay label=partial_support",
        },
        {
            "claim_id": "C-E1",
            "source_type": "candidate_span",
            "span_id": "S-2",
            "strength": "contradicts",
            "support_status": "contradicts",
            "evidence_span": {
                "paper_id": 0,
                "section": "candidate_span",
                "snippet": "PDF layout quality was not evaluated in this study.",
            },
            "citation_candidate": {
                "paper_id": 0,
                "identifier": "S-2",
                "source_type": "candidate_span",
                "title": "Post-search visible span S-2",
            },
            "citation_verification": {
                "object_type": "citation_verification",
                "target_id": "S-2",
                "status": "contradicts",
            },
            "review_issue": {
                "object_type": "review_issue",
                "target_id": "S-2",
                "category": "unsupported_evidence_link",
                "status": "open",
                "blocking": True,
            },
            "gate_decision": {
                "object_type": "gate_decision",
                "target_id": "S-2",
                "action": "block",
                "reason_codes": ["unsupported_evidence_link"],
            },
            "notes": "postsearch Pilot-5 replay label=contradicts",
        },
    ]
    assert all(
        item["primitive"] == "evidence_link" and item["success"] is True
        for item in evidence_score["runner_output"]["primitive_results"]
    )

    skipped = [
        score
        for score in report["scores"]
        if score["evidence_state"] == "skipped_runner_scope"
    ]
    assert len(skipped) == 4
    assert all(
        reason.startswith("evidence_link_record_replay_not_supported_for_task_type:")
        for score in skipped
        for reason in score["skip_reasons"]
    )


def test_postsearch_pilot5_evidence_link_record_replay_cli(
    runner,
    tmp_path: Path,
):
    root = tmp_path / "postsearch-pilot5"
    score_file = tmp_path / "postsearch-evidence-link-score.json"
    build_postsearch_pilot5_task_pack(root, include_gold=True)

    result = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "run-postsearch-primitive",
            "--task-pack",
            str(root),
            "--runner",
            "evidence_link_record_replay",
            "--out",
            str(score_file),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["runner_id"] == "evidence_link_record_replay"
    assert payload["score_count"] == 5
    assert payload["blocked_score_count"] == 0
    assert payload["skipped_score_count"] == 4
    assert payload["supported_score_count"] == 1
    report = _load_json(score_file)
    assert report["baseline_kind"] == "real_rh_evidence_link_record_replay"


def test_postsearch_pilot5_prediction_file_scores_all_downstream_tasks(
    tmp_path: Path,
):
    root = tmp_path / "postsearch-pilot5"
    prediction_file = tmp_path / "predictions.json"
    build_postsearch_pilot5_task_pack(root, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.postsearch_predictions.v0.1",
                "runner_id": "candidate_model_replay",
                "model_execution_performed": True,
                "predictions": [
                    {
                        "task_id": "postsearch.P01_paper_selection_precision",
                        "prediction": {"selected_paper_ids": ["P-A", "P-C"]},
                    },
                    {
                        "task_id": "postsearch.P02_claim_extraction_quality",
                        "prediction": {
                            "claims": [
                                {
                                    "paper_id": "P-D",
                                    "claim_text": (
                                        "Span-level evidence gates improve factual "
                                        "consistency for draft claims."
                                    ),
                                    "scope": "draft claims with exact supporting spans",
                                }
                            ]
                        },
                    },
                    {
                        "task_id": "postsearch.P03_evidence_link_support",
                        "prediction": {
                            "evidence_links": [
                                {
                                    "span_id": "S-1",
                                    "support_label": "partial_support",
                                    "support_status": "partial",
                                    "evidence_span": {
                                        "paper_id": 0,
                                        "section": "candidate_span",
                                        "snippet": (
                                            "The system improves citation accuracy "
                                            "on held-out drafts."
                                        ),
                                    },
                                    "citation_candidate": {
                                        "paper_id": 0,
                                        "identifier": "S-1",
                                        "source_type": "candidate_span",
                                        "title": "Post-search visible span S-1",
                                    },
                                },
                                {
                                    "span_id": "S-2",
                                    "support_label": "contradicts",
                                    "support_status": "contradicts",
                                    "evidence_span": {
                                        "paper_id": 0,
                                        "section": "candidate_span",
                                        "snippet": (
                                            "PDF layout quality was not evaluated "
                                            "in this study."
                                        ),
                                    },
                                    "citation_candidate": {
                                        "paper_id": 0,
                                        "identifier": "S-2",
                                        "source_type": "candidate_span",
                                        "title": "Post-search visible span S-2",
                                    },
                                    "citation_verification": {
                                        "object_type": "citation_verification",
                                        "target_id": "S-2",
                                        "status": "contradicts",
                                    },
                                    "review_issue": {
                                        "object_type": "review_issue",
                                        "target_id": "S-2",
                                        "category": "unsupported_evidence_link",
                                        "status": "open",
                                        "blocking": True,
                                    },
                                    "gate_decision": {
                                        "object_type": "gate_decision",
                                        "target_id": "S-2",
                                        "action": "block",
                                        "reason_codes": ["unsupported_evidence_link"],
                                    },
                                },
                            ]
                        },
                    },
                    {
                        "task_id": "postsearch.P04_section_draft_grounding",
                        "prediction": {
                            "draft": (
                                "Evidence maps preserve span-level provenance [P-F]. "
                                "Citation sanitization detects hallucinated identifiers [P-G]."
                            ),
                            "citations": ["P-F", "P-G"],
                        },
                    },
                    {
                        "task_id": "postsearch.P05_final_bundle_quality",
                        "prediction": {
                            "bundle_checks": [
                                "pdf_exists",
                                "latex_compiled",
                                "citation_warnings",
                                "figure_warnings",
                            ]
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_postsearch_pilot5_predictions(root, prediction_file)

    report = result.report
    assert report["baseline_id"] == "candidate_model_replay"
    assert report["baseline_kind"] == "postsearch_prediction_file"
    assert report["model_execution_performed"] is True
    assert report["metrics"]["score_count"] == 5
    assert report["metrics"]["blocked_score_count"] == 0
    assert report["metrics"]["supported_score_count"] == 5
    assert report["metrics"]["mean_combined_score"] == 1.0
    evidence_score = next(
        score
        for score in report["scores"]
        if score["task_id"] == "postsearch.P03_evidence_link_support"
    )
    assert evidence_score["metrics"]["citation_governance_replay_coverage"] == 1.0
    assert all(
        score["evidence_state"] == "prediction_file_scored"
        for score in report["scores"]
    )


def test_postsearch_pilot5_prediction_file_cli(
    runner,
    tmp_path: Path,
):
    root = tmp_path / "postsearch-pilot5"
    prediction_file = tmp_path / "predictions.json"
    score_file = tmp_path / "postsearch-prediction-score.json"
    build_postsearch_pilot5_task_pack(root, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.postsearch_predictions.v0.1",
                "runner_id": "candidate_model_replay",
                "model_execution_performed": False,
                "predictions": [
                    {
                        "task_id": "postsearch.P01_paper_selection_precision",
                        "prediction": {"selected_paper_ids": ["P-A", "P-C"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "score-postsearch-predictions",
            "--task-pack",
            str(root),
            "--predictions",
            str(prediction_file),
            "--out",
            str(score_file),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["baseline_id"] == "candidate_model_replay"
    assert payload["score_count"] == 5
    assert payload["blocked_score_count"] == 4
    assert payload["supported_score_count"] == 1
    report = _load_json(score_file)
    assert report["scores"][0]["evidence_state"] == "prediction_file_scored"
    assert report["scores"][1]["evidence_state"] == "blocked_missing_prediction"


def test_postsearch_pilot5_prediction_file_rejects_duplicate_task_ids(
    tmp_path: Path,
):
    root = tmp_path / "postsearch-pilot5"
    prediction_file = tmp_path / "predictions.json"
    build_postsearch_pilot5_task_pack(root, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.postsearch_predictions.v0.1",
                "runner_id": "candidate_model_replay",
                "predictions": [
                    {
                        "task_id": "postsearch.P01_paper_selection_precision",
                        "prediction": {"selected_paper_ids": ["P-A"]},
                    },
                    {
                        "task_id": "postsearch.P01_paper_selection_precision",
                        "prediction": {"selected_paper_ids": ["P-C"]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate post-search prediction task_id"):
        run_postsearch_pilot5_predictions(root, prediction_file)


def test_postsearch_pilot5_prediction_file_blocks_invalid_prediction_payload(
    tmp_path: Path,
):
    root = tmp_path / "postsearch-pilot5"
    prediction_file = tmp_path / "predictions.json"
    build_postsearch_pilot5_task_pack(root, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.postsearch_predictions.v0.1",
                "runner_id": "candidate_model_replay",
                "model_execution_performed": "false",
                "predictions": [
                    {
                        "task_id": "postsearch.P01_paper_selection_precision",
                        "prediction": ["P-A", "P-C"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_postsearch_pilot5_predictions(root, prediction_file)

    report = result.report
    assert report["model_execution_performed"] is False
    assert report["metrics"]["blocked_score_count"] == 5
    invalid_score = report["scores"][0]
    assert invalid_score["evidence_state"] == "blocked_invalid_prediction"
    assert invalid_score["blockers"] == ["postsearch_prediction_payload_invalid"]
    assert report["scores"][1]["evidence_state"] == "blocked_missing_prediction"


def test_postsearch_pilot5_publication_pack_backfill_runner_generates_and_scans(
    tmp_path: Path,
    monkeypatch,
):
    from research_harness.primitives import writing_impls
    from research_harness.primitives.types import PaperFinalizeOutput

    root = tmp_path / "postsearch-pilot5"
    build_postsearch_pilot5_task_pack(root, include_gold=True)
    generated_pdf = tmp_path / "generated.pdf"
    generated_pdf.write_bytes(b"%PDF-1.4\n% generated\n")

    def fake_finalize(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        tex_path = output_dir / "paper.tex"
        log_path = output_dir / "paper.log"
        tex_path.write_text(
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "Generated citation \\citep{PZ}.\n"
            "\\end{document}\n",
            encoding="utf-8",
        )
        log_path.write_text("", encoding="utf-8")
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(tex_path),
            pdf_path=str(generated_pdf),
            pages=1,
            word_count=5,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: tmp_path / f"topic-{topic_id}",
    )

    result = run_postsearch_pilot5_primitive(
        root,
        runner_id="publication_pack_backfill_scan",
    )

    report = result.report
    assert report["runner_id"] == "publication_pack_backfill_scan"
    final_score = next(
        score
        for score in report["scores"]
        if score["task_id"] == "postsearch.P05_final_bundle_quality"
    )
    assert final_score["metrics"]["final_bundle_check_coverage"] == 1.0
    assert final_score["metrics"]["citation_integrity"] == 1.0
    assert final_score["metrics"]["combined_score"] == 1.0
    assert (
        final_score["runner_output"]["generated_final_bundle"]["status"]
        == "ready_interim"
    )
    assert final_score["runner_output"]["issue_counts"]["blocking"] == 0


def test_researchflowbench_baseline_score_file_records_and_archives(
    runner,
    tmp_path: Path,
    monkeypatch,
):
    db_path = tmp_path / "rfb-baseline.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    create = runner.invoke(main, ["topic", "init", "rfb-baseline"])
    assert create.exit_code == 0, create.output

    db = Database(db_path)
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, ?, ?)",
            ("rfb-baseline", "RFB baseline CLI test"),
        )
        conn.commit()
    finally:
        conn.close()

    score_file = tmp_path / "score-report.json"
    run = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "run-baseline",
            "--task-pack",
            str(PILOT20_FIXTURE_ROOT),
            "--out",
            str(score_file),
        ],
    )
    assert run.exit_code == 0, run.output
    run_payload = json.loads(run.output)
    assert run_payload["recorded_artifact_id"] is None

    record = runner.invoke(
        main,
        [
            "--json",
            "self-evolution",
            "record-rfb-score-report",
            "--topic",
            "rfb-baseline",
            "--score-file",
            str(score_file),
        ],
    )
    assert record.exit_code == 0, record.output
    record_payload = json.loads(record.output)
    assert record_payload["artifact_type"] == "researchflowbench_score_report"
    assert record_payload["score_count"] == 20

    archive = runner.invoke(
        main,
        [
            "--json",
            "self-evolution",
            "archive-from-artifacts",
            "--topic",
            "rfb-baseline",
        ],
    )
    assert archive.exit_code == 0, archive.output
    archive_payload = json.loads(archive.output)
    assert archive_payload["record_count"] == 20
    assert archive_payload["mutation_performed"] is False
