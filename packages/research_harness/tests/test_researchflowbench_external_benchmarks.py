from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from research_harness.cli import main
from research_harness.eval.researchflowbench import (
    AutoResearchBenchAdapter,
    ExternalBenchmarkAdapter,
    LitSearchAdapter,
    attribute_score_report_failures,
    build_autoresearchbench_candidate_source,
    check_local_benchmark_data,
    compare_score_reports,
    export_external_benchmark_registry,
    local_benchmark_data_check_payload,
    list_local_benchmark_data,
    local_benchmark_data_registry_payload,
    list_external_benchmarks,
    metric_map_payload,
    metric_mappings_for_benchmark,
    recommended_external_benchmarks,
    run_external_task_pack_agent,
    run_external_task_pack_baseline,
    run_external_task_pack_predictions,
    run_external_task_pack_primitive,
    validate_external_task_pack,
    write_score_report,
)
from research_harness.eval.researchflowbench.cli import researchflowbench_group
from research_harness.eval.researchflowbench.primitive_runner import (
    _codex_prediction_schema,
    build_autoresearchbench_agent_prompt,
    prepare_autoresearchbench_agent_workspace,
)


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "scripts" / "diagnose_autoresearchbench_candidate_coverage.py").exists()
)


def load_autoresearchbench_candidate_coverage_script():
    script_path = (
        REPO_ROOT / "scripts" / "diagnose_autoresearchbench_candidate_coverage.py"
    )
    spec = importlib.util.spec_from_file_location("arb_candidate_coverage", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_autoresearchbench_candidate_rerank_script():
    script_path = (
        REPO_ROOT / "scripts" / "diagnose_autoresearchbench_candidate_rerank.py"
    )
    spec = importlib.util.spec_from_file_location("arb_candidate_rerank", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_autoresearchbench_agent_smoke_script():
    script_path = REPO_ROOT / "scripts" / "run_autoresearchbench_rh_agent_smoke.py"
    spec = importlib.util.spec_from_file_location("arb_agent_smoke", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_autoresearchbench_candidate_source_fixture(
    candidate_dir: Path,
    records: list[dict[str, object]],
) -> None:
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            }
        ),
        encoding="utf-8",
    )
    (candidate_dir / "candidate_corpus.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def write_codex_exec_stub(
    codex_bin: Path,
    *,
    last_message: dict[str, object],
) -> None:
    codex_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import sys",
                "",
                "output_file = sys.argv[sys.argv.index('--output-last-message') + 1]",
                f"payload = {json.dumps(last_message, sort_keys=True)!r}",
                "with open(output_file, 'w', encoding='utf-8') as handle:",
                "    json.dump(json.loads(payload), handle)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    codex_bin.chmod(0o755)


def write_hanging_codex_exec_stub(codex_bin: Path, *, child_pid_file: Path) -> None:
    codex_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import subprocess",
                "import sys",
                "import time",
                "",
                f"child_pid_file = {str(child_pid_file)!r}",
                "child = subprocess.Popen(",
                "    [sys.executable, '-c', 'import time; time.sleep(60)']",
                ")",
                "with open(child_pid_file, 'w', encoding='utf-8') as handle:",
                "    handle.write(str(child.pid))",
                "try:",
                "    time.sleep(60)",
                "finally:",
                "    child.poll()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    codex_bin.chmod(0o755)


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_process(pid: int) -> None:
    if not process_exists(pid):
        return
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not process_exists(pid):
            return
        time.sleep(0.05)
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        return


def wait_for_pid_file(pid_file: Path) -> int:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if pid_file.exists():
            return int(pid_file.read_text(encoding="utf-8"))
        time.sleep(0.05)
    raise AssertionError(f"pid file was not written: {pid_file}")


def test_external_benchmark_registry_prioritizes_public_impact_candidates():
    p0_ids = {spec.benchmark_id for spec in recommended_external_benchmarks("P0")}

    assert {"autoresearchbench", "litsearch"}.issubset(p0_ids)

    specs = {spec.benchmark_id: spec for spec in list_external_benchmarks()}
    assert specs["autoresearchbench"].public_metrics == ("deep_accuracy", "wide_iou")
    assert "literature_discovery" in specs["autoresearchbench"].rh_axes
    assert specs["autoresearchbench"].adapter_status == "adapter_available"
    assert specs["litsearch"].license_key == "mit"
    assert "retrieval_quality" in specs["litsearch"].rh_axes
    assert specs["litsearch"].to_dict()["metric_mappings"][0]["adapter_contract"]


def test_license_limited_benchmarks_are_not_marked_publication_ready():
    specs = {spec.benchmark_id: spec for spec in list_external_benchmarks()}

    assert specs["airs_bench"].license_key == "cc-by-nc-4.0"
    assert not specs["airs_bench"].publication_ready
    assert "license_review_required" in specs["airs_bench"].limitations

    assert specs["researcherbench"].license_key == "noassertion"
    assert not specs["researcherbench"].publication_ready


def test_planned_benchmarks_extend_longer_research_flow_coverage():
    specs = {spec.benchmark_id: spec for spec in list_external_benchmarks()}

    assert specs["sage_literature_retrieval"].adapter_status == "adapter_planned"
    assert "deep_research" in specs["sage_literature_retrieval"].rh_axes
    assert "retrieval_scaling" in specs["sage_literature_retrieval"].public_metrics

    assert specs["paperarena"].adapter_status == "adapter_planned"
    assert "evidence_synthesis" in specs["paperarena"].rh_axes
    assert "license_review_required" in specs["paperarena"].limitations

    assert specs["deepresearch_bench"].priority == "P2"
    assert "citation_faithfulness" in specs["deepresearch_bench"].rh_axes
    assert specs["deepresearch_bench_ii"].adapter_status == (
        "leaderboard_harness_planned"
    )

    assert specs["mlr_bench"].priority == "P3"
    assert "paper_writing" in specs["mlr_bench"].rh_axes
    assert specs["airs_bench"].priority == "P3"


def test_external_benchmark_export_writes_json_and_markdown(tmp_path: Path):
    result = export_external_benchmark_registry(tmp_path)

    registry = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert registry["schema_version"] == "researchflowbench.external_benchmarks.v0.1"
    assert registry["benchmark_count"] >= 6
    assert registry["recommended_p0_ids"] == ["autoresearchbench", "litsearch"]
    assert (
        registry["metric_map"]["schema_version"] == "researchflowbench.metric_map.v0.1"
    )
    assert registry["local_data_registry"]["schema_version"] == (
        "researchflowbench.local_benchmark_data.v0.1"
    )

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "AutoResearchBench" in markdown
    assert "Deep Accuracy" in markdown
    assert "paper_search.recall" in markdown
    assert "https://github.com/CherYou/AutoResearchBench" in markdown
    assert "do not vendor released benchmark data into RH" in markdown
    assert "${RESEARCH_HARNESS_BENCHMARK_DATA}/litsearch" in markdown


def test_local_benchmark_data_registry_tracks_p0_adapter_data_contracts():
    registry = local_benchmark_data_registry_payload()
    specs = {spec.benchmark_id: spec for spec in list_local_benchmark_data()}

    assert registry["schema_version"] == "researchflowbench.local_benchmark_data.v0.1"
    assert registry["policy"]["third_party_data_vendored"] is False
    assert set(specs) == {"autoresearchbench", "litsearch"}

    litsearch = specs["litsearch"]
    assert litsearch.official_source_url == (
        "https://huggingface.co/datasets/princeton-nlp/LitSearch"
    )
    assert (
        litsearch.expected_local_path == "${RESEARCH_HARNESS_BENCHMARK_DATA}/litsearch"
    )
    assert litsearch.license_key == "mit"
    assert litsearch.adapter_id == "researchflowbench.adapters.litsearch.v0.1"
    assert litsearch.supported_metrics == ("retrieval_recall", "rerank_quality")
    assert litsearch.gold_label_policy == "local_only"
    assert "query/queries.jsonl" in litsearch.required_local_files

    autoresearchbench = specs["autoresearchbench"]
    assert autoresearchbench.license_key == "apache-2.0"
    assert autoresearchbench.adapter_id == (
        "researchflowbench.adapters.autoresearchbench.v0.1"
    )
    assert autoresearchbench.supported_metrics == ("deep_accuracy", "wide_iou")
    assert autoresearchbench.gold_label_policy == "local_only"
    assert "AutoResearchBench.jsonl" in autoresearchbench.expected_local_path


def test_metric_map_links_external_metrics_to_rh_axes():
    payload = metric_map_payload()
    axis_ids = {axis["axis_id"] for axis in payload["rh_axes"]}

    assert "paper_search.recall" in axis_ids
    assert "retrieval.provenance_coverage" in axis_ids
    assert "paper_selection.precision" in axis_ids
    assert "paper_reading.claim_quality" in axis_ids
    assert "evidence_linking.support_accuracy" in axis_ids
    assert "section_drafting.citation_grounding" in axis_ids
    assert "final_bundle.pdf_quality" in axis_ids

    litsearch_mappings = metric_mappings_for_benchmark("litsearch")
    assert {mapping.public_metric for mapping in litsearch_mappings} == {
        "retrieval_recall",
        "rerank_quality",
    }
    assert litsearch_mappings[0].adapter_contract == (
        "researchflowbench.adapters.litsearch.v0.1"
    )
    autoresearchbench_mappings = metric_mappings_for_benchmark("autoresearchbench")
    assert {mapping.public_metric for mapping in autoresearchbench_mappings} == {
        "deep_accuracy",
        "wide_iou",
    }
    assert autoresearchbench_mappings[0].adapter_contract == (
        "researchflowbench.adapters.autoresearchbench.v0.1"
    )


def test_litsearch_adapter_builds_tasks_and_scores_retrieval():
    adapter = LitSearchAdapter.from_records(
        [
            {
                "query_id": "q1",
                "query": "papers about dense retrieval for literature search",
                "gold_paper_ids": ["S2-1", "S2-2"],
                "specificity": "high",
            }
        ],
        [
            {
                "paper_id": "S2-1",
                "title": "Dense Scientific Retrieval",
                "abstract": "A retrieval paper.",
                "outgoing_citation_ids": ["S2-0"],
            }
        ],
    )

    assert adapter.query_count == 1
    assert adapter.corpus_count == 1
    task = adapter.tasks()[0]
    assert task.task_id == "litsearch.q1"
    assert task.split == "mutate_dev"
    assert task.metadata["specificity"] == "high"
    assert task.corpus_paper_ids == ("S2-1",)

    score = LitSearchAdapter.score_retrieval(task, ["S2-9", "S2-1"], k=2)
    assert score.hit_at_k
    assert score.recall_at_k == 0.5
    assert score.mrr == 0.5
    assert isinstance(adapter, ExternalBenchmarkAdapter)

    report = LitSearchAdapter.score_report((score,), artifact_refs=("artifact:lit",))
    assert report["schema_version"] == "researchflowbench_score_report.v0"
    assert report["benchmark_id"] == "litsearch"
    assert report["metrics"] == ["retrieval_recall", "rerank_quality"]
    assert report["scores"][0]["split"] == "mutate_dev"
    assert report["scores"][0]["metrics"]["retrieval_recall"] == 0.5
    assert report["artifact_refs"] == ["artifact:lit"]


def test_litsearch_adapter_accepts_official_query_and_corpus_field_names():
    adapter = LitSearchAdapter.from_records(
        [
            {
                "query": "official LitSearch query schema",
                "corpusids": [202719327],
            }
        ],
        [
            {
                "corpusid": 202719327,
                "title": "Official Corpus Schema",
                "citations": [1, 2],
            }
        ],
    )

    task = adapter.tasks()[0]
    assert task.gold_paper_ids == ("202719327",)
    assert task.corpus_paper_ids == ("202719327",)


def test_litsearch_adapter_writes_task_pack_without_gold_by_default(tmp_path: Path):
    adapter = LitSearchAdapter.from_records(
        [
            {
                "id": "q2",
                "question": "which paper introduced a citation-aware retriever?",
                "paper_ids": ["123"],
            }
        ]
    )

    manifest = adapter.write_task_pack(tmp_path)

    assert manifest["adapter_contract"] == "researchflowbench.adapters.litsearch.v0.1"
    assert manifest["gold_written"] is False
    task_path = tmp_path / "tasks" / "litsearch.q2" / "input.json"
    assert task_path.exists()
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    assert payload["benchmark_id"] == "litsearch"
    assert payload["split"] == "mutate_dev"
    assert payload["license"]["dataset_license"] == "mit"
    assert payload["artifact_policy"]["gold_storage_policy"] == "local_only"
    assert payload["archive_linkage"]["rh_axis_ids"] == [
        "paper_search.recall",
        "paper_search.rerank_quality",
        "citation.candidate_generation",
    ]
    assert "gold_paper_ids" not in payload


def test_autoresearchbench_adapter_builds_tasks_and_scores_deep_and_wide():
    adapter = AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "deep-1",
                "question": "Find the paper that introduced Sample Method.",
                "search_type": "deep",
                "answer": ["Sample Method: A Retrieval Paper"],
            },
            {
                "id": "wide-1",
                "question": "Find all papers satisfying a benchmark condition.",
                "search_type": "wide",
                "answer": ["Paper A", "Paper B"],
                "arxiv_id": ["arXiv:2401.12345", "2502.23456"],
            },
        ]
    )

    assert isinstance(adapter, ExternalBenchmarkAdapter)
    assert adapter.task_count == 2
    assert adapter.manifest()["task_type_counts"] == {"deep": 1, "wide": 1}

    deep_task, wide_task = adapter.tasks()
    assert deep_task.task_id == "autoresearchbench.deep-1"
    deep_score = AutoResearchBenchAdapter.score_deep(
        deep_task,
        ["Sample Method A Retrieval Paper"],
    )
    assert deep_score.deep_accuracy == 1.0
    assert deep_score.matched_titles == ("Sample Method A Retrieval Paper",)

    wide_score = AutoResearchBenchAdapter.score_wide(
        wide_task,
        ["2401.12345", "2603.00001"],
    )
    assert wide_score.wide_iou == 0.333333
    assert wide_score.wide_recall == 0.5
    assert wide_score.wide_precision == 0.5
    assert wide_score.matched_arxiv_ids == ("2401.12345",)


def test_autoresearchbench_adapter_writes_task_pack_without_gold_by_default(
    tmp_path: Path,
):
    adapter = AutoResearchBenchAdapter.from_records(
        [
            {
                "question_id": "q4",
                "input_data": {
                    "question": "Which paper matches this multi-hop clue?",
                    "answer": ["A Hidden Title"],
                },
            }
        ]
    )

    manifest = adapter.write_task_pack(tmp_path)

    assert manifest["adapter_contract"] == (
        "researchflowbench.adapters.autoresearchbench.v0.1"
    )
    assert manifest["license"]["dataset_license"] == "apache-2.0"
    assert manifest["gold_storage_policy"] == "local_only"
    assert manifest["gold_written"] is False
    task_path = tmp_path / "tasks" / "autoresearchbench.q4" / "input.json"
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    assert payload["benchmark_id"] == "autoresearchbench"
    assert payload["task_type"] == "deep"
    assert payload["split"] == "mutate_dev"
    assert payload["license"]["dataset_license"] == "apache-2.0"
    assert payload["archive_linkage"]["rh_axis_ids"] == [
        "deep_research.discovery_accuracy",
        "literature.set_completion",
        "retrieval.provenance_coverage",
    ]
    assert "answer_titles" not in payload


def test_autoresearchbench_external_pack_validation_rejects_visible_gold_fields(
    tmp_path: Path,
):
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "visible-leak",
                "question": "visible clue",
                "search_type": "deep",
                "answer": ["Visible Leak Target"],
            }
        ]
    ).write_task_pack(tmp_path, include_gold=False)
    input_path = tmp_path / "tasks" / "autoresearchbench.visible-leak" / "input.json"
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["input"] = payload["input"] | {"answer_titles": ["Visible Leak Target"]}
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    report = validate_external_task_pack(tmp_path)

    assert not report.is_valid
    assert any(
        issue.code == "external_task_visible_gold_field" for issue in report.issues
    )


def test_autoresearchbench_adapter_score_report_uses_contract_shape():
    score = AutoResearchBenchAdapter.score_wide(
        AutoResearchBenchAdapter.from_records(
            [
                {
                    "id": "wide-score",
                    "question": "Find all matching papers.",
                    "search_type": "wide",
                    "arxiv_id": ["2401.12345"],
                }
            ]
        ).tasks()[0],
        ["2401.12345"],
    )

    report = AutoResearchBenchAdapter.score_report(
        (score,),
        artifact_refs=("artifact:arb",),
    )

    assert report["schema_version"] == "researchflowbench_score_report.v0"
    assert report["benchmark_id"] == "autoresearchbench"
    assert report["metrics"] == ["deep_accuracy", "wide_iou"]
    assert report["scores"][0]["metrics"]["wide_iou"] == 1.0
    assert report["scores"][0]["rh_axis_ids"] == [
        "deep_research.discovery_accuracy",
        "literature.set_completion",
        "retrieval.provenance_coverage",
    ]


def test_external_benchmarks_cli_emits_machine_readable_registry(tmp_path: Path):
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        ["external-benchmarks", "--json", "--out", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["benchmark_count"] >= 6
    assert payload["metric_map"]["external_metric_mappings"]
    assert (tmp_path / "external_benchmarks.json").exists()
    assert (tmp_path / "external_benchmarks.md").exists()


def test_local_data_registry_cli_emits_machine_readable_registry():
    runner = CliRunner()

    result = runner.invoke(researchflowbench_group, ["local-data-registry", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "researchflowbench.local_benchmark_data.v0.1"
    assert payload["benchmark_count"] == 2
    assert {record["benchmark_id"] for record in payload["benchmarks"]} == {
        "autoresearchbench",
        "litsearch",
    }


def test_local_data_check_reports_missing_litsearch_files(tmp_path: Path):
    checks = check_local_benchmark_data("litsearch", root=tmp_path)

    assert len(checks) == 1
    check = checks[0]
    assert check.status == "blocked"
    assert check.root_source == "argument"
    assert check.root_path == str(tmp_path)
    assert check.expected_local_path == str(tmp_path / "litsearch")
    assert check.found_files == ()
    assert check.missing_files == (
        str(tmp_path / "litsearch" / "query" / "queries.jsonl"),
        str(tmp_path / "litsearch" / "corpus_clean" / "corpus.jsonl"),
    )


def test_local_data_check_passes_when_litsearch_required_files_exist(tmp_path: Path):
    query_file = tmp_path / "litsearch" / "query" / "queries.jsonl"
    corpus_file = tmp_path / "litsearch" / "corpus_clean" / "corpus.jsonl"
    query_file.parent.mkdir(parents=True)
    corpus_file.parent.mkdir(parents=True)
    query_file.write_text("{}\n", encoding="utf-8")
    corpus_file.write_text("{}\n", encoding="utf-8")

    payload = local_benchmark_data_check_payload("litsearch", root=tmp_path)

    assert payload["status"] == "pass"
    assert payload["check_count"] == 1
    assert payload["checks"][0]["found_files"] == [
        str(query_file),
        str(corpus_file),
    ]
    assert payload["checks"][0]["missing_files"] == []


def test_local_data_check_cli_emits_blocked_status(tmp_path: Path):
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        [
            "local-data-check",
            "--benchmark-id",
            "litsearch",
            "--root",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == (
        "researchflowbench.local_benchmark_data_check.v0.1"
    )
    assert payload["status"] == "blocked"
    assert payload["checks"][0]["benchmark_id"] == "litsearch"
    assert payload["checks"][0]["missing_files"]


def test_litsearch_adapter_cli_writes_manifest(tmp_path: Path):
    data_dir = tmp_path / "litsearch"
    query_dir = data_dir / "query"
    query_dir.mkdir(parents=True)
    (query_dir / "queries.jsonl").write_text(
        json.dumps(
            {
                "query_id": "q3",
                "query": "find a paper about neural reranking",
                "gold_paper_ids": ["p1"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        [
            "adapt-litsearch",
            "--data",
            str(data_dir),
            "--out",
            str(out_dir),
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    manifest = json.loads((out_dir / "adapter_manifest.json").read_text("utf-8"))
    assert manifest["benchmark_id"] == "litsearch"
    assert manifest["task_ids"] == ["litsearch.q3"]


def test_external_task_pack_validator_accepts_gold_blind_adapter_pack(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    LitSearchAdapter.from_records(
        [
            {
                "query_id": "qv1",
                "query": "find literature search evaluation papers",
                "gold_paper_ids": ["p1"],
            }
        ]
    ).write_task_pack(out_dir)

    report = validate_external_task_pack(out_dir)

    assert report.is_valid, report.to_dict()
    assert report.checked_task_count == 1
    assert report.checked_file_count == 2


def test_external_task_pack_validator_rejects_visible_gold(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    LitSearchAdapter.from_records(
        [
            {
                "query_id": "qv2",
                "query": "find citation reranking papers",
                "gold_paper_ids": ["p1"],
            }
        ]
    ).write_task_pack(out_dir)
    task_path = out_dir / "tasks" / "litsearch.qv2" / "input.json"
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    payload["artifact_policy"]["gold_visible"] = True
    task_path.write_text(json.dumps(payload), encoding="utf-8")

    report = validate_external_task_pack(out_dir)

    assert not report.is_valid
    assert "external_task_gold_visible" in {issue.code for issue in report.issues}


def test_external_task_pack_validator_cli_reports_pass(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    LitSearchAdapter.from_records(
        [
            {
                "query_id": "qv3",
                "query": "find neural retrieval papers",
                "gold_paper_ids": ["p1"],
            }
        ]
    ).write_task_pack(out_dir)
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        ["validate-external-pack", "--task-pack", str(out_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "validation PASS" in result.output


def test_external_baseline_scores_litsearch_pack_with_local_gold(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    LitSearchAdapter.from_records(
        [
            {
                "query_id": "qscore1",
                "query": "find neural retrieval papers",
                "gold_paper_ids": ["p1"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)

    result = run_external_task_pack_baseline(out_dir, evidence_state="real_data")

    assert result.validation_report.is_valid
    assert result.report["benchmark_id"] == "litsearch"
    assert result.report["model_execution_performed"] is False
    assert result.report["scores"][0]["metrics"]["retrieval_recall"] == 0.0
    assert result.report["scores"][0]["evidence_state"] == "real_data"
    assert result.report["metadata"]["blocked_score_count"] == 0
    assert result.report["metrics"]["blocked_score_count"] == 0


def test_external_baseline_marks_missing_local_gold_blocked(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    LitSearchAdapter.from_records(
        [
            {
                "query_id": "qscore2",
                "query": "find neural retrieval papers",
                "gold_paper_ids": ["p1"],
            }
        ]
    ).write_task_pack(out_dir)

    result = run_external_task_pack_baseline(out_dir)

    assert result.report["metadata"]["blocked_score_count"] == 1
    assert result.report["scores"][0]["evidence_state"] == "blocked_missing_local_gold"
    assert result.report["metrics"]["blocked_score_count"] == 1


def test_external_lexical_baseline_scores_litsearch_against_local_corpus(
    tmp_path: Path,
):
    data_dir = tmp_path / "litsearch"
    corpus_file = data_dir / "corpus_clean" / "corpus.jsonl"
    corpus_file.parent.mkdir(parents=True)
    corpus_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "corpusid": 101,
                        "title": "Neural reranking for literature search",
                        "abstract": "A dense retrieval method for scientific papers.",
                    }
                ),
                json.dumps(
                    {
                        "corpusid": 202,
                        "title": "Unrelated vision model",
                        "abstract": "An image classification method.",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "external-pack"
    LitSearchAdapter.from_records(
        [
            {
                "query_id": "qlex",
                "query": "dense retrieval literature search",
                "gold_paper_ids": ["101"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)

    result = run_external_task_pack_baseline(
        out_dir,
        baseline_id="lexical_retrieval",
        data_root=data_dir,
        evidence_state="real_data",
    )

    score = result.report["scores"][0]
    assert score["metrics"]["retrieval_recall"] == 1.0
    assert score["metrics"]["hit_at_k"] is True
    assert score["retrieved_paper_ids"][0] == "101"


def test_external_bm25_baseline_scores_litsearch_against_local_corpus(
    tmp_path: Path,
):
    data_dir = tmp_path / "litsearch"
    corpus_file = data_dir / "corpus_clean" / "corpus.jsonl"
    corpus_file.parent.mkdir(parents=True)
    corpus_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "corpusid": 101,
                        "title": "Neural reranking for literature search",
                        "abstract": "A dense retrieval method for scientific papers.",
                    }
                ),
                json.dumps(
                    {
                        "corpusid": 202,
                        "title": "Unrelated vision model",
                        "abstract": "An image classification method.",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "external-pack"
    LitSearchAdapter.from_records(
        [
            {
                "query_id": "qbm25",
                "query": "dense retrieval literature search",
                "gold_paper_ids": ["101"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)

    result = run_external_task_pack_baseline(
        out_dir,
        baseline_id="bm25_retrieval",
        data_root=data_dir,
        evidence_state="real_data",
    )

    score = result.report["scores"][0]
    assert result.report["baseline_id"] == "bm25_retrieval"
    assert score["metrics"]["retrieval_recall"] == 1.0
    assert score["retrieved_paper_ids"][0] == "101"


def test_external_primitive_replay_scores_litsearch_with_real_paper_search(
    tmp_path: Path,
):
    data_dir = tmp_path / "litsearch"
    corpus_file = data_dir / "corpus_clean" / "corpus.jsonl"
    corpus_file.parent.mkdir(parents=True)
    corpus_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "corpusid": 101,
                        "title": "Scientific discovery systems",
                        "abstract": "Dense retrieval and neural reranking for literature search.",
                    }
                ),
                json.dumps(
                    {
                        "corpusid": 202,
                        "title": "Unrelated vision model",
                        "abstract": "An image classification method.",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "external-pack"
    LitSearchAdapter.from_records(
        [
            {
                "query_id": "qprimitive",
                "query": "dense retrieval reranking",
                "gold_paper_ids": ["101"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)

    result = run_external_task_pack_primitive(
        out_dir,
        runner_id="paper_search_local_bm25",
        data_root=data_dir,
        evidence_state="real_data",
    )

    score = result.report["scores"][0]
    assert result.report["baseline_kind"] == "rh_primitive_replay"
    assert result.report["runner_id"] == "paper_search_local_bm25"
    assert score["metrics"]["retrieval_recall"] == 1.0
    assert score["retrieved_paper_ids"][0] == "101"
    assert score["primitive_trace"]["primitive"] == "paper_search"
    assert score["primitive_trace"]["local_only"] is True
    assert score["primitive_trace"]["local_index_cache"] is True
    assert score["primitive_trace"]["retrieval_backend"] == "local_bm25_metadata_v0"
    assert score["retrieval_trace"]["schema_version"] == (
        "researchflowbench.external_retrieval_trace.v0.1"
    )
    assert score["retrieval_trace"]["query"] == "dense retrieval reranking"
    assert score["retrieval_trace"]["retrieval_tool_calls"] == [
        {
            "tool_name": "paper_search",
            "call_mode": "local_only",
            "local_index_cache": True,
            "max_results": 20,
        }
    ]
    assert score["retrieval_trace"]["candidate_ids"][0] == "101"
    assert score["retrieval_trace"]["candidate_set"][0]["rank"] == 1
    assert score["retrieval_trace"]["candidate_set"][0]["source"] == (
        "paper_search.local_bm25_metadata_v0"
    )
    assert score["retrieval_trace"]["retrieval_trace_complete"] is True


def test_external_baseline_cli_writes_score_report(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "deep-cli-score",
                "question": "Find the exact paper title.",
                "search_type": "deep",
                "answer": ["Exact Paper Title"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        [
            "run-external-baseline",
            "--task-pack",
            str(out_dir),
            "--out",
            str(score_file),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(score_file.read_text(encoding="utf-8"))
    assert payload["benchmark_id"] == "autoresearchbench"
    assert payload["scores"][0]["metrics"]["deep_accuracy"] == 0.0


def test_autoresearchbench_candidate_bm25_rejects_official_gold_source(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "deep-gold-source",
                "question": "Find the exact paper title.",
                "search_type": "deep",
                "answer": ["Exact Paper Title"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    official_dir = tmp_path / "official"
    official_dir.mkdir()
    (official_dir / "AutoResearchBench.jsonl").write_text(
        json.dumps(
            {
                "question": "Find the exact paper title.",
                "answer": ["Exact Paper Title"],
                "arxiv_id": ["2401.00001"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="candidate_manifest.json"):
        run_external_task_pack_baseline(
            out_dir,
            baseline_id="autoresearchbench_candidate_bm25",
            data_root=official_dir,
        )


@pytest.mark.parametrize(
    ("manifest", "message"),
    (
        (
            {
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            },
            "schema_version",
        ),
        (
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            },
            "records_file",
        ),
        (
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "../AutoResearchBench.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            },
            "records_file",
        ),
    ),
)
def test_autoresearchbench_candidate_bm25_rejects_invalid_candidate_manifest(
    tmp_path: Path,
    manifest: dict[str, object],
    message: str,
):
    out_dir = tmp_path / "external-pack"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "deep-invalid-manifest",
                "question": "Find the exact paper title.",
                "search_type": "deep",
                "answer": ["Exact Paper Title"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    candidate_dir.mkdir()
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        run_external_task_pack_baseline(
            out_dir,
            baseline_id="autoresearchbench_candidate_bm25",
            data_root=candidate_dir,
        )


def test_autoresearchbench_candidate_bm25_scores_non_gold_candidate_source(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "deep-candidate",
                "question": "exact paper clue",
                "search_type": "deep",
                "answer": ["Exact Paper Title"],
            },
            {
                "id": "wide-candidate",
                "question": "matching benchmark condition",
                "search_type": "wide",
                "answer": ["Matching Benchmark Condition"],
                "arxiv_id": ["2401.00001"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    candidate_dir.mkdir()
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
                "source_type": "synthetic_non_gold_candidate_fixture",
                "third_party_data_vendored": False,
            }
        ),
        encoding="utf-8",
    )
    (candidate_dir / "candidate_corpus.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "paper_id": "deep-match",
                        "title": "Exact Paper Title",
                        "abstract": "exact paper clue retrieval candidate",
                        "arxiv_id": "2301.00001",
                    }
                ),
                json.dumps(
                    {
                        "paper_id": "wide-match",
                        "title": "Matching Benchmark Condition",
                        "abstract": "matching benchmark condition candidate",
                        "arxiv_id": "2401.00001",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_external_task_pack_baseline(
        out_dir,
        baseline_id="autoresearchbench_candidate_bm25",
        data_root=candidate_dir,
        evidence_state="real_data",
    )

    scores = {score["task_id"]: score for score in result.report["scores"]}
    deep_score = scores["autoresearchbench.deep-candidate"]
    wide_score = scores["autoresearchbench.wide-candidate"]
    assert result.report["baseline_kind"] == "model_free_candidate_retrieval"
    assert deep_score["metrics"]["deep_accuracy"] == 1.0
    assert deep_score["predicted_titles"] == ["Exact Paper Title"]
    assert deep_score["retrieval_trace"]["candidate_ids"][0] == "deep-match"
    assert wide_score["metrics"]["wide_iou"] == 1.0
    assert wide_score["predicted_arxiv_ids"] == ["2401.00001"]
    assert wide_score["retrieval_trace"]["candidate_set"][0]["source"] == (
        "autoresearchbench_candidate_bm25.candidate_corpus"
    )


def test_autoresearchbench_candidate_bm25_keeps_duplicate_candidate_ids(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "wide-duplicate-id",
                "question": "duplicate candidate clue",
                "search_type": "wide",
                "answer": ["Duplicate Candidate Clue"],
                "arxiv_id": ["2401.00001"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    candidate_dir.mkdir()
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            }
        ),
        encoding="utf-8",
    )
    (candidate_dir / "candidate_corpus.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "paper_id": "duplicate-id",
                        "title": "Duplicate Candidate Clue Distractor",
                        "abstract": "",
                        "arxiv_id": "2501.00001",
                    }
                ),
                json.dumps(
                    {
                        "paper_id": "duplicate-id",
                        "title": "Duplicate Candidate Clue Match",
                        "abstract": "",
                        "arxiv_id": "2401.00001",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_external_task_pack_baseline(
        out_dir,
        baseline_id="autoresearchbench_candidate_bm25",
        data_root=candidate_dir,
        candidate_top_k=2,
    )

    candidate_ids = result.report["scores"][0]["retrieval_trace"]["candidate_ids"]
    assert len(candidate_ids) == 2
    assert len(set(candidate_ids)) == 2
    assert candidate_ids[0] == "duplicate-id"
    assert candidate_ids[1].startswith("duplicate-id#")


def test_autoresearchbench_candidate_bm25_extracts_arxiv_id_from_public_doi(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "wide-doi-candidate",
                "question": "matching public doi benchmark condition",
                "search_type": "wide",
                "answer": ["Matching Public DOI Benchmark Condition"],
                "arxiv_id": ["2401.00001"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    candidate_dir.mkdir()
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            }
        ),
        encoding="utf-8",
    )
    (candidate_dir / "candidate_corpus.jsonl").write_text(
        json.dumps(
            {
                "paper_id": "doi-match",
                "title": "Matching Public DOI Benchmark Condition",
                "abstract": "matching public doi benchmark condition candidate",
                "doi": "https://doi.org/10.48550/arXiv.2401.00001",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_external_task_pack_baseline(
        out_dir,
        baseline_id="autoresearchbench_candidate_bm25",
        data_root=candidate_dir,
        evidence_state="real_data",
    )

    score = result.report["scores"][0]
    assert score["metrics"]["wide_iou"] == 1.0
    assert score["predicted_arxiv_ids"] == ["2401.00001"]


def test_autoresearchbench_candidate_bm25_respects_candidate_top_k(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "wide-top-k-candidate",
                "question": "shared retrieval clue",
                "search_type": "wide",
                "answer": ["Shared Retrieval Clue"],
                "arxiv_id": ["2401.00001"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    candidate_dir.mkdir()
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            }
        ),
        encoding="utf-8",
    )
    (candidate_dir / "candidate_corpus.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "paper_id": "aaa-distractor",
                        "title": "Shared Retrieval Clue Distractor",
                        "abstract": "",
                        "arxiv_id": "2501.00001",
                    }
                ),
                json.dumps(
                    {
                        "paper_id": "zzz-match",
                        "title": "Shared Retrieval Clue Match",
                        "abstract": "",
                        "arxiv_id": "2401.00001",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    top1 = run_external_task_pack_baseline(
        out_dir,
        baseline_id="autoresearchbench_candidate_bm25",
        data_root=candidate_dir,
        candidate_top_k=1,
    )
    top2 = run_external_task_pack_baseline(
        out_dir,
        baseline_id="autoresearchbench_candidate_bm25",
        data_root=candidate_dir,
        candidate_top_k=2,
    )

    assert top1.report["metadata"]["candidate_top_k"] == 1
    assert top1.report["scores"][0]["metrics"]["wide_iou"] == 0.0
    assert top2.report["metadata"]["candidate_top_k"] == 2
    assert top2.report["scores"][0]["metrics"]["wide_iou"] > 0.0


def test_autoresearchbench_candidate_coverage_diagnostic_omits_gold_details(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "deep-coverage",
                "question": "shared coverage clue",
                "search_type": "deep",
                "answer": ["Secret Covered Paper"],
            },
            {
                "id": "wide-coverage",
                "question": "shared coverage clue",
                "search_type": "wide",
                "answer": ["Secret Wide Paper"],
                "arxiv_id": ["2401.00001"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    candidate_dir.mkdir()
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            }
        ),
        encoding="utf-8",
    )
    (candidate_dir / "candidate_corpus.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "paper_id": "aaa-distractor",
                        "title": "Shared Coverage Clue Distractor",
                        "abstract": "",
                        "arxiv_id": "2501.00001",
                    }
                ),
                json.dumps(
                    {
                        "paper_id": "zzz-deep-match",
                        "title": "Secret Covered Paper",
                        "abstract": "not ranked at top one",
                    }
                ),
                json.dumps(
                    {
                        "paper_id": "zzz-wide-match",
                        "title": "Secret Wide Paper",
                        "abstract": "not ranked at top one",
                        "arxiv_id": "2401.00001",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_external_task_pack_baseline(
        out_dir,
        baseline_id="autoresearchbench_candidate_bm25",
        data_root=candidate_dir,
        candidate_top_k=1,
    )
    write_score_report(result.report, score_file)
    module = load_autoresearchbench_candidate_coverage_script()

    diagnostic = module.diagnose_candidate_coverage(
        task_pack=out_dir,
        candidate_source=candidate_dir,
        score_file=score_file,
    )
    rendered = json.dumps(diagnostic, sort_keys=True)

    assert diagnostic["gold_detail_emitted"] is False
    assert diagnostic["score_candidate_top_k"] == 1
    assert diagnostic["by_type"]["deep"]["title_covered_task_count"] == 1
    assert diagnostic["by_type"]["deep"]["title_top_hit_task_count"] == 0
    assert diagnostic["by_type"]["wide"]["arxiv_covered_task_count"] == 1
    assert diagnostic["by_type"]["wide"]["arxiv_top_hit_task_count"] == 0
    assert "Secret Covered Paper" not in rendered
    assert "2401.00001" not in rendered


def test_autoresearchbench_candidate_rerank_diagnostic_omits_gold_details(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "deep-rerank",
                "question": "public clue token",
                "search_type": "deep",
                "answer": ["Secret Covered Paper"],
            },
            {
                "id": "wide-rerank",
                "question": "public clue token",
                "search_type": "wide",
                "answer": ["Secret Wide Paper"],
                "arxiv_id": ["2401.00001"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    score_file.write_text(
        json.dumps(
            {
                "metadata": {"candidate_top_k": 2},
                "scores": [
                    {
                        "task_id": "autoresearchbench.deep-rerank",
                        "retrieval_trace": {
                            "candidate_set": [
                                {
                                    "candidate_id": "distractor",
                                    "rank": 1,
                                    "score": 3.0,
                                    "title": "Public Distractor",
                                    "arxiv_id": "",
                                },
                                {
                                    "candidate_id": "deep-match",
                                    "rank": 2,
                                    "score": 1.0,
                                    "title": "Secret Covered Paper",
                                    "arxiv_id": "",
                                },
                            ]
                        },
                    },
                    {
                        "task_id": "autoresearchbench.wide-rerank",
                        "retrieval_trace": {
                            "candidate_set": [
                                {
                                    "candidate_id": "wide-distractor",
                                    "rank": 1,
                                    "score": 3.0,
                                    "title": "Public Distractor",
                                    "arxiv_id": "2501.00001",
                                },
                                {
                                    "candidate_id": "wide-match",
                                    "rank": 2,
                                    "score": 1.0,
                                    "title": "Secret Wide Paper",
                                    "arxiv_id": "2401.00001",
                                },
                            ]
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()

    diagnostic = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        selection_ks=(1, 2),
    )
    rendered = json.dumps(diagnostic, sort_keys=True)
    by_strategy = {
        (item["strategy_id"], item["selection_k"]): item
        for item in diagnostic["strategies"]
    }

    assert diagnostic["gold_detail_emitted"] is False
    assert diagnostic["score_candidate_top_k"] == 2
    assert by_strategy[("bm25_order", 1)]["metrics"]["mean_deep_accuracy"] == 0.0
    assert by_strategy[("bm25_order", 2)]["metrics"]["mean_deep_accuracy"] == 0.5
    assert by_strategy[("bm25_order", 2)]["by_type"]["wide"]["positive_task_count"] == 1
    assert "Secret Covered Paper" not in rendered
    assert "Secret Wide Paper" not in rendered
    assert "2401.00001" not in rendered


def test_autoresearchbench_candidate_rerank_diagnostic_supports_source_retrieval(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "deep-source-rrf",
                "question": (
                    "Find the paper connected to a public tail clue about "
                    "calibration lattice retrieval."
                ),
                "search_type": "deep",
                "answer": ["Secret Source RRF Paper"],
            },
            {
                "id": "wide-source-rrf",
                "question": (
                    "Find papers connected to a public tail clue about "
                    "federated lattice retrieval."
                ),
                "search_type": "wide",
                "answer": ["Secret Source RRF Wide Paper"],
                "arxiv_id": ["2401.00001"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    score_file.write_text(
        json.dumps(
            {
                "metadata": {"candidate_top_k": 1},
                "scores": [
                    {
                        "task_id": "autoresearchbench.deep-source-rrf",
                        "retrieval_trace": {
                            "candidate_set": [
                                {
                                    "candidate_id": "deep-distractor",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Public Distractor",
                                    "arxiv_id": "",
                                }
                            ]
                        },
                    },
                    {
                        "task_id": "autoresearchbench.wide-source-rrf",
                        "retrieval_trace": {
                            "candidate_set": [
                                {
                                    "candidate_id": "wide-distractor",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Public Distractor",
                                    "arxiv_id": "2501.00001",
                                }
                            ]
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    candidate_dir = tmp_path / "candidate-source"
    candidate_dir.mkdir()
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            }
        ),
        encoding="utf-8",
    )
    (candidate_dir / "candidate_corpus.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "paper_id": "deep-source-match",
                        "title": "Secret Source RRF Paper",
                        "abstract": "calibration lattice retrieval public tail clue",
                        "arxiv_id": "2301.00001",
                    }
                ),
                json.dumps(
                    {
                        "paper_id": "wide-source-match",
                        "title": "Secret Source RRF Wide Paper",
                        "abstract": "federated lattice retrieval public tail clue",
                        "arxiv_id": "2401.00001",
                    }
                ),
                json.dumps(
                    {
                        "paper_id": "source-distractor",
                        "title": "Unrelated Public Distractor",
                        "abstract": "unrelated evidence for another benchmark",
                        "arxiv_id": "2501.00001",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()

    diagnostic = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        candidate_source=candidate_dir,
        candidate_search_k=3,
        selection_ks=(1,),
    )
    rendered = json.dumps(diagnostic, sort_keys=True)
    by_strategy = {
        (item["strategy_id"], item["selection_k"]): item
        for item in diagnostic["strategies"]
    }

    assert diagnostic["gold_detail_emitted"] is False
    assert diagnostic["candidate_source_record_count"] == 3
    assert diagnostic["strategy_kinds"] == ["source_retrieval", "trace_rerank"]
    assert diagnostic["strategy_dependency_kinds"] == [
        "source_augmented_trace_rerank",
        "source_retrieval",
        "trace_only_rerank",
    ]
    assert by_strategy[("bm25_order", 1)]["strategy_kind"] == "trace_rerank"
    assert (
        by_strategy[("bm25_order", 1)]["strategy_dependency_kind"]
        == "trace_only_rerank"
    )
    assert (
        by_strategy[("metadata_field_overlap_bm25_blend", 1)]["strategy_kind"]
        == "trace_rerank"
    )
    assert (
        by_strategy[("metadata_field_overlap_bm25_blend", 1)][
            "strategy_dependency_kind"
        ]
        == "source_augmented_trace_rerank"
    )
    assert (
        by_strategy[("query_variant_rrf_bm25", 1)]["strategy_kind"]
        == "source_retrieval"
    )
    assert (
        by_strategy[("query_variant_rrf_bm25", 1)]["strategy_dependency_kind"]
        == "source_retrieval"
    )
    assert by_strategy[("bm25_order", 1)]["metrics"]["mean_deep_accuracy"] == 0.0
    assert (
        by_strategy[("query_variant_rrf_bm25", 1)]["metrics"]["mean_deep_accuracy"]
        == 0.5
    )
    assert (
        by_strategy[("query_variant_rrf_bm25", 1)]["by_type"]["wide"][
            "positive_task_count"
        ]
        == 1
    )
    assert (
        by_strategy[("idf_query_rrf_bm25", 1)]["metrics"]["mean_deep_accuracy"] == 0.5
    )
    assert (
        by_strategy[("idf_query_rrf_bm25", 1)]["by_type"]["wide"]["positive_task_count"]
        == 1
    )
    assert (
        by_strategy[("idf_window_rrf_bm25", 1)]["metrics"]["mean_deep_accuracy"] == 0.5
    )
    assert (
        by_strategy[("idf_window_rrf_bm25", 1)]["by_type"]["wide"][
            "positive_task_count"
        ]
        == 1
    )
    assert "Secret Source RRF Paper" not in rendered
    assert "Secret Source RRF Wide Paper" not in rendered
    assert "2401.00001" not in rendered


def test_autoresearchbench_source_retrieval_idf_windows_keep_local_clues(
    tmp_path: Path,
):
    candidate_dir = tmp_path / "candidate-source"
    candidate_dir.mkdir()
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            }
        ),
        encoding="utf-8",
    )
    (candidate_dir / "candidate_corpus.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "paper_id": "rare-window-match",
                        "title": "Rare Window Match",
                        "abstract": "calibration lattice retrieval phase diagram",
                    }
                ),
                json.dumps(
                    {
                        "paper_id": "generic-context",
                        "title": "Generic Context",
                        "abstract": (
                            "benchmark evaluation model system analysis result "
                            "dataset method"
                        ),
                    }
                ),
                json.dumps(
                    {
                        "paper_id": "split-rare-terms",
                        "title": "Split Rare Terms",
                        "abstract": (
                            "calibration benchmark lattice evaluation retrieval "
                            "system phase model diagram"
                        ),
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()
    source = module._build_autoresearchbench_candidate_source(candidate_dir)

    variants = module._query_variants(
        (
            "Find a paper from a broad benchmark evaluation model system. "
            "The public clue says calibration lattice retrieval phase diagram."
        ),
        candidate_source=source,
        include_raw=False,
        variant_mode="idf_window",
    )
    variant_queries = [variant["query"] for variant in variants]

    assert variant_queries
    assert all(
        not variant["variant_id"].startswith("raw_visible") for variant in variants
    )
    assert any(
        "calibration lattice retrieval phase diagram" in query
        for query in variant_queries
    )


def test_autoresearchbench_source_retrieval_reuses_cached_variant_searches(
    tmp_path: Path,
):
    candidate_dir = tmp_path / "candidate-source"
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "cache-match",
                "title": "Cache Match",
                "abstract": "calibration lattice retrieval public tail clue",
                "arxiv_id": "2301.00001",
            },
            {
                "paper_id": "cache-distractor",
                "title": "Cache Distractor",
                "abstract": "unrelated public benchmark evidence",
                "arxiv_id": "2301.00002",
            },
        ],
    )
    module = load_autoresearchbench_candidate_rerank_script()
    base_source = module._build_autoresearchbench_candidate_source(candidate_dir)

    class CountingIndex:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.calls = []

        def search(self, query: str, *, k: int = 20, scoring: str = "bm25"):
            self.calls.append((query, k, scoring))
            return self.wrapped.search(query, k=k, scoring=scoring)

    counting_index = CountingIndex(base_source.index)
    source = SimpleNamespace(
        index=counting_index,
        records_by_id=base_source.records_by_id,
        manifest=base_source.manifest,
    )
    query = (
        "Find the paper connected to a public tail clue about "
        "calibration lattice retrieval."
    )
    search_cache = {}

    first = module._rerank_candidates(
        (),
        query=query,
        strategy_id="query_variant_rrf_bm25",
        candidate_source=source,
        candidate_search_k=2,
        include_raw_query=True,
        source_search_cache=search_cache,
    )
    call_count_after_first = len(counting_index.calls)
    second = module._rerank_candidates(
        (),
        query=query,
        strategy_id="query_variant_rrf_field_blend",
        candidate_source=source,
        candidate_search_k=2,
        include_raw_query=True,
        source_search_cache=search_cache,
    )

    assert first
    assert second
    assert call_count_after_first > 0
    assert len(counting_index.calls) == call_count_after_first


def test_autoresearchbench_source_retrieval_cache_is_source_scoped(tmp_path: Path):
    candidate_dir_a = tmp_path / "candidate-source-a"
    candidate_dir_b = tmp_path / "candidate-source-b"
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir_a,
        [
            {
                "paper_id": "cache-source-a",
                "title": "Cache Source A",
                "abstract": "shared cache clue",
                "arxiv_id": "2301.00001",
            }
        ],
    )
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir_b,
        [
            {
                "paper_id": "cache-source-b",
                "title": "Cache Source B",
                "abstract": "shared cache clue",
                "arxiv_id": "2301.00002",
            }
        ],
    )
    module = load_autoresearchbench_candidate_rerank_script()
    base_source_a = module._build_autoresearchbench_candidate_source(candidate_dir_a)
    base_source_b = module._build_autoresearchbench_candidate_source(candidate_dir_b)

    class CountingIndex:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.calls = []

        def search(self, query: str, *, k: int = 20, scoring: str = "bm25"):
            self.calls.append((query, k, scoring))
            return self.wrapped.search(query, k=k, scoring=scoring)

    counting_index_a = CountingIndex(base_source_a.index)
    counting_index_b = CountingIndex(base_source_b.index)
    source_a = SimpleNamespace(
        index=counting_index_a,
        records_by_id=base_source_a.records_by_id,
        manifest=base_source_a.manifest,
    )
    source_b = SimpleNamespace(
        index=counting_index_b,
        records_by_id=base_source_b.records_by_id,
        manifest=base_source_b.manifest,
    )
    search_cache = {}

    first = module._rerank_candidates(
        (),
        query="shared cache clue",
        strategy_id="query_variant_rrf_bm25",
        candidate_source=source_a,
        candidate_search_k=1,
        include_raw_query=True,
        source_search_cache=search_cache,
    )
    second = module._rerank_candidates(
        (),
        query="shared cache clue",
        strategy_id="query_variant_rrf_bm25",
        candidate_source=source_b,
        candidate_search_k=1,
        include_raw_query=True,
        source_search_cache=search_cache,
    )

    assert first[0]["candidate_id"] == "cache-source-a"
    assert second[0]["candidate_id"] == "cache-source-b"
    assert counting_index_a.calls
    assert counting_index_b.calls


def test_autoresearchbench_source_retrieval_diagnostic_can_exclude_raw_query(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "raw-fallback",
                "question": "paper about",
                "search_type": "deep",
                "answer": ["Raw Fallback Paper"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    score_file.write_text(
        json.dumps(
            {
                "metadata": {"candidate_top_k": 1},
                "scores": [
                    {
                        "task_id": "autoresearchbench.raw-fallback",
                        "retrieval_trace": {"candidate_set": []},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    candidate_dir = tmp_path / "candidate-source"
    candidate_dir.mkdir()
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            }
        ),
        encoding="utf-8",
    )
    (candidate_dir / "candidate_corpus.jsonl").write_text(
        json.dumps(
            {
                "paper_id": "raw-fallback-match",
                "title": "Raw Fallback Paper",
                "abstract": "paper about raw fallback",
                "arxiv_id": "2301.00001",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()

    without_raw = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        candidate_source=candidate_dir,
        candidate_search_k=1,
        include_raw_query=False,
        selection_ks=(1,),
    )
    with_raw = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        candidate_source=candidate_dir,
        candidate_search_k=1,
        include_raw_query=True,
        selection_ks=(1,),
    )
    without_by_strategy = {
        (item["strategy_id"], item["selection_k"]): item
        for item in without_raw["strategies"]
    }
    with_by_strategy = {
        (item["strategy_id"], item["selection_k"]): item
        for item in with_raw["strategies"]
    }

    assert without_raw["include_raw_query"] is False
    assert with_raw["include_raw_query"] is True
    assert (
        without_by_strategy[("query_variant_rrf_bm25", 1)]["metrics"][
            "mean_deep_accuracy"
        ]
        == 0.0
    )
    assert (
        with_by_strategy[("query_variant_rrf_bm25", 1)]["metrics"]["mean_deep_accuracy"]
        == 1.0
    )
    assert (
        without_by_strategy[("idf_query_rrf_bm25", 1)]["metrics"]["mean_deep_accuracy"]
        == 0.0
    )
    assert (
        with_by_strategy[("idf_query_rrf_bm25", 1)]["metrics"]["mean_deep_accuracy"]
        == 1.0
    )
    assert (
        without_by_strategy[("idf_window_rrf_bm25", 1)]["metrics"]["mean_deep_accuracy"]
        == 0.0
    )
    assert (
        with_by_strategy[("idf_window_rrf_bm25", 1)]["metrics"]["mean_deep_accuracy"]
        == 1.0
    )


def test_autoresearchbench_source_retrieval_reports_candidate_source_mismatch(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "candidate-source-mismatch",
                "question": "public mismatch clue",
                "search_type": "deep",
                "answer": ["Expected Source Paper"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    expected_source_dir = tmp_path / "expected-source"
    actual_source_dir = tmp_path / "actual-source"
    expected_source_dir.mkdir()
    actual_source_dir.mkdir()
    score_file.write_text(
        json.dumps(
            {
                "metadata": {
                    "candidate_top_k": 1,
                    "data_root": str(expected_source_dir),
                },
                "scores": [
                    {
                        "task_id": "autoresearchbench.candidate-source-mismatch",
                        "retrieval_trace": {
                            "schema_version": (
                                "researchflowbench.autoresearchbench_candidate_trace.v0.1"
                            ),
                            "baseline_id": "autoresearchbench_candidate_bm25",
                            "candidate_source_schema_version": (
                                "researchflowbench.autoresearchbench_candidate_source.v0.1"
                            ),
                            "retrieval_trace_complete": True,
                            "candidate_set": [
                                {
                                    "candidate_id": "expected-only",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Expected Source Paper",
                                    "arxiv_id": "",
                                }
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (actual_source_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            }
        ),
        encoding="utf-8",
    )
    (actual_source_dir / "candidate_corpus.jsonl").write_text(
        json.dumps(
            {
                "paper_id": "actual-only",
                "title": "Actual Source Paper",
                "abstract": "public mismatch clue",
                "arxiv_id": "2301.00001",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()

    diagnostic = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        candidate_source=actual_source_dir,
        candidate_search_k=1,
        selection_ks=(1,),
    )
    compatibility = diagnostic["candidate_source_compatibility"]

    assert compatibility["checked"] is True
    assert compatibility["data_root_matches"] is False
    assert compatibility["missing_source_record_count"] == 1
    assert "score_report_data_root_mismatch" in compatibility["warnings"]
    assert (
        "trace_candidate_ids_missing_from_candidate_source" in compatibility["warnings"]
    )


def test_autoresearchbench_source_retrieval_accepts_repo_relative_data_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo_root = tmp_path / "repo-root"
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "reports" / "score.json"
    score_file.parent.mkdir()
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "relative-data-root",
                "question": "public relative root clue",
                "search_type": "deep",
                "answer": ["Relative Root Paper"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = repo_root / "fixtures" / "candidate-source"
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "relative-match",
                "title": "Relative Root Paper",
                "abstract": "public relative root clue",
                "arxiv_id": "2301.00001",
            }
        ],
    )
    score_file.write_text(
        json.dumps(
            {
                "metadata": {
                    "candidate_top_k": 1,
                    "data_root": "fixtures/candidate-source",
                },
                "scores": [
                    {
                        "task_id": "autoresearchbench.relative-data-root",
                        "retrieval_trace": {
                            "schema_version": (
                                "researchflowbench.autoresearchbench_candidate_trace.v0.1"
                            ),
                            "baseline_id": "autoresearchbench_candidate_bm25",
                            "candidate_source_schema_version": (
                                "researchflowbench.autoresearchbench_candidate_source.v0.1"
                            ),
                            "retrieval_trace_complete": True,
                            "candidate_set": [
                                {
                                    "candidate_id": "relative-match",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Relative Root Paper",
                                    "arxiv_id": "2301.00001",
                                }
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    module = load_autoresearchbench_candidate_rerank_script()
    monkeypatch.setattr(module, "REPO_ROOT", repo_root)
    monkeypatch.chdir(other_cwd)

    diagnostic = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        candidate_source=candidate_dir,
        candidate_search_k=1,
        selection_ks=(1,),
        selected_strategy_ids=("bm25_order",),
    )
    compatibility = diagnostic["candidate_source_compatibility"]

    assert compatibility["checked"] is True
    assert compatibility["data_root_matches"] is True
    assert compatibility["warnings"] == []


def test_autoresearchbench_source_retrieval_reports_missing_selected_score_entry(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "missing-score",
                "question": "public missing score clue",
                "search_type": "deep",
                "answer": ["Missing Score Paper"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "missing-score-match",
                "title": "Missing Score Paper",
                "abstract": "public missing score clue",
                "arxiv_id": "2301.00001",
            }
        ],
    )
    score_file.write_text(
        json.dumps(
            {
                "metadata": {"candidate_top_k": 1},
                "scores": [],
            }
        ),
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()

    diagnostic = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        candidate_source=candidate_dir,
        candidate_search_k=1,
        selection_ks=(1,),
        selected_strategy_ids=("bm25_order",),
        selected_task_ids=("autoresearchbench.missing-score",),
    )
    compatibility = diagnostic["candidate_source_compatibility"]

    assert diagnostic["task_count"] == 1
    assert diagnostic["strategies"][0]["metrics"]["score_count"] == 1
    assert "missing_score_entry" in compatibility["warnings"]
    assert compatibility["missing_score_count"] == 1
    assert compatibility["missing_score_task_ids"] == [
        "autoresearchbench.missing-score"
    ]


def test_autoresearchbench_source_retrieval_treats_missing_trace_metadata_as_unknown(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "minimal-trace",
                "question": "public minimal trace clue",
                "search_type": "deep",
                "answer": ["Minimal Trace Paper"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "minimal-match",
                "title": "Minimal Trace Paper",
                "abstract": "public minimal trace clue",
                "arxiv_id": "2301.00001",
            }
        ],
    )
    score_file.write_text(
        json.dumps(
            {
                "metadata": {"candidate_top_k": 1},
                "scores": [
                    {
                        "task_id": "autoresearchbench.minimal-trace",
                        "retrieval_trace": {
                            "candidate_set": [
                                {
                                    "candidate_id": "minimal-match",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Minimal Trace Paper",
                                    "arxiv_id": "2301.00001",
                                }
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()

    diagnostic = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        candidate_source=candidate_dir,
        candidate_search_k=1,
        selection_ks=(1,),
        selected_strategy_ids=("bm25_order",),
    )
    compatibility = diagnostic["candidate_source_compatibility"]

    assert compatibility["warnings"] == []
    assert compatibility["trace_baseline_ids"] == []
    assert compatibility["trace_schema_versions"] == []
    assert compatibility["candidate_source_schema_versions"] == []
    assert compatibility["incomplete_trace_count"] == 0


def test_autoresearchbench_source_retrieval_validates_trace_schema(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "bad-trace-schema",
                "question": "public schema clue",
                "search_type": "deep",
                "answer": ["Schema Paper"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "schema-match",
                "title": "Schema Paper",
                "abstract": "public schema clue",
                "arxiv_id": "2301.00001",
            }
        ],
    )
    score_file.write_text(
        json.dumps(
            {
                "metadata": {"candidate_top_k": 1},
                "scores": [
                    {
                        "task_id": "autoresearchbench.bad-trace-schema",
                        "retrieval_trace": {
                            "schema_version": "researchflowbench.unexpected_trace.v9",
                            "baseline_id": "autoresearchbench_candidate_bm25",
                            "candidate_source_schema_version": (
                                "researchflowbench.autoresearchbench_candidate_source.v0.1"
                            ),
                            "retrieval_trace_complete": True,
                            "candidate_set": [
                                {
                                    "candidate_id": "schema-match",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Schema Paper",
                                    "arxiv_id": "2301.00001",
                                }
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()

    diagnostic = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        candidate_source=candidate_dir,
        candidate_search_k=1,
        selection_ks=(1,),
        selected_strategy_ids=("bm25_order",),
    )
    compatibility = diagnostic["candidate_source_compatibility"]

    assert "unexpected_trace_schema" in compatibility["warnings"]
    assert compatibility["trace_schema_versions"] == [
        "researchflowbench.unexpected_trace.v9"
    ]
    assert compatibility["expected_trace_schema_version"] == (
        "researchflowbench.autoresearchbench_candidate_trace.v0.1"
    )


def test_autoresearchbench_source_retrieval_scopes_compatibility_to_task_filter(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "compat-keep",
                "question": "public keep compatibility clue",
                "search_type": "deep",
                "answer": ["Compatibility Keep Paper"],
            },
            {
                "id": "compat-drop",
                "question": "public drop compatibility clue",
                "search_type": "deep",
                "answer": ["Compatibility Drop Paper"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "keep-match",
                "title": "Compatibility Keep Paper",
                "abstract": "public keep compatibility clue",
                "arxiv_id": "2301.00001",
            }
        ],
    )
    score_file.write_text(
        json.dumps(
            {
                "metadata": {"candidate_top_k": 1},
                "scores": [
                    {
                        "task_id": "autoresearchbench.compat-keep",
                        "retrieval_trace": {
                            "schema_version": (
                                "researchflowbench.autoresearchbench_candidate_trace.v0.1"
                            ),
                            "baseline_id": "autoresearchbench_candidate_bm25",
                            "candidate_source_schema_version": (
                                "researchflowbench.autoresearchbench_candidate_source.v0.1"
                            ),
                            "retrieval_trace_complete": True,
                            "candidate_set": [
                                {
                                    "candidate_id": "keep-match",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Compatibility Keep Paper",
                                    "arxiv_id": "2301.00001",
                                }
                            ],
                        },
                    },
                    {
                        "task_id": "autoresearchbench.compat-drop",
                        "retrieval_trace": {
                            "schema_version": "researchflowbench.unexpected_trace.v9",
                            "baseline_id": "unexpected_baseline",
                            "candidate_source_schema_version": "unexpected_source.v9",
                            "retrieval_trace_complete": False,
                            "candidate_set": [
                                {
                                    "candidate_id": "drop-missing",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Compatibility Drop Paper",
                                    "arxiv_id": "2301.00002",
                                }
                            ],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()

    diagnostic = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        candidate_source=candidate_dir,
        candidate_search_k=1,
        selection_ks=(1,),
        selected_strategy_ids=("bm25_order",),
        selected_task_ids=("autoresearchbench.compat-keep",),
    )
    compatibility = diagnostic["candidate_source_compatibility"]

    assert diagnostic["selected_task_ids"] == ["autoresearchbench.compat-keep"]
    assert compatibility["warnings"] == []
    assert compatibility["trace_candidate_id_count"] == 1
    assert compatibility["missing_source_record_count"] == 0
    assert compatibility["trace_baseline_ids"] == ["autoresearchbench_candidate_bm25"]
    assert compatibility["trace_schema_versions"] == [
        "researchflowbench.autoresearchbench_candidate_trace.v0.1"
    ]


def test_autoresearchbench_candidate_rerank_diagnostic_filters_strategies(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "strategy-filter",
                "question": "public strategy filter clue",
                "search_type": "deep",
                "answer": ["Strategy Filter Paper"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    score_file.write_text(
        json.dumps(
            {
                "metadata": {"candidate_top_k": 1},
                "scores": [
                    {
                        "task_id": "autoresearchbench.strategy-filter",
                        "retrieval_trace": {
                            "candidate_set": [
                                {
                                    "candidate_id": "trace-match",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Strategy Filter Paper",
                                    "arxiv_id": "",
                                }
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()

    diagnostic = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        selection_ks=(1,),
        selected_strategy_ids=("title_token_overlap", "bm25_order"),
    )

    assert diagnostic["selected_strategy_ids"] == [
        "bm25_order",
        "title_token_overlap",
    ]
    assert diagnostic["selected_task_ids"] == []
    assert [item["strategy_id"] for item in diagnostic["strategies"]] == [
        "bm25_order",
        "title_token_overlap",
    ]
    assert diagnostic["strategy_count"] == 2


def test_autoresearchbench_candidate_rerank_diagnostic_filters_task_ids(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "keep-task",
                "question": "public keep clue",
                "search_type": "deep",
                "answer": ["Keep Task Paper"],
            },
            {
                "id": "drop-task",
                "question": "public drop clue",
                "search_type": "deep",
                "answer": ["Drop Task Paper"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    score_file.write_text(
        json.dumps(
            {
                "metadata": {"candidate_top_k": 1},
                "scores": [
                    {
                        "task_id": "autoresearchbench.keep-task",
                        "retrieval_trace": {
                            "candidate_set": [
                                {
                                    "candidate_id": "keep-match",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Keep Task Paper",
                                    "arxiv_id": "",
                                }
                            ]
                        },
                    },
                    {
                        "task_id": "autoresearchbench.drop-task",
                        "retrieval_trace": {
                            "candidate_set": [
                                {
                                    "candidate_id": "drop-match",
                                    "rank": 1,
                                    "score": 4.0,
                                    "title": "Drop Task Paper",
                                    "arxiv_id": "",
                                }
                            ]
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    module = load_autoresearchbench_candidate_rerank_script()

    diagnostic = module.diagnose_candidate_rerank(
        task_pack=out_dir,
        score_file=score_file,
        selection_ks=(1,),
        selected_strategy_ids=("bm25_order",),
        selected_task_ids=("autoresearchbench.keep-task",),
    )

    assert diagnostic["selected_task_ids"] == ["autoresearchbench.keep-task"]
    assert diagnostic["task_count"] == 1
    assert diagnostic["strategies"][0]["metrics"]["mean_deep_accuracy"] == 1.0
    assert diagnostic["strategies"][0]["metrics"]["score_count"] == 1


def test_autoresearchbench_candidate_rerank_diagnostic_rejects_empty_task_pack(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    out_dir.mkdir()
    score_file = tmp_path / "score.json"
    score_file.write_text(json.dumps({"metadata": {}, "scores": []}), encoding="utf-8")
    module = load_autoresearchbench_candidate_rerank_script()

    with pytest.raises(ValueError, match="no scoreable AutoResearchBench gold tasks"):
        module.diagnose_candidate_rerank(
            task_pack=out_dir,
            score_file=score_file,
            selection_ks=(1,),
        )


def test_autoresearchbench_candidate_rerank_diagnostic_rejects_missing_task_id(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "present-task",
                "question": "public present clue",
                "search_type": "deep",
                "answer": ["Present Task Paper"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    score_file.write_text(json.dumps({"metadata": {}, "scores": []}), encoding="utf-8")
    module = load_autoresearchbench_candidate_rerank_script()

    with pytest.raises(ValueError, match="task IDs not found"):
        module.diagnose_candidate_rerank(
            task_pack=out_dir,
            score_file=score_file,
            selection_ks=(1,),
            selected_task_ids=("autoresearchbench.missing-task",),
        )


def test_autoresearchbench_candidate_bm25_cli_writes_score_report(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "arb-candidate-score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "deep-cli-candidate",
                "question": "exact cli paper clue",
                "search_type": "deep",
                "answer": ["Exact CLI Paper"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    candidate_dir = tmp_path / "candidate-source"
    candidate_dir.mkdir()
    (candidate_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    "researchflowbench.autoresearchbench_candidate_source.v0.1"
                ),
                "benchmark_id": "autoresearchbench",
                "records_file": "candidate_corpus.jsonl",
                "gold_label_policy": "no_gold_labels",
                "contains_official_answers": False,
            }
        ),
        encoding="utf-8",
    )
    (candidate_dir / "candidate_corpus.jsonl").write_text(
        json.dumps(
            {
                "paper_id": "cli-match",
                "title": "Exact CLI Paper",
                "abstract": "exact cli paper clue",
                "arxiv_id": "2402.00001",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        [
            "run-external-baseline",
            "--task-pack",
            str(out_dir),
            "--baseline",
            "autoresearchbench_candidate_bm25",
            "--data",
            str(candidate_dir),
            "--out",
            str(score_file),
            "--evidence-state",
            "real_data",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(score_file.read_text(encoding="utf-8"))
    assert payload["baseline_kind"] == "model_free_candidate_retrieval"
    assert payload["scores"][0]["metrics"]["deep_accuracy"] == 1.0


def test_external_prediction_file_scores_autoresearchbench_deep_and_wide(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    prediction_file = tmp_path / "predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "deep-agent",
                "question": "Find the paper about a hidden target system.",
                "search_type": "deep",
                "answer": ["Target System Paper"],
            },
            {
                "id": "wide-agent",
                "question": "Find the 2024 papers about a target family.",
                "search_type": "wide",
                "arxiv_id": ["2401.00001", "2401.00002"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "candidate_model_replay",
                "model_execution_performed": True,
                "execution_limits": {
                    "max_agent_iterations": 5,
                    "max_retrieval_iterations": 5,
                },
                "predictions": [
                    {
                        "task_id": "autoresearchbench.deep-agent",
                        "prediction": {
                            "predicted_titles": ["Target System Paper"],
                            "predicted_arxiv_ids": [],
                        },
                        "runner_output": {"iterations_used": 2},
                    },
                    {
                        "task_id": "autoresearchbench.wide-agent",
                        "prediction": {
                            "predicted_titles": [],
                            "predicted_arxiv_ids": ["2401.00001", "2501.99999"],
                        },
                        "runner_output": {"iterations_used": 3},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_external_task_pack_predictions(
        out_dir,
        prediction_file,
        evidence_state="real_data",
        max_agent_iterations=5,
        max_retrieval_iterations=5,
    )

    report = result.report
    assert report["benchmark_id"] == "autoresearchbench"
    assert report["baseline_id"] == "candidate_model_replay"
    assert report["baseline_kind"] == "external_prediction_file"
    assert report["model_execution_performed"] is True
    assert report["metadata"]["max_agent_iterations"] == 5
    scores = {score["task_id"]: score for score in report["scores"]}
    assert scores["autoresearchbench.deep-agent"]["metrics"]["deep_accuracy"] == 1.0
    assert scores["autoresearchbench.wide-agent"]["metrics"]["wide_iou"] == 0.333333
    assert scores["autoresearchbench.wide-agent"]["metrics"]["wide_recall"] == 0.5
    assert all(score["evidence_state"] == "real_data" for score in report["scores"])


def test_external_prediction_file_blocks_missing_autoresearchbench_prediction(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    prediction_file = tmp_path / "predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "missing-agent",
                "question": "Find one paper.",
                "search_type": "deep",
                "answer": ["Missing Agent Target"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "candidate_model_replay",
                "model_execution_performed": False,
                "predictions": [],
            }
        ),
        encoding="utf-8",
    )

    result = run_external_task_pack_predictions(out_dir, prediction_file)

    score = result.report["scores"][0]
    assert score["evidence_state"] == "blocked_missing_prediction"
    assert score["blockers"] == ["external_prediction_missing"]


def test_external_prediction_file_rejects_missing_contract_fields(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    prediction_file = tmp_path / "predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "missing-contract-field",
                "question": "Find one paper.",
                "search_type": "deep",
                "answer": ["Missing Contract Field Target"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "predictions": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required field: runner_id"):
        run_external_task_pack_predictions(out_dir, prediction_file)


def test_external_prediction_file_blocks_non_object_prediction_payload(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    prediction_file = tmp_path / "predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "bad-prediction-payload",
                "question": "Find one paper.",
                "search_type": "deep",
                "answer": ["Bad Prediction Payload Target"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "candidate_model_replay",
                "model_execution_performed": False,
                "predictions": [
                    {
                        "task_id": "autoresearchbench.bad-prediction-payload",
                        "prediction": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_external_task_pack_predictions(out_dir, prediction_file)

    score = result.report["scores"][0]
    assert score["evidence_state"] == "blocked_invalid_prediction"
    assert score["blockers"] == ["external_prediction_payload_invalid"]


def test_external_prediction_file_scores_selected_autoresearchbench_task_ids(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    prediction_file = tmp_path / "predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "selected-agent",
                "question": "Find selected paper.",
                "search_type": "deep",
                "answer": ["Selected Agent Target"],
            },
            {
                "id": "unselected-agent",
                "question": "Find unselected paper.",
                "search_type": "deep",
                "answer": ["Unselected Agent Target"],
            },
        ]
    ).write_task_pack(out_dir, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "candidate_model_replay",
                "model_execution_performed": False,
                "predictions": [
                    {
                        "task_id": "autoresearchbench.selected-agent",
                        "prediction": {
                            "predicted_titles": ["Selected Agent Target"],
                            "predicted_arxiv_ids": [],
                        },
                        "runner_output": {"iterations_used": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_external_task_pack_predictions(
        out_dir,
        prediction_file,
        task_ids=("autoresearchbench.selected-agent",),
    )

    assert result.report["metadata"]["selected_task_ids"] == [
        "autoresearchbench.selected-agent"
    ]
    assert result.report["metrics"]["score_count"] == 1
    assert result.report["metrics"]["blocked_score_count"] == 0
    assert result.report["scores"][0]["metrics"]["deep_accuracy"] == 1.0


def test_external_prediction_file_rejects_duplicate_autoresearchbench_task_ids(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    prediction_file = tmp_path / "predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "duplicate-agent",
                "question": "Find one paper.",
                "search_type": "deep",
                "answer": ["Duplicate Agent Target"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "candidate_model_replay",
                "model_execution_performed": False,
                "predictions": [
                    {
                        "task_id": "autoresearchbench.duplicate-agent",
                        "prediction": {"predicted_titles": []},
                    },
                    {
                        "task_id": "autoresearchbench.duplicate-agent",
                        "prediction": {"predicted_titles": []},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate external prediction task_id"):
        run_external_task_pack_predictions(out_dir, prediction_file)


def test_external_prediction_file_rejects_over_budget_iterations(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    prediction_file = tmp_path / "predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "iteration-cap",
                "question": "Find one paper.",
                "search_type": "deep",
                "answer": ["Iteration Cap Target"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "candidate_model_replay",
                "model_execution_performed": False,
                "predictions": [
                    {
                        "task_id": "autoresearchbench.iteration-cap",
                        "prediction": {"predicted_titles": ["Iteration Cap Target"]},
                        "runner_output": {"iterations_used": 6},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match="iterations_used exceeds max_agent_iterations"
    ):
        run_external_task_pack_predictions(
            out_dir,
            prediction_file,
            max_agent_iterations=5,
        )
    with pytest.raises(
        ValueError, match="max_agent_iterations must be between 1 and 5"
    ):
        run_external_task_pack_predictions(
            out_dir,
            prediction_file,
            max_agent_iterations=6,
        )


def test_autoresearchbench_agent_runner_writes_predictions_without_gold(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    prediction_file = tmp_path / "predictions.json"
    fake_prediction_file = tmp_path / "fake-predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "gold-blind-agent",
                "question": "Find the paper with public clue only.",
                "search_type": "deep",
                "answer": ["Secret Gold Title Must Stay Hidden"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    fake_prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "fake_agent",
                "model_execution_performed": False,
                "predictions": [
                    {
                        "task_id": "autoresearchbench.gold-blind-agent",
                        "prediction": {
                            "predicted_titles": ["Secret Gold Title Must Stay Hidden"],
                            "predicted_arxiv_ids": [],
                        },
                        "runner_output": {"iterations_used": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with prepare_autoresearchbench_agent_workspace(
        out_dir,
        "autoresearchbench.gold-blind-agent",
    ) as workspace:
        workspace_files = {
            path.relative_to(workspace).as_posix() for path in workspace.rglob("*")
        }
        assert "task/input.json" in workspace_files
        assert "task/gold.json" not in workspace_files
        workspace_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in workspace.rglob("*")
            if path.is_file()
        )
        assert "Secret Gold Title Must Stay Hidden" not in workspace_text

    run_external_task_pack_agent(
        out_dir,
        predictions_file=prediction_file,
        runner_id="fake_agent",
        fake_predictions_file=fake_prediction_file,
        max_agent_iterations=5,
        max_retrieval_iterations=5,
    )

    payload = json.loads(prediction_file.read_text(encoding="utf-8"))
    assert payload["runner_id"] == "fake_agent"
    assert payload["metadata"]["gold_blind_workspace"] is True
    assert payload["model_execution_performed"] is False


def test_autoresearchbench_agent_workspace_copies_candidate_source_without_origin_path(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    candidate_dir = tmp_path / "candidate-source"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "candidate-copy-agent",
                "question": "Find a public candidate only.",
                "search_type": "wide",
                "answer": ["Public Candidate"],
                "arxiv_ids": ["2401.00001"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "public-candidate",
                "title": "Public Candidate",
                "abstract": "visible non-gold metadata",
                "arxiv_id": "2401.00001",
            }
        ],
    )

    with prepare_autoresearchbench_agent_workspace(
        out_dir,
        "autoresearchbench.candidate-copy-agent",
        candidate_source=candidate_dir,
    ) as workspace:
        workspace_files = {
            path.relative_to(workspace).as_posix() for path in workspace.rglob("*")
        }
        workspace_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in workspace.rglob("*")
            if path.is_file()
        )

        assert "candidate_source/candidate_manifest.json" in workspace_files
        assert "candidate_source/candidate_corpus.jsonl" in workspace_files
        assert "candidate_source/path.txt" not in workspace_files
        assert str(candidate_dir) not in workspace_text
        assert "visible non-gold metadata" in workspace_text
        assert "2401.00001" in workspace_text


def test_autoresearchbench_agent_prompt_is_gold_blind(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "prompt-agent",
                "question": "Find the paper with public clue only.",
                "search_type": "deep",
                "answer": ["Secret Prompt Gold"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    task_id = "autoresearchbench.prompt-agent"
    visible = json.loads(
        (out_dir / "tasks" / task_id / "input.json").read_text(encoding="utf-8")
    )

    prompt = build_autoresearchbench_agent_prompt(
        task_id=task_id,
        visible_task=visible,
        max_agent_iterations=5,
        max_retrieval_iterations=5,
    )

    assert "Secret Prompt Gold" not in prompt
    assert str(out_dir / "tasks" / task_id / "gold.json") not in prompt
    assert "answer_titles" not in prompt


def test_autoresearchbench_agent_prompt_requires_candidate_source_trace(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    candidate_dir = tmp_path / "candidate-source"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "prompt-trace-agent",
                "question": "Find the paper with public candidate-source evidence.",
                "search_type": "deep",
                "answer": ["Secret Prompt Trace Gold"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "public-candidate",
                "title": "Visible Public Candidate",
                "abstract": "visible non-gold metadata",
                "arxiv_id": "2401.00001",
            }
        ],
    )
    task_id = "autoresearchbench.prompt-trace-agent"
    visible = json.loads(
        (out_dir / "tasks" / task_id / "input.json").read_text(encoding="utf-8")
    )

    prompt = build_autoresearchbench_agent_prompt(
        task_id=task_id,
        visible_task=visible,
        max_agent_iterations=5,
        max_retrieval_iterations=5,
        candidate_source=candidate_dir,
    )

    assert "candidate_source/" in prompt
    assert "candidate_source_files" in prompt
    assert "candidate_source_used" in prompt
    assert "candidate_ids" in prompt
    assert "retrieval_trace_complete" in prompt
    assert "Secret Prompt Trace Gold" not in prompt
    assert str(out_dir / "tasks" / task_id / "gold.json") not in prompt
    assert str(candidate_dir) not in prompt


def test_autoresearchbench_codex_schema_allows_candidate_source_trace_fields():
    schema = _codex_prediction_schema(candidate_source_available=True)
    trace_properties = schema["properties"]["runner_output"]["properties"][
        "retrieval_trace"
    ]["properties"]

    assert "candidate_source_available" in trace_properties
    assert "candidate_source_used" in trace_properties
    assert "candidate_source_files" in trace_properties
    assert "candidate_ids" in trace_properties
    assert "retrieval_trace_complete" in trace_properties


def test_autoresearchbench_codex_agent_adds_missing_candidate_source_trace(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    candidate_dir = tmp_path / "candidate-source"
    prediction_file = tmp_path / "predictions.json"
    codex_bin = tmp_path / "codex-stub"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "missing-trace-agent",
                "question": "Find one paper using public candidate evidence.",
                "search_type": "deep",
                "answer": ["Secret Missing Trace Gold"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "public-candidate",
                "title": "Visible Public Candidate",
                "abstract": "visible non-gold metadata",
                "arxiv_id": "2401.00001",
            }
        ],
    )
    write_codex_exec_stub(
        codex_bin,
        last_message={
            "prediction": {
                "predicted_titles": ["Visible Public Candidate"],
                "predicted_arxiv_ids": ["2401.00001"],
            },
            "runner_output": {
                "iterations_used": 1,
                "retrieval_iterations_used": 1,
                "retrieval_trace": {},
                "notes": "returned a candidate without trace details",
            },
        },
    )

    run_external_task_pack_agent(
        out_dir,
        predictions_file=prediction_file,
        candidate_source=candidate_dir,
        codex_bin=str(codex_bin),
        max_agent_iterations=5,
        max_retrieval_iterations=5,
        task_timeout_sec=30,
    )

    payload = json.loads(prediction_file.read_text(encoding="utf-8"))
    trace = payload["predictions"][0]["runner_output"]["retrieval_trace"]
    assert trace["candidate_source_available"] is True
    assert trace["candidate_source_used"] is False
    assert trace["candidate_source_files"] == [
        "candidate_manifest.json",
        "candidate_corpus.jsonl",
    ]
    assert trace["candidate_source_schema_version"] == (
        "researchflowbench.autoresearchbench_candidate_source.v0.1"
    )
    assert trace["candidate_source_record_count"] == 1
    assert trace["retrieval_trace_complete"] is False
    assert trace["trace_status"] == "missing_candidate_source_trace"


def test_autoresearchbench_codex_agent_preserves_candidate_source_trace(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    candidate_dir = tmp_path / "candidate-source"
    prediction_file = tmp_path / "predictions.json"
    codex_bin = tmp_path / "codex-stub"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "preserve-trace-agent",
                "question": "Find one paper using public candidate evidence.",
                "search_type": "wide",
                "answer": ["Secret Preserve Trace Gold"],
                "arxiv_id": ["2401.00001"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "public-candidate",
                "title": "Visible Public Candidate",
                "abstract": "visible non-gold metadata",
                "arxiv_id": "2401.00001",
            }
        ],
    )
    write_codex_exec_stub(
        codex_bin,
        last_message={
            "prediction": {
                "predicted_titles": ["Visible Public Candidate"],
                "predicted_arxiv_ids": ["2401.00001"],
            },
            "runner_output": {
                "iterations_used": 1,
                "retrieval_iterations_used": 1,
                "retrieval_trace": {
                    "candidate_source_used": True,
                    "candidate_ids": ["public-candidate"],
                    "retrieval_trace_complete": True,
                    "trace_status": "agent_reported_candidate_source_trace",
                },
                "notes": "inspected candidate_source/candidate_corpus.jsonl",
            },
        },
    )

    run_external_task_pack_agent(
        out_dir,
        predictions_file=prediction_file,
        candidate_source=candidate_dir,
        codex_bin=str(codex_bin),
        max_agent_iterations=5,
        max_retrieval_iterations=5,
        task_timeout_sec=30,
    )

    payload = json.loads(prediction_file.read_text(encoding="utf-8"))
    trace = payload["predictions"][0]["runner_output"]["retrieval_trace"]
    assert trace["candidate_source_available"] is True
    assert trace["candidate_source_used"] is True
    assert trace["candidate_ids"] == ["public-candidate"]
    assert trace["candidate_source_record_count"] == 1
    assert trace["retrieval_trace_complete"] is True
    assert trace["trace_status"] == "agent_reported_candidate_source_trace"


@pytest.mark.skipif(os.name == "nt", reason="process-group cleanup is POSIX-only")
def test_autoresearchbench_codex_agent_timeout_cleans_child_process(
    tmp_path: Path,
):
    out_dir = tmp_path / "external-pack"
    prediction_file = tmp_path / "predictions.json"
    codex_bin = tmp_path / "codex-stub"
    child_pid_file = tmp_path / "child.pid"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "timeout-cleanup-agent",
                "question": "Find one paper slowly.",
                "search_type": "deep",
                "answer": ["Secret Timeout Cleanup Gold"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    write_hanging_codex_exec_stub(codex_bin, child_pid_file=child_pid_file)
    child_pid = 0

    try:
        run_external_task_pack_agent(
            out_dir,
            predictions_file=prediction_file,
            codex_bin=str(codex_bin),
            max_agent_iterations=5,
            max_retrieval_iterations=5,
            task_timeout_sec=3,
        )
        child_pid = wait_for_pid_file(child_pid_file)
        payload = json.loads(prediction_file.read_text(encoding="utf-8"))
        assert payload["predictions"][0]["runner_output"]["error"] == (
            "codex_exec_timeout"
        )

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and process_exists(child_pid):
            time.sleep(0.05)
        assert not process_exists(child_pid)
    finally:
        if child_pid:
            terminate_process(child_pid)


def test_autoresearchbench_external_agent_and_prediction_cli_smoke(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    prediction_file = tmp_path / "predictions.json"
    fake_prediction_file = tmp_path / "fake-predictions.json"
    score_file = tmp_path / "score.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "cli-agent",
                "question": "Find one CLI agent paper.",
                "search_type": "deep",
                "answer": ["CLI Agent Target"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    fake_prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "fake_agent",
                "predictions": [
                    {
                        "task_id": "autoresearchbench.cli-agent",
                        "prediction": {
                            "predicted_titles": ["CLI Agent Target"],
                            "predicted_arxiv_ids": [],
                        },
                        "runner_output": {"iterations_used": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    run_result = runner.invoke(
        researchflowbench_group,
        [
            "run-external-agent",
            "--task-pack",
            str(out_dir),
            "--runner",
            "fake_agent",
            "--fake-predictions",
            str(fake_prediction_file),
            "--predictions-out",
            str(prediction_file),
        ],
    )
    score_result = runner.invoke(
        researchflowbench_group,
        [
            "score-external-predictions",
            "--task-pack",
            str(out_dir),
            "--predictions",
            str(prediction_file),
            "--out",
            str(score_file),
            "--evidence-state",
            "real_data",
        ],
    )

    assert run_result.exit_code == 0, run_result.output
    assert score_result.exit_code == 0, score_result.output
    report = json.loads(score_file.read_text(encoding="utf-8"))
    assert report["baseline_id"] == "fake_agent"
    assert report["scores"][0]["metrics"]["deep_accuracy"] == 1.0


def test_autoresearchbench_full_eval_plan_checks_gold_and_candidate_source(
    tmp_path: Path,
):
    module = load_autoresearchbench_agent_smoke_script()
    task_pack = tmp_path / "external-pack"
    candidate_dir = tmp_path / "candidate-source"
    out_dir = tmp_path / "run"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "full-deep",
                "question": "Find one full-eval deep paper.",
                "search_type": "deep",
                "answer": ["Full Eval Deep Target"],
            },
            {
                "id": "full-wide",
                "question": "Find all full-eval wide papers.",
                "search_type": "wide",
                "arxiv_id": ["2401.00001", "2401.00002"],
            },
        ]
    ).write_task_pack(task_pack, include_gold=True)
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "candidate-full",
                "title": "Full Eval Candidate",
                "abstract": "public non-gold candidate metadata",
                "arxiv_id": "2401.00001",
            }
        ],
    )

    plan = module.build_full_eval_plan(
        task_pack_root=task_pack,
        candidate_source=candidate_dir,
        out_dir=out_dir,
        task_timeout_deep_sec=30,
        task_timeout_wide_sec=90,
        max_agent_iterations=2,
        max_retrieval_iterations=2,
    )

    assert plan["schema_version"] == (
        "researchflowbench.autoresearchbench_full_eval_run.v0.1"
    )
    assert plan["status"] == "ready"
    assert plan["ready_for_full_run"] is True
    assert plan["task_count"] == 2
    assert plan["task_type_counts"] == {"deep": 1, "wide": 1}
    assert plan["gold_file_count"] == 2
    assert plan["candidate_source"]["status"] == "ready"
    assert plan["timeout_policy"] == {"deep": 30, "unknown": 30, "wide": 90}
    assert plan["resume_config"]["status"] == "not_applicable"
    assert plan["pending_task_ids"] == [
        "autoresearchbench.full-deep",
        "autoresearchbench.full-wide",
    ]
    assert plan["output_files"]["predictions"].endswith("predictions.json")
    assert plan["blockers"] == []


def test_autoresearchbench_full_eval_plan_blocks_resume_config_drift(
    tmp_path: Path,
):
    module = load_autoresearchbench_agent_smoke_script()
    task_pack = tmp_path / "external-pack"
    candidate_dir = tmp_path / "candidate-source"
    previous_candidate_dir = tmp_path / "previous-candidate-source"
    out_dir = tmp_path / "run"
    predictions_file = out_dir / "predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "drift-deep",
                "question": "Find one drift deep paper.",
                "search_type": "deep",
                "answer": ["Drift Deep Target"],
            }
        ]
    ).write_task_pack(task_pack, include_gold=True)
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "candidate-current",
                "title": "Drift Deep Target",
                "abstract": "public non-gold candidate metadata",
                "arxiv_id": "2401.00001",
            }
        ],
    )
    write_autoresearchbench_candidate_source_fixture(
        previous_candidate_dir,
        [
            {
                "paper_id": "candidate-previous",
                "title": "Different Candidate",
                "abstract": "public non-gold candidate metadata",
                "arxiv_id": "2401.00002",
            }
        ],
    )
    out_dir.mkdir(parents=True)
    predictions_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "legacy_agent",
                "model_execution_performed": False,
                "metadata": {
                    "resume_config": module._resume_config(
                        candidate_source=previous_candidate_dir,
                        task_timeout_deep_sec=60,
                        task_timeout_wide_sec=90,
                        max_agent_iterations=2,
                        max_retrieval_iterations=2,
                        reasoning_effort="medium",
                        model="previous-model",
                        codex_bin="codex",
                    )
                },
                "predictions": [
                    {
                        "task_id": "autoresearchbench.drift-deep",
                        "prediction": {
                            "predicted_titles": ["Drift Deep Target"],
                            "predicted_arxiv_ids": [],
                        },
                        "runner_output": {"iterations_used": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    plan = module.build_full_eval_plan(
        task_pack_root=task_pack,
        candidate_source=candidate_dir,
        out_dir=out_dir,
        task_timeout_deep_sec=30,
        task_timeout_wide_sec=90,
        max_agent_iterations=2,
        max_retrieval_iterations=2,
        reasoning_effort="low",
        model=None,
    )

    assert plan["status"] == "blocked"
    assert plan["ready_for_full_run"] is False
    assert plan["resume_config"]["status"] == "blocked"
    assert plan["resume_config"]["mismatches"] == [
        "candidate_source",
        "execution_limits",
        "timeout_policy",
    ]
    assert any(
        blocker.startswith("resume_config_incompatible:")
        for blocker in plan["blockers"]
    )


def test_autoresearchbench_full_eval_runner_resumes_and_scores_fake_predictions(
    tmp_path: Path,
):
    module = load_autoresearchbench_agent_smoke_script()
    task_pack = tmp_path / "external-pack"
    candidate_dir = tmp_path / "candidate-source"
    out_dir = tmp_path / "run"
    fake_prediction_file = tmp_path / "fake-predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "resume-deep",
                "question": "Find one resumable deep paper.",
                "search_type": "deep",
                "answer": ["Resumable Deep Target"],
            },
            {
                "id": "resume-wide",
                "question": "Find all resumable wide papers.",
                "search_type": "wide",
                "arxiv_id": ["2401.00001", "2401.00002"],
            },
        ]
    ).write_task_pack(task_pack, include_gold=True)
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "resume-candidate",
                "title": "Resumable Deep Target",
                "abstract": "public non-gold candidate metadata",
                "arxiv_id": "2401.00001",
            }
        ],
    )
    fake_prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "fake_agent",
                "model_execution_performed": False,
                "predictions": [
                    {
                        "task_id": "autoresearchbench.resume-deep",
                        "prediction": {
                            "predicted_titles": ["Resumable Deep Target"],
                            "predicted_arxiv_ids": [],
                        },
                        "runner_output": {
                            "iterations_used": 1,
                            "retrieval_trace": {
                                "trace_status": "missing_candidate_source_trace"
                            },
                        },
                    },
                    {
                        "task_id": "autoresearchbench.resume-wide",
                        "prediction": {
                            "predicted_titles": [],
                            "predicted_arxiv_ids": ["2401.00001"],
                        },
                        "runner_output": {
                            "iterations_used": 1,
                            "retrieval_trace": {
                                "trace_status": "agent_reported_candidate_source_trace"
                            },
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    first = module.run_full_eval(
        task_pack_root=task_pack,
        candidate_source=candidate_dir,
        out_dir=out_dir,
        fake_predictions_file=fake_prediction_file,
        task_ids=("autoresearchbench.resume-deep",),
        task_timeout_deep_sec=30,
        task_timeout_wide_sec=90,
        max_agent_iterations=2,
        max_retrieval_iterations=2,
    )
    second = module.run_full_eval(
        task_pack_root=task_pack,
        candidate_source=candidate_dir,
        out_dir=out_dir,
        fake_predictions_file=fake_prediction_file,
        task_timeout_deep_sec=30,
        task_timeout_wide_sec=90,
        max_agent_iterations=2,
        max_retrieval_iterations=2,
    )

    assert first["completed_task_count"] == 1
    assert first["pending_task_count"] == 0
    assert second["completed_task_count"] == 2
    assert second["pending_task_count"] == 0
    assert second["score_report"]["score_count"] == 2
    assert second["score_report"]["blocked_score_count"] == 0
    predictions = json.loads(
        Path(second["output_files"]["predictions"]).read_text(encoding="utf-8")
    )
    assert predictions["model_execution_performed"] is False
    assert [entry["task_id"] for entry in predictions["predictions"]] == [
        "autoresearchbench.resume-deep",
        "autoresearchbench.resume-wide",
    ]
    diagnostics_by_task = {
        entry["task_id"]: entry["runner_output"]["task_diagnostics"]
        for entry in predictions["predictions"]
    }
    assert (
        diagnostics_by_task["autoresearchbench.resume-deep"]["schema_version"]
        == "researchflowbench.autoresearchbench_task_diagnostics.v0.1"
    )
    assert diagnostics_by_task["autoresearchbench.resume-deep"]["task_type"] == "deep"
    assert diagnostics_by_task["autoresearchbench.resume-deep"]["timeout_sec"] == 30
    assert diagnostics_by_task["autoresearchbench.resume-deep"]["elapsed_sec"] >= 0
    assert (
        diagnostics_by_task["autoresearchbench.resume-deep"][
            "candidate_source_configured"
        ]
        is True
    )
    assert (
        diagnostics_by_task["autoresearchbench.resume-deep"][
            "candidate_source_trace_status"
        ]
        == "missing_candidate_source_trace"
    )
    assert diagnostics_by_task["autoresearchbench.resume-wide"]["task_type"] == "wide"
    assert diagnostics_by_task["autoresearchbench.resume-wide"]["timeout_sec"] == 90
    assert (
        diagnostics_by_task["autoresearchbench.resume-wide"][
            "candidate_source_trace_status"
        ]
        == "agent_reported_candidate_source_trace"
    )
    manifest = json.loads(
        Path(second["output_files"]["run_manifest"]).read_text(encoding="utf-8")
    )
    assert manifest["task_diagnostics"]["task_count"] == 2
    assert manifest["task_diagnostics"]["status_counts"] == {"completed": 2}
    assert manifest["task_diagnostics"]["candidate_source_missing_trace_count"] == 1
    score = json.loads(
        Path(second["output_files"]["score_report"]).read_text(encoding="utf-8")
    )
    assert score["model_execution_performed"] is False
    assert score["scores"][0]["metrics"]["deep_accuracy"] == 1.0
    assert score["scores"][1]["metrics"]["wide_iou"] == 0.5


def test_autoresearchbench_full_eval_runner_backfills_legacy_resume_diagnostics(
    tmp_path: Path,
):
    module = load_autoresearchbench_agent_smoke_script()
    task_pack = tmp_path / "external-pack"
    candidate_dir = tmp_path / "candidate-source"
    out_dir = tmp_path / "run"
    fake_prediction_file = tmp_path / "fake-predictions.json"
    predictions_file = out_dir / "predictions.json"
    AutoResearchBenchAdapter.from_records(
        [
            {
                "id": "legacy-deep",
                "question": "Find one legacy deep paper.",
                "search_type": "deep",
                "answer": ["Legacy Deep Target"],
            },
            {
                "id": "legacy-wide",
                "question": "Find all legacy wide papers.",
                "search_type": "wide",
                "arxiv_id": ["2401.00001", "2401.00002"],
            },
        ]
    ).write_task_pack(task_pack, include_gold=True)
    write_autoresearchbench_candidate_source_fixture(
        candidate_dir,
        [
            {
                "paper_id": "legacy-candidate",
                "title": "Legacy Deep Target",
                "abstract": "public non-gold candidate metadata",
                "arxiv_id": "2401.00001",
            }
        ],
    )
    out_dir.mkdir(parents=True)
    predictions_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "legacy_agent",
                "model_execution_performed": False,
                "metadata": {
                    "resume_config": module._resume_config(
                        candidate_source=candidate_dir,
                        task_timeout_deep_sec=30,
                        task_timeout_wide_sec=90,
                        max_agent_iterations=2,
                        max_retrieval_iterations=2,
                        reasoning_effort="low",
                        model=None,
                        codex_bin="codex",
                    )
                },
                "predictions": [
                    {
                        "task_id": "autoresearchbench.legacy-deep",
                        "prediction": {
                            "predicted_titles": ["Legacy Deep Target"],
                            "predicted_arxiv_ids": [],
                        },
                        "runner_output": {
                            "iterations_used": 1,
                            "retrieval_trace": {
                                "trace_status": "missing_candidate_source_trace"
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fake_prediction_file.write_text(
        json.dumps(
            {
                "schema_version": "researchflowbench.external_predictions.v0.1",
                "benchmark_id": "autoresearchbench",
                "runner_id": "fake_agent",
                "model_execution_performed": False,
                "predictions": [
                    {
                        "task_id": "autoresearchbench.legacy-wide",
                        "prediction": {
                            "predicted_titles": [],
                            "predicted_arxiv_ids": ["2401.00001"],
                        },
                        "runner_output": {
                            "iterations_used": 1,
                            "retrieval_trace": {
                                "trace_status": "agent_reported_candidate_source_trace"
                            },
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = module.run_full_eval(
        task_pack_root=task_pack,
        candidate_source=candidate_dir,
        out_dir=out_dir,
        fake_predictions_file=fake_prediction_file,
        task_timeout_deep_sec=30,
        task_timeout_wide_sec=90,
        max_agent_iterations=2,
        max_retrieval_iterations=2,
    )

    assert result["completed_task_count"] == 2
    predictions = json.loads(predictions_file.read_text(encoding="utf-8"))
    diagnostics_by_task = {
        entry["task_id"]: entry["runner_output"]["task_diagnostics"]
        for entry in predictions["predictions"]
    }
    assert diagnostics_by_task["autoresearchbench.legacy-deep"]["task_type"] == "deep"
    assert diagnostics_by_task["autoresearchbench.legacy-deep"]["timeout_sec"] == 30
    assert (
        diagnostics_by_task["autoresearchbench.legacy-deep"][
            "candidate_source_trace_status"
        ]
        == "missing_candidate_source_trace"
    )
    assert diagnostics_by_task["autoresearchbench.legacy-wide"]["task_type"] == "wide"
    manifest = json.loads(
        Path(result["output_files"]["run_manifest"]).read_text(encoding="utf-8")
    )
    assert manifest["task_diagnostics"]["task_count"] == 2
    assert manifest["task_diagnostics"]["status_counts"] == {"completed": 2}
    assert manifest["task_diagnostics"]["candidate_source_missing_trace_count"] == 1


def test_autoresearchbench_candidate_source_builder_writes_non_gold_jsonl(
    tmp_path: Path,
):
    metadata_file = tmp_path / "papers.jsonl"
    out_dir = tmp_path / "candidate-source"
    metadata_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "p1",
                        "title": "Exact Candidate Paper",
                        "abstract": "retrieval clue for exact candidate",
                        "arxiv_id": "arxiv:2401.00001",
                        "doi": "10.1000/example",
                        "extra_provider_field": "ignored",
                    }
                ),
                json.dumps({"id": "empty", "title": "", "abstract": ""}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = build_autoresearchbench_candidate_source(
        metadata_file,
        out_dir,
        source_kind="metadata_jsonl",
    )

    corpus_records = [
        json.loads(line)
        for line in (out_dir / "candidate_corpus.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert manifest["schema_version"] == (
        "researchflowbench.autoresearchbench_candidate_source.v0.1"
    )
    assert manifest["records_file"] == "candidate_corpus.jsonl"
    assert manifest["gold_label_policy"] == "no_gold_labels"
    assert manifest["contains_official_answers"] is False
    assert manifest["record_count"] == 1
    assert manifest["skipped_record_count"] == 1
    assert corpus_records == [
        {
            "paper_id": "p1",
            "title": "Exact Candidate Paper",
            "abstract": "retrieval clue for exact candidate",
            "arxiv_id": "2401.00001",
            "doi": "10.1000/example",
        }
    ]


def test_autoresearchbench_candidate_source_builder_extracts_public_arxiv_id(
    tmp_path: Path,
):
    metadata_file = tmp_path / "papers.jsonl"
    out_dir = tmp_path / "candidate-source"
    metadata_file.write_text(
        json.dumps(
            {
                "id": "https://openalex.org/W123",
                "title": "OpenAlex Candidate Paper",
                "abstract": "retrieval clue from public metadata",
                "doi": "https://doi.org/10.48550/arXiv.2406.17153",
                "url": "https://arxiv.org/abs/2406.17153v2",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    build_autoresearchbench_candidate_source(
        metadata_file,
        out_dir,
        source_kind="metadata_jsonl",
    )

    corpus_record = json.loads(
        (out_dir / "candidate_corpus.jsonl").read_text(encoding="utf-8")
    )
    assert corpus_record["arxiv_id"] == "2406.17153"


def test_autoresearchbench_candidate_source_builder_uniquifies_duplicate_ids(
    tmp_path: Path,
):
    metadata_file = tmp_path / "papers.jsonl"
    out_dir = tmp_path / "candidate-source"
    metadata_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "duplicate-id",
                        "title": "First Candidate Paper",
                        "abstract": "first retrieval clue",
                    }
                ),
                json.dumps(
                    {
                        "id": "duplicate-id",
                        "title": "Second Candidate Paper",
                        "abstract": "second retrieval clue",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = build_autoresearchbench_candidate_source(
        metadata_file,
        out_dir,
        source_kind="metadata_jsonl",
    )

    corpus_records = [
        json.loads(line)
        for line in (out_dir / "candidate_corpus.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    paper_ids = [record["paper_id"] for record in corpus_records]
    assert manifest["record_count"] == 2
    assert manifest["duplicate_paper_id_count"] == 1
    assert len(set(paper_ids)) == 2
    assert paper_ids[0] == "duplicate-id"
    assert paper_ids[1].startswith("duplicate-id#")


def test_autoresearchbench_candidate_source_builder_rejects_gold_fields(
    tmp_path: Path,
):
    metadata_file = tmp_path / "papers.jsonl"
    metadata_file.write_text(
        json.dumps(
            {
                "paper_id": "leaky",
                "title": "Leaky paper",
                "abstract": "metadata",
                "answer_titles": ["Leaky paper"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="gold label fields"):
        build_autoresearchbench_candidate_source(
            metadata_file,
            tmp_path / "candidate-source",
            source_kind="metadata_jsonl",
        )


def test_autoresearchbench_candidate_source_builder_rejects_invalid_limit(
    tmp_path: Path,
):
    metadata_file = tmp_path / "papers.jsonl"
    metadata_file.write_text(
        json.dumps({"paper_id": "p1", "title": "Paper", "abstract": "metadata"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="limit must be positive"):
        build_autoresearchbench_candidate_source(
            metadata_file,
            tmp_path / "candidate-source",
            limit=0,
        )


def test_autoresearchbench_candidate_source_cli_builds_from_paper_db(
    tmp_path: Path,
):
    db_path = tmp_path / "pool.db"
    out_dir = tmp_path / "candidate-source"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            arxiv_id TEXT,
            doi TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO papers (id, title, abstract, arxiv_id, doi)
        VALUES (7, 'DB Candidate Paper', 'db retrieval clue', 'arxiv:2402.00002', '')
        """
    )
    conn.commit()
    conn.close()
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        [
            "build-autoresearchbench-candidate-source",
            "--paper-db",
            str(db_path),
            "--out",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    manifest = json.loads((out_dir / "candidate_manifest.json").read_text())
    corpus = [
        json.loads(line)
        for line in (out_dir / "candidate_corpus.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert manifest["source_type"] == "research_harness_paper_db"
    assert manifest["record_count"] == 1
    assert corpus[0]["paper_id"] == "7"
    assert corpus[0]["title"] == "DB Candidate Paper"


def test_external_primitive_cli_writes_score_report(tmp_path: Path):
    data_dir = tmp_path / "litsearch"
    corpus_file = data_dir / "corpus_clean" / "corpus.jsonl"
    corpus_file.parent.mkdir(parents=True)
    corpus_file.write_text(
        json.dumps(
            {
                "corpusid": 101,
                "title": "Scientific discovery systems",
                "abstract": "Dense retrieval for literature search.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "primitive-score.json"
    LitSearchAdapter.from_records(
        [
            {
                "query_id": "qprimitive-cli",
                "query": "dense retrieval",
                "gold_paper_ids": ["101"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        [
            "run-external-primitive",
            "--task-pack",
            str(out_dir),
            "--data",
            str(data_dir),
            "--out",
            str(score_file),
            "--evidence-state",
            "real_data",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(score_file.read_text(encoding="utf-8"))
    assert payload["baseline_kind"] == "rh_primitive_replay"
    assert payload["scores"][0]["metrics"]["retrieval_recall"] == 1.0


def test_failure_attribution_groups_external_scores_by_rh_axis():
    report = {
        "benchmark_id": "litsearch",
        "split": "mutate_dev",
        "model_execution_performed": False,
        "scores": [
            {
                "task_id": "litsearch.q1",
                "metrics": {"retrieval_recall": 0.0, "rerank_quality": 0.0},
                "rh_axis_ids": ["paper_search.recall", "paper_search.rerank_quality"],
                "evidence_state": "fixture_only",
            },
            {
                "task_id": "litsearch.q2",
                "metrics": {},
                "rh_axis_ids": ["paper_search.recall"],
                "evidence_state": "blocked_missing_local_gold",
                "blockers": ["external_gold_file_missing"],
            },
        ],
    }

    attribution = attribute_score_report_failures(report)

    assert attribution["benchmark_id"] == "litsearch"
    assert attribution["evidence_state"] == "blocked_mixed"
    assert attribution["automatic_mutation_enabled"] is False
    by_axis = {item["rh_axis_id"]: item for item in attribution["axis_attribution"]}
    assert by_axis["paper_search.recall"]["failure_count"] == 2
    assert by_axis["paper_search.recall"]["metric_means"]["retrieval_recall"] == 0.0
    assert attribution["blockers"] == ["external_gold_file_missing"]


def test_failure_attribution_applies_default_evidence_state_to_axis_counts():
    report = {
        "benchmark_id": "researchflowbench.synthetic_public_pilot20_v0",
        "split": "draft_dev",
        "model_execution_performed": False,
        "scores": [
            {
                "task_id": "rfb.synthetic.example.0001",
                "metrics": {"combined_score": 0.0},
                "rh_axis_ids": ["retrieval.provenance_coverage"],
            },
        ],
    }

    attribution = attribute_score_report_failures(
        report,
        evidence_state="synthetic_public",
    )

    by_axis = {item["rh_axis_id"]: item for item in attribution["axis_attribution"]}
    assert attribution["evidence_state_counts"] == {"synthetic_public": 1}
    assert by_axis["retrieval.provenance_coverage"]["evidence_state_counts"] == {
        "synthetic_public": 1
    }


def test_failure_attribution_treats_zero_combined_score_as_failure():
    report = {
        "benchmark_id": "researchflowbench.synthetic_public_pilot20_v0",
        "split": "draft_dev",
        "model_execution_performed": False,
        "scores": [
            {
                "task_id": "rfb.synthetic.visible-contract.0001",
                "metrics": {
                    "combined_score": 0.0,
                    "expected_object_coverage": 0.5,
                },
                "rh_axis_ids": ["citation.candidate_generation"],
                "evidence_state": "synthetic_public",
            },
        ],
    }

    attribution = attribute_score_report_failures(report)

    by_axis = {item["rh_axis_id"]: item for item in attribution["axis_attribution"]}
    assert by_axis["citation.candidate_generation"]["failure_count"] == 1


def test_score_comparison_gate_passes_candidate_improvements():
    baseline = {
        "benchmark_id": "litsearch",
        "baseline_id": "bm25_retrieval",
        "metrics": {
            "blocked_score_count": 0,
            "mean_retrieval_recall": 0.56,
            "mean_rerank_quality": 0.33,
        },
    }
    candidate = {
        "benchmark_id": "litsearch",
        "runner_id": "paper_search_local_bm25",
        "metrics": {
            "blocked_score_count": 0,
            "mean_retrieval_recall": 0.58,
            "mean_rerank_quality": 0.35,
        },
    }

    gate = compare_score_reports(
        baseline,
        candidate,
        required_metrics=("mean_retrieval_recall", "mean_rerank_quality"),
        min_deltas={"mean_retrieval_recall": 0.0},
    )

    assert gate["status"] == "pass"
    assert gate["candidate_id"] == "paper_search_local_bm25"
    assert gate["blockers"] == []
    deltas = {item["metric"]: item["delta"] for item in gate["metric_comparisons"]}
    assert deltas["mean_retrieval_recall"] == 0.02


def test_score_comparison_gate_blocks_metric_regression():
    baseline = {
        "benchmark_id": "litsearch",
        "baseline_id": "bm25_retrieval",
        "metrics": {"blocked_score_count": 0, "mean_retrieval_recall": 0.56},
    }
    candidate = {
        "benchmark_id": "litsearch",
        "runner_id": "paper_search_local_bm25",
        "metrics": {"blocked_score_count": 0, "mean_retrieval_recall": 0.55},
    }

    gate = compare_score_reports(
        baseline,
        candidate,
        required_metrics=("mean_retrieval_recall",),
    )

    assert gate["status"] == "fail"
    assert gate["blockers"] == ["metric_regression:mean_retrieval_recall"]


def test_score_comparison_cli_writes_gate_report(tmp_path: Path):
    baseline_file = tmp_path / "baseline.json"
    candidate_file = tmp_path / "candidate.json"
    gate_file = tmp_path / "gate.json"
    baseline_file.write_text(
        json.dumps(
            {
                "benchmark_id": "litsearch",
                "baseline_id": "bm25_retrieval",
                "metrics": {"blocked_score_count": 0, "mean_retrieval_recall": 0.56},
            }
        ),
        encoding="utf-8",
    )
    candidate_file.write_text(
        json.dumps(
            {
                "benchmark_id": "litsearch",
                "runner_id": "paper_search_local_bm25",
                "metrics": {"blocked_score_count": 0, "mean_retrieval_recall": 0.58},
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        [
            "compare-score-reports",
            "--baseline-file",
            str(baseline_file),
            "--candidate-file",
            str(candidate_file),
            "--out",
            str(gate_file),
            "--metric",
            "mean_retrieval_recall",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(gate_file.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["candidate_id"] == "paper_search_local_bm25"


def test_failure_attribution_cli_writes_report(tmp_path: Path):
    out_dir = tmp_path / "external-pack"
    score_file = tmp_path / "score.json"
    attribution_file = tmp_path / "attribution.json"
    LitSearchAdapter.from_records(
        [
            {
                "query_id": "qattr",
                "query": "find neural retrieval papers",
                "gold_paper_ids": ["p1"],
            }
        ]
    ).write_task_pack(out_dir, include_gold=True)
    baseline = run_external_task_pack_baseline(out_dir)
    score_file.write_text(json.dumps(baseline.report), encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        [
            "attribute-score-report",
            "--score-file",
            str(score_file),
            "--out",
            str(attribution_file),
            "--evidence-state",
            "fixture_only",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(attribution_file.read_text(encoding="utf-8"))
    assert payload["benchmark_id"] == "litsearch"
    assert payload["axis_attribution"]


def test_autoresearchbench_adapter_cli_writes_manifest(tmp_path: Path):
    data_dir = tmp_path / "autoresearchbench"
    data_dir.mkdir()
    (data_dir / "AutoResearchBench.jsonl").write_text(
        json.dumps(
            {
                "id": "deep-cli",
                "question": "Find the exact paper title.",
                "search_type": "deep",
                "answer": ["Exact Paper Title"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out-arb"
    runner = CliRunner()

    result = runner.invoke(
        researchflowbench_group,
        [
            "adapt-autoresearchbench",
            "--data",
            str(data_dir),
            "--out",
            str(out_dir),
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    manifest = json.loads((out_dir / "adapter_manifest.json").read_text("utf-8"))
    assert manifest["benchmark_id"] == "autoresearchbench"
    assert manifest["task_ids"] == ["autoresearchbench.deep-cli"]


def test_top_level_external_benchmarks_cli_honors_json_flag(runner, tmp_path: Path):
    result = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "external-benchmarks",
            "--out",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "researchflowbench.external_benchmarks.v0.1"
    assert payload["recommended_p0_ids"] == ["autoresearchbench", "litsearch"]
    assert payload["export"]["benchmark_count"] == payload["benchmark_count"]


def test_top_level_local_data_registry_cli_honors_json_flag(runner):
    result = runner.invoke(
        main,
        [
            "--json",
            "researchflowbench",
            "local-data-registry",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "researchflowbench.local_benchmark_data.v0.1"
    assert payload["policy"]["root_env"] == "RESEARCH_HARNESS_BENCHMARK_DATA"
    assert {record["benchmark_id"] for record in payload["benchmarks"]} == {
        "autoresearchbench",
        "litsearch",
    }
